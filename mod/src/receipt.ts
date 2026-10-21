// The receipt a turn ends with, and the start line under its prompt, from
// the figures documents.
//
// agents/plans/_implemented/redesign.md has the design ("The receipt"):
// live, then stamped.  While a turn runs the band draws its 🎤 and 🎮 rows; once the
// turn's records are in the transcript, the mod stamps them there frozen, a
// `$.ui.log` line each: a head, 🔺🔖 the turn's tag and when it was
// stamped, and over it the same two rows, from the cost document
// (`cost_figures`), dim so history reads apart from the live band.  As
// a turn starts, the mod draws the same tag under the prompt, 🔻 pointing
// down at the turn it opens, from the status document.  The rows are drawn
// on the band's fixed grid (band.ts), so the receipt's columns are the
// band's and the panel's.
//
// Pure, as band.ts is: the clock is drawn in the TZ the edge sets.
import { E_TURN_AHEAD, E_TURN_PAST } from "./spec.ts";
import type { Settings } from "./formatting.ts";
import { span } from "./spans.ts";
import type { Span } from "./spans.ts";
import type { Turn } from "./claude_records.ts";
import { turnShares } from "./claude_calib.ts";
import type { Accounting } from "./claude_calib.ts";
import { decodeTranscript } from "./figures.ts";
import { _readAccounting, decodeTurn } from "./claude_cost.ts";
import {
  CELLS, cacheRate, hms, sessionLabel, turnHead, turnLabel, ymd,
} from "./cells.ts";
import { draw, hidden } from "./grid.ts";
import type { Row } from "./grid.ts";
import {
  ROW_NAMES, accountingSplit, fixedKeys, scopesOf, shareCells, turnCache,
  turnTokens,
} from "./band.ts";
import type { RowName } from "./band.ts";
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

/** Whether `t` is an automatic compaction, which lands inside whatever
 * turn was running: the fold gives it a turn of its own, named as
 * turnsOf names it, and files the running turn's records after it there,
 * with no promptId. */
function inTurnCompaction(t: Turn): boolean {
  return t.compact && !t.agent && t.text === "/compact (auto)";
}

/** Sums `a` and `b` where either is a number, else null. */
function addOrNull(a: number | null, b: number | null): number | null {
  return a === null ? b : b === null ? a : a + b;
}

/** `t` with the compaction `c` that landed inside it, and the records
 * after it, as one turn: its own tag and prompt, everything billed summed,
 * the compaction's dollars and tokens with it, since the turn spent them.
 * 🧠 adds up: each turn's growth is over the reading before it. */
function absorb(t: Turn, c: Turn): Turn {
  return { ...t,
    fresh: t.fresh + c.fresh, cache_write: t.cache_write + c.cache_write,
    cache_read: t.cache_read + c.cache_read, out: t.out + c.out,
    ctx: c.ctx || t.ctx, calls: t.calls + c.calls, dur_s: t.dur_s + c.dur_s,
    dctx: addOrNull(t.dctx, c.dctx), usd_in: t.usd_in + c.usd_in,
    usd_out: t.usd_out + c.usd_out, usd_cr: t.usd_cr + c.usd_cr,
    usd_cw: t.usd_cw + c.usd_cw, reported: c.reported,
    parts: [...t.parts, ...c.parts], agent_calls: t.agent_calls + c.agent_calls,
    agent_ids: [...t.agent_ids, ...c.agent_ids],
    tool_s: t.tool_s + c.tool_s, blocked_s: t.blocked_s + c.blocked_s,
    agent_model_s: t.agent_model_s + c.agent_model_s,
    agent_tool_s: t.agent_tool_s + c.agent_tool_s,
    lines_added: t.lines_added + c.lines_added,
    lines_removed: t.lines_removed + c.lines_removed,
    eta: c.eta.length ? c.eta : t.eta };
}

/** absorb's, for the two turns' accountings: the window shares add up, as
 * the dollars do; the cache shares are worked out again over `merged`. */
