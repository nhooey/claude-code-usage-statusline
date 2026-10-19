// Pure Claude subagent-panel row layout.
//
// A port of coding_agent_usage_line/claude_subagent_render.py, function for
// function and under the same names in camelCase.  Preparation (sidecar
// lookup, usage parsing, limits and source selection) stays the caller's;
// this lays out the facts it is handed.  Its cells return spans, and
// renderTaskRows joins each row into escape codes, where the panel prints
// it.  The Python's docstrings carry each cell's history and argument and
// are not copied: the comments here say what the port has to do to match.
//
// THE USAGE IS READ AS THE PYTHON READS IT, BY ATTRIBUTE WITH A DEFAULT.
// The renderer is written against getattr(usage, name, default), not
// against AgentUsage, and the shared cases pin what it does with a usage
// that is None or holds only some fields.  So a usage here is any value,
// read through `ua`, which is getattr's rule for a dict: an own key's
// value, null included, else the default.
//
// The constants that measure a glyph (A_ETA_W, A_DIFF_W, A_CTX_W and the
// cost and token cells) depend on the terminal profile, which the Python
// reads at import; here they are computed from the Settings each time.
import {
  E_ETA, E_GAUGE, E_GIT_OK, E_HUNDRED, E_IDLE, E_INBOX, E_KIDS, E_MOD,
  E_MODE_AGENTS, E_MODE_API_ERROR, E_MODE_DONE, E_MODE_ETA, E_MODE_FAILED,
  E_MODE_KILLED, E_MODE_MONITOR, E_MODE_QUEUED, E_MODE_SHELL, E_PCT,
  E_PHASE_END, E_PHASE_PAUSE, E_PHASE_RUN, E_RATE, E_ROW_AGENTS,
  E_ROW_COMPACT, E_SESS, E_SPIN, E_TOOL, E_TREE_BAR, E_TREE_END, E_TREE_MID,
  E_TREE_NODE, E_TREE_OPEN, E_WAIT, E_WEEK, E_WORK, GAUGE_W, LIM_FIG_W,
  MAG_DUR_S, MAG_RATE, MAG_SHARE_AGENT, MAG_TOK, QUIET_S, QUIET_WARN_S,
  VAL_W, VAL2_W,
  E_CACHE, E_DIFF, E_DOWN, E_EFF_HIGH, E_EFF_LOW, E_EFF_MAX, E_EFF_MED,
  E_EFF_XHIGH, E_SUP_DIGITS, E_UP, MAG_COST, MAG_DIFF, MODEL_FAMILIES,
} from "./spec.ts";
import {
  cacheColor, durFmt, fitCols, humanize, limitPct, magDim, moneyFig,
  padVal, rateFig, seg, visWidth,
} from "./formatting.ts";
import type { Settings } from "./formatting.ts";
import {
  ink, join, paint, rstrip, span, spans, width,
} from "./spans.ts";
import type { Span, SpanLike } from "./spans.ts";
import {
  isDict, pyAsciiDigits, pyFormatF, pyGet, pyIntStr, pyIntText, pyLen,
  pyOr, pyRstrip, pySlice, pyTruthy,
} from "./py.ts";
import type { Dict } from "./py.ts";
import { pyFloat, pyFloatText, pyStr } from "./sources.ts";
import { WAITING_TOOLS, etaFinish, squash } from "./claude_records.ts";
import type { Limits } from "./claude_sources.ts";

export const A_KIND_W = 2, A_ID_W = 10, A_STATE_W = 2;
export const A_HEAD_GAP = 1, A_NAME_MIN = 8, A_ACT_MIN = 8, A_CLOCK_W = 6,
  A_RATE_W = 8, A_GAP = 2, A_TICK_S = 5.0;
// 🤖 🔧 🚦, each two columns of mark and GAUGE_W of gauge, one space apart.
export const A_SPLIT_W = 3 * (2 + GAUGE_W) + 2;
export const A_LIMIT_W = 2 + LIM_FIG_W, A_TREE_W = 2;
// 🪫 one column wider than 🔋, for the decimal limitPct adds at digits=4.
export const A_LIMIT_WEEK_W = A_LIMIT_W + 1;
// ⛳ and five for the figure: durFmt's widest is four, and an overrun
// spends one more on its "+".
export const A_ETA_FIG_W = 5;
export const A_SPIN_W = 1;
// The name room a row must still have after paying for the tree beside its
// right group; see the Python.
export const A_TREE_ROOM = 40;
// 🧠's share of the agent's window at its widest, "100٪".
export const A_CTX_PCT_W = 4;
// The 🤖 state trades its rate for how long the agent has been quiet; see
// renderDoing.
export const A_SILENT_S = QUIET_S, A_SILENT_WARN_S = QUIET_WARN_S;
// The most a worktree's branch spends of the name's room, 🌿 not counted.
export const A_BRANCH_W = 16;

/** ⛳ and its figure: E_ETA measured on this terminal. */
export function aEtaW(st: Settings): number {
  return visWidth(E_ETA, st.widths) + A_ETA_FIG_W;
}

/** 💾 and the eleven columns renderDiff lays after it. */
export function aDiffW(st: Settings): number {
  return visWidth(E_DIFF + " ", st.widths) + 11;
}

/** 🧠, the size, a blank and the share: "🧠 124k 12٪". */
export function aCtxW(st: Settings): number {
  return visWidth(st.sCtx, st.widths) + 4 + 1 + A_CTX_PCT_W;
}

export const KIND_MARK: ReadonlyMap<string, string> = new Map([
  ["general-purpose", "🔩"], ["claude", "🎩"], ["Explore", "🔍"],
  ["Plan", "📐"], ["claude-code-guide", "📚"], ["statusline-setup", "📟"],
  ["fork", "🍴"], ["local_agent", "👥"], ["local_bash", "🐚"],
  ["local_workflow", "🔗"], ["remote_agent", "🌐"],
  ["in_process_teammate", "🎎"]]);
