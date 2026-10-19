// Claude payload records and transcript/accounting parser.
//
// The port of claude_records.py, function for function under the same names
// in camelCase; a record's fields keep the Python's snake_case names, as
// claude_sources.ts's do, so a record reads the same in both and the shared
// cases compare it as it is.  It owns Claude-specific JSONL interpretation and price
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
//     JavaScript does not, so every such test goes through py.ts's
//     `pyTruthy` and `pyOr`.
//   - Missing is null, never undefined and never zero.  `pyGet` returns
//     null for an absent key, as `d.get("k")` does, and `pyHas` is `"k" in
//     d` where the Python tells the two apart.
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

import { sha256Hex } from "./sha256.ts";
import { E_FOLD, E_ETA_REPORT, E_ETA_REPORT_OLD } from "./spec.ts";
import {
  daysIn, isDict, PY_SPACE, pyAsciiDigits, pyDig, pyFloatRepr, pyGet, pyHas,
  pyLen, pyOr, pyStrip, pyTruthy,
  utf8,
} from "./py.ts";

// ════════════════════════════════════════════════════════════════════════════
// Python's semantics, where JavaScript's differ.
// ════════════════════════════════════════════════════════════════════════════

/** A parsed JSON object, the shape every record is read as. */
export type Rec = { readonly [k: string]: unknown };

/** A number field read `u.get(k) or 0`. */
function num0(v: unknown): number {
  return typeof v === "number" && pyTruthy(v) ? v : 0;
}

/** A number field read `u.get(k, 0)`: present and null is the Python's
 * TypeError, read here as 0. */
