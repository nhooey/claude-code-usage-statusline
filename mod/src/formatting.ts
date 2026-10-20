// Shared terminal display, measurement, geometry and formatting.
//
// A port of coding_agent_usage_line/formatting.py, function for function.
// The glyphs, colours, widths and cuts are spec.ts's, generated from
// spec/layout.jsonc; what is here is computed from them.  The Python's
// docstrings carry each format's history and argument, and are not copied:
// the comments here say what the port has to do to match it.
//
// WHERE THE PYTHON HAS MODULE STATE, THIS HAS A VALUE.  formatting.py reads
// the terminal profile from the environment at import, fixes the S_* forms
// and the width table from it, and lets set_mark_spacing and
// set_subscript_decimals rebind MARK_SP, RIGHT_GRID, LINE3_RESERVED, the C_*
// widths and SUB_DEC afterwards, and set_right_edge RIGHT_EDGE_COLS.  Here
// all of that is one immutable `Settings`, built once at the edge by
// `settings(env, markSpacing, subscriptDecimals, rightEdge)` and passed
// first to every function that reads any of it.  Every function that reads
// the clock takes `now`, and term_cols takes its process walk and its ioctl
// as arguments.
import {
  C_CACHE_TIGHT, C_LIM_TOT_TIGHT, C_TOK_TIGHT, CACHE_CRIT, CACHE_WARN,
  COL3_TIGHT_W, COL4_TIGHT_W, E_BOT, E_CACHE, E_COST, E_CTX, E_DATE, E_DIFF,
  E_HUMAN, E_IDLE, E_MOD, E_PCT, E_PR, E_RATE, E_READ, E_RESET,
  E_ROW_AGENTS, E_ROW_COMPACT, E_ROW_PROMPT, E_ROW_TOTAL, E_SESS, E_STY,
  E_SUB_DIGITS, E_SUM, E_TIME, E_TOK, E_WEEK, E_WORK, E_WRITE, EAW_WIDE, G,
  K, LINE3_TIGHT, M, MAG_SHARE_READ, MAG_SHARE_SESS, MAG_SHARE_TURN,
  MAX_LINE, MODEL_FAMILIES, MONTH_S, PAD_PROFILES, PAIR_GAP, PROFILE_RULES,
  RIGHT_EDGE, RULE_MIN, SEG_GAP, SEG_RULE, VAL_W, VAL2_W, WIDTH_PROFILES,
} from "./spec.ts";
import {
  pyAsciiDigits, pyFormatF, pyFloatRepr, pyIntDigits, pyIntStr, pyIntText,
  pyIsDigit, pyLen, pyLjust, pyPadS, pyRstrip, pySlice, pySplitWs, pyStrip,
  pyTruthy,
} from "./py.ts";
import { pyFloat } from "./sources.ts";
import { tsEpoch } from "./claude_records.ts";
import { _naiveTimestamp, _strptimeStamp } from "./claude_calib.ts";
import * as sp from "./spans.ts";
import type { Span, SpanLike } from "./spans.ts";

// ════════════════════════════════════════════════════════════════════════════
// Constants that do not depend on the terminal or the switches.
// ════════════════════════════════════════════════════════════════════════════

// Erase the line before painting it and past its end after: see the Python
// for the "1sm" a shrinking value left standing without it.
export const LINE_CLEAR = "\x1b[0m\x1b[2K";
export const EOL_CLEAR = "\x1b[K";

// The ladder humanize and moneyFmt both climb, largest first.
export const SI_UNITS: readonly (readonly [number, string])[] = [
  [G, "G"], [M, "M"], [K, "k"]];

// The cost rows' labels, padded to one width so their 📊 stack.  The emoji
// goes ahead of the padded text, never inside it: ljust counts characters
// and the glyph is two columns.
const LABELS = ["Usage: Prompt (last)", "Usage: Session (total)",
  "Usage: Compact (last)", "Usage: Agents (other)"];
const LABEL_W = Math.max(...LABELS.map(pyLen));
const lab = (e: string, i: number): string =>
  e + " " + pyLjust(LABELS[i], LABEL_W);
