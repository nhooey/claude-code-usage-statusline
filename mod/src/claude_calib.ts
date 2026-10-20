// The plan-window shares and their calibration, from claude.py.
//
// claude.py is the Claude CLI's orchestration and rendering as well as its
// accounting; this is the accounting part of it: what a turn, a session
// and the machine spent inside each plan window, and the dollars per point
// of plan reading that turn a spend into a share.  Each function keeps its
// Python name in camelCase (`_window_costs` is `_windowCosts`), so a change
// to one names the place to change in the other.
//
// The Python reads three things from module state that are arguments here:
// the plan snapshot (`limits_snapshot()`, `snap`), the clock, and where the
// files are (`CalibEnv`).  Everything here is pure; the I/O, the projects
// glob, the scan's per-file cache and the calibration cache, is in
// claude_calib_node.ts for Node, and in the mod's handlers for the mod,
// which runs with no Node and reads through `$`.
//
// What does not carry over from Python by itself, decided once:
//
//   - Time.  The window boundaries are NAIVE LOCAL datetimes in the Python,
//     compared as wall-clock times and turned into instants by
//     datetime.timestamp(), which has its own answer for a time in a DST gap
//     or fold.  A `Naive` here is that wall-clock time as seconds counted as
//     if it were UTC, and `_naiveTimestamp` is the Python's search for the
//     instant, step for step.  Both read the process's TZ, as the Python's
//     localtime does.
//   - Keys.  The scan dedupes request ids in Python sets, where 1, 1.0 and
//     True are one key and a list is no key at all (TypeError).  `_idKey`
//     spells that out.  json.loads hands back ONE NaN object for every NaN
//     it reads, so every NaN id is the same key, by identity.  An integer
//     id past 2**53 loses its precision, as everywhere in the ports.
//   - Crashes.  A malformed record the scan cannot price (a message that is
//     not an object, a token count that is a string) raises in the Python
//     and takes the whole calibration with it; its callers draw "?".  The
//     port throws there too, since carrying on would print a figure where
//     the Python prints none.  A count too large for a float, which raises
//     OverflowError in Python, is Infinity here.
//   - Rounding.  `round` rounds half to even; see `_pyRound`.
//   - Sums.  Left to right, as 3.9's sum() adds; 3.12's compensates.
//   - Caches.  The calibration cache is one file both write and read, named
//     by spec/state.jsonc (state.ts).  The scan's cost cache is still each
//     port's own: the Python keys it by a digest of its own source, this by
//     the mod's version.
//   - File order.  The scan visits files in the order the directory lists
//     them, which is the filesystem's, as glob.glob does.  A request id in
//     two files is billed at the first, so the order can matter; the shared
//     cases hand the Python's order in through `CalibEnv.glob`.

import { STAMP_FMT } from "./spec.ts";
import type { Dict } from "./py.ts";
import {
  daysFromCivil, daysIn, isDict, pyAsciiDigits, pyGet, pyHas, pyOr, PY_SPACE,
  pyTruthy, utf8,
} from "./py.ts";
import { pyFloat, pyJsonDumps, pyJsonLoads } from "./sources.ts";
import { stateName } from "./state.ts";
import { _price, pyStr, tsEpoch, turnTimes } from "./claude_records.ts";
import type { Transcript, Turn } from "./claude_records.ts";
import { limitsEqual, NO_LIMITS } from "./claude_sources.ts";
import type { Limits } from "./claude_sources.ts";

export const CALIB_TTL = 300;  // the scan walks transcripts; five minutes is
                               // plenty

// The smallest plan reading that can serve as the DIVISOR of a calibration.
// A reading quantised to whole percent is uncertain by half a point, ±50٪
// at 1 and ±25٪ at 2; see the Python's note for what that cost and bought.
export const CALIB_MIN_PCT = 2.0;

// How much of a file, ending where the last scan stopped, has to read the
// same for the scan to trust that the file was only appended to since.
export const COST_TAIL_BYTES = 4096;
// How often a scan that is still reading saves what it has.
export const COST_SAVE_EVERY_S = 1.0;