export const END_MARK: ReadonlyMap<string, string> = new Map([
  ["completed", E_MODE_DONE], ["failed", E_MODE_FAILED],
  ["killed", E_MODE_KILLED]]);
export const PAUSE_MARK: ReadonlyMap<string, string> = new Map([
  ["bash", E_MODE_SHELL], ["monitor", E_MODE_MONITOR]]);

// ════════════════════════════════════════════════════════════════════════════
// Reading the prepared records as the Python does.
// ════════════════════════════════════════════════════════════════════════════

/** An ETA as the records carry it: [] for none yet, [epoch, seconds left]
 * off the last report, null for no transcript to report in. */
export type Eta = readonly number[] | null;

/** One prepared task: (task, usage, meta, shares), each as the caller
 * handed it, so a field of the wrong shape reads as the Python's does. */
export type Prepared = readonly [unknown, unknown, unknown, unknown];

/** getattr(u, k, dflt) of a usage: see the header. */
function ua(u: unknown, k: string, dflt: unknown = null): unknown {
  return pyGet(u, k, dflt);
}

/** `getattr(u, k, ()) or ()`: a list field, empty for missing or false. */
function uaList(u: unknown, k: string): readonly any[] {
  const v = ua(u, k, []);
  return pyTruthy(v) ? (v as readonly any[]) : [];
}

/** str(v or ""): "" for a missing or false value. */
function strOr(v: unknown): string {
  return pyTruthy(v) ? pyStr(v) : "";
}

/** "%d" % n. */
function d(n: unknown): string {
  return pyIntStr(n as number);
}

/** float(v) / 1000.0, or null where float() raises: a startTime in
 * milliseconds as seconds. */
function msToS(v: unknown): number | null {
  const f = v === null || v === undefined ? null : pyFloat(v);
  return f === null ? null : f / 1000.0;
}

/** The task dicts that draw a row: a dict with a true id. */
function hasId(t: unknown): t is Dict {
  return isDict(t) && pyTruthy(t.id);
}

/** max(xs), the first of equals, as Python's; xs not empty. */
function pyMax(xs: readonly number[]): number {
  let m = xs[0];
  for (const x of xs.slice(1)) if (x > m) m = x;
  return m;
}

/** max(xs or [0]). */
function maxOr0(xs: readonly number[]): number {
  return xs.length ? pyMax(xs) : 0;
}

/** min(xs), the first of equals, as Python's; xs not empty. */
function pyMin(xs: readonly number[]): number {
  let m = xs[0];
  for (const x of xs.slice(1)) if (x < m) m = x;
  return m;
}

// ════════════════════════════════════════════════════════════════════════════
// The status line's cells the panel borrows.
//
// These are claude_render.py's render_tokens, render_cost, render_diff,
// model_spec (with model_label), effort_glyph, eta_reading and inherit_eta,
// copied here because claude_render.ts is being written beside this
// module.  Once it lands, each of these becomes an import of its own, and
// the panel's cases prove the two copies were one.
// ════════════════════════════════════════════════════════════════════════════

function renderTokens(st: Settings, up: unknown, down: unknown,
  downW: number = VAL2_W): Span[] {
  if (up === null || up === undefined) return [];
  const u = up as number, dn = down as number;
  return [span(st.sTok),
    span(padVal(st, VAL_W, E_UP + padVal(st, 4, humanize(st, u)), true),
      "F_TUP", magDim(u, MAG_TOK)),
    span(padVal(st, downW, E_DOWN + padVal(st, 4, humanize(st, dn))),
      "F_TDN", magDim(dn, MAG_TOK))];
}

function renderCost(st: Settings, costUsd: string,
  mark: string = st.sCost): Span[] {
  if (!costUsd || costUsd === "null") return [];
  const c = pyFloatText(costUsd);
  if (c === null || !Number.isFinite(c)) return [];
  return [span(mark),
    span(padVal(st, 4, moneyFig(st, c)), "F_YEL", magDim(c, MAG_COST))];
}

function renderDiff(st: Settings, added: string, removed: string): Span[] {
  if (!added) return [];
  // int(float(v)), or None where either raises, "inf" as well.
  const n = (v: string): number | null => {
    const f = pyFloatText(v);
    return f === null || !Number.isFinite(f) ? null : Math.trunc(f);
  };
  const half = (sign: string, v: number | null, col: string): Span => {
    const fig = v === null ? "?" : pyRstrip(humanize(st, v));
    return span(sign + padVal(st, 4, fig), col, magDim(v, MAG_DIFF));
  };
  return [span(E_DIFF + " "), half("+", n(added), "F_GRN"), span(" "),
    half("-", n(removed), "F_RED")];
}

const MODEL_VER = /^[-_. ]*(\p{Nd}{1,3})(?:[-_.](\p{Nd}{1,3}))?(?!\p{Nd})/u;

function modelLabel(modelId: string): string {
  const low = (modelId || "").toLowerCase();
  const fam = (MODEL_FAMILIES as readonly string[])
    .find((f) => low.includes(f.toLowerCase())) ?? "";
  if (!fam) return pySlice(modelId, null, VAL_W);
  const flow = fam.toLowerCase();
  const tail = low.slice(low.indexOf(flow) + flow.length);
  const m = MODEL_VER.exec(tail);
  if (!m) return fam;
  return fam + " " + [m[1], m[2]].filter((g) => g).join(".");
}

function modelSpec(modelId: string): string {
  const label = modelLabel(modelId);
  if (!label) return "";
  const sp = label.indexOf(" ");
  const fam = sp < 0 ? label : label.slice(0, sp);
  const ver = sp < 0 ? "" : label.slice(sp + 1);
  if (ver) {
    const c = pySlice(ver, null, 1);
    // A Unicode digit the version regex took; int() reads it.
    return pySlice(fam, null, 1) + (/^\p{Nd}$/u.test(c)
      ? Array.from(E_SUP_DIGITS)[Number(pyAsciiDigits(c))] : c);
  }
  return pySlice(fam, null, 2);
}

