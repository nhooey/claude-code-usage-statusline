// Mock up the proposed layout: Claude Code's screen with all three readouts.
//
// A design aid, not a readout.  It draws a short transcript, the turn
// receipt, the band a mod would draw above the prompt, the prompt, the agent
// panel's rows and the mode line, from made-up figures, so the proposal can
// be looked at in a real terminal before any of it is built.  The status
// line is gone from it: the band replaces it.
//
// The proposal it draws, laid out by src/grid.ts (agents/plans/redesign.md
// has the design):
//
// - One column per metric, in one order, on every row of every readout:
//   model, 🛫, 💰, 🧠, 🧩, 🎯, ⌛ ⛳ 🤖 🔧 🚦, 🔋, 🪫, 💾.  The cells are the
//   agent panel's own, drawn by claude_subagent_render.ts's and
//   claude_render.ts's renderers, so the figures are formatted as the
//   readouts format them.
// - One scope per row, named by its label: 💳 the account, 🎤 the turn,
//   🤖💬 the main thread, 🎮 the session, and one row per agent.  The band
//   draws 🎤 and 🎮 only while the turn runs; once it ends, the receipt
//   carries them.
// - Every row's cells end RIGHT_EDGE columns short of the terminal's right
//   edge, where Claude Code draws the band's [-] button.
// - When the terminal is too narrow for every label to keep LABEL_MIN
//   columns, whole columns drop on every row together, in DROP_ORDER.
// - --hide takes a path, scope[.group[.metric]], with * for any one part:
//   "account", "*.work", "turn.time.eta".  A column hidden on every row it
//   could show on is removed; hidden on some, it is left blank there.
// - A label sheds its ranked parts whole (🎨, 🔀, 📁; 📅, 🕐) before it is
//   cut, and runs on over its own row's leading blank columns, up to its
//   first figure.  --labels clip stops every label where the first column
//   starts instead, for comparison.
// - The mod draws 🔻🔖 under the prompt as the turn starts, and the receipt
//   opens on 🔺🔖 when it ends.
//
// It lives under mod/ beside the code it draws with, and runs on node's
// own type stripping:
//
//   node mod/tools/layout-mockup.ts [--cols N] [--hide PATH ...]
//        [--receipt hook|mod] [--phase running|done] [--labels clip|spill]
//        [--grid fixed|rows] [--agents 0|1|2] [--part PART] [--plain]
//
// Only `main` reads the terminal (its profile, and its width when --cols
// is not given); everything under it is handed the Settings.
import { spawnSync } from "node:child_process";
import { closeSync, openSync } from "node:fs";
import {
  E_ACCT, E_BOT, E_COSTLINE, E_DATE, E_DIR, E_GIT_OK, E_PCT,
  E_PR, E_PROJ, E_RESET, E_SESS, E_SESSION, E_STY, E_TIME, E_TURN,
  E_TURN_AHEAD, E_TURN_ID, E_TURN_PAST, E_WEEK, RIGHT_EDGE,
} from "../src/spec.ts";
import {
  durFmt, humanize, padVal, seg, settings, stripAnsi, termCols,
} from "../src/formatting.ts";
import type { Env, Settings } from "../src/formatting.ts";
import { join, span } from "../src/spans.ts";
import type { Span, SpanLike } from "../src/spans.ts";
import { pyFormatF, pyRstrip } from "../src/py.ts";
import { renderCost, renderTokens } from "../src/claude_render.ts";
import {
  renderAgentCache, renderAgentCtx, renderAgentDiff, renderAgentElapsed,
  renderAgentEta, renderAgentLimit, renderAgentModel, renderAgentRate,
  renderAgentSplit, renderKind,
} from "../src/claude_subagent_render.ts";
import { chrome, draw, hidden, layout } from "../src/grid.ts";
import type { Piece, Row } from "../src/grid.ts";

const NOW = 1_792_000_000.0;

/** 🧠 for a turn: how much the context grew, in tokens and points. */
function ctxGrowth(st: Settings, tokens: number, points: number): Span[] {
  return [span(st.sCtx), span(padVal(st, 4, "+" + humanize(st, tokens)) +
    " " + padVal(st, 4, "+" + points + E_PCT), "F_PNK")];
}

