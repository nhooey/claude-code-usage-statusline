// Spans: the text a cell draws, each run with its own colour and attributes.
//
// A port of coding_agent_usage_line/spans.py.  A cell returns spans, not a
// string with escape codes in it, so that what it draws can be measured,
// compared and carried to a mod, whose `Text` refuses control characters,
// without parsing escapes back out.  The colour is the NAME of a spec
// constant, "F_PNK" and not its value, so the Python and this port carry
// the same span; the mod looks the name up in spec.ts for a hex colour,
// and `join` derives from that hex the escape the Python's spec.py holds.
//
// A plain string stands in for one uncoloured span wherever spans are
// taken, so a mark or a pad need not be wrapped.
import * as spec from "./spec.ts";
import { pyLen, pyLstrip, pyRstrip } from "./py.ts";
import { visWidth } from "./formatting.ts";
import type { Widths } from "./formatting.ts";

// The attribute escapes.  The colours are spec's; these are not colours.
export const R = "\x1b[0m";                // reset
export const DIM = "\x1b[2m";              // dim attribute: see spans.py
export const BOLD = "\x1b[1m";
export const UNBOLD = "\x1b[22m";          // 22 (bold off) and not 0 (all
                                           // attributes off), so it cannot
                                           // stomp colour set around it.

/** One run of text drawn one way.
 *
 * `colour` and `bg` name an F_* and a B_* constant of spec, or are null for
 * the terminal's own.  A span with none of the four drawn attributes is
 * plain text and writes no escape at all. */
export type Span = {
  readonly text: string;
  readonly colour: string | null;
  readonly dim: boolean;
  readonly bold: boolean;
  readonly bg: string | null;
};

/** Span(text, colour, dim, bold, bg), the NamedTuple's constructor. */
export function span(text: string, colour: string | null = null,
  dim = false, bold = false, bg: string | null = null): Span {
  return { text, colour, dim, bold, bg };
}

/** Span.styled(): whether it writes an escape.  "" names no colour, as it
 * is false to Python. */
export function styled(s: Span): boolean {
  return Boolean(s.colour || s.bg || s.dim || s.bold);
}

export type SpanLike = string | Span | readonly SpanLike[];

function isSpan(x: SpanLike): x is Span {
  return typeof x === "object" && !Array.isArray(x);
}

/** `x` as a flat list of spans: a string is one plain span and "" none,
 * and a list may hold strings, spans and lists of either, so a cell can be
 * written as its pieces in order. */
export function spans(x: SpanLike): Span[] {
  if (typeof x === "string") return x ? [span(x)] : [];
  if (isSpan(x)) return [x];
  const out: Span[] = [];
  for (const s of x as readonly SpanLike[]) out.push(...spans(s));
  return out;
}

/** bool(x) of a SpanLike: a string or a list is true when it is not empty,
 * and a Span always is, since Python's is a tuple of five. */
export function truthy(x: SpanLike): boolean {
  if (typeof x === "string") return x.length > 0;
  if (isSpan(x)) return true;
  return (x as readonly SpanLike[]).length > 0;
}

/** A style with no text yet: `paint` puts text in it.  What a renderer
 * passes where the escape-code version passed a colour prefix such as
 * DIM + F_AMB. */
export function ink(colour: string | null, dim = false): Span {
  return span("", colour, dim);
}

/** `text` in `style`'s colour and attributes. */
export function paint(style: Span, text: string): Span {
  return { ...style, text };
}

/** The spans' text alone, as the terminal's cells hold it. */
export function text(x: SpanLike): string {
  return spans(x).map((s) => s.text).join("");
}

/** Columns the spans occupy, as visWidth counts them under `w`. */
export function width(x: SpanLike, w: Widths): number {
  let n = 0;
  for (const s of spans(x)) n += visWidth(s.text, w);
  return n;
}

/** The spans in `cols` columns, ellipsis included: cut where fitCols cuts
 * their text, the longest start that leaves a column for the `…`, with
 * each span kept as it was drawn.  The `…` takes the style of the span it
 * cuts into.  At no room, `cols` 0 or under, nothing is left, since even
 * the `…` would run a column past it. */
export function cut(x: SpanLike, cols: number, w: Widths): Span[] {
  const out = spans(x);
  const all = text(out);
  if (visWidth(all, w) <= cols) return out;
  if (cols <= 0) return [];
  const budget = cols - 1;                 // a column for the ellipsis
  const cps = Array.from(all);
  let lo = 0, hi = cps.length;
  while (lo < hi) {
    const mid = Math.floor((lo + hi + 1) / 2);
    if (visWidth(cps.slice(0, mid).join(""), w) <= budget) lo = mid;
    else hi = mid - 1;
  }
  const kept: Span[] = [];
  for (const s of out) {
    const t = Array.from(s.text);
    if (lo >= t.length) {
      kept.push(s);
      lo -= t.length;
      continue;
    }
    kept.push({ ...s, text: t.slice(0, lo).join("") + "…" });
    break;
  }
  return kept;
}

