// The band above the prompt: a status figures document drawn as the grid's
// rows.
//
// agents/plans/redesign.md has the design, and its "Where each row's
// figures come from" says which field each cell reads; the comments over
// each row's builder here say the same, field by field.  The band draws
// four rows while a turn runs, 💳 the account, 🎤 the turn, 🤖💬 the main
// thread and 🎮 the session, and drops to 💳 and 🤖💬 when it ends, since
// the receipt (receipt.ts) then carries the turn and the session.
//
// Pure: everything comes from the document, and what the mod keeps itself
// comes in as an argument: HOME, to show the working directory as "~", and
// 🛫, the main thread's token rate, which the mod works out in memory from
// successive documents (decision 1).  The clock's cells draw `clock.now`
// in the process's TZ, which the edge sets from `clock.tz` before drawing,
// as for claude_cost.ts.
import {
  CHROME_DEPTH, E_ACCT, E_DATE, E_PROJ, E_TOOL, E_WORK, GRID_CELLS, MAG_DUR_S, QUIET_WARN_S,
  RIGHT_EDGE,
} from "./spec.ts";
import { durFmt, magDim, padVal, visWidth } from "./formatting.ts";
import type { Settings } from "./formatting.ts";
import { span } from "./spans.ts";
import type { Span } from "./spans.ts";
import { pyLen, pyRstrip, pySlice } from "./py.ts";
import { pyFloat } from "./sources.ts";
import {
  W_CACHE_READ, W_CACHE_WRITE, etaFinish, squash,
} from "./claude_records.ts";
import type { Git, Payload, Transcript, Turn } from "./claude_records.ts";
import type { Accounting } from "./claude_calib.ts";
import {
  ETA_LIVE_S, inheritEta, mainDoing, projectName,
} from "./claude_render.ts";
import {
  decodeGit, decodeLimits, decodePayload, decodeTranscript,
} from "./figures.ts";
import { decodeTurn } from "./claude_cost.ts";
import {
  CELLS, accountLabel, cacheRate, hms, mainLabel, sessionLabel, turnLabel,
  untilReset, ymd,
} from "./cells.ts";
import type { Workspace } from "./cells.ts";
import { draw, hidden, layout } from "./grid.ts";
import type { Piece, Row } from "./grid.ts";
import type { Dict } from "./py.ts";

/** Whether a turn is running, which draws all four rows, or done. */
export type Phase = "running" | "done";

/** What the band is drawn with besides the document: HOME, the main
 * thread's 🛫 (tokens a second, or null for no reading yet) and the
 * phase, which picks what the 🤖💬 label says. */
export type BandOpts = {
  readonly home: string;
  readonly rate: number | null;
  readonly phase: Phase;
  /** Blank columns before each row's label (`indented`). */
  readonly indent?: number;
  /** Columns the container the rows are drawn in already stands in from
   * the terminal's left edge: each row is drawn that much narrower, on the
   * columns laid out at the full width, so its cells still land on the
   * agent panel's columns and it ends where they end.  None where
   * absent. */
  readonly inset?: number;
  /** The rows that stay where they are drawn once a turn ends; see
   * RowName.  None where absent. */
  readonly sticky?: readonly RowName[];
};

/** A row of the band as the configuration names it: 🎤 "turn", 🤖
 * "agent", 🎮 "session".  A sticky row stays where the band draws it once
 * a turn ends, and the receipt stamps the others, any of the three either
 * way (asked 2026-10-20). */
export type RowName = "turn" | "agent" | "session";

/** Where the band's rows are drawn: "above" the prompt, or under its
 * "hint", the footer line. */
export type BandPlace = "above" | "hint";
export const ROW_NAMES: readonly RowName[] = ["turn", "agent", "session"];

/** The scopes of the rows `sticky` names. */
export function stickyScopes(sticky: readonly RowName[] = []): string[] {
  return sticky.map((n) => n === "agent" ? "main" : n);
}

/** The band's four rows, whichever the phase draws. */
export type BandRows = {
  readonly account: Row;
  readonly turn: Row;
  readonly main: Row;
  readonly session: Row;
};

type Cells = { [key: string]: Span[] };

// ════════════════════════════════════════════════════════════════════════════
// The fixed grid.
// ════════════════════════════════════════════════════════════════════════════

const ALL = GRID_CELLS.map((c) => c.key);

