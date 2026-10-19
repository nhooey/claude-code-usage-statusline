// Claude payload records and transcript/accounting parser.
//
// The port of claude_records.py, function for function under the same names
// in camelCase.  It owns Claude-specific JSONL interpretation and price
// accounting, and has no terminal rendering.
//
// The Python reads files inside its functions; here every reader that takes
// a path is a thin edge over a pure core that takes the bytes or the parsed
// records (`_recordsOf`, `transcriptOf`, `turnsOf`, ...), so the mod can
// feed it what its own handlers read.  The state directory, the clock and
// the cache version are arguments, never read from the environment here.
//
// What does not carry over from Python by itself, decided once:
//
//   - Truthiness.  `r.get("x") or y` treats 0, "", [], {} and None alike;
//     JavaScript does not, so every such test goes through `truthy` and `or`.
//   - Missing is null, never undefined and never zero.  `get` returns
//     undefined for an absent key so that `"k" in d` and `d.get("k")` stay
//     apart where the Python tells them apart.
//   - Numbers.  JSON.parse cannot tell 5 from 5.0, so the two places the
//     Python asks `isinstance(v, int)` accept an integral float here; and an
//     integer past 2**53 loses precision.
//   - Strings.  Python counts and iterates code points, and its regexes'
//     \d and \s are Unicode classes; the port does the same explicitly.
//   - Bytes.  Agent files are read as bytes and their offsets are byte
//     offsets; lines are found in a Uint8Array, never in a decoded string.
//   - Crashes.  Where a malformed field makes the Python raise (a record
//     that is not an object, a usage count that is not a number), the port
//     carries on with the field missing.  No shared case pins those inputs.

import * as fs from "node:fs";
import * as crypto from "node:crypto";
import { E_FOLD, E_ETA_REPORT, E_ETA_REPORT_OLD } from "./spec.ts";

// ════════════════════════════════════════════════════════════════════════════
// Python's semantics, where JavaScript's differ.
// ════════════════════════════════════════════════════════════════════════════

/** A parsed JSON object, the shape every record is read as. */
export type Rec = { readonly [k: string]: unknown };

