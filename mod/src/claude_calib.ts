// The plan-window shares and their calibration, from claude.py.
//
// claude.py is the Claude CLI's orchestration and rendering as well as its
// accounting; this is the accounting part of it: what a turn, a session
// and the machine spent inside each plan window, and the dollars per point
// of plan reading that turn a spend into a share.  Each function keeps its
// Python name in camelCase (`_window_costs` is `_windowCosts`), so a change
// to one names the place to change in the other.
//
// The Python reads three things from module state that are arguments here:
// the plan snapshot (`limits_snapshot()`, `snap`), the clock, and where the
// files are (`CalibEnv`).  The I/O is at the bottom, under "The edges": the
// projects glob, the scan's per-file cache and the calibration cache.  Every
// function above that line is pure.
//
// What does not carry over from Python by itself, decided once:
//
//   - Time.  The window boundaries are NAIVE LOCAL datetimes in the Python,
//     compared as wall-clock times and turned into instants by
//     datetime.timestamp(), which has its own answer for a time in a DST gap
//     or fold.  A `Naive` here is that wall-clock time as seconds counted as
//     if it were UTC, and `_naiveTimestamp` is the Python's search for the
//     instant, step for step.  Both read the process's TZ, as the Python's
//     localtime does.
//   - Keys.  The scan dedupes request ids in Python sets, where 1, 1.0 and
//     True are one key and a list is no key at all (TypeError).  `_idKey`
//     spells that out.  json.loads hands back ONE NaN object for every NaN
//     it reads, so every NaN id is the same key, by identity.  An integer
//     id past 2**53 loses its precision, as everywhere in the ports.
//   - Crashes.  A malformed record the scan cannot price (a message that is
//     not an object, a token count that is a string) raises in the Python
//     and takes the whole calibration with it; its callers draw "?".  The
//     port throws there too, since carrying on would print a figure where
//     the Python prints none.  A count too large for a float, which raises
//     OverflowError in Python, is Infinity here.
//   - Rounding.  `round` rounds half to even; see `_pyRound`.
//   - Sums.  Left to right, as 3.9's sum() adds; 3.12's compensates.
//   - Caches.  The Python keys its caches by a digest of its own source;
//     these are keyed by the mod's version and named apart, so the two never
//     serve each other a scan.
//   - File order.  The scan visits files in the order the directory lists
//     them, which is the filesystem's, as glob.glob does.  A request id in
//     two files is billed at the first, so the order can matter; the shared
//     cases hand the Python's order in through `CalibEnv.glob`.

import * as fs from "node:fs";
import * as crypto from "node:crypto";
import { STAMP_FMT } from "./spec.ts";
import type { Dict } from "./py.ts";
import {
  isDict, pyAsciiDigits, pyGet, pyHas, pyOr, PY_SPACE, pyTruthy,
} from "./py.ts";
import { expandUser, pyFloat, pyJsonDumps, pyJsonLoads } from "./sources.ts";
import {
  _price, cmpStr, pyJoin, pyStr, tsEpoch, writeAtomic,
} from "./claude_records.ts";
import type { Turn } from "./claude_records.ts";
import { limitsEqual, NO_LIMITS } from "./claude_sources.ts";
import type { Limits } from "./claude_sources.ts";

export const CALIB_TTL = 300;  // the scan walks transcripts; five minutes is
                               // plenty

// The smallest plan reading that can serve as the DIVISOR of a calibration.
// A reading quantised to whole percent is uncertain by half a point, ±50٪
// at 1 and ±25٪ at 2; see the Python's note for what that cost and bought.
export const CALIB_MIN_PCT = 2.0;

// How much of a file, ending where the last scan stopped, has to read the
// same for the scan to trust that the file was only appended to since.
export const COST_TAIL_BYTES = 4096;
// How often a scan that is still reading saves what it has.
export const COST_SAVE_EVERY_S = 1.0;

/** limits_snapshot(): the plan reading one render is taken against. */
export type Snapshot = Dict;

/** Dollars per point of each window, or null.  A planted calibration cache
 * states them directly and may hold anything, which the readers divide by
 * as Python would, raising where it raises. */
export type Calib = { readonly sess?: unknown; readonly week?: unknown };

/** A naive local datetime: its wall-clock reading in seconds, counted from
 * 1970-01-01 00:00 as if it were UTC.  Two compare as the Python's do. */
export type Naive = number;

// ════════════════════════════════════════════════════════════════════════════
// Python's semantics, where JavaScript's differ.
// ════════════════════════════════════════════════════════════════════════════