/** A part of a row's label, with the path --hide names it by; see Piece. */
function piece(path: string, text: string, colour: string | null = null,
  drop = 0, dim = false): Piece {
  return { path, spans: [span(text, colour, dim)], drop };
}

/** The figures of one sample row, drawn into cells by `cells`. */
type Figures = {
  model?: [string, string]; rate?: number; cost?: number;
  ctx?: [number, number] | ["+", number, number];
  tok?: [number, number]; cache?: number; clock?: number;
  eta?: [number, number]; split?: [number, number, number];
  five?: number; week?: number; diff?: [number, number];
};

/** The figures drawn by the panel's renderers, one cell per key. */
function cells(st: Settings, f: Figures): { [key: string]: Span[] } {
  const out: { [key: string]: Span[] } = {};
  if (f.model) out.model = renderAgentModel(st, ...f.model);
  if (f.rate !== undefined) out.rate = renderAgentRate(st, f.rate);
  if (f.cost !== undefined) out.cost = renderCost(st, pyFormatF(f.cost, 4));
  if (f.ctx) {
    out.ctx = f.ctx[0] === "+" ? ctxGrowth(st, f.ctx[1], f.ctx[2])
      : renderAgentCtx(st, f.ctx[0], f.ctx[1]);
  }
  if (f.tok) out.tok = renderTokens(st, f.tok[0], f.tok[1]);
  if (f.cache !== undefined) out.cache = renderAgentCache(st, f.cache);
  if (f.clock !== undefined) {
    out.clock = renderAgentElapsed(st, f.clock * 1000, NOW);
  }
  if (f.eta) {
    out.eta = renderAgentEta(st, [NOW, f.eta[1]], f.eta[0] * 1000, NOW);
  }
  if (f.split) out.split = renderAgentSplit(...f.split);
  if (f.five !== undefined) {
    out.five = renderAgentLimit(st, E_SESS, "1", f.five, "F_LIM_SESS");
  }
  if (f.week !== undefined) {
    out.week = renderAgentLimit(st, E_WEEK, "1", f.week, "F_LIM_WEEK",
      true, false, 4);
  }
  if (f.diff) {
    out.diff = renderAgentDiff(st,
      { lines_added: f.diff[0], lines_removed: f.diff[1] });
  }
  return out;
}

const TURN_START = NOW - 4 * 60, SESSION_START = NOW - 9 * 3600;

/** The receipt's first line: which turn the rows under it bill, by the
 * head of its promptId and Claude Code's turn index, and when it ended. */
const RECEIPT_HEAD = E_TURN_PAST + E_TURN_ID + " 8f37748e #12  " + E_DATE +
  " 2026-10-19  " + E_TIME + " 13:06:02";
/** The line the mod draws under the prompt as the turn starts: the same
 * tag, 🔻 pointing down at the turn it opens, and when it started. */
const START_TAG = E_TURN_AHEAD + E_TURN_ID + " 8f37748e #12  " + E_DATE +
  " 2026-10-19  " + E_TIME + " 13:02:00";

/** The sample rows: the band's, the receipt's and the panel's. */
type Sample = {
  account: Row; turn: Row; main: Row; session: Row;
  receipt: Row[]; agents: Row[];
};

/** One sample session: a turn that asked why the build is slow, the main
 * thread answering it, and two agents it started. */