/** Is `v` a JSON object, which Python reads as a dict? */
export function isDict(v: unknown): v is Rec {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** `d.get(k)`: the value under an OWN key of a dict, else undefined.  Own,
 * so a record's "constructor" is not Object's. */
export function get(d: unknown, k: string): unknown {
  return isDict(d) && Object.hasOwn(d, k) ? d[k] : undefined;
}

/** `k in d`. */
export function has(d: unknown, k: string): boolean {
  return isDict(d) && Object.hasOwn(d, k);
}

/** Python's truth: None, False, 0, "", an empty list or dict are false. */
export function truthy(v: unknown): boolean {
  if (v === null || v === undefined || v === false || v === 0 || v === "") {
    return false;
  }
  if (Array.isArray(v)) return v.length > 0;
  if (isDict(v)) return Object.keys(v).length > 0;
  return true;
}

/** `a or b`: `a` when it is true, else `b`. */
export function or<A, B>(a: A, b: B): A | B {
  return truthy(a) ? a : b;
}

/** `(d.get(k) or {})` followed by `.get(k2)`, the chain the reader is
 * built from: a missing or non-dict link reads as missing. */
export function dig(d: unknown, ...keys: string[]): unknown {
  let cur: unknown = d;
  for (const k of keys) cur = get(cur, k);
  return cur;
}

/** A number field read `u.get(k) or 0`. */
function num0(v: unknown): number {
  return typeof v === "number" && truthy(v) ? v : 0;
}

/** A number field read `u.get(k, 0)`: present and null is the Python's
 * TypeError, read here as 0. */
function numGet(d: unknown, k: string): number {
  const v = get(d, k);
  return typeof v === "number" ? v : 0;
}

/** Python's code-point string order, which `sorted` and `<` use.  The
 * default JavaScript order is by UTF-16 unit, and puts an astral character
 * before U+E000..U+FFFF. */
export function cmpStr(a: string, b: string): number {
  const ia = a[Symbol.iterator](), ib = b[Symbol.iterator]();
  for (;;) {
    const x = ia.next(), y = ib.next();
    if (x.done || y.done) return x.done ? (y.done ? 0 : -1) : 1;
    const cx = x.value.codePointAt(0)!, cy = y.value.codePointAt(0)!;
    if (cx !== cy) return cx < cy ? -1 : 1;
  }
}

/** `len(s)`: code points, not UTF-16 units. */
export function pyLen(s: string): number {
  let n = 0;
  for (const _ of s) n++;
  return n;
}

// Python's str.isspace, which \s, strip() and split() use for a str: the
// JavaScript \s has U+FEFF and lacks U+001C..U+001F and U+0085.
const PY_SPACE = "\\t\\n\\v\\f\\r\\x1c-\\x20\\x85\\xa0\\u1680" +
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

/** Unicode digits as ASCII ones, for parseInt and parseFloat. */
function asciiDigits(s: string): string {
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

// What isprintable() refuses, which repr() escapes: the C and Z categories
// but the space.
const UNPRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

/** repr() of a JSON value, as `"%s" % v` prints a list or a dict.  A JSON
 * number is an int when integral; see the head of the file. */
export function pyRepr(v: unknown): string {
  if (v === null || v === undefined) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  if (typeof v === "number") {
    return Number.isInteger(v) ? BigInt(v).toString() : pyFloatRepr(v);
  }
  if (typeof v === "string") {
    const q = v.includes("'") && !v.includes('"') ? '"' : "'";
    let out = q;
    for (const ch of v) {
      const cp = ch.codePointAt(0)!;
      if (ch === q || ch === "\\") out += "\\" + ch;
      else if (ch === "\t") out += "\\t";
      else if (ch === "\n") out += "\\n";
      else if (ch === "\r") out += "\\r";
      else if (ch !== " " && UNPRINTABLE.test(ch)) {
        const h = cp.toString(16);
        out += cp < 0x100 ? "\\x" + h.padStart(2, "0")
          : cp < 0x10000 ? "\\u" + h.padStart(4, "0")
          : "\\U" + h.padStart(8, "0");
      } else out += ch;
    }
    return out + q;
  }
  if (Array.isArray(v)) return "[" + v.map(pyRepr).join(", ") + "]";
  if (isDict(v)) {
    return "{" + Object.entries(v)
      .map(([k, x]) => pyRepr(k) + ": " + pyRepr(x)).join(", ") + "}";
  }
  return String(v);
}

/** str(v). */
export function pyStr(v: unknown): string {
  return typeof v === "string" ? v : pyRepr(v);
}

/** os.path.join for two parts, which unlike path.join normalises nothing,
 * so a path built here is spelt as the Python spells it. */
export function pyJoin(a: string, b: string): string {
  if (b.startsWith("/")) return b;
  return a === "" || a.endsWith("/") ? a + b : a + "/" + b;
}

/** os.path.basename, which unlike path.basename keeps a trailing slash's
 * empty name. */
export function pyBasename(p: string): string {
  return p.slice(p.lastIndexOf("/") + 1);
}

/** json.dumps(d) for a flat {str: int}, with its default ", " and ": " and
 * ensure_ascii, so a file the two languages write is the same bytes. */
export function pyJsonDumps(d: ReadonlyMap<string, number>): string {
  const str = (s: string) => '"' + Array.from(s, (ch) => {
    const cp = ch.codePointAt(0)!;
    if (ch === '"') return '\\"';
    if (ch === "\\") return "\\\\";
    const esc: Record<string, string> = {
      "\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f" };
    if (esc[ch]) return esc[ch];
    if (cp < 0x20 || cp > 0x7e) {
      const u = (c: number) => "\\u" + c.toString(16).padStart(4, "0");
      if (cp < 0x10000) return u(cp);
      const c = cp - 0x10000;
      return u(0xd800 + (c >> 10)) + u(0xdc00 + (c & 0x3ff));
    }
    return ch;
  }).join("") + '"';
  return "{" + [...d].map(([k, v]) => str(k) + ": " + String(v))
    .join(", ") + "}";
}

/** Python's `max(a, b)`: `a` unless `b` is greater. */
function pyMax(a: number, b: number): number {
  return b > a ? b : a;
}

/** Python's `min(a, b)`: `a` unless `b` is less. */
function pyMin(a: number, b: number): number {
  return b < a ? b : a;
}

/** Lexicographic order over number tuples, as `sorted` orders them. */
function cmpTuple(a: readonly number[], b: readonly number[]): number {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  }
  return a.length - b.length;
}

// Billing weights relative to a fresh input token.  Raw ▴ traffic is ~99%
// cache reads in a typical session, so an unweighted sum says nothing about
// either cost or context size.  The write weight is TTL-dependent — 1.25x
// at the 5-minute default, 2x at the 1-hour TTL these sessions run on.
export const W_CACHE_WRITE = 2.0;
export const W_CACHE_READ = 0.1;

// Opus 5 list price, USD per token, for the cost line's per-prompt figure.
export const P_IN = 5e-6, P_OUT = 25e-6, P_CR = 0.5e-6, P_CW = 10e-6;

export type Prices = readonly [number, number, number, number];

// Per-model prices.  For the calibration scan, which sees other sessions'
// turns and so cannot assume one model; and since 2026-09-11 for every
// record read_turns prices, because an agent can run a model its session
// does not.  $/token: fresh, output, cache-read, cache-write at the 2x TTL.
//
// FIRST MATCH WINS, so the specific rows sit above the family they refine.
// Figures are Claude Code's own: its binary bakes in a model catalog
// (`pricing_tiers` / `models[].pricing`), read out of 2.1.268 on 2026-09-11.
// Fable 5.1 differs from Fable 5 in one field, cache-read, and Sonnet 5 is
// not Sonnet 4.x — the old "sonnet" row was 3/15/6/0.3, which is the 4.x
// tier and priced every Sonnet 5 fork half again too high.  The bare
// "opus" row stays as _price's fallback for a model it has never heard of:
// the deliberate ceiling rather than a guess in the other direction.
export const MODEL_PRICE: readonly (readonly [string, Prices])[] = [
  ["opus", [5e-6, 25e-6, 0.5e-6, 10e-6]],
  ["fable-5-1", [10e-6, 50e-6, 0.25e-6, 20e-6]],
  ["fable", [10e-6, 50e-6, 1e-6, 20e-6]],
  ["sonnet-5", [2e-6, 10e-6, 0.2e-6, 4e-6]],
  ["sonnet", [3e-6, 15e-6, 0.3e-6, 6e-6]],
  ["haiku", [1e-6, 5e-6, 0.1e-6, 2e-6]],
];

// ════════════════════════════════════════════════════════════════════════════
// Records.
// ════════════════════════════════════════════════════════════════════════════
//
// Each NamedTuple is a readonly record and a function of the same name that
// fills in its defaults.  NamedTuples compare by value (`lim == NO_LIMITS`);
// records do not, so `recordEqual` is that comparison.

/** Value equality over records, arrays and primitives. */
export function recordEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a === "number" && typeof b === "number") return a === b;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => recordEqual(x, b[i]));
  }
  if (isDict(a) && isDict(b)) {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length &&
      ka.every((k) => Object.hasOwn(b, k) && recordEqual(a[k], b[k]));
  }
  return false;
}

