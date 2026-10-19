// The fixtures' encoding, shared by formatting.test.ts and spans.test.ts:
// tests/fixtures/gen/formatting.py writes a Span as {"span": [text, colour,
// dim, bold, bg]} and a float JSON cannot carry as {"$float": ...}.
import * as sp from "../src/spans.ts";
import type { Span } from "../src/spans.ts";

/** The generator's JSON back to values: {"$float": ...} is what JSON
 * cannot spell, and {"span": [...]} a Span. */
export function revive(v: any): any {
  if (Array.isArray(v)) return v.map(revive);
  if (v !== null && typeof v === "object") {
    if (Object.keys(v).length === 1 && "$float" in v) {
      return { inf: Infinity, "-inf": -Infinity, nan: NaN, "-0": -0 }[
        v.$float as string];
    }
    if (Object.keys(v).length === 1 && "span" in v) {
      const [text, colour, dim, bold, bg] = v.span;
      return sp.span(text, colour, dim, bold, bg);
    }
    return Object.fromEntries(Object.entries(v).map(([k, x]) =>
      [k, revive(x)]));
  }
  return v;
}

/** A TypeScript result as the generator writes the Python's: a Span as
 * {"span": [...]}, a set as its sorted list, a non-finite float marked. */
export function enc(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(enc);
  if (v instanceof Set) return [...v].sort((a, b) => a - b);
  if (typeof v === "number") {
    if (Number.isNaN(v)) return { $float: "nan" };
    if (!Number.isFinite(v)) return { $float: v > 0 ? "inf" : "-inf" };
    if (Object.is(v, -0)) return { $float: "-0" };
    return v;
  }
  if (v !== null && typeof v === "object") {
    if ("text" in v && "colour" in v) {
      const s = v as Span;
      return { span: [s.text, s.colour, s.dim, s.bold, s.bg] };
    }
    return Object.fromEntries(Object.entries(v).map(([k, x]) =>
      [k, enc(x)]));
  }
  return v;
}