export const C_LABEL = lab(E_ROW_PROMPT, 0);
export const C_TOTALS_LABEL = lab(E_ROW_TOTAL, 1);
export const C_COMPACT_LABEL = lab(E_ROW_COMPACT, 2);
export const C_AGENTS_LABEL = lab(E_ROW_AGENTS, 3);

// The status-mode glyph forms that carry a hard space in every profile, or
// none: see formatting.py for each.  The six that carry the profile's paint
// pad are Settings fields (sTok and the rest).
export const S_HUMAN = E_HUMAN + " ";
export const S_BOT = E_BOT + " ";
export const S_TIME = E_TIME + " ";
export const S_DATE = E_DATE + " ";
export const S_IDLE = E_IDLE + " ";
export const S_STY = E_STY + " ";
export const S_PR = E_PR + " ";
export const S_DIFF = E_DIFF + " ";
export const S_WORK = E_IDLE + E_WORK;
export const S_SESS = E_SESS + " ";
export const S_WEEK = E_WEEK + " ";
export const S_READ = E_READ + " ";
export const S_WRITE = E_WRITE + " ";
export const S_RESET = E_RESET;
export const S_SUM = E_SUM + " ";

// ════════════════════════════════════════════════════════════════════════════
// The terminal profile and the settings.
// ════════════════════════════════════════════════════════════════════════════

/** Everything terminal-specific about measuring a string. */
export type Widths = {
  readonly narrow: ReadonlySet<number>;   // advances ONE where the table
                                          // says two
  readonly icons: ReadonlySet<number>;    // advances TWO where it says one
  readonly clusters: boolean;             // folds a grapheme cluster
  readonly wide: readonly (readonly number[])[];
};

/** The environment, as os.environ reads: a missing variable is undefined. */
export type Env = { readonly [name: string]: string | undefined };

/** Which terminal is drawing this, as a profile name: the first of
 * PROFILE_RULES whose variable is set (to its value, where it names one).
 * TMUX goes first; formatting.py says what that rests on. */
export function termProfile(env: Env): string {
  for (const [name, value, profile] of PROFILE_RULES) {
    const v = env[name as string];
    if (v && (value === null || v === value)) return profile as string;
  }
  return "unknown";
}

/** The measurement rules for one terminal profile.  An unknown terminal
 * corrects nothing. */
export function widthsFor(profile: string): Widths {
  for (const p of WIDTH_PROFILES) {
    if ((p.profiles as readonly string[]).includes(profile)) {
      return Object.freeze({
        narrow: new Set<number>(p.narrow), icons: new Set<number>(p.icons),
        clusters: p.clusters, wide: EAW_WIDE,
      });
    }
  }
  return Object.freeze({
    narrow: new Set<number>(), icons: new Set<number>(), clusters: false,
    wide: EAW_WIDE,
  });
}

/** What formatting.py holds as module globals, fixed at import or rebound
 * by its two setters, as one value.  Built by `settings`; never edited. */
export type Settings = {
  readonly profile: string;          // PROFILE
  readonly widths: Widths;           // WIDTHS
  readonly pad: string;              // _PAD: a column of paint room after
                                     // the icons that carry a value, on
                                     // the terminals whose ink spills
  readonly markSp: string;           // MARK_SP
  readonly subDec: boolean;          // SUB_DEC
  readonly rightGrid: readonly number[];  // RIGHT_GRID
  readonly line3Reserved: number;    // LINE3_RESERVED
  readonly pwdMaxFallback: number;   // PWD_MAX_FALLBACK
  readonly cTok: number;             // C_TOK
  readonly cCache: number;           // C_CACHE
  readonly cLimTot: number;          // C_LIM_TOT
  readonly cSess: number;            // C_SESS
  readonly sTok: string;             // S_TOK
  readonly sCtx: string;             // S_CTX
  readonly sMod: string;             // S_MOD
  readonly sRate: string;            // S_RATE
  readonly sCache: string;           // S_CACHE
  readonly sCost: string;            // S_COST
  readonly doingPad: string;         // DOING_PAD
  readonly col2Val2W: number;        // COL2_VAL2_W
  readonly rightEdge: number;        // RIGHT_EDGE_COLS: the columns every
                                     // grid row ends short of the
                                     // terminal's edge
};

