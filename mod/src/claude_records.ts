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

// ════════════════════════════════════════════════════════════════════════════
// Tool spans and clocks.
// ════════════════════════════════════════════════════════════════════════════

export type Span = readonly [number, number];
/** A tool call asked for and not yet answered: when, and the tool's name. */
export type Pending = Map<string, readonly [number, string]>;

/** The length of the UNION of `spans`, in seconds.
 *
 * Overlapping spans are merged rather than added, which is the whole reason
 * this is not a sum: five agents working the same ten minutes is ten
 * minutes of the session's clock, not fifty. */
export function unionSeconds(spans: readonly Span[]): number {
  let total = 0.0;
  let cur: [number, number] | null = null;
  const sorted = spans.filter((s) => s[1] > s[0]).sort(cmpTuple);
  for (const [lo, hi] of sorted) {
    if (cur === null) cur = [lo, hi];
    else if (lo <= cur[1]) cur[1] = pyMax(cur[1], hi);
    else {
      total += cur[1] - cur[0];
      cur = [lo, hi];
    }
  }
  return total + (cur ? cur[1] - cur[0] : 0.0);
}

// Tools whose result IS the user's answer, so their whole span is a person
// thinking rather than a machine working: taken out of 🔧 and given to 🚦.
// BY NAME, and only by name, because the name is the only thing in the
// transcript that says so; a permission prompt has the same shape and is
// not excluded.
export const BLOCKING_TOOLS: ReadonlySet<string> =
  new Set(["AskUserQuestion", "ExitPlanMode"]);

// Tools whose span is ANOTHER AGENT's work: the thread that called one is
// waiting on the agent, not running a tool, and that agent's time is on its
// own row.  Both names, because Claude Code renamed Task to Agent and older
// transcripts still say Task.
export const DELEGATING_TOOLS: ReadonlySet<string> =
  new Set(["Agent", "Task"]);

// What a thread's 🚦 takes out of its tool spans: a person answering, or
// another agent working.  Neither is this thread's machine doing anything.
export const WAITING_TOOLS: ReadonlySet<string> =
  new Set([...BLOCKING_TOOLS, ...DELEGATING_TOOLS]);

/** Fold one record into a running scan for (start, end) of every tool call.
 *
 * A tool's clock starts on the ASSISTANT record that asked for it and stops
 * on the `tool_result` that answers it, matched by `tool_use_id` — never by
 * adjacency: one assistant record can carry four `tool_use` blocks that run
 * at once and land in any order.  A result whose id names no call it has
 * seen is not counted, which is the right answer for a transcript that was
 * resumed mid-call.
 *
 * `pending` and `out` are the caller's, so one walk of a file can feed this
 * and the billing scan beside it.  `blocked` takes the SUBSET of `out`
 * whose tool is in WAITING_TOOLS — a subset and not a partition, so a
 * reader that wants the machine's tool time subtracts one union from the
 * other; see netToolSeconds. */
export function scanToolSpans(r: Rec, pending: Pending, out: Span[],
  blocked: Span[] | null = null): void {
  const t = tsEpoch(or(get(r, "timestamp"), ""));
  if (t === null) return;
  const blocks = dig(r, "message", "content");
  if (!Array.isArray(blocks)) return;
  for (const b of blocks) {
    if (!isDict(b)) continue;
    const kind = get(b, "type");
    if (kind === "tool_use") {
      if (truthy(get(b, "id"))) {
        pending.set(pyStr(get(b, "id")), [t, pyStr(or(get(b, "name"), ""))]);
      }
    } else if (kind === "tool_result") {
      const id = pyStr(or(get(b, "tool_use_id"), ""));
      const hit = pending.get(id);
      pending.delete(id);
      if (hit !== undefined && t > hit[0]) {
        out.push([hit[0], t]);
        if (blocked !== null && WAITING_TOOLS.has(hit[1])) {
          blocked.push([hit[0], t]);
        }
      }
    }
  }
}

/** Every tool call in `records`, as (start, end).  See scanToolSpans. */
export function toolSpans(records: readonly Rec[],
  blocked: Span[] | null = null): Span[] {
  const pending: Pending = new Map();
  const out: Span[] = [];
  for (const r of records) scanToolSpans(r, pending, out, blocked);
  return out;
}

// The terminal states a TaskOutput reading can report for the task it read.
export const TASK_ENDED: ReadonlySet<unknown> =
  new Set(["completed", "failed", "killed", "stopped"]);

/** The `<task-notification>` a record delivers, or "".
 *
 * An agent's file holds one as a `queued_command` attachment; a thread
 * Claude Code woke with it holds a plain user record whose content is the
 * notification itself. */
export function notificationText(r: Rec): string {
  const a = or(get(r, "attachment"), {});
  let c: unknown = get(a, "type") === "queued_command" ? get(a, "prompt")
    : get(r, "type") === "user" ? dig(r, "message", "content") : null;
  if (Array.isArray(c)) {
    c = c.filter(isDict).map((b) => pyStr(or(get(b, "text"), ""))).join("");
  }
  return typeof c === "string" && c.includes("<task-notification>") ? c : "";
}

const TASK_ID = /<task-id>([^<]+)<\/task-id>/;

/** Fold one record into `open`, {task id: "bash" or "monitor"}, the
 * background tasks a thread started and has not heard the end of.
 *
 * These are what keep an agent that ended its turn alive while it waits:
 * Claude Code parks it on `bash:<id>` or `monitor:<id>` and marks it
 * completed, and the payload carries neither.  A task opens on the tool
 * result that hands back its id — `backgroundTaskId` for a Bash run in the
 * background, `taskId` beside `timeoutMs` for a Monitor.  It closes on a
 * `<task-notification>` for that id that carries a `<status>`, or on the
 * thread ending it itself: TaskStop's result, or TaskOutput reading it
 * finished. */