/** The columns each scope can draw, whatever its figures: 🛫 and the
 * model are state, on agent-shaped rows only; the session has no context
 * and no ⛳ of its own; the account none, its plan being on its label.  The receipt's rows are
 * the turn's and the session's. */
export const SCOPE_KEYS: { readonly [scope: string]: readonly string[] } = {
  account: [],
  turn: ALL.filter((k) => k !== "model" && k !== "rate"),
  main: ALL,
  session: ALL.filter((k) => !["model", "rate", "ctx", "eta"].includes(k)),
  agent: ALL,
};

/** A row with every column its scope can draw and nothing in them. */
function skeleton(scope: string, depth?: number): Row {
  return { scope, ...(depth === undefined ? {} : { depth }), label: [],
    cells: Object.fromEntries(SCOPE_KEYS[scope].map((k) => [k, []])) };
}

/** `row` with `n` blank columns before its label, as the label's first
 * piece: the label's room is `n` less, so the columns stay where an
 * unindented row's are, and only on a terminal too narrow for the label
 * is the indent cut.  Claude Code indents each line of a Stop message
 * C_CHROME_CONT columns; the band takes the same indent, so the two
 * readouts start at one column. */
export function indented(row: Row, n: number): Row {
  return n ? { ...row, label: [{ path: "indent",
    spans: [span(" ".repeat(n))], drop: 0 }, ...row.label] } : row;
}

/** The columns at `cols` under `hide`, laid out over every row the band,
 * the receipt and the panel can draw, agents to CHROME_DEPTH: they follow
 * from the width and --hide alone, so no column moves when the turn ends,
 * a document lacks a figure or an agent starts. */
export function fixedKeys(st: Settings, cols: number,
  hide: readonly string[]): string[] {
  const rows = [skeleton("account"), skeleton("turn"), skeleton("main"),
    skeleton("session")];
  for (let d = 1; d <= CHROME_DEPTH; d++) rows.push(skeleton("agent", d));
  return layout(st, rows.filter((r) => !hidden(hide, r.scope)), cols, hide);
}

// ════════════════════════════════════════════════════════════════════════════
// Shared by the rows.
// ════════════════════════════════════════════════════════════════════════════

/** A turn's ▴, weighed as cost_group weighs it, and its ▾. */
export function turnTokens(t: Turn): [number, number] {
  return [t.fresh + W_CACHE_WRITE * t.cache_write +
    W_CACHE_READ * t.cache_read, t.out];
}

/** A turn's 🎯, as cost_group works it out. */
export function turnCache(t: Turn): number {
  return cacheRate(t.cache_read, t.fresh + t.cache_write + t.cache_read);
}

/** 🤖 🔧 🚦 off an accounting's seconds, drawn as proportions of
 * themselves: agents running side by side put more agent-seconds in it
 * than the wall clock has (decision 5). */
export function accountingSplit(a: Accounting): Span[] {
  return CELLS.split(a.model_s + a.tool_s + a.blocked_s, a.model_s,
    a.tool_s);
}

/** The plan cells of an accounting's shares, under the plan reading's
 * percentages, "" where there is none: a share the accounting could not
 * work out is drawn "?", and with no reading the cells are blank. */
export function shareCells(st: Settings, a: Accounting, sessPct: string,
  weekPct: string): Cells {
  return { five: CELLS.five(st, sessPct, a.sess_share),
    week: CELLS.week(st, weekPct, a.week_share) };
}

/** The main thread's ⛳, as today's ⌛ row draws it: its own last report,
 * pushed out by a live agent's (inherit_eta), counted from the turn's
 * prompt; nothing with no transcript. */
function threadEta(st: Settings, tr: Transcript, now: number): Span[] {
  if (!tr.start_s) return [];
  const live = tr.agent_etas
    .filter(([, last]) => last !== null && now - last <= ETA_LIVE_S)
    .map(([f]) => f);
  const shown = inheritEta(tr.eta, live, tr.turn_s);
  // Signed off: its own report is zero and no live agent pushed the
  // finish past it.
  const signedOff = tr.eta.length > 0 && tr.eta[1] === 0 &&
    shown.length > 0 && etaFinish(shown)! <= etaFinish(tr.eta)! + 1e-6;
  return CELLS.eta(st, shown, tr.turn_s || null, now, signedOff);
}

/** 🎤's ⛳: the turn's own last report alone, and nothing before the turn
 * has one; 🤖's (threadEta) is what live agents push out (asked
 * 2026-10-19). */