const EFFORTS: ReadonlyMap<string, string> = new Map([
  ["low", E_EFF_LOW], ["medium", E_EFF_MED], ["high", E_EFF_HIGH],
  ["xhigh", E_EFF_XHIGH], ["max", E_EFF_MAX]]);

function effortGlyph(effort: string): string {
  return EFFORTS.get(effort) ?? E_EFF_MED;
}

/** (share done, seconds left), [] for no live estimate, null for no
 * transcript; see claude_render.eta_reading. */
function etaReading(eta: Eta, startMs: unknown, now: number | null,
  status = "running", end: number | null = null):
  readonly [number, number] | readonly [] | null {
  if (eta === null || eta === undefined) return null;
  if (!eta.length) return [];
  let t = now === null ? Date.now() / 1000 : now;
  if (end !== null && (status === "killed" || status === "failed")) {
    t = Math.min(t, end);
  }
  let t0 = msToS(startMs);
  const [at, said] = eta;
  // A report older than the start is an agent Claude Code resumed after
  // it wrote one: the run is read from the report instead.
  if (t0 !== null) t0 = Math.min(t0, at);
  const total = said + (t0 !== null ? at - t0 : 0.0);
  const gone = t - (t0 !== null ? t0 : at);
  const share = total > 0 ? gone / total : 1.0;
  return [Math.min(1.0, Math.max(0.0, share)), total - gone];
}

/** `own` pushed out to the latest of `finishes`; see
 * claude_render.inherit_eta. */
function inheritEta(own: Eta, finishes: readonly (number | null)[],
  startS: number | null): Eta {
  const ends = finishes.filter((f): f is number => f !== null);
  const mine = own && own.length ? etaFinish(own) : null;
  if (mine !== null) ends.push(mine);
  if (!ends.length || (mine !== null && ends.length === 1)) return own;
  const at = startS ? startS : (own && own.length ? own[0] : pyMax(ends));
  return [at, pyMax(ends) - at];
}

// ════════════════════════════════════════════════════════════════════════════
// The cells.
// ════════════════════════════════════════════════════════════════════════════

/** Tokens a second over the panel's samples, A_TICK_S apart; null unless
 * running with two samples float() reads. */
export function tokenRate(samples: unknown, status: string): number | null {
  if (status !== "running" || !Array.isArray(samples) || samples.length < 2) {
    return null;
  }
  const first = pyFloat(samples[0]), last = pyFloat(samples.at(-1));
  if (first === null || last === null) return null;
  return Math.max(0.0, last - first) / (A_TICK_S * (samples.length - 1));
}

/** `emoji` and the agent's share of the window; `colour` names the row's
 * F_* constant. */
export function renderAgentLimit(st: Settings, emoji: string, pctS: string,
  share: number | null, colour: string, billed = true, dim = false,
  digits = 3): Span[] {
  if (!pctS || pyFloat(pctS) === null || !billed) return [];
  const style = ink(colour, dim);
  const w = LIM_FIG_W + digits - 3;
  let fig: Span;
  if (share === null || share === undefined) {
    fig = span(padVal(st, w, "?"), "F_CRM", true);
  } else if (share >= 99.5) {
    fig = paint(style, padVal(st, w, E_HUNDRED + E_PCT));
  } else {
    fig = paint(style, padVal(st, w, limitPct(st, share, digits) + E_PCT));
  }
  return [span(emoji), fig];
}

export function renderKind(agentType: string, taskKind: string): string {
  return KIND_MARK.get(agentType || taskKind) ?? E_ROW_AGENTS;
}

/** The row's two state marks, (phase, mode); see the Python's agent_state
 * for what each says. */
export function agentState(status: string, usage: unknown = null,
  waitingOn = false): [string, string] {
  if (status === "running") {
    const names = uaList(usage, "pending").map((p) => p[1]);
    const mode = ua(usage, "eta") === null ? ""
      : names.some((n) => WAITING_TOOLS.has(n)) ? E_WAIT
      : names.length ? E_TOOL : E_WORK;
    return [E_PHASE_RUN, mode];
  }
  if (status === "pending") return [E_PHASE_PAUSE, E_MODE_QUEUED];
  const eta = ua(usage, "eta") as Eta;
  const bg = ua(usage, "background", []);
  if (pyTruthy(ua(usage, "api_error", false)) &&
    (status === "completed" || status === "failed")) {
    // Claude Code calls an agent whose last request failed for good
    // completed; the mark says why it stopped.
    return [parked(status, eta, waitingOn, bg) ? E_PHASE_PAUSE : E_PHASE_END,
      E_MODE_API_ERROR];
  }
  if (parked(status, eta, waitingOn, bg)) {
    const kinds = uaList(usage, "background").map((b) => b[1]);
    const woke = (["bash", "monitor"] as const).find((k) => kinds.includes(k));
    return [E_PHASE_PAUSE, waitingOn ? E_MODE_AGENTS
      : woke !== undefined ? PAUSE_MARK.get(woke)! : E_MODE_ETA];
  }
  const end = END_MARK.get(status);
  if (end !== undefined) return [E_PHASE_END, end];
  return status ? [pySlice(status, null, 2), ""] : ["", ""];
}

const PHASES: readonly string[] = [E_PHASE_RUN, E_PHASE_PAUSE, E_PHASE_END,
  ""];

/** The phase circle and the mode mark after it; see agentState. */
export function renderState(status: string, usage: unknown = null,
  waitingOn = false): Span[] {
  const [phase, mode] = agentState(status, usage, waitingOn);
  return spans([phaseSpan(phase), mode]);
}

/** The phase circle alone: the mode is the Doing cell's; see renderDoing. */
export function renderPhase(status: string, usage: unknown = null,
  waitingOn = false): Span[] {
  return spans(phaseSpan(agentState(status, usage, waitingOn)[0]));
}

/** The phase circle, or a status never seen in amber. */
function phaseSpan(phase: string): Span {
  return span(phase, PHASES.includes(phase) ? null : "F_AMB");
}

