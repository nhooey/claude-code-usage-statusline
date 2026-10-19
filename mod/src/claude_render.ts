// Pure Claude status-line renderers.
//
// A port of coding_agent_usage_line/claude_render.py, function for
// function and in the same order.  The Python's docstrings carry each
// cell's history and the argument for its shape, and are not copied: the
// comments here say what the port has to do to draw the same bytes.
//
// All data arrives as arguments.  Where the Python reads module state, the
// settings come first as `st` (formatting.ts's Settings: the profile's
// widths, the mark spacing and the subscript switch); where it falls back
// to the clock, `now` is required; and where it reads HOME to shorten the
// working directory, render_status takes `home`.  Each cell returns spans,
// [] for nothing to draw, and only drawnLine joins them into escapes.
import {
  E_ACCT, E_COST, E_DIR, E_DIRTY, E_DOWN, E_EFF_HIGH, E_EFF_LOW, E_EFF_MAX,
  E_EFF_MED, E_EFF_XHIGH, E_ETA, E_GIT_BAD, E_GIT_OK, E_HUNDRED, E_INBOX,
  E_MODE_MONITOR, E_MODE_SHELL, E_PCT, E_PROJ, E_ROW_COMPACT, E_SESSION,
  E_SUP_DIGITS, E_TOOL, E_TURN, E_UP, E_WAIT, E_WORK, LEFT_GAP, LIM_ACCT_W,
  LIM_FIG_W, LMIN_BRANCH, LMIN_PATH, LMIN_PROJ, LWT_BRANCH, LWT_PATH,
  LWT_PROJ, MAG_COST, MAG_DIFF, MAG_DUR_S, MAG_RATE, MAG_TOK, MAX_ROW,
  MIN_GAP, MODEL_FAMILIES, QUIET_S, QUIET_WARN_S, RIGHT_MARGIN, RST_W,
  SHARE_FIG_W, VAL_W, VAL2_W, W_STY,
} from "./spec.ts";
import {
  EOL_CLEAR, LINE_CLEAR, S_BOT, S_DATE, S_DIFF, S_HUMAN, S_IDLE, S_PR,
  S_READ, S_RESET, S_SESS, S_STY, S_TIME, S_WEEK, S_WRITE, cacheColor,
  cacheDims, durFmt, fitCols, fitHead, fitPath, gridRow, humanize, limitPct,
  magDim, moneyFig, padVal, pct, pct2, rateFig, resetDim, rulesOn, seg,
  shareDims, shortDur, visWidth,
} from "./formatting.ts";
import type { Settings } from "./formatting.ts";
import {
  ink, join, paint, rstrip, span, spans, truthy, width,
} from "./spans.ts";
import type { Span, SpanLike } from "./spans.ts";
import { NO_CACHE_SHARES, etaFinish } from "./claude_records.ts";
import type {
  AgentEta, CacheShares, Git, Limits, Payload, Transcript,
} from "./claude_records.ts";
import {
  pyAsciiDigits, pyIntStr, pyLen, pyRstrip, pySlice,
} from "./py.ts";
import { pyFloat } from "./sources.ts";

/** The project name: the main repository root's basename inside a repo,
 * and "[none]" outside one. */
export function projectName(git: Git, projectDir: string): string {
  if (!git.in_git) return "[none]";
  const base = (p: string): string => {
    const t = pyRstrip(p, "/");
    return t.slice(t.lastIndexOf("/") + 1);
  };
  const n = base(git.main_root || git.toplevel) || base(projectDir);
  return n || "?";
}

// ════════════════════════════════════════════════════════════════════════════
// Status-line segment renderers.
//
// One per metric, each padded to its own width and placed by the layout
// below.  float(s), where the Python parses a payload string, is pyFloat:
// null where Python raises.
// ════════════════════════════════════════════════════════════════════════════

/** The ▴/▾ billable-equivalent token totals, each half dimmed on its own
 * figure.  `downW` is the ▾ field's width. */