function turnEta(st: Settings, tr: Transcript, now: number): Span[] {
  if (!tr.start_s || !tr.eta.length) return [];
  return CELLS.eta(st, tr.eta, tr.turn_s || null, now, tr.eta[1] === 0);
}

/** The working directory under `home` as "~", as render_status shows it. */
function homeDir(dir: string, home: string): string {
  if (dir === home) return "~";
  if (home && dir.startsWith(home + "/")) {
    return "~" + pySlice(dir, pyLen(home));
  }
  return dir;
}

/** `dir`, as homeDir draws it, with the project's root, `root`, drawn as
 * 📦, the project's own mark, under its parent (asked 2026-10-19):
 * "~/git/📦/mod" for its mod/ folder. */
function projectDir(dir: string, root: string, home: string): string {
  const r = pyRstrip(root, "/");
  if (!r || (dir !== r && !dir.startsWith(r + "/"))) return homeDir(dir, home);
  const parent = r.slice(0, r.lastIndexOf("/"));
  return (parent ? homeDir(parent, home) : "") + "/" + E_PROJ +
    pySlice(dir, pyLen(r));
}

/** Where the session works, off the document's `git` and `payload`.  The
 * receipt draws the 📦 🌿 of the band's last one (decision 7). */
export function workspaceOf(fig: Dict, home: string): Workspace {
  const pay: Payload = decodePayload(fig.payload);
  const git: Git = decodeGit(fig.git);
  const style = pay.output_style;
  const pr = pay.pr_number;
  return {
    project: projectName(git, pay.project_dir),
    branch: git.branch,
    dirty: Boolean(git.dirty),
    dir: git.in_git
      ? projectDir(pay.current_dir, git.main_root || git.toplevel, home)
      : homeDir(pay.current_dir, home),
    pr: pr && pr !== "null" ? pr : "",
    style: style && style !== "default" && style !== "null" ? style : "",
  };
}

// ════════════════════════════════════════════════════════════════════════════
// The rows.
// ════════════════════════════════════════════════════════════════════════════

/** 💳: the plan's two windows, `limits.session_pct` and `weekly_pct` as the
 * source gave them, and on the label the time to each reset,
 * `limits.session_reset` and `weekly_reset`, then 📅 🕐 off `clock.now`. */
function accountRow(st: Settings, fig: Dict, now: number): Row {
  const lim = decodeLimits(fig.limits);
  // The resets as the epochs the document carries, not the minute stamps
  // decodeLimits makes of them.
  const raw = fig.limits as Dict;
  const reset = (k: string): string | null =>
    untilReset(st, raw[k] as number | null, now);
  const pct = (s: string): number | null => {
    const v = pyFloat(s);
    return v === null || Number.isNaN(v) ? null : v;
  };
  return { scope: "account", label: accountLabel(st,
    pct(lim.session_pct), pct(lim.weekly_pct), reset("session_reset"),
    reset("weekly_reset"), ymd(now), hms(now)), cells: {} };
}

/** 🎤: the turn opened last, `open_turn`, with `accounting.open_turn`
 * (decision 8), so a fresh turn reads zeros; its prompt is the turn's
 * opener.  🧠 is how much the context grew in it, ⌛ how long it has run,
 * ⛳ the main thread's.  With no open turn, the prompt's placeholder and
 * the ⛳ alone. */
function turnRow(st: Settings, fig: Dict, tr: Transcript, now: number,
  sessPct: string, weekPct: string, opts: BandOpts): Row {
  const raw = fig.open_turn as Dict | null;
  const acc = (fig.accounting as Dict).open_turn as Accounting | null;
  const pay = decodePayload(fig.payload);
  // The model and effort, and 🛫, are the turn's (decided 2026-10-19), not
  // the 🤖 row's: 🎤 is drawn only while the turn runs.  While a tool runs
  // no tokens stream, so 🛫's column says how long the tool has run.
  const cells: Cells = {
    model: CELLS.model(st, pay.model_id || pay.model, pay.effort),
    rate: toolCell(st, tr, now) ??
      CELLS.rate(st, opts.phase === "running" ? opts.rate : null),
    eta: turnEta(st, tr, now),
  };
  if (!raw) return { scope: "turn", label: turnLabel(""), cells };
  const t = decodeTurn(raw);
  const [up, down] = turnTokens(t);
  Object.assign(cells, {
    ctx: CELLS.growth(st, t.dctx, Math.trunc(fig.context_window as number)),
    tok: CELLS.tok(st, up, down),
    cache: CELLS.cache(st, turnCache(t)),
    clock: CELLS.clock(st, t.dur_s),
  });
  if (acc) {
    Object.assign(cells, {
      cost: CELLS.cost(st, acc.cost_usd),
      split: accountingSplit(acc),
      ...shareCells(st, acc, sessPct, weekPct),
      diff: CELLS.diff(st, acc.lines_added, acc.lines_removed),
    });
  }
  // The opener as the transcript holds it, newlines and all: a queued or
  // pasted prompt, or a message from another session, runs to many lines.
  // squash folds it to one, as the status line's 🎤 text is.
  return { scope: "turn", label: turnLabel(squash(t.text)), cells };
}