export function sample(st: Settings): Sample {
  const account: Row = { scope: "account", label: [
    piece("name.label", E_ACCT + " account  "),
    piece("plan.reset", E_SESS + " " + E_RESET + " " +
      durFmt(st, 6.7 * 60) + "  " + E_WEEK + " " + E_RESET + " " +
      durFmt(st, 1.8 * 86400) + "  ", null, 0, true),
    piece("clock.date", E_DATE + " 2026-10-19  ", null, 2, true),
    piece("clock.time", E_TIME + " 13:06:02", null, 3, true)],
  cells: cells(st, { five: 15.0, week: 87.0 }) };
  const turn: Row = { scope: "turn", label: [
    piece("name.label", E_TURN + " "),
    piece("chat.prompt", "Why is the build slow?", "F_CHAT_B")],
  cells: cells(st, { cost: 0.21, ctx: ["+", 34_000, 3],
    tok: [28_000, 7_100], cache: 95, clock: TURN_START,
    eta: [TURN_START, 120], split: [240, 150, 60], five: 0.03, week: 0.05,
    diff: [12, 3] }) };
  const main: Row = { scope: "main", label: [
    piece("name.label", E_BOT + " "),
    piece("chat.reply",
      "The test step takes 80٪ of the build: Jest runs serially",
      "F_CHAT_B")],
  cells: cells(st, { model: ["claude-opus-5-5", "high"], cost: 92.0,
    ctx: [115_000, 1_000_000], tok: [2_100_000, 640_000], cache: 98,
    clock: SESSION_START, eta: [TURN_START, 120],
    split: [9 * 3600, 4 * 3600, 3 * 3600], five: 0.9, week: 2.1,
    diff: [3100, 180], rate: 220 }) };
  const session: Row = { scope: "session", label: [
    piece("name.label", E_SESSION + " session  "),
    piece("workspace.project", E_PROJ + "app ", "F_BLU"),
    piece("workspace.branch", E_GIT_OK + "main  ", "F_GRN"),
    piece("workspace.dir", E_DIR + "~/src/app/web  ", "F_BLU", 3),
    piece("workspace.pr", E_PR + "#418  ", "F_CYN", 2),
    piece("workspace.style", E_STY + "Explanatory", "F_CYN", 1)],
  cells: cells(st, { cost: 115.0, tok: [2_700_000, 841_000], cache: 98,
    clock: SESSION_START, split: [9 * 3600, 4 * 3600, 3 * 3600], five: 1.2,
    week: 3.8, diff: [3400, 214] }) };
  const agents: Row[] = [
    { scope: "agent", depth: 1, label: [
      piece("name.kind", renderKind("general-purpose", "") + "🟢 "),
      piece("name.label", "Port renderer  ", "F_BLU"),
      piece("chat.doing", "Editing claude_render.py", "F_CHAT_B")],
    cells: cells(st, { model: ["claude-opus-5-5", "high"], cost: 0.4,
      ctx: [124_000, 1_000_000], tok: [66_000, 3_600], cache: 93,
      clock: NOW - 14 * 60, eta: [NOW - 14 * 60, 180],
      split: [14 * 60, 5 * 60, 60], five: 0.08, week: 0.10, diff: [48, 9],
      rate: 1_500 }) },
    { scope: "agent", depth: 2, label: [
      piece("name.kind", renderKind("Explore", "") + "🟢 "),
      piece("name.label", "Find callers of seg()  ", "F_BLU"),
      piece("chat.doing", "Searching", "F_CHAT_B")],
    cells: cells(st, { model: ["claude-sonnet-5-5", "medium"], cost: 0.1,
      ctx: [48_000, 200_000], tok: [24_000, 1_000], cache: 90,
      clock: NOW - 8.3 * 60, eta: [NOW - 8.3 * 60, 150],
      split: [8.3 * 60, 2 * 60, 0], five: 0.03, week: 0.04, diff: [0, 0],
      rate: 340 }) },
  ];
  // The receipt is the band's 🎤 and 🎮 rows as they stood when the turn
  // ended, behind the receipt's 📊.
  const receipt = [
    { ...turn, label: [piece("name.receipt", E_COSTLINE + " "),
      ...turn.label] },
    { ...session, label: [piece("name.receipt", E_COSTLINE + " "),
      ...session.label] },
  ];
  return { account, turn, main, session, receipt, agents };
}

/** The 🤖💬 row mid-turn: it says what the thread is doing, not its
 * reply. */
export function runningMain(main: Row): Row {
  return { ...main, label: [main.label[0],
    piece("chat.doing", "Reading jest.config.js", "F_CHAT_B")] };
}

type Readouts = {
  band: Span[][]; receipt: Span[][]; agents: [Row, Span[]][];
};

