// claude.ts, the glue that builds the figures documents, against the
// documents the Python built.
//
// For each status and cost case in tests/fixtures/cases.json this reads
// the case's inputs as run-cases.py hands them to the Python, builds the
// document with statusFigures or costFigures, and compares it with the
// committed tests/fixtures/figures/<suite>/<id>.json field for field.
// What the Python read outside the transcript comes from the committed
// document itself: the usage source's reading (sources.test.ts pins the
// reader), the git context (claude.test.ts pins detectGit's reading of
// git's answers below) and the token rate (the status line's own state
// file, which the mod does not keep).  Everything the accounting works
// out, the transcript, the turns, the shares, the limits and the context
// window, is the TypeScript's.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import {
  agentRecords, EMPTY_TRANSCRIPT, readTranscript, readTurns,
} from "../src/claude_records_node.ts";
import type { AgentEta } from "../src/claude_records_node.ts";
import { legacyLimits } from "../src/claude_sources.ts";
import {
  _calibrationOf, _windowsKey, _windowStarts, seedLimitsSnapshot,
} from "../src/claude_calib.ts";
import type { Calib, Snapshot } from "../src/claude_calib.ts";
import {
  _mainRoot, _pctStr, baseLimits, costFigures, ctxWindowFor, detectGit,
  pyG, statusFigures, windowFor,
} from "../src/claude.ts";
import { decodeGit, decodePayload } from "../src/figures.ts";
import { pyJsonLoads } from "../src/sources.ts";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../..");
const FIXTURES = path.join(REPO, "tests/fixtures");
const SCRATCH = path.join(os.tmpdir(), "claude-glue-scratch");

type Case = {
  id: string; suite: string; env: string; input: string; cols: number;
  flags: string[];
};

function fill(text: string): string {
  return text.replaceAll("${HOME}", os.homedir())
    .replaceAll("${FIXTURES}", FIXTURES)
    .replaceAll("${SCRATCH}", SCRATCH);
}

/** A document as JSON holds it, so deepEqual compares values: the
 * Python's -0.0 and 0 are one figure in canonical JSON. */
function plain(v: unknown): unknown {
  return JSON.parse(JSON.stringify(v, (_k, x) => Object.is(x, -0) ? 0 : x));
}

const cases: Case[] = JSON.parse(fs.readFileSync(
  path.join(FIXTURES, "cases.json"), "utf-8")).cases;

const savedTz = process.env.TZ;

function withTz<T>(tz: string, body: () => T): T {
  process.env.TZ = tz;
  try {
    return body();
  } finally {
    if (savedTz === undefined) delete process.env.TZ;
    else process.env.TZ = savedTz;
  }
}

function envOf(c: Case): any {
  return JSON.parse(fs.readFileSync(
    path.join(FIXTURES, "env", c.env + ".json"), "utf-8"));
}

/** The committed document, read as the Python reads JSON. */
function committed(c: Case): any {
  return pyJsonLoads(fill(fs.readFileSync(
    path.join(FIXTURES, "figures", c.suite, c.id + ".json"), "utf-8")));
}

/** The calibration the case's planted cache gives under this snapshot, as
 * _read_calib_cache and calibration read it: a fixture of units as it
 * is, and the live shape only for the windows it was measured over.  No
 * case runs the scan. */
function calibOf(env: any, snap: Snapshot): Calib {
  const planted = env.calib;
  const [ss, ws] = _windowStarts(snap);
  const fits = !("windows" in planted) ||
    planted.windows === _windowsKey(ss, ws);
  return _calibrationOf(snap, fits ? planted : null, null);
}

const status = cases.filter((c) => c.suite === "status");
const cost = cases.filter((c) => c.suite === "cost");

test("every status and cost case is here", () => {
  assert.equal(status.length, 142);
  assert.equal(cost.length, 88);
});