export function renderTokens(st: Settings, up: number | null, down: number,
  downW: number = VAL2_W): Span[] {
  if (up === null) return [];
  return [span(st.sTok),
    span(padVal(st, VAL_W, E_UP + padVal(st, 4, humanize(st, up)), true),
      "F_TUP", magDim(up, MAG_TOK)),
    span(padVal(st, downW, E_DOWN + padVal(st, 4, humanize(st, down))),
      "F_TDN", magDim(down, MAG_TOK))];
}

/** What the main thread is doing, as the Doing mark and the epoch it
 * started; ["", 0] on an offline read. */
export function mainDoing(tr: Transcript): [string, number] {
  if (tr.tool_at) return [E_TOOL, tr.tool_at];
  if (tr.wait_at) return [E_WAIT, tr.wait_at];
  if (tr.idle_at) return [E_WAIT, tr.idle_at];
  if (tr.last_seen) return [E_WORK, tr.last_seen];
  return ["", 0.0];
}

/** The Doing figure and 🎯 the cache hit rate in one cell. */
export function renderRateCache(st: Settings, rate: number | null,
  cachePct: number | null, mark = "", secs: number | null = null): Span[] {
  if (cachePct === null || cachePct < 0) return [];
  const showRate = !mark || (mark === E_WORK && rate !== null &&
    (secs === null || secs < QUIET_S));
  let head: Span[];
  if (!showRate && secs !== null) {
    const style = mark === E_WORK && secs >= QUIET_WARN_S ? ink("F_AMB")
      : ink("F_PRW", magDim(secs, MAG_DUR_S));
    head = [span(mark + st.doingPad),
      paint(style, padVal(st, VAL_W - 1, durFmt(st, secs)) + " ")];
  } else {
    const fig = rate === null ? "" : rateFig(st, rate) + "/s";
    head = [span(mark ? mark + st.doingPad : st.sRate),
      span(padVal(st, VAL_W, fig), "F_RATE", magDim(rate, MAG_RATE))];
  }
  return [...head, ...padVal(st, st.col2Val2W, [
    span(st.sCache),
    paint(cacheColor(cachePct),
      padVal(st, 3, pct2(cachePct) + E_PCT))])];
}

/** Live context occupancy, as a size and then a percentage, both fields'
 * edges read off column 3's share rows. */
export function renderCtx(st: Settings, ctxPct: number | null,
  ctxTokens: number, est = false): Span[] {
  if (ctxPct === null) return [];
  const turnEnd = visWidth(S_READ, st.widths) + visWidth(E_TURN, st.widths) +
    st.markSp.length + SHARE_FIG_W;
  const sizeW = turnEnd - visWidth(st.sCtx, st.widths);
  const pctW = st.rightGrid[2] - turnEnd;
  const style = ink("F_PNK", magDim(ctxTokens, MAG_TOK));
  const tilde = est ? "~" : "";
  return [span(st.sCtx),
    paint(style, padVal(st, sizeW, tilde + humanize(st, ctxTokens))),
    paint(style, padVal(st, pctW, tilde + pyIntStr(ctxPct) + E_PCT))];
}

/** The session cost, "💰115 ".  `mark` defaults to S_COST, which is the
 * settings' and so cannot be a default here: null stands for it. */
export function renderCost(st: Settings, costUsd: string,
  mark: string | null = null): Span[] {
  if (!costUsd || costUsd === "null") return [];
  const c = pyFloat(costUsd);
  // json reads NaN and 1e400 as floats; the Python drops both.
  if (c === null || !Number.isFinite(c)) return [];
  return [span(mark ?? st.sCost),
    span(padVal(st, 4, moneyFig(st, c)), "F_YEL", magDim(c, MAG_COST))];
}

/** The model and the cost side by side in one cell, "🤖 O⁵🚶  💰5.1k". */
export function renderModelCost(st: Settings, model: string, effort: string,
  costUsd: string): Span[] {
  const mod = renderModel(st, model, effort);
  const cost = renderCost(st, costUsd, E_COST);
  if (!mod.length && !cost.length) return [];
  return [...seg(st, visWidth(st.sMod, st.widths) + VAL_W, mod),
    ...(cost.length ? padVal(st, st.col2Val2W, cost) : [])];
}

/** One plan-limit segment: 🎤 🎮 💳, then the countdown.  One colour per
 * row; the caller says which of the session's two scopes dim. */