/** The status-line JSON, reduced to what is actually read. */
export interface Payload {
  readonly currentDir: string;
  readonly projectDir: string;
  readonly model: string;
  readonly modelId: string;
  readonly ctxWindow: string;       // context_window.context_window_size
  readonly transcript: string;
  readonly costUsd: string;
  readonly linesAdded: string;
  readonly linesRemoved: string;
  readonly outputStyle: string;
  readonly effort: string;
  readonly sessionId: string;
  readonly rlSessionPct: string;
  readonly rlSessionReset: string;
  readonly rlWeeklyPct: string;
  readonly rlWeeklyReset: string;
  readonly prNumber: string;
}

/** What one pass over the transcript yields for the status line.
 *
 * `tokUp` is null only when there was no transcript to read at all, which
 * is a different state from a transcript that exists and is empty: the
 * first suppresses the token segment, the second renders it as zeros.  Two
 * empty states, two renderings, and conflating them was how a fresh session
 * grew a "▴0 ▾0" that looked like a stall.  The fields are documented on
 * the Python's Transcript, field for field. */
export interface Transcript {
  readonly tokUp: number | null;
  readonly tokDown: number;
  readonly cachePct: number;        // -1 when there is no usage data at all
  readonly ctxTokens: number;
  readonly userTs: string;
  readonly userText: string;
  readonly asstTs: string;
  readonly asstText: string;
  readonly busyS: number;           // this thread's answering; thread_clock
  readonly startS: number;          // epoch of the first STAMPED record
  readonly toolS: number;           // inside a tool, less the waiting spans
  readonly blockedS: number;        // inside a WAITING_TOOLS call
  readonly turnS: number;           // epoch of the current turn's prompt
  readonly eta: readonly number[];  // (epoch, seconds left), or ()
  readonly agentEtas: readonly (readonly [number, number | null])[];
  readonly queued: number;          // messages waiting; see queueStep
  readonly compactions: number;     // see isCompaction
  readonly ctxEst: boolean;         // ctxTokens is a compaction's estimate
  readonly shells: number;          // open background shells; scanBackground
  readonly monitors: number;        // and Monitors, likewise
  readonly toolAt: number;          // oldest running tool call, on a live read
  readonly waitAt: number;          // oldest WAITING_TOOLS call, likewise
  readonly idleAt: number;          // the last answer's end, while idle
  readonly lastSeen: number;        // its last stamped record of any kind
}