/** round(x) to an int: half to even, and a NaN or an infinity raises. */
export function _pyRound(x: number): number {
  if (!Number.isFinite(x)) throw new RangeError("cannot round " + x);
  const f = Math.floor(x), d = x - f;
  const r = d > 0.5 ? f + 1 : d < 0.5 ? f : f % 2 === 0 ? f : f + 1;
  return r + 0;  // never -0: Python's int has no sign on zero
}

/** `a / b` for JSON values: a bool is 0 or 1, anything but a number
 * raises TypeError.  `b` is never zero here; every caller tests it first. */
function pyDiv(a: unknown, b: unknown): number {
  const n = (v: unknown): number => {
    if (typeof v === "boolean") return v ? 1 : 0;
    if (typeof v === "number") return v;
    throw new TypeError("unsupported operand type for /");
  };
  return n(a) / n(b);
}

/** `v * p` for a token count read off a record, which Python multiplies
 * when it is a number or a bool and raises TypeError on otherwise. */
function pyMulCount(v: unknown, p: number): number {
  if (typeof v === "boolean") return (v ? 1 : 0) * p;
  if (typeof v === "number") return v * p;
  throw new TypeError("can't multiply sequence by non-int of type 'float'");
}

/** A request id as a key of a Python set: equal ids get equal keys.  1,
 * 1.0 and True are one key, -0.0 and 0 another, every NaN json.loads made
 * a third; a list or a dict is unhashable and raises. */
export function _idKey(k: unknown): string {
  if (k === null || k === undefined) return "N";
  if (typeof k === "string") return "s" + k;
  if (typeof k === "boolean") return "n" + (k ? 1 : 0);
  if (typeof k === "number") return Number.isNaN(k) ? "nan" : "n" + (k + 0);
  throw new TypeError("unhashable type");
}

// ════════════════════════════════════════════════════════════════════════════
// Naive local datetimes.
// ════════════════════════════════════════════════════════════════════════════

const DAY = 86400;