export function scanBackground(r: Rec, open: Map<string, string>): void {
  const res = get(r, "toolUseResult");
  if (isDict(res)) {
    if (truthy(get(res, "backgroundTaskId"))) {
      open.set(pyStr(get(res, "backgroundTaskId")), "bash");
    } else if (truthy(get(res, "taskId")) && has(res, "timeoutMs")) {
      open.set(pyStr(get(res, "taskId")), "monitor");
    } else if (truthy(get(res, "task_id")) && has(res, "message")) {
      open.delete(pyStr(get(res, "task_id")));
    }
    const task = get(res, "task");
    if (isDict(task) && TASK_ENDED.has(get(task, "status"))) {
      open.delete(pyStr(or(get(task, "task_id"), "")));
    }
  }
  const text = notificationText(r);
  if (text && text.includes("<status>")) {
    const m = TASK_ID.exec(text);
    if (m) open.delete(pyStrip(m[1]));
  }
}

/** Fold one main-transcript record into `ends`, {agent id: the epoch of the
 * latest record saying that agent finished}.
 *
 * A background agent finishes on a `<task-notification>` for its id that
 * carries a `<status>`; a foreground one on the Agent call's result, whose
 * toolUseResult names its agentId beside a terminal status.  The LATEST end
 * is kept, because an agent resumed by SendMessage finishes again. */
export function scanAgentEnd(r: Rec, ends: Map<string, number>): void {
  const res = get(r, "toolUseResult");
  let aid: string;
  if (isDict(res) && truthy(get(res, "agentId")) &&
    TASK_ENDED.has(get(res, "status"))) {
    aid = pyStr(get(res, "agentId"));
  } else {
    const text = notificationText(r);
    const m = text.includes("<status>") ? TASK_ID.exec(text) : null;
    if (!m) return;
    aid = pyStrip(m[1]);
  }
  const t = tsEpoch(or(get(r, "timestamp"), ""));
  if (t !== null && t > (ends.get(aid) ?? -Infinity)) ends.set(aid, t);
}

/** Seconds inside a tool that were not waiting on someone else: a
 * subtraction of two unions, exact because `blocked` is a SUBSET of
 * `spans`. */
export function netToolSeconds(spans: readonly Span[],
  blocked: readonly Span[]): number {
  return pyMax(0.0, unionSeconds(spans) - unionSeconds(blocked));
}

/** Run every tool call still waiting on its result on to `now`.
 *
 * Its seconds are 🔧's — or 🚦's, for a WAITING_TOOLS call — as they
 * happen, and not only once the result lands.  The caller passes a `now`
 * only for a thread that is live: a finished one's unanswered calls were
 * interrupted. */
export function openToolSpans(pending: Pending, now: number, tools: Span[],
  waiting: Span[]): void {
  for (const [t, name] of pending.values()) {
    if (now > t) {
      tools.push([t, now]);
      if (WAITING_TOOLS.has(name)) waiting.push([t, now]);
    }
  }
}

/** One thread's (busy, tool, waiting) seconds, off its OWN file alone.
 *
 *   busy     the union of its work and its tools
 *   tool     its tool spans, less the ones that were waiting
 *   waiting  the waiting spans
 *
 * so that busy - tool - waiting is 🤖, the model thinking, and the age less
 * busy, plus waiting, is 🚦.  Own file alone since 2026-09-27: waiting on
 * an agent is 🚦, and the agent's work is on its row. */
export function threadClock(work: readonly Span[], tools: readonly Span[],
  waiting: readonly Span[]): [number, number, number] {
  return [unionSeconds([...work, ...tools]), netToolSeconds(tools, waiting),
    unionSeconds(waiting)];
}

/** threadClock's 🤖 and 🔧, cut into one (model, tool) pair per cut.
 *
 * Pair i is the time after cut i-1 and up to cut i.  Nothing after the last
 * cut is in any pair: agentRecords cuts an agent's clock at each billed
 * request, so its seconds can be filed under a turn the way its tokens
 * are, and a stretch past the last request is time the NEXT one will bill.
 * `cuts` must be in order.
 *
 * A sweep rather than threadClock per cut: 🤖 is the work spans less the
 * tool spans, and 🔧 the tool spans less the waiting ones, so each stretch
 * between two span ends is one or the other or neither by what is open
 * across it. */
export function splitClock(work: readonly Span[], tools: readonly Span[],
  waiting: readonly Span[], cuts: readonly number[]): [number, number][] {
  const out: [number, number][] = cuts.map(() => [0.0, 0.0]);
  if (cuts.length === 0) return [];
  const ev: [number, number, number][] = [];
  [work, tools, waiting].forEach((spans, k) => {
    for (const [lo, hi] of spans) {
      if (hi > lo) ev.push([lo, k, 1], [hi, k, -1]);
    }
  });
  ev.sort(cmpTuple);
  const live = [0, 0, 0];
  let prev: number | null = null;
  let j = 0;
  for (const [t, k, d] of ev) {
    let lo = prev !== null ? prev : t;
    while (lo < t) {
      while (j < cuts.length - 1 && cuts[j] <= lo) j++;
      if (cuts[j] <= lo) break;
      const hi = pyMin(t, cuts[j]);
      if (live[1] && !live[2]) out[j][1] += hi - lo;
      else if (live[0] && !live[1]) out[j][0] += hi - lo;
      lo = hi;
    }
    live[k] += d;
    prev = t;
  }
  return out;
}

/** One turn's (tool, waiting) seconds: threadClock's two, over its span,
 * clipped to [t0, t1] because the turn's own span is what durS measures. */
