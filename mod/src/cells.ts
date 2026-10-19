// The redesigned grid's cells and label pieces, from figures to spans.
//
// One renderer per GRID_CELLS key, in CELLS, and the helpers that build the
// pieces of each row's label.  The band and the receipt (band.ts,
// receipt.ts) draw real figures through them and mod/tools/layout-mockup.ts
// draws its made-up ones, so a cell looks the same in all three.  Each
// takes plain figures, never a figures document: reading a document is the
// builders' job, and a cell here cannot tell where its figures came from.
//
// The cells are the agent panel's, from claude_subagent_render.ts, with
// claude_render.ts's 💰 and 🧩, since the grid takes the panel's columns.
// What the panel has no cell for is drawn here the way today's cells draw
// the same case: the context's growth over a turn, an estimate marked "~"
// as renderCtx marks one, a duration handed over as seconds.
//
// Nothing here reads the clock or the environment.  The clock cells draw
// `now` in the process's TZ, which the edge sets from the document's
// `clock.tz`, as claude_cost.ts's do.
import {
  E_ACCT, E_BOT, E_COST, E_COSTLINE, E_DATE, E_DIR, E_DIRTY, E_GIT_BAD,
  E_GIT_OK, E_IDLE, E_PCT, E_PR, E_PROJ, E_RESET, E_SESS, E_SESSION, E_STY,
  E_TIME, E_TURN, E_TURN_ID, E_WEEK, K, MAG_COST, MAG_DUR_S, TURN_ID_HEX,
} from "./spec.ts";
import {
  durFmt, humanize, limitPct, magDim, moneyFig, padVal, visWidth,
} from "./formatting.ts";
import type { Settings } from "./formatting.ts";
import { span } from "./spans.ts";
import type { Span } from "./spans.ts";
import { pyFormatF, pyIntStr, pyRstrip, pySlice } from "./py.ts";
import { renderCost, renderTokens } from "./claude_render.ts";
import {
  aCtxW, renderAgentCache, renderAgentCtx, renderAgentDiff, renderAgentEta,
  renderAgentLimit, renderAgentModel, renderAgentRate, renderAgentSplit,
} from "./claude_subagent_render.ts";
import type { Piece } from "./grid.ts";

// ════════════════════════════════════════════════════════════════════════════
// The cells, one per GRID_CELLS key.  Each returns [] where it has nothing
// to draw, and the grid leaves the column blank.
// ════════════════════════════════════════════════════════════════════════════

/** model: the family and version, then the effort's glyph. */
function model(st: Settings, modelId: string, effort: string): Span[] {
  return renderAgentModel(st, modelId, effort);
}

/** rate, 🛫: tokens a second, or nothing with no reading. */
function rate(st: Settings, perSecond: number | null): Span[] {
  return renderAgentRate(st, perSecond);
}

/** cost, 💰: dollars.  An estimate, `est`, is marked "~" before the
 * figure, as renderCtx marks an estimated context; the mark takes the
 * column the profile pads 💰 with where there is one, and where the figure
 * would still not fit, its decimal goes. */
function cost(st: Settings, usd: number | null, est = false): Span[] {
  if (usd === null) return [];
  if (!est) return renderCost(st, pyFormatF(usd, 4));
  const room = visWidth(st.sCost, st.widths) + 4 - visWidth(E_COST, st.widths);
  // moneyFig's unit column kept where it fits, so the figure stands where
  // an exact one would.
  const whole = moneyFig(st, usd);
  let fig = "~" + whole;
  if (visWidth(fig, st.widths) > room) fig = "~" + pyRstrip(whole);
  if (visWidth(fig, st.widths) > room && usd >= K - K / 2000.0) {
    fig = "~" + pyFormatF(usd / K, 0) + "k";
  }
  return [span(E_COST),
    span(padVal(st, room, fig), "F_YEL", magDim(usd, MAG_COST))];
}

/** ctx, 🧠: the context's size and its share of the window.  An estimate
 * is marked "~" before the size, in the blank between the two figures. */
function ctx(st: Settings, tokens: number, window: number,
  est = false): Span[] {
  const out = renderAgentCtx(st, tokens, window);
  if (!est || !out.length) return out;
  // [🧠, size, " ", share]: the size and its blank become one field.
  const [mark, size, , share] = out;
  return [mark, { ...size,
    text: padVal(st, 5, "~" + pyRstrip(size.text.trimStart())) }, share];
}

/** ctx on a turn's row, 🧠 +34k +3٪: how much the context grew, in
 * tokens and in points of the window, signed, the sign the tokens'.  The
 * two fields keep the panel cell's widths, and where a five-character
 * figure would push the cell wider, the blank between them goes. */
function ctxGrowth(st: Settings, tokens: number,
  points: number | null): Span[] {
  const sign = tokens < 0 ? "-" : "+";
  const size = padVal(st, 4, sign + pyRstrip(humanize(st, Math.abs(tokens))));
  const pct = points === null ? ""
    : padVal(st, 4, sign + pyIntStr(Math.abs(points)) + E_PCT);
  const room = aCtxW(st) - visWidth(st.sCtx, st.widths);
  const gap = visWidth(size + " " + pct, st.widths) > room ? "" : " ";
  return [span(st.sCtx), span(size + gap + pct, "F_PNK")];
}

