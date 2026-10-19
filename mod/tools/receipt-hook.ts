// The receipt's Stop hook: each turn's receipt, stamped into the transcript.
//
//   node mod/tools/receipt-hook.ts [--cols N] [--plain] [--wait S]
//        [--usage-source SPEC] [--hide PATH ...]
//
// agents/plans/redesign.md has the design ("The receipt"): while a turn
// runs the band draws its 🎤 and 🎮 rows live; when it ends, this prints
// them frozen, as the Stop hook's systemMessage, so every receipt stays in
// the transcript to scroll back to.  Claude Code draws `Stop says: ` before
// the message and indents each line C_CHROME_CONT columns, so the message
// opens with a newline, the label alone on its line, and the rows are laid
// out as the band lays its own, indented C_CHROME_CONT, and printed
// without the indent.
//
// stdin    the Stop payload: transcript_path (the session is its basename,
//          as the Python hook takes it, else session_id), cwd,
//          last_assistant_message, which the transcript is waited on to
//          hold (Claude Code runs the hook before it has written the
//          turn's records, and without the wait the last turn read is the
//          one before), and the
//          engine's duration of the turn where a payload carries one
//          (duration_ms or durationMs; Claude Code's does not yet, and the
//          billed turn is then timed as the transcript gives).
// stdout   {"systemMessage": "\n<head>\n<📊 🎤>\n<📊 🎮>"}, the rows as
//          receipt.ts draws them, dimmed, joined into escapes as spans.ts
//          joins them; nothing at all for no receipt.
// --cols   the terminal's width, else found as the Python's term_cols
//          finds it, else 80.
// --plain  the same rows with no escapes.
// --wait   how long to wait for the transcript to hold the turn's last
//          message, in seconds (3, inside the Stop hook's 20 s timeout).
//
// The reads are the mod's, through Node's edges (src/*_node.ts): the
// transcript after read_turns_settled's wait, the agent files, the usage
// source of hooks/config.ts (--usage-source overrides it), the calibration
// as the band last scanned it (keyed by CONFIG.version, so the mod's; the
// hook never scans, so a session the band has not calibrated draws blank
// shares), the context window the status line or the band published, and
// git in the payload's cwd for 📦 🌿.
//
// State, in the status line's state directory: each Stop writes the agent
// offsets file the Python Stop hook wrote (claude-agent-offsets-*.json, the
// same format, so the status line and the band read where it left off),
// and `reported-receipt-<digest>.json`, the billed turn last printed for
// this session, so a second Stop over the same turn prints nothing.  A
// turn that went on (a Stop hook that blocked, `stop_hook_active`) and
// billed more is a new receipt.
//
// Nothing here may break a Stop: any failure prints nothing, exits 0, and
// is logged to the mod's log file (src/modlog.ts).
import * as fs from "node:fs";
import { spawnSync } from "node:child_process";
import { CONFIG } from "../hooks/config.ts";
import { C_CHROME_CONT } from "../src/spec.ts";
import { settings, stripAnsi } from "../src/formatting.ts";
import type { Env } from "../src/formatting.ts";
import { join } from "../src/spans.ts";
import type { Span } from "../src/spans.ts";
import { pyRstrip } from "../src/py.ts";
import type { Dict } from "../src/py.ts";
import { sha256Hex } from "../src/sha256.ts";
import {
  SETTLE_POLL_S, SETTLE_S, agentRecords, publishAgentOffsets, pyJoin,
  readTurnsSettled, writeAtomic,
} from "../src/claude_records_node.ts";
import type { Turn } from "../src/claude_records_node.ts";
import { calibration, seedLimitsSnapshot } from "../src/claude_calib_node.ts";
import { prepareClaudeReading } from "../src/claude_sources_node.ts";
import { stateDir } from "../src/sources_node.ts";
import {
  baseLimits, costFigures, detectGit, windowFor,
} from "../src/claude.ts";
import { projectName } from "../src/claude_render.ts";
import type { Workspace } from "../src/cells.ts";
import {
  receiptLines, receiptTurn, withEngineDuration,
} from "../src/receipt.ts";
import { LOG_NAME, logAppended, logLine } from "../src/modlog.ts";