export function turnClock(tools: readonly Span[], waiting: readonly Span[],
  t0: number | null, t1: number | null): [number, number] {
  if (t0 === null || t1 === null || t1 <= t0) return [0.0, 0.0];
  const clip = (spans: readonly Span[]): Span[] =>
    spans.map(([lo, hi]) => [pyMax(lo, t0), pyMin(hi, t1)]);
  const tc = clip(tools), wc = clip(waiting);
  return [netToolSeconds(tc, wc), unionSeconds(wc)];
}

/** The receipt's ⌛🤖: the turn's span less its tool and waiting seconds,
 * clamped at zero. */
export function turnModelS(t: Turn): number {
  return pyMax(0.0, t.durS - t.toolS - t.blockedS);
}

/** The receipt's ⌛🤖 and 🔧 for a row: the main thread's, plus its
 * agents', which are agent-seconds and can outrun the turn. */
export function turnTimes(t: Turn): [number, number] {
  return [turnModelS(t) + t.agentModelS, t.toolS + t.agentToolS];
}

// ════════════════════════════════════════════════════════════════════════════
// ETA reports.
// ════════════════════════════════════════════════════════════════════════════

// The skill that has an agent report its ETA, and the line it has it write:
//
//     ⛳ skills/coding-agent-usage-line-report-eta: ETA 4m
//
// The skill's path is the part matched; the flag may be missing, and the 🏁
// the skill had it write before ⛳ is read as well.  Backticks and bold
// around the line are forgiven.  A run of figure-and-unit pairs (`6h30m`)
// is one figure, and a few words after a dash are not read.
//
// The Python compiles this with re.MULTILINE, whose ^ and $ are at a "\n"
// alone; JavaScript's m flag also breaks at "\r", U+2028 and U+2029, so the
// line ends are spelt out as lookarounds instead.  \d is Unicode's, as the
// Python's is.
export const ETA_SKILL = "coding-agent-usage-line-report-eta";
export const ETA_PART = String.raw`\p{Nd}+(?:\.\p{Nd}+)? ?[smh]`;
export const ETA_LINE = new RegExp(
  String.raw`(?<![^\n])[ \t\x60*]*(?:[${E_ETA_REPORT}${E_ETA_REPORT_OLD}]` +
  String.raw`[ \t]*)?skills/${ETA_SKILL}: ETA (${ETA_PART}` +
  String.raw`(?:[ \t]*${ETA_PART})*)(?:[ \t]+[—–\-][ \t]` +
  String.raw`[^\n]*?)?[ \t\x60*]*(?![^\n])`, "gu");
export const ETA_SPLIT = /(\p{Nd}+(?:\.\p{Nd}+)?) ?([smh])/gu;
export const ETA_UNIT_S: Readonly<Record<string, number>> =
  { s: 1.0, m: 60.0, h: 3600.0 };

/** (epoch, seconds left) off the LAST ETA report in `records`, or [].
 *
 * Only what the agent itself wrote counts: the text blocks of assistant
 * records.  A tool result that quotes the line, or the skill's text
 * arriving as a user message, is not a report.  The epoch is the record's
 * own stamp, which is what lets the row count the estimate down between
 * reports. */
export function etaReport(records: readonly unknown[]): number[] {
  let last: number[] = [];
  for (const r of records) {
    if (!isDict(r) || get(r, "type") !== "assistant") continue;
    const content = dig(r, "message", "content");
    if (!Array.isArray(content)) continue;
    for (const block of content) {
      if (!isDict(block) || get(block, "type") !== "text") continue;
      const hits = [...pyStr(or(get(block, "text"), "")).matchAll(ETA_LINE)]
        .map((m) => m[1]);
      const epoch = tsEpoch(or(get(r, "timestamp"), ""));
      if (hits.length && epoch !== null) {
        let secs = 0;
        for (const [, n, unit] of hits[hits.length - 1].matchAll(ETA_SPLIT)) {
          secs += parseFloat(asciiDigits(n)) * ETA_UNIT_S[unit];
        }
        last = [epoch, secs];
      }
    }
  }
  return last;
}

/** When an ETA says its run ends: the report's epoch plus the time it said
 * was left.  null only for no report.  A report of zero is the skill's
 * sign-off, and says the run ends at the report. */
export function etaFinish(eta: readonly number[]): number | null {
  if (eta.length === 0) return null;
  return eta[0] + eta[1];
}

/** True for an assistant record that ends its answer. */
export function endsTurn(r: Rec): boolean {
  return get(r, "type") === "assistant" &&
    dig(r, "message", "stop_reason") === "end_turn";
}

/** liveEta's state for one thread: the report, whether the answer is done,
 * the last epoch, and the report's message id. */
export type EtaState = [number[], boolean, number | null, unknown];

/** A fresh `state` for liveEta: no report, not done, no stamp, no
 * message. */
export function newEtaState(): EtaState {
  return [[], false, null, null];
}

/** Fold one record into `state`, [eta, done, last epoch, report's message
 * id], for one thread.
 *
 * The ETA belongs to the answer it was written in: a new prompt clears it,
 * and so does the answer finishing — an assistant record that ends its
 * turn, with no work after it.
 *
 * Unless the message that ends the turn is the one that carries the
 * report.  That is an agent PARKING rather than finishing: it has ended
 * its turn to wait on a background task, and says in the same breath how
 * long it expects the rest to take.  A 0s in the message that ends the
 * turn is finishing, not parking; and one that ends without a line in its
 * last message reads as finished too.  A message is split over several
 * records, one per block, so the test is on the message id. */