/** A running agent's spinner, one frame on for each ⏺ it has written. */
export function renderSpin(status: string, usage: unknown = null): Span[] {
  if (status !== "running" || ua(usage, "eta") === null) return [];
  const one = Array.from(E_SPIN);
  const frames = [...one, ...one.reverse()];
  const n = pyOr(ua(usage, "blocks", 0), 0) as number;
  // Python's % takes the divisor's sign.
  const i = ((n % frames.length) + frames.length) % frames.length;
  return [span(frames[i], "F_SPIN")];
}

/** 👶🏻 and how many agents hang under this row on the panel. */
export function renderKids(n: number): Span[] {
  return !n ? [] : [span(E_KIDS), span(d(n), "F_CRM")];
}

export function renderAgentModel(st: Settings, modelId: string,
  effort: string): Span[] {
  if (!modelId) return [];
  return spans([E_MOD, span(padVal(st, 2, modelSpec(modelId)), "F_PUR"),
    effort && effort !== "null" ? effortGlyph(effort) : ""]);
}

export function renderAgentCache(st: Settings, cachePct: unknown): Span[] {
  if (cachePct === null || cachePct === undefined) return [];
  const p = cachePct as number;
  if (p < 0) return [];
  // The bare 🎯: the agent cell draws no paint pad after it.
  return [span(E_CACHE),
    paint(cacheColor(p), (p >= 100 ? E_HUNDRED : padVal(st, 2, d(p))) +
      E_PCT)];
}

/** 🧠, the agent's context size and its share of its own window, blank
 * where the payload gives no window; its column stays either way. */
export function renderAgentCtx(st: Settings, ctxTokens: number,
  window = 0): Span[] {
  if (ctxTokens <= 0) return [];
  const pct = window > 0
    ? pyIntStr(ctxTokens * 100 / window) + E_PCT : "";
  const style = ink("F_PNK", magDim(ctxTokens, MAG_TOK));
  return [span(st.sCtx), paint(style, padVal(st, 4, humanize(st, ctxTokens))),
    span(" "), paint(style, padVal(st, A_CTX_PCT_W, pct))];
}

/** 🤏 and how often the agent's window has been compacted. */
export function renderCompactions(n: number): Span[] {
  return !n ? [] : [span(E_ROW_COMPACT), span(d(n), "F_PNK")];
}

/** 📨 and how many messages wait for the agent's next tool round. */
export function renderInbox(n: number): Span[] {
  return !n ? [] : [span(E_INBOX), span(d(n), "F_CYN")];
}

/** How many background tasks of `kind` the agent has not heard the end
 * of; 0 once it failed or was killed, whose tasks stop with it. */
export function backgroundCount(status: string, usage: unknown,
  kind: string): number {
  if (status === "failed" || status === "killed") return 0;
  return uaList(usage, "background").filter((b) => b[1] === kind).length;
}

/** 💻 or 📡 and how many shells or Monitors it has running. */
export function renderBackground(mark: string, n: number): Span[] {
  return !n ? [] : [span(mark), span(d(n), "F_CRM")];
}

/** The agent's own +adds/-removes, in the status line's 💾 cell, drawn
 * even at "+0 -0". */
export function renderAgentDiff(st: Settings, usage: unknown): Span[] {
  return renderDiff(st, d(ua(usage, "lines_added", 0)),
    d(ua(usage, "lines_removed", 0)));
}

/** Seconds from the earlier of `first` and startTime to now, or to `end`;
 * null with neither start.  See the Python for why the earlier. */
export function agentElapsed(startMs: unknown, now: number | null,
  end: number | null = null, first: number | null = null): number | null {
  const starts = first === null ? [] : [first];
  const s = msToS(startMs);
  if (s !== null) starts.push(s);
  if (!starts.length) return null;
  const t0 = pyMin(starts);
  let t = now === null ? Date.now() / 1000 : now;
  if (end !== null) t = Math.min(t, Math.max(end, t0));
  return Math.max(0.0, t - t0);
}

/** ⌛ and the agent's age; see agentElapsed. */
export function renderAgentElapsed(st: Settings, startMs: unknown,
  now: number | null, end: number | null = null,
  first: number | null = null): Span[] {
  const run = agentElapsed(startMs, now, end, first);
  if (run === null) return [];
  return [span(E_IDLE), span(padVal(st, 4, durFmt(st, run)), "F_PRW",
    magDim(run, MAG_DUR_S))];
}

/** `parts` shared out as whole dots that always sum to `dots`: largest
 * remainder, ties to the earlier part, and a part of 1% or more that
 * rounds to nothing raised to one dot taken from the largest. */
export function gaugeDots(parts: readonly number[],
  dots = 4 * GAUGE_W): number[] {
  const total = parts.reduce((a, b) => a + b, 0);
  if (total <= 0) return parts.map(() => 0);
  const exact = parts.map((p) => dots * p / total);
  const n = exact.map((x) => Math.trunc(x));
  const short = dots - n.reduce((a, b) => a + b, 0);
  const order = parts.map((_, i) => i)
    .sort((a, b) => (n[a] - exact[a]) - (n[b] - exact[b]));
  for (const i of order.slice(0, Math.max(0, short))) n[i] += 1;
  parts.forEach((p, i) => {
    if (n[i] === 0 && p >= 0.01 * total) {
      n[n.indexOf(pyMax(n))] -= 1;
      n[i] = 1;
    }
  });
  return n;
}

/** `mark` and `n` dots of E_GAUGE, dim under MAG_DUR_S of its seconds. */
export function renderGauge(mark: string, secs: number, n: number): Span[] {
  const steps = Array.from(E_GAUGE);
  let cells = "";
  for (let k = 0; k < GAUGE_W; k++) {
    cells += steps[Math.max(0, Math.min(4, n - 4 * k))];
  }
  return [span(mark), span(cells, "F_PRW", magDim(secs, MAG_DUR_S))];
}