/** What the command line gives. */
/** How long a Stop waits for the transcript to hold its turn's last
 * message, inside the hook's 20 s timeout: long enough for a write
 * behind, short enough that a miss does not hold the prompt. */
const WRITTEN_S = 3;

export type Options = { cols: number | null; plain: boolean;
  wait: number; usageSource: string; hide: string[] };

export function parseArgs(argv: readonly string[]): Options {
  const o: Options = { cols: null, plain: false, wait: WRITTEN_S,
    usageSource: CONFIG.usageSource, hide: [...CONFIG.hide] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = (): string => {
      if (i + 1 >= argv.length) throw new Error(a + " takes a value");
      return argv[++i];
    };
    if (a === "--cols") {
      const n = Number(next());
      if (!Number.isInteger(n) || n <= 0) throw new Error("--cols " + n);
      o.cols = n;
    } else if (a === "--plain") o.plain = true;
    else if (a === "--wait") {
      const n = Number(next());
      if (!(n >= 0)) throw new Error("--wait " + n);
      o.wait = n;
    }
    else if (a === "--usage-source") o.usageSource = next();
    else if (a === "--hide") o.hide.push(next());
    else throw new Error("unrecognized argument " + a);
  }
  return o;
}

// ════════════════════════════════════════════════════════════════════════════
// The terminal's width.
// ════════════════════════════════════════════════════════════════════════════

/** The columns of a tty device, or null: `stty size` with the device as
 * its stdin, where the Python asks TIOCGWINSZ, which Node has no call
 * for. */
function winsize(path: string): number | null {
  let fd: number;
  try {
    fd = fs.openSync(path, fs.constants.O_RDONLY | fs.constants.O_NOCTTY);
  } catch {
    return null;
  }
  try {
    const r = spawnSync("stty", ["size"], { stdio: [fd, "pipe", "ignore"],
      encoding: "utf8", timeout: 2_000 });
    const cols = Number((r.stdout ?? "").trim().split(/\s+/)[1]);
    return Number.isInteger(cols) && cols > 0 ? cols : null;
  } catch {
    return null;
  } finally {
    fs.closeSync(fd);
  }
}

/** term_cols: the hook's stdio are pipes and it has no controlling
 * terminal, but an ancestor, the `claude` process, owns the tty, so walk up
 * until one reports a tty and ask that device.  Null under `claude -p` and
 * anywhere else with no tty in the ancestry. */
export function termCols(): number | null {
  let p = process.ppid;
  for (let i = 0; i < 6; i++) {
    if (p <= 1) return null;
    let out: string[];
    try {
      out = (spawnSync("ps", ["-o", "tty=,ppid=", "-p", String(p)],
        { encoding: "utf8", timeout: 2_000 }).stdout ?? "").trim()
        .split(/\s+/);
    } catch {
      return null;
    }
    if (out.length < 2) return null;
    const [tty, parent] = out;
    if (tty && tty !== "?" && tty !== "??") {
      const cols = winsize("/dev/" + tty);
      if (cols) return cols;
    }
    p = Number(parent);
    if (!Number.isInteger(p)) return null;
  }
  return null;
}

// ════════════════════════════════════════════════════════════════════════════
// The reads.
// ════════════════════════════════════════════════════════════════════════════

/** The clock: CODING_AGENT_USAGE_LINE_NOW pinned, as the Python's
 * frozen_now reads it, else the wall's. */
function nowOf(env: Env): number {
  const v = Number(env.CODING_AGENT_USAGE_LINE_NOW ?? "");
  return env.CODING_AGENT_USAGE_LINE_NOW && Number.isFinite(v) ? v
    : Date.now() / 1000;
}

/** The context window the status line published for the session
 * (stored_ctx_window's file), or 0. */
function publishedWindow(state: string, session: string): number {
  if (!session) return 0;
  const path = pyJoin(state, "claude-context-" +
    sha256Hex("context\0" + session) + ".json");
  try {
    const v = Number(fs.readFileSync(path, "utf8").trim());
    return Number.isInteger(v) && v > 0 ? v : 0;
  } catch {
    return 0;
  }
}

