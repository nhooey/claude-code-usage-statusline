// The receipt's Stop hook, tools/receipt-hook.ts, run as Claude Code runs
// it: a Stop payload on stdin naming a fixture transcript, in a scratch
// state directory, with the clock pinned.  What it prints is checked
// against the src/ functions over the same transcript, so the test pins
// the hook's reads and its message's shape, and rows.test.ts the rows.
import { after, test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { spawnSync } from "node:child_process";
import { CONFIG } from "../hooks/config.ts";
import { C_CHROME_CONT } from "../src/spec.ts";
import { settings, stripAnsi } from "../src/formatting.ts";
import { DIM, join } from "../src/spans.ts";
import { pyRstrip } from "../src/py.ts";
import type { Dict } from "../src/py.ts";
import { sha256Hex } from "../src/sha256.ts";
import { agentRecords, readTurns } from "../src/claude_records_node.ts";
import { calibration, seedLimitsSnapshot } from "../src/claude_calib_node.ts";
import { prepareClaudeReading } from "../src/claude_sources_node.ts";
import { baseLimits, costFigures, windowFor } from "../src/claude.ts";
import { receiptLines, withEngineDuration } from "../src/receipt.ts";
import { LOG_NAME } from "../src/modlog.ts";

const HOOK = path.join(import.meta.dirname, "..", "tools", "receipt-hook.ts");
const TRANSCRIPT = path.join(import.meta.dirname, "..", "..", "tests",
  "fixtures", "transcripts", "cost", "09-agents.jsonl");
const SESSION = "09-agents";
const NOW = 1786846800;
const COLS = 160;
const WINDOW = 1_000_000;

/** A scratch home, a state directory, and a working directory that is a
 * repository of one commit on branch `trunk`, for the 📊 🎮 row's 📦 🌿. */
const roots: string[] = [];
after(() => {
  for (const r of roots) fs.rmSync(r, { recursive: true, force: true });
});

function scratch() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "receipt-hook-"));
  roots.push(root);
  const dirs = { root, state: path.join(root, "state"),
    cwd: path.join(root, "work") };
  fs.mkdirSync(dirs.state);
  fs.mkdirSync(dirs.cwd);
  for (const args of [["init", "-q", "-b", "trunk"],
    ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
      "--allow-empty", "-m", "start"]]) {
    const r = spawnSync("git", args, { cwd: dirs.cwd, encoding: "utf8" });
    assert.equal(r.status, 0, r.stderr);
  }
  return dirs;
}

type Dirs = ReturnType<typeof scratch>;

/** The hook's environment: nothing of the terminal's, so its profile is
 * the plain one, and no Claude Code variables. */
function envOf(d: Dirs): NodeJS.ProcessEnv {
  return { PATH: process.env.PATH, HOME: d.root, TZ: "UTC",
    CODING_AGENT_USAGE_LINE_STATE_DIR: d.state,
    CODING_AGENT_USAGE_LINE_NOW: String(NOW) };
}

function stop(d: Dirs, payload: string, args: string[] = []) {
  const r = spawnSync(process.execPath, [HOOK, "--cols", String(COLS),
    "--usage-source", "none", ...args], { input: payload, env: envOf(d),
    encoding: "utf8" });
  return { status: r.status, stdout: r.stdout, stderr: r.stderr };
}

function payloadOf(d: Dirs, extra: Dict = {}): string {
  return JSON.stringify({ session_id: "s-" + SESSION,
    transcript_path: TRANSCRIPT, cwd: d.cwd, hook_event_name: "Stop",
    stop_hook_active: false, ...extra });
}