/** 🤖 🔧 🚦, each with a gauge of its share of the agent's ⌛; blank with
 * no transcript to read the split from. */
export function renderAgentSplit(elapsed: number | null,
  modelS: number | null, toolS: number | null = 0.0): Span[] {
  if (modelS === null || modelS === undefined || elapsed === null) return [];
  const m = Math.max(0.0, modelS), t = Math.max(0.0, toolS || 0.0);
  const parts = [m, t, Math.max(0.0, elapsed - m - t)];
  const dots = gaugeDots(parts);
  const out: Span[] = [];
  [E_WORK, E_TOOL, E_WAIT].forEach((mark, i) => {
    if (out.length) out.push(span(" "));
    out.push(...renderGauge(mark, parts[i], dots[i]));
  });
  return out;
}

/** Whether a task Claude Code calls completed is only waiting: on an ETA
 * still live, an agent under it, or a background task it started. */
export function parked(status: string, eta: unknown, waitingOn = false,
  background: unknown = []): boolean {
  return status === "completed" &&
    (pyTruthy(eta) || waitingOn || pyTruthy(background));
}

/** The ids with an agent running or not yet started anywhere under them. */
export function runningParents(prepared: readonly Prepared[]): Set<string> {
  const parent = new Map<string, string>();
  for (const [t, , m] of prepared) {
    if (hasId(t)) {
      parent.set(pyStr(t.id), strOr(pyGet(pyOr(m, {}), "parentAgentId")));
    }
  }
  const out = new Set<string>();
  for (const [t] of prepared) {
    if (hasId(t) && (t.status === "running" || t.status === "pending")) {
      let up = parent.get(pyStr(t.id)) ?? "";
      const seen = new Set<string>();
      while (up && !seen.has(up)) {
        seen.add(up);
        out.add(up);
        up = parent.get(up) ?? "";
      }
    }
  }
  return out;
}

/** ⛳ and how long the agent says it has left; see etaReading.  Late, an
 * amber "+", or a red one when `signedOff`; "?" with no live estimate;
 * nothing with no transcript. */
export function renderAgentEta(st: Settings, eta: Eta, startMs: unknown,
  now: number | null, status = "running", end: number | null = null,
  signedOff = false): Span[] {
  const got = etaReading(eta, startMs, now, status, end);
  if (got === null) return [];
  if (!got.length) {
    return [span(E_ETA), span(padVal(st, A_ETA_FIG_W, "?"), "F_ETA", true)];
  }
  const left = got[1];
  if (left < 0) {
    return [span(E_ETA), span(padVal(st, A_ETA_FIG_W,
      "+" + durFmt(st, -left)), signedOff ? "F_OVER" : "F_AMB")];
  }
  return [span(E_ETA), span(padVal(st, A_ETA_FIG_W, durFmt(st, left)),
    "F_ETA", magDim(left, MAG_DUR_S))];
}

export function renderAgentRate(st: Settings, rate: number | null,
  mark: string = E_RATE): Span[] {
  return rate === null ? [] : [span(mark + " "),
    span(padVal(st, 3, rateFig(st, rate)) + "/s", "F_RATE",
      magDim(rate, MAG_RATE))];
}

/** The epoch the agent entered the state `mode` names, or null; see the
 * Python's state_since for each. */
export function stateSince(status: string, usage: unknown, phase: string,
  mode: string, task: unknown = null): number | null {
  const pending = uaList(usage, "pending");
  if (status === "running") {
    let starts: unknown[];
    if (mode === E_WAIT) {
      starts = pending.filter((p) => WAITING_TOOLS.has(p[1])).map((p) => p[0]);
    } else if (mode === E_TOOL) {
      starts = pending.filter((p) => !WAITING_TOOLS.has(p[1]))
        .map((p) => p[0]);
    } else if (mode === E_WORK) {
      starts = [ua(usage, "last_seen")];
    } else {
      starts = [];
    }
    const got = starts.filter((t): t is number => t !== null &&
      t !== undefined);
    return got.length ? pyMin(got) : null;
  }
  if (status === "pending") return msToS(pyGet(pyOr(task, {}), "startTime"));
  if (phase === E_PHASE_PAUSE || phase === E_PHASE_END) {
    return pyOr(ua(usage, "last_seen"), ua(usage, "last_epoch")) as
      number | null;
  }
  return null;
}

/** What the agent is doing, and for how long: the mode mark, then the
 * time since stateSince, or 🤖's rate while its records keep landing. */
export function renderDoing(st: Settings, status: string, usage: unknown,
  waitingOn = false, rate: number | null = null, now: number | null = null,
  task: unknown = null): Span[] {
  const [phase, mode] = agentState(status, usage, waitingOn);
  if (!mode) return renderAgentRate(st, rate);
  const t = now === null ? Date.now() / 1000 : now;
  const since = stateSince(status, usage, phase, mode, task);
  const secs = since === null ? null : Math.max(0.0, t - since);
  const figW = A_RATE_W - visWidth(mode, st.widths) - 2;
  if (mode === E_WORK && status === "running" && rate !== null &&
    (secs === null || secs < A_SILENT_S)) {
    return renderAgentRate(st, rate, mode);
  }
  if (secs === null) return [span(mode)];
  const style = mode === E_WORK && secs >= A_SILENT_WARN_S ? ink("F_AMB")
    : ink("F_PRW", magDim(secs, MAG_DUR_S));
  return [span(mode + " "),
    paint(style, padVal(st, figW, durFmt(st, secs)) + " ")];
}

/** The name, 🌿 and a worktree's branch, then the activity, in that order
 * of claim on `room`: the name cut to fit, the branch whole or not at all,
 * the activity only with A_ACT_MIN. */
