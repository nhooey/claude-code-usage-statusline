// The Node edges of claude_calib.ts: the projects glob, the scan's
// per-file cache and the calibration cache, over node:fs.
//
// claude_calib.ts is pure, so the mod, which runs with no Node, can import
// it; the mod reads the same files through `$` in its own handlers.  This
// is the Node reading, for the tests, the tools and anything else run by
// Node, with the Python's names.  Everything claude_calib.ts exports is
// exported from here too, so a Node caller imports one module.
import * as fs from "node:fs";
import * as crypto from "node:crypto";
import { isDict, pyGet, pyHas } from "./py.ts";
import { expandUser, pyJsonLoads } from "./sources_node.ts";
import { cmpStr, pyJoin } from "./claude_records.ts";
import { writeAtomic } from "./claude_records_node.ts";
import { statePath } from "./state.ts";
import {
  _calibCacheText, _calibrationCacheName, _calibrationOf, _idKey,
  _pricedRecord, _windowCostsFiles, _windowCostsOf, _windowCostsText,
  _windowsKey, _windowStarts, CALIB_TTL, COST_SAVE_EVERY_S, COST_TAIL_BYTES,
} from "./claude_calib.ts";
import type {
  Calib, CostKept, Naive, Priced, Snapshot,
} from "./claude_calib.ts";
import type { Dict } from "./py.ts";

export * from "./claude_calib.ts";

/** Where the scan and the calibration cache read and write, and the clock
 * the cache's age is read against: the Python's module globals and
 * environment, as arguments. */
export interface CalibEnv {
  readonly projectsDir: string;   // ~/.claude/projects
  readonly stateDir: string;      // the private state directory
  readonly now: number;           // time.time()
  // CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE, for planted fixtures.
  readonly calibCacheOverride?: string;
  // The files the scan visits, in order; projectFiles by default.
  readonly glob?: (projectsDir: string) => string[];
  // time.monotonic(), for the saves a long scan makes as it goes.
  readonly monotonic?: () => number;
}

/** os.path.split's head: the path up to its last slash, trailing slashes
 * dropped unless that is all it is. */
function splitHead(p: string): string {
  const head = p.slice(0, p.lastIndexOf("/") + 1);
  return head && !/^\/+$/.test(head) ? head.replace(/\/+$/, "") : head;
}

/** os.scandir's names in `dir`, in the directory's own order (which
 * opendir keeps and readdirSync would sort), with whether each is a
 * directory, symlinks followed; nothing for a directory that will not
 * open. */
function scandir(dir: string): [string, boolean][] {
  const out: [string, boolean][] = [];
  let d: fs.Dir;
  try {
    d = fs.opendirSync(dir || ".");
  } catch {
    return out;
  }
  try {
    for (let e = d.readSync(); e !== null; e = d.readSync()) {
      let isDir = e.isDirectory();
      if (e.isSymbolicLink()) {
        try {
          isDir = fs.statSync(pyJoin(dir, e.name)).isDirectory();
        } catch {
          isDir = false;
        }
      }
      out.push([e.name, isDir]);
    }
  } catch {
    // A directory that fails mid-listing ends there, as scandir's does.
  } finally {
    d.closeSync();
  }
  return out;
}

/** glob's `*` within one directory: names not starting with a dot. */
function glob1(dir: string, match: RegExp, dironly: boolean): string[] {
  return scandir(dir).filter(([n, isDir]) => (!dironly || isDir) &&
    !n.startsWith(".") && match.test(n)).map(([n]) => n);
}

/** glob's `**`: "" for `dir` itself, then every directory under it, depth
 * first, in listing order, hidden ones skipped and not descended. */
function rlistdir(dir: string): string[] {
  const out: string[] = [];
  for (const [n] of scandir(dir).filter(([, d]) => d)) {
    if (n.startsWith(".")) continue;
    out.push(n);
    for (const y of rlistdir(pyJoin(dir, n))) out.push(pyJoin(n, y));
  }
  return out;
}

const ANY = /^[\s\S]*$/;
const JSONL = /^[\s\S]*\.jsonl$/;
const AGENT = /^agent-[\s\S]*\.jsonl$/;

/** Every main and agent transcript under the projects directory, as
 * glob.glob finds `<dir>/*\/*.jsonl` and then, recursively,
 * `<dir>/*\/*\/subagents/**\/agent-*.jsonl`: paths spelt as it spells them,
 * in the order it visits them. */
export function projectFiles(projectsDir: string): string[] {
  const base = splitHead(pyJoin(projectsDir, "*"));
  const out: string[] = [];
  const projects = glob1(base, ANY, true).map((n) => pyJoin(base, n));
  for (const p of projects) {
    for (const n of glob1(p, JSONL, false)) out.push(pyJoin(p, n));
  }
  for (const p of projects) {
    for (const s of glob1(p, ANY, true)) {
      const sub = pyJoin(pyJoin(p, s), "subagents");
      try {
        fs.lstatSync(sub);
      } catch {
        continue;
      }
      for (const r of ["", ...rlistdir(sub)]) {
        const d = pyJoin(sub, r);
        for (const n of glob1(d, AGENT, false)) out.push(pyJoin(d, n));
      }
    }
  }
  return out;
}