/** 🔧 and how long the main thread's tool has run, in 🛫's column, padded
 * to the rate's width; null while no tool runs. */
function toolCell(st: Settings, tr: Transcript, now: number): Span[] | null {
  const [mark, since] = mainDoing(tr);
  if (mark !== E_TOOL) return null;
  const secs = Math.max(0.0, now - since);
  return [span(E_TOOL + " "), span(padVal(st, 4, durFmt(st, secs)), "F_PRW",
    magDim(secs, MAG_DUR_S))];
}

/** What the main thread is doing, as today's Doing cell says it: the mark
 * of its state and how long it has been in it, amber once it has worked
 * QUIET_WARN_S without a word.  Null on an offline read, and while a tool
 * runs, which 🎤's 🛫 column says (toolCell). */
function doingCell(st: Settings, tr: Transcript, now: number):
  Span[] | null {
  const [mark, since] = mainDoing(tr);
  if (!mark || mark === E_TOOL) return null;
  const secs = Math.max(0.0, now - since);
  const amber = mark === E_WORK && secs >= QUIET_WARN_S;
  return [span(mark + " "), span(padVal(st, 4, durFmt(st, secs)),
    amber ? "F_AMB" : "F_PRW", !amber && magDim(secs, MAG_DUR_S))];
}

/** 🤖: the main thread alone, before its agents' figures are added.  The
 * model and effort and 🛫 are on 🎤 (turnRow), not here; 💰 🔋 🪫
 * `accounting.own`, its compactions in, the 💰 marked an estimate by
 * `own_est` (decision 2); 🧠 its context, `ctx_est` marking an estimate;
 * 🧩 🎯 `own_tok_*` and `own_cache_pct`; ⌛ its age from `start_s` and the
 * split off `busy_s`, `tool_s` and `blocked_s`, as today's ⌛ row
 * partitions it; 💾 its own lines.  Running, the label says what it is
 * doing before its last reply. */
function mainRow(st: Settings, fig: Dict, tr: Transcript, now: number,
  sessPct: string, weekPct: string, opts: BandOpts): Row {
  const pay = decodePayload(fig.payload);
  const own = (fig.accounting as Dict).own as Accounting | null;
  const win = Math.trunc(fig.context_window as number);
  const cells: Cells = { eta: threadEta(st, tr, now) };
  if (own) {
    Object.assign(cells, {
      cost: CELLS.cost(st, own.cost_usd, tr.own_est),
      ...shareCells(st, own, sessPct, weekPct),
    });
  }
  if (tr.start_s) {
    // renderElapsed's partition of the age: a blocking prompt moves from
    // the busy clock to the idle one.
    const age = Math.max(0.0, now - tr.start_s);
    const wait = Math.min(Math.max(0.0, tr.blocked_s), tr.busy_s);
    Object.assign(cells, {
      ctx: CELLS.ctx(st, tr.ctx_tokens, win, tr.ctx_est),
      tok: CELLS.tok(st, tr.own_tok_up, tr.own_tok_down),
      cache: CELLS.cache(st, tr.own_cache_pct),
      clock: CELLS.clock(st, age),
      split: CELLS.split(age, Math.max(0.0, tr.busy_s - wait - tr.tool_s),
        tr.tool_s),
      diff: CELLS.diff(st, tr.lines_added, tr.lines_removed),
    });
  }
  // Running, what it is doing and for how long in 🛫's column, as 🎤 draws
  // a running tool's (asked 2026-10-19); the model's column left blank, so
  // the reply ends where 🎤's model starts.
  const doing = opts.phase === "running" ? doingCell(st, tr, now) : null;
  Object.assign(cells, { model: [], rate: doing ?? [] });
  return { scope: "main", label: mainLabel(tr.asst_text), cells };
}