export function renderLimit(st: Settings, emoji: string, pctS: string,
  delta: string, resets: string, turn = "", colour = "F_LIM_SESS",
  dimTotal = false, now: number, dimTurn = false,
  dimSession = false): Span[] {
  if (!pctS) return [];
  const pctV = pyFloat(pctS);
  if (pctV === null) return [];
  const d = shortDur(st, resets, now);
  let rst: Span[];
  if (d) {
    rst = [span(S_RESET + st.markSp),
      span(padVal(st, RST_W - visWidth(S_RESET, st.widths), d), colour,
        resetDim(d))];
  } else {
    rst = [span(" ".repeat(RST_W + st.markSp.length))];
  }

  const fig = (mark: string, v: number | null, col: Span,
    w: number = LIM_FIG_W, digits = 3): Span[] => {
    if (v === null) {
      return [span(mark + st.markSp),
        span(padVal(st, w, "?"), "F_CRM", true)];
    }
    // limit_pct's own threshold, so the glyph and the string agree.
    if (v >= 99.5) {
      return [span(mark + st.markSp),
        paint(col, padVal(st, w, E_HUNDRED + E_PCT))];
    }
    return [span(mark + st.markSp),
      paint(col, padVal(st, w, limitPct(st, v, digits) + E_PCT))];
  };

  const tcol = ink(colour, dimTotal);
  return spans([emoji,
    fig(E_TURN, turn ? pyFloat(turn) : null, ink(colour, dimTurn)), " ",
    fig(E_SESSION, delta ? pyFloat(delta) : null, ink(colour, dimSession)),
    " ",
    fig(E_ACCT, pctV, tcol, LIM_ACCT_W, 2), " ",
    rst]);
}

/** One column-3 row: where a bill went, at two scopes, "📖 🎤 61٪ 🎮 45٪". */
export function renderCacheShare(st: Settings, emoji: string,
  turn: number | null, sess: number | null, colour = "F_SHARE",
  dimTurn = false, dimSess = false): Span[] {
  if (turn === null && sess === null) return [];

  const fig = (mark: string, v: number | null, col: Span): Span[] => {
    if (v === null) {
      return [span(mark + st.markSp),
        span(padVal(st, SHARE_FIG_W, "?"), "F_CRM", true)];
    }
    if (v >= 99.5) {
      return [span(mark + st.markSp),
        paint(col, padVal(st, SHARE_FIG_W, E_HUNDRED + E_PCT))];
    }
    return [span(mark + st.markSp),
      paint(col, padVal(st, SHARE_FIG_W, pct(v)))];
  };

  return spans([emoji,
    fig(E_TURN, turn, ink(colour, dimTurn)), " ",
    fig(E_SESSION, sess, ink(colour, dimSess))]);
}

/** The +adds/-removes segment, each half dimmed on its own count. */
export function renderDiff(st: Settings, added: string,
  removed: string): Span[] {
  if (!added) return [];

  // int(float(v)): an infinity or a NaN raises, and is "?".
  const n = (v: string): number | null => {
    const f = pyFloat(v);
    return f === null || !Number.isFinite(f) ? null : Math.trunc(f);
  };

  const half = (sign: string, v: number | null, col: string): Span => {
    // The one cell that drops humanize's unit column.
    const fig = v === null ? "?" : pyRstrip(humanize(st, v));
    return span(sign + padVal(st, 4, fig), col, magDim(v, MAG_DIFF));
  };

  return [span(S_DIFF), half("+", n(added), "F_GRN"), span(" "),
    half("-", n(removed), "F_RED")];
}

export function renderPr(st: Settings, pr: string): Span[] {
  if (!pr || pr === "null") return [];
  return [span(S_PR), span(padVal(st, 4, pr), "F_CYN")];
}

// Up to two short runs of digits right after the family, and nothing that
// runs on into more digits, which is the date stamp.  Python's \d is any
// Unicode decimal digit.
const MODEL_VERSION =
  /^[-_. ]*(\p{Nd}{1,3})(?:[-_.](\p{Nd}{1,3}))?(?!\p{Nd})/u;