function absorbAccounting(a: Accounting, c: Accounting, merged: Turn):
  Accounting {
  const [read_share, write_share] = turnShares(merged);
  return { ...a, cost_usd: a.cost_usd + c.cost_usd,
    sess_share: addOrNull(a.sess_share, c.sess_share),
    week_share: addOrNull(a.week_share, c.week_share), read_share,
    write_share, model_s: a.model_s + c.model_s, tool_s: a.tool_s + c.tool_s,
    blocked_s: a.blocked_s + c.blocked_s,
    lines_added: a.lines_added + c.lines_added,
    lines_removed: a.lines_removed + c.lines_removed };
}

/** `turns` as the receipt bills them: each automatic compaction folded
 * into the turn it landed in, with `acc`, the turns' accountings, folded
 * alike.  The fold splits such a turn in two at the compaction (seen live
 * 2026-10-20): its prompt with what it billed before, and a compaction
 * with no promptId holding the rest, which the receipt passes over, so it
 * billed the turn before instead, or nothing. */
export function inTurns<A extends Accounting | null>(turns: readonly Turn[],
  acc: readonly A[]): [Turn[], A[]] {
  const out: Turn[] = [];
  const outAcc: A[] = [];
  for (let i = 0; i < turns.length; i++) {
    const head = out.length - 1;
    const prev = head >= 0 ? out[head] : null;
    if (prev && !prev.compact && !prev.agent &&
      inTurnCompaction(turns[i])) {
      out[head] = absorb(prev, turns[i]);
      const a = outAcc[head];
      const c = acc[i];
      if (a && c) outAcc[head] = absorbAccounting(a, c, out[head]) as A;
      continue;
    }
    out.push(turns[i]);
    outAcc.push(acc[i]);
  }
  return [out, outAcc];
}

/** inTurns over a cost figures document: its turns and their accountings
 * as the receipt bills them.  A document already folded comes back as it
 * was. */
export function billedFig(fig: Dict): Dict {
  const raw = fig.turns as Dict[];
  const acc = fig.accounting as Dict;
  const accTurns = (acc.turns as Dict[]).map(_readAccounting);
  const [turns, accs] = inTurns(raw.map(decodeTurn), accTurns);
  if (turns.length === raw.length) return fig;
  return { ...fig, turns, accounting: { ...acc, turns: accs } };
}

/** Whether the billed turn is the turn that opened with `prompt`, its
 * promptId, or with none given, the newest of the main thread's turns.
 * One before it is the turn before's, read before this turn's records were
 * written: Claude Code writes a turn's assistant records only after its
 * Stop hooks have run, and its prompt's record as it opens, so until then
 * the newest prompt bills nothing and receiptTurn falls back past it.
 * With `prompt`, a turn opened after it does not count: a task
 * notification delivered as the turn ends is written as a turn of its own
 * that may never run, and the turn it follows is billed all the same.  A
 * turn an automatic compaction landed in is read as one (inTurns). */
export function newestBilled(all: readonly Turn[], prompt = ""): boolean {
  const [turns] = inTurns(all, []);
  const i = receiptTurn(turns);
  if (i < 0 || !turns[i].calls || turns[i].compact || turns[i].agent) {
    return false;
  }
  if (prompt) return turns[i].prompt_id === prompt;
  for (let j = turns.length - 1; j > i; j--) {
    if (!turns[j].agent && !turns[j].compact) return false;
  }
  return true;
}

/** How a turn ended, as its turn.complete says: `reason`, and `usage`,
 * whether the engine counted any of its requests. */
export interface TurnEnd {
  readonly reason: string;
  readonly usage: boolean;
}

/** Why the turn that opened with `prompt` billed nothing, where that is
 * known, else "": it may yet bill.  A turn the fold shows billed is never
 * one.  Ended by an interrupt or an API error with no request counted
 * (`end`), it is "interrupted" or "an API error"; a prompt sent before it
 * was finished is rewound so, before any reply (seen live 2026-10-20).
 * Or "replaced": no call of its own and a later prompt in the same turn
 * slot, its turnPosition's turnIndex, as the full prompt that replaced
 * that one was written ~2 min on. */
export function billedNothing(all: readonly Turn[], prompt: string,
  end: TurnEnd | null = null): string {
  const [turns] = inTurns(all, []);
  const at = prompt ? turns.findIndex((t) => t.prompt_id === prompt) : -1;
  const own = at >= 0 ? turns[at] : null;
  if (own && own.calls) return "";
  if (end && !end.usage) {
    if (end.reason === "aborted") return "interrupted";
    if (end.reason === "error") return "an API error";
  }
  if (own && own.turn_index !== null && turns.slice(at + 1).some((t) =>
    !t.agent && !t.compact && t.prompt_id && t.prompt_id !== prompt &&
    t.turn_index === own.turn_index)) return "replaced";
  return "";
}