function numGet(d: unknown, k: string): number {
  const v = pyGet(d, k);
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
export function cmpTuple(a: readonly number[], b: readonly number[]): number {
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
  readonly current_dir: string;
  readonly project_dir: string;
  readonly model: string;
  readonly model_id: string;
  readonly ctx_window: string;      // context_window.context_window_size
  readonly transcript: string;
  readonly cost_usd: string;
  readonly lines_added: string;
  readonly lines_removed: string;
  readonly output_style: string;
  readonly effort: string;
  readonly session_id: string;
  readonly rl_session_pct: string;
  readonly rl_session_reset: string;
  readonly rl_weekly_pct: string;
  readonly rl_weekly_reset: string;
  readonly pr_number: string;
}

/** What one pass over the transcript yields for the status line.
 *
 * `tok_up` is null only when there was no transcript to read at all, which
 * is a different state from a transcript that exists and is empty: the
 * first suppresses the token segment, the second renders it as zeros.  Two
 * empty states, two renderings, and conflating them was how a fresh session
 * grew a "▴0 ▾0" that looked like a stall.  The fields are documented on
 * the Python's Transcript, field for field. */
export interface Transcript {
  readonly tok_up: number | null;
  readonly tok_down: number;
  readonly cache_pct: number;       // -1 when there is no usage data at all
  readonly ctx_tokens: number;
  readonly user_ts: string;
  readonly user_text: string;
  readonly asst_ts: string;
  readonly asst_text: string;
  readonly busy_s: number;          // this thread's answering; thread_clock
  readonly start_s: number;         // epoch of the first STAMPED record
  readonly tool_s: number;          // inside a tool, less the waiting spans
  readonly blocked_s: number;       // inside a WAITING_TOOLS call
  readonly turn_s: number;          // epoch of the current turn's prompt
  readonly eta: readonly number[];  // (epoch, seconds left), or ()
  readonly agent_etas: readonly AgentEta[];
  readonly queued: number;          // messages waiting; see queueStep
  readonly compactions: number;     // see isCompaction
  readonly ctx_est: boolean;        // ctx_tokens is a compaction's estimate
  readonly shells: number;          // open background shells; scanBackground
  readonly monitors: number;        // and Monitors, likewise
  readonly tool_at: number;         // oldest running tool call, on a live read
  readonly wait_at: number;         // oldest WAITING_TOOLS call, likewise
  readonly idle_at: number;         // the last answer's end, while idle
  readonly last_seen: number;       // its last stamped record of any kind
  // The main thread's own figures, off this file alone, before the agents'
  // requests are added: what the redesign's 🤖💬 row counts.  Its
  // compactions are in the dollars, not in the tokens.
  readonly own_tok_up: number | null;
  readonly own_tok_down: number;
  readonly own_cache_pct: number;   // -1 when it billed nothing
  readonly own_usd: number;         // the parts below, totalled
  readonly own_parts: readonly (readonly [number | null, number])[];
                                    // (epoch, dollars) per own request and
                                    // compaction, as Turn.parts
  readonly own_est: boolean;        // own_usd counts a compaction's estimate
  readonly lines_added: number;     // what the main thread wrote; agentDiff
  readonly lines_removed: number;
  readonly prompt_id: string;       // the turn opened last: its promptId
  readonly turn_index: number | null;   // and turnIndex; _stampTurnId
}

type TranscriptFirst = "tok_up" | "tok_down" | "cache_pct" | "ctx_tokens" |
  "user_ts" | "user_text" | "asst_ts" | "asst_text" | "busy_s" | "start_s";

export function transcript(
  t: Pick<Transcript, TranscriptFirst> & Partial<Transcript>): Transcript {
  return {
    tool_s: 0.0, blocked_s: 0.0, turn_s: 0.0, eta: [], agent_etas: [],
    queued: 0, compactions: 0, ctx_est: false, shells: 0, monitors: 0,
    tool_at: 0.0, wait_at: 0.0, idle_at: 0.0, last_seen: 0.0,
    own_tok_up: null, own_tok_down: 0, own_cache_pct: -1, own_usd: 0.0,
    own_parts: [], own_est: false,
    lines_added: 0, lines_removed: 0, prompt_id: "", turn_index: null, ...t,
  };
}

export const EMPTY_TRANSCRIPT: Transcript = transcript({
  tok_up: null, tok_down: 0, cache_pct: -1, ctx_tokens: 0, user_ts: "",
  user_text: "", asst_ts: "", asst_text: "", busy_s: 0.0, start_s: 0.0,
});

export interface Git {
  readonly in_git: boolean;
  readonly branch: string;
  readonly dirty: boolean;
  readonly toplevel: string;
  readonly main_root: string;
  readonly is_worktree: boolean;
}

export const NO_GIT: Git = {
  in_git: false, branch: "", dirty: false, toplevel: "", main_root: "",
  is_worktree: false,
};

// The two plan windows, Limits, are claude_sources.ts's: the usage-source
// reader fills them, and one definition serves both modules.
export { NO_LIMITS, limitsEqual } from "./claude_sources.ts";
export type { Limits } from "./claude_sources.ts";

/** Where the money went, as whole percent of a bill: 📖 cache reads and 📝
 * cache writes, for the turn just answered and for the session.  null is a
 * figure that could not be derived and draws "?". */
export interface CacheShares {
  readonly turn_read: number | null;
  readonly turn_write: number | null;
  readonly sess_read: number | null;
  readonly sess_write: number | null;
}

export function cacheShares(c: Partial<CacheShares> = {}): CacheShares {
  return { turn_read: null, turn_write: null, sess_read: null,
    sess_write: null,
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
  readonly cache_write: number;
  readonly cache_read: number;
  readonly out: number;
  readonly ctx: number;             // a READING, not a sum — see readTurns
  readonly calls: number;
  readonly dur_s: number;
  readonly dctx: number | null;     // growth over the previous reading
  readonly usd_in: number;          // the bill's four parts, each priced
  readonly usd_out: number;         // per record at its own model
  readonly usd_cr: number;
  readonly usd_cw: number;
  readonly compact: boolean;
  readonly reported: boolean;
  readonly parts: readonly (readonly [number | null, number])[];
  readonly agent_calls: number;
  readonly agent_ids: readonly unknown[];
  readonly agent: boolean;
  readonly tool_s: number;
  readonly blocked_s: number;
  readonly agent_model_s: number;
  readonly agent_tool_s: number;
  readonly agent_id: string;
  readonly agent_name: string;
  readonly prompt_id: string;
  readonly turn_index: number | null;
  readonly lines_added: number;     // what the turn wrote, its agents'
  readonly lines_removed: number;   // included; see diffLines
  readonly eta: readonly number[];  // (epoch, seconds left) off the last ETA
                                    // the turn reported, kept when it ends
}

type TurnFirst = "ts" | "text" | "fresh" | "cache_write" | "cache_read" |
  "out" | "ctx" | "calls" | "dur_s" | "dctx" | "usd_in" | "usd_out" |
  "usd_cr" |
  "usd_cw";

export function turn(t: Pick<Turn, TurnFirst> & Partial<Turn>): Turn {
  return {
    compact: false, reported: false, parts: [], agent_calls: 0, agent_ids: [],
    agent: false, tool_s: 0.0, blocked_s: 0.0, agent_model_s: 0.0,
    agent_tool_s: 0.0, agent_id: "", agent_name: "", prompt_id: "",
    turn_index: null, lines_added: 0, lines_removed: 0, eta: [], ...t,
  };
}

/** One billed request from an agent's transcript, with what is needed to
 * file it under a turn of the main transcript.  See agentRecords. */
export interface AgentRec {
  readonly epoch: number | null;
  readonly prompt_id: unknown;      // "" where the agent file never said
  readonly model: unknown;
  readonly fresh: number;
  readonly cache_write: number;
  readonly cache_read: number;
  readonly out: number;
  readonly request_id: unknown;
  readonly path: string;            // the agent file, for the offsets the
  readonly offset: number;          // Stop hook keeps — see agentOffsets
  readonly model_s: number;         // the agent's 🤖 and 🔧 since its
  readonly tool_s: number;          // previous billed request; splitClock
  readonly lines_added: number;     // and what it wrote since then, filed
  readonly lines_removed: number;   // the same way; see _readAgentBytes
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
      if (pyHas(cur, part)) cur = pyGet(cur, part);
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
    current_dir: _first(d, ["workspace.current_dir", "cwd"]),
    project_dir: _first(d, ["workspace.project_dir", "cwd"]),
    model: _first(d, ["model.display_name"]),
    model_id: _first(d, ["model.id"]),
    ctx_window: _first(d, ["context_window.context_window_size"]),
    transcript: _first(d, ["transcript_path"]),
    cost_usd: _first(d, ["cost.total_cost_usd"]),
    lines_added: _first(d, ["cost.total_lines_added"], "0"),
    lines_removed: _first(d, ["cost.total_lines_removed"], "0"),
    output_style: _first(d, ["output_style.name"]),
    effort: _first(d, ["effort.level"]),
    session_id: _first(d, ["session_id"]),
    rl_session_pct: _first(d, ["rate_limits.five_hour.used_percentage"]),
    rl_session_reset: _first(d, ["rate_limits.five_hour.resets_at"]),
    rl_weekly_pct: _first(d, ["rate_limits.seven_day.used_percentage"]),
    rl_weekly_reset: _first(d, ["rate_limits.seven_day.resets_at"]),
    // Five alternate locations, first non-null wins.  Claude Code has moved
    // this field before and may again.
    pr_number: _first(d, ["pr.number", "github.pr.number",
      "github.pull_request.number", "github_pr.number",
      "pull_request.number"]),
  };
}

// ════════════════════════════════════════════════════════════════════════════
// Reading the transcript.
// ════════════════════════════════════════════════════════════════════════════

// Decoding as Python's text mode does with errors="replace", keeping a BOM,
// which "utf-8" (unlike "utf-8-sig") does not strip.
const DECODE_REPLACE = { decode: (b: Uint8Array) => utf8(b, false, true) };
// Decoding as json.loads(bytes) does: invalid UTF-8 raises, and the line is
// skipped; a leading BOM is taken as "utf-8-sig" and dropped.
const DECODE_STRICT = { decode: (b: Uint8Array) => utf8(b, true) };

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
    if (!pyTruthy(pyDig(r, "message", "usage"))) continue;
    const k = pyOr(pyOr(pyGet(r, "requestId"), pyDig(r, "message", "id")),
      "?");
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
  if (!pyTruthy(ts) || typeof ts !== "string") return null;
  const s = ts.split(".")[0].replace(/Z+$/, "");
  const m = STRPTIME.exec(s);
  if (!m || m[0].length !== s.length) return null;
  const [y, mo, d, h, mi, sec] = m.slice(1).map(
    (g) => parseInt(pyAsciiDigits(g.trim()), 10));
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
  const m = pyStr(pyOr(model, "")).toLowerCase();
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
  const t = tsEpoch(pyOr(pyGet(r, "timestamp"), ""));
  if (t === null) return;
  const blocks = pyDig(r, "message", "content");
  if (!Array.isArray(blocks)) return;
  for (const b of blocks) {
    if (!isDict(b)) continue;
    const kind = pyGet(b, "type");
    if (kind === "tool_use") {
      if (pyTruthy(pyGet(b, "id"))) {
        pending.set(pyStr(pyGet(b, "id")),
          [t, pyStr(pyOr(pyGet(b, "name"), ""))]);
      }
    } else if (kind === "tool_result") {
      const id = pyStr(pyOr(pyGet(b, "tool_use_id"), ""));
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
  const a = pyOr(pyGet(r, "attachment"), {});
  let c: unknown = pyGet(a, "type") === "queued_command" ? pyGet(a, "prompt")
    : pyGet(r, "type") === "user" ? pyDig(r, "message", "content") : null;
  if (Array.isArray(c)) {
    c = c.filter(isDict).map((b) => pyStr(pyOr(pyGet(b, "text"), "")))
      .join("");
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
  const res = pyGet(r, "toolUseResult");
  if (isDict(res)) {
    if (pyTruthy(pyGet(res, "backgroundTaskId"))) {
      open.set(pyStr(pyGet(res, "backgroundTaskId")), "bash");
    } else if (pyTruthy(pyGet(res, "taskId")) && pyHas(res, "timeoutMs")) {
      open.set(pyStr(pyGet(res, "taskId")), "monitor");
    } else if (pyTruthy(pyGet(res, "task_id")) && pyHas(res, "message")) {
      open.delete(pyStr(pyGet(res, "task_id")));
    }
    const task = pyGet(res, "task");
    if (isDict(task) && TASK_ENDED.has(pyGet(task, "status"))) {
      open.delete(pyStr(pyOr(pyGet(task, "task_id"), "")));
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
  const res = pyGet(r, "toolUseResult");
  let aid: string;
  if (isDict(res) && pyTruthy(pyGet(res, "agentId")) &&
    TASK_ENDED.has(pyGet(res, "status"))) {
    aid = pyStr(pyGet(res, "agentId"));
  } else {
    const text = notificationText(r);
    const m = text.includes("<status>") ? TASK_ID.exec(text) : null;
    if (!m) return;
    aid = pyStrip(m[1]);
  }
  const t = tsEpoch(pyOr(pyGet(r, "timestamp"), ""));
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
  return pyMax(0.0, t.dur_s - t.tool_s - t.blocked_s);
}

/** The receipt's ⌛🤖 and 🔧 for a row: the main thread's, plus its
 * agents', which are agent-seconds and can outrun the turn. */
export function turnTimes(t: Turn): [number, number] {
  return [turnModelS(t) + t.agent_model_s, t.tool_s + t.agent_tool_s];
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
    if (!isDict(r) || pyGet(r, "type") !== "assistant") continue;
    const content = pyDig(r, "message", "content");
    if (!Array.isArray(content)) continue;
    for (const block of content) {
      if (!isDict(block) || pyGet(block, "type") !== "text") continue;
      const hits = [...pyStr(pyOr(pyGet(block, "text"), ""))
        .matchAll(ETA_LINE)].map((m) => m[1]);
      const epoch = tsEpoch(pyOr(pyGet(r, "timestamp"), ""));
      if (hits.length && epoch !== null) {
        let secs = 0;
        for (const [, n, unit] of hits[hits.length - 1].matchAll(ETA_SPLIT)) {
          secs += parseFloat(pyAsciiDigits(n)) * ETA_UNIT_S[unit];
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
  return pyGet(r, "type") === "assistant" &&
    pyDig(r, "message", "stop_reason") === "end_turn";
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
    const mid = pyDig(r, "message", "id") ?? null;
    if (report.length) {
      state[0] = report;
      state[3] = mid;
    }
    const parked = state[0].length > 0 && state[0][1] > 0 &&
      (report.length > 0 || (mid !== null && mid === state[3]));
    state[1] = endsTurn(r) && !parked;
  }
  const t = tsEpoch(pyOr(pyGet(r, "timestamp"), ""));
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
  const t = tsEpoch(pyOr(pyGet(r, "timestamp"), ""));
  if (t === null) return;
  if (state[0] !== null && turnStartText(r) !== null) {
    closeAgentSpan(state, spans);
  }
  if (state[0] === null) {
    const type = pyGet(r, "type");
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
  const c = pyDig(r, "message", "content");
  if (pyGet(r, "type") !== "user" || pyGet(r, "userType") !== "external" ||
    pyTruthy(pyGet(r, "isCompactSummary")) || typeof c !== "string" ||
    c.length === 0) {
    return false;
  }
  if (pyGet(r, "promptSource") === "system") return true;
  const source = pyHas(r, "promptSource") ? pyGet(r, "promptSource") : "typed";
  return !pyTruthy(pyGet(r, "isMeta")) && source === "typed" &&
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
  if (pyGet(r, "type") !== "queue-operation") return null;
  if (!QUEUE_DELIVERED.includes(pyGet(r, "operation"))) return null;
  const c = pyGet(r, "content");
  return typeof c === "string" && c.length > 0 && !c.startsWith("<")
    ? c : null;
}

/** +1 for a message put on this thread's queue, -1 for one handed over.
 * The running sum, never below zero, is how many messages are waiting for
 * the thread's next turn. */
export function queueStep(r: Rec): number {
  if (pyGet(r, "type") !== "queue-operation") return 0;
  const op = pyGet(r, "operation");
  return op === "enqueue" ? 1 : QUEUE_DELIVERED.includes(op) ? -1 : 0;
}

// What postTokens leaves out of a reading, when the transcript has no
// reading before its compaction to take it from: the median over 520 local
// compactions on 2026-10-16.  See the 🧠 estimate in transcriptOf.
export const COMPACT_OVERHEAD = 46000;

/** True for the marker a compaction writes, /compact's or the automatic
 * one's: `type: system`, `subtype: compact_boundary`. */
export function isCompaction(r: Rec): boolean {
  return pyGet(r, "type") === "system" &&
    pyGet(r, "subtype") === "compact_boundary";
}

/** The text of the prompt this record opens, or null if it opens none. */
export function turnStartText(r: Rec): string | null {
  if (opensTurn(r)) return pyDig(r, "message", "content") as string;
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
  const t = pyGet(r, "type");
  if (t === "assistant" || t === "system") return true;
  if (t === "user") return Array.isArray(pyDig(r, "message", "content"));
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

/** One record of an agent file that carries usage, as _readAgentFile keeps
 * it: (epoch, promptId, model, fresh, cache write, cache read, out,
 * requestId, offset, lines added, lines removed), the lines being what its
 * tool results wrote since the usage record before. */
export type AgentRaw = readonly [number | null, unknown, unknown, number,
  number, number, number, unknown, number, number, number];

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
    // A record dropped below hands what its results wrote on to the next
    // one this file keeps, as splitClock hands on its time.
    let added = 0, removed = 0;
    for (const [epoch, pid, model, fresh, cw, cr, o, k, pos, la, lr] of
      got.recs) {
      added += la;
      removed += lr;
      if (seen.has(k)) continue;
      seen.add(k);
      if (!(pyTruthy(fresh) || pyTruthy(cw) || pyTruthy(cr) ||
            pyTruthy(o))) continue;
      out.push({ epoch, prompt_id: pid, model, fresh, cache_write: cw,
        cache_read: cr, out: o, request_id: k, path, offset: pos,
        model_s: 0.0, tool_s: 0.0, lines_added: added,
        lines_removed: removed });
      added = removed = 0;
    }
    if (etas !== null && got.eta !== null) etas.push([...got.eta]);
    const cuts: number[] = [];
    let cut = -Infinity;
    for (const a of out.slice(first)) {
      cut = a.epoch !== null ? pyMax(cut, a.epoch) : cut;
      cuts.push(cut);
    }
    const split = splitClock(got.work, got.tools, got.waiting, cuts);
    split.forEach(([m, tl], i) => {
      out[first + i] = { ...out[first + i], model_s: m, tool_s: tl };
    });
  }
  // Stamp order across files, unparseable stamps last: the fold-in walks
  // turns forward and a record that cannot be placed in time is handed to
  // the last turn rather than the first.
  const key = (a: AgentRec): [number, number] =>
    [a.epoch === null ? 1 : 0, pyOr(a.epoch, 0.0) as number];
  return out.sort((a, b) => cmpTuple(key(a), key(b)));
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
  const wrote = new Set<string>();
  let added = 0, removed = 0;
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
    const [a, d] = diffLines(r, wrote);
    added += a;
    removed += d;
    if (pyGet(r, "type") === "user") {
      pid = pyOr(pyGet(r, "promptId"), pid);
      continue;
    }
    if (pyGet(r, "type") !== "assistant") continue;
    const m = pyOr(pyGet(r, "message"), {});
    const u = pyGet(m, "usage");
    if (!pyTruthy(u)) continue;
    recs.push([tsEpoch(pyOr(pyGet(r, "timestamp"), "")), pid,
      pyGet(m, "model") ?? null, num0(pyGet(u, "input_tokens")),
      num0(pyGet(u, "cache_creation_input_tokens")),
      num0(pyGet(u, "cache_read_input_tokens")),
      num0(pyGet(u, "output_tokens")),
      pyOr(pyOr(pyGet(r, "requestId"), pyGet(m, "id")), "?"), pos,
      added, removed]);
    added = removed = 0;
  }
  closeAgentSpan(spanState, work);
  let eta: [number | null, number | null] | null = null;
  if (etaState[0].length && !etaState[1]) {
    eta = [etaFinish(etaState[0]), etaState[2]];
  }
  return { recs, work, tools, waiting, eta };
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
  const digest = sha256Hex("claude-agent-files-ts\0" + sid);
  return pyJoin(stateDir, "claude-agent-files-ts-" + digest + ".cache");
}

/** Where the Stop hook records how far into each agent file it reported.
 *
 * Per session, in private application state.  A one-way digest keeps a raw
 * transcript/session id out of the path.  The same file the Python's Stop
 * hook writes, so the two report each record once between them. */
export function _agentStatePath(transcript: string, stateDir: string): string {
  let sid = pyBasename(transcript);
  if (sid.endsWith(".jsonl")) sid = sid.slice(0, -".jsonl".length);
  const digest = sha256Hex("claude-agent-offsets\0" + sid);
  return pyJoin(stateDir, "claude-agent-offsets-" + digest + ".json");
}

/** agentOffsets' reading of the file's text: the byte offset the last Stop
 * reported each agent file up to, or null for a file that is not a JSON
 * object.  A value must be an int, and Python's bool is one.  Throws on
 * text that will not parse, which the reader takes as no file. */
export function agentOffsetsOf(text: string): Map<string, number> | null {
  const d: unknown = JSON.parse(text);
  if (!isDict(d)) return null;
  const out = new Map<string, number>();
  for (const [k, v] of Object.entries(d)) {
    if (typeof v === "boolean") out.set(k, v ? 1 : 0);
    else if (typeof v === "number" && Number.isInteger(v)) out.set(k, v);
  }
  return out;
}

/** The id off an agent file's `agent-<id>.jsonl`, else "". */
export function agentLabelId(path: string): string {
  const base = pyBasename(path);
  return base.startsWith("agent-") && base.endsWith(".jsonl") &&
    base.length >= "agent-".length + ".jsonl".length
    ? base.slice("agent-".length, -".jsonl".length) : "";
}

// Decoding as open(encoding="utf-8") does: a bad byte raises, and a BOM is
// kept, for json.load to refuse.
const DECODE_FATAL_BOM = { decode: (b: Uint8Array) => utf8(b, true, true) };

/** agentLabel's reading: the id off `agent-<id>.jsonl`, and the name
 * `meta`, the bytes of its `.meta.json` sidecar or null for none, gives:
 * its description, else its agentType, else "". */
export function agentLabelOf(path: string, meta: Uint8Array | null):
  [string, string] {
  const aid = agentLabelId(path);
  let name = "";
  if (meta === null) return [aid, name];
  try {
    const d: unknown = JSON.parse(DECODE_FATAL_BOM.decode(meta));
    if (isDict(d)) {
      name = pyStr(pyOr(pyOr(pyGet(d, "description"),
        pyGet(d, "agentType")), ""));
    }
  } catch {
    // A sidecar that will not parse: the id alone.
  }
  return [aid, name];
}

/** A label read with no sidecar: the id alone.  turnsOf's default, since
 * reading the sidecar is the caller's: agentLabel in Node, the mod's own
 * read in the mod. */
export function noSidecar(path: string): [string, string] {
  return agentLabelOf(path, null);
}

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
  const res = pyGet(r, "toolUseResult");
  const msg = isDict(res) ? pyGet(res, "message") : null;
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
  const a = pyGet(r, "attachment");
  let o: unknown;
  if (isDict(a) && pyGet(a, "type") === "queued_command") {
    o = pyGet(a, "origin");
  }
  else if (pyGet(r, "type") === "user") o = pyGet(r, "origin");
  else return false;
  if (!isDict(o)) return false;
  const kind = pyGet(o, "kind");
  return kind === "coordinator" ||
    (kind === "peer" && !pyTruthy(pyGet(o, "handback")));
}

/** Where `mark` next occurs in `data` at or after `from`, else -1. */
function findBytes(data: Uint8Array, mark: Uint8Array, from: number): number {
  // Node's Buffer#indexOf, which the mod does not have: each place the
  // mark's first byte occurs, checked in full.
  if (mark.length === 0) return Math.min(from, data.length);
  const last = data.length - mark.length;
  for (let i = data.indexOf(mark[0], from); i >= 0 && i <= last;
    i = data.indexOf(mark[0], i + 1)) {
    let j = 1;
    while (j < mark.length && data[i + j] === mark[j]) j++;
    if (j === mark.length) return i;
  }
  return -1;
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

// ════════════════════════════════════════════════════════════════════════════
// The status line's pass over the transcript.
// ════════════════════════════════════════════════════════════════════════════

export type AgentEta = readonly [number | null, number | null];

/** +adds/-removes one record's tool result wrote, counted the way a diff
 * is: over the `structuredPatch` an Edit's result carries, one hunk line at
 * a time, `+` added and `-` removed; a Write to a NEW file, `type:
 * "create"`, adds every line of its `content`.  `seen` holds the tool-use
 * ids counted already, since a resumed or compacted transcript can carry a
 * result twice; a result with no id is counted. */
export function diffLines(r: Rec, seen: Set<string>): [number, number] {
  const res = pyGet(r, "toolUseResult");
  if (!isDict(res)) return [0, 0];
  let tid = "";
  const content = pyOr(pyDig(r, "message", "content"), []);
  // Iterating a string or a dict meets no dict, so only a list has blocks.
  for (const block of Array.isArray(content) ? content : []) {
    if (isDict(block) && pyTruthy(pyGet(block, "tool_use_id"))) {
      tid = pyStr(pyGet(block, "tool_use_id"));
      break;
    }
  }
  if (tid) {
    if (seen.has(tid)) return [0, 0];
    seen.add(tid);
  }
  let added = 0, removed = 0;
  const patch = pyGet(res, "structuredPatch");
  if (Array.isArray(patch) && patch.length) {
    for (const hunk of patch) {
      const lines = pyOr(pyGet(pyOr(hunk, {}), "lines"), []);
      // A str is iterated by character, as the Python iterates it.
      const each = typeof lines === "string" ? Array.from(lines)
        : Array.isArray(lines) ? lines : [];
      for (const line of each) {
        if (typeof line !== "string" || !line) continue;
        if (line[0] === "+") added += 1;
        else if (line[0] === "-") removed += 1;
      }
    }
  } else if (pyGet(res, "type") === "create" &&
    typeof pyGet(res, "content") === "string") {
    added += pySplitlinesCount(pyGet(res, "content") as string);
  }
  return [added, removed];
}

// str.splitlines' line boundaries.
const LINE_BREAK = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/g;

/** len(s.splitlines()): a break ends a line, and a last line without one
 * is a line too. */
function pySplitlinesCount(s: string): number {
  if (!s) return 0;
  const breaks = s.match(LINE_BREAK)?.length ?? 0;
  const tail = s.replace(LINE_BREAK, "\n").endsWith("\n") ? 0 : 1;
  return breaks + tail;
}

/** +adds/-removes across everything one thread wrote: diffLines over every
 * record, deduped across them.  An agent row, the main thread and each
 * turn count their own this way; the payload's pair is the session's. */
export function agentDiff(records: readonly Rec[]): [number, number] {
  let added = 0, removed = 0;
  const seen = new Set<string>();
  for (const r of records) {
    const [a, d] = diffLines(r, seen);
    added += a;
    removed += d;
  }
  return [added, removed];
}

/** One pass for the status line: totals, cache rate, context, last texts.
 *
 * The token totals and the cache rate count what the session's AGENTS
 * billed as well — `agents` is agentRecords' reading of the files beside
 * the transcript — because it was billed.  Time does NOT, since
 * 2026-09-27: busy, tool and waiting time are this thread's own, off this
 * file alone — see threadClock.  With a `now`, a tool call still running
 * counts to it; see openToolSpans.  Context size does NOT either: it is a
 * reading of THIS window, the one 🧠 is watched to decide when to compact.
 *
 * The pure core; readTranscript reads the file and the agents. */
export function transcriptOf(records: readonly Rec[],
  agents: readonly AgentRec[], agent_etas: readonly AgentEta[] = [],
  now: number | null = null): Transcript {
  const reqs = _dedupeUsage(records);
  let fresh = 0, cwrite = 0, cread = 0, down = 0;
  // The main thread's own parts, its requests and its compactions, in one
  // walk so each compaction falls in its place.  A compaction is priced as
  // readTurns prices its turn, preTokens at the cache-read rate and the
  // summary's estimated output once it arrives while no turn has opened
  // since, and stamped where readTurns stamps that turn: at the /compact
  // prompt that asked for it, where one is open with no calls, else at the
  // boundary.
  const kept = new Set(reqs);
  type Compacting = [number | null, [number, number]];
  const parts: ([number | null, number] | Compacting)[] = [];
  let compacting: Compacting | null = null;
  let opener: [unknown, string, number] | null = null;
  let own_est = false;
  for (const r of records) {
    const text = turnStartText(r);
    if (text !== null) {
      opener = [pyOr(pyGet(r, "timestamp"), ""), text, 0];
      compacting = null;
    } else if (pyGet(r, "subtype") === "compact_boundary") {
      const md = pyOr(pyGet(r, "compactMetadata"), {});
      const at: unknown = opener !== null && !opener[2] &&
        pyStrip(opener[1]) === "/compact" ? opener[0]
        : pyOr(pyGet(r, "timestamp"), "");
      compacting = [tsEpoch(at), [num0(pyGet(md, "preTokens")) * P_CR, 0.0]];
      parts.push(compacting);
      own_est = true;
      // The compaction is the open turn now, with a call, as readTurns
      // makes it: a second boundary opens another.
      opener = [at, "", 1];
    } else if (pyTruthy(pyGet(r, "isCompactSummary")) && compacting !== null) {
      const c = pyDig(r, "message", "content");
      if (typeof c === "string") {
        compacting[1][1] = Math.trunc(pyLen(c) / SUMMARY_CPT) * P_OUT;
      }
    }
    if (!kept.has(r)) continue;
    const u = pyDig(r, "message", "usage");
    fresh += num0(pyGet(u, "input_tokens"));
    cwrite += num0(pyGet(u, "cache_creation_input_tokens"));
    cread += num0(pyGet(u, "cache_read_input_tokens"));
    down += num0(pyGet(u, "output_tokens"));
    if (opener !== null) opener[2] += 1;
    // Priced per record at its own model, as readTurns prices it.
    const d = _usd(pyDig(r, "message", "model"),
      num0(pyGet(u, "input_tokens")),
      num0(pyGet(u, "cache_creation_input_tokens")),
      num0(pyGet(u, "cache_read_input_tokens")),
      num0(pyGet(u, "output_tokens")));
    parts.push([tsEpoch(pyOr(pyGet(r, "timestamp"), "")),
      0 + d[0] + d[1] + d[2] + d[3]]);
  }
  // A compaction's two halves summed as turnCost sums its turn's: the
  // output, then the cache read.
  const own_parts = parts.map(([e, c]): [number | null, number] =>
    [e, Array.isArray(c) ? c[1] + c[0] : c]);
  let ownUsd = 0;
  for (const [, c] of own_parts) ownUsd += c;
  // The main thread's own figures, before the agents are added.
  const ownIn = fresh + cwrite + cread;
  const ownUp = Math.trunc(fresh + W_CACHE_WRITE * cwrite +
    W_CACHE_READ * cread);
  const ownDown = down;
  const ownCache = ownIn > 0 ? Math.trunc(100 * cread / ownIn) : -1;
  for (const a of agents) {
    fresh += a.fresh;
    cwrite += a.cache_write;
    cread += a.cache_read;
    down += a.out;
  }
  const inAll = fresh + cwrite + cread;

  // Walked over `records` rather than `reqs` so a compaction boundary falls
  // in its place among the readings; `kept` is the dedupe's choice of them.
  let ctx = 0, firstCtx = 0;
  let ctx_est = false;
  for (const r of records) {
    if (pyGet(r, "isSidechain") === true) continue;
    if (isCompaction(r)) {
      // A compaction writes no usage record, so until the next request the
      // last reading is the size from BEFORE it.  postTokens is the
      // compacted conversation alone; what it leaves out is the system
      // prompt, the tools and the files re-attached after it, which the
      // session's first reading carries too, or COMPACT_OVERHEAD without
      // one.  The Python's comment has the measurements.
      const post = num0(pyDig(r, "compactMetadata", "postTokens"));
      if (post) {
        ctx = post + (firstCtx || COMPACT_OVERHEAD);
        ctx_est = true;
      }
      continue;
    }
    if (!kept.has(r)) continue;
    const u = pyDig(r, "message", "usage");
    // Skip a request whose usage is all zero: that is how an interrupted
    // request is recorded, and letting it win the last-write would blank
    // the 🧠 cell for the rest of the session.
    const c = num0(pyGet(u, "input_tokens")) +
      num0(pyGet(u, "cache_creation_input_tokens")) +
      num0(pyGet(u, "cache_read_input_tokens"));
    if (c) {
      ctx = c;
      ctx_est = false;
      firstCtx = firstCtx || c;
    }
  }

  let user_ts: unknown = "", user_text = "", asst_ts: unknown = "";
  let asst_text: unknown = "";
  for (const r of records) {
    const c = pyDig(r, "message", "content");
    if (pyGet(r, "type") === "user" && pyGet(r, "userType") === "external" &&
      typeof c === "string" && c.length > 0 && !c.startsWith("<")) {
      user_ts = pyOr(pyGet(r, "timestamp"), "");
      user_text = c;
    }
    if (pyGet(r, "type") === "assistant") {
      const blocks = pyOr(pyDig(r, "message", "content"), []);
      if (Array.isArray(blocks)) {
        const texts = blocks.filter((b) => isDict(b) &&
          pyGet(b, "type") === "text");
        if (texts.length) {
          asst_text = pyOr(pyGet(texts[texts.length - 1], "text"), "");
          asst_ts = pyOr(pyGet(r, "timestamp"), "");
        }
      }
    }
  }

  // Time spent ANSWERING, which is not the time the session has existed.
  // A turn runs from the prompt that opens it to the last record before
  // the next prompt, so summing those spans counts the working time and
  // skips every gap where the session sat waiting for someone to type.
  const spans: Span[] = [];
  const tools: Span[] = [];
  const blocked: Span[] = [];
  const pending: Pending = new Map();
  let first: number | null = null, openAt: number | null = null;
  let prev: number | null = null;
  // The ETA belongs to the turn it was written in; see liveEta.
  const etaState = newEtaState();
  let queued = 0, compactions = 0;
  const background = new Map<string, string>();
  let idle_at = 0.0, last_seen = 0.0;
  let opened = _newTurn("", "");    // the open turn, for its promptId alone
  const wrote = new Set<string>();  // tool-use ids diffLines has counted
  let added = 0, removed = 0;
  for (const r of records) {
    queued = Math.max(0, queued + queueStep(r));
    compactions += isCompaction(r) ? 1 : 0;
    scanToolSpans(r, pending, tools, blocked);
    const [a, d] = diffLines(r, wrote);
    added += a;
    removed += d;
    // The tag the start line prints: the promptId and turnIndex of the
    // turn opened last, read as readTurns reads a turn's.
    if (turnStartText(r) !== null) opened = _newTurn("", "");
    _stampTurnId(opened, r);
    if (pyGet(r, "isSidechain") !== true) {
      liveEta(r, etaState);
      scanBackground(r, background);
    }
    const t = tsEpoch(pyOr(pyGet(r, "timestamp"), ""));
    if (t === null) continue;
    if (first === null) first = t;
    if (pyGet(r, "isSidechain") !== true) {
      last_seen = t;
      // The answer ending opens the idle; the next request or tool
      // result, or a prompt, closes it.  Not any work record: Claude Code
      // writes system records after the end.
      if (endsTurn(r)) idle_at = t;
      else if (pyGet(r, "type") === "assistant" || turnStartText(r) !== null ||
        (pyGet(r, "type") === "user" &&
          Array.isArray(pyDig(r, "message", "content")))) {
        idle_at = 0.0;
      }
    }
    if (turnStartText(r) !== null) {
      if (openAt !== null && prev! > openAt) spans.push([openAt, prev!]);
      openAt = prev = t;
    } else if (openAt !== null && isWork(r)) {
      prev = t;
    }
  }
  if (openAt !== null && prev! > openAt) spans.push([openAt, prev!]);
  // The oldest call still running, for the 🛫 cell: only one asked for in
  // the turn still open, since an older one left unanswered was cut off.
  const running: number[] = [], waits: number[] = [];
  for (const [t, name] of pending.values()) {
    if (!pyTruthy(openAt) || t < openAt!) continue;
    (WAITING_TOOLS.has(name) ? waits : running).push(t);
  }
  if (now !== null) openToolSpans(pending, now, tools, blocked);
  const [busy, tool, blocked_s] = threadClock(spans, tools, blocked);
  const min = (xs: number[]) => xs.reduce((a, b) => pyMin(a, b));

  return transcript({
    busy_s: busy,
    // The first STAMPED record, not records[0]: a transcript can open with
    // an unstamped one.
    start_s: pyOr(first, 0.0) as number,
    tok_up: Math.trunc(fresh + W_CACHE_WRITE * cwrite + W_CACHE_READ * cread),
    tok_down: down,
    // -1 is a sentinel meaning "no usage data at all", which renders as no
    // segment rather than as a zero.
    cache_pct: inAll > 0 ? Math.trunc(100 * cread / inAll) : -1,
    ctx_tokens: ctx,
    ctx_est,
    user_ts: pyStr(user_ts),
    user_text: squash(user_text),
    asst_ts: pyStr(asst_ts),
    asst_text: squash(pyStr(asst_text)),
    tool_s: tool,
    blocked_s,
    turn_s: pyOr(openAt, 0.0) as number,
    eta: etaState[1] ? [] : etaState[0],
    agent_etas: [...agent_etas],
    queued,
    compactions,
    shells: [...background.values()].filter((k) => k === "bash").length,
    monitors: [...background.values()].filter((k) => k === "monitor").length,
    tool_at: now !== null && running.length ? min(running) : 0.0,
    wait_at: now !== null && waits.length ? min(waits) : 0.0,
    idle_at: now !== null ? idle_at : 0.0,
    last_seen: now !== null ? last_seen : 0.0,
    own_tok_up: ownUp,
    own_tok_down: ownDown,
    own_cache_pct: ownCache,
    own_usd: ownUsd,
    own_parts,
    own_est,
    lines_added: added,
    lines_removed: removed,
    prompt_id: opened.pid,
    turn_index: opened.tidx,
  });
}

// ════════════════════════════════════════════════════════════════════════════
// The cost line's turns.
// ════════════════════════════════════════════════════════════════════════════

// Characters per token for the compaction summary, calibrated against the
// metadata: two compactions summarised to 16,201 and 23,659 characters
// against postTokens of 6,597 and 8,737, which is the summary plus the
// handful of preserved messages.
export const SUMMARY_CPT = 4.0;

/** The mutable turn readTurns builds up, before it is frozen. */
interface TurnBuild {
  ts: string;
  text: string;
  fresh: number;
  cw: number;
  cr: number;
  out: number;
  ctx: number;
  n: number;
  usd: [number, number, number, number];
  an: number;
  aids: unknown[];
  t0: number | null;
  t1: number | null;
  parts: [number | null, number][];
  tools: Span[];
  waits: Span[];
  am: number;
  at: number;
  pid: string;
  tidx: number | null;
  la: number;
  lr: number;
  eta: number[];
  dur?: number;
  compact?: boolean;
}

export function _newTurn(ts: string, text: string): TurnBuild {
  return { ts, text, fresh: 0, cw: 0, cr: 0, out: 0, ctx: 0, n: 0,
    usd: [0.0, 0.0, 0.0, 0.0], an: 0, aids: [], t0: tsEpoch(ts), t1: null,
    parts: [], tools: [], waits: [], am: 0.0, at: 0.0, pid: "", tidx: null,
    la: 0, lr: 0, eta: [] };
}

/** Take the turn's promptId and turnIndex off `r`, where the turn has none
 * yet.  First one wins: every user record of a turn carries the same
 * promptId, and a turn a queue-operation record opened gets its id from
 * the first tool result instead of from its opener.  A bool is not an
 * index, though Python's int would take it. */
export function _stampTurnId(cur: TurnBuild, r: Rec): void {
  const pid = pyGet(r, "promptId");
  if (pyTruthy(pid) && !cur.pid) cur.pid = pyStr(pid);
  const idx = pyDig(r, "turnPosition", "turnIndex");
  if (cur.tidx === null && typeof idx === "number" && Number.isInteger(idx)) {
    cur.tidx = idx;
  }
}

/** Bill one record to a turn: the four dollar sums, and one part. */
export function _addUsd(cur: TurnBuild, epoch: number | null, model: unknown,
  fresh: number, cw: number, cr: number, out: number): void {
  const d = _usd(model, fresh, cw, cr, out);
  for (let i = 0; i < 4; i++) cur.usd[i] += d[i];
  cur.parts.push([epoch, 0 + d[0] + d[1] + d[2] + d[3]]);
}

/** File every agent record under a turn of the main transcript.
 *
 * By promptId where a main record carried it — the turn that spawned the
 * agent, or resumed it, whenever it finished.  By stamp only where no main
 * record carries the id: the last NON-COMPACTION turn open at that moment,
 * so agent spend never prints on the 🤏 row.  Dropped where no turn
 * precedes the record.  Into the turn: the token sums, the dollar sums, a
 * part and agentCalls — not `n`, not `ctx`, not `t1`.
 *
 * EXCEPT when the record is NEW and its turn is not the one the next Stop
 * will report: it would be counted in the totals and printed on no row.
 * Those records go into a turn of their own instead, one per agent file,
 * returned here by path for readTurns to freeze — once the agent has
 * FINISHED, by `ends`; until then they stay on their spawning turn and go
 * into `held`.  "New" is exact with `offsets`, the byte counts the last
 * Stop stored; without them, a record stamped after the last Stop record.
 * The Python's docstring has the measurements. */
export function _foldAgents(turns: TurnBuild[],
  byPid: ReadonlyMap<unknown, TurnBuild>, agents: readonly AgentRec[],
  lastStop: number | null = null,
  offsets: ReadonlyMap<string, number> | null = null,
  ends: ReadonlyMap<string, number> | null = null,
  held: Map<string, number> | null = null): Map<string, TurnBuild> {
  const late = new Map<string, TurnBuild>();
  if (agents.length === 0 || turns.length === 0) return late;
  const stamped = turns.filter((t) => t.t0 !== null && !pyTruthy(t.compact));
  // The turn the 🎤 row will be about: the same selection render_cost_line
  // and _with_shares make.  `n` is main-thread calls, so folding agents in
  // cannot move it.
  let prompt: TurnBuild | null = null;
  for (const t of turns) if (t.n && !pyTruthy(t.compact)) prompt = t;
  for (const a of agents) {
    let cur = pyTruthy(a.prompt_id) ? byPid.get(a.prompt_id) ?? null : null;
    if (cur === null) {
      for (let i = stamped.length - 1; i >= 0; i--) {
        if (a.epoch === null || stamped[i].t0! <= a.epoch) {
          cur = stamped[i];
          break;
        }
      }
      if (cur === null) continue;
    }
    if (prompt !== null && cur !== prompt) {
      const isNew = offsets !== null
        ? a.offset > (offsets.get(a.path) ?? 0)
        : lastStop === null || (a.epoch !== null && a.epoch > lastStop);
      if (isNew && !_endedAfter(a, ends)) {
        // Still running: its 👥 row waits for its end, and the record stays
        // on its spawning turn for the totals until then.  `held` keeps
        // publishAgentOffsets from marking it reported.
        if (held !== null && a.offset < (held.get(a.path) ?? a.offset + 1)) {
          held.set(a.path, a.offset);
        }
      } else if (isNew) {
        if (!late.has(a.path)) {
          late.set(a.path, _newTurn(_stampUtc(a.epoch), "agents (other)"));
        }
        cur = late.get(a.path)!;
      }
    }
    cur.fresh += a.fresh;
    cur.cw += a.cache_write;
    cur.cr += a.cache_read;
    cur.out += a.out;
    cur.an += 1;
    cur.aids.push(a.request_id);
    cur.am += a.model_s;
    cur.at += a.tool_s;
    cur.la += a.lines_added;
    cur.lr += a.lines_removed;
    _addUsd(cur, a.epoch, a.model, a.fresh, a.cache_write, a.cache_read,
      a.out);
  }
  return late;
}

/** Has the agent that billed `a` finished since, by `ends`?  An agent file
 * is named `agent-<id>.jsonl`; a record with no stamp counts as before any
 * end. */
export function _endedAfter(a: AgentRec,
  ends: ReadonlyMap<string, number> | null): boolean {
  const end = ends?.get(agentLabelId(a.path));
  return end !== undefined && (a.epoch === null || a.epoch <= end);
}

/** Segment the transcript into prompts, with each turn's billed usage.
 *
 * `ctx` is LAST-WRITE-WINS within a turn and is the MAIN THREAD's — an
 * instantaneous reading of how big the window is, not a sum of anything.
 * Agent usage never touches it.  Every agent record is folded into the turn
 * whose promptId it carries, or the turn open at its stamp; its tokens and
 * dollars go into the same sums and its cost into `parts`, but its stamp
 * does NOT move the turn's end.  Assistant records before the first
 * recognised prompt are dropped: there is no turn to attribute them to.
 *
 * The pure core: `agentsOf` gives the agent records, handed the set of
 * request ids the main thread billed so the two dedupe together; `offsets`
 * is what agentOffsets read; `label` names a late agent turn's file. */
export function turnsOf(records: readonly Rec[],
  agentsOf: (seen: Set<unknown>) => readonly AgentRec[],
  offsets: ReadonlyMap<string, number> | null = null,
  held: Map<string, number> | null = null,
  label: (path: string) => [string, string] = noSidecar): Turn[] {
  const turns: TurnBuild[] = [];
  let settled = 0;      // turns that a Stop hook has already run past
  let cur: TurnBuild | null = null;
  const seen = new Set<unknown>();
  const byPid = new Map<unknown, TurnBuild>();
  let lastStop: number | null = null;
  const pending: Pending = new Map();
  const ends = new Map<string, number>();
  const wrote = new Set<string>();      // tool-use ids diffLines has counted
  for (const r of records) {
    scanAgentEnd(r, ends);
    // What the record's tool result wrote, onto the turn it is filed under
    // below: the main thread's 💾, turn by turn.
    const [added, removed] = diffLines(r, wrote);
    // Every tool call, onto the turn open when its RESULT arrives: the scan
    // transcriptOf makes for the status line's 🔧, so the two readouts
    // count the same calls by the same rule.  A record before the first
    // prompt is still scanned, and its own spans go nowhere.
    scanToolSpans(r, pending, cur ? cur.tools : [], cur ? cur.waits : []);
    const pid = pyGet(r, "promptId");
    const text = turnStartText(r);
    if (text !== null) {
      // A queued message can be recorded BOTH ways — once typed, once
      // delivered.  The earlier of the two has no records under it yet, so
      // replacing it in place keeps one turn, with the later timestamp.
      if (cur !== null && cur.n === 0 && cur.t1 === null &&
        cur.text === text) {
        cur.ts = pyOr(pyGet(r, "timestamp"), cur.ts) as string;
        cur.t0 = tsEpoch(pyOr(pyGet(r, "timestamp"), ""));
      } else {
        cur = _newTurn(pyStr(pyOr(pyGet(r, "timestamp"), "")), text);
        turns.push(cur);
      }
      _stampTurnId(cur, r);
      cur.la += added;
      cur.lr += removed;
      if (pyTruthy(pid)) byPid.set(pid, cur);
      continue;
    }
    // Every user record of a turn carries the turn's promptId, so the index
    // is built from all of them, not from the opener alone.
    if (pyTruthy(pid) && cur !== null && !pyTruthy(cur.compact)) {
      if (!byPid.has(pid)) byPid.set(pid, cur);
      _stampTurnId(cur, r);
    }
    if (cur !== null) {
      cur.la += added;
      cur.lr += removed;
      // The last ETA the main thread reported in the turn, read as liveEta
      // reads one, and here before the dedupe below can skip the record
      // that carries it.
      if (pyGet(r, "isSidechain") !== true) {
        const report = etaReport([r]);
        if (report.length) cur.eta = report;
      }
    }
    if (pyGet(r, "subtype") === "compact_boundary") {
      // A compaction leaves NO usage record anywhere; its boundary record's
      // preTokens is what was fed to the summariser, charged at the
      // cache-read rate, and its durationMs how long it took.  An AUTO
      // compaction lands inside whatever turn was running, so it gets a
      // turn of its own unless the one open is the /compact that asked for
      // it.  The Python's comment has the measurements.
      const md = pyOr(pyGet(r, "compactMetadata"), {});
      if (cur === null || cur.n || pyStrip(cur.text) !== "/compact") {
        cur = _newTurn(pyStr(pyOr(pyGet(r, "timestamp"), "")),
          `/compact (${pyStr(pyOr(pyGet(md, "trigger"), "auto"))})`);
        turns.push(cur);
      }
      cur.cr = num0(pyGet(md, "preTokens"));
      cur.usd[2] = cur.cr * P_CR;
      cur.n = 1;
      cur.dur = num0(pyGet(md, "durationMs")) / 1000.0;
      cur.compact = true;
    } else if (pyGet(r, "subtype") === "stop_hook_summary" &&
      !pyTruthy(pyGet(r, "isSidechain"))) {
      lastStop = pyOr(tsEpoch(pyOr(pyGet(r, "timestamp"), "")), lastStop);
      // The transcript's own record that a Stop hook RAN: the only mark in
      // the file of where a previous cost line drew its window.
      settled = turns.length;
    } else if (pyTruthy(pyGet(r, "isCompactSummary")) && cur !== null &&
      pyTruthy(cur.compact)) {
      // What the summariser WROTE, estimated from the text: the only
      // estimate on either row.
      const c = pyDig(r, "message", "content");
      if (typeof c === "string") {
        cur.out = Math.trunc(pyLen(c) / SUMMARY_CPT);
        cur.usd[1] = cur.out * P_OUT;
      }
    } else if (pyGet(r, "type") === "assistant" &&
      pyTruthy(pyDig(r, "message", "usage"))) {
      const k = pyOr(pyGet(r, "requestId"), pyDig(r, "message", "id")) ?? null;
      if (seen.has(k) || cur === null) continue;
      seen.add(k);
      const u = pyDig(r, "message", "usage");
      const f = numGet(u, "input_tokens");
      const cw = numGet(u, "cache_creation_input_tokens");
      const cr = numGet(u, "cache_read_input_tokens");
      const o = numGet(u, "output_tokens");
      cur.fresh += f;
      cur.cw += cw;
      cur.cr += cr;
      cur.out += o;
      cur.n += 1;
      // Priced here, per record, at the record's own model: `parts` carries
      // the same figure, so the parts total the whole EXACTLY.
      _addUsd(cur, tsEpoch(pyOr(pyGet(r, "timestamp"), "")),
        pyDig(r, "message", "model") ?? null, f, cw, cr, o);
      if (!pyTruthy(pyGet(r, "isSidechain"))) {
        // LAST-WRITE-WINS, but only over readings that exist: an
        // interrupted request is written with every usage field zero.
        const c = f + cw + cr;
        if (c) cur.ctx = c;
      }
    }
    // Every stamped record of the ANSWER moves the turn's end, not just the
    // billed ones; isWork keeps the user's own time out of it.
    if (cur !== null && isWork(r)) {
      const t = tsEpoch(pyOr(pyGet(r, "timestamp"), ""));
      if (t !== null) cur.t1 = t;
    }
  }

  const late = _foldAgents(turns, byPid, agentsOf(seen), lastStop, offsets,
    ends, held);

  // Context growth per turn.  The first turn gets null rather than its own
  // absolute size, and `prev` SKIPS a turn that carries no reading, so the
  // prompt after a /compact reports the drop across it.
  const out: Turn[] = [];
  let prev: TurnBuild | null = null;
  for (const t of turns) {
    const dctx = prev !== null && t.ctx ? t.ctx - prev.ctx : null;
    // A compaction's time is its durationMs, the summariser's, which runs
    // no tool.
    const [tool_s, blocked_s] = pyTruthy(t.compact) ? [0.0, 0.0]
      : turnClock(t.tools, t.waits, t.t0, t.t1);
    out.push(turn({
      ts: t.ts, text: t.text, fresh: t.fresh, cache_write: t.cw,
      cache_read: t.cr, out: t.out, ctx: t.ctx, calls: t.n, dctx,
      usd_in: t.usd[0], usd_out: t.usd[1], usd_cr: t.usd[2], usd_cw: t.usd[3],
      compact: pyTruthy(t.compact), reported: out.length < settled,
      parts: [...t.parts], agent_calls: t.an, agent_ids: [...t.aids],
      dur_s: pyTruthy(t.dur) ? t.dur!
        : pyTruthy(t.t0) && pyTruthy(t.t1) && t.t1! > t.t0! ? t.t1! - t.t0!
        : 0.0,
      tool_s, blocked_s, agent_model_s: t.am, agent_tool_s: t.at,
      prompt_id: pyTruthy(t.compact) ? "" : t.pid,
      turn_index: pyTruthy(t.compact) ? null : t.tidx,
      lines_added: t.la, lines_removed: t.lr, eta: t.eta,
    }));
    if (t.ctx) prev = t;
  }
  if (late.size) {
    for (const [path, t] of late) out.push(lateAgentTurn(t, path, label));
    out.sort((a, b) => cmpStr(a.ts, b.ts));
  }
  return out;
}

/** Freeze the synthetic turn _foldAgents built for late agent records.
 *
 * `calls` is 0 and `agent` is set, which between them keep it out of every
 * "the prompt to report" selection and out of the settle wait; `ctx` is 0
 * so the Δctx walk steps over it; `reported` is false because the records
 * in it are, by construction, ones no Stop has seen. */
export function lateAgentTurn(t: TurnBuild, path = "",
  label: (path: string) => [string, string] = noSidecar): Turn {
  const [agent_id, agent_name] = label(path);
  return turn({
    ts: t.ts, text: t.text, fresh: t.fresh, cache_write: t.cw,
    cache_read: t.cr, out: t.out, ctx: 0, calls: 0, dur_s: 0.0, dctx: null,
    usd_in: t.usd[0], usd_out: t.usd[1], usd_cr: t.usd[2], usd_cw: t.usd[3],
    parts: [...t.parts], agent_calls: t.an, agent_ids: [...t.aids],
    agent: true, agent_model_s: t.am, agent_tool_s: t.at,
    lines_added: t.la, lines_removed: t.lr, agent_id, agent_name,
  });
}

/** The turn opened last, whether or not it has called yet: what the
 * redesign's running 🎤 row draws, so a fresh turn reads zeros rather than
 * the turn before.  Neither a compaction nor a late agent turn is a
 * prompt; null for a transcript with none. */
export function openTurn(turns: readonly Turn[]): Turn | null {
  for (let i = turns.length - 1; i >= 0; i--) {
    if (!turns[i].compact && !turns[i].agent) return turns[i];
  }
  return null;
}

// How long the Stop hook waits for the turn it is about to report to appear
// in the transcript, and how often it looks: room for the write to land,
// nowhere near the hook's budget.
export const SETTLE_S = 1.5;
export const SETTLE_POLL_S = 0.025;

/** Has the turn being reported billed anything yet?  The last turn that is
 * not a synthetic agents turn, which sorts in by stamp and bills no
 * calls. */
export function _settled(turns: readonly Turn[]): boolean {
  for (let i = turns.length - 1; i >= 0; i--) {
    if (!turns[i].agent) return Boolean(turns[i].calls);
  }
  return false;
}
