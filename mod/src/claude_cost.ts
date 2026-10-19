// The Stop-hook receipt's metric groups and its render stage, from
// claude.py.
//
// claude.py draws the receipt's two kinds of row, a turn's (cost_group) and
// the session's (cost_totals_group), and hands them to the layout in
// claude_cost_render.py.  Those, the cells they are built from, and the
// render stage that draws a figures document (render_cost_figures) are
// here, each under its Python name in camelCase; the comment over each
// names the claude.py function it came from.  claude.py's docstrings carry
// the argument for every cell and are not copied: the comments here say
// what the port has to do to match it.
//
// Pure, as the Python's render stage is: the clock is the document's
// `clock.now`, drawn in the process's TZ, which the edge sets from
// `clock.tz` (the Python's _fig_zone); the shares are the document's
// `accounting`, never worked out again; and the width comes in resolved,
// since only the edge can ask the terminal for it.
import {
  C_COST, C_CTX, C_ELAPSED, C_SEG_GAP, C_STAMP, C_TOOL, CACHE_CRIT,
  CACHE_WARN, E_ACCT, E_CACHE, E_COST, E_COSTLINE, E_CTX, E_DOWN, E_HUNDRED,
  E_PCT, E_READ, E_ROW_AGENTS, E_ROW_COMPACT, E_ROW_PROMPT, E_ROW_TOTAL,
  E_SESS, E_TOK, E_TOOL, E_UP, E_WEEK, E_WRITE,
} from "./spec.ts";
import {
  C_AGENTS_LABEL, C_COMPACT_LABEL, C_LABEL, C_TOTALS_LABEL, decAlign,
  durFmt, humanize, moneyCell, padVal, pct, planPct, S_DATE, S_TIME, S_WORK,
  seg, signed, signedPct,
} from "./formatting.ts";
import type { Settings } from "./formatting.ts";
import { span, spans } from "./spans.ts";
import type { Span, SpanLike } from "./spans.ts";
import { pyFormatF, pyIsDigit, pyIntDigits, pyStrip } from "./py.ts";
import { turnTimes, W_CACHE_READ, W_CACHE_WRITE } from "./claude_records.ts";
import type { Turn } from "./claude_records.ts";
import { _pyRound, planTotals as calibPlanTotals, turnCost }
  from "./claude_calib.ts";
import type { Accounting } from "./claude_calib.ts";
import { costOpts, inkColour as _c, renderCostLine }
  from "./claude_cost_render.ts";
import type { CostAccounting, CostOpts, PlanTotals }
  from "./claude_cost_render.ts";

// ════════════════════════════════════════════════════════════════════════════
// The clock, as time.strftime(fmt, time.localtime(now)) draws it.
// ════════════════════════════════════════════════════════════════════════════

const two = (n: number): string => String(n).padStart(2, "0");

/** localtime(now) in the process's TZ.  Python takes the whole second
 * below `now`, as a Date's fields do. */
function localtime(now: number): Date {
  return new Date(Math.floor(now) * 1000);
}

/** strftime("%Y-%m-%d"). */
function ymd(now: number): string {
  const d = localtime(now);
  return String(d.getFullYear()).padStart(4, "0") + "-" +
    two(d.getMonth() + 1) + "-" + two(d.getDate());
}

/** strftime("%H:%M:%S"). */
function hms(now: number): string {
  const d = localtime(now);
  return two(d.getHours()) + ":" + two(d.getMinutes()) + ":" +
    two(d.getSeconds());
}

// ════════════════════════════════════════════════════════════════════════════
// The cells.
// ════════════════════════════════════════════════════════════════════════════

/** claude.py's plan_totals, off a figures document's plan reading: the two
 * percentages as numbers, or {} where either is missing. */
export function planTotals(plan: unknown): PlanTotals {
  return calibPlanTotals(plan as { [k: string]: unknown });
}

/** claude.py's share_half: the C_LIM_TOT half of a per-prompt limit cell,
 * the full seven columns even with no share, since seg pads the cost row
 * on the left and a short cell would shove the whole cell off its column. */
export function shareHalf(st: Settings, emoji: string, share: number | null,
  colour: boolean): SpanLike {
  if (share === null) return " ".repeat(st.cLimTot);
  return [" " + emoji + st.markSp,
    span(padVal(st, 3, pct(share)), _c(colour, "F_AMB"))];
}

/** claude.py's _cost_cells: a cost row's cells, C_SEG_GAP blanks between
 * each two. */