type TranscriptFirst = "tokUp" | "tokDown" | "cachePct" | "ctxTokens" |
  "userTs" | "userText" | "asstTs" | "asstText" | "busyS" | "startS";

export function transcript(
  t: Pick<Transcript, TranscriptFirst> & Partial<Transcript>): Transcript {
  return {
    toolS: 0.0, blockedS: 0.0, turnS: 0.0, eta: [], agentEtas: [],
    queued: 0, compactions: 0, ctxEst: false, shells: 0, monitors: 0,
    toolAt: 0.0, waitAt: 0.0, idleAt: 0.0, lastSeen: 0.0, ...t,
  };
}

export const EMPTY_TRANSCRIPT: Transcript = transcript({
  tokUp: null, tokDown: 0, cachePct: -1, ctxTokens: 0, userTs: "",
  userText: "", asstTs: "", asstText: "", busyS: 0.0, startS: 0.0,
});

export interface Git {
  readonly inGit: boolean;
  readonly branch: string;
  readonly dirty: boolean;
  readonly toplevel: string;
  readonly mainRoot: string;
  readonly isWorktree: boolean;
}

export const NO_GIT: Git = {
  inGit: false, branch: "", dirty: false, toplevel: "", mainRoot: "",
  isWorktree: false,
};

/** The two plan windows.  Percentages are strings because a missing figure
 * is the empty string throughout, which is what makes a blank row blank.
 * They carry whatever precision their source gave them and are not rounded
 * until limit_pct draws them. */
export interface Limits {
  readonly sessionPct: string;
  readonly sessionReset: string;
  readonly sessionShare: string;
  readonly weeklyPct: string;
  readonly weeklyReset: string;
  readonly weeklyShare: string;
  // What the ONE turn just answered put into each window; only
  // _with_shares has a transcript to derive it from.
  readonly sessionTurn: string;
  readonly weeklyTurn: string;
}