/** 🎮: the main thread and every agent, summed.  💰 💾 the accounting's
 * (decision 4); ⌛ the session's age from `accounting.session.start_s`
 * and 🤖 🔧 🚦 its agent-seconds (decision 5); 🧩 🎯 the transcript's
 * session totals; the workspace on the label. */
function sessionRow(st: Settings, fig: Dict, tr: Transcript, now: number,
  sessPct: string, weekPct: string, home: string): Row {
  const acc = (fig.accounting as Dict).session as Accounting | null;
  const cells: Cells = {};
  if (tr.start_s) {
    Object.assign(cells, {
      tok: CELLS.tok(st, tr.tok_up, tr.tok_down),
      cache: CELLS.cache(st, tr.cache_pct),
    });
  }
  if (acc) {
    Object.assign(cells, {
      cost: CELLS.cost(st, acc.cost_usd),
      split: accountingSplit(acc),
      ...shareCells(st, acc, sessPct, weekPct),
      diff: CELLS.diff(st, acc.lines_added, acc.lines_removed),
    });
    if (acc.start_s !== null && acc.start_s !== undefined) {
      cells.clock = CELLS.clock(st, now - acc.start_s);
    }
  }
  return { scope: "session", label: sessionLabel(workspaceOf(fig, home)),
    cells };
}

/** The band's four rows from a status figures document. */
export function bandRows(st: Settings, fig: Dict, opts: BandOpts):
  BandRows {
  const now = (fig.clock as Dict).now as number;
  const tr = decodeTranscript(fig.transcript);
  const lim = decodeLimits(fig.limits);
  const [sp, wp] = [lim.session_pct, lim.weekly_pct];
  return {
    account: accountRow(st, fig, now),
    turn: turnRow(st, fig, tr, now, sp, wp, opts),
    main: mainRow(st, fig, tr, now, sp, wp, opts),
    session: sessionRow(st, fig, tr, now, sp, wp, opts.home),
  };
}

/** The rows a phase draws, top to bottom: 🎤, 🤖💬 and 🎮 while a turn
 * runs, the order the receipt stamps them in (asked 2026-10-20), and once
 * it ends the `sticky` ones, which the receipt does not stamp: none by
 * default (asked 2026-10-20).  💳 is not among them: it is drawn
 * on the footer under the prompt, right-aligned, as `accountText` gives it
 * (decided 2026-10-19). */
export function phaseRows(rows: BandRows, phase: Phase,
  sticky: readonly RowName[] = []): Row[] {
  const all = [rows.turn, rows.main, rows.session];
  if (phase === "running") return all;
  const kept = stickyScopes(sticky);
  return all.filter((r) => kept.includes(r.scope));
}

/** The 💳 row's label as one line of plain text after the workspace,
 * "📦claude-code-usage-statusline 🌿master  📁~/git/📦  💳 🔋 1٪ 🔜 4.8h
 * 🪫 49٪ 🔜 9.8h  📅 2026-10-19  🕐 22:12:44", each piece hidden by its own
 * path, the workspace's under `account.workspace`, with `home` shortening
 * the 📁 directory as the band's does; ""
 * under the hide path `account`.  The footer it is drawn on takes a string,
 * so it keeps none of the row's colours. */
export function accountText(st: Settings, fig: Dict,
  hide: readonly string[], home = ""): string {
  return accountPieces(st, fig, hide, home)
    .flatMap((p) => p.spans.map((s) => s.text)).join("").trim();
}

/** accountText's pieces, in their colours; none under the hide path
 * `account`. */
function accountPieces(st: Settings, fig: Dict, hide: readonly string[],
  home: string): Piece[] {
  if (hidden(hide, "account")) return [];
  const now = (fig.clock as Dict).now as number;
  // 📦 the project, 🌿 the branch and 📁 the directory first, as 🎮's
  // label draws them (asked 2026-10-20), each hidden by its own path.
  const shown: Piece[] = sessionLabel(workspaceOf(fig, home)).filter((p) =>
    ["workspace.project", "workspace.branch", "workspace.dir"]
      .includes(p.path) && !hidden(hide, "account." + p.path));
  let dropped = false;
  for (const p of accountRow(st, fig, now).label) {
    // A window's 🔜 goes with its window.
    const gone: boolean = hidden(hide, "account." + p.path) ||
      (dropped && p.path === "plan.reset");
    dropped = gone && p.path !== "plan.reset";
    if (!gone) shown.push(p);
  }
  return shown;
}