/** A display name from a model id or alias: family from the id, version
 * from the dotted digits after it, never the 8-digit date. */
export function modelLabel(modelId: string): string {
  const low = (modelId || "").toLowerCase();
  const fam = (MODEL_FAMILIES as readonly string[])
    .find((f) => low.includes(f.toLowerCase())) ?? "";
  if (!fam) return pySlice(modelId, null, VAL_W);
  const tail = low.slice(low.indexOf(fam.toLowerCase()) + fam.length);
  const m = MODEL_VERSION.exec(tail);
  if (!m) return fam;
  return fam + " " + [m[1], m[2]].filter((g) => g).join(".");
}

/** Two terminal cells: family initial and superscript major version. */
export function modelSpec(modelId: string): string {
  const label = modelLabel(modelId);
  if (!label) return "";
  const sp = label.indexOf(" ");
  const fam = sp < 0 ? label : label.slice(0, sp);
  const ver = sp < 0 ? "" : label.slice(sp + 1);
  if (ver) {
    const d = pySlice(ver, null, 1);
    return pySlice(fam, null, 1) + (/^\p{Nd}$/u.test(d)
      ? Array.from(E_SUP_DIGITS)[Number(pyAsciiDigits(d))] : d);
  }
  return pySlice(fam, null, 2);
}

/** 🤖, the two-character model spec and the effort's glyph, "🤖O⁵🏃". */
export function renderModel(st: Settings, model: string,
  effort = ""): Span[] {
  if (!model) return [];
  const cell = [span(st.sMod),
    span(padVal(st, 2, modelSpec(model)), "F_PUR")];
  if (effort && effort !== "null") cell.push(span(effortGlyph(effort)));
  return cell;
}

const EFFORT_GLYPHS: Readonly<Record<string, string>> = {
  low: E_EFF_LOW, medium: E_EFF_MED, high: E_EFF_HIGH, xhigh: E_EFF_XHIGH,
  max: E_EFF_MAX,
};

/** The level's glyph on the ladder; the middle of it for one not on it. */
export function effortGlyph(effort: string): string {
  return Object.hasOwn(EFFORT_GLYPHS, effort) ? EFFORT_GLYPHS[effort]
    : E_EFF_MED;
}

/** 📨 the queued messages, then 🤏 the compactions, "📨 2 🤏 1"; each half
 * keeps its columns when the other is zero. */
export function renderQueue(st: Settings, queued: number,
  compactions: number): Span[] {
  const half = (mark: string, n: number, col: string): Span[] => {
    if (!n) return [span(" ".repeat(visWidth(mark, st.widths) + 2))];
    return [span(mark), span(padVal(st, 2, pyIntStr(Math.min(n, 99))), col)];
  };
  if (!queued && !compactions) return [];
  return rstrip([half(E_INBOX, queued, "F_CYN"), " ",
    half(E_ROW_COMPACT, compactions, "F_PNK")]);
}

/** The output style, when it is not the default one. */
export function renderStyle(style: string): Span[] {
  if (!style || style === "default" || style === "null") return [];
  return [span(S_STY), span(pySlice(style, null, W_STY - 2), "F_CYN")];
}

/** time.localtime(now)'s fields in the process's zone.  Python floors a
 * fractional epoch to the second before it reads the calendar. */
function localTime(now: number): Date {
  return new Date(Math.floor(now) * 1000);
}

const two = (n: number): string => String(n).padStart(2, "0");

/** The wall clock, right-aligned on column 5's edge. */
export function renderTime(st: Settings, now: number): Span[] {
  const t = localTime(now);
  const hms = `${two(t.getHours())}:${two(t.getMinutes())}:` +
    two(t.getSeconds());
  return [span(S_TIME), span(padVal(st, 11, hms), "F_CRM")];
}

/** Today, above the clock it belongs to. */
export function renderDate(st: Settings, now: number): Span[] {
  const t = localTime(now);
  const ymd = `${String(t.getFullYear()).padStart(4, "0")}-` +
    `${two(t.getMonth() + 1)}-${two(t.getDate())}`;
  return [span(S_DATE), span(padVal(st, 11, ymd), "F_CRM")];
}