/** limits_snapshot(): the plan reading one render is taken against. */
export type Snapshot = Dict;

/** Dollars per point of each window, or null.  A planted calibration cache
 * states them directly and may hold anything, which the readers divide by
 * as Python would, raising where it raises. */
export type Calib = { readonly sess?: unknown; readonly week?: unknown };

/** A naive local datetime: its wall-clock reading in seconds, counted from
 * 1970-01-01 00:00 as if it were UTC.  Two compare as the Python's do. */
export type Naive = number;

// ════════════════════════════════════════════════════════════════════════════
// Python's semantics, where JavaScript's differ.
// ════════════════════════════════════════════════════════════════════════════

/** round(x) to an int: half to even, and a NaN or an infinity raises. */
export function _pyRound(x: number): number {
  if (!Number.isFinite(x)) throw new RangeError("cannot round " + x);
  const f = Math.floor(x), d = x - f;
  const r = d > 0.5 ? f + 1 : d < 0.5 ? f : f % 2 === 0 ? f : f + 1;
  return r + 0;  // never -0: Python's int has no sign on zero
}

/** `a / b` for JSON values: a bool is 0 or 1, anything but a number
 * raises TypeError.  `b` is never zero here; every caller tests it first. */
function pyDiv(a: unknown, b: unknown): number {
  const n = (v: unknown): number => {
    if (typeof v === "boolean") return v ? 1 : 0;
    if (typeof v === "number") return v;
    throw new TypeError("unsupported operand type for /");
  };
  return n(a) / n(b);
}

/** `v * p` for a token count read off a record, which Python multiplies
 * when it is a number or a bool and raises TypeError on otherwise. */
function pyMulCount(v: unknown, p: number): number {
  if (typeof v === "boolean") return (v ? 1 : 0) * p;
  if (typeof v === "number") return v * p;
  throw new TypeError("can't multiply sequence by non-int of type 'float'");
}

/** A request id as a key of a Python set: equal ids get equal keys.  1,
 * 1.0 and True are one key, -0.0 and 0 another, every NaN json.loads made
 * a third; a list or a dict is unhashable and raises. */
export function _idKey(k: unknown): string {
  if (k === null || k === undefined) return "N";
  if (typeof k === "string") return "s" + k;
  if (typeof k === "boolean") return "n" + (k ? 1 : 0);
  if (typeof k === "number") return Number.isNaN(k) ? "nan" : "n" + (k + 0);
  throw new TypeError("unhashable type");
}

// ════════════════════════════════════════════════════════════════════════════
// Naive local datetimes.
// ════════════════════════════════════════════════════════════════════════════

const DAY = 86400;