/** The 💳 account as a row of its own, in its colours, for under the
 * footer line, in its container (asked 2026-10-20): the workspace, 💳 and
 * 📅 🕐, FOOTER_GAP columns apart, after blanks that end it where the
 * band's rows end at `cols`; none under the hide path `account`. */
export function accountLine(st: Settings, fig: Dict, hide: readonly string[],
  cols: number, home = ""): Span[] {
  const parts: Span[][] = [];
  for (const p of accountPieces(st, fig, hide, home)) {
    const lead = p.spans.map((s) => s.text).join("").trimStart();
    if (!parts.length || lead.startsWith(E_ACCT) || lead.startsWith(E_DATE)) {
      parts.push([]);
    }
    parts[parts.length - 1].push(...p.spans);
  }
  const trimmed = parts.map(trimSpans).filter((p) => p.length);
  if (!trimmed.length) return [];
  const gap = span(" ".repeat(FOOTER_GAP));
  const out = trimmed.flatMap((p, i) => i ? [gap, ...p] : p);
  const w = visWidth(out.map((s) => s.text).join(""), st.widths);
  return [span(" ".repeat(Math.max(0, cols - RIGHT_EDGE - w))), ...out];
}

/** `spans` without the blanks at either end. */
function trimSpans(spans: readonly Span[]): Span[] {
  const out = spans.filter((s) => s.text);
  while (out.length && !out[0].text.trim()) out.shift();
  while (out.length && !out[out.length - 1].text.trim()) out.pop();
  if (!out.length) return out;
  out[0] = { ...out[0], text: out[0].text.trimStart() };
  const n = out.length - 1;
  out[n] = { ...out[n], text: out[n].text.trimEnd() };
  return out;
}

/** What the footer under the prompt gets after Claude Code's own line,
 * `hint`, at `cols`: `accountText`, after blanks that end it where the
 * band's rows end; "" with no account text.  Claude Code trims the tail's
 * leading spaces and joins it to the line with FOOTER_JOIN, so the blanks
 * are TAIL_BLANK, which it keeps (seen live 2026-10-20).  The line is two
 * blanks in, and `hint` is read with one space between its parts, so the
 * padding is a guess at the drawn width; a tail too wide is cut where the
 * row ends.  `hint` leaves out the permission mode's pill, "⏵⏵ auto mode
 * on · " (seen live 2026-10-20: "-- INSERT -- 2 shells"), so the pill of
 * `mode`, the session's permission mode, is counted apart. */
export function footerTail(st: Settings, fig: Dict, hide: readonly string[],
  hint: string, cols: number, mode?: string, home = ""): string {
  const plain = accountText(st, fig, hide, home);
  if (!plain) return "";
  const pillW = pillWidth(st, hint, MODE_PILLS[mode ?? ""] ?? "");
  const room = cols - RIGHT_EDGE - 2 - pillW - visWidth(hint, st.widths) -
    visWidth(FOOTER_JOIN, st.widths);
  // The workspace, the 💳 account and 📅 🕐, FOOTER_GAP columns apart,
  // both gaps fewer, down to one, where the row is short (asked
  // 2026-10-20).
  const parts = footerParts(plain);
  const gapless = visWidth(parts.join(""), st.widths);
  const gaps = parts.length - 1;
  const gap = gaps ? Math.max(1, Math.min(FOOTER_GAP,
    Math.floor((room - gapless) / gaps))) : 0;
  // Claude Code draws a run of spaces in the tail as one (seen live
  // 2026-10-20: "6.6h 📅"), so a run's spaces past its first are blanks.
  const text = parts.join(" ".repeat(gap)).replace(/ {2,}/g,
    (run) => " " + TAIL_BLANK.repeat(run.length - 1));
  return TAIL_BLANK.repeat(Math.max(0, room - visWidth(text, st.widths))) +
    text;
}

/** A ruler as wide as `tail`, laid where it ends at `cols`: each column
 * the last digit of its number, counting the terminal's first as 1. */
export function footerRuler(st: Settings, tail: string, cols: number): string {
  const n = visWidth(tail, st.widths);
  const end = cols - RIGHT_EDGE;
  let out = "";
  for (let c = end - n + 1; c <= end; c++) out += String(c % 10);
  return out;
}