/** eta_reading's three answers: null where there is no transcript to
 * report in, [] for no live estimate (drawn "?"), and otherwise the share
 * done and the seconds left. */
export type EtaReading = null | readonly [] | readonly [number, number];

/** (share done, seconds left) off the latest ETA and the elapsed time;
 * `eta` is (epoch, seconds left), or null for no transcript. */
export function etaReading(eta: readonly number[] | null,
  startMs: number | null, now: number, status = "running",
  end: number | null = null): EtaReading {
  if (eta === null) return null;
  if (!eta.length) return [];
  let t = now;
  if (end !== null && (status === "killed" || status === "failed")) {
    t = Math.min(t, end);
  }
  let t0 = startMs === null ? null : startMs / 1000.0;
  const [at, said] = eta;
  // A report older than the start is a resumed agent: read from the
  // report instead.
  if (t0 !== null) t0 = Math.min(t0, at);
  const total = said + (t0 !== null ? at - t0 : 0.0);
  const gone = t - (t0 !== null ? t0 : at);
  const share = total > 0 ? gone / total : 1.0;
  return [Math.min(1.0, Math.max(0.0, share)), total - gone];
}

// An agent whose file has been silent this long no longer holds the status
// line's ⛳ open; see the Python.
export const ETA_LIVE_S = 1800.0;

/** `own` ETA, pushed out to the latest of the descendants' `finishes`. */
export function inheritEta(own: readonly number[],
  finishes: readonly (number | null)[],
  startS: number | null): readonly number[] {
  const ends = finishes.filter((f): f is number => f !== null);
  const mine = own.length ? etaFinish(own) : null;
  if (mine !== null) ends.push(mine);
  if (!ends.length || (mine !== null && ends.length === 1)) return own;
  const at = startS ? startS : (own.length ? own[0] : Math.max(...ends));
  return [at, Math.max(...ends) - at];
}

/** ⛳ and the time left in a field of `w`: "?" with no live estimate, an
 * amber "+" past it (bright red when `signedOff`), nothing with no
 * transcript. */
export function etaFig(st: Settings, reading: EtaReading, w: number,
  digits = 3, signedOff = false): Span[] {
  if (reading === null) return [];
  if (!reading.length) {
    return [span(E_ETA + st.markSp), span(padVal(st, w, "?"), "F_ETA", true)];
  }
  const left = reading[1];
  if (left < 0) {
    // The "+" takes a column, so an overrun gets no decimal.
    return [span(E_ETA + st.markSp),
      span(padVal(st, w, "+" + durFmt(st, -left, Math.min(digits, w - 2))),
        signedOff ? "F_OVER" : "F_AMB")];
  }
  return [span(E_ETA + st.markSp),
    span(padVal(st, w, durFmt(st, left, digits)), "F_ETA",
      magDim(left, MAG_DUR_S))];
}

/** The session's clock: ⛳ the turn's ETA, then 🤖 🔧 🚦, which partition
 * the session's age. */
export function renderElapsed(st: Settings, busyS: number, startS: number,
  toolS = 0.0, now: number, blockedS = 0.0, eta: readonly number[] = [],
  turnS = 0.0, agentEtas: readonly AgentEta[] = []): Span[] {
  if (!startS) return [];
  const t = now;
  const age = t > startS ? t - startS : 0.0;
  // A blocking prompt moves from the busy clock to the idle one, clamped
  // so the three fields never sum past the age.
  const wait = Math.min(Math.max(0.0, blockedS), busyS);
  let idle = age > busyS ? age - busyS + wait : wait;
  idle = Math.min(idle, age);
  let modelS = busyS - wait - toolS;
  modelS = modelS > 0.0 ? modelS : 0.0;

  const fig = (mark: string, v: number, w: number = LIM_FIG_W,
    digits = 2): Span[] =>
    [span(mark + st.markSp),
      span(padVal(st, w, durFmt(st, v, digits)), "F_PRW",
        magDim(v, MAG_DUR_S))];

  const shown = inheritEta(eta, agentEtas
    .filter(([, last]) => last !== null && t - last <= ETA_LIVE_S)
    .map(([f]) => f), turnS);
  const reading = etaReading(shown, turnS ? turnS * 1000.0 : null, t);
  // Signed off: the main thread's own report is zero and no live agent
  // pushed the finish past it.
  const signedOff = eta.length > 0 && eta[1] === 0 && shown.length > 0 &&
    etaFinish(shown)! <= etaFinish(eta)! + 1e-6;
  return spans([S_IDLE, etaFig(st, reading, LIM_FIG_W, 3, signedOff),
    " ", fig(E_WORK, modelS, LIM_FIG_W, 3),
    " ", fig(E_TOOL, toolS, LIM_ACCT_W, 3),
    " ", fig(E_WAIT, idle, RST_W - visWidth(E_WAIT, st.widths), 3)]);
}