export function limits(l: Omit<Limits, "sessionTurn" | "weeklyTurn"> &
  Partial<Limits>): Limits {
  return { sessionTurn: "", weeklyTurn: "", ...l };
}

export const NO_LIMITS: Limits = limits({
  sessionPct: "", sessionReset: "", sessionShare: "", weeklyPct: "",
  weeklyReset: "", weeklyShare: "",
});

/** Where the money went, as whole percent of a bill: 📖 cache reads and 📝
 * cache writes, for the turn just answered and for the session.  null is a
 * figure that could not be derived and draws "?". */
export interface CacheShares {
  readonly turnRead: number | null;
  readonly turnWrite: number | null;
  readonly sessRead: number | null;
  readonly sessWrite: number | null;
}

export function cacheShares(c: Partial<CacheShares> = {}): CacheShares {
  return { turnRead: null, turnWrite: null, sessRead: null, sessWrite: null,
    ...c };
}

export const NO_CACHE_SHARES: CacheShares = cacheShares();

/** One prompt the user typed, and everything billed while answering it,
 * its agents' requests included.  Field by field as the Python's Turn,
 * which says what each one means. */
export interface Turn {
  readonly ts: string;
  readonly text: string;
  readonly fresh: number;
  readonly cacheWrite: number;
  readonly cacheRead: number;
  readonly out: number;
  readonly ctx: number;             // a READING, not a sum — see readTurns
  readonly calls: number;
  readonly durS: number;
  readonly dctx: number | null;     // growth over the previous reading
  readonly usdIn: number;           // the bill's four parts, each priced
  readonly usdOut: number;          // per record at its own model
  readonly usdCr: number;
  readonly usdCw: number;
  readonly compact: boolean;
  readonly reported: boolean;
  readonly parts: readonly (readonly [number | null, number])[];
  readonly agentCalls: number;
  readonly agentIds: readonly unknown[];
  readonly agent: boolean;
  readonly toolS: number;
  readonly blockedS: number;
  readonly agentModelS: number;
  readonly agentToolS: number;
  readonly agentId: string;
  readonly agentName: string;
  readonly promptId: string;
  readonly turnIndex: number | null;
}

type TurnFirst = "ts" | "text" | "fresh" | "cacheWrite" | "cacheRead" |
  "out" | "ctx" | "calls" | "durS" | "dctx" | "usdIn" | "usdOut" | "usdCr" |
  "usdCw";

export function turn(t: Pick<Turn, TurnFirst> & Partial<Turn>): Turn {
  return {
    compact: false, reported: false, parts: [], agentCalls: 0, agentIds: [],
    agent: false, toolS: 0.0, blockedS: 0.0, agentModelS: 0.0,
    agentToolS: 0.0, agentId: "", agentName: "", promptId: "",
    turnIndex: null, ...t,
  };
}

/** One billed request from an agent's transcript, with what is needed to
 * file it under a turn of the main transcript.  See agentRecords. */
export interface AgentRec {
  readonly epoch: number | null;
  readonly promptId: unknown;       // "" where the agent file never said
  readonly model: unknown;
  readonly fresh: number;
  readonly cacheWrite: number;
  readonly cacheRead: number;
  readonly out: number;
  readonly requestId: unknown;
  readonly path: string;            // the agent file, for the offsets the
  readonly offset: number;          // Stop hook keeps — see agentOffsets
  readonly modelS: number;          // the agent's 🤖 and 🔧 since its
  readonly toolS: number;           // previous billed request; splitClock
}

// ════════════════════════════════════════════════════════════════════════════
// Reading the payload.
// ════════════════════════════════════════════════════════════════════════════

/** First present, non-null value among dotted `paths`, else `dflt`.
 *
 * Mirrors jq's `//` chain, including that it short-circuits on null or
 * absent but NOT on a present falsy value like 0 or false. */