/** os.path.getmtime as a float of seconds, as Python builds it from the
 * nanosecond stamp, or null where it raises. */
export function _mtime(path: string): number | null {
  try {
    const ns = fs.statSync(path, { bigint: true }).mtimeNs;
    const s = ns / 1000000000n, rem = ns % 1000000000n;
    // Python truncates toward zero and adds the remainder; so does BigInt.
    return Number(s) + Number(rem) * 1e-9;
  } catch {
    return null;
  }
}

/** A digest of the COST_TAIL_BYTES before `off`, or null past the end. */
export function _tailDigest(fd: number, off: unknown): string | null {
  if (typeof off !== "number" || !Number.isInteger(off) || off < 0) {
    return null;
  }
  const start = Math.max(0, off - COST_TAIL_BYTES);
  const buf = new Uint8Array(off - start);
  let got = 0;
  while (got < buf.length) {
    const n = fs.readSync(fd, buf, got, buf.length - got, start + got);
    if (n === 0) break;
    got += n;
  }
  if (got !== buf.length) return null;
  return crypto.createHash("sha256").update(buf).digest("hex");
}

/** Each line of the file from `off` on, as a binary file iterates: up to
 * and including its "\n", the last one without.  Read in chunks, since a
 * cold scan reads hundreds of megabytes. */
function* linesFrom(fd: number, off: number): Generator<Uint8Array> {
  const CHUNK = 1 << 20;
  let carry = new Uint8Array(0), pos = off;
  for (;;) {
    const buf = new Uint8Array(CHUNK);
    const n = fs.readSync(fd, buf, 0, CHUNK, pos);
    if (n === 0) break;
    pos += n;
    let data = buf.subarray(0, n);
    if (carry.length) {
      const joined = new Uint8Array(carry.length + n);
      joined.set(carry);
      joined.set(data, carry.length);
      data = joined;
    }
    let s = 0;
    for (let e = data.indexOf(10, s); e >= 0; e = data.indexOf(10, s)) {
      yield data.subarray(s, e + 1);
      s = e + 1;
    }
    carry = data.slice(s);
  }
  if (carry.length) yield carry;
}

type Kept = CostKept;

/** Every scanned file's priced records, kept from one scan to the next.
 *
 * A transcript is only appended to, so what a file held at the last scan
 * is still at its head, and only the lines after it need reading.  Kept
 * per file: the offset of the last complete line read, a digest of the
 * bytes before it, and the records up to it; a file that shrank, or whose
 * bytes before the offset changed, is read again from the start.  Within
 * one file a request id after its first record is dropped as it is read.
 * A last line with no newline yet is billed if it parses, but not kept.
 *
 * The one file spec/state.jsonc's window-costs kind names, which the
 * Python and the mod read and write too, in `_windowCostsText`'s bytes. */
export class _CostCache {
  readonly path: string;
  kept: Record<string, Kept> = {};
  keep: Record<string, Kept> = {};
  dirty = false;

  constructor(stateDir: string) {
    this.path = statePath(stateDir, "window-costs");
    try {
      this.kept = _windowCostsFiles(new TextDecoder("utf-8", { fatal: true })
        .decode(fs.readFileSync(this.path))) ?? {};
    } catch {
      // No cache yet: read everything.
    }
  }

  records(path: string): Priced[] {
    let fd: number;
    try {
      fd = fs.openSync(path, "r");
      if (fs.fstatSync(fd).isDirectory()) {
        fs.closeSync(fd);
        return [];
      }
    } catch {
      return [];
    }
    let recs: Priced[], seen: Set<string>, partial: Priced | null = null;
    try {
      const got = Object.hasOwn(this.kept, path) ? this.kept[path] : null;
      let off = 0, reused = false;
      recs = [];
      if (isDict(got) &&
          _tailDigest(fd, pyGet(got, "off", -1)) === pyGet(got, "tail")) {
        [off, recs, reused] = [got.off, got.recs, true];
      }
      const fresh: Priced[] = [];
      seen = new Set(recs.map(([, k]) => _idKey(k)));
      for (const line of linesFrom(fd, off)) {
        if (line[line.length - 1] !== 10) {
          partial = _pricedRecord(line);
          break;
        }
        off += line.length;
        const rec = _pricedRecord(line);
        if (rec === null) continue;
        const key = _idKey(rec[1]);
        if (seen.has(key)) continue;
        seen.add(key);
        fresh.push(rec);
      }
      if (fresh.length || !reused || pyGet(got, "off") !== off) {
        recs = [...recs, ...fresh];
        this.dirty = true;
      }
      this.keep[path] = { off, tail: _tailDigest(fd, off), recs };
    } finally {
      fs.closeSync(fd);
    }
    if (partial !== null && !seen.has(_idKey(partial[1]))) {
      return [...recs, partial];
    }
    return recs;
  }