export function _costCells(cells: readonly SpanLike[]): Span[] {
  const out: Span[] = [];
  cells.forEach((cell, index) => {
    if (index) out.push(span(" ".repeat(C_SEG_GAP)));
    out.push(...spans(cell));
  });
  return out;
}

/** claude.py's _cache_ink: the colour a cache rate is drawn in. */
export function _cacheInk(p: number): string {
  if (p <= CACHE_CRIT) return "F_RED";
  if (p <= CACHE_WARN) return "F_AMB";
  return "F_GRN";
}

/** int(100 * read / whole), or -1 for no input at all. */
function cacheRate(read: number, whole: number): number {
  return whole ? Math.trunc(100 * read / whole) : -1;
}

/** The 🧩 cell both rows open with: ▴ the weighted input, ▾ the output. */
function tokCell(st: Settings, up: number, out: number,
  colour: boolean): Span[] {
  return seg(st, st.cTok, [
    E_TOK + st.markSp,
    span(E_UP + padVal(st, 4, humanize(st, up)), _c(colour, "F_TUP")),
    span(" " + E_DOWN + padVal(st, 4, humanize(st, out)),
      _c(colour, "F_TDN"))], false);
}

/** The 🎯 cell, blank where there was no input to rate. */
function cacheCell(st: Settings, cpct: number, colour: boolean): Span[] {
  return seg(st, st.cCache, cpct >= 0
    ? [E_CACHE + st.markSp,
      span(padVal(st, 3, pct(cpct)), _c(colour, _cacheInk(cpct)))]
    : [], false);
}

/** claude.py's cost_group: the constant-width group for one prompt, its
 * shares read from the turn's accounting. */
export function costGroup(st: Settings, t: Turn, shares: Accounting,
  win: number, colour: boolean, now: number, acct = true,
  stamps = true): Span[] {
  const up = t.fresh + W_CACHE_WRITE * t.cache_write +
    W_CACHE_READ * t.cache_read;
  const cpct = cacheRate(t.cache_read, t.fresh + t.cache_write +
    t.cache_read);
  const c = shares.cost_usd;
  const rd = shares.read_share, wr = shares.write_share;
  const tsh = { sess: shares.sess_share, week: shares.week_share };
  const [modelS, toolS] = turnTimes(t);
  const limW = acct ? st.cSess : st.cSess - st.cLimTot;
  const cells: SpanLike[] = [
    tokCell(st, up, t.out, colour),
    cacheCell(st, cpct, colour),
    seg(st, C_CTX, t.dctx !== null
      ? [E_CTX, span(signedPct(st, t.dctx, win) + " ", _c(colour, "F_PNK2")),
        span(signed(st, t.dctx), _c(colour, "F_PNK"))]
      : [], false),
    seg(st, C_COST, [E_COST,
      span("+" + moneyCell(st, c), _c(colour, "F_YEL"))], false),
    seg(st, limW, tsh.sess !== null
      ? [E_SESS,
        span("+" + decAlign(st, planPct(st, tsh.sess), 2, 2, E_PCT),
          _c(colour, "F_AMB")),
        acct ? shareHalf(st, E_READ, rd, colour) : ""]
      : [], false),
    // One column wider than 🔋 for planPct's third decimal.
    seg(st, limW + 1, tsh.week !== null
      ? [E_WEEK,
        span("+" + decAlign(st, planPct(st, tsh.week, 3), 2, 3, E_PCT),
          _c(colour, "F_AMB")),
        acct ? shareHalf(st, E_WRITE, wr, colour) : ""]
      : [], false),
    seg(st, C_ELAPSED, [S_WORK,
      span("+" + padVal(st, 4, durFmt(st, modelS)), _c(colour, "F_CRM"))],
    false),
    seg(st, C_TOOL, [E_TOOL,
      span("+" + padVal(st, 4, durFmt(st, toolS)), _c(colour, "F_CRM"))],
    false),
    // Blank on a compaction and an agents row, the cell kept so the
    // columns to its left still stack.
    seg(st, C_STAMP, !(t.compact || t.agent)
      ? [S_DATE, span(padVal(st, 10, ymd(now)), _c(colour, "F_CRM"))]
      : [], false),
  ];
  // Dropped, not blanked: see the Python.
  if (!stamps) cells.pop();
  return _costCells(cells);
}

/** claude.py's limit_cell: a totals-row limit cell, this session's share
 * then 💳 and the window's own reading, 💯 for a full one. */