export function _first(d: unknown, paths: readonly string[],
  dflt = ""): string {
  for (const p of paths) {
    let cur: unknown = d;
    let ok = true;
    for (const part of p.split(".")) {
      if (has(cur, part)) cur = get(cur, part);
      else {
        ok = false;
        break;
      }
    }
    if (ok && cur !== null && cur !== false) {
      return typeof cur === "string" ? cur : _num(cur);
    }
  }
  return dflt;
}

/** A JSON number the way jq -r prints it: integers without a decimal. */
export function _num(v: unknown): string {
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number" && Number.isInteger(v)) {
    return BigInt(v).toString();
  }
  return pyStr(v);
}

/** Parse the status-line JSON.  A malformed payload yields empty fields
 * rather than an exception: a status line that renders nothing is a worse
 * failure than one that renders a row of blanks. */
export function readPayload(raw: string): Payload {
  let d: unknown;
  try {
    d = JSON.parse(raw);
  } catch {
    d = {};
  }
  if (!isDict(d)) d = {};
  return {
    currentDir: _first(d, ["workspace.current_dir", "cwd"]),
    projectDir: _first(d, ["workspace.project_dir", "cwd"]),
    model: _first(d, ["model.display_name"]),
    modelId: _first(d, ["model.id"]),
    ctxWindow: _first(d, ["context_window.context_window_size"]),
    transcript: _first(d, ["transcript_path"]),
    costUsd: _first(d, ["cost.total_cost_usd"]),
    linesAdded: _first(d, ["cost.total_lines_added"], "0"),
    linesRemoved: _first(d, ["cost.total_lines_removed"], "0"),
    outputStyle: _first(d, ["output_style.name"]),
    effort: _first(d, ["effort.level"]),
    sessionId: _first(d, ["session_id"]),
    rlSessionPct: _first(d, ["rate_limits.five_hour.used_percentage"]),
    rlSessionReset: _first(d, ["rate_limits.five_hour.resets_at"]),
    rlWeeklyPct: _first(d, ["rate_limits.seven_day.used_percentage"]),
    rlWeeklyReset: _first(d, ["rate_limits.seven_day.resets_at"]),
    // Five alternate locations, first non-null wins.  Claude Code has moved
    // this field before and may again.
    prNumber: _first(d, ["pr.number", "github.pr.number",
      "github.pull_request.number", "github_pr.number",
      "pull_request.number"]),
  };
}

// ════════════════════════════════════════════════════════════════════════════
// Reading the transcript.
// ════════════════════════════════════════════════════════════════════════════

// Decoding as Python's text mode does with errors="replace", keeping a BOM,
// which "utf-8" (unlike "utf-8-sig") does not strip.
const DECODE_REPLACE = new TextDecoder("utf-8", { ignoreBOM: true });
// Decoding as json.loads(bytes) does: invalid UTF-8 raises, and the line is
// skipped; a leading BOM is taken as "utf-8-sig" and dropped.
const DECODE_STRICT = new TextDecoder("utf-8", { fatal: true });

/** Every line of `data` that parses, in order, as `_records` yields them.
 *
 * The Python opens the file in text mode, whose universal newlines split on
 * "\r\n", "\r" and "\n" alike.  A record that is not an object is dropped:
 * the Python yields it and its first reader raises on it. */
export function _recordsOf(data: Uint8Array): Rec[] {
  const out: Rec[] = [];
  for (const line of DECODE_REPLACE.decode(data).split(/\r\n|\r|\n/)) {
    if (line === "") continue;
    try {
      const r: unknown = JSON.parse(line);
      if (isDict(r)) out.push(r);
    } catch {
      continue;
    }
  }
  return out;
}

/** Yield parsed JSONL records, skipping any line that will not parse.
 *
 * A transcript is appended to live, so the last line can be a partial
 * write.  Skipping is the only reasonable response; failing would blank the
 * row for whichever frame caught the file mid-append. */
export function _records(path: string): Rec[] {
  let data: Uint8Array;
  try {
    data = fs.readFileSync(path);
  } catch {
    return [];
  }
  return _recordsOf(data);
}

