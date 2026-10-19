// Python's semantics, where JavaScript's differ: one copy for every module.
//
// The ports read JSON the Python reads, and the Python reads it through
// dict.get, `or` and truthiness, none of which JavaScript spells the same
// way.  Each helper here is the Python expression in its doc comment, and
// a port writes the helper wherever the Python writes the expression, so
// the two read alike line by line.  sources.ts and claude_records.ts each
// grew a copy of these before this module; they are folded in here so a
// fix to one is a fix to both.

/** UTF-8 to a string, as bytes.decode("utf-8") with `fatal` "strict" or
 * else "replace": a leading byte-order mark kept with `keepBom`, as
 * Python's "utf-8" keeps it, and dropped without, as "utf-8-sig" drops it.
 *
 * Here, and not as TextDecoder's options at each reader, because the mod's
 * runtime takes `fatal` but not `ignoreBOM`: its decoder always drops the
 * mark, so the mark is put back by hand, alike in both runtimes. */
export function utf8(bytes: Uint8Array, fatal = false,
  keepBom = false): string {
  const text = (fatal ? STRICT : REPLACE).decode(bytes);
  return keepBom && bytes[0] === 0xef && bytes[1] === 0xbb &&
    bytes[2] === 0xbf ? "﻿" + text : text;
}

type DecoderWith = new (label: string,
  options: { fatal: boolean }) => TextDecoder;
const STRICT = new (TextDecoder as unknown as DecoderWith)("utf-8",
  { fatal: true });
const REPLACE = new TextDecoder("utf-8");

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

/** The value of a Unicode decimal digit, which Python's int() and float()
 * accept and \d matches: every Nd run is 0..9 in order, so a digit's value
 * is how far it sits from the start of its run, modulo ten. */
function digitValue(ch: string): number {
  let cp = ch.codePointAt(0)!;
  if (cp >= 48 && cp <= 57) return cp - 48;
  let n = 0;
  while (/\p{Nd}/u.test(String.fromCodePoint(cp - 1))) {
    cp--;
    n++;
  }
  return n % 10;
}

/** Unicode digits as ASCII ones, for parseInt and parseFloat, as int()
 * and float() read them. */
export function pyAsciiDigits(s: string): string {
  return s.replace(/\p{Nd}/gu, (c) => String(digitValue(c)));
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

// ════════════════════════════════════════════════════════════════════════════
// Strings by code point, as Python indexes them.
//
// A Python str is a sequence of code points where a JavaScript string is
// one of UTF-16 units, so every emoji above U+FFFF is one character to
// len() and a slice and two to .length and .slice.  The formatters cut,
// count and pad by character, and do it here.
// ════════════════════════════════════════════════════════════════════════════

/** len(s). */
export function pyLen(s: string): number {
  let n = 0;
  for (const _ of s) n++;
  return n;
}

/** s[start:end], negative indices from the end and clamped, as a slice
 * is: an omitted bound is null. */
export function pySlice(s: string, start: number | null = null,
  end: number | null = null): string {
  const cps = Array.from(s);
  const n = cps.length;
  const at = (i: number | null, dflt: number): number => {
    if (i === null) return dflt;
    if (i < 0) return Math.max(0, n + i);
    return Math.min(i, n);
  };
  const a = at(start, 0), b = at(end, n);
  return a < b ? cps.slice(a, b).join("") : "";
}

const RSTRIP_WS = new RegExp(`[${PY_SPACE}]+$`, "u");
const LSTRIP_WS = new RegExp(`^[${PY_SPACE}]+`, "u");

/** s.rstrip(chars): `chars` a set of characters, null for whitespace. */
export function pyRstrip(s: string, chars: string | null = null): string {
  if (chars === null) return s.replace(RSTRIP_WS, "");
  const set = new Set(Array.from(chars));
  const cps = Array.from(s);
  while (cps.length && set.has(cps[cps.length - 1])) cps.pop();
  return cps.join("");
}

/** s.lstrip(chars): `chars` a set of characters, null for whitespace. */
export function pyLstrip(s: string, chars: string | null = null): string {
  if (chars === null) return s.replace(LSTRIP_WS, "");
  const set = new Set(Array.from(chars));
  const cps = Array.from(s);
  let i = 0;
  while (i < cps.length && set.has(cps[i])) i++;
  return cps.slice(i).join("");
}

/** s.split() with no separator: runs of whitespace, none at either end. */
export function pySplitWs(s: string): string[] {
  const t = pyStrip(s);
  return t ? t.split(new RegExp(`[${PY_SPACE}]+`, "u")) : [];
}

/** "%*s" % (w, s) when `left` is false, "%-*s" when it is true: padded
 * with blanks to `w` characters, and a negative `w` pads on the right
 * whichever was asked, as Python's % takes a negative star width. */
export function pyPadS(s: string, w: number, left = false): string {
  const pad = " ".repeat(Math.max(0, Math.abs(w) - pyLen(s)));
  return left || w < 0 ? s + pad : pad + s;
}

/** s.ljust(w). */
export function pyLjust(s: string, w: number): string {
  return s + " ".repeat(Math.max(0, w - pyLen(s)));
}

// ════════════════════════════════════════════════════════════════════════════
// Numbers as % formats them.
// ════════════════════════════════════════════════════════════════════════════

/** "%.*f" % (prec, x): the double's EXACT value rounded half to even, which
 * is what Python's float formatting does and toFixed does not (toFixed
 * takes a tie up, so 2.5 is "3" to it and "2" to Python), at any
 * magnitude (toFixed turns exponential at 1e21).  A negative zero keeps
 * its sign, "-0.0", and a negative precision is none. */
export function pyFormatF(x: number, prec: number): string {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";
  const p = Math.max(0, Math.trunc(prec));
  const neg = x < 0 || Object.is(x, -0);
  // |x| = mant * 2**e, read straight off the IEEE bits.
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, Math.abs(x));
  const hi = view.getUint32(0), lo = view.getUint32(4);
  const bexp = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let e: number;
  if (bexp === 0) {
    e = -1074;
  } else {
    mant |= 1n << 52n;
    e = bexp - 1075;
  }
  let num = mant * 10n ** BigInt(p), den = 1n;
  if (e >= 0) num <<= BigInt(e);
  else den <<= BigInt(-e);
  let q = num / den;
  const twice = 2n * (num % den);
  if (twice > den || (twice === den && (q & 1n) === 1n)) q += 1n;
  let s = q.toString();
  if (p > 0) {
    s = s.padStart(p + 1, "0");
    s = s.slice(0, -p) + "." + s.slice(-p);
  }
  return (neg ? "-" : "") + s;
}