export function liveEta(r: Rec, state: EtaState): void {
  if (turnStartText(r) !== null) {
    state[0] = [];
    state[1] = false;
    state[3] = null;
  } else if (isWork(r)) {
    const report = etaReport([r]);
    const mid = dig(r, "message", "id") ?? null;
    if (report.length) {
      state[0] = report;
      state[3] = mid;
    }
    const parked = state[0].length > 0 && state[0][1] > 0 &&
      (report.length > 0 || (mid !== null && mid === state[3]));
    state[1] = endsTurn(r) && !parked;
  }
  const t = tsEpoch(or(get(r, "timestamp"), ""));
  if (t !== null) state[2] = t;
}

/** agentSpan's state: when the open span opened, and its last work. */
export type SpanState = [number | null, number | null];

/** Fold one record of an AGENT's file into its working spans.
 *
 * `state` is [opened at, last work], both null between spans; a span is
 * appended to `spans` as it closes, and the caller closes the last one —
 * see closeAgentSpan.  An agent's resumptions are not prompts, so an answer
 * that ENDS its turn closes the span, and whatever comes next opens the
 * following one; a prompt still closes and reopens it. */
export function agentSpan(r: Rec, state: SpanState, spans: Span[]): void {
  const t = tsEpoch(or(get(r, "timestamp"), ""));
  if (t === null) return;
  if (state[0] !== null && turnStartText(r) !== null) {
    closeAgentSpan(state, spans);
  }
  if (state[0] === null) {
    const type = get(r, "type");
    if (type !== "user" && type !== "assistant") return;
    state[0] = state[1] = t;
  } else if (isWork(r)) {
    state[1] = pyMax(state[1]!, t);
  }
  if (endsTurn(r)) closeAgentSpan(state, spans);
}

/** Append agentSpan's open span, if it has any length, and clear it. */
export function closeAgentSpan(state: SpanState, spans: Span[]): void {
  if (state[0] !== null && state[1]! > state[0]) {
    spans.push([state[0], state[1]!]);
  }
  state[0] = state[1] = null;
}

// ════════════════════════════════════════════════════════════════════════════
// Turn boundaries.
// ════════════════════════════════════════════════════════════════════════════

/** True for a record that OPENS a turn — the unit the cost line reports.
 *
 * A prompt the user typed is one.  A message DELIVERED to an idle session,
 * which Claude Code writes as `type: user` with `promptSource: "system"`,
 * is the other: a task notification, a message from another session, an
 * idle notice, the usage limit resetting.  The session answers each of
 * them as it answers a typed prompt, and bills it the same way.
 *
 * Excluded: isCompactSummary; strings opening with '<' on the typed
 * branch (tool results, system reminders); isMeta on a typed record; and
 * promptSource "queued", whose boundary is the queue's own removal record —
 * see queuedText.  An absent promptSource counts as typed, so transcripts
 * from before the field still segment.  The Python's docstring has the
 * measurements. */
export function opensTurn(r: Rec): boolean {
  const c = dig(r, "message", "content");
  if (get(r, "type") !== "user" || get(r, "userType") !== "external" ||
    truthy(get(r, "isCompactSummary")) || typeof c !== "string" ||
    c.length === 0) {
    return false;
  }
  if (get(r, "promptSource") === "system") return true;
  const source = has(r, "promptSource") ? get(r, "promptSource") : "typed";
  return !truthy(get(r, "isMeta")) && source === "typed" &&
    !c.startsWith("<");
}

// Every enqueue is matched by exactly one of these, so a removal is a
// delivery, not a cancellation: the queue draining one item, draining all
// of them, and the item being taken off the front.
export const QUEUE_DELIVERED: readonly unknown[] =
  ["remove", "dequeue", "popAll"];

/** The prompt a `queue-operation` record delivered, or null.
 *
 * A message typed while the assistant is working gets no `type: user`
 * record, only an enqueue when it was typed and a removal when it was
 * handed to the model.  The removal is the boundary: the enqueue is stamped
 * when the message was TYPED, which can be minutes before the assistant was
 * free to read it.  Typed-only: machinery riding the same queue opens with
 * '<', and is refused. */
export function queuedText(r: Rec): string | null {
  if (get(r, "type") !== "queue-operation") return null;
  if (!QUEUE_DELIVERED.includes(get(r, "operation"))) return null;
  const c = get(r, "content");
  return typeof c === "string" && c.length > 0 && !c.startsWith("<")
    ? c : null;
}

/** +1 for a message put on this thread's queue, -1 for one handed over.
 * The running sum, never below zero, is how many messages are waiting for
 * the thread's next turn. */
export function queueStep(r: Rec): number {
  if (get(r, "type") !== "queue-operation") return 0;
  const op = get(r, "operation");
  return op === "enqueue" ? 1 : QUEUE_DELIVERED.includes(op) ? -1 : 0;
}

// What postTokens leaves out of a reading, when the transcript has no
// reading before its compaction to take it from: the median over 520 local
// compactions on 2026-10-16.  See the 🧠 estimate in transcriptOf.
export const COMPACT_OVERHEAD = 46000;

/** True for the marker a compaction writes, /compact's or the automatic
 * one's: `type: system`, `subtype: compact_boundary`. */
export function isCompaction(r: Rec): boolean {
  return get(r, "type") === "system" &&
    get(r, "subtype") === "compact_boundary";
}

/** The text of the prompt this record opens, or null if it opens none. */
export function turnStartText(r: Rec): string | null {
  if (opensTurn(r)) return dig(r, "message", "content") as string;
  return queuedText(r);
}

/** True for a record written while the assistant was answering.
 *
 * A turn ends at the last record the ANSWER produced, and the transcript
 * keeps appending after that: slash-command caveats, the enqueue stamped
 * when the user typed, the compact summary.  Tool results have to stay IN:
 * they arrive as `type: user` with a LIST of blocks, where a person's
 * message is always a plain string. */