/** Assistant records carrying usage, deduped FIRST-WINS on request id.
 *
 * Two reasons this matters, and the second is the one that gets forgotten:
 *
 *   1. Claude Code writes one JSONL line per content block — thinking,
 *      text, each tool call — and repeats the whole usage object on every
 *      one.  A turn with ten parallel Reads writes twelve lines all claiming
 *      the same cache reads, so summing lines instead of requests inflates
 *      the total about fourfold.
 *   2. A RETRIED request appears again with the same id.  First-wins is
 *      what stops the retry being billed twice; last-wins or no dedupe both
 *      double-count it.
 *
 * Order-preserving, because callers below take the LAST non-sidechain
 * entry and a re-sort would lose track of which request that was. */
export function _dedupeUsage(records: readonly Rec[]): Rec[] {
  const seen = new Set<unknown>();
  const out: Rec[] = [];
  for (const r of records) {
    if (!truthy(dig(r, "message", "usage"))) continue;
    const k = or(or(get(r, "requestId"), dig(r, "message", "id")), "?");
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(r);
  }
  return out;
}

/** One record's bill, split four ways, at its own model's rates. */
export function _usd(model: unknown, fresh: number, cw: number, cr: number,
  out: number): Prices {
  const [pi, po, pr, pw] = _price(model);
  return [fresh * pi, out * po, cr * pr, cw * pw];
}

// Pictographs whose DEFAULT PRESENTATION IS TEXT, as sorted ranges.
//
// EAW_WIDE blankets 1F300-1FBFF as two columns, and that blanket is wrong
// for about 1,600 codepoints in it.  UAX #11 gives Wide to a pictograph
// whose default presentation is emoji and Neutral to the rest, so this
// table is the blanket's exceptions: 🛢 U+1F6E2, 🕰 U+1F570, 🗓, 🗑, 🎟, 🌡
// and the rest of that family.  With no emoji presentation they are drawn
// from whatever text font the terminal reaches for — one column in some,
// two in others.  It is used by squash, to escape the ones that turn up in
// chat text, where nobody vets the glyphs.  Regional indicators are in here
// too: a flag is two of them, and the terminal decides how wide.
//
// Generated from unicodedata (UCD 15.0.0).  KEEP IT SORTED — the scan stops
// at the first range starting above the codepoint.
export const EAW_TEXT_PRES: readonly (readonly [number, number])[] = [
  [126976, 126979], [126981, 127182], [127184, 127373], [127375, 127376],
  [127387, 127487], [127491, 127503], [127548, 127551], [127561, 127567],
  [127570, 127583], [127590, 127743], [127777, 127788], [127798, 127798],
  [127869, 127869], [127892, 127903], [127947, 127950], [127956, 127967],
  [127985, 127987], [127989, 127991], [128063, 128063], [128065, 128065],
  [128253, 128254], [128318, 128330], [128335, 128335], [128360, 128377],
  [128379, 128404], [128407, 128419], [128421, 128506], [128592, 128639],
  [128710, 128715], [128717, 128719], [128723, 128724], [128728, 128731],
  [128736, 128746], [128749, 128755], [128765, 128991], [129004, 129007],
  [129009, 129291], [129339, 129339], [129350, 129350], [129536, 129647],
  [129661, 129663], [129673, 129679], [129726, 129726], [129734, 129741],
  [129756, 129759], [129769, 129775], [129785, 130047],
];

/** Is this a pictograph the terminal will draw from a TEXT font?  The table
 * is sorted, so the scan stops at the first range starting above it. */
export function _textPres(cp: number): boolean {
  for (const [lo, hi] of EAW_TEXT_PRES) {
    if (cp < lo) return false;
    if (cp <= hi) return true;
  }
  return false;
}

/** Make chat text safe to measure, and flatten it to one line.
 *
 * Chat text is the one part of the row nobody vets, and a single glyph
 * whose width is guessed wrong drags the whole metric block out of line.
 * So the glyphs that cannot be trusted are replaced by their codepoint in
 * ASCII: <27F3> in place of a reset arrow, exact in width and saying what
 * was there.  Three families qualify: U+2190-U+2BFF (arrows, misc
 * technical, misc symbols, dingbats), the variation selectors, and the
 * text-presentation pictographs of EAW_TEXT_PRES.  The Python's docstring
 * has the history. */