/** The three readouts' rows: the band's, the receipt's and the panel's. */
export function readouts(st: Settings, cols: number,
  patterns: readonly string[], phase = "done", spill = true,
  grid = "fixed", depth = 2): Readouts {
  const s = sample(st);
  const every = [s.account, s.turn, s.main, s.session]
    .filter((r) => !hidden(patterns, r.scope));
  const receipt = s.receipt.filter((r) => !hidden(patterns, r.scope));
  const possible = s.agents.filter((r) => !hidden(patterns, r.scope));
  const agents = possible.filter((r) => r.depth! <= depth);
  // Laid out over every row either phase can draw, so the columns do not
  // move when the turn ends and its rows leave the band.
  const keys = grid === "fixed"
    ? layout(st, [...every, ...receipt, ...possible], cols, patterns)
    : layout(st, [...every, ...receipt, ...agents], cols, patterns, false);
  // The band carries the turn and the session while the turn runs.  Once
  // it ends the receipt carries them, and the band keeps the account and
  // the main thread.
  let band = phase === "running" ? every
    : every.filter((r) => r.scope === "account" || r.scope === "main");
  if (phase === "running") {
    band = band.map((r) => r !== s.main ? r : runningMain(r));
  }
  const d = (r: Row): Span[] => draw(st, r, keys, cols, patterns, spill);
  return { band: band.map(d), receipt: receipt.map(d),
    agents: agents.map((r) => [r, d(r)]) };
}

/** A drawn line as the terminal gets it, less its trailing blanks. */
function line(x: SpanLike): string {
  return pyRstrip(join(x));
}

const dim = (t: string): Span => span(t, null, true);

export function screen(st: Settings, cols: number,
  patterns: readonly string[], receiptBy = "hook", phase = "done",
  spill = true, grid = "fixed", depth = 2): string {
  const rule = "─".repeat(cols);
  const parts = readouts(st, cols, patterns, phase, spill, grid, depth);
  const out: SpanLike[] = [
    [dim("❯ "), "Why is the build slow?"],
    [dim("  " + START_TAG)],
    "",
    "⏺ Bash(npm run build -- --profile)",
    "  ⎿  compile 31s · bundle 18s · test 3m 12s",
    "",
  ];
  if (phase === "running") {
    out.push("⏺ Read(jest.config.js)", "",
      [span("✻ ", "F_PNK"), "Pondering… (3m 48s · esc to interrupt)"], "");
  } else {
    out.push(
      "⏺ The test step takes 80٪ of the build: Jest runs the suites serially",
      "  because maxWorkers is 1 in jest.config.js.", "");
    if (receiptBy === "hook") {
      // Claude Code draws a Stop hook's systemMessage behind "Stop says: ",
      // and no setting changes it, so the receipt opens on a newline.
      out.push([dim("Stop says: ")], RECEIPT_HEAD, ...parts.receipt, "",
        [dim("✻ Worked for 4m 2s · done 1:06 PM")]);
    } else {
      // The mod redraws the TurnDuration line instead, with the receipt's
      // head on it and its rows under it, and the Stop hook prints nothing.
      out.push([dim("✻ Worked for 4m 2s · "), RECEIPT_HEAD],
        ...parts.receipt);
    }
  }
  const band: SpanLike[] = [...parts.band];
  if (band.length) {
    // Claude Code's [-] button, on the band's first row.
    band[0] = [...seg(st, cols - RIGHT_EDGE, parts.band[0]), "  ",
      dim("[-]")];
  }
  out.push(...band, [dim(rule)], "❯ ", [dim(rule)],
    [dim("  -- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle)")]);
  if (parts.agents.length) {
    // The panel sits under the mode line, after a blank one, and opens on
    // Claude Code's own main row, which no hook draws.
    out.push("", [dim("  ⏺ main")], ...parts.agents.map(([, r]) => r));
  }
  return out.map(line).join("\n");
}

const USAGE = "usage: layout-mockup.ts [--cols N] [--hide PATH] " +
  "[--receipt {hook,mod}] [--phase {running,done}] [--labels {spill,clip}] " +
  "[--grid {fixed,rows}] [--agents {0,1,2}] " +
  "[--part {screen,band,receipt,start,panel}] [--plain]";

type Options = {
  cols: number | null; hide: string[]; receipt: string; phase: string;
  labels: string; grid: string; agents: number; part: string;
  plain: boolean;
};

