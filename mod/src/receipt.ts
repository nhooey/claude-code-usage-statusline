// The receipt a turn ends with, and the start line under its prompt, from
// the figures documents.
//
// agents/plans/redesign.md has the design ("The receipt"): live, then
// stamped.  While a turn runs the band draws its 🎤 and 🎮 rows; when it
// ends, the Stop hook (tools/receipt-hook.ts) prints them frozen into the
// transcript as its systemMessage: a head, 🔺🔖 the turn's tag and when it
// ended, and under it the same two rows behind 📊, from the cost document
// (`cost_figures`), dimmed so history reads apart from the live band.  As
// a turn starts, the mod draws the same tag under the prompt, 🔻 pointing
// down at the turn it opens, from the status document.  The rows are drawn
// on the band's fixed grid (band.ts), so the receipt's columns are the
// band's and the panel's.
//
// Pure, as band.ts is: the 📦 🌿 on the 📊 🎮 row are the caller's, since
// cost_figures runs no git (the hook runs detectGit), and the clock is
// drawn in the TZ the edge sets.
import { E_TURN_AHEAD, E_TURN_PAST } from "./spec.ts";
import type { Settings } from "./formatting.ts";
import { span } from "./spans.ts";
import type { Span } from "./spans.ts";
import { squash } from "./claude_records.ts";
import type { Turn } from "./claude_records.ts";
import type { Accounting } from "./claude_calib.ts";
import { decodeTranscript } from "./figures.ts";
import { _readAccounting, decodeTurn } from "./claude_cost.ts";
import {
  CELLS, cacheRate, hms, receiptLabel, sessionLabel, turnHead, turnLabel,
  ymd,
} from "./cells.ts";
import type { Workspace } from "./cells.ts";
import { draw, hidden } from "./grid.ts";
import type { Row } from "./grid.ts";
import {
  accountingSplit, fixedKeys, indented, shareCells, turnCache, turnTokens,
} from "./band.ts";
import type { Dict } from "./py.ts";

type Cells = { [key: string]: Span[] };

/** The turn the receipt bills, as renderCostLine picks it: the last with
 * calls that is neither a compaction nor an agent's, else the last; -1
 * with none. */
export function receiptTurn(turns: readonly Turn[]): number {
  for (let i = turns.length - 1; i >= 0; i--) {
    const t = turns[i];
    if (t.calls && !t.compact && !t.agent) return i;
  }
  return turns.length - 1;
}

/** The plan reading's percentage as the plan cells take it, "" for
 * none. */
function planPct(plan: unknown, key: string): string {
  const v = plan && typeof plan === "object"
    ? (plan as Dict)[key] : null;
  return v === null || v === undefined ? "" : String(v);
}

/** 📊 🎤: the turn the receipt bills, `turns[i]` with
 * `accounting.turns[i]`.  🧠 its growth, `dctx` over `context_window`;
 * 🧩 🎯 weighed from its tokens; ⌛ its `dur_s`; ⛳ the last ETA it
 * reported, `eta` (decision 6), read at `clock.now`, when it ended, so a
 * turn that ran past its estimate reads late. */
function turnRow(st: Settings, t: Turn, acc: Accounting, win: number,
  now: number, sessPct: string, weekPct: string): Row {
  const [up, down] = turnTokens(t);
  const cells: Cells = {
    cost: CELLS.cost(st, acc.cost_usd),
    ctx: CELLS.growth(st, t.dctx, win),
    tok: CELLS.tok(st, up, down),
    cache: CELLS.cache(st, turnCache(t)),
    clock: CELLS.clock(st, t.dur_s),
    eta: CELLS.eta(st, t.eta, null, now,
      t.eta.length > 0 && t.eta[1] === 0),
    split: accountingSplit(acc),
    ...shareCells(st, acc, sessPct, weekPct),
    diff: CELLS.diff(st, acc.lines_added, acc.lines_removed),
  };
  return { scope: "turn", label: receiptLabel(turnLabel(squash(t.text))),
    cells };
}

/** sum() of floats, left to right, as the receipt's totals add up. */
function addUp(values: readonly number[]): number {
  let total = 0;
  for (const v of values) total += v;
  return total;
}

/** 📊 🎮: the session, `accounting.session`, its 🧩 🎯 every turn summed
 * as cost_totals_group sums them, ⌛ its age from `start_s` (decision 5),
 * and on the label the caller's 📦 🌿. */
function sessionRow(st: Settings, turns: readonly Turn[], acc: Accounting,
  now: number, sessPct: string, weekPct: string,
  ws: Workspace | null): Row {
  const tokens = turns.map(turnTokens);
  const cells: Cells = {
    cost: CELLS.cost(st, acc.cost_usd),
    tok: CELLS.tok(st, addUp(tokens.map(([u]) => u)),
      addUp(tokens.map(([, d]) => d))),
    cache: CELLS.cache(st, cacheRate(addUp(turns.map((t) => t.cache_read)),
      addUp(turns.map((t) => t.fresh + t.cache_write + t.cache_read)))),
    split: accountingSplit(acc),
    ...shareCells(st, acc, sessPct, weekPct),
    diff: CELLS.diff(st, acc.lines_added, acc.lines_removed),
  };
  if (acc.start_s !== null && acc.start_s !== undefined) {
    cells.clock = CELLS.clock(st, now - acc.start_s);
  }
  // Only the project and the branch: the receipt is about what was spent
  // where, not where the shell stood.
  const where = ws ? { ...ws, dir: "", pr: "", style: "" } : null;
  return { scope: "session", label: receiptLabel(sessionLabel(where)),
    cells };
}