/** The settings for a terminal described by `env` (TMUX,
 * TERMINAL_EMULATOR and TERM_PROGRAM are what is read), with the blank
 * between a column-4 mark and its value on or off (--no-mark-spacing), the
 * subscript fraction form on or off (--subscript-decimals), and the
 * columns every grid row ends short of the terminal's edge (--right-edge,
 * RIGHT_EDGE by default).
 *
 * The Python's set_mark_spacing says which constants move together; they
 * are all computed here, so none can be left behind. */
export function settings(env: Env, markSpacing = true,
  subscriptDecimals = false, rightEdge: number = RIGHT_EDGE): Settings {
  const profile = termProfile(env);
  const pad = (PAD_PROFILES as readonly string[]).includes(profile)
    ? " " : "";
  const markSp = markSpacing ? " " : "";
  const n = markSp.length;
  const line3Reserved = LINE3_TIGHT + 6 * n;
  const cLimTot = C_LIM_TOT_TIGHT + n;
  return Object.freeze({
    profile,
    widths: widthsFor(profile),
    pad,
    markSp,
    subDec: subscriptDecimals,
    rightGrid: Object.freeze([11, pad ? 15 : 13, COL3_TIGHT_W + 2 * n,
      COL4_TIGHT_W + 4 * n, 14]),
    line3Reserved,
    pwdMaxFallback: MAX_LINE - line3Reserved,
    cTok: C_TOK_TIGHT + n,
    cCache: C_CACHE_TIGHT + n,
    cLimTot,
    cSess: 9 + cLimTot,
    sTok: E_TOK + pad,
    sCtx: E_CTX + pad,
    sMod: E_MOD + pad,
    sRate: E_RATE + pad,
    sCache: E_CACHE + pad,
    sCost: E_COST + pad,
    doingPad: pad,
    col2Val2W: VAL2_W + pad.length,
    rightEdge,
  });
}

// ════════════════════════════════════════════════════════════════════════════
// Measurement.
// ════════════════════════════════════════════════════════════════════════════