export function limitCell(st: Settings, emoji: string, share: number | null,
  total: number | null, colour: boolean, acct = true,
  places = 2): SpanLike {
  if (share === null && (total === null || !acct)) return "";
  const left = share !== null
    ? decAlign(st, planPct(st, share, places), 2, places, E_PCT)
    : padVal(st, st.cSess - st.cLimTot - 5 + places, "?");
  if (!acct) return [emoji, span(" " + left, _c(colour, "F_AMB"))];
  // The threshold is render_limit's, so the two readouts can never draw
  // different things for one window.
  let right: string;
  if (total === null) right = "?";
  else if (total >= 99.5) right = E_HUNDRED + E_PCT;
  else right = pct(_pyRound(total));
  return [emoji, span(" " + left, _c(colour, "F_AMB")),
    " " + E_ACCT + st.markSp,
    span(padVal(st, 3, right), _c(colour, "F_AMB"))];
}

/** sum() of floats, left to right: claude_records.py's add_up. */
function addUp(values: Iterable<number>): number {
  let total = 0;
  for (const v of values) total += v;
  return total;
}

/** claude.py's cost_totals_group: the session-to-date row under the
 * per-prompt one, its shares read from the session's accounting. */
export function costTotalsGroup(st: Settings, turns: readonly Turn[],
  totals: PlanTotals, win: number, colour: boolean, now: number,
  shares: Accounting | null = null, acct = true,
  stamps = true): Span[] {
  const up = addUp(turns.map((t) => t.fresh + W_CACHE_WRITE * t.cache_write +
    W_CACHE_READ * t.cache_read));
  const outTok = addUp(turns.map((t) => t.out));
  const cr = addUp(turns.map((t) => t.cache_read));
  const inAll = addUp(turns.map((t) => t.fresh + t.cache_write +
    t.cache_read));
  const cpct = cacheRate(cr, inAll);
  // The last turn that HAS a reading, not simply the last turn: a
  // compaction has none.
  let ctx = 0;
  for (let i = turns.length - 1; i >= 0; i--) {
    if (turns[i].ctx) {
      ctx = turns[i].ctx;
      break;
    }
  }
  // Without the accounting there is no share to draw.
  const sh: Pick<Accounting, "cost_usd" | "sess_share" | "week_share" |
    "read_share" | "write_share"> = shares ?? {
    cost_usd: addUp(turns.map(turnCost)), sess_share: null,
    week_share: null, read_share: null, write_share: null };
  const c = sh.cost_usd;
  const workS = addUp(turns.map((t) => turnTimes(t)[0]));
  const toolS = addUp(turns.map((t) => turnTimes(t)[1]));
  const limW = acct ? st.cSess : st.cSess - st.cLimTot;
  const cells: SpanLike[] = [
    tokCell(st, up, outTok, colour),
    cacheCell(st, cpct, colour),
    // A space where the per-prompt row prints its sign, then the same
    // decAlign, so the two readings stack digit under digit.
    seg(st, C_CTX, ctx
      ? [E_CTX,
        span(" " + decAlign(st, pyFormatF(100.0 * ctx / win, 1), 2, 1,
          E_PCT) + " ", _c(colour, "F_PNK2")),
        span(" " + padVal(st, 4, humanize(st, ctx)), _c(colour, "F_PNK"))]
      : [], false),
    seg(st, C_COST, [E_COST,
      span(" " + moneyCell(st, c), _c(colour, "F_YEL"))], false),
    seg(st, limW, limitCell(st, E_SESS, sh.sess_share,
      totals.sess ?? null, colour, acct), false),
    // One wider than 🔋 for the week's third decimal.
    seg(st, limW + 1, limitCell(st, E_WEEK, sh.week_share,
      totals.week ?? null, colour, acct, 3), false),
    seg(st, C_ELAPSED, [S_WORK,
      span(" " + padVal(st, 4, durFmt(st, workS)), _c(colour, "F_CRM"))],
    false),
    seg(st, C_TOOL, [E_TOOL,
      span(" " + padVal(st, 4, durFmt(st, toolS)), _c(colour, "F_CRM"))],
    false),
    seg(st, C_STAMP, [S_TIME,
      span(padVal(st, 10, hms(now)), _c(colour, "F_CRM"))], false),
  ];
  if (!stamps) cells.pop();       // dropped rather than blanked
  return _costCells(cells);
}

// ════════════════════════════════════════════════════════════════════════════
// The render stage.
// ════════════════════════════════════════════════════════════════════════════