// ════════════════════════════════════════════════════════════════════════════
// Status-line layout.
// ════════════════════════════════════════════════════════════════════════════

/** Split `budget` columns between branch, project and path by weighted
 * max-min fair sharing, then hold each to its minimum.  `//` floors, as
 * Math.floor does and Math.trunc does not. */
export function allocateLeft(budget: number, natBranch: number,
  natProj: number, natPath: number): [number, number, number] {
  const nat = [natBranch, natProj, natPath];
  const wt = [LWT_BRANCH, LWT_PROJ, LWT_PATH];
  const mn = [LMIN_BRANCH, LMIN_PROJ, LMIN_PATH];
  const got = [0, 0, 0];
  let pool = budget;
  let still = [0, 1, 2];
  const sumOf = (ix: number[]): number => ix.reduce((a, i) => a + wt[i], 0);

  for (let round = 0; round < 3; round++) {
    let sumw = sumOf(still);
    if (sumw <= 0) break;
    let settled = false;
    const nxt: number[] = [];
    for (const i of still) {
      const share = Math.floor(pool * wt[i] / sumw);
      if (nat[i] <= share) {
        got[i] = nat[i];
        pool -= nat[i];
        settled = true;
      } else {
        nxt.push(i);
      }
    }
    still = nxt;
    if (!still.length) break;
    if (!settled) {
      // Everyone left wants more than its share: split what remains by
      // weight, the remainder to the highest-priority claimant.
      sumw = sumOf(still);
      let spent = 0;
      for (const i of still) {
        got[i] = Math.floor(pool * wt[i] / sumw);
        spent += got[i];
      }
      got[still[0]] += pool - spent;
      break;
    }
  }

  for (const i of [0, 1, 2]) {
    const need = Math.min(mn[i], nat[i]);
    while (got[i] < need) {
      let donor = -1;
      for (const j of [2, 1, 0]) {
        if (j !== i && got[j] > mn[j]) {
          donor = j;
          break;
        }
      }
      if (donor < 0) break;
      got[i] += 1;
      got[donor] -= 1;
    }
  }
  return [got[0], got[1], got[2]];
}

/** 💻 the background shells and 📡 the Monitors the main thread has
 * running, each only while it has one. */
export function renderThreadBackground(st: Settings, shells: number,
  monitors: number): Span[] {
  const out: SpanLike[] = [];
  for (const [mark, n] of [[E_MODE_SHELL, shells],
    [E_MODE_MONITOR, monitors]] as const) {
    if (n) {
      if (out.length) out.push(" ");
      out.push(span(mark + st.markSp), span(pyIntStr(n), "F_CRM"));
    }
  }
  return spans(out);
}

/** The project / pwd / branch group, the flush-left half of line 3, then
 * `background`.  The names arrive pre-fitted; the branch segment's
 * presence is the session's, so the measuring call with empty names
 * returns the true chrome width. */
export function renderWhereGroup(proj: string, path: string, branch: string,
  git: Git, background: SpanLike = []): Span[] {
  const out = [span(E_PROJ), span(proj, "F_BLU"),
    span(" ".repeat(LEFT_GAP) + E_DIR), span(path, "F_BLU2")];
  if (git.branch) {
    out.push(span(" ".repeat(LEFT_GAP)));
    if (git.dirty) {
      out.push(span(E_GIT_BAD), span(branch + " " + E_DIRTY, "F_AMB"));
    } else {
      out.push(span(E_GIT_OK), span(branch, "F_GRN"));
    }
  }
  const bg = spans(background);
  if (bg.length) out.push(span(" ".repeat(LEFT_GAP)), ...bg);
  return out;
}