/** The spans less trailing blanks, as str.rstrip took them off a drawn
 * string: only off plain spans, since a coloured span's text ends at the
 * reset after it, which no rstrip reached. */
export function rstrip(x: SpanLike): Span[] {
  const out = spans(x);
  while (out.length && !styled(out[out.length - 1])) {
    const t = pyRstrip(out[out.length - 1].text);
    if (t) {
      out[out.length - 1] = { ...out[out.length - 1], text: t };
      break;
    }
    out.pop();
  }
  return out;
}

/** The spans less leading `chars` (blanks by default), as str.lstrip took
 * them off a drawn string: only off plain spans, since a coloured span's
 * text starts after the escape that opens it. */
export function lstrip(x: SpanLike, chars: string | null = null): Span[] {
  const out = spans(x);
  while (out.length && !styled(out[0])) {
    const t = pyLstrip(out[0].text, chars);
    if (t) {
      out[0] = { ...out[0], text: t };
      break;
    }
    out.shift();
  }
  return out;
}

/** Columns of blanks the spans open with: what lstrip(" ") takes off. */
export function indent(x: SpanLike): number {
  return pyLen(text(x)) - pyLen(text(lstrip(x, " ")));
}

/** Whether `s` and `nxt` are both a colour alone, so the escape that opens
 * `nxt` replaces `s`'s colour with no reset between them. */
function runsOn(s: Span, nxt: Span | null): boolean {
  const bare = (t: Span): boolean =>
    Boolean(t.colour) && !(t.bg || t.dim || t.bold);
  return nxt !== null && bare(s) && bare(nxt);
}

const SPEC = spec as unknown as { [name: string]: unknown };

/** The escape spec.py holds for the colour constant `name`: a B_ name lays
 * a background (48), any other a foreground (38), from the hex spec.ts
 * holds.  An unknown name throws, as getattr(spec, name) raises. */
export function escape(name: string): string {
  const hex = Object.hasOwn(SPEC, name) ? SPEC[name] : undefined;
  const m = typeof hex === "string" ? /^#([0-9a-f]{6})$/i.exec(hex) : null;
  if (!m) throw new Error("no colour " + name + " in spec");
  const n = parseInt(m[1], 16);
  return `\x1b[${name.startsWith("B_") ? 48 : 38};2;` +
    `${n >> 16};${(n >> 8) & 255};${n & 255}m`;
}

/** The escapes that open `s`: background, dim, bold, then colour, the
 * order the renderers wrote them in (B_DRK + DIM + F_CHAT_U). */
function sgr(s: Span): string {
  return (s.bg ? escape(s.bg) : "") + (s.dim ? DIM : "") +
    (s.bold ? BOLD : "") + (s.colour ? escape(s.colour) : "");
}

/** The spans as the terminal draws them, with their escape codes.
 *
 * Each styled span is opened with its escapes and closed with a reset of
 * its own, so no attribute leaks into the next: R, or UNBOLD for a span
 * that is only bold, which turns bold off without stomping the colour
 * around it.  Two exceptions keep the bytes the renderers wrote before
 * spans, which the goldens pin:
 *
 * - A span is not reset before one that only lays a background under the
 *   same colour: a chat row's prefix runs straight into its body on the
 *   dark band, "fg 👤 B_DRK fg text R".
 * - `close` writes one more reset at the end, which the status line's grid
 *   rows always carried after their last cell.
 *
 * `runs` keeps the receipt's bytes: its metric groups wrote a run of bare
 * colours, F_TUP ▴ then F_TDN ▾, with one reset after the run, so with it
 * a span that is a colour alone is not reset before another. */
export function join(x: SpanLike, close = false, runs = false): string {
  let out = "";
  const items = spans(x);
  items.forEach((s, i) => {
    if (!styled(s)) {
      out += s.text;
      return;
    }
    out += sgr(s) + s.text;
    const nxt = i + 1 < items.length ? items[i + 1] : null;
    if (nxt !== null && s.colour && nxt.colour === s.colour && nxt.bg &&
      !s.bg && !s.bold) {
      return;
    }
    if (runs && runsOn(s, nxt)) return;
    out += s.bold && !(s.colour || s.bg || s.dim) ? UNBOLD : R;
  });
  if (close) out += R;
  return out;
}