export function renderWho(st: Settings, name: string, act: string,
  room: number, branch = ""): Span[] {
  const tag = branch ? E_GIT_OK + fitCols(st, branch, A_BRANCH_W) : "";
  const out: Span[] = [];
  let left = room;
  const parts: [string, string, number | null][] = [
    ["F_BLU", name, 0], ["F_GRN", tag, null], ["F_CHAT_B", act, A_ACT_MIN]];
  for (const [col, text0, least] of parts) {
    let text = text0;
    if (!text) continue;
    const have = left - (out.length ? A_HEAD_GAP : 0);
    if (!out.length) text = fitCols(st, text, have);
    else if (least === null) {
      if (have < visWidth(text, st.widths)) continue;
    } else if (have < least) continue;
    else text = fitCols(st, text, have);
    if (out.length) out.push(span(" ".repeat(A_HEAD_GAP)));
    out.push(span(text, col));
    left = have - visWidth(text, st.widths);
  }
  return out;
}

// ════════════════════════════════════════════════════════════════════════════
// The tree.
// ════════════════════════════════════════════════════════════════════════════

/** The columns the panel spends before a NESTED row, which `cols` is not
 * net of: A_TREE_W a level below the top. */
export function treeCols(task: unknown, meta: unknown,
  depth: number | null = null): number {
  return A_TREE_W * ((depth === null ? spawnDepth(task, meta) : depth) - 1);
}

/** 1 for a task the session started, 2 for one an agent started, and so
 * on: max(1, int(...)), 1 where int() raises. */
export function spawnDepth(task: unknown, meta: unknown): number {
  const v = pyOr(pyOr(pyGet(meta, "spawnDepth"), pyGet(task, "spawnDepth")),
    1);
  let n: number | null;
  if (typeof v === "boolean") n = v ? 1 : 0;
  else if (typeof v === "number") n = Number.isFinite(v) ? Math.trunc(v) : 1;
  else if (typeof v === "string") n = pyIntText(v);
  else n = null;
  return n === null ? 1 : Math.max(1, n);
}

/** Each task id's parent and depth as the panel draws them; see the
 * Python's tree_shape for the walk. */
export function treeShape(prepared: readonly Prepared[]):
  Map<string, [string, number]> {
  const rows = new Map<string, [Dict, unknown, unknown]>();
  for (const [t, u, m] of prepared) {
    if (hasId(t)) rows.set(pyStr(t.id), [t, u, pyOr(m, {})]);
  }
  const busy = runningParents(prepared);
  const raw = new Map<string, string>();
  for (const [tid, [, , m]] of rows) {
    raw.set(tid, strOr(pyGet(m, "parentAgentId")));
  }
  const done = (tid: string): boolean => {
    const [t, u] = rows.get(tid)!;
    const status = strOr(t.status);
    return status === "completed" && !parked(status, ua(u, "eta"),
      busy.has(tid), ua(u, "background", []));
  };
  const up = (tid: string): string => {
    let p = raw.get(tid)!;
    const seen = new Set([tid]);
    while (rows.has(p) && !seen.has(p)) {
      if (!done(p)) return p;
      seen.add(p);
      p = raw.get(p)!;
    }
    return "";
  };
  const parent = new Map<string, string>();
  for (const tid of rows.keys()) parent.set(tid, up(tid));
  const out = new Map<string, [string, number]>();
  for (const tid of rows.keys()) {
    let depth = 1, p = parent.get(tid)!;
    const seen = new Set([tid]);
    while (p && !seen.has(p)) {
      seen.add(p);
      depth += 1;
      p = parent.get(p)!;
    }
    out.set(tid, [parent.get(tid)!, depth]);
  }
  return out;
}

/** The panel's tree, drawn again for each task id; see the Python's
 * tree_marks for the order and the filled ⏺. */
export function treeMarks(prepared: readonly Prepared[],
  shape: Map<string, [string, number]> | null = null): Map<string, string> {
  const sh = shape ?? treeShape(prepared);
  const tasks = prepared.map((p) => p[0]).filter(hasId);
  const started = (t: Dict): number => {
    const v = pyOr(t.startTime, 0);
    return pyFloat(v) ?? 0.0;
  };
  const order = tasks.map((t, i) => [started(t), i, pyStr(t.id)] as const)
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((x) => x[2]);
  const parent = new Map<string, string>();
  for (const tid of order) parent.set(tid, sh.get(tid)![0]);
  const open = new Set(parent.values());
  const last = new Map<string, boolean>();
  order.forEach((tid, i) => {
    last.set(tid, !order.slice(i + 1).some((q) =>
      parent.get(q) === parent.get(tid)));
  });
  const out = new Map<string, string>();
  for (const tid of order) {
    const [p, depth] = sh.get(tid)!;
    const marks = depth > 1 ? [last.get(tid) ? E_TREE_END : E_TREE_MID] : [];
    let up = p;
    for (let k = 0; k < depth - 2; k++) {
      marks.push(last.get(up) ?? true ? " " : E_TREE_BAR);
      up = parent.get(up) ?? "";
    }
    out.set(tid, [...marks.reverse(),
      open.has(tid) ? E_TREE_OPEN : E_TREE_NODE].join(" "));
  }
  return out;
}

/** Each task's ETA, pushed out to the latest finish below it on the panel;
 * see the Python's inherited_etas for which descendants count. */
export function inheritedEtas(prepared: readonly Prepared[]):
  Map<string, Eta> {
  const rows = new Map<string, [Dict, unknown, unknown]>();
  for (const [t, u, m] of prepared) {
    if (hasId(t)) rows.set(pyStr(t.id), [t, u, pyOr(m, {})]);
  }
  const kids = new Map<string, string[]>();
  for (const [tid, [, , m]] of rows) {
    const p = strOr(pyGet(m, "parentAgentId"));
    if (rows.has(p)) {
      if (!kids.has(p)) kids.set(p, []);
      kids.get(p)!.push(tid);
    }
  }
  const memo = new Map<string, number | null>();
  const finish = (tid: string,
    seen: readonly string[] = []): number | null => {
    if (memo.has(tid)) return memo.get(tid)!;
    const [t, u] = rows.get(tid)!;
    const st = strOr(t.status);
    const own = st !== "killed" && st !== "failed"
      ? etaFinish((pyOr(ua(u, "eta"), []) as readonly number[])) : null;
    const ends = [own, ...(kids.get(tid) ?? [])
      .filter((k) => !seen.includes(k))
      .map((k) => finish(k, [...seen, tid]))]
      .filter((e): e is number => e !== null);
    const got = ends.length ? pyMax(ends) : null;
    memo.set(tid, got);
    return got;
  };
  const out = new Map<string, Eta>();
  for (const [tid, [t, u]] of rows) {
    const start = msToS(t.startTime);
    out.set(tid, inheritEta(ua(u, "eta") as Eta,
      (kids.get(tid) ?? []).map((k) => finish(k)), start));
  }
  return out;
}