/** One chat row: truncated text on a dark background, with a tail riding
 * the right edge. */
export function chatRow(st: Settings, prefix: string, text: string,
  placeholder: string, fg: string, tail: SpanLike,
  cols: number | null): Span[] {
  let body = text;
  let dim = false;
  if (!body) [body, dim] = [placeholder, true];
  const tl = spans(tail);
  let cap = MAX_ROW;
  let tailW = 0;
  if (tl.length && cols) {
    tailW = width(tl, st.widths);
    cap = cols - RIGHT_MARGIN - tailW - MIN_GAP - visWidth(prefix, st.widths);
  }
  if (cap < 1) cap = 1;
  body = fitCols(st, body, cap);

  const out = [span(prefix, fg), span(body, fg, dim, false, "B_DRK")];
  if (tl.length) {
    // tailW stays 0 at an unknown width, as the Python's does; the pad
    // clamps to MIN_GAP either way.
    let pad = (cols || 0) - RIGHT_MARGIN - tailW -
      visWidth(prefix + body, st.widths);
    if (pad < MIN_GAP) pad = MIN_GAP;
    out.push(span(" ".repeat(pad)), ...tl);
  }
  return out;
}

/** Lines 1 and 2, swapping order when the model is thinking.  The tails
 * belong to the positions, not to the speakers.  The stamps are ISO-8601,
 * which sort as their UTF-16 strings sort. */
export function renderChatRows(st: Settings, tr: Transcript,
  tail1: SpanLike, tail2: SpanLike, cols: number | null): [Span[], Span[]] {
  if (tr.user_ts > tr.asst_ts) {
    return [chatRow(st, S_BOT, tr.asst_text, "(no reply yet)", "F_CHAT_B",
      tail1, cols),
    chatRow(st, S_HUMAN, tr.user_text, "(no prompt yet)", "F_CHAT_U",
      tail2, cols)];
  }
  return [chatRow(st, S_HUMAN, tr.user_text, "(no prompt yet)", "F_CHAT_U",
    tail1, cols),
  chatRow(st, S_BOT, tr.asst_text, "(no reply yet)", "F_CHAT_B",
    tail2, cols)];
}

/** One printed line of the readout: the row's spans joined into escapes
 * between the clears.  `grid` says the row ends on a grid row, whose
 * closing reset join writes. */
export function drawnLine(row: SpanLike, grid = true): string {
  return LINE_CLEAR + join(row, grid) + EOL_CLEAR;
}

/** The whole readout, as one string ending in a newline: three rows, or
 * four when the terminal is too narrow for line 3 to hold both halves.
 *
 * `home` is what the Python's os.path.expanduser("~") reads, for showing
 * the working directory under it as "~". */