// Turn's str fields: written null in the document when "", and "" again
// here (claude.py's decode_record).  Turn has no other missing-value
// fields, and no stamps.
const TURN_STRS = ["ts", "text", "agent_id", "agent_name", "prompt_id"];
const TURN_FIELDS = ["ts", "text", "fresh", "cache_write", "cache_read",
  "out", "ctx", "calls", "dur_s", "dctx", "usd_in", "usd_out", "usd_cr",
  "usd_cw", "compact", "reported", "parts", "agent_calls", "agent_ids",
  "agent", "tool_s", "blocked_s", "agent_model_s", "agent_tool_s",
  "agent_id", "agent_name", "prompt_id", "turn_index", "lines_added",
  "lines_removed"];

/** claude.py's decode_record(Turn, d).  Every field must be present: a
 * document missing one is from another schema, not a record with a
 * default.  A number is a number whichever way the document wrote it, so
 * _fig_typed's float() and int() have nothing to do here. */
export function decodeTurn(d: { readonly [k: string]: unknown }): Turn {
  const out: { [k: string]: unknown } = {};
  for (const field of TURN_FIELDS) {
    if (!Object.hasOwn(d, field)) throw new Error("no " + field + " in Turn");
    const v = d[field];
    out[field] = v === null && TURN_STRS.includes(field) ? "" : v;
  }
  return out as unknown as Turn;
}

/** claude.py's _read_accounting: one turn's or the session's accounting
 * as it was worked out.  The Python makes the cost and the window shares
 * floats again; a number here is one already. */
export function _readAccounting(acc: { readonly [k: string]: unknown }):
  Accounting {
  return { ...acc } as unknown as Accounting;
}

/** claude.py's _flag: the value after `name`, or `dflt`. */
export function _flag(argv: readonly string[], name: string,
  dflt = ""): string {
  const i = argv.indexOf(name);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : dflt;
}

/** claude.py's _cols: --cols, where "0" means a width that is unknown,
 * else what the edge reads off the terminal (term_cols). */
export function _cols(argv: readonly string[],
  termCols: () => number | null): number | null {
  const s = _flag(argv, "--cols");
  return pyIsDigit(s) ? (pyIntDigits(s) || null) : termCols();
}

/** claude.py's _cost_opts.  --no-usage-text keeps each row's marker glyph
 * and drops the words.  The width is resolved at the edge (_cols). */
export function _costOpts(argv: readonly string[], cols: number | null,
  sessionId = ""): CostOpts {
  const words = !argv.includes("--no-usage-text");
  return costOpts({
    prefix: _flag(argv, "--prefix", E_COSTLINE),
    label: _flag(argv, "--label", words ? C_LABEL : E_ROW_PROMPT),
    totals_label: words ? C_TOTALS_LABEL : E_ROW_TOTAL,
    compact_label: words ? C_COMPACT_LABEL : E_ROW_COMPACT,
    agents_label: words ? C_AGENTS_LABEL : E_ROW_AGENTS,
    account_totals: !argv.includes("--no-account-totals"),
    stamps: !argv.includes("--no-datetime"),
    force_newline: argv.includes("--force-newline"),
    cols,
    colour: argv.includes("--color"),
    totals: !argv.includes("--no-totals"),
    right_align: !argv.includes("--no-right-align"),
    session_id: sessionId,
  });
}

/** A cost figures document, as far as the render stage reads it. */
export type CostFigures = {
  readonly clock: { readonly now: number; readonly tz: string | null };
  readonly turns: readonly { readonly [k: string]: unknown }[];
  readonly context_window: number;
  readonly accounting: {
    readonly turns: readonly { readonly [k: string]: unknown }[];
    readonly session: { readonly [k: string]: unknown };
  };
  readonly usage: {
    readonly plan: unknown;
    readonly account_text: string | null;
  };
};

/** claude.py's render_cost_figures: the systemMessage, or "" for none.
 * Reads no file, no clock and no plan reading but the document's.  The
 * Python's _fig_zone sets TZ from `clock.tz` first; that is the caller's,
 * which must set it before calling. */
export function renderCostFigures(st: Settings, fig: CostFigures,
  opts: CostOpts): string {
  const turns = fig.turns.map(decodeTurn);
  const accounting: CostAccounting = {
    turns: fig.accounting.turns.map(_readAccounting),
    session: _readAccounting(fig.accounting.session),
  };
  let line = renderCostLine(st, turns, opts, Math.trunc(fig.context_window),
    accounting, planTotals(fig.usage.plan), fig.clock.now, costGroup,
    costTotalsGroup);
  if (!pyStrip(line)) return "";
  const text = fig.usage.account_text;
  if (text) line += "\n" + text;
  return line;
}