/** The columns between the footer's workspace, its account and its 📅 🕐,
 * at most. */
export const FOOTER_GAP = 4;

/** accountText cut into the workspace, the 💳 account and 📅 🕐, each
 * trimmed, leaving out any that is not there. */
export function footerParts(text: string): string[] {
  const cuts = [E_ACCT, E_DATE].map((m) => text.indexOf(m))
    .filter((i) => i > 0);
  const out: string[] = [];
  let from = 0;
  for (const i of cuts) {
    out.push(text.slice(from, i));
    from = i;
  }
  out.push(text.slice(from));
  return out.map((p) => p.trim()).filter((p) => p);
}

/** The columns the footer draws for the mode's `pill` that `hint` does
 * not read (seen live 2026-10-20):
 *
 *   none, where `hint` has the pill whole;
 *   its glyph and a space, where it has the pill's words alone, "-- INSERT
 *   -- plan mode on (shift+tab to cycle)", the first of the two draws a
 *   change of mode makes;
 *   the pill and a space, where it has none of it and nothing follows but
 *   MODE_CYCLE, "-- INSERT -- (shift+tab to cycle)" or "-- INSERT --";
 *   the pill and FOOTER_JOIN before anything else, "-- INSERT -- 2 shells".
 */
export function pillWidth(st: Settings, hint: string, pill: string): number {
  if (!pill || hint.includes(pill)) return 0;
  const glyph = pill.slice(0, pill.indexOf(" ") + 1);
  if (hint.includes(pill.slice(glyph.length))) {
    return visWidth(glyph, st.widths);
  }
  const rest = hint.replace(/^-- [A-Z]+ --\s*/, "");
  const join = !rest || rest.startsWith(MODE_CYCLE) ? " " : FOOTER_JOIN;
  return visWidth(pill + join, st.widths);
}

/** The permission mode a change of mode has just turned on, from the
 * first of the two draws it makes: that `hint` reads the words of the
 * mode turned off (seen live 2026-10-20: "accept edits on" while plan's
 * pill was drawn), and shift+tab turns on the next in MODE_CYCLE_ORDER.
 * undefined where `hint` reads no mode's words. */
export function modeOfHint(hint: string): string | undefined {
  for (const [mode, pill] of Object.entries(MODE_PILLS)) {
    if (!hint.includes(pill.slice(pill.indexOf(" ") + 1))) continue;
    const i = MODE_CYCLE_ORDER.indexOf(mode);
    return i < 0 ? undefined
      : MODE_CYCLE_ORDER[(i + 1) % MODE_CYCLE_ORDER.length];
  }
  return undefined;
}

/** The modes shift+tab steps through, in order (seen live 2026-10-20). */
export const MODE_CYCLE_ORDER: readonly string[] =
  ["default", "acceptEdits", "plan", "auto"];

/** The help that follows the mode's pill, joined to it by a space. */
export const MODE_CYCLE = "(shift+tab to cycle)";

/** What Claude Code puts between its footer line and a hook's tail. */
export const FOOTER_JOIN = " · ";

/** The pill Claude Code draws in the footer for each permission mode, by
 * the mode's name: all but bypassPermissions's seen live (2026-10-20). */
export const MODE_PILLS: Readonly<Record<string, string>> = {
  default: "⏸ manual mode on",
  auto: "⏵⏵ auto mode on",
  acceptEdits: "⏵⏵ accept edits on",
  plan: "⏸ plan mode on",
  bypassPermissions: "⏵⏵ bypass permissions on",
};
/** U+2800, a blank cell that is not whitespace, so no trim takes it. */
export const TAIL_BLANK = "⠀";

/** The band as drawn at `cols` under `hide`: its rows' spans, top to
 * bottom, on the fixed grid, each `opts.inset` columns narrower.  A hidden
 * scope's row is left out. */
export function bandLines(st: Settings, fig: Dict, cols: number,
  hide: readonly string[], opts: BandOpts): Span[][] {
  const keys = fixedKeys(st, cols, hide);
  const drawn = cols - (opts.inset ?? 0);
  return phaseRows(bandRows(st, fig, opts), opts.phase, opts.sticky)
    .filter((r) => !hidden(hide, r.scope))
    .map((r) => draw(st, indented(r, opts.indent ?? 0), keys, drawn, hide));
}