const SGR = /\x1b\[[0-9;]*m/g;

/** Drop SGR escapes so a rendered segment can be measured as text. */
export function stripAnsi(s: string): string {
  return s.replace(SGR, "");
}

/** Columns a string occupies, as THIS terminal counts them: every code
 * point advances on its own, with no grapheme clustering unless the
 * profile says the terminal folds clusters.  formatting.py has the
 * measurements behind it; "fixing" it to handle clusters everywhere
 * reintroduces the four-column error it was written to remove. */
export function visWidth(s: string, w: Widths): number {
  let total = 0;
  let skip = false;
  let prevRi = false;
  for (const ch of stripAnsi(s)) {
    const cp = ch.codePointAt(0)!;
    if (cp < 128) {
      total += 1;
      continue;
    }
    if (w.clusters) {
      if (cp === 0x200d) {                          // ZWJ
        skip = true;
        continue;
      }
      if (skip) {                                   // its partner
        skip = false;
        continue;
      }
      if (cp === 0xfe0f || cp === 0xfe0e || cp === 0x20e3) continue;
      if (cp >= 0x1f3fb && cp <= 0x1f3ff) continue;  // skin tones
      if (cp >= 0x1f1e6 && cp <= 0x1f1ff) {
        // A flag is two regional indicators drawn as one glyph.
        if (prevRi) {
          prevRi = false;
          continue;
        }
        prevRi = true;
      } else {
        prevRi = false;
      }
    }
    if (w.narrow.has(cp)) {
      total += 1;
      continue;
    }
    if (w.icons.has(cp)) {
      total += 2;
      continue;
    }
    // The table is sorted, so the scan stops at the first range starting
    // above this code point.  A hit is two columns; anything else is one.
    for (const [lo, hi] of w.wide) {
      if (cp < lo) break;
      if (cp <= hi) {
        total += 1;
        break;
      }
    }
    total += 1;
  }
  return total;
}

/** `txt` padded into a field of `want` COLUMNS, right-aligned by default.
 * Never truncates.  A string comes back a string, and spans come back
 * spans with the pad a plain span of its own, outside the colour. */
export function padVal(st: Settings, want: number, txt: string,
  left?: boolean): string;
export function padVal(st: Settings, want: number, txt: SpanLike,
  left?: boolean): Span[];
export function padVal(st: Settings, want: number, txt: SpanLike,
  left = false): string | Span[] {
  if (typeof txt !== "string") {
    const have = sp.width(txt, st.widths);
    if (have >= want) return sp.spans(txt);
    const pad = sp.span(" ".repeat(want - have));
    return left ? [...sp.spans(txt), pad] : [pad, ...sp.spans(txt)];
  }
  const have = visWidth(txt, st.widths);
  if (have >= want) return txt;
  const pad = " ".repeat(want - have);
  return left ? txt + pad : pad + txt;
}

/** One grid cell of exactly `want` columns, the slack to the right of the
 * segment (`left`, the status line) or to its left (the cost line).  An
 * empty segment is all pad; it never truncates.  Spans in, spans out; a
 * string comes back a string. */
export function seg(st: Settings, want: number, txt?: string,
  left?: boolean): string;
export function seg(st: Settings, want: number, txt: SpanLike,
  left?: boolean): Span[];
export function seg(st: Settings, want: number, txt: SpanLike = "",
  left = true): string | Span[] {
  if (typeof txt !== "string") {
    const pad = sp.span(" ".repeat(Math.max(0, want -
      sp.width(txt, st.widths))));
    return left ? [...sp.spans(txt), pad] : [pad, ...sp.spans(txt)];
  }
  const have = txt ? visWidth(stripAnsi(txt), st.widths) : 0;
  const pad = " ".repeat(Math.max(0, want - have));
  return left ? txt + pad : pad + txt;
}

/** Two segments as one cell of `want` columns, `a` flush left and `b`
 * flush right, the slack between: `a`'s columns are reserved whether or
 * not it is there, so `b` never moves. */
export function pair(st: Settings, a: SpanLike, b: SpanLike, want: number,
  gap: number = PAIR_GAP): Span[] {
  return [...seg(st, want - sp.width(b, st.widths),
    sp.truthy(a) ? [a, " ".repeat(Math.max(0, gap))] : []), ...sp.spans(b)];
}

/** Whether this row is wide enough to draw the rules between its columns:
 * not in the tight layout, and not at an unknown width or one under
 * RULE_MIN. */
export function rulesOn(st: Settings, cols: number | null): boolean {
  return Boolean(st.markSp) && cols !== null && cols >= RULE_MIN;
}

/** The SEG_GAP columns between two grid cells, ruled or blank, exactly
 * SEG_GAP wide either way, so a ruled row stacks against a blank one. */
export function segGap(rule = false): Span[] {
  if (!rule) return [sp.span(" ".repeat(SEG_GAP))];
  return [sp.span("  "), sp.span(SEG_RULE, "F_RULE"),
    sp.span(" ".repeat(Math.max(0, SEG_GAP - 3)))];
}

/** Lay segments onto the column grid, one per slot, empty for unused; the
 * grid is the settings' RIGHT_GRID unless one is given. */
export function gridRow(st: Settings, cells: readonly SpanLike[],
  grid: readonly number[] | null = null, rule = false): Span[] {
  const g = grid ?? st.rightGrid;
  const gap = segGap(rule);
  const out: Span[] = [];
  g.forEach((want, i) => {
    if (i) out.push(...gap);
    out.push(...seg(st, want, i < cells.length ? sp.spans(cells[i]) : []));
  });
  return out;
}

/** Trim to `maxChars` CHARACTERS by dropping them off the end. */
export function fitHead(t: string, maxChars: number): string {
  if (maxChars > 1 && pyLen(t) > maxChars) {
    return pySlice(t, null, maxChars - 1) + "…";
  }
  return t;
}

/** Trim the path by dropping characters off the FRONT. */
export function fitPath(p: string, maxChars: number): string {
  if (maxChars > 1 && pyLen(p) > maxChars) {
    return "…" + pySlice(p, -(maxChars - 1));
  }
  return p;
}

/** Trim to `maxCols` COLUMNS, ellipsis included, by the binary search the
 * Python inherited from the bash. */
export function fitCols(st: Settings, txt: string, maxCols: number): string {
  if (visWidth(txt, st.widths) <= maxCols) return txt;
  const budget = maxCols - 1;              // a column for the ellipsis
  const cps = Array.from(txt);
  let lo = 0, hi = cps.length;
  while (lo < hi) {
    const mid = Math.floor((lo + hi + 1) / 2);
    if (visWidth(cps.slice(0, mid).join(""), st.widths) <= budget) lo = mid;
    else hi = mid - 1;
  }
  return cps.slice(0, lo).join("") + "…";
}

/** `s` cut to at most `want` columns, counting as visWidth does. */
export function trunc(st: Settings, s: string, want: number): string {
  let out = "", w = 0;
  for (const ch of s) {
    const cw = visWidth(ch, st.widths);
    if (w + cw > want) break;
    out += ch;
    w += cw;
  }
  return out;
}

// ════════════════════════════════════════════════════════════════════════════
// Formatting.
//
// SIGNIFICANT DIGITS, not decimal places, throughout.  Python's "%.Nf"
// rounds the double's exact value half to even, which toFixed does not, so
// every one goes through pyFormatF.
// ════════════════════════════════════════════════════════════════════════════

const SUB_DIGITS = Array.from(E_SUB_DIGITS);
const DEC_RUN = /\.(\p{Nd}+)/gu;    // Python's \d: any Unicode decimal digit

/** A formatted number with its fraction in subscript digits, or unchanged
 * when the switch is off.  Works on the rendered string, so one function
 * covers every magnitude rule; the zero limitPct drops comes back. */
export function subDec(st: Settings, v: string): string {
  if (!st.subDec || !v.includes(".")) return v;
  if (v.startsWith(".")) v = "0" + v;
  return v.replace(DEC_RUN, (_m, ds: string) =>
    Array.from(pyAsciiDigits(ds), (d) => SUB_DIGITS[Number(d)]).join(""));
}

/** 10 ** k as Python's float power gives it for an integer k: the double
 * nearest, which a literal is and Math.pow need not be. */
function pow10(k: number): number {
  return Number("1e" + k);
}

/** re.sub(r"\.0$", "", s). */
function dropPointZero(s: string): string {
  return s.replace(/\.0$/, "");
}

/** A token count in at most four columns: 1234 → "1.2k", 632 → "632 ".
 * Under a thousand the unit column holds a blank. */
export function humanize(st: Settings, n: number): string {
  for (const [lim, unit] of SI_UNITS) {
    // The cut is where the mantissa would round up into a fourth digit.
    if (n >= lim - lim / 2000.0) {
      const v = n / lim;
      const s = v >= 10 ? pyFormatF(v, 0) : dropPointZero(pyFormatF(v, 1));
      return subDec(st, s + unit);
    }
  }
  return subDec(st, pyIntStr(n) + " ");
}

/** The token rate in three characters where three will hold it: no blank
 * unit, and rounded to the unit where humanize keeps a decimal. */
export function rateFig(st: Settings, rate: number): string {
  let s = pyRstrip(humanize(st, rate));
  if (visWidth(s, st.widths) > 3) {
    for (const [lim, unit] of SI_UNITS) {
      if (rate >= lim) {
        s = pyFormatF(rate / lim, 0) + unit;
        break;
      }
    }
  }
  return s;
}

/** Clamp a percentage to two characters: 100 saturates at "99".  "%s" of
 * an int; a JSON number cannot say whether it was 5 or 5.0, so a whole one
 * prints as the int. */
export function pct2(v: number): string {
  if (v > 99) return "99";
  return Number.isInteger(v) ? pyIntStr(v) : pyFloatRepr(v);
}

/** A plan-window percentage for the COST row, `places` decimals at most,
 * trailing zeros stripped, the leading zero kept. */
export function planPct(st: Settings, v: number, places = 2): string {
  if (v >= 100 - 0.5 * pow10(-(places - 1))) {
    return subDec(st, "99." + "9".repeat(Math.max(0, places - 1)));
  }
  const s = v >= 10 - 0.5 * pow10(-places)
    ? pyFormatF(v, places - 1) : pyFormatF(v, places);
  return subDec(st, pyRstrip(pyRstrip(s, "0"), ".") || "0");
}

/** A plan-window percentage in the characters its segment budgets: three
 * by default ("100", "62", "5.4", ".38", "0"), two for the account field,
 * four for an agent's weekly share.  Each cut sits where the next format
 * would round up into one more character. */
export function limitPct(st: Settings, v: number, digits = 3): string {
  return subDec(st, limitPctRaw(v, digits));
}

function limitPctRaw(v: number, digits: number): string {
  if (v <= 0) return "0";
  if (digits > 3) {
    if (v >= 99.95) return "100";
    if (v >= 9.995) return pyFormatF(v, 1);
    if (v >= 0.9995) return pyFormatF(v, 2);
    return pySlice(pyFormatF(v, 3), 1);
  }
  if (digits < 3) {
    if (v >= 99.5) return "100";
    if (v >= 0.95) return pyFormatF(v, 0);
    if (v > 0) return pySlice(pyFormatF(v, 1), 1);
    return "0";
  }
  if (v >= 99.5) return "100";
  if (v >= 9.95) return pyFormatF(v, 0);
  if (v >= 0.995) return dropPointZero(pyFormatF(v, 1));
  return pySlice(pyFormatF(v, 2), 1);
}

/** A dollar figure in four characters: 0.4, 1.9, 12.3, 123, 1.2k, 12k. */
export function moneyFmt(st: Settings, c: number): string {
  for (const [lim, unit] of SI_UNITS) {
    // The cut is where the format below would round into a fifth
    // character: $999.5 belongs with "1.0k".
    if (c >= lim - lim / 2000.0) {
      const v = c / lim;
      return subDec(st, (v >= 10 ? pyFormatF(v, 0)
        : dropPointZero(pyFormatF(v, 1))) + unit);
    }
  }
  return subDec(st, c >= 99.95 ? pyFormatF(c, 0) : pyFormatF(c, 1));
}

/** A dollar figure as three characters and a unit column, humanize's
 * shape, for the status line's 💰: "0.4 ", "12 ", "115 ", "1.2k". */
export function moneyFig(st: Settings, c: number): string {
  if (c >= K - K / 2000.0) return humanize(st, c);
  return (c >= 9.95 ? pyFormatF(c, 0) : pyFormatF(c, 1)) + " ";
}

/** Seconds → "45s" / "1.5m" / "58m" / "2.5h" / "3d" / "1.4M"; `digits`
 * two forbids the decimal. */
export function durFmt(st: Settings, d: number, digits = 3): string {
  if (d < 60) return subDec(st, pyIntStr(d) + "s");
  // The minute and hour cuts sit half a unit early, where "%.0f" would
  // round up into the next unit.
  let v: number, u: string;
  if (d < 3570) [v, u] = [d / 60.0, "m"];
  else if (d < 84600) [v, u] = [d / 3600.0, "h"];
  else if (d < MONTH_S) [v, u] = [d / 86400.0, "d"];
  else [v, u] = [d / MONTH_S, "M"];
  if (digits < 3 || v >= 10) return subDec(st, pyFormatF(v, 0) + u);
  return subDec(st, dropPointZero(pyFormatF(v, 1)) + u);
}

/** int(now): the clock in whole seconds, as the Python takes it so a
 * fraction cannot tip a rounding.  An infinity or a NaN raises there. */
function wholeSeconds(now: number): number {
  if (!Number.isFinite(now)) throw new RangeError("cannot convert " + now);
  return Math.trunc(now);
}

/** Time until `target`, a bare Unix epoch or a local "YYYY-MM-DD HH:MM",
 * in its most significant unit; null for empty or unparseable input, and
 * "now" once the moment has passed.  The local stamp is read in the
 * process's time zone, as datetime.timestamp() reads it. */
export function shortDur(st: Settings, target: string | null,
  now: number): string | null {
  if (!target) return null;
  const t = wholeSeconds(now);
  if (pyIsDigit(target)) {
    const delta = pyIntDigits(target) - t;
    return delta <= 0 ? "now" : durFmt(st, delta);
  }
  const n = _strptimeStamp(target);
  if (n === null) return null;
  // A stamp at the calendar's edge whose local reading falls off it: the
  // Python's timestamp() raises ValueError there, which it catches.
  let stamp: number;
  try {
    stamp = _naiveTimestamp(n);
  } catch {
    return null;
  }
  const delta = Math.trunc(stamp) - t;
  return delta <= 0 ? "now" : durFmt(st, delta);
}

/** How long ago the transcript stamp `ts` was; "0s" for one in the
 * future, null for empty or unparseable input. */
export function elapsedShort(st: Settings, ts: string | null,
  now: number): string | null {
  if (!ts) return null;
  const t0 = tsEpoch(ts);
  if (t0 === null) return null;
  const t = wholeSeconds(now);
  return t > t0 ? durFmt(st, t - t0) : "0s";
}

/** Shorten a model display name: the family and version if both fit the
 * field, the family alone if only it fits, and a cut family with its
 * version only where the family cannot fit at all. */
export function shortModel(m: string, field: number = VAL_W): string {
  const fam = (MODEL_FAMILIES as readonly string[])
    .find((f) => m.startsWith(f)) ?? "";
  if (!fam) return pySlice(m, null, field);
  const ver = pyStrip(pySlice(m, pyLen(fam))).split(" ")[0];
  if (ver && pyLen(fam) + pyLen(ver) <= field) return fam + ver;
  if (pyLen(fam) <= field) return fam;
  return pySlice(m, null, Math.max(0, field - pyLen(ver))) + ver;
}

/** `v` padded so its decimal point falls in a fixed column: `ip` columns
 * of integer, then the point, `fp` of fraction and `suffix` straight after
 * the last digit.  Under subscript decimals the point's column is kept. */
export function decAlign(st: Settings, v: string, ip: number, fp: number,
  suffix = ""): string {
  v = subDec(st, v);
  const dot = v.indexOf(".");
  let head = dot < 0 ? v : v.slice(0, dot);
  const tail = dot < 0 ? "" : v.slice(dot + 1);
  let frac: string;
  if (tail) {
    frac = "." + tail + suffix;
  } else {
    const cps = Array.from(v);
    const cut = cps.findIndex((ch) => SUB_DIGITS.includes(ch));
    if (cut < 0) {
      head = v;
      frac = suffix;
    } else {
      head = cps.slice(0, cut).join("");
      frac = cps.slice(cut).join("") + suffix;
    }
  }
  return pyPadS(head, ip) + pyPadS(frac, fp + 1 + pyLen(suffix), true);
}

/** moneyFmt decimal-aligned in the six columns both cost rows reserve, its
 * unit dec_align's suffix and a blank where there is none. */
export function moneyCell(st: Settings, c: number): string {
  const s = moneyFmt(st, c);
  const cps = Array.from(s);
  const last = cps[cps.length - 1];
  const unit = "kMG".includes(last) ? last : " ";
  return decAlign(st, unit !== " " ? cps.slice(0, -1).join("") : s, 3, 1,
    unit);
}

/** A token delta in exactly five columns: "+142k", "- 88k", "+ 855", the
 * sign in a column of its own. */
export function signed(st: Settings, n: number): string {
  return (n >= 0 ? "+" : "-") + padVal(st, 4, humanize(st, Math.abs(n)));
}

/** min(a, b) as Python's: `a` unless `b` is less, so a NaN first stays. */
function pyMin(a: number, b: number): number {
  return b < a ? b : a;
}

/** A delta as a signed percentage of `whole`: sign, then six columns. */
export function signedPct(st: Settings, n: number, whole: number): string {
  // `if whole`: a NaN is true to Python.
  const p = whole !== 0 ? 100.0 * n / whole : 0.0;
  return (p >= 0 ? "+" : "-") +
    decAlign(st, pyFormatF(pyMin(Math.abs(p), 99.9), 1), 2, 1, E_PCT);
}

/** A percentage in at most three columns, clamped so it never needs four. */
export function pct(p: number): string {
  return pyIntStr(pyMin(wholeSeconds(p), 99)) + E_PCT;
}

// ════════════════════════════════════════════════════════════════════════════
// Colour tiers.
// ════════════════════════════════════════════════════════════════════════════

/** Whether a reset countdown dims: unless it is under an hour away. */
export function resetDim(d: string): boolean {
  return d.endsWith("d") || d.endsWith("h");
}

/** Whether a figure dims: under its magnitude cut.  null, no reading, is
 * left alone. */
export function magDim(v: number | null, cut: number): boolean {
  return !(v === null || v >= cut);
}

/** float(value), or null where Python raises: formatting.py's _pct_num. */
function pctNum(value: unknown): number | null {
  return pyFloat(value);
}

/** Whether the 🎤 and 🎮 shares dim, for both limit rows, off the weekly
 * figures alone.  A missing share is not dimmed here. */
export function shareDims(weekTurn: unknown,
  weekSess: unknown): [boolean, boolean] {
  const t = pyTruthy(weekTurn) ? pctNum(weekTurn) : null;
  const s = pyTruthy(weekSess) ? pctNum(weekSess) : null;
  return [t !== null && t < MAG_SHARE_TURN, s !== null && s < MAG_SHARE_SESS];
}

/** Whether column 3's 🎤 and 🎮 dim, each scope's pair off its 📖 share
 * alone, under MAG_SHARE_READ. */
export function cacheDims(turnRead: number | null,
  sessRead: number | null): [boolean, boolean] {
  return [turnRead !== null && turnRead < MAG_SHARE_READ,
    sessRead !== null && sessRead < MAG_SHARE_READ];
}

/** The cache-hit rate's tier as a style with no text: inverted, a high
 * rate the healthy one, and dim as well as green. */
export function cacheColor(p: number): Span {
  if (p <= CACHE_CRIT) return sp.ink("F_RED");
  if (p <= CACHE_WARN) return sp.ink("F_AMB");
  return sp.ink("F_GRN", true);
}

// ════════════════════════════════════════════════════════════════════════════
// Terminal geometry.
// ════════════════════════════════════════════════════════════════════════════

/** `ps -o tty=,ppid= -p PID`'s output, or null where it could not run. */
export type PsRun = (pid: number) => string | null;

/** Columns of a tty device, or null if it cannot be read: the ioctl. */
export type Winsize = (path: string) => number | null;

/** Columns in the terminal Claude Code is drawing into, or null: the walk
 * up from `ppid`, at most six hops, to the first ancestor with a tty that
 * reports a size.  The process table and the ioctl are the edge's, passed
 * in; formatting.py says why neither stdio nor /dev/tty can answer. */
export function termCols(ppid: number, ps: PsRun,
  winsize: Winsize): number | null {
  let p = ppid;
  for (let i = 0; i < 6; i++) {
    if (p <= 1) return null;
    const stdout = ps(p);
    if (stdout === null) return null;
    const out = pySplitWs(stdout);
    if (out.length < 2) return null;
    const [tty, parent] = out;
    if (tty && tty !== "?" && tty !== "??") {
      const cols = winsize("/dev/" + tty);
      if (cols) return cols;
    }
    const next = pyIntText(parent);
    if (next === null) return null;
    p = next;
  }
  return null;
}
