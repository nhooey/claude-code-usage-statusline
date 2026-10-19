// Pure layout for Claude's prepared Stop-cost report.
//
// A port of coding_agent_usage_line/claude_cost_render.py, function for
// function.  The caller supplies turns plus already-prepared window,
// accounting and plan totals: each turn's cost and window shares are worked
// out before drawing, and only read here.  Nothing here reads a transcript,
// a cache, an account source, the clock or the environment.  The metric
// groups are arguments, so the groups claude_cost.ts draws stay beside the
// notes claude.py keeps on them.
//
// Labels, tags and groups are all spans, joined into escape codes once,
// where renderCostLine hands back the finished rows.  As formatting.ts
// does, every function that measures takes the Settings first, since the
// width table is the terminal's and not this module's.
import {
  C_CHROME_CONT, C_CHROME_LEFT, C_MIN_GAP, C_RIGHT_MARGIN, E_TURN_ID,
  E_TURN_PAST, TURN_ID_HEX,
} from "./spec.ts";
import { fitCols, trunc, visWidth } from "./formatting.ts";
import type { Settings } from "./formatting.ts";
import { indent, join, lstrip, rstrip, span, spans, width } from "./spans.ts";
import type { Span, SpanLike } from "./spans.ts";
import { pyIntStr, pySlice } from "./py.ts";
import { cmpStr } from "./claude_records.ts";
import type { Turn } from "./claude_records.ts";
import type { Accounting } from "./claude_calib.ts";

// A metric group, a label and the chrome its row sits beside.
export type Row = readonly [Span[], string, number];

/** CostOpts, the NamedTuple: how the receipt is laid out, from the flags. */
export type CostOpts = {
  readonly prefix: string;
  readonly label: string;
  readonly totals_label: string;
  readonly cols: number | null;
  readonly colour: boolean;
  readonly totals: boolean;
  readonly right_align: boolean;
  readonly session_id: string;
  readonly compact_label: string;
  readonly agents_label: string;
  readonly account_totals: boolean;
  readonly stamps: boolean;
  readonly force_newline: boolean;
};

type CostOptsFirst = "prefix" | "label" | "totals_label" | "cols" |
  "colour" | "totals" | "right_align";

/** CostOpts(...) with the NamedTuple's defaults for the fields after
 * right_align. */
export function costOpts(o: Pick<CostOpts, CostOptsFirst> &
  Partial<CostOpts>): CostOpts {
  return Object.freeze({
    session_id: "", compact_label: "", agents_label: "",
    account_totals: true, stamps: true, force_newline: false, ...o,
  });
}

/** `name`, "F_CRM", where the receipt is in colour (--color), and null,
 * the terminal's own, where it is not. */
export function inkColour(colour: boolean, name: string): string | null {
  return colour ? name : null;
}

/** The row's prefix, then its label in bold: "P " and a bold "A". */
export function painted(prefix: string, value: string): Span[] {
  const out = spans(prefix);
  if (value) {
    if (out.length) out.push(span(" "));
    out.push(span(value, null, false, true));
  }
  return out;
}

/** " ".join(part for part in (prefix, label) if part). */
function plainHead(prefix: string, label: string): string {
  return [prefix, label].filter((part) => part).join(" ");
}

/** The label cut to the room left beside the group: what place and
 * placeStacked fall back to when the full label will not fit. */
function cutHead(st: Settings, opts: CostOpts, label: string,
  room: number): Span[] {
  const keep = trunc(st, label, Math.max(0, room -
    visWidth(opts.prefix, st.widths) - 1 - C_MIN_GAP));
  return keep ? painted(opts.prefix, keep) : spans(opts.prefix);
}

/** Place one finished cost row. */
export function place(st: Settings, group: SpanLike, opts: CostOpts,
  label: string, chrome: number): Span[] {
  const g = spans(group);
  if (opts.cols && opts.right_align) {
    const room = opts.cols - chrome - C_RIGHT_MARGIN - width(g, st.widths);
    const pad = room - visWidth(plainHead(opts.prefix, label), st.widths) -
      C_MIN_GAP;
    if (pad >= 0) {
      return spans([" ".repeat(pad), painted(opts.prefix, label),
        " ".repeat(C_MIN_GAP), g]);
    }
    return spans([cutHead(st, opts, label, room), " ".repeat(C_MIN_GAP), g]);
  }
  const head = painted(opts.prefix, label);
  return head.length ? spans([head, " ", g]) : g;
}

/** The shared tight/room/base geometry for a block of cost rows. */
export function stackMetrics(st: Settings, rows: readonly Row[],
  opts: CostOpts): [number, number, number] {
  const tight = Math.max(...rows.map(([group, , chrome]) =>
    chrome + width(group, st.widths)));
  const room = (opts.cols ?? 0) - C_RIGHT_MARGIN - tight;
  const widest = Math.max(...rows.map(([, label]) =>
    visWidth(plainHead(opts.prefix, label), st.widths)));
  return [tight, room, room - widest - C_MIN_GAP];
}