export function squash(s: string, fold: string = E_FOLD): string {
  let out = "";
  for (const ch of s) {
    const cp = ch.codePointAt(0)!;
    if ((cp >= 8592 && cp <= 11263) || (cp >= 65024 && cp <= 65039) ||
      _textPres(cp)) {
      out += "<" + cp.toString(16).toUpperCase() + ">";
    } else out += ch;
  }
  return out.replaceAll("\n", fold).replaceAll("\t", " ").replace(/ +/g, " ");
}

// strptime's own regex for "%Y-%m-%dT%H:%M:%S", which is case-insensitive
// and whose \d is any Unicode digit: "2026-1-5t1:2:3" is a stamp to it.
// Matched at the start only, then held to the whole string, as strptime
// raises "unconverted data remains" on a match that stops short.
const STRPTIME = new RegExp(
  "^(\\p{Nd}\\p{Nd}\\p{Nd}\\p{Nd})-(1[0-2]|0[1-9]|[1-9])" +
  "-(3[01]|[12]\\p{Nd}|0[1-9]|[1-9]| [1-9])" +
  "T(2[0-3]|[0-1]\\p{Nd}|\\p{Nd}):([0-5]\\p{Nd}|\\p{Nd})" +
  ":(6[0-1]|[0-5]\\p{Nd}|\\p{Nd})", "iu");

function daysIn(y: number, m: number): number {
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
}

/** Epoch seconds of a UTC calendar time, for any year 1..9999: Date.UTC
 * reads a year under 100 as 1900 and more. */
function utcEpoch(y: number, mo: number, d: number, h: number, mi: number,
  s: number): number {
  const t = new Date(0);
  t.setUTCFullYear(y, mo - 1, d);
  t.setUTCHours(h, mi, s, 0);
  return t.getTime() / 1000;
}

/** A transcript timestamp as a Unix epoch, or null if it is not one.
 *
 * Transcript stamps are UTC with a trailing "Z"; the fraction is dropped
 * and the Z's stripped, as the Python's strptime dance does.  Not cached:
 * the Python's lru_cache is there for strptime's cost. */
export function tsEpoch(ts: unknown): number | null {
  if (!truthy(ts) || typeof ts !== "string") return null;
  const s = ts.split(".")[0].replace(/Z+$/, "");
  const m = STRPTIME.exec(s);
  if (!m || m[0].length !== s.length) return null;
  const [y, mo, d, h, mi, sec] = m.slice(1).map(
    (g) => parseInt(asciiDigits(g.trim()), 10));
  if (y < 1 || d > daysIn(y, mo) || sec > 59) return null;
  return utcEpoch(y, mo, d, h, mi, sec);
}

/** tsEpoch's inverse: a transcript-shaped UTC stamp, "" for null.  Python
 * rounds the epoch to the microsecond before taking its second. */
export function _stampUtc(epoch: number | null): string {
  if (epoch === null) return "";
  const s = Math.floor(Math.round(epoch * 1e6) / 1e6);
  const t = new Date(s * 1000);
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(t.getUTCFullYear(), 4)}-${p(t.getUTCMonth() + 1)}-` +
    `${p(t.getUTCDate())}T${p(t.getUTCHours())}:${p(t.getUTCMinutes())}:` +
    `${p(t.getUTCSeconds())}.000Z`;
}

/** The four prices of a model: the first MODEL_PRICE row whose key is in
 * its lowercased name, else the "opus" ceiling. */
export function _price(model: unknown): Prices {
  const m = pyStr(or(model, "")).toLowerCase();
  for (const [key, prices] of MODEL_PRICE) {
    if (m.includes(key)) return prices;
  }
  return MODEL_PRICE[0][1];
}