for (const c of status) {
  test("status " + c.id, () => {
    const env = envOf(c), want = committed(c);
    withTz(env.tz, () => {
      const pay = decodePayload(want.payload);
      const tp = pay.transcript;
      const have = Boolean(tp) && fs.existsSync(tp) &&
        fs.statSync(tp).isFile();
      const etas: AgentEta[] = [];
      const agents = have ? agentRecords(tp, null, etas) : [];
      // A tool call still running counts to the case's clock: these are
      // live renders, never --transcript ones.
      const tr = have ? readTranscript(tp, agents, etas, env.now)
        : EMPTY_TRANSCRIPT;
      const turns = have ? readTurns(tp, agents) : null;
      const reading = want.usage.reading ?? {};
      const prepared = { reading, limits: legacyLimits(reading) };
      const snap = seedLimitsSnapshot(baseLimits(prepared), reading);
      const got = statusFigures({
        payload: pay, transcript: tr, turns, git: decodeGit(want.git),
        prepared, snap, calib: calibOf(env, snap), now: env.now,
        tz: env.tz, rate: want.rate,
      });
      assert.deepEqual(plain(got), plain(want));
    });
  });
}

for (const c of cost) {
  test("cost " + c.id, () => {
    const env = envOf(c), want = committed(c);
    withTz(env.tz, () => {
      const tp = path.join(FIXTURES, c.input);
      const turns = readTurns(tp, agentRecords(tp), new Map());
      const reading = want.usage.reading ?? {};
      const prepared = { reading, limits: legacyLimits(reading) };
      const snap = seedLimitsSnapshot(baseLimits(prepared), reading);
      // No status line ran in the cost suite, so none published a window.
      const got = costFigures(turns, windowFor(turns, 0),
        calibOf(env, snap), snap, prepared, env.now, env.tz);
      assert.deepEqual(plain(got), plain(want));
    });
  });
}

// tests/fixtures/gen/claude.py's cases: the small pure parts, each case
// one call of the Python's.
const glue = JSON.parse(fs.readFileSync(
  path.join(FIXTURES, "claude/glue.json"), "utf-8"));

/** gen/calib.py's float encoding back. */
function float(v: any): number | null {
  if (v === null || typeof v === "number") return v;
  return { nan: NaN, inf: Infinity, "-inf": -Infinity, "-0": -0 }[
    v.$float as string]!;
}

test("ctxWindowFor, as ctx_window_for", () => {
  for (const c of glue.ctx_window) {
    assert.equal(ctxWindowFor(c.size, c.name), c.expected,
      JSON.stringify(c));
  }
});

test("windowFor, as window_for", () => {
  for (const c of glue.window_for) {
    const turns = c.ctx.map((ctx: number) => ({ ctx }));
    assert.equal(windowFor(turns, c.published), c.expected,
      JSON.stringify(c));
  }
});

test("_pctStr, as _pct_str", () => {
  for (const c of glue.pct_str) {
    assert.equal(_pctStr(float(c.v)), c.expected, JSON.stringify(c));
  }
  assert.equal(pyG(0.15 + 0.15 + 0.15), "0.45");
});

test("_mainRoot, as _main_root", () => {
  for (const c of glue.main_root) {
    assert.deepEqual(_mainRoot(c.common, c.toplevel), c.expected,
      JSON.stringify(c));
  }
});

test("detectGit: git's answers read as detect_git reads them", async () => {
  const answers = (table: { [args: string]: string | null }) =>
    async (args: readonly string[]) => table[args.join(" ")] ?? null;
  assert.deepEqual(await detectGit(answers({
    "rev-parse --show-toplevel --path-format=absolute --git-common-dir --short HEAD":
      "/r/wt\n/r/.git\nabc1234",
    "symbolic-ref --short HEAD": "main",
    "diff --quiet HEAD": "",
  })), { in_git: true, branch: "main", dirty: false, toplevel: "/r/wt",
    main_root: "/r", is_worktree: true });
  // Detached and dirty.
  assert.deepEqual(await detectGit(answers({
    "rev-parse --show-toplevel --path-format=absolute --git-common-dir --short HEAD":
      "/r\n.git\nabc1234",
  })), { in_git: true, branch: "abc1234", dirty: true, toplevel: "/r",
    main_root: "/r", is_worktree: false });
  // A repo with no commits yet, and no repo at all.
  assert.deepEqual(await detectGit(answers({
    "rev-parse --is-inside-work-tree": "true",
    "rev-parse --show-toplevel": "/e",
    "rev-parse --path-format=absolute --git-common-dir": ".git",
  })), { in_git: true, branch: "", dirty: false, toplevel: "/e",
    main_root: "/e", is_worktree: false });
  assert.deepEqual(await detectGit(answers({})), { in_git: false,
    branch: "", dirty: false, toplevel: "", main_root: "",
    is_worktree: false });
});