/** Place several rows as one aligned block. */
export function placeStacked(st: Settings, rows: readonly Row[],
  opts: CostOpts): Span[][] {
  if (!(opts.cols && opts.right_align)) {
    return rows.map(([group, label]) => {
      const head = painted(opts.prefix, label);
      return head.length ? rstrip(lstrip([head, " ", group])) : spans(group);
    });
  }
  const [tight, room, base] = stackMetrics(st, rows, opts);
  return rows.map(([group, label, chrome]) => {
    const shift = tight - chrome - width(group, st.widths);
    if (base >= 0) {
      return spans([" ".repeat(Math.max(0, base + shift)),
        painted(opts.prefix, label), " ".repeat(C_MIN_GAP), group]);
    }
    return spans([" ".repeat(Math.max(0, shift)),
      cutHead(st, opts, label, room), " ".repeat(C_MIN_GAP), group]);
  });
}

/** 🔺🔖 8f37748e #12: the turn the 🎤 row bills, by the head of its
 * promptId and Claude Code's turn index.  Each half is drawn only where the
 * transcript wrote it, and the tag not at all where it wrote neither. */
export function turnTag(t: Turn, colour: boolean): Span[] {
  const idx = t.turn_index, pid = t.prompt_id;
  const parts = [...(pid ? [pySlice(pid, null, TURN_ID_HEX)] : []),
    ...(idx !== null ? ["#" + pyIntStr(idx)] : [])];
  if (!parts.length) return [];
  return [span(E_TURN_PAST + E_TURN_ID + " "),
    span(parts.join(" "), inkColour(colour, "F_CRM"))];
}

// The agent id on a 👥 row, cut as the agent panel cuts it, and the fewest
// columns of its name worth drawing after it.
export const AGENT_ID_W = 10, AGENT_NAME_MIN = 6;

/** The name and id of the agent a 👥 row bills, in at most `room`
 * columns: as much of the name as fits, then the id padded to AGENT_ID_W,
 * so the ids of a block of 👥 rows stand in one column beside their 📊s.
 * The id whole or nothing. */
export function agentTag(st: Settings, t: Turn, colour: boolean,
  room: number): Span[] {
  const aid = t.agent_id;
  if (!aid || room < AGENT_ID_W) return [];
  const id = [span(fitCols(st, aid, AGENT_ID_W), inkColour(colour, "F_CRM"))];
  id.push(span(" ".repeat(Math.max(0, AGENT_ID_W - width(id, st.widths)))));
  const left = room - AGENT_ID_W - 1;
  const name = t.agent_name && left >= AGENT_NAME_MIN
    ? trunc(st, t.agent_name, left) : "";
  return spans([name ? name + " " : "", id]);
}

/** One plan reading's totals for the totals row: {} where there is none. */
export type PlanTotals = { readonly sess?: number; readonly week?: number };

/** The figures document's `accounting`: one per turn in order, and the
 * session's. */
export type CostAccounting = {
  readonly turns: readonly Accounting[];
  readonly session: Accounting;
};

/** cost_group's shape: a turn and its accounting drawn as a group. */
export type CostGroup = (st: Settings, t: Turn, shares: Accounting,
  win: number, colour: boolean, now: number, acct: boolean,
  stamps: boolean) => Span[];

/** cost_totals_group's shape: every turn and the session's accounting. */
export type TotalsGroup = (st: Settings, turns: readonly Turn[],
  totals: PlanTotals, win: number, colour: boolean, now: number,
  shares: Accounting, acct: boolean, stamps: boolean) => Span[];

/** Lay out prepared Claude cost rows; all accounting is supplied by the
 * caller.  `costGroup` and `totalsGroup` are pure builders that draw a
 * group from a turn and its accounting, so nothing here divides by the
 * plan.  The one place the receipt's spans become escape codes. */