export function isWork(r: Rec): boolean {
  const t = get(r, "type");
  if (t === "assistant" || t === "system") return true;
  if (t === "user") return Array.isArray(dig(r, "message", "content"));
  return false;
}

// ════════════════════════════════════════════════════════════════════════════
// Agent files.
// ════════════════════════════════════════════════════════════════════════════

/** Where Claude Code keeps this session's agent transcripts.
 *
 * `<project>/<sid>.jsonl` is the session; `<project>/<sid>/subagents/` is
 * everything it spawned.  "" for a path that is not a transcript at all. */
export function _agentDir(transcript: string): string {
  if (!transcript.endsWith(".jsonl")) return "";
  return pyJoin(transcript.slice(0, -".jsonl".length), "subagents");
}

const AGENT_NAME = /^agent-.*\.jsonl$/s;

/** Every agent transcript of this session, sorted so the walk is stable.
 *
 * Two depths and no others, measured over 2,134 files on 2026-09-11:
 * `subagents/agent-<id>.jsonl` for the Agent tool, forks, and agents that
 * agents spawned; `subagents/workflows/wf_<id>/agent-<id>.jsonl` for a
 * workflow's agents.  The workflow's `journal.jsonl` carries no usage and
 * is not matched.  Walked as the Python's recursive glob walks: hidden
 * names are skipped, and a directory is entered through a symlink. */
export function agentFiles(transcript: string): string[] {
  const d = _agentDir(transcript);
  if (!d || !isDir(d)) return [];
  const out: string[] = [];
  const walk = (dir: string): void => {
    let names: string[];
    try {
      names = fs.readdirSync(dir);
    } catch {
      return;
    }
    for (const name of names) {
      if (name.startsWith(".")) continue;
      const p = pyJoin(dir, name);
      if (AGENT_NAME.test(name)) out.push(p);
      if (isDir(p)) walk(p);
    }
  };
  walk(d);
  return out.sort(cmpStr);
}