// ════════════════════════════════════════════════════════════════════════════
// The row and the panel.
// ════════════════════════════════════════════════════════════════════════════

/** The widest 📨, 🤏, 💻 and 📡 cells on the panel, each 0 where no row
 * draws one, so a cell any row needs keeps its column on every row. */
export type PanelWidths = {
  readonly inbox: number;
  readonly compact: number;
  readonly shells: number;
  readonly monitors: number;
};

/** Render one fully prepared task; it performs no reads or accounting.
 * The arguments after `now` are the panel's, from renderTaskRows; see the
 * Python's render_agent_row for each.  `eta` false is the row's own. */
export function renderAgentRow(st: Settings, task0: unknown, usage: unknown,
  meta0: unknown, shares0: unknown, limits: Limits,
  cols0: number | null = null, now: number | null = null, tree = "",
  treeW = 0, eta: Eta | false = false, waitingOn = false,
  depth: number | null = null, kids = 0, kidsW = 0, lead = 0,
  widths0: PanelWidths | null = null): Span[] {
  const task = pyOr(task0, {}) as Dict, meta = pyOr(meta0, {});
  const shares = pyOr(shares0, {});
  const widths: Partial<PanelWidths> = widths0 ?? {};
  let cols = cols0;
  if (cols) cols = Math.max(0, cols - treeCols(task, meta, depth) - lead);
  const tid = strOr(task.id), status = strOr(task.status);
  const kind = strOr(task.type);
  const model = pyOr(pyOr(strOr(task.model), ua(usage, "model", "")),
    strOr(pyGet(meta, "model"))) as string;
  const week = pyGet(shares, "week");
  const light = week !== null && (week as number) < MAG_SHARE_AGENT;
  const gap = " ".repeat(A_GAP);
  const billed = pyTruthy(ua(usage, "parts", []));
  const ownEta = ua(usage, "eta") as Eta;
  const live = status === "running" ||
    parked(status, ownEta, waitingOn, ua(usage, "background", []));
  // A finished row stops at its last billed stamp, else at its last
  // working span; with neither, ⌛ is blank.
  const work = uaList(usage, "work");
  const end = live ? null : (pyOr(ua(usage, "last_epoch"),
    work.length ? pyMax(work.map((w) => w[1])) : null) as number | null);
  const clocked = live || end !== null;
  // Where its transcript starts: its first working span, or the one still
  // open when it has closed none.
  const firsts: number[] = work.slice(0, 1).map((w) => w[0]);
  const openAt = ua(usage, "open_at");
  if (openAt !== null) firsts.push(openAt as number);
  const first = firsts.length ? pyMin(firsts) : null;
  const shownEta = eta === false ? ownEta : eta;
  // Signed off: its own last report is zero and no descendant pushed the
  // finish past it.
  const signedOff = pyTruthy(ownEta) && ownEta![1] === 0 &&
    pyTruthy(shownEta) &&
    etaFinish(shownEta!)! <= etaFinish(ownEta!)! + 1e-6;
  const lastEpoch = ua(usage, "last_epoch") as number | null;
  const elapsed = clocked ? agentElapsed(task.startTime, now, end, first)
    : null;
  const cells: [number, SpanLike][] = [
    // The model and effort, right before the 💰 they priced.
    [6, renderAgentModel(st, model,
      pyOr(strOr(task.effort), ua(usage, "effort", "")) as string)],
    [visWidth(st.sCost, st.widths) + 4, billed
      ? renderCost(st, pyFormatF(ua(usage, "cost", 0) as number, 4)) : []],
    [aCtxW(st), renderAgentCtx(st, ua(usage, "ctx_tokens", 0) as number,
      ua(usage, "ctx_window", 0) as number)],
    [visWidth(st.sTok, st.widths) + VAL_W + VAL2_W,
      renderTokens(st, ua(usage, "tok_up"), ua(usage, "tok_down", 0))],
    [5, renderAgentCache(st, ua(usage, "cache_pct", -1))],
    // ⌛ ⛳ 🤖 🔧 🚦, one space apart as one segment, right before the 5h
    // and 1w it spent.
    [A_CLOCK_W + aEtaW(st) + A_SPLIT_W + 2, spans([
      seg(st, A_CLOCK_W, clocked
        ? renderAgentElapsed(st, task.startTime, now, end, first) : []), " ",
      seg(st, aEtaW(st), renderAgentEta(st, shownEta, task.startTime, now,
        status, lastEpoch, signedOff)), " ",
      renderAgentSplit(elapsed, ua(usage, "model_s") as number | null,
        ua(usage, "tool_s", 0.0) as number | null)])],
    [A_LIMIT_W, renderAgentLimit(st, E_SESS, limits.session_pct,
      pyGet(shares, "sess") as number | null, "F_LIM_SESS", billed, light)],
    [A_LIMIT_WEEK_W, renderAgentLimit(st, E_WEEK, limits.weekly_pct,
      week as number | null, "F_LIM_WEEK", billed, light, 4)],
    [aDiffW(st), billed ? renderAgentDiff(st, usage) : []],
  ];
  let right = gapped(gap, cells.filter(([w]) => w)
    .map(([w, c]) => seg(st, w, c)));
  const desc = squash(strOr(task.description));
  const name = strOr(task.name) || desc;
  let act = squash(strOr(task.label));
  if (act === desc) act = "";
  // The cells a panel draws only while some row needs one sit together,
  // right after the kind and state; see the Python for their order.
  const headCells: [number, SpanLike][] = [
    [A_SPIN_W + A_KIND_W + A_STATE_W + 1 + A_RATE_W, spans([
      seg(st, A_SPIN_W, renderSpin(status, usage)),
      renderKind(strOr(pyGet(meta, "agentType")), kind),
      seg(st, A_STATE_W, renderPhase(status, usage, waitingOn)), " ",
      seg(st, A_RATE_W, renderDoing(st, status, usage, waitingOn,
        tokenRate(task.tokenSamples, status), now, task))])],
    [kidsW, renderKids(kids)],
    [widths.compact ?? 0,
      renderCompactions(ua(usage, "compactions", 0) as number)],
    [widths.shells ?? 0, renderBackground(E_MODE_SHELL,
      backgroundCount(status, usage, "bash"))],
    [widths.monitors ?? 0, renderBackground(E_MODE_MONITOR,
      backgroundCount(status, usage, "monitor"))],
    [widths.inbox ?? 0, renderInbox(ua(usage, "inbox", 0) as number)],
    [A_ID_W, [span(fitCols(st, tid, A_ID_W), "F_BLU2", true)]],
  ];
  const head = gapped(" ".repeat(A_HEAD_GAP), headCells.filter(([w]) => w)
    .map(([w, c]) => seg(st, w, c)));
  let room = !cols ? A_NAME_MIN : Math.max(A_NAME_MIN,
    cols - width(head, st.widths) - A_HEAD_GAP - width(right, st.widths) -
    A_GAP);
  const branch = strOr(ua(usage, "branch", ""));
  // Decided on the room a row would have with neither the panel's indent
  // nor the lead, which add up to the same on every row.
  if (tree && room + treeCols(task, meta, depth) + lead - treeW -
    A_HEAD_GAP >= A_TREE_ROOM) {
    room -= treeW + A_HEAD_GAP;
    right = [...seg(st, treeW, [span(tree, null, true)]),
      span(" ".repeat(A_HEAD_GAP)), ...right];
  }
  return rstrip([" ".repeat(lead), head, " ".repeat(A_HEAD_GAP),
    seg(st, room, renderWho(st, name, act, room, branch)), gap, right]);
}