/** 📦 🌿 for the 📊 🎮 row: detect_git in `cwd`, the project named as the
 * band names it, under CLAUDE_PROJECT_DIR when Claude Code sets it. */


/** A receipt row without the C_CHROME_CONT blanks `indented` put first. */
function unindent(row: Span[]): Span[] {
  const pad = " ".repeat(C_CHROME_CONT);
  const [first, ...rest] = row;
  return first?.text.startsWith(pad)
    ? [{ ...first, text: first.text.slice(pad.length) }, ...rest] : row;
}

/** What `holds` looks for: the message's first line, trimmed, to 60
 * characters, as JSON encodes it, which is how the transcript holds a text
 * block.  Trimmed and one line, so a payload that trims the message or
 * ends its lines otherwise still matches. */
export function needleOf(message: string): string {
  const first = message.trim().split(/\r?\n/)[0];
  return JSON.stringify(Array.from(first).slice(0, 60).join("")).slice(1, -1);
}

/** Whether the transcript's tail holds `message`, polled until it does or
 * `budget` seconds pass. */
async function holds(path: string, message: string, budget: number):
  Promise<boolean> {
  const needle = needleOf(message);
  const deadline = performance.now() + budget * 1000;
  for (;;) {
    let tail = "";
    try {
      const fd = fs.openSync(path, "r");
      try {
        const size = fs.fstatSync(fd).size;
        const n = Math.min(size, 4 << 20);
        const buf = Buffer.alloc(n);
        fs.readSync(fd, buf, 0, n, size - n);
        tail = buf.toString("utf8");
      } finally {
        fs.closeSync(fd);
      }
    } catch {
      return false;
    }
    if (tail.includes(needle)) return true;
    if (performance.now() >= deadline) return false;
    await new Promise((ok) => setTimeout(ok, 50));
  }
}

async function workspaceIn(cwd: string, env: Env): Promise<Workspace> {
  const git = await detectGit(async (args) => {
    const r = spawnSync("git", ["--no-optional-locks", ...args],
      { cwd: cwd || undefined, encoding: "utf8", timeout: 2_000 });
    return r.status === 0 ? r.stdout.replace(/\n+$/, "") : null;
  });
  return { project: projectName(git, env.CLAUDE_PROJECT_DIR || cwd),
    branch: git.branch, dirty: Boolean(git.dirty), dir: "", pr: "",
    style: "" };
}

/** Where the turn last printed is kept, per session, by a one-way digest
 * of its id. */
function reportedPath(state: string, session: string): string {
  return pyJoin(state, "reported-receipt-" +
    sha256Hex("usage-band-receipt\0" + session) + ".json");
}

/** The billed turn, as one key: its tag, its first stamp and how many
 * calls it has billed, so the same turn read again is the same key and a
 * turn that went on is not. */
function turnKey(turns: readonly Turn[]): string {
  const i = receiptTurn(turns);
  if (i < 0) return "";
  const t = turns[i];
  return JSON.stringify([t.prompt_id, t.turn_index, t.ts, t.calls]);
}

function lastReported(path: string): string {
  try {
    const d = JSON.parse(fs.readFileSync(path, "utf8")) as Dict;
    return typeof d.turn === "string" ? d.turn : "";
  } catch {
    return "";
  }
}

// ════════════════════════════════════════════════════════════════════════════
// The hook.
// ════════════════════════════════════════════════════════════════════════════

/** What the Stop prints, "" for nothing; `note` is told why there is no
 * receipt where there is a reason worth a log line. */