function isDir(p: string): boolean {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

/** One record of an agent file that carries usage, as _readAgentFile keeps
 * it: (epoch, promptId, model, fresh, cache write, cache read, out,
 * requestId, offset). */
export type AgentRaw = readonly [number | null, unknown, unknown, number,
  number, number, number, unknown, number];

/** One agent file's part of agentRecords, read from it alone. */
export interface AgentReading {
  readonly recs: readonly AgentRaw[];
  readonly work: readonly Span[];
  readonly tools: readonly Span[];
  readonly waiting: readonly Span[];
  readonly eta: readonly [number | null, number | null] | null;
}

/** Every billed request an agent of this session made, in stamp order.
 *
 * Nothing an agent bills is in the session's own transcript; it is in the
 * files agentFiles lists, and every reader that adds up a transcript reads
 * these as well, or it is reading the main thread and calling it the
 * session.
 *
 * WHICH TURN each record belongs to is the `promptId` of the
 * main-transcript turn that spawned the agent, carried on the agent's USER
 * records and carried forward record by record, because an agent a later
 * turn resumed gets a second one.  Skipped: records whose usage is all
 * zero, the `<synthetic>` API-error placeholders.  Deduped first-wins on
 * requestId across every file together, and against the main transcript
 * when the caller passes its `seen` set.
 *
 * `offset` is the byte position after the record's own line: what the Stop
 * hook stores to say "I have reported everything up to here", in bytes
 * because files that flush on their own schedules share no clock.  Each
 * record carries the agent's 🤖 and 🔧 since the one before it, by
 * splitClock; a record deduped away hands its time on to the next one this
 * file keeps.  `etas` is an out-parameter: for every agent still answering
 * with a live ETA, (finish epoch, its last record's epoch).
 *
 * The pure core: `files` is each agent file with its reading, as
 * _agentFileReadings gives them. */
export function agentRecordsOf(
  files: readonly (readonly [string, AgentReading])[],
  seen: Set<unknown> | null = null,
  etas: (readonly [number | null, number | null])[] | null = null,
): AgentRec[] {
  seen = seen ?? new Set();
  const out: AgentRec[] = [];
  for (const [path, got] of files) {
    const first = out.length;
    for (const [epoch, pid, model, fresh, cw, cr, o, k, pos] of got.recs) {
      if (seen.has(k)) continue;
      seen.add(k);
      if (!(truthy(fresh) || truthy(cw) || truthy(cr) || truthy(o))) continue;
      out.push({ epoch, promptId: pid, model, fresh, cacheWrite: cw,
        cacheRead: cr, out: o, requestId: k, path, offset: pos,
        modelS: 0.0, toolS: 0.0 });
    }
    if (etas !== null && got.eta !== null) etas.push([...got.eta]);
    const cuts: number[] = [];
    let cut = -Infinity;
    for (const a of out.slice(first)) {
      cut = a.epoch !== null ? pyMax(cut, a.epoch) : cut;
      cuts.push(cut);
    }
    splitClock(got.work, got.tools, got.waiting, cuts).forEach(([m, tl], i) => {
      out[first + i] = { ...out[first + i], modelS: m, toolS: tl };
    });
  }
  // Stamp order across files, unparseable stamps last: the fold-in walks
  // turns forward and a record that cannot be placed in time is handed to
  // the last turn rather than the first.
  const key = (a: AgentRec): [number, number] =>
    [a.epoch === null ? 1 : 0, or(a.epoch, 0.0) as number];
  return out.sort((a, b) => cmpTuple(key(a), key(b)));
}

/** agentRecordsOf over this session's agent files, read here; see
 * _agentFileReadings for `cache`. */
export function agentRecords(transcript: string,
  seen: Set<unknown> | null = null,
  etas: (readonly [number | null, number | null])[] | null = null,
  cache: AgentCache | null = null): AgentRec[] {
  return agentRecordsOf(_agentFileReadings(transcript, cache), seen, etas);
}

/** Split `data` into lines as a binary file iterates: each up to and
 * including its "\n", the last one without. */
function* byteLines(data: Uint8Array): Generator<Uint8Array> {
  let s = 0;
  while (s < data.length) {
    let e = data.indexOf(10, s);
    e = e < 0 ? data.length : e + 1;
    yield data.subarray(s, e);
    s = e;
  }
}

/** One agent file's part of agentRecords, from its bytes alone.
 *
 * Everything here depends on this file's bytes and nothing else, which is
 * what lets _agentFileReadings keep it from one render to the next.  So it
 * stops short of the two steps that look across files: `recs` holds every
 * record that carries usage, zero bills and repeated requestIds included,
 * and agentRecordsOf dedupes them and cuts the clock at the ones it keeps.
 * `work`, `tools` and `waiting` are that clock's spans, and `eta` is the
 * file's live ETA, or null.  A line that is not UTF-8 is skipped, as
 * json.loads skips it when handed bytes. */
export function _readAgentBytes(data: Uint8Array): AgentReading {
  let pid: unknown = "";
  const etaState = newEtaState();
  const spanState: SpanState = [null, null];
  const work: Span[] = [];
  const pending: Pending = new Map();
  const tools: Span[] = [], waiting: Span[] = [];
  const recs: AgentRaw[] = [];
  let pos = 0;
  for (const line of byteLines(data)) {
    pos += line.length;
    let r: unknown;
    try {
      r = JSON.parse(DECODE_STRICT.decode(line));
    } catch {
      continue;
    }
    if (!isDict(r)) continue;
    liveEta(r, etaState);
    agentSpan(r, spanState, work);
    scanToolSpans(r, pending, tools, waiting);
    if (get(r, "type") === "user") {
      pid = or(get(r, "promptId"), pid);
      continue;
    }
    if (get(r, "type") !== "assistant") continue;
    const m = or(get(r, "message"), {});
    const u = get(m, "usage");
    if (!truthy(u)) continue;
    recs.push([tsEpoch(or(get(r, "timestamp"), "")), pid, get(m, "model") ??
      null, num0(get(u, "input_tokens")),
      num0(get(u, "cache_creation_input_tokens")),
      num0(get(u, "cache_read_input_tokens")), num0(get(u, "output_tokens")),
      or(or(get(r, "requestId"), get(m, "id")), "?"), pos]);
  }
  closeAgentSpan(spanState, work);
  let eta: [number | null, number | null] | null = null;
  if (etaState[0].length && !etaState[1]) {
    eta = [etaFinish(etaState[0]), etaState[2]];
  }
  return { recs, work, tools, waiting, eta };
}

/** _readAgentBytes off the file, or null for a file that will not open. */
export function _readAgentFile(path: string): AgentReading | null {
  try {
    return _readAgentBytes(fs.readFileSync(path));
  } catch {
    return null;
  }
}

// A file last written this long ago is SETTLED, and only a settled file's
// reading is kept.  Size and mtime are the whole test for a kept reading
// being current, and a file rewritten within the clock's granularity can
// come back the same size with the same stamp.  A live agent's file is
// never settled while it runs, and is read afresh.
export const AGENT_CACHE_SETTLE_S = 2.0;

/** Where _agentFileReadings keeps its readings: a state directory, a
 * version that a kept reading must match, and the clock that says which
 * files have settled.  The Python keys its cache by a digest of its own
 * source; the mod passes its version, and its file is named apart, so the
 * two never serve each other a reading. */
export interface AgentCache {
  readonly stateDir: string;
  readonly version: string;
  readonly now: number;
}

/** Where the TypeScript keeps its readings of this session's agent files.
 * Not .json: the usage caches are every .json in the directory. */
export function _agentCachePath(transcript: string, stateDir: string): string {
  let sid = pyBasename(transcript);
  if (sid.endsWith(".jsonl")) sid = sid.slice(0, -".jsonl".length);
  const digest = crypto.createHash("sha256")
    .update("claude-agent-files-ts\0" + sid, "utf8").digest("hex");
  return pyJoin(stateDir, "claude-agent-files-ts-" + digest + ".cache");
}

type Kept = AgentReading & { readonly stamp: readonly [number, string] };

/** _readAgentFile for every agent file, in agentFiles' order, from the
 * cache where a file has not changed since it was kept.
 *
 * Without it, every render parsed every agent file the session ever ran: a
 * session with 611 of them, 768 MB, took six seconds a render.  A finished
 * agent's file never changes, so a render reads only the files that grew.
 * A reading is current while the file's size and mtime match the ones
 * stamped when it was read.  The cache is written back only when a reading
 * was added or a file went away.  With no `cache`, every file is read. */
export function _agentFileReadings(transcript: string,
  cache: AgentCache | null = null): [string, AgentReading][] {
  const paths = agentFiles(transcript);
  if (paths.length === 0) return [];
  const cpath = cache ? _agentCachePath(transcript, cache.stateDir) : "";
  let kept: Record<string, Kept> = {};
  if (cache) {
    try {
      const d = JSON.parse(fs.readFileSync(cpath, "utf-8"));
      if (isDict(d) && d.version === cache.version) {
        kept = (or(d.files, {}) as Record<string, Kept>);
      }
    } catch {
      // No cache yet, or one that will not parse: read everything.
    }
  }
  const settled = cache ? cache.now - AGENT_CACHE_SETTLE_S : 0;
  const out: [string, AgentReading][] = [];
  const keep: Record<string, Kept> = {};
  let dirty = false;
  for (const path of paths) {
    let st: fs.BigIntStats;
    try {
      st = fs.statSync(path, { bigint: true });
    } catch {
      continue;
    }
    const stamp: [number, string] = [Number(st.size), String(st.mtimeNs)];
    let got: AgentReading | null = Object.hasOwn(kept, path)
      ? kept[path] : null;
    if (isDict(got) && recordEqual((got as Kept).stamp, stamp)) {
      const { recs, work, tools, waiting, eta } = got;
      got = { recs, work, tools, waiting, eta };
      keep[path] = kept[path];
    } else {
      // Stamped before the read: a file that grows during it comes back
      // with a newer stamp next time, and is read again.
      got = _readAgentFile(path);
      if (got === null) continue;
      if (cache && Number(st.mtimeNs) / 1e9 < settled) {
        keep[path] = { ...got, stamp };
        dirty = true;
      }
    }
    out.push([path, got]);
  }
  const same = (a: object, b: object) =>
    recordEqual(Object.keys(a).sort(), Object.keys(b).sort());
  if (cache && (dirty || !same(kept, keep))) {
    writeAtomic(cpath, JSON.stringify({ version: cache.version,
      files: keep }));
  }
  return out;
}

/** Write `text` to `path` through a temporary file renamed over it, private
 * to the user, as the Python does; a failure leaves the old file. */
function writeAtomic(path: string, text: string): void {
  const tmp = `${path}.${process.pid}`;
  try {
    fs.mkdirSync(path.slice(0, path.lastIndexOf("/")) || "/",
      { recursive: true, mode: 0o700 });
    fs.writeFileSync(tmp, text);
    fs.chmodSync(tmp, 0o600);
    fs.renameSync(tmp, path);
  } catch {
    // Unwritable state is a slower next render, not a failure.
  }
}

/** Where the Stop hook records how far into each agent file it reported.
 *
 * Per session, in private application state.  A one-way digest keeps a raw
 * transcript/session id out of the path.  The same file the Python's Stop
 * hook writes, so the two report each record once between them. */
export function _agentStatePath(transcript: string, stateDir: string): string {
  let sid = pyBasename(transcript);
  if (sid.endsWith(".jsonl")) sid = sid.slice(0, -".jsonl".length);
  const digest = crypto.createHash("sha256")
    .update("claude-agent-offsets\0" + sid, "utf8").digest("hex");
  return pyJoin(stateDir, "claude-agent-offsets-" + digest + ".json");
}

/** The byte offset the last Stop reported each agent file up to, or null
 * when no Stop has written one for this session.  See _foldAgents for what
 * the distinction buys.  A value must be an int, and Python's bool is one. */
export function agentOffsets(transcript: string,
  stateDir: string): Map<string, number> | null {
  let d: unknown;
  try {
    d = JSON.parse(fs.readFileSync(_agentStatePath(transcript, stateDir),
      "utf-8"));
  } catch {
    return null;
  }
  if (!isDict(d)) return null;
  const out = new Map<string, number>();
  for (const [k, v] of Object.entries(d)) {
    if (typeof v === "boolean") out.set(k, v ? 1 : 0);
    else if (typeof v === "number" && Number.isInteger(v)) out.set(k, v);
  }
  return out;
}

/** Record, after a Stop has rendered, how far into each agent file the
 * records it folded in reached.
 *
 * Written from the records themselves rather than from the files' sizes,
 * so that what is stored is exactly what was reported.  Files with no
 * billed record yet are absent, and absent reads as 0.  `held` is what
 * readTurns held back from a still-running agent, {path: the first such
 * record's offset}: the extent stops short of them. */
export function publishAgentOffsets(transcript: string,
  agents: readonly AgentRec[], held: ReadonlyMap<string, number> | null,
  stateDir: string): void {
  held = held ?? new Map();
  const ext = new Map<string, number>();
  for (const a of agents) {
    if (a.offset >= (held.get(a.path) ?? a.offset + 1)) continue;
    if (a.offset > (ext.get(a.path) ?? 0)) ext.set(a.path, a.offset);
  }
  writeAtomic(_agentStatePath(transcript, stateDir), pyJsonDumps(ext));
}

/** The id off an agent file's `agent-<id>.jsonl`, else "". */
export function agentLabelId(path: string): string {
  const base = pyBasename(path);
  return base.startsWith("agent-") && base.endsWith(".jsonl") &&
    base.length >= "agent-".length + ".jsonl".length
    ? base.slice("agent-".length, -".jsonl".length) : "";
}

/** An agent file's id and name: the id off `agent-<id>.jsonl`, and the
 * description its `.meta.json` sidecar gives, else its agentType, else
 * "". */
export function agentLabel(path: string): [string, string] {
  const aid = agentLabelId(path);
  let name = "";
  try {
    const meta: unknown = JSON.parse(DECODE_FATAL_BOM.decode(
      fs.readFileSync(path.slice(0, -".jsonl".length) + ".meta.json")));
    if (isDict(meta)) {
      name = pyStr(or(or(get(meta, "description"), get(meta, "agentType")),
        ""));
    }
  } catch {
    // No sidecar, or one that will not parse: the id alone.
  }
  return [aid, name];
}

// Decoding as open(encoding="utf-8") does: a bad byte raises, and a BOM is
// kept, for json.load to refuse.
const DECODE_FATAL_BOM = new TextDecoder("utf-8",
  { fatal: true, ignoreBOM: true });

// ════════════════════════════════════════════════════════════════════════════
// The inbox.
// ════════════════════════════════════════════════════════════════════════════

// What SendMessage answers when the agent it names is busy: the message
// waits in that agent's inbox until its next tool round, and Claude Code's
// panel counts it on the agent's row as "1 queued".  The payload the panel
// hands the subagent status line carries no such count, so inboxCounts
// rebuilds it from the two ends.  \S is Python's, the complement of
// PY_SPACE.
export const SEND_QUEUED_RE = new RegExp(
  `queued for delivery to ([^${PY_SPACE}]+) at its next tool round`, "u");
export const SEND_QUEUED_MARK = new TextEncoder()
  .encode("queued for delivery to");
// The origins inboxDelivery counts: tighter than `"queued_command"`, which
// every task notification carries too, and the value alone, so the search
// holds whether or not the JSON is spaced.
export const INBOX_MARKS: readonly Uint8Array[] =
  ['"coordinator"', '"peer"'].map((m) => new TextEncoder().encode(m));

/** The agent id a SendMessage result says its message is waiting for, or
 * "". */
export function queuedSend(r: Rec): string {
  const res = get(r, "toolUseResult");
  const msg = isDict(res) ? get(res, "message") : null;
  const m = typeof msg === "string" ? SEND_QUEUED_RE.exec(msg) : null;
  return m ? m[1] : "";
}

/** True for a SendMessage delivery taken off this agent's inbox.
 *
 * Written in the agent's own file as a `queued_command` attachment or a
 * `type: user` record, whose `origin` says who sent it: `coordinator` for
 * the main thread and `peer` for another agent.  A peer message marked
 * `handback` is a subagent's final report, not a send. */
export function inboxDelivery(r: Rec): boolean {
  const a = get(r, "attachment");
  let o: unknown;
  if (isDict(a) && get(a, "type") === "queued_command") o = get(a, "origin");
  else if (get(r, "type") === "user") o = get(r, "origin");
  else return false;
  if (!isDict(o)) return false;
  const kind = get(o, "kind");
  return kind === "coordinator" ||
    (kind === "peer" && !truthy(get(o, "handback")));
}

/** Where `mark` next occurs in `data` at or after `from`, else -1. */
function findBytes(data: Uint8Array, mark: Uint8Array, from: number): number {
  return Buffer.from(data.buffer, data.byteOffset, data.byteLength)
    .indexOf(mark, from);
}

/** Parse only the lines of `data` that hold one of `marks`, in file order.
 *
 * For a scan of the main transcript on every panel tick, where _records
 * would parse a file that can run to 200MB to find a handful of lines: a
 * byte search finds them in a fifth of a second.  A line that will not
 * parse is skipped, as _records skips it. */
export function markedRecordsOf(data: Uint8Array,
  marks: readonly Uint8Array[]): Rec[] {
  const starts = new Set<number>();
  for (const mark of marks) {
    let i = findBytes(data, mark, 0);
    while (i >= 0) {
      starts.add(i > 0 ? data.lastIndexOf(10, i - 1) + 1 : 0);
      const e = data.indexOf(10, i);
      i = e >= 0 ? findBytes(data, mark, e) : -1;
    }
  }
  const out: Rec[] = [];
  for (const s of [...starts].sort((a, b) => a - b)) {
    const e = data.indexOf(10, s);
    try {
      const r: unknown = JSON.parse(DECODE_REPLACE.decode(
        data.subarray(s, e >= 0 ? e : data.length)));
      if (isDict(r)) out.push(r);
    } catch {
      continue;
    }
  }
  return out;
}

/** markedRecordsOf over the file at `path`; [] if it will not open. */
export function markedRecords(path: string,
  marks: readonly Uint8Array[]): Rec[] {
  try {
    return markedRecordsOf(fs.readFileSync(path), marks);
  } catch {
    return [];
  }
}

/** (epoch, target id) for each message this file queued for an agent. */
export function inboxSends(path: string): [number, string][] {
  const out: [number, string][] = [];
  for (const r of markedRecords(path, [SEND_QUEUED_MARK])) {
    const t = tsEpoch(or(get(r, "timestamp"), "")), target = queuedSend(r);
    if (t !== null && target) out.push([t, target]);
  }
  return out;
}

/** The epoch of each SendMessage delivery in this agent's file. */
export function inboxDeliveries(path: string): number[] {
  return markedRecords(path, INBOX_MARKS).filter(inboxDelivery)
    .map((r) => tsEpoch(or(get(r, "timestamp"), "")))
    .filter((t): t is number => t !== null);
}

/** How many messages wait in each agent's inbox: {agent id: count}.
 *
 * `files` is every transcript that can send — the main thread's and each
 * agent's — and `targets` maps each agent on the panel to its own file.
 * The two ends are matched by time, not by text: a send raises the count,
 * a delivery lowers it, and the count never goes below zero.  `since`, the
 * earliest any target started, skips every file last written before it. */
export function inboxCounts(files: readonly string[],
  targets: ReadonlyMap<string, string>,
  since: number | null = null): Map<string, number> {
  const sent = new Map<string, number[]>();
  for (const f of files) {
    try {
      if (since !== null &&
        Number(fs.statSync(f, { bigint: true }).mtimeNs) / 1e9 < since) {
        continue;
      }
    } catch {
      continue;
    }
    for (const [t, target] of inboxSends(f)) {
      if (targets.has(target)) {
        if (!sent.has(target)) sent.set(target, []);
        sent.get(target)!.push(t);
      }
    }
  }
  const out = new Map<string, number>();
  for (const [aid, times] of sent) {
    // A send and its delivery stamped alike: the send first.
    const events: [number, number, number][] = [
      ...times.map((t): [number, number, number] => [t, 0, 1]),
      ...inboxDeliveries(targets.get(aid)!)
        .map((t): [number, number, number] => [t, 1, -1])];
    events.sort(cmpTuple);
    let n = 0;
    for (const [, , step] of events) n = Math.max(0, n + step);
    if (n) out.set(aid, n);
  }
  return out;
}