/** `cells`' spans in one list, `gap` between each two: str.join for
 * spans. */
function gapped(gap: string, cells: readonly SpanLike[]): Span[] {
  const out: Span[] = [];
  cells.forEach((c, i) => {
    if (i) out.push(span(gap));
    out.push(...spans(c));
  });
  return out;
}

/** The widest 📨, 🤏, 💻 and 📡 cell on the panel; see PanelWidths. */
export function panelWidths(st: Settings,
  prepared: readonly Prepared[]): PanelWidths {
  const live = prepared.filter(([t]) => hasId(t))
    .map(([t, u]) => [strOr((t as Dict).status), u] as const);
  const widest = (mark: string, ns: readonly unknown[]): number =>
    maxOr0(ns.filter((n) => pyTruthy(n))
      .map((n) => visWidth(mark, st.widths) + pyLen(pyStr(n))));
  return {
    inbox: widest(E_INBOX, live.map(([, u]) => ua(u, "inbox", 0))),
    compact: widest(E_ROW_COMPACT,
      live.map(([, u]) => ua(u, "compactions", 0))),
    shells: widest(E_MODE_SHELL,
      live.map(([s, u]) => backgroundCount(s, u, "bash"))),
    monitors: widest(E_MODE_MONITOR,
      live.map(([s, u]) => backgroundCount(s, u, "monitor"))),
  };
}

/** The (task id, joined row) pairs for prepared (task, usage, meta,
 * shares) facts, in the payload's order. */
export function renderTaskRowSpans(st: Settings,
  prepared: readonly Prepared[], limits: Limits, cols: number | null = null,
  now: number | null = null): [string, Span[]][] {
  const rows: [string, Span[]][] = [];
  const shape = treeShape(prepared);
  const trees = treeMarks(prepared, shape);
  const etas = inheritedEtas(prepared);
  const busy = runningParents(prepared);
  const treeW = maxOr0([...trees.values()]
    .map((t) => visWidth(t, st.widths)));
  // 👶🏻 counts the rows hanging directly under each one, as treeShape
  // resolves them, finished or not.
  const kids = new Map<string, number>();
  for (const [p] of shape.values()) {
    if (p) kids.set(p, (kids.get(p) ?? 0) + 1);
  }
  const kidsW = maxOr0([...kids.values()]
    .map((n) => visWidth(E_KIDS, st.widths) + pyLen(String(n))));
  // Each row opens with the blank the deepest row spends on its tree, less
  // its own, so every row's cells start on one column.
  const deep = shape.size ? pyMax([...shape.values()].map(([, dp]) => dp))
    : 1;
  const widths = panelWidths(st, prepared);
  for (const [task, usage, meta, shares] of prepared) {
    if (hasId(task)) {
      const tid = pyStr(task.id);
      const dp = shape.get(tid)![1];
      rows.push([tid, renderAgentRow(st, task, usage, meta, shares, limits,
        cols, now, trees.get(tid) ?? "", treeW,
        etas.has(tid) ? etas.get(tid)! : false, busy.has(tid), dp,
        kids.get(tid) ?? 0, kidsW, A_TREE_W * (deep - dp), widths)]);
    }
  }
  return rows;
}

/** render_task_rows: `(task id, row)` pairs, each row joined into escape
 * codes where the panel prints it. */
export function renderTaskRows(st: Settings, prepared: readonly Prepared[],
  limits: Limits, cols: number | null = null,
  now: number | null = null): [string, string][] {
  return renderTaskRowSpans(st, prepared, limits, cols, now)
    .map(([tid, row]) => [tid, join(row)]);
}