/** The billed turn, as one key: its tag, its first stamp and how many
 * calls it has billed, so the same turn read again is the same key and a
 * turn that went on is not; "" with none. */
export function turnKey(all: readonly Turn[]): string {
  const [turns] = inTurns(all, []);
  const i = receiptTurn(turns);
  if (i < 0) return "";
  const t = turns[i];
  return JSON.stringify([t.prompt_id, t.turn_index, t.ts, t.calls]);
}

/** The plan reading's percentage as the plan cells take it, "" for
 * none. */
function planPct(plan: unknown, key: string): string {
  const v = plan && typeof plan === "object"
    ? (plan as Dict)[key] : null;
  return v === null || v === undefined ? "" : String(v);
}

/** 🎤: the turn the receipt bills, `turns[i]` with
 * `accounting.turns[i]`.  🧠 its growth, `dctx` over `context_window`;
 * 🧩 🎯 weighed from its tokens; ⌛ its `dur_s`; ⛳ the last ETA it
 * reported, `eta` (decision 6), read at `clock.now`, when it ended, so a
 * turn that ran past its estimate reads late; none for one signed off
 * at zero. */
function turnRow(st: Settings, t: Turn, acc: Accounting, win: number,
  now: number, sessPct: string, weekPct: string): Row {
  const [up, down] = turnTokens(t);
  const cells: Cells = {
    cost: CELLS.cost(st, acc.cost_usd),
    ctx: CELLS.growth(st, t.dctx, win),
    tok: CELLS.tok(st, up, down),
    cache: CELLS.cache(st, turnCache(t)),
    clock: CELLS.clock(st, t.dur_s),
    // A turn signed off at zero ended on time: its overrun is only the
    // seconds between the sign-off and the turn's last record, so no ⛳.
    eta: t.eta.length > 0 && t.eta[1] === 0 ? []
      : CELLS.eta(st, t.eta, null, now),
    split: accountingSplit(acc),
    ...shareCells(st, acc, sessPct, weekPct),
    diff: CELLS.diff(st, acc.lines_added, acc.lines_removed),
  };
  return { scope: "turn", label: turnLabel(), cells };
}

/** sum() of floats, left to right, as the receipt's totals add up. */
function addUp(values: readonly number[]): number {
  let total = 0;
  for (const v of values) total += v;
  return total;
}

/** 🎮: the session, `accounting.session`, its 🧩 🎯 every turn summed
 * as cost_totals_group sums them, ⌛ its age from `start_s` (decision 5),
 * and its mark alone on the label, as the band's 🎮 is. */
function sessionRow(st: Settings, turns: readonly Turn[], acc: Accounting,
  now: number, sessPct: string, weekPct: string): Row {
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
  return { scope: "session", label: sessionLabel(), cells };
}

/** The receipt's rows from a cost figures document: 🎤, or null with no
 * turn to bill, and 🎮.  They have no 📊 of their own (decided
 * 2026-10-19): the band has no 🎤 or 🎮 once a turn ends, so they read
 * apart by being dim. */
export function receiptRows(st: Settings, all: Dict):
  { turn: Row | null; session: Row } {
  const fig = billedFig(all);
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
      now, sp, wp),
  };
}

/** `fig` with the billed turn timed by the engine's own duration.  The
 * transcript's turn_duration record, which dur_s takes when it is there,
 * lands late, after turn.complete, so until then dur_s is the span from the
 * turn's first record to its last, short of what Claude Code's closing
 * line prints.  The seconds added are the model's: they are the
 * answer streaming after its last record, in no tool and no wait. */