  /** Write the cache back if it changed.  A save before the scan has
   * finished keeps the files it has not reached yet; the final one drops
   * every file this scan did not read, which has aged out. */
  save(final = true): void {
    const same = (a: object, b: object) => {
      const x = Object.keys(a).sort(cmpStr), y = Object.keys(b).sort(cmpStr);
      return x.length === y.length && x.every((k, i) => k === y[i]);
    };
    if (final && !(this.dirty || !same(this.kept, this.keep))) return;
    if (!final && !this.dirty) return;
    const files = final ? this.keep : { ...this.kept, ...this.keep };
    let text: string;
    try {
      text = _windowCostsText(files);
    } catch {
      return;
    }
    if (writeAtomic(this.path, text)) this.dirty = false;
  }
}

/** Total spend on this machine since each window opened: the scan, over
 * every transcript under the projects directory, through the cost cache,
 * saved every COST_SAVE_EVERY_S while it fills so a scan killed part way
 * leaves the next one only the files it had not reached. */
export function _windowCosts(sessStart: Naive | null,
  weekStart: Naive | null, env: CalibEnv): [number, number] {
  const files = (env.glob ?? projectFiles)(env.projectsDir);
  const cache = new _CostCache(env.stateDir);
  const monotonic = env.monotonic ?? (() => performance.now() / 1000);
  let saved = monotonic();
  const tick = () => {
    if (monotonic() - saved > COST_SAVE_EVERY_S) {
      cache.save(false);
      saved = monotonic();
    }
  };
  const out = _windowCostsOf(sessStart, weekStart, files, _mtime,
    (fp) => cache.records(fp), tick);
  cache.save();
  return out;
}

/** The calibration cache: the override when one is set, else the file
 * for the snapshot's scope that the Python and the mod share. */
export function calibrationCachePath(snap: Snapshot, env: CalibEnv): string {
  if (env.calibCacheOverride) return expandUser(env.calibCacheOverride);
  return pyJoin(env.stateDir, _calibrationCacheName(snap));
}

/** The cached scan, if it is younger than `ttl` seconds (any age for a
 * null `ttl`) AND measured over these windows, with the readings it was
 * taken with.  A dict with no "windows" is a planted fixture, returned as
 * it is. */
export function _readCalibCache(windows: string, snap: Snapshot,
  env: CalibEnv, ttl: number | null = CALIB_TTL): Dict | null {
  const path = calibrationCachePath(snap, env);
  let d: unknown;
  try {
    if (ttl !== null) {
      const mt = _mtime(path);
      if (mt === null || mt <= env.now - ttl) return null;
    }
    d = pyJsonLoads(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true })
      .decode(fs.readFileSync(path)));
  } catch {
    return null;
  }
  if (!isDict(d)) return null;
  if (!pyHas(d, "windows")) return d;
  if (pyGet(d, "windows") !== windows) return null;
  // An entry with no reading to pair the scan with is a miss.
  return pyHas(d, "sess_pct") ? d : null;
}

/** The scan, and the two readings it was SIMULTANEOUS with. */
export function _writeCalibCache(windows: string, snap: Snapshot,
  env: CalibEnv, sc: number, wc: number, sp: unknown, wp: unknown): void {
  let text: string;
  try {
    text = _calibCacheText(windows, sc, wc, sp, wp);
  } catch {
    return;
  }
  writeAtomic(calibrationCachePath(snap, env), text);
}

/** Dollars per one percent of each plan window.
 *
 *     $/1%          = (cost of everything in the window) / (percent used)
 *     prompt share  = prompt cost / $/1%
 *
 * What is cached is the scan, with the reading it was taken with, keyed by
 * the windows it was measured over; the division happens fresh on every
 * call.  `scan` false never runs the scan: it takes the cached one for
 * these windows however old, and with none returns no units.  Throws where
 * the Python raises, which its callers draw as "?". */
export function calibration(snap: Snapshot, env: CalibEnv,
  scan = true): Calib {
  const [ss, ws] = _windowStarts(snap);
  const windows = _windowsKey(ss, ws);
  let cached = _readCalibCache(windows, snap, env);
  if (cached === null && !scan) {
    cached = _readCalibCache(windows, snap, env, null);
  }
  const run = (ss === null && ws === null) || !scan ? null : () => {
    const [sc, wc] = _windowCosts(ss, ws, env);
    _writeCalibCache(windows, snap, env, sc, wc,
      pyGet(snap, "session_pct"), pyGet(snap, "weekly_pct"));
    return [sc, wc] as [number, number];
  };
  return _calibrationOf(snap, cached, run);
}