/** The message the hook should print, from the src/ functions alone. */
async function expected(d: Dirs, published: number,
  durationMs = 0): Promise<string> {
  const was = process.env.TZ;
  process.env.TZ = "UTC";
  try {
    const turns = readTurns(TRANSCRIPT, agentRecords(TRANSCRIPT), new Map(),
      d.state);
    const env = { HOME: d.root, CODING_AGENT_USAGE_LINE_STATE_DIR: d.state };
    const prepared = await prepareClaudeReading("none", CONFIG.account,
      CONFIG.period, { session: SESSION }, NOW, env);
    const snap = seedLimitsSnapshot(baseLimits(prepared), prepared.reading);
    const calib = calibration(snap, { projectsDir: d.root + "/.claude/projects",
      stateDir: d.state, version: CONFIG.version, now: NOW }, false);
    let fig = costFigures(turns, windowFor(turns, published), calib, snap,
      prepared, NOW, "UTC");
    if (durationMs) fig = withEngineDuration(fig, durationMs);
    const ws = { project: "work", branch: "trunk", dirty: false, dir: "",
      pr: "", style: "" };
    const { head, rows } = receiptLines(settings({}), fig,
      COLS - C_CHROME_CONT, [], ws, true);
    return "\n" + [head, ...rows].map((l) => pyRstrip(join(l))).join("\n");
  } finally {
    if (was === undefined) delete process.env.TZ;
    else process.env.TZ = was;
  }
}

function logOf(d: Dirs): string {
  try {
    return fs.readFileSync(path.join(d.state, LOG_NAME), "utf8");
  } catch {
    return "";
  }
}

test("a Stop prints the receipt, dimmed; a second for the same turn nothing",
  async () => {
    const d = scratch();
    // The window the band published for the session.
    fs.writeFileSync(path.join(d.state, "claude-context-" +
      sha256Hex("context\0" + SESSION) + ".json"), WINDOW + "\n");
    const first = stop(d, payloadOf(d));
    assert.equal(first.status, 0, first.stderr);
    const msg = (JSON.parse(first.stdout) as Dict).systemMessage as string;
    assert.equal(msg, await expected(d, WINDOW));
    // `Stop says:` alone on its line, then the head and the two rows, each
    // drawn dim from its first escape.
    const lines = msg.split("\n");
    assert.equal(lines[0], "");
    assert.equal(lines.length, 4);
    assert.ok(stripAnsi(lines[1]).startsWith("🔺🔖 "));
    assert.ok(stripAnsi(lines[2]).startsWith("📊 🎤 "));
    assert.match(stripAnsi(lines[3]), /^📊 🎮 session  📦work +🌿trunk /);
    for (const l of lines.slice(1)) assert.ok(l.startsWith(DIM), l);
    // The Python Stop hook's agent offsets, and the turn reported.
    const state = fs.readdirSync(d.state);
    assert.ok(state.some((f) => /^claude-agent-offsets-[0-9a-f]+\.json$/
      .test(f)), state.join(" "));
    assert.ok(state.some((f) => /^reported-receipt-[0-9a-f]+\.json$/
      .test(f)), state.join(" "));

    const second = stop(d, payloadOf(d, { stop_hook_active: true }));
    assert.equal(second.status, 0, second.stderr);
    assert.equal(second.stdout, "");
    assert.equal(logOf(d), "");
  });

test("the engine's duration, where the payload carries one, times the turn",
  async () => {
    const d = scratch();
    const got = stop(d, payloadOf(d, { duration_ms: 400_000 }));
    assert.equal(got.status, 0, got.stderr);
    assert.equal((JSON.parse(got.stdout) as Dict).systemMessage,
      await expected(d, 0, 400_000));
  });

test("--plain prints the same rows with no escapes", async () => {
  const d = scratch();
  const got = stop(d, payloadOf(d), ["--plain"]);
  assert.equal((JSON.parse(got.stdout) as Dict).systemMessage,
    stripAnsi(await expected(d, 0)));
});

test("a Stop that fails prints nothing, exits 0 and logs why", () => {
  const d = scratch();
  const bad = stop(d, "{not json");
  assert.equal(bad.status, 0);
  assert.equal(bad.stdout, "");
  assert.match(logOf(d), /receipt-hook: no receipt: .*JSON/);

  const gone = stop(d, payloadOf(d, { transcript_path: d.root + "/x.jsonl",
    session_id: "abcdef1234" }));
  assert.equal(gone.status, 0);
  assert.equal(gone.stdout, "");
  assert.match(logOf(d), / abcdef12 receipt-hook: no receipt: no transcript/);

  const flag = stop(d, payloadOf(d), ["--cols", "wide"]);
  assert.equal(flag.status, 0);
  assert.equal(flag.stdout, "");
  assert.match(logOf(d), /receipt-hook: no receipt: --cols/);
});
