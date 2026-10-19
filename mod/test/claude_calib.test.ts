// claude_calib.ts against the calibration in claude.py, case by case.
//
// tests/fixtures/gen/calib.py runs the Python and writes each call's
// inputs and result under tests/fixtures/calib/; this runs the same call
// through the TypeScript and compares the two with deepEqual.  A call the
// Python raises on is {"raises": true}, and the TypeScript must throw.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import * as cc from "../src/claude_calib.ts";
import type { CalibEnv, Naive } from "../src/claude_calib.ts";
import type { Turn } from "../src/claude_records.ts";
import type { Limits } from "../src/claude_sources.ts";
import { isDict } from "../src/py.ts";
import { pyJsonLoads } from "../src/sources.ts";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../..");
const DIR = path.join(REPO, "tests/fixtures/calib");
// cases.py's PIN_NOW, the clock every scenario step runs at unless it says.
const PIN_NOW = 1786847000;

type Case = { [k: string]: any };

/** The generator's JSON back to values: {"$float": ...} is what JSON
 * cannot spell. */
function revive(v: any): any {
  if (Array.isArray(v)) return v.map(revive);
  if (v !== null && typeof v === "object") {
    if (Object.keys(v).length === 1 && "$float" in v) {
      return { inf: Infinity, "-inf": -Infinity, nan: NaN, "-0": -0 }[
        v.$float as string];
    }
    return Object.fromEntries(Object.entries(v).map(([k, x]) =>
      [k, revive(x)]));
  }
  return v;
}

/** A value with every dict a plain object, as deepEqual wants it:
 * pyJsonLoads builds its dicts with no prototype. */
function plain(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(plain);
  if (isDict(v)) {
    return Object.fromEntries(Object.entries(v).map(([k, x]) =>
      [k, plain(x)]));
  }
  return v;
}

const RAISES = { raises: true };

/** fn(), or the mark of a call that threw. */
function attempt<T>(fn: () => T): T | typeof RAISES {
  try {
    return fn();
  } catch {
    return RAISES;
  }
}

function load(name: string): Case[] {
  return revive(JSON.parse(fs.readFileSync(path.join(DIR, name + ".json"),
    "utf-8"))).cases;
}

function str(n: Naive | null): string | null {
  return n === null ? null : cc.naiveStr(n);
}

/** str(datetime) back to a Naive. */
function parseNaive(s: string | null): Naive | null {
  if (s === null) return null;
  const [y, mo, d, h, mi, sec] = s.split(/[- :]/).map(Number);
  return cc.naive(y, mo, d, h, mi, sec);
}

function bytesOf(a: { text?: string; hex?: string }): Uint8Array {
  return a.hex !== undefined ? Buffer.from(a.hex, "hex")
    : new TextEncoder().encode(a.text!);
}

/** Group cases by function and run each group as one test. */
function suite(file: string, run: Record<string, (c: Case) => unknown>,
  cases: Case[]): void {
  const byFn = new Map<string, Case[]>();
  for (const c of cases) byFn.set(c.fn, [...(byFn.get(c.fn) ?? []), c]);
  for (const [fn, group] of byFn) {
    test(`${file}: ${fn} (${group.length})`, () => {
      assert.ok(run[fn], `no TypeScript runner for ${fn}`);
      for (const c of group) {
        if (c.tz) process.env.TZ = c.tz;
        assert.deepEqual(plain(run[fn](c)), c.out,
          `${fn} in ${c.tz ?? "-"}: ${JSON.stringify(c.args).slice(0, 300)}`);
      }
    });
  }
}

// ════════════════════════════════════════════════════════════════════════════
// values.json
// ════════════════════════════════════════════════════════════════════════════

suite("values", {
  _local_naive: (c) => str(cc._localNaive(c.args[0])),
  _window_starts: (c) => {
    const [ss, ws] = cc._windowStarts(c.args[0]);
    const stamp = (n: Naive | null) =>
      n === null ? null : attempt(() => cc._naiveTimestamp(n));
    return [str(ss), str(ws), [stamp(ss), stamp(ws)],
      cc._windowsKey(ss, ws)];
  },
  _pct_num: (c) => cc._pctNum(c.args[0]),
  seed_limits_snapshot: (c) =>
    cc.seedLimitsSnapshot(c.args[0] as Limits, c.args[1]),
  plan_totals: (c) => cc.planTotals(c.args[0]),
  _priced_record: (c) => attempt(() => cc._pricedRecord(bytesOf(c.args[0]))),
}, load("values"));

// ════════════════════════════════════════════════════════════════════════════
// shares.json
// ════════════════════════════════════════════════════════════════════════════

const shareCases = load("shares");
const TURNS: Record<string, Turn[]> = shareCases[0].out;