export async function receiptMessage(raw: string, o: Options, env: Env,
  note: (what: string) => void): Promise<string> {
  const pay = JSON.parse(raw) as Dict;
  const transcript = typeof pay.transcript_path === "string"
    ? pay.transcript_path : "";
  if (!transcript || !fs.statSync(transcript, { throwIfNoEntry: false })
    ?.isFile()) {
    note("no receipt: no transcript at " + JSON.stringify(transcript));
    return "";
  }
  const session = transcript.endsWith(".jsonl")
    ? transcript.slice(transcript.lastIndexOf("/") + 1, -".jsonl".length)
    : String(pay.session_id ?? "");
  const state = stateDir(env);
  // The agent files read once, so the offsets published are the extent of
  // the reading the receipt was made from.
  const last = typeof pay.last_assistant_message === "string"
    ? pay.last_assistant_message : "";
  if (last && !await holds(transcript, last, o.wait)) {
    // The text it looked for, so a miss can be told from a write behind.
    note("no receipt: the transcript lacks the turn's last message after " +
      o.wait + "s: " + JSON.stringify(needleOf(last).slice(0, 40)));
    return "";
  }
  const agents = agentRecords(transcript);
  const held = new Map<string, number>();
  const turns = await readTurnsSettled(transcript, SETTLE_S, SETTLE_POLL_S,
    agents, held, state);
  const key = turnKey(turns);
  const reported = reportedPath(state, session);
  if (!key || key === lastReported(reported)) return "";

  const now = nowOf(env);
  const prepared = await prepareClaudeReading(o.usageSource, CONFIG.account,
    CONFIG.period, { session }, now, env);
  const snap = seedLimitsSnapshot(baseLimits(prepared), prepared.reading);
  const home = env.HOME ?? "";
  const calib = calibration(snap, { projectsDir: (env.CLAUDE_CONFIG_DIR ||
    home + "/.claude") + "/projects", stateDir: state,
  version: CONFIG.version, now }, false);
  let fig = costFigures(turns, windowFor(turns,
    publishedWindow(state, session)), calib, snap, prepared, now,
  Intl.DateTimeFormat().resolvedOptions().timeZone || null);
  const ms = Number(pay.duration_ms ?? pay.durationMs);
  if (ms > 0) fig = withEngineDuration(fig, ms);

  const st = settings(env, CONFIG.markSpacing, CONFIG.subscriptDecimals);
  const cols = o.cols ?? termCols() ?? 80;
  const ws = await workspaceIn(typeof pay.cwd === "string" ? pay.cwd : "",
    env);
  // Laid out as the band is, at the terminal's width with its indent, then
  // printed without the indent, which Claude Code draws.
  const { head, rows } = receiptLines(st, fig, cols, o.hide, ws, true,
    C_CHROME_CONT);
  const text = [head, ...rows.map(unindent)]
    .map((l) => pyRstrip(join(l))).join("\n");
  // Kept before it is printed: a receipt printed twice is the worse
  // failure than one lost to a write that failed after it.
  writeAtomic(reported, JSON.stringify({ turn: key }) + "\n");
  publishAgentOffsets(transcript, agents, held, state);
  return "\n" + (o.plain ? stripAnsi(text) : text);
}

/** A line in the mod's log file, never failing. */
function logTo(env: Env, session: string, what: string, err?: unknown) {
  try {
    const path = pyJoin(stateDir(env), LOG_NAME);
    let old = "";
    try {
      old = fs.readFileSync(path, "utf8");
    } catch {
      // No log yet.
    }
    writeAtomic(path, logAppended(old, logLine(Date.now(), session,
      "receipt-hook: " + what, err)));
  } catch {
    // Unwritable: the line is lost, the Stop is not.
  }
}

async function main(): Promise<void> {
  const env = process.env as Env;
  let raw = "";
  let session = "?";
  try {
    raw = fs.readFileSync(0, "utf8");
    try {
      const id = (JSON.parse(raw) as Dict).session_id;
      if (typeof id === "string" && id) session = id;
    } catch {
      // Told below, where the payload is read for good.
    }
    const msg = await receiptMessage(raw, parseArgs(process.argv.slice(2)),
      env, (what) => logTo(env, session, what));
    if (msg) process.stdout.write(JSON.stringify({ systemMessage: msg }) + "\n");
  } catch (err) {
    logTo(env, session, "no receipt", err);
  }
}

// Run, not imported: Node before 24.2 has no import.meta.main.
if (process.argv[1] && fs.realpathSync(process.argv[1]) ===
  import.meta.filename) {
  await main();
}