/** ctxGrowth from a turn's `dctx` over the window: nothing where the turn
 * has no reading, as the receipt's 🧠 draws nothing, and no points where
 * there is no window, as the panel's share. */
function growth(st: Settings, dctx: number | null, window: number): Span[] {
  if (dctx === null) return [];
  return ctxGrowth(st, dctx,
    window > 0 ? Math.trunc(100 * dctx / window) : null);
}

/** tok, 🧩: ▴ the weighted input and ▾ the output. */
function tok(st: Settings, up: number | null, down: number): Span[] {
  return renderTokens(st, up, down);
}

/** cache, 🎯: the share of the input read from the cache; nothing for a
 * negative rate, which is no input to rate. */
function cache(st: Settings, pct: number | null): Span[] {
  return renderAgentCache(st, pct);
}

/** clock, ⌛: a duration in seconds, the panel's ⌛ drawn from it rather
 * than from a start. */
function clock(st: Settings, secs: number | null): Span[] {
  if (secs === null) return [];
  const run = Math.max(0.0, secs);
  return [span(E_IDLE), span(padVal(st, 4, durFmt(st, run)), "F_PRW",
    magDim(run, MAG_DUR_S))];
}

/** eta, ⛳: the time left on `reported`, an (epoch, seconds) report or []
 * for none, at `now`, blank for none; late in amber, or red when
 * `signedOff`.  `startS` is when the work began, or null. */
function eta(st: Settings, reported: readonly number[] | null,
  startS: number | null, now: number, signedOff = false): Span[] {
  return renderAgentEta(st, reported as [number, number] | [] | null,
    startS === null ? null : startS * 1000, now, "running", null, signedOff);
}

/** split, 🤖 🔧 🚦: gauges of model, tool and the rest of `elapsed`. */
function split(elapsed: number | null, modelS: number | null,
  toolS: number | null): Span[] {
  return renderAgentSplit(elapsed, modelS, toolS);
}

/** five, 🔋: a share of the five-hour window, drawn only while the plan
 * has a reading (`pctS`, the window's own percentage as given), "?" where
 * the share is not known. */
function five(st: Settings, pctS: string, share: number | null): Span[] {
  return renderAgentLimit(st, E_SESS, pctS, share, "F_LIM_SESS");
}

/** week, 🪫: five's for the weekly window, a digit wider. */
function week(st: Settings, pctS: string, share: number | null): Span[] {
  return renderAgentLimit(st, E_WEEK, pctS, share, "F_LIM_WEEK", true,
    false, 4);
}

/** diff, 💾: lines added and removed, blank when neither: none changed,
 * or none counted. */
function diff(st: Settings, added: number, removed: number): Span[] {
  return renderAgentDiff(st, { lines_added: added, lines_removed: removed });
}

/** The cells by GRID_CELLS key, with ctx's two other readings. */
export const CELLS = {
  model, rate, cost, ctx, ctxGrowth, growth, tok, cache, clock, eta, split,
  five, week, diff,
};

/** A cache rate as the receipt works it out: int(100 * read / input), or
 * -1 for no input at all. */
export function cacheRate(read: number, whole: number): number {
  return whole ? Math.trunc(100 * read / whole) : -1;
}

// ════════════════════════════════════════════════════════════════════════════
// Label pieces.
// ════════════════════════════════════════════════════════════════════════════

/** A part of a row's label, with the path --hide names it by; see Piece. */
export function piece(path: string, text: string, colour: string | null = null,
  drop = 0, dim = false): Piece {
  return { path, spans: [span(text, colour, dim)], drop };
}

/** The clock's date, strftime("%Y-%m-%d") of localtime(now). */
export function ymd(now: number): string {
  const d = new Date(Math.floor(now) * 1000);
  return String(d.getFullYear()).padStart(4, "0") + "-" +
    String(d.getMonth() + 1).padStart(2, "0") + "-" +
    String(d.getDate()).padStart(2, "0");
}

/** The clock's time, strftime("%H:%M:%S") of localtime(now). */
export function hms(now: number): string {
  const d = new Date(Math.floor(now) * 1000);
  const two = (n: number): string => String(n).padStart(2, "0");
  return two(d.getHours()) + ":" + two(d.getMinutes()) + ":" +
    two(d.getSeconds());
}

/** The time until a reset at `epoch`, as shortDur reads a bare epoch:
 * "now" once it has passed, null with no reset. */
export function untilReset(st: Settings, epoch: number | null,
  now: number): string | null {
  if (epoch === null) return null;
  const delta = Math.trunc(epoch) - Math.trunc(now);
  return delta <= 0 ? "now" : durFmt(st, delta);
}

/** 💳 account, then each window's 🔜 reset where it has one, then 📅 and 🕐,
 * which leave first on a narrow terminal. */