suite("shares", {
  turns: (c) => c.out,
  turn_costs: (c) => {
    const ts = TURNS[c.args[0]];
    return {
      turn_cost: ts.map(cc.turnCost),
      turn_shares: ts.map((t) => attempt(() => cc.turnShares(t))),
      session_cache_shares: attempt(() => cc.sessionCacheShares(ts)),
    };
  },
  shares: (c) => {
    const ts = TURNS[c.args[0]];
    const starts = cc._windowStarts(c.snap);
    return {
      turn_cost_since: ts.map((t) =>
        starts.map((s) => attempt(() => cc.turnCostSince(t, s)))),
      by_calib: c.calibs.map((calib: cc.Calib) => ({
        window_shares: ts.map((t) =>
          attempt(() => cc.windowShares(t, calib, c.snap))),
        session_shares: attempt(() => cc.sessionShares(ts, calib, c.snap)),
      })),
    };
  },
}, shareCases);

// ════════════════════════════════════════════════════════════════════════════
// scan.json
// ════════════════════════════════════════════════════════════════════════════

/** A JSON file's content as the generator reads it, or null. */
function readJson(p: string): unknown {
  try {
    return plain(pyJsonLoads(fs.readFileSync(p, "utf-8")));
  } catch {
    return null;
  }
}

function scrub(v: unknown, dir: string): unknown {
  if (typeof v === "string") return v.replaceAll(dir, "${DIR}");
  if (Array.isArray(v)) return v.map((x) => scrub(x, dir));
  if (isDict(v)) {
    return Object.fromEntries(Object.entries(v).map(([k, x]) =>
      [scrub(k, dir), scrub(x, dir)]));
  }
  return v;
}

/** One scenario: its files laid out in a scratch directory, then each step
 * run in turn against one state directory. */
function scenario(c: Case): void {
  process.env.TZ = c.tz;
  const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),
    "calib-ts-")));
  const projects = path.join(dir, "projects");
  const state = path.join(dir, "state");
  fs.mkdirSync(projects);
  const put = (f: Case, append = false) => {
    const p = path.join(projects, f.path);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    let data: Uint8Array | null = null;
    if (f.from !== undefined) data = fs.readFileSync(path.join(REPO, f.from));
    else if (f.text !== undefined || f.hex !== undefined) data = bytesOf(f);
    if (data !== null) {
      if (append) fs.appendFileSync(p, data);
      else fs.writeFileSync(p, data);
    }
    if (f.mtime !== undefined) fs.utimesSync(p, f.mtime, f.mtime);
  };
  for (const f of c.files) put(f);
  let override = "";
  let last: unknown = null;
  const costsCache = (s: Case, where: string) => {
    const d = readJson(path.join(state, "claude-window-costs-ts.cache"));
    const got = isDict(d) ? scrub(d.files, dir) : null;
    if (s.costs_cache === "same") {
      assert.deepEqual(got, last, `${where}: the scan cache changed`);
    } else {
      assert.deepEqual(got, s.costs_cache, `${where}: the scan cache`);
      last = got;
    }
  };
  try {
    c.steps.forEach((s: Case, i: number) => {
      const where = `${c.name} step ${i} (${s.op})`;
      const env: CalibEnv = {
        projectsDir: projects, stateDir: state, version: "test",
        now: s.now ?? PIN_NOW, calibCacheOverride: override,
        glob: () => s.glob.map((r: string) => path.join(projects, r)),
      };
      const snap = s.snap ?? {};
      if (s.glob) {
        // The TypeScript's own listing finds the same files; the order is
        // the filesystem's, and the step's is the one the Python saw.
        const own = cc.projectFiles(projects)
          .map((p) => path.relative(projects, p));
        assert.deepEqual([...own].sort(), [...s.glob].sort(),
          `${where}: the projects glob`);
      }
      if (s.op === "append" || s.op === "replace") {
        put(s, s.op === "append");
      } else if (s.op === "override") {
        override = s.path ? path.join(dir, s.path) : "";
      } else if (s.op === "plant" || s.op === "age") {
        const p = cc.calibrationCachePath(s.windows, snap, env);
        if (s.op === "plant") {
          fs.mkdirSync(path.dirname(p), { recursive: true });
          fs.writeFileSync(p, s.content);
        }
        if (s.age !== undefined && s.age !== null) {
          fs.utimesSync(p, env.now - s.age, env.now - s.age);
        }
      } else if (s.op === "calibration") {
        const got = attempt(() => cc.calibration(snap, env, s.scan ?? true));
        assert.deepEqual(plain(got), s.out, `${where}: the units`);
        const [ss, ws] = cc._windowStarts(snap);
        const p = cc.calibrationCachePath(cc._windowsKey(ss, ws), snap, env);
        assert.deepEqual(readJson(p), s.calib_cache,
          `${where}: the calibration cache`);
        costsCache(s, where);
      } else if (s.op === "window_costs") {
        const got = attempt(() => cc._windowCosts(parseNaive(s.ss),
          parseNaive(s.ws), env));
        assert.deepEqual(got, s.out, `${where}: the costs`);
        costsCache(s, where);
      } else {
        assert.fail(`unknown step ${s.op}`);
      }
    });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

for (const c of load("scan")) {
  test(`scan: ${c.name} (${c.steps.length} steps)`, () => scenario(c));
}