export function renderCostLine(st: Settings, turns: readonly Turn[],
  opts: CostOpts, win: number, accounting: CostAccounting,
  planTotals: PlanTotals, now: number, costGroup: CostGroup,
  totalsGroup: TotalsGroup): string {
  if (!turns.length) return opts.prefix + " (no prompts recorded yet)";
  const colour = opts.colour;
  const perTurn = accounting.turns;
  const prompts: number[] = [];
  turns.forEach((t, i) => {
    if (t.calls && !t.compact && !t.agent) prompts.push(i);
  });
  const lastIndex = prompts.length ? prompts[prompts.length - 1]
    : turns.length - 1;
  const previous = prompts.length > 1 ? prompts[prompts.length - 2] : -1;
  const last = turns[lastIndex];
  // By index, so each row's group reads its own turn's accounting.
  let pending: number[] = [];
  if (turns.some((t) => t.reported)) {
    turns.forEach((t, i) => {
      if ((t.compact && !t.reported) || t.agent) pending.push(i);
    });
  } else {
    for (let i = previous + 1; i < lastIndex; i++) {
      if (turns[i].compact) pending.push(i);
    }
    turns.forEach((t, i) => {
      if (t.agent) pending.push(i);
    });
    // Array#sort is stable, as list.sort is, and cmpStr orders by code
    // point, as Python compares strings.
    pending = [...pending].sort((a, b) => cmpStr(turns[a].ts, turns[b].ts));
  }
  const acct = opts.account_totals, stamps = opts.stamps;
  const spec: Row[] = pending.map((at, index) => [
    costGroup(st, turns[at], perTurn[at], win, colour, now, acct, stamps),
    turns[at].agent ? opts.agents_label : opts.compact_label,
    index === 0 ? C_CHROME_LEFT : C_CHROME_CONT]);
  spec.push([
    costGroup(st, last, perTurn[lastIndex], win, colour, now, acct, stamps),
    last.compact ? opts.compact_label : opts.label,
    !spec.length ? C_CHROME_LEFT : C_CHROME_CONT]);
  if (opts.totals) {
    spec.push([totalsGroup(st, turns, planTotals, win, colour, now,
      accounting.session, acct, stamps), opts.totals_label, C_CHROME_CONT]);
  }
  const flatten = (rows: readonly Row[]): Row[] =>
    rows.map(([group, label]) => [group, label, C_CHROME_CONT]);
  let leadNewline = opts.force_newline;
  if (!leadNewline && opts.cols && opts.right_align) {
    const b = stackMetrics(st, flatten(spec), opts)[2];
    leadNewline = stackMetrics(st, spec, opts)[2] < 0 && 0 <= b;
  }
  const lead = pending.length + (last.compact ? 1 : 0);

  const drawn = (rows: readonly SpanLike[], newline = leadNewline): string =>
    (newline ? "\n" : "") + rows.map((row) => join(row, false, true))
      .join("\n");

  const laidOut = (ownLine: boolean): Span[][] => {
    const flat = ownLine ? flatten(spec) : spec;
    const rows = placeStacked(st, flat, opts).map((row) => rstrip(row));
    // Each 👥 row bills one agent, and names it in its pad, C_MIN_GAP left
    // of its 📊 the way the turn tag sits on the 🎤 row.
    pending.forEach((at, index) => {
      const t = turns[at];
      if (!t.agent) return;
      const row = rows[index];
      if (!(opts.cols && opts.right_align)) {
        // Flush left there is no pad, and no column to keep: the tag
        // leads the row.
        const tag = agentTag(st, t, colour, AGENT_ID_W + 1 + 40);
        rows[index] = tag.length ? spans([tag, " ", row]) : row;
        return;
      }
      const chart = indent(row);
      const tag = agentTag(st, t, colour, chart - C_MIN_GAP);
      if (tag.length) {
        rows[index] = spans([
          " ".repeat(Math.max(0, chart - C_MIN_GAP - width(tag, st.widths))),
          tag, " ".repeat(C_MIN_GAP), lstrip(row, " ")]);
      }
    });
    if (lead && rows.length > lead) rows.splice(lead, 0, []);
    return rows;
  };

  const tag = last.compact ? [] : turnTag(last, colour);
  if (!tag.length) return drawn(laidOut(leadNewline));
  // The tag names the turn the 🎤 row bills, so it goes on that row and on
  // no other: in its pad, C_MIN_GAP columns left of its 📊, where the pad
  // has room.  The 🎤 row follows the 👥 and compaction rows and the blank
  // line laidOut puts under them, when there are any.
  let rows = laidOut(leadNewline);
  const at = lead && rows.length > lead ? lead + 1 : 0;
  let chart = indent(rows[at]);
  const room = chart - width(tag, st.widths) - C_MIN_GAP;
  if (room >= 0) {
    rows[at] = spans([" ".repeat(room), tag, " ".repeat(C_MIN_GAP),
      lstrip(rows[at], " ")]);
    return drawn(rows);
  }
  // No room: the tag takes a line of its own directly above the 🎤 row,
  // its 🔖 over the row's 📊 with 🔺 just left of it.  Under 👥 or
  // compaction rows that is the blank line between them and the 🎤 row.
  if (at) {
    rows[at - 1] = spans([" ".repeat(Math.max(0,
      chart - visWidth(E_TURN_PAST, st.widths))), tag]);
    return drawn(rows);
  }
  // With the 🎤 row first, it is the line beside Claude Code's chrome, so
  // the rows below it are all continuation lines, and the first line's
  // extra C_CHROME_LEFT - C_CHROME_CONT columns come off the pad.
  rows = laidOut(true);
  chart = indent(rows[0]);
  const pad = chart - (C_CHROME_LEFT - C_CHROME_CONT) -
    visWidth(E_TURN_PAST, st.widths);
  return " ".repeat(Math.max(0, pad)) + join(tag) + "\n" +
    drawn(rows, false);
}