/** "%d" % x, or str(int(x)): the number truncated toward zero, at any
 * magnitude.  An infinity raises OverflowError and a NaN ValueError in
 * Python, so both throw here. */
export function pyIntStr(x: number): string {
  if (!Number.isFinite(x)) throw new RangeError("cannot convert " + x);
  return BigInt(Math.trunc(x)).toString();
}

// The characters str.isdigit takes that int() does not: the superscripts,
// the subscripts and the circled and parenthesised digits, which are
// Numeric_Type=Digit and not decimal.  JavaScript has no property for the
// type, so the ranges are written out; they are the ones a status line
// could plausibly be handed.
const DIGIT_NOT_DECIMAL = "\\u00b2\\u00b3\\u00b9\\u2070\\u2074-\\u2079" +
  "\\u2080-\\u2089\\u2460-\\u2468\\u2474-\\u247c\\u2488-\\u2490\\u24ea" +
  "\\u24f5-\\u24fd\\u24ff\\u2776-\\u277e\\u2780-\\u2788\\u278a-\\u2792";
const IS_DIGIT = new RegExp(`^[\\p{Nd}${DIGIT_NOT_DECIMAL}]+$`, "u");
const IS_DECIMAL = /^\p{Nd}+$/u;

/** s.isdigit(). */
export function pyIsDigit(s: string): boolean {
  return IS_DIGIT.test(s);
}

/** int(s) of a string s.isdigit() passed: a ValueError, thrown, where it
 * holds a digit that is not a decimal one. */
export function pyIntDigits(s: string): number {
  if (!IS_DECIMAL.test(s)) {
    throw new RangeError("invalid literal for int(): " + s);
  }
  return parseInt(pyAsciiDigits(s), 10);
}

const INT_TEXT = /^[+-]?\p{Nd}+(?:_\p{Nd}+)*$/u;

/** int(s) of a string, or null where Python raises ValueError. */
export function pyIntText(s: string): number | null {
  const t = pyStrip(s);
  if (!INT_TEXT.test(t)) return null;
  return parseInt(pyAsciiDigits(t).replaceAll("_", ""), 10);
}

// ════════════════════════════════════════════════════════════════════════════
// The proleptic Gregorian calendar, as datetime counts it.
// ════════════════════════════════════════════════════════════════════════════

/** Days from 1970-01-01 to y-m-d. */
export function daysFromCivil(y: number, m: number, d: number): number {
  y -= m <= 2 ? 1 : 0;
  const era = Math.floor(y / 400);
  const yoe = y - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

/** The days in month m of year y. */
export function daysIn(y: number, m: number): number {
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
}