function civilFromDays(z: number): [number, number, number] {
  z += 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor((doe - Math.floor(doe / 1460) +
    Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp + (mp < 10 ? 3 : -9);
  return [yoe + era * 400 + (m <= 2 ? 1 : 0), m, d];
}

/** datetime(y, mo, d, h, mi, s) as a Naive. */
export function naive(y: number, mo: number, d: number, h = 0, mi = 0,
  s = 0): Naive {
  return daysFromCivil(y, mo, d) * DAY + h * 3600 + mi * 60 + s;
}

/** A Naive's fields: year, month, day, hour, minute, second. */
function fields(n: Naive): number[] {
  const days = Math.floor(n / DAY), secs = n - days * DAY;
  return [...civilFromDays(days), Math.floor(secs / 3600),
    Math.floor(secs % 3600 / 60), secs % 60];
}

/** A Naive inside datetime's range, years 1 to 9999; outside it the
 * Python's arithmetic raises OverflowError. */
function inRange(n: Naive): Naive {
  const y = fields(n)[0];
  if (y < 1 || y > 9999) throw new RangeError("date value out of range");
  return n;
}

/** str(datetime), as "%s" writes a window start into the cache key, and
 * "None" for none. */
export function naiveStr(n: Naive | null): string {
  if (n === null) return "None";
  const [y, mo, d, h, mi, s] = fields(n);
  const p = (v: number, w = 2) => String(v).padStart(w, "0");
  return `${p(y, 4)}-${p(mo)}-${p(d)} ${p(h)}:${p(mi)}:${p(s)}`;
}

/** The wall clock at instant `u`, as localtime(u) reads it in the TZ.
 * Off datetime's calendar it raises, as CPython's local() does, so a
 * timestamp of the first or last day of the calendar can raise. */
function local(u: number): Naive {
  const t = new Date(u * 1000);
  return inRange(naive(t.getFullYear(), t.getMonth() + 1, t.getDate(),
    t.getHours(), t.getMinutes(), t.getSeconds()));
}

/** datetime.timestamp() of a naive datetime: the instant whose local wall
 * clock reads `n`.  CPython's local_to_seconds, step for step, with fold
 * 0: in a fold, the earlier of the two instants; in a gap, the wall clock
 * read with the offset from before it, which lands after the gap. */
export function _naiveTimestamp(n: Naive): number {
  const t = n;
  const a = local(t) - t;
  const u1 = t - a;
  const t1 = local(u1);
  let b: number;
  if (t1 === t) {
    const u2 = u1 - DAY;
    b = local(u2) - u2;
    if (a === b) return u1;
  } else {
    b = t1 - u1;
  }
  const u2 = t - b;
  if (local(u2) === t) return u2;
  if (t1 === t) return u1;
  return Math.max(u1, u2);
}

// strptime's regex for STAMP_FMT, "%Y-%m-%d %H:%M": \d is any Unicode
// digit and the space any run of whitespace.  Matched at the start, then
// held to the whole string, as strptime raises "unconverted data remains"
// on a match that stops short.
const STAMP_STRPTIME = (() => {
  if (STAMP_FMT !== "%Y-%m-%d %H:%M") {
    throw new Error("STAMP_STRPTIME is out of step with STAMP_FMT");
  }
  return new RegExp("^(\\p{Nd}\\p{Nd}\\p{Nd}\\p{Nd})-(1[0-2]|0[1-9]|[1-9])" +
    "-(3[01]|[12]\\p{Nd}|0[1-9]|[1-9]| [1-9])[" + PY_SPACE + "]+" +
    "(2[0-3]|[0-1]\\p{Nd}|\\p{Nd}):([0-5]\\p{Nd}|\\p{Nd})", "iu");
})();

/** datetime.strptime(v, STAMP_FMT), or null where it raises. */
export function _strptimeStamp(v: unknown): Naive | null {
  if (typeof v !== "string") return null;
  const m = STAMP_STRPTIME.exec(v);
  if (!m || m[0].length !== v.length) return null;
  const [y, mo, d, h, mi] = m.slice(1)
    .map((g) => parseInt(pyAsciiDigits(g), 10));
  if (y < 1 || d > daysIn(y, mo)) return null;
  return naive(y, mo, d, h, mi);
}

/** A transcript's UTC "…Z" stamp as a naive LOCAL datetime, or null.
 *
 * The window boundaries are naive local times, so both sides of every
 * comparison have to be in that one frame. */
export function _localNaive(ts: string): Naive | null {
  const e = tsEpoch(ts);
  if (e === null) return null;
  try {
    return inRange(local(e));
  } catch {
    return null;
  }
}

// ════════════════════════════════════════════════════════════════════════════
// The plan snapshot and the window boundaries.
// ════════════════════════════════════════════════════════════════════════════

/** A carried percentage back as a number, or null if it is not one. */
export function _pctNum(v: unknown): number | null {
  return pyFloat(v);
}

/** seed_limits_snapshot: the plan reading as the accounting reads it.
 *
 * The Python installs it in a module global for the render; here it is
 * returned, and every reader below takes it as `snap`.  `reading` gives a
 * non-secret identity that scopes the calibration cache. */
export function seedLimitsSnapshot(lim: Limits,
  reading: unknown = null): Snapshot {
  if (limitsEqual(lim, NO_LIMITS)) return {};
  const part = (k: string) => isDict(reading) ? pyGet(reading, k) : "";
  const scope = ["source", "account_name", "period_start"]
    .map((k) => pyStr(pyOr(part(k), ""))).join("\0");
  return { session_pct: _pctNum(lim.session_pct),
    session_resets_at: lim.session_reset,
    weekly_pct: _pctNum(lim.weekly_pct),
    weekly_resets_at: lim.weekly_reset,
    _scope: scope };
}

/** When the 5-hour and the weekly window opened, or null for either:
 * each reset time the snapshot publishes, less the window's length. */
export function _windowStarts(snap: Snapshot): [Naive | null, Naive | null] {
  const start = (key: string, delta: number): Naive | null => {
    const v = pyGet(snap, key);
    if (!pyTruthy(v)) return null;
    const at = _strptimeStamp(v);
    if (at === null) return null;
    try {
      return inRange(at - delta);
    } catch {
      return null;
    }
  };
  return [start("session_resets_at", 5 * 3600),
    start("weekly_resets_at", 7 * DAY)];
}

/** The calibration cache's key: the two window starts as "%s|%s". */
export function _windowsKey(ss: Naive | null, ws: Naive | null): string {
  return naiveStr(ss) + "|" + naiveStr(ws);
}

/** The selected plan reading as numeric cost-grid totals. */
export function planTotals(snap: Snapshot): { sess?: number; week?: number } {
  const sp = _pctNum(pyGet(snap, "session_pct"));
  const wp = _pctNum(pyGet(snap, "weekly_pct"));
  if (sp === null || wp === null) return {};
  return { sess: sp, week: wp };
}

// ════════════════════════════════════════════════════════════════════════════
// A turn's and a session's shares.
// ════════════════════════════════════════════════════════════════════════════

/** List-price cost of one turn: the four sums read_turns priced per
 * record, at each record's own model. */
export function turnCost(t: Turn): number {
  return t.usd_in + t.usd_out + t.usd_cr + t.usd_cw;
}

/** The part of one turn's cost that was billed at or after `start`.
 *
 * Split at the boundary by each billed part's own stamp; a stamp that will
 * not parse counts IN.  A compaction bills through no usage record, so it
 * has nothing stamped to split and goes whole by its prompt's stamp. */
export function turnCostSince(t: Turn, start: Naive | null): number {
  if (start === null) return turnCost(t);
  const edge = _naiveTimestamp(start);
  if (t.compact || t.parts.length === 0) {
    const ts = _localNaive(t.ts);
    return ts === null || ts >= start ? turnCost(t) : 0.0;
  }
  let sum = 0;
  for (const [e, c] of t.parts) if (e === null || e >= edge) sum += c;
  return sum;
}

/** One turn's share of each live window, counting only what it billed in
 * it, on the same boundaries as sessionShares. */
export function windowShares(t: Turn, calib: Calib, snap: Snapshot):
  { sess: number | null; week: number | null } {
  const [ss, ws] = _windowStarts(snap);
  const out: { sess: number | null; week: number | null } =
    { sess: null, week: null };
  for (const [key, start] of [["sess", ss], ["week", ws]] as const) {
    const unit = pyGet(calib, key);
    if (pyTruthy(unit)) out[key] = pyDiv(turnCostSince(t, start), unit);
  }
  return out;
}

/** What fraction of one prompt's cost went on re-reading, and on caching,
 * in whole percent rounded half to even; nulls for a turn with no cost. */
export function turnShares(t: Turn): [number | null, number | null] {
  const c = turnCost(t);
  if (c <= 0) return [null, null];
  return [_pyRound(100 * t.usd_cr / c), _pyRound(100 * t.usd_cw / c)];
}

/** turnShares over the whole session, summed before dividing. */
export function sessionCacheShares(turns: readonly Turn[]):
  [number | null, number | null] {
  let c = 0, cr = 0, cw = 0;
  for (const t of turns) c += turnCost(t);
  if (c <= 0) return [null, null];
  for (const t of turns) cr += t.usd_cr;
  for (const t of turns) cw += t.usd_cw;
  return [_pyRound(100 * cr / c), _pyRound(100 * cw / c)];
}

/** What THIS session put into each plan window, as a percentage of it:
 * every turn split at the window's start, over dollars per point. */
export function sessionShares(turns: readonly Turn[], calib: Calib,
  snap: Snapshot): { sess: number | null; week: number | null } {
  const out: { sess: number | null; week: number | null } =
    { sess: null, week: null };
  if (!pyTruthy(calib)) return out;
  const [ss, ws] = _windowStarts(snap);
  for (const [key, start] of [["sess", ss], ["week", ws]] as const) {
    const unit = pyGet(calib, key);
    if (!pyTruthy(unit) || start === null) continue;
    let sum = 0;
    for (const t of turns) sum += turnCostSince(t, start);
    out[key] = pyDiv(sum, unit);
  }
  return out;
}

/** What one turn, or the session, comes to: the figures document's
 * `accounting` entry. */
export interface Accounting {
  readonly cost_usd: number;
  readonly sess_share: number | null;
  readonly week_share: number | null;
  readonly read_share: number | null;
  readonly write_share: number | null;
  // How its time went and what it wrote, for the redesigned grid's ⌛
  // split and 💾; today's cells read none of these.
  readonly model_s: number;
  readonly tool_s: number;
  readonly blocked_s: number;
  readonly lines_added: number;
  readonly lines_removed: number;
  // The session's alone: when its earliest turn opened, the 🎮 rows' ⌛
  // start, or null with none stamped.
  readonly start_s?: number | null;
}

/** What one turn comes to: its cost, its share of each live window and
 * the shares of it spent re-reading and caching.  cost_group draws these.
 * The window shares read the plan snapshot, so this belongs to the first
 * stage, never to a render.  `model_s` and `tool_s` are turnTimes', the
 * main thread's and its agents' agent-seconds; `blocked_s` is the main
 * thread's waiting; the lines are the Turn's own. */
export function turnAccounting(t: Turn, calib: Calib, snap: Snapshot):
  Accounting {
  const tsh = windowShares(t, calib, snap);
  const [rd, wr] = turnShares(t);
  const [model_s, tool_s] = turnTimes(t);
  return { cost_usd: turnCost(t), sess_share: tsh.sess,
    week_share: tsh.week, read_share: rd, write_share: wr, model_s, tool_s,
    blocked_s: t.blocked_s, lines_added: t.lines_added,
    lines_removed: t.lines_removed };
}

/** turnAccounting over the whole session: every turn summed, left to
 * right, the shares worked out over the sum rather than added up.  The
 * split is agent-seconds and can add up to more than the session's age,
 * which the 🎮 rows count from `start_s`, its earliest turn's stamp. */
export function sessionAccounting(turns: readonly Turn[], calib: Calib,
  snap: Snapshot): Accounting {
  const sh = sessionShares(turns, calib, snap);
  const [rd, wr] = sessionCacheShares(turns);
  let cost = 0, model_s = 0, tool_s = 0, blocked_s = 0;
  let lines_added = 0, lines_removed = 0;
  for (const t of turns) cost += turnCost(t);
  const stamps = turns.map((t) => tsEpoch(t.ts))
    .filter((e): e is number => e !== null);
  const times = turns.map(turnTimes);
  for (const [m] of times) model_s += m;
  for (const [, tl] of times) tool_s += tl;
  for (const t of turns) {
    blocked_s += t.blocked_s;
    lines_added += t.lines_added;
    lines_removed += t.lines_removed;
  }
  return { cost_usd: cost, start_s: stamps.length ? Math.min(...stamps)
    : null, sess_share: sh.sess, week_share: sh.week,
    read_share: rd, write_share: wr, model_s, tool_s, blocked_s,
    lines_added, lines_removed };
}

/** sessionShares for (epoch, dollars) parts rather than turns: each part
 * in the window or not by its own stamp, an unstamped one in, and null for
 * a window with no start, as sessionShares leaves it. */
export function partsShares(parts: readonly (readonly [number | null,
  number])[], calib: Calib, snap: Snapshot):
  { sess: number | null; week: number | null } {
  const out: { sess: number | null; week: number | null } =
    { sess: null, week: null };
  if (!pyTruthy(calib)) return out;
  const [ss, ws] = _windowStarts(snap);
  for (const [key, start] of [["sess", ss], ["week", ws]] as const) {
    const unit = pyGet(calib, key);
    if (!pyTruthy(unit) || start === null) continue;
    const edge = _naiveTimestamp(start);
    let sum = 0;
    for (const [e, c] of parts) if (e === null || e >= edge) sum += c;
    out[key] = pyDiv(sum, unit);
  }
  return out;
}

/** The main thread's own cost and its share of each live window, apart
 * from its agents and with its compactions: the redesign's 🤖💬 row. */
export function ownAccounting(tr: Pick<Transcript, "own_usd" | "own_parts">,
  calib: Calib, snap: Snapshot):
  { cost_usd: number; sess_share: number | null; week_share: number | null } {
  const sh = partsShares(tr.own_parts, calib, snap);
  return { cost_usd: tr.own_usd, sess_share: sh.sess, week_share: sh.week };
}

/** turnAccounting for each turn, in order, and the same for the session:
 * the figures document's `accounting`. */
export function costAccounting(turns: readonly Turn[], calib: Calib,
  snap: Snapshot): { turns: Accounting[]; session: Accounting } {
  return { turns: turns.map((t) => turnAccounting(t, calib, snap)),
    session: sessionAccounting(turns, calib, snap) };
}

// ════════════════════════════════════════════════════════════════════════════
// The machine-wide scan.
// ════════════════════════════════════════════════════════════════════════════

/** One record the scan bills: its epoch (null for a stamp that will not
 * parse), its request id, and its list-price cost. */
export type Priced = [number | null, unknown, number];


/** One transcript line as (epoch, request id, list-price cost), or null
 * for anything the scan does not bill: a line that will not parse, a
 * record that is not an assistant's, or one with no usage or no stamp.
 * Throws where the Python raises; see the head of the file. */
export function _pricedRecord(line: Uint8Array): Priced | null {
  let r: unknown;
  try {
    r = pyJsonLoads(utf8(line, false, true));
  } catch {
    return null;
  }
  if (!isDict(r) || pyGet(r, "type") !== "assistant") return null;
  const m = pyOr(pyGet(r, "message"), {});
  if (!isDict(m)) throw new TypeError("message has no get");
  const u = pyGet(m, "usage");
  const ts = pyGet(r, "timestamp");
  if (!pyTruthy(u) || !pyTruthy(ts)) return null;
  const model = pyGet(m, "model");
  if (pyTruthy(model) && typeof model !== "string") {
    throw new TypeError("model has no lower");
  }
  const [pi, po, pr, pw] = _price(model);
  if (!isDict(u)) throw new TypeError("usage has no get");
  const n = (k: string) => pyGet(u, k, 0);
  const c = pyMulCount(n("input_tokens"), pi) +
    pyMulCount(n("output_tokens"), po) +
    pyMulCount(n("cache_read_input_tokens"), pr) +
    pyMulCount(n("cache_creation_input_tokens"), pw);
  // ts_epoch is lru_cached, so a list raises on hashing, and anything else
  // that is not a string raises on .split.
  if (typeof ts !== "string") throw new TypeError("timestamp is no str");
  return [tsEpoch(ts), pyOr(pyGet(r, "requestId"), pyGet(m, "id")), c];
}

/** Total spend in `files` since each window opened, in that order.
 *
 * Bounded by file mtime: nothing last written a day before the earlier
 * start can hold a record in either window.  A request id is billed once,
 * at its first record; a record whose stamp will not parse still claims its
 * id but bills nothing.  `files` is the projects glob; see _windowCosts. */
export function _windowCostsOf(sessStart: Naive | null,
  weekStart: Naive | null, files: readonly string[],
  mtime: (path: string) => number | null,
  records: (path: string) => Priced[],
  tick: () => void = () => {}): [number, number] {
  let sess = 0.0, week = 0.0;
  const seen = new Set<string>();
  const starts = [sessStart, weekStart].filter((s) => s !== null);
  const earliest = starts.length ? Math.min(...starts) : null;
  const cutoff = earliest === null ? null
    : _naiveTimestamp(inRange(earliest - DAY));
  // Epochs on both sides: the records are kept as epochs, and a naive
  // local start's timestamp is the instant _localNaive compared with.
  const earlyE = earliest === null ? null : _naiveTimestamp(earliest);
  const weekE = weekStart === null ? null : _naiveTimestamp(weekStart);
  const sessE = sessStart === null ? null : _naiveTimestamp(sessStart);
  for (const fp of files) {
    tick();
    if (cutoff !== null) {
      const mt = mtime(fp);
      if (mt === null || mt < cutoff) continue;
    }
    for (const [t, k, c] of records(fp)) {
      const key = _idKey(k);
      if (seen.has(key)) continue;
      seen.add(key);
      if (t === null) continue;
      if (earlyE !== null && t < earlyE) continue;
      if (weekE === null || t >= weekE) week += c;
      if (sessE !== null && t >= sessE) sess += c;
    }
  }
  return [sess, week];
}

/** Dollars per one percent of each plan window, from a scan and the
 * readings it was taken with.
 *
 * `cached` is the calibration cache for these windows, or null; `scan`
 * runs the scan when there is none.  A cache with no "windows" is a
 * planted fixture, which states the two units directly.  Otherwise both
 * halves of the ratio come off one moment, the cache's or the scan's, and
 * no unit is derived from a reading under CALIB_MIN_PCT. */
export function _calibrationOf(snap: Snapshot, cached: Dict | null,
  scan: (() => [number, number]) | null): Calib {
  const out: { sess: unknown; week: unknown } = { sess: null, week: null };
  if (cached !== null && !pyHas(cached, "windows")) {
    return { sess: pyGet(cached, "sess"), week: pyGet(cached, "week") };
  }
  let sc: unknown, wc: unknown;
  let sp = pyGet(snap, "session_pct"), wp = pyGet(snap, "weekly_pct");
  if (cached !== null) {
    sc = pyGet(cached, "sess_cost");
    wc = pyGet(cached, "week_cost");
    sp = pyGet(cached, "sess_pct");
    wp = pyGet(cached, "week_pct");
  } else if (scan === null) {
    return out;
  } else {
    [sc, wc] = scan();
  }
  const spn = _pctNum(sp), wpn = _pctNum(wp);
  if (pyTruthy(spn) && spn! >= CALIB_MIN_PCT && sc !== null) {
    out.sess = pyDiv(sc, spn);
  }
  if (pyTruthy(wpn) && wpn! >= CALIB_MIN_PCT && wc !== null) {
    out.week = pyDiv(wc, wpn);
  }
  return out;
}

/** The calibration cache's file name: spec/state.jsonc's calibration
 * kind, keyed by the snapshot's scope, the name the Python's
 * calibration_cache_path gives.  The windows are inside the file. */
export function _calibrationCacheName(snap: Snapshot): string {
  return stateName("calibration", pyStr(pyGet(snap, "_scope", "")));
}

/** The calibration cache's text, byte for byte as calib_cache_text writes
 * it: compact, in this key order, every number a float. */
export function _calibCacheText(windows: string, sc: unknown, wc: unknown,
  sp: unknown, wp: unknown): string {
  return pyJsonDumps({ windows, sess_cost: sc, week_cost: wc,
    sess_pct: sp, week_pct: wp }, false,
  ["sess_cost", "week_cost", "sess_pct", "week_pct"]);
}