function daysFromCivil(y: number, m: number, d: number): number {
  y -= m <= 2 ? 1 : 0;
  const era = Math.floor(y / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

function civilFromDays(z: number): [number, number, number] {
  z += 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) +
    Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp + (mp < 10 ? 3 : -9);
  return [yoe + era * 400 + (m <= 2 ? 1 : 0), m, d];
}

function daysIn(y: number, m: number): number {
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
}

/** datetime(y, mo, d, h, mi, s) as a Naive. */
export function naive(y: number, mo: number, d: number, h = 0, mi = 0,
  s = 0): Naive {
  return daysFromCivil(y, mo, d) * DAY + h * 3600 + mi * 60 + s;
}

/** A Naive's fields: year, month, day, hour, minute, second. */
function fields(n: Naive): number[] {
  const days = Math.floor(n / DAY), secs = n - days * DAY;
  return [...civilFromDays(days), Math.floor(secs / 3600),
    Math.floor(secs % 3600 / 60), secs % 60];
}

/** A Naive inside datetime's range, years 1 to 9999; outside it the
 * Python's arithmetic raises OverflowError. */
function inRange(n: Naive): Naive {
  const y = fields(n)[0];
  if (y < 1 || y > 9999) throw new RangeError("date value out of range");
  return n;
}

/** str(datetime), as "%s" writes a window start into the cache key, and
 * "None" for none. */
export function naiveStr(n: Naive | null): string {
  if (n === null) return "None";
  const [y, mo, d, h, mi, s] = fields(n);
  const p = (v: number, w = 2) => String(v).padStart(w, "0");
  return `${p(y, 4)}-${p(mo)}-${p(d)} ${p(h)}:${p(mi)}:${p(s)}`;
}

/** The wall clock at instant `u`, as localtime(u) reads it in the TZ.
 * Off datetime's calendar it raises, as CPython's local() does, so a
 * timestamp of the first or last day of the calendar can raise. */
function local(u: number): Naive {
  const t = new Date(u * 1000);
  return inRange(naive(t.getFullYear(), t.getMonth() + 1, t.getDate(),
    t.getHours(), t.getMinutes(), t.getSeconds()));
}

/** datetime.timestamp() of a naive datetime: the instant whose local wall
 * clock reads `n`.  CPython's local_to_seconds, step for step, with fold
 * 0: in a fold, the earlier of the two instants; in a gap, the wall clock
 * read with the offset from before it, which lands after the gap. */
export function _naiveTimestamp(n: Naive): number {
  const t = n;
  const a = local(t) - t;
  const u1 = t - a;
  const t1 = local(u1);
  let b: number;
  if (t1 === t) {
    const u2 = u1 - DAY;
    b = local(u2) - u2;
    if (a === b) return u1;
  } else {
    b = t1 - u1;
  }
  const u2 = t - b;
  if (local(u2) === t) return u2;
  if (t1 === t) return u1;
  return Math.max(u1, u2);
}

// strptime's regex for STAMP_FMT, "%Y-%m-%d %H:%M": \d is any Unicode
// digit and the space any run of whitespace.  Matched at the start, then
// held to the whole string, as strptime raises "unconverted data remains"
// on a match that stops short.
const STAMP_STRPTIME = (() => {
  if (STAMP_FMT !== "%Y-%m-%d %H:%M") {
    throw new Error("STAMP_STRPTIME is out of step with STAMP_FMT");
  }
  return new RegExp("^(\\p{Nd}\\p{Nd}\\p{Nd}\\p{Nd})-(1[0-2]|0[1-9]|[1-9])" +
    "-(3[01]|[12]\\p{Nd}|0[1-9]|[1-9]| [1-9])[" + PY_SPACE + "]+" +
    "(2[0-3]|[0-1]\\p{Nd}|\\p{Nd}):([0-5]\\p{Nd}|\\p{Nd})", "iu");
})();

/** datetime.strptime(v, STAMP_FMT), or null where it raises. */
export function _strptimeStamp(v: unknown): Naive | null {
  if (typeof v !== "string") return null;
  const m = STAMP_STRPTIME.exec(v);
  if (!m || m[0].length !== v.length) return null;
  const [y, mo, d, h, mi] = m.slice(1)
    .map((g) => parseInt(pyAsciiDigits(g), 10));
  if (y < 1 || d > daysIn(y, mo)) return null;
  return naive(y, mo, d, h, mi);
}

/** A transcript's UTC "…Z" stamp as a naive LOCAL datetime, or null.
 *
 * The window boundaries are naive local times, so both sides of every
 * comparison have to be in that one frame. */
export function _localNaive(ts: string): Naive | null {
  const e = tsEpoch(ts);
  if (e === null) return null;
  try {
    return inRange(local(e));
  } catch {
    return null;
  }
}

// ════════════════════════════════════════════════════════════════════════════
// The plan snapshot and the window boundaries.
// ════════════════════════════════════════════════════════════════════════════

/** A carried percentage back as a number, or null if it is not one. */
export function _pctNum(v: unknown): number | null {
  return pyFloat(v);
}

/** seed_limits_snapshot: the plan reading as the accounting reads it.
 *
 * The Python installs it in a module global for the render; here it is
 * returned, and every reader below takes it as `snap`.  `reading` gives a
 * non-secret identity that scopes the calibration cache. */
export function seedLimitsSnapshot(lim: Limits,
  reading: unknown = null): Snapshot {
  if (limitsEqual(lim, NO_LIMITS)) return {};
  const part = (k: string) => isDict(reading) ? pyGet(reading, k) : "";
  const scope = ["source", "account_name", "period_start"]
    .map((k) => pyStr(pyOr(part(k), ""))).join("\0");
  return { session_pct: _pctNum(lim.session_pct),
    session_resets_at: lim.session_reset,
    weekly_pct: _pctNum(lim.weekly_pct),
    weekly_resets_at: lim.weekly_reset,
    _scope: scope };
}

/** When the 5-hour and the weekly window opened, or null for either:
 * each reset time the snapshot publishes, less the window's length. */
export function _windowStarts(snap: Snapshot): [Naive | null, Naive | null] {
  const start = (key: string, delta: number): Naive | null => {
    const v = pyGet(snap, key);
    if (!pyTruthy(v)) return null;
    const at = _strptimeStamp(v);
    if (at === null) return null;
    try {
      return inRange(at - delta);
    } catch {
      return null;
    }
  };
  return [start("session_resets_at", 5 * 3600),
    start("weekly_resets_at", 7 * DAY)];
}

/** The calibration cache's key: the two window starts as "%s|%s". */
export function _windowsKey(ss: Naive | null, ws: Naive | null): string {
  return naiveStr(ss) + "|" + naiveStr(ws);
}

/** The selected plan reading as numeric cost-grid totals. */
export function planTotals(snap: Snapshot): { sess?: number; week?: number } {
  const sp = _pctNum(pyGet(snap, "session_pct"));
  const wp = _pctNum(pyGet(snap, "weekly_pct"));
  if (sp === null || wp === null) return {};
  return { sess: sp, week: wp };
}

// ════════════════════════════════════════════════════════════════════════════
// A turn's and a session's shares.
// ════════════════════════════════════════════════════════════════════════════

/** List-price cost of one turn: the four sums read_turns priced per
 * record, at each record's own model. */
export function turnCost(t: Turn): number {
  return t.usd_in + t.usd_out + t.usd_cr + t.usd_cw;
}

/** The part of one turn's cost that was billed at or after `start`.
 *
 * Split at the boundary by each billed part's own stamp; a stamp that will
 * not parse counts IN.  A compaction bills through no usage record, so it
 * has nothing stamped to split and goes whole by its prompt's stamp. */
export function turnCostSince(t: Turn, start: Naive | null): number {
  if (start === null) return turnCost(t);
  const edge = _naiveTimestamp(start);
  if (t.compact || t.parts.length === 0) {
    const ts = _localNaive(t.ts);
    return ts === null || ts >= start ? turnCost(t) : 0.0;
  }
  let sum = 0;
  for (const [e, c] of t.parts) if (e === null || e >= edge) sum += c;
  return sum;
}

/** One turn's share of each live window, counting only what it billed in
 * it, on the same boundaries as sessionShares. */
export function windowShares(t: Turn, calib: Calib, snap: Snapshot):
  { sess: number | null; week: number | null } {
  const [ss, ws] = _windowStarts(snap);
  const out: { sess: number | null; week: number | null } =
    { sess: null, week: null };
  for (const [key, start] of [["sess", ss], ["week", ws]] as const) {
    const unit = pyGet(calib, key);
    if (pyTruthy(unit)) out[key] = pyDiv(turnCostSince(t, start), unit);
  }
  return out;
}

/** What fraction of one prompt's cost went on re-reading, and on caching,
 * in whole percent rounded half to even; nulls for a turn with no cost. */
export function turnShares(t: Turn): [number | null, number | null] {
  const c = turnCost(t);
  if (c <= 0) return [null, null];
  return [_pyRound(100 * t.usd_cr / c), _pyRound(100 * t.usd_cw / c)];
}

/** turnShares over the whole session, summed before dividing. */
export function sessionCacheShares(turns: readonly Turn[]):
  [number | null, number | null] {
  let c = 0, cr = 0, cw = 0;
  for (const t of turns) c += turnCost(t);
  if (c <= 0) return [null, null];
  for (const t of turns) cr += t.usd_cr;
  for (const t of turns) cw += t.usd_cw;
  return [_pyRound(100 * cr / c), _pyRound(100 * cw / c)];
}

/** What THIS session put into each plan window, as a percentage of it:
 * every turn split at the window's start, over dollars per point. */
export function sessionShares(turns: readonly Turn[], calib: Calib,
  snap: Snapshot): { sess: number | null; week: number | null } {
  const out: { sess: number | null; week: number | null } =
    { sess: null, week: null };
  if (!pyTruthy(calib)) return out;
  const [ss, ws] = _windowStarts(snap);
  for (const [key, start] of [["sess", ss], ["week", ws]] as const) {
    const unit = pyGet(calib, key);
    if (!pyTruthy(unit) || start === null) continue;
    let sum = 0;
    for (const t of turns) sum += turnCostSince(t, start);
    out[key] = pyDiv(sum, unit);
  }
  return out;
}

/** What one turn, or the session, comes to: the figures document's
 * `accounting` entry. */
export interface Accounting {
  readonly cost_usd: number;
  readonly sess_share: number | null;
  readonly week_share: number | null;
  readonly read_share: number | null;
  readonly write_share: number | null;
}

/** What one turn comes to: its cost, its share of each live window and
 * the shares of it spent re-reading and caching.  cost_group draws these.
 * The window shares read the plan snapshot, so this belongs to the first
 * stage, never to a render. */
export function turnAccounting(t: Turn, calib: Calib, snap: Snapshot):
  Accounting {
  const tsh = windowShares(t, calib, snap);
  const [rd, wr] = turnShares(t);
  return { cost_usd: turnCost(t), sess_share: tsh.sess,
    week_share: tsh.week, read_share: rd, write_share: wr };
}

/** turnAccounting for each turn, in order, and the same for the session:
 * the figures document's `accounting`. */
export function costAccounting(turns: readonly Turn[], calib: Calib,
  snap: Snapshot): { turns: Accounting[]; session: Accounting } {
  const sh = sessionShares(turns, calib, snap);
  const [rd, wr] = sessionCacheShares(turns);
  const each = turns.map((t) => turnAccounting(t, calib, snap));
  let cost = 0;
  for (const t of turns) cost += turnCost(t);
  return { turns: each, session: { cost_usd: cost, sess_share: sh.sess,
    week_share: sh.week, read_share: rd, write_share: wr } };
}

// ════════════════════════════════════════════════════════════════════════════
// The machine-wide scan.
// ════════════════════════════════════════════════════════════════════════════

/** One record the scan bills: its epoch (null for a stamp that will not
 * parse), its request id, and its list-price cost. */
export type Priced = [number | null, unknown, number];

// Decoding as bytes.decode("utf-8", "replace"), which keeps a BOM.
const DECODE_REPLACE = new TextDecoder("utf-8", { ignoreBOM: true });

/** One transcript line as (epoch, request id, list-price cost), or null
 * for anything the scan does not bill: a line that will not parse, a
 * record that is not an assistant's, or one with no usage or no stamp.
 * Throws where the Python raises; see the head of the file. */
export function _pricedRecord(line: Uint8Array): Priced | null {
  let r: unknown;
  try {
    r = pyJsonLoads(DECODE_REPLACE.decode(line));
  } catch {
    return null;
  }
  if (!isDict(r) || pyGet(r, "type") !== "assistant") return null;
  const m = pyOr(pyGet(r, "message"), {});
  if (!isDict(m)) throw new TypeError("message has no get");
  const u = pyGet(m, "usage");
  const ts = pyGet(r, "timestamp");
  if (!pyTruthy(u) || !pyTruthy(ts)) return null;
  const model = pyGet(m, "model");
  if (pyTruthy(model) && typeof model !== "string") {
    throw new TypeError("model has no lower");
  }
  const [pi, po, pr, pw] = _price(model);
  if (!isDict(u)) throw new TypeError("usage has no get");
  const n = (k: string) => pyGet(u, k, 0);
  const c = pyMulCount(n("input_tokens"), pi) +
    pyMulCount(n("output_tokens"), po) +
    pyMulCount(n("cache_read_input_tokens"), pr) +
    pyMulCount(n("cache_creation_input_tokens"), pw);
  // ts_epoch is lru_cached, so a list raises on hashing, and anything else
  // that is not a string raises on .split.
  if (typeof ts !== "string") throw new TypeError("timestamp is no str");
  return [tsEpoch(ts), pyOr(pyGet(r, "requestId"), pyGet(m, "id")), c];
}

/** Total spend in `files` since each window opened, in that order.
 *
 * Bounded by file mtime: nothing last written a day before the earlier
 * start can hold a record in either window.  A request id is billed once,
 * at its first record; a record whose stamp will not parse still claims its
 * id but bills nothing.  `files` is the projects glob; see _windowCosts. */
export function _windowCostsOf(sessStart: Naive | null,
  weekStart: Naive | null, files: readonly string[],
  mtime: (path: string) => number | null,
  records: (path: string) => Priced[],
  tick: () => void = () => {}): [number, number] {
  let sess = 0.0, week = 0.0;
  const seen = new Set<string>();
  const starts = [sessStart, weekStart].filter((s) => s !== null);
  const earliest = starts.length ? Math.min(...starts) : null;
  const cutoff = earliest === null ? null
    : _naiveTimestamp(inRange(earliest - DAY));
  // Epochs on both sides: the records are kept as epochs, and a naive
  // local start's timestamp is the instant _localNaive compared with.
  const earlyE = earliest === null ? null : _naiveTimestamp(earliest);
  const weekE = weekStart === null ? null : _naiveTimestamp(weekStart);
  const sessE = sessStart === null ? null : _naiveTimestamp(sessStart);
  for (const fp of files) {
    tick();
    if (cutoff !== null) {
      const mt = mtime(fp);
      if (mt === null || mt < cutoff) continue;
    }
    for (const [t, k, c] of records(fp)) {
      const key = _idKey(k);
      if (seen.has(key)) continue;
      seen.add(key);
      if (t === null) continue;
      if (earlyE !== null && t < earlyE) continue;
      if (weekE === null || t >= weekE) week += c;
      if (sessE !== null && t >= sessE) sess += c;
    }
  }
  return [sess, week];
}

/** Dollars per one percent of each plan window, from a scan and the
 * readings it was taken with.
 *
 * `cached` is the calibration cache for these windows, or null; `scan`
 * runs the scan when there is none.  A cache with no "windows" is a
 * planted fixture, which states the two units directly.  Otherwise both
 * halves of the ratio come off one moment, the cache's or the scan's, and
 * no unit is derived from a reading under CALIB_MIN_PCT. */
export function _calibrationOf(snap: Snapshot, cached: Dict | null,
  scan: (() => [number, number]) | null): Calib {
  const out: { sess: unknown; week: unknown } = { sess: null, week: null };
  if (cached !== null && !pyHas(cached, "windows")) {
    return { sess: pyGet(cached, "sess"), week: pyGet(cached, "week") };
  }
  let sc: unknown, wc: unknown;
  let sp = pyGet(snap, "session_pct"), wp = pyGet(snap, "weekly_pct");
  if (cached !== null) {
    sc = pyGet(cached, "sess_cost");
    wc = pyGet(cached, "week_cost");
    sp = pyGet(cached, "sess_pct");
    wp = pyGet(cached, "week_pct");
  } else if (scan === null) {
    return out;
  } else {
    [sc, wc] = scan();
  }
  const spn = _pctNum(sp), wpn = _pctNum(wp);
  if (pyTruthy(spn) && spn! >= CALIB_MIN_PCT && sc !== null) {
    out.sess = pyDiv(sc, spn);
  }
  if (pyTruthy(wpn) && wpn! >= CALIB_MIN_PCT && wc !== null) {
    out.week = pyDiv(wc, wpn);
  }
  return out;
}

// ════════════════════════════════════════════════════════════════════════════
// The edges.
// ════════════════════════════════════════════════════════════════════════════

/** Where the scan and the calibration cache read and write, and the clock
 * the cache's age is read against: the Python's module globals and
 * environment, as arguments. */
export interface CalibEnv {
  readonly projectsDir: string;   // ~/.claude/projects
  readonly stateDir: string;      // the private state directory
  readonly version: string;       // the mod's version, which keys its caches
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

type Kept = { off: number; tail: string | null; recs: Priced[] };

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
 * Keyed by the mod's version, as the Python's is by a digest of its
 * source, since the prices and the rules for what counts are both in it,
 * and named apart from the Python's. */
export class _CostCache {
  readonly path: string;
  readonly version: string;
  kept: Record<string, Kept> = {};
  keep: Record<string, Kept> = {};
  dirty = false;

  constructor(stateDir: string, version: string) {
    this.path = pyJoin(stateDir, "claude-window-costs-ts.cache");
    this.version = version;
    try {
      const d = pyJsonLoads(new TextDecoder("utf-8", { fatal: true })
        .decode(fs.readFileSync(this.path)));
      if (isDict(d) && pyGet(d, "version") === version) {
        const files = pyOr(pyGet(d, "files"), {});
        if (isDict(files)) this.kept = files as Record<string, Kept>;
      }
    } catch {
      // No cache yet, or one that will not parse: read everything.
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
      // Every number in a record written as a float, so a -0.0 id comes
      // back as itself rather than as 0.
      text = pyJsonDumps({ version: this.version, files }, false, [""]);
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
  const cache = new _CostCache(env.stateDir, env.version);
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

/** The calibration cache for these windows: the override when one is
 * set, else a private file keyed by the snapshot's scope, the windows and
 * the mod's version, named apart from the Python's. */
export function calibrationCachePath(windows: string, snap: Snapshot,
  env: CalibEnv): string {
  if (env.calibCacheOverride) return expandUser(env.calibCacheOverride);
  const scope = pyStr(pyGet(snap, "_scope", ""));
  const key = crypto.createHash("sha256")
    .update(env.version + "\0" + scope + "\0" + windows, "utf8")
    .digest("hex");
  return pyJoin(env.stateDir, "claude-calibration-ts-" + key + ".cache");
}

/** The cached scan, if it is younger than `ttl` seconds (any age for a
 * null `ttl`) AND measured over these windows, with the readings it was
 * taken with.  A dict with no "windows" is a planted fixture, returned as
 * it is. */
export function _readCalibCache(windows: string, snap: Snapshot,
  env: CalibEnv, ttl: number | null = CALIB_TTL): Dict | null {
  const path = calibrationCachePath(windows, snap, env);
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
    text = pyJsonDumps({ windows, sess_cost: sc, week_cost: wc,
      sess_pct: sp, week_pct: wp }, false,
    ["sess_cost", "week_cost", "sess_pct", "week_pct"]);
  } catch {
    return;
  }
  writeAtomic(calibrationCachePath(windows, snap, env), text);
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