export function accountLabel(st: Settings, sess: number | null,
  week: number | null, sessReset: string | null, weekReset: string | null,
  date: string, time: string): Piece[] {
  // Each window whole on the label, its share then its reset, since the
  // row has no figure in the plan columns to sit under: 🔋 15٪ 🔜 6.7m.
  // Three digits for both, so 🪫 reads 87٪ as 🔋 does, not the 87.0٪ the
  // wider 🪫 column draws for an agent's small share.
  const plan = (path: string, mark: string, colour: string,
    v: number | null, reset: string | null): Piece[] => {
    if (v === null && reset === null) return [];
    const out: Piece[] = [];
    out.push({ path, spans: [span(mark + " "), ...(v === null ? [] :
      [span(limitPct(st, v, 3) + E_PCT, colour)]), span(" ")], drop: 0 });
    if (reset !== null) {
      out.push(piece("plan.reset", E_RESET + " " + reset + "  ", null, 0,
        true));
    } else {
      out.push(piece(path, " "));
    }
    return out;
  };
  const windows = [
    ...plan("plan.five_hour", E_SESS, "F_LIM_SESS", sess, sessReset),
    ...plan("plan.week", E_WEEK, "F_LIM_WEEK", week, weekReset)];
  // No blanks after the last window: they would only take room a cut
  // label needs.
  const last = windows.at(-1);
  if (last) {
    const s = last.spans.at(-1)!;
    windows[windows.length - 1] = { ...last, spans: [...last.spans.slice(0,
      -1), { ...s, text: s.text.replace(/ +$/, "") }] };
  }
  return [
    piece("clock.date", E_DATE + " " + date + "  ", null, 2, true),
    piece("clock.time", E_TIME + " " + time + "  ", null, 3, true),
    piece("name.label", E_ACCT + " "), ...windows];
}

/** 🎤 and the turn's prompt, or today's placeholder, dim, for none. */
export function turnLabel(prompt: string): Piece[] {
  return [piece("name.label", E_TURN + " "), prompt
    ? piece("chat.prompt", prompt, "F_CHAT_B")
    : piece("chat.prompt", "(no prompt yet)", "F_CHAT_B", 0, true)];
}

/** 🤖💬 and the main thread's reply, or today's placeholder for none;
 * `doing`, what it is doing, goes before the reply. */
export function mainLabel(reply: string, doing: Piece | null = null):
  Piece[] {
  return [piece("name.label", E_BOT + " "), ...(doing ? [doing] : []),
    reply ? piece("chat.reply", reply, "F_CHAT_B")
      : piece("chat.reply", "(no reply yet)", "F_CHAT_B", 0, true)];
}

/** Where the session works.  Each part is "" where there is none. */
export type Workspace = {
  readonly project: string;
  readonly branch: string;
  readonly dirty: boolean;
  readonly dir: string;
  readonly pr: string;
  readonly style: string;
};

/** 🎮 session and its workspace: 📦 the project, 🌿 the branch (🍂 and ✱ on
 * a dirty tree, as today's line 3 draws one), 📁 the directory, 🔀 the PR and
 * 🎨 the output style, the last three leaving first, 🎨 before 🔀 before
 * 📁. */
export function sessionLabel(ws: Workspace | null): Piece[] {
  const out = [piece("name.label", E_SESSION + " ")];
  if (!ws) return out;
  if (ws.project) {
    out.push(piece("workspace.project", E_PROJ + ws.project + " ", "F_BLU"));
  }
  if (ws.branch) {
    out.push(ws.dirty
      ? piece("workspace.branch", E_GIT_BAD + ws.branch + " " + E_DIRTY +
        "  ", "F_AMB")
      : piece("workspace.branch", E_GIT_OK + ws.branch + "  ", "F_GRN"));
  }
  if (ws.dir) out.push(piece("workspace.dir", E_DIR + ws.dir + "  ", "F_BLU", 3));
  if (ws.pr) out.push(piece("workspace.pr", E_PR + "#" + ws.pr + "  ", "F_CYN", 2));
  if (ws.style) out.push(piece("workspace.style", E_STY + ws.style, "F_CYN", 1));
  return out;
}

/** A receipt row's label: the band row's behind 📊. */
export function receiptLabel(label: readonly Piece[]): Piece[] {
  return [piece("name.receipt", E_COSTLINE + " "), ...label];
}

/** A turn's tag and when, "🔺🔖 8f37748e #12  📅 2026-10-19  🕐 13:06:02":
 * `arrow` then 🔖, the head of the promptId and Claude Code's turn index,
 * each only where the transcript wrote it and the tag not at all where it
 * wrote neither, as turnTag draws it; then the date and the time, where
 * there is a time. */
export function turnHead(arrow: string, promptId: string,
  turnIndex: number | null, date: string | null,
  time: string | null): string {
  const parts = [...(promptId ? [pySlice(promptId, null, TURN_ID_HEX)] : []),
    ...(turnIndex !== null ? ["#" + pyIntStr(turnIndex)] : [])];
  const tag = parts.length ? arrow + E_TURN_ID + " " + parts.join(" ") : "";
  const when = date !== null && time !== null
    ? E_DATE + " " + date + "  " + E_TIME + " " + time : "";
  return tag && when ? tag + "  " + when : tag + when;
}