export function withEngineDuration(all: Dict, durationMs: number): Dict {
  const fig = billedFig(all);
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

/** The receipt's tag line, drawn as the start line is, at no indent, so the
 * two stack: "🔺🔖 8f37748e #12  📅 2026-10-19  🕐 13:06:02", the billed
 * turn's tag and `clock.now`, when it was stamped; none under the hide path
 * `name.tag`. */
export function receiptHead(all: Dict, hide: readonly string[]): Span[] {
  if (tagsHidden(hide)) return [];
  const fig = billedFig(all);
  const now = (fig.clock as Dict).now as number;
  const turns = (fig.turns as Dict[]).map(decodeTurn);
  const i = receiptTurn(turns);
  const t = i < 0 ? null : turns[i];
  const text = turnHead(E_TURN_PAST, t ? t.prompt_id : "",
    t ? t.turn_index : null, ymd(now), hms(now));
  return text ? [span(text)] : [];
}

/** The receipt as drawn at `cols` under `hide`: 🎤, `main`, the band's 🤖
 * row, where there is one, and 🎮 on the band's fixed grid, at no indent,
 * as the band's rows are, then the tag line
 * (receiptHead) under them (decided 2026-10-19).  A hidden scope's row is
 * left out, and so is a row not `stamped` (RowName: the rows whose
 * `rows.<row>.transcript` is true), and the tag line without `tags`
 * (`rows.tag.transcript`).  `dim` draws every span dim, as the stamped
 * receipt is drawn, its colours kept. */
export function receiptLines(st: Settings, fig: Dict, cols: number,
  hide: readonly string[], dim = false, main: Row | null = null,
  stamped: readonly RowName[] = ROW_NAMES, inset = 0, tags = true):
  Span[][] {
  return receiptScoped(st, fig, cols, hide, dim, main, stamped, inset,
    tags).map((l) => l.spans);
}

/** receiptLines, each line with its scope (`turn` for 🎤, `main` for 🤖,
 * `session` for 🎮, `blank` and `tag` for the tag line and the row above
 * it), so a caller can tell the rows apart. */
export function receiptScoped(st: Settings, fig: Dict, cols: number,
  hide: readonly string[], dim = false, main: Row | null = null,
  stamped: readonly RowName[] = ROW_NAMES, inset = 0, tags = true):
  { scope: string; spans: Span[] }[] {
  const { turn, session } = receiptRows(st, fig);
  // 🤖 between 🎤 and 🎮, as the band stacks them, where the caller has
  // the band's row for it (asked 2026-10-20).
  const kept = scopesOf(stamped);
  const rows = [turn, main, session].filter((r): r is Row =>
    r !== null && kept.includes(r.scope) && !hidden(hide, r.scope));
  // `inset` columns in, led by as many blanks and that much narrower, so
  // they stack on the band's rows where those are drawn inset (asked
  // 2026-10-20); the tag line stays at no indent, under the prompt's.
  const lines = drawRows(st, rows, cols - inset, hide)
    .map((l, i) => ({ scope: rows[i].scope,
      spans: inset ? [span(" ".repeat(inset)), ...l] : l }));
  // A blank row before the tag line (asked 2026-10-20): a space, since Ink
  // measures an empty Text as no row at all.
  const head = tags ? receiptHead(fig, hide) : [];
  if (head.length) {
    lines.push({ scope: "blank", spans: [span(" ")] },
      { scope: "tag", spans: head });
  }
  return dim ? lines.map((l) => ({ ...l, spans: dimmed(l.spans) })) : lines;
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

/** Whether `hide` hides the turn's tag lines, the start line's 🔻🔖 and
 * the receipt's 🔺🔖, with the blank rows that set them apart: the hide
 * path `name.tag` (asked 2026-10-20). */
export function tagsHidden(hide: readonly string[]): boolean {
  return hidden(hide, "name.tag");
}

/** The line under the prompt as its turn starts, dim, from a status
 * document: 🔻🔖, the tag of the turn opened last, `transcript.prompt_id`
 * and `turn_index`, and when its prompt was stamped, `transcript.turn_s`;
 * without the stamp, the tag alone, and nothing with neither, or under the
 * hide path `name.tag`. */
export function startLine(fig: Dict, hide: readonly string[] = []): Span[] {
  if (tagsHidden(hide)) return [];
  const tr = decodeTranscript(fig.transcript);
  const at = tr.turn_s || null;
  const text = turnHead(E_TURN_AHEAD, tr.prompt_id, tr.turn_index,
    at === null ? null : ymd(at), at === null ? null : hms(at));
  return text ? [span(text, null, true)] : [];
}