export function renderStatus(st: Settings, pay: Payload, tr: Transcript,
  git: Git, lim: Limits, cols: number | null, now: number, rules = true,
  ctxWindow = 0, rate: number | null = null,
  cache: CacheShares = NO_CACHE_SHARES, home: string): string {
  let ctxPct: number | null = null;
  if (tr.ctx_tokens > 0 && ctxWindow > 0) {
    ctxPct = Math.trunc(tr.ctx_tokens * 100 / ctxWindow);
  }

  // The ASK and the ROOM: asking never overrides a width without room.
  const rule = rules && rulesOn(st, cols);

  const [dimTurn, dimSess] = shareDims(lim.weekly_turn, lim.weekly_share);
  const [dimRdTurn, dimRdSess] = cacheDims(cache.turn_read, cache.sess_read);
  const usage = gridRow(st, [
    renderStyle(pay.output_style),
    renderModelCost(st, pay.model, pay.effort, pay.cost_usd),
    renderCtx(st, ctxPct, tr.ctx_tokens, tr.ctx_est),
    renderElapsed(st, tr.busy_s, tr.start_s, tr.tool_s, now, tr.blocked_s,
      tr.eta, tr.turn_s, tr.agent_etas),
    renderDate(st, now),
  ], null, rule);
  const limitsRow = gridRow(st, [
    renderPr(st, pay.pr_number),
    renderTokens(st, tr.tok_up, tr.tok_down, st.col2Val2W),
    renderCacheShare(st, S_READ, cache.turn_read, cache.sess_read,
      "F_SHARE", dimRdTurn, dimRdSess),
    renderLimit(st, S_SESS, lim.session_pct, lim.session_share,
      lim.session_reset, lim.session_turn, "F_LIM_SESS", true, now,
      dimTurn, dimSess),
    renderTime(st, now),
  ], null, rule);
  const doing = mainDoing(tr);
  const right = gridRow(st, [
    renderQueue(st, tr.queued, tr.compactions),
    renderRateCache(st, rate, tr.cache_pct, doing[0],
      doing[0] ? Math.max(0.0, now - doing[1]) : null),
    renderCacheShare(st, S_WRITE, cache.turn_write, cache.sess_write,
      "F_SHARE", dimRdTurn, dimRdSess),
    renderLimit(st, S_WEEK, lim.weekly_pct, lim.weekly_share,
      lim.weekly_reset, lim.weekly_turn, "F_LIM_WEEK", false, now,
      dimTurn, dimSess),
    renderDiff(st, pay.lines_added, pay.lines_removed),
  ], null, rule);

  const [row1, row2] = renderChatRows(st, tr, usage, limitsRow, cols);

  let pwdDisplay = pay.current_dir;
  if (pwdDisplay === home) pwdDisplay = "~";
  else if (pwdDisplay.startsWith(home + "/")) {
    pwdDisplay = "~" + pySlice(pwdDisplay, pyLen(home));
  }
  let projDisplay = projectName(git, pay.project_dir);
  let branchDisplay = git.branch;
  const background = renderThreadBackground(st, tr.shells, tr.monitors);

  const rightW = width(right, st.widths);
  let split = false;
  if (cols) {
    // The left names share what the row leaves, less their own chrome,
    // measured by drawing the group with all three names empty.
    const chromeW = width(renderWhereGroup("", "", "", git, background),
      st.widths);
    let budget = cols - RIGHT_MARGIN - rightW - MIN_GAP - chromeW;
    if (budget < LMIN_PROJ + LMIN_PATH) {
      // Too narrow to share line 3: the names move to a line 4.
      split = true;
      budget = Math.max(cols - RIGHT_MARGIN - chromeW, LMIN_PROJ + LMIN_PATH);
    }
    const [aBranch, aProj, aPath] = allocateLeft(budget,
      pyLen(branchDisplay), pyLen(projDisplay), pyLen(pwdDisplay));
    branchDisplay = fitHead(branchDisplay, aBranch);
    projDisplay = fitHead(projDisplay, aProj);
    pwdDisplay = fitPath(pwdDisplay, aPath);
  }

  if (split) {
    const left = renderWhereGroup(projDisplay, pwdDisplay, branchDisplay,
      git, background);
    // Line 3 starts where rows 1 and 2 put their tails.
    const pad = width(row1, st.widths) - width(usage, st.widths);
    return `${drawnLine(row1)}\n${drawnLine(row2)}\n` +
      `${drawnLine([" ".repeat(Math.max(0, pad)), right])}\n` +
      `${drawnLine(left, false)}\n`;
  }

  let line3: SpanLike;
  if (cols) {
    const left = renderWhereGroup(projDisplay, pwdDisplay, branchDisplay,
      git, background);
    let pad = cols - RIGHT_MARGIN - rightW - width(left, st.widths);
    if (pad < MIN_GAP) pad = MIN_GAP;
    line3 = [left, " ".repeat(pad), right];
  } else {
    // No usable width: the left-flowing row, only the path trimmed.
    const bgW = truthy(background)
      ? LEFT_GAP + width(background, st.widths) : 0;
    line3 = [renderWhereGroup(projDisplay,
      fitPath(pwdDisplay, st.pwdMaxFallback - bgW), branchDisplay, git,
      background), " ".repeat(MIN_GAP), right];
  }
  return `${drawnLine(row1)}\n${drawnLine(row2)}\n${drawnLine(line3)}\n`;
}