/** The receipt's rows from a cost figures document: 📊 🎤, or null with
 * no turn to bill, and 📊 🎮. */
export function receiptRows(st: Settings, fig: Dict,
  ws: Workspace | null): { turn: Row | null; session: Row } {
  const now = (fig.clock as Dict).now as number;
  const turns = (fig.turns as Dict[]).map(decodeTurn);
  const acc = fig.accounting as Dict;
  const plan = (fig.usage as Dict).plan;
  const [sp, wp] = [planPct(plan, "session_pct"), planPct(plan, "weekly_pct")];
  const i = receiptTurn(turns);
  const win = Math.trunc(fig.context_window as number);
  return {
    turn: i < 0 ? null : turnRow(st, turns[i],
      _readAccounting((acc.turns as Dict[])[i]), win, now, sp, wp),
    session: sessionRow(st, turns, _readAccounting(acc.session as Dict),
      now, sp, wp, ws),
  };
}

/** `fig` with the billed turn timed by the engine's own duration.  The
 * transcript's turn_duration record, which dur_s takes when it is there,
 * lands late, after turn.complete, so until then dur_s is the span from the
 * turn's first record to its last, short of what Claude Code's closing
 * line prints.  The seconds added are the model's: they are the
 * answer streaming after its last record, in no tool and no wait. */
export function withEngineDuration(fig: Dict, durationMs: number): Dict {
  const turns = fig.turns as Dict[];
  const i = receiptTurn(turns.map(decodeTurn));
  if (i < 0 || !(durationMs > 0)) return fig;
  const dur = durationMs / 1000;
  const gain = dur - (turns[i].dur_s as number);
  if (!(gain > 0)) return fig;
  const acc = fig.accounting as Dict;
  const accTurns = [...(acc.turns as Dict[])];
  const a = accTurns[i];
  accTurns[i] = { ...a, model_s: (a.model_s as number) + gain };
  const t = [...turns];
  t[i] = { ...turns[i], dur_s: dur };
  return { ...fig, turns: t, accounting: { ...acc, turns: accTurns } };
}

/** The receipt's head, "🔺🔖 8f37748e #12  📅 2026-10-19  🕐 13:06:02": the
 * billed turn's tag and `clock.now`, when the Stop ran. */
export function receiptHead(fig: Dict): Span[] {
  const now = (fig.clock as Dict).now as number;
  const turns = (fig.turns as Dict[]).map(decodeTurn);
  const i = receiptTurn(turns);
  const t = i < 0 ? null : turns[i];
  return [span(turnHead(E_TURN_PAST, t ? t.prompt_id : "",
    t ? t.turn_index : null, ymd(now), hms(now)))];
}

/** The receipt as drawn at `cols` under `hide`: the head, on a line of its
 * own, and the rows under it, on the band's fixed grid.  A hidden scope's
 * row is left out.  `dim` draws every span dim, as the stamped receipt is
 * drawn, its colours kept. */
export function receiptLines(st: Settings, fig: Dict, cols: number,
  hide: readonly string[], ws: Workspace | null, dim = false, indent = 0):
  { head: Span[]; rows: Span[][] } {
  const { turn, session } = receiptRows(st, fig, ws);
  const head = receiptHead(fig);
  const rows = drawRows(st, [...(turn ? [turn] : []), session]
    .map((r) => indented(r, indent)), cols, hide);
  return dim ? { head: dimmed(head), rows: rows.map(dimmed) }
    : { head, rows };
}

/** `spans`, each drawn dim. */
export function dimmed(spans: readonly Span[]): Span[] {
  return spans.map((s) => ({ ...s, dim: true }));
}

/** Rows drawn on the band's fixed grid at `cols` under `hide`, a hidden
 * scope's left out. */
export function drawRows(st: Settings, rows: readonly Row[], cols: number,
  hide: readonly string[]): Span[][] {
  const keys = fixedKeys(st, cols, hide);
  return rows.filter((r) => !hidden(hide, r.scope))
    .map((r) => draw(st, r, keys, cols, hide));
}

/** The line under the prompt as its turn starts, dim, from a status
 * document: 🔻🔖, the tag of the turn opened last, `transcript.prompt_id`
 * and `turn_index`, and when its prompt was stamped, `transcript.turn_s`;
 * without the stamp, the tag alone, and nothing with neither. */
export function startLine(fig: Dict): Span[] {
  const tr = decodeTranscript(fig.transcript);
  const at = tr.turn_s || null;
  const text = turnHead(E_TURN_AHEAD, tr.prompt_id, tr.turn_index,
    at === null ? null : ymd(at), at === null ? null : hms(at));
  return text ? [span(text, null, true)] : [];
}
