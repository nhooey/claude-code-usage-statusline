// Python's semantics, where JavaScript's differ: one copy for every module.
//
// The ports read JSON the Python reads, and the Python reads it through
// dict.get, `or` and truthiness, none of which JavaScript spells the same
// way.  Each helper here is the Python expression in its doc comment, and
// a port writes the helper wherever the Python writes the expression, so
// the two read alike line by line.  sources.ts and claude_records.ts each
// grew a copy of these before this module; they are folded in here so a
// fix to one is a fix to both.

/** A parsed JSON object, which Python reads as a dict. */
export type Dict = { [key: string]: unknown };

/** Is `v` a dict?  A JSON object, a plist dict, or one built here.
 * Arrays, plist data (Uint8Array) and dates are objects too, and none of
 * them is a dict. */
export function isDict(v: unknown): v is Dict {
  if (typeof v !== "object" || v === null) return false;
  const proto = Object.getPrototypeOf(v);
  return proto === Object.prototype || proto === null;
}

/** bool(v): None, False, 0, "", an empty list or dict are false.  NaN is
 * true, which is where it differs from JavaScript's. */
export function pyTruthy(v: unknown): boolean {
  if (v === null || v === undefined || v === false) return false;
  if (typeof v === "number") return v !== 0;
  if (typeof v === "string") return v.length > 0;
  if (Array.isArray(v) || v instanceof Uint8Array) return v.length > 0;
  if (isDict(v)) return Object.keys(v).length > 0;
  return true;
}

/** `d.get(k, dflt)`: the value under an OWN key of a dict, else `dflt`.
 * Own, so a record's "constructor" is not Object's.  A key present with a
 * null value returns the null, not the default, which `a.get("x",
 * a.get("y"))` depends on.  A `d` that is not a dict reads as empty. */
export function pyGet(d: unknown, k: string, dflt: unknown = null): unknown {
  return isDict(d) && Object.hasOwn(d, k) ? d[k] : dflt;
}

/** `k in d`. */
export function pyHas(d: unknown, k: string): boolean {
  return isDict(d) && Object.hasOwn(d, k);
}

/** `a or b`: `a` when it is true, else `b`. */
export function pyOr<A, B>(a: A, b: B): A | B {
  return pyTruthy(a) ? a : b;
}

/** `(d.get(k) or {})` followed by `.get(k2)`, the chain the readers are
 * built from: a missing or non-dict link reads as missing. */
export function pyDig(d: unknown, ...keys: string[]): unknown {
  let cur: unknown = d;
  for (const k of keys) cur = pyGet(cur, k);
  return cur;
}

// Python's str.isspace, which \s, strip() and split() use for a str: the
// JavaScript \s has U+FEFF and lacks U+001C..U+001F and U+0085.
export const PY_SPACE = "\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680" +
  "\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const STRIP = new RegExp(`^[${PY_SPACE}]+|[${PY_SPACE}]+$`, "gu");

/** `s.strip()`. */
export function pyStrip(s: string): string {
  return s.replace(STRIP, "");
}

/** repr(float): the shortest digits that round-trip, as both languages
 * find them, laid out Python's way: fixed between 1e-4 and 1e16 with a
 * ".0" when integral, else d.ddde+XX. */
export function pyFloatRepr(x: number): string {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
  if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
  const [mant, e] = x.toExponential().split("e");
  const exp = Number(e);
  const neg = mant.startsWith("-");
  const digits = mant.replace(/^-/, "").replace(".", "");
  let body: string;
  if (exp >= -4 && exp < 16) {
    if (exp < 0) {
      body = "0." + "0".repeat(-exp - 1) + digits;
    } else if (digits.length <= exp + 1) {
      body = digits + "0".repeat(exp + 1 - digits.length) + ".0";
    } else {
      body = digits.slice(0, exp + 1) + "." + digits.slice(exp + 1);
    }
  } else {
    const m = digits.length > 1 ? digits[0] + "." + digits.slice(1)
      : digits;
    const a = Math.abs(exp);
    body = m + "e" + (exp < 0 ? "-" : "+") + (a < 10 ? "0" + a : String(a));
  }
  return (neg ? "-" : "") + body;
}