/** The command line, as the Python's argparse took it. */
function parse(argv: readonly string[]): Options {
  const o: Options = { cols: null, hide: [], receipt: "mod", phase: "done",
    labels: "spill", grid: "fixed", agents: 2, part: "screen", plain: false };
  const choices: { [k: string]: readonly string[] } = {
    receipt: ["hook", "mod"], phase: ["running", "done"],
    labels: ["spill", "clip"], grid: ["fixed", "rows"],
    agents: ["0", "1", "2"],
    part: ["screen", "band", "receipt", "start", "panel"],
  };
  const fail = (msg: string): never => {
    process.stderr.write(USAGE + "\nlayout-mockup.ts: error: " + msg + "\n");
    process.exit(2);
  };
  for (let i = 0; i < argv.length; i++) {
    let a = argv[i], v: string | undefined;
    if (a === "-h" || a === "--help") {
      process.stdout.write(USAGE + "\n");
      process.exit(0);
    }
    if (a === "--plain") {
      o.plain = true;
      continue;
    }
    const eq = a.indexOf("=");
    if (a.startsWith("--") && eq > 0) [a, v] = [a.slice(0, eq), a.slice(eq + 1)];
    const name = a.slice(2);
    if (!["cols", "hide", ...Object.keys(choices)].includes(name)) {
      fail("unrecognized arguments: " + a);
    }
    if (v === undefined) {
      if (i + 1 >= argv.length) fail("argument " + a + ": expected one argument");
      v = argv[++i];
    }
    if (name === "cols") {
      if (!/^\s*[-+]?\d+\s*$/.test(v!)) fail("argument --cols: invalid int value: '" + v + "'");
      o.cols = parseInt(v!, 10);
    } else if (name === "hide") {
      o.hide.push(v!);
    } else if (!choices[name].includes(v!)) {
      fail("argument --" + name + ": invalid choice: '" + v + "'");
    } else if (name === "agents") {
      o.agents = Number(v);
    } else {
      (o as unknown as { [k: string]: string })[name] = v!;
    }
  }
  return o;
}

/** The terminal's width, walked up from this process's parent as
 * formatting.py's term_cols does, the device asked through stty. */
function terminalCols(): number | null {
  const ps = (pid: number): string | null => {
    const got = spawnSync("ps", ["-o", "tty=,ppid=", "-p", String(pid)],
      { encoding: "utf8" });
    return got.error ? null : got.stdout;
  };
  const winsize = (path: string): number | null => {
    let fd: number;
    try {
      fd = openSync(path, "r");
    } catch {
      return null;
    }
    try {
      const got = spawnSync("stty", ["size"],
        { stdio: [fd, "pipe", "ignore"], encoding: "utf8" });
      const cols = Number((got.stdout || "").trim().split(/\s+/)[1]);
      return cols > 0 ? cols : null;
    } finally {
      closeSync(fd);
    }
  };
  return termCols(process.ppid, ps, winsize);
}

/** The mockup for `argv`, as it prints; `env` is the terminal's. */
export function run(argv: readonly string[], env: Env,
  cols: () => number | null = terminalCols): string {
  const a = parse(argv);
  const st = settings(env);
  const width = a.cols ?? cols() ?? 160;
  const spill = a.labels === "spill";
  let text: string;
  if (a.part === "screen") {
    text = screen(st, width, a.hide, a.receipt, a.phase, spill, a.grid,
      a.agents);
  } else if (a.part === "start") {
    text = START_TAG;
  } else {
    const parts = readouts(st, width, a.hide, a.phase, spill, a.grid,
      a.agents);
    let rows: SpanLike[];
    if (a.part === "band") rows = parts.band;
    else if (a.part === "receipt") rows = [RECEIPT_HEAD, ...parts.receipt];
    // The agent rows without the panel's chrome, which Claude Code draws.
    else rows = parts.agents.map(([r, row]) => row.slice(chrome(r.depth).length));
    text = rows.map(line).join("\n");
  }
  return (a.plain ? stripAnsi(text) : text) + "\n";
}

if (import.meta.main) {
  process.stdout.write(run(process.argv.slice(2), process.env));
}
