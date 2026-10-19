// Usage source selection and the versioned, safe custom-command contract.
//
// A port of coding_agent_usage_line/sources.py, as far as the band needs it:
// the version-1 reading (normalise and its validators), the payload's own
// rate_limits (nativeReading), the scoped cache (cachedReading and the
// refresh cadence), the custom command (commandReading), the tracker
// (claudeUsageTracker) and collect, which chooses between them.  Each
// function keeps its Python name in camelCase, so a change to one names the
// place to change in the other.
//
// NOT PORTED: the HTTP sources (anthropic-admin, openai-admin,
// experimental-claude-oauth, experimental-codex-api, with request_json,
// request_pages and _retry_after) and the Codex app-server collector.  The
// band is Claude's and reads the tracker; validateSource still accepts their
// names, so a spec that names one fails the way an unavailable source does
// (no reading) rather than as an unknown source.
//
// What Python gives for free and this file spells out, because the shared
// cases would otherwise drift on it: float() on strings, str() on JSON
// values, json.loads' NaN and Infinity, datetime.fromisoformat as 3.9
// parses it, and "%.6f"'s half-even rounding.  They are at the top, under
// "Python's semantics"; truthiness, dict.get and strip() are in py.ts,
// shared with the other ports.
//
// The I/O, the cache files, running a command and reading the tracker, is
// in sources_node.ts for Node and in the mod's handlers for the mod, which
// runs with no Node.  collect takes them as arguments, and everything here
// is pure.

import { sha256Hex } from "./sha256.ts";

import type { Dict } from "./py.ts";
import {
  daysFromCivil, daysIn, isDict, pyAsciiDigits, pyFloatRepr, pyGet, pyStrip,
  pyTruthy, utf8,
} from "./py.ts";

export type { Dict };
export type Reading = Dict;

export const VALID_SOURCES = [
  "auto", "native", "none", "off", "claude-usage-tracker",
  "codex-app-server", "anthropic-admin", "openai-admin",
  "experimental-claude-oauth", "experimental-codex-api",
] as const;

// ════════════════════════════════════════════════════════════════════════════
// Python's semantics.
// ════════════════════════════════════════════════════════════════════════════

const DIGITS = "[0-9](?:_?[0-9])*";
const PY_FLOAT = new RegExp(
  "^[+-]?(?:(?:" + DIGITS + "(?:\\.(?:" + DIGITS + ")?)?|\\." + DIGITS +
  ")(?:[eE][+-]?" + DIGITS + ")?|inf|infinity|nan)$", "i");

// float(text), or null where Python raises ValueError.  Like float(), it
// reads any Unicode decimal digit as its ASCII one.
export function pyFloatText(text: string): number | null {
  const s = pyStrip(pyAsciiDigits(text));
  if (!PY_FLOAT.test(s)) return null;
  const body = s.replace(/^[+-]/, "").toLowerCase();
  const sign = s.startsWith("-") ? -1 : 1;
  if (body === "nan") return NaN;
  if (body === "inf" || body === "infinity") return sign * Infinity;
  return Number(s.replaceAll("_", ""));
}

// float(value), or null where Python raises TypeError or ValueError.
// Bytes come from a plist's <data>; float() reads them as ASCII.
export function pyFloat(value: unknown): number | null {
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "number") return value;
  if (typeof value === "string") return pyFloatText(value);
  if (value instanceof Uint8Array) {
    if (value.some((b) => b > 127)) return null;
    return pyFloatText(String.fromCharCode(...value));
  }
  return null;
}

// str() of a JSON value.  JSON's 5 and 5.0 are one number here, so a whole
// number prints as Python's int would; that is the one place it can differ.
export function pyStr(value: unknown): string {
  if (typeof value === "string") return value;
  return pyRepr(value);
}

function pyRepr(value: unknown): string {
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (typeof value === "number") {
    return Number.isInteger(value) ? BigInt(value).toString()
      : pyFloatRepr(value);
  }
  if (typeof value === "string") {
    const quote = value.includes("'") && !value.includes('"') ? '"' : "'";
    let out = "";
    for (const ch of value) {
      const code = ch.codePointAt(0)!;
      if (ch === "\\" || ch === quote) out += "\\" + ch;
      else if (ch === "\n") out += "\\n";
      else if (ch === "\r") out += "\\r";
      else if (ch === "\t") out += "\\t";
      else if (code < 32 || code === 127) {
        out += "\\x" + code.toString(16).padStart(2, "0");
      } else out += ch;
    }
    return quote + out + quote;
  }
  if (Array.isArray(value)) return "[" + value.map(pyRepr).join(", ") + "]";
  if (isDict(value)) {
    return "{" + Object.entries(value)
      .map(([k, v]) => pyRepr(k) + ": " + pyRepr(v)).join(", ") + "}";
  }
  return String(value);
}

// json.loads: JSON, plus the NaN, Infinity and -Infinity Python reads and
// writes.  JSON.parse refuses those, so a command printing one would be a
// failed reading here and a reading with that one field missing in Python.
export function pyJsonLoads(text: string): unknown {
  let i = 0;
  const fail = (): never => {
    throw new SyntaxError("invalid JSON at " + i);
  };
  const ws = () => {
    while (i < text.length && " \t\n\r".includes(text[i])) i++;
  };
  const NUMBER = /-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?/y;
  const value = (): unknown => {
    ws();
    const ch = text[i];
    if (ch === "{") {
      i++;
      const obj: Dict = Object.create(null);
      ws();
      if (text[i] === "}") { i++; return obj; }
      for (;;) {
        ws();
        if (text[i] !== '"') fail();
        const key = string();
        ws();
        if (text[i++] !== ":") fail();
        obj[key] = value();
        ws();
        const sep = text[i++];
        if (sep === "}") return obj;
        if (sep !== ",") fail();
      }
    }
    if (ch === "[") {
      i++;
      const arr: unknown[] = [];
      ws();
      if (text[i] === "]") { i++; return arr; }
      for (;;) {
        arr.push(value());
        ws();
        const sep = text[i++];
        if (sep === "]") return arr;
        if (sep !== ",") fail();
      }
    }
    if (ch === '"') return string();
    for (const [word, val] of [["true", true], ["false", false],
                               ["null", null], ["NaN", NaN],
                               ["Infinity", Infinity],
                               ["-Infinity", -Infinity]] as const) {
      if (text.startsWith(word, i)) { i += word.length; return val; }
    }
    NUMBER.lastIndex = i;
    const m = NUMBER.exec(text);
    if (!m) fail();
    i += m![0].length;
    return Number(m![0]);
  };
  const string = (): string => {
    i++;
    let out = "";
    for (;;) {
      if (i >= text.length) fail();
      const ch = text[i++];
      if (ch === '"') return out;
      if (ch < " ") fail();
      if (ch !== "\\") { out += ch; continue; }
      const esc = text[i++];
      const simple: Dict = { '"': '"', "\\": "\\", "/": "/", b: "\b",
                             f: "\f", n: "\n", r: "\r", t: "\t" };
      if (esc !== undefined && Object.hasOwn(simple, esc)) {
        out += simple[esc];
      } else if (esc === "u") {
        const hex = text.slice(i, i + 4);
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail();
        out += String.fromCharCode(parseInt(hex, 16));
        i += 4;
      } else fail();
    }
  };
  const result = value();
  ws();
  if (i !== text.length) fail();
  return result;
}

// json.dumps with ensure_ascii, the separators and sort_keys given.  A
// whole number is written as an int; `floats` names the keys Python holds
// as floats, which it writes with ".0".
export function pyJsonDumps(value: unknown, sortKeys = false,
                            floats: readonly string[] = [],
                            key = ""): string {
  if (value === null || value === undefined) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "number") {
    if (Number.isNaN(value)) return "NaN";
    if (!Number.isFinite(value)) return value > 0 ? "Infinity" : "-Infinity";
    if (Number.isInteger(value) && !floats.includes(key)) {
      return BigInt(value).toString();
    }
    return pyFloatRepr(value);
  }
  if (typeof value === "string") {
    let out = '"';
    for (let j = 0; j < value.length; j++) {
      const c = value.charCodeAt(j);
      const ch = value[j];
      if (ch === '"') out += '\\"';
      else if (ch === "\\") out += "\\\\";
      else if (ch === "\n") out += "\\n";
      else if (ch === "\r") out += "\\r";
      else if (ch === "\t") out += "\\t";
      else if (ch === "\b") out += "\\b";
      else if (ch === "\f") out += "\\f";
      else if (c < 32 || c > 126) {
        out += "\\u" + c.toString(16).padStart(4, "0");
      } else out += ch;
    }
    return out + '"';
  }
  if (Array.isArray(value)) {
    return "[" + value.map((v) => pyJsonDumps(v, sortKeys, floats))
      .join(",") + "]";
  }
  if (isDict(value)) {
    const keys = Object.keys(value);
    if (sortKeys) keys.sort(comparePy);
    return "{" + keys.map((k) => pyJsonDumps(k) + ":" +
      pyJsonDumps(value[k], sortKeys, floats, k)).join(",") + "}";
  }
  throw new TypeError("not JSON serializable");
}

// Python sorts strings by code point; JavaScript's < compares UTF-16 units,
// which differ above U+FFFF.
function comparePy(a: string, b: string): number {
  const x = [...a].map((c) => c.codePointAt(0)!);
  const y = [...b].map((c) => c.codePointAt(0)!);
  for (let j = 0; j < Math.min(x.length, y.length); j++) {
    if (x[j] !== y[j]) return x[j] - y[j];
  }
  return x.length - y.length;
}

// Python rounds a timestamp's fraction to whole microseconds, half to even,
// before it turns it into a datetime, so x.9999996 is the NEXT second.  A
// JavaScript Date would truncate it to the millisecond below.
export function splitTimestamp(t: number): [number, number] {
  let secs = Math.floor(t);
  const scaled = (t - secs) * 1e6;
  let us = Math.round(scaled);
  if (Math.abs(scaled - Math.trunc(scaled)) === 0.5 && us % 2 !== 0) us -= 1;
  if (us >= 1e6) { us -= 1e6; secs += 1; }
  return [secs, us];
}

// datetime.fromisoformat as Python 3.9's C implementation parses, which is
// what /usr/bin/python3 runs the status line with: YYYY-MM-DD, any one
// separator, HH[:MM[:SS[.fff[fff]]]], and an offset of +HH:MM[:SS[.ffffff]].
// Newer Pythons accept more (a bare "Z", basic formats); a reading that
// leans on those is unavailable to both.  The C walks UTF-8 bytes with a
// NUL after the last, and so does this, so its corner cases land the same
// way.  The result is Unix seconds, a naive time read as UTC, as epoch()
// reads it; null where Python raises.
export function fromIsoformat(text: string): number | null {
  const head = text.slice(0, 10);
  if (/[^\x00-\x7f]/.test(head)) return null;
  const sepCode = text.codePointAt(10);
  const sepLen = sepCode !== undefined && sepCode > 0xffff ? 2 : 1;
  const bytes = new TextEncoder().encode(head);
  const timeBytes = text.length > 10
    ? new TextEncoder().encode(text.slice(10 + sepLen)) : null;
  const at = (buf: Uint8Array, k: number) => (k < buf.length ? buf[k] : 0);
  const digits = (buf: Uint8Array, k: number, n: number): number | null => {
    let v = 0;
    for (let j = 0; j < n; j++) {
      const d = at(buf, k + j) - 48;
      if (d < 0 || d > 9) return null;
      v = v * 10 + d;
    }
    return v;
  };
  const year = digits(bytes, 0, 4);
  if (year === null || at(bytes, 4) !== 45) return null;
  const month = digits(bytes, 5, 2);
  if (month === null || at(bytes, 7) !== 45) return null;
  const day = digits(bytes, 8, 2);
  if (day === null) return null;

  // parse_hh_mm_ss_ff: [HH[:MM[:SS]]][.fff[fff]] between start and end.
  const hhmmss = (buf: Uint8Array, start: number, end: number,
                  out: number[]): number => {
    let p = start;
    let i = 0;
    for (; i < 3; i++) {
      const v = digits(buf, p, 2);
      if (v === null) return -3;
      out[i] = v;
      p += 2;
      const c = at(buf, p++);
      if (p >= end) return c !== 0 ? 1 : 0;
      if (c === 58) continue;
      if (c === 46) break;
      return -4;
    }
    const remains = end - p;
    if (remains !== 6 && remains !== 3) return -3;
    const us = digits(buf, p, remains);
    if (us === null) return -3;
    out[3] = remains === 3 ? us * 1000 : us;
    return 0;
  };

  const t = [0, 0, 0, 0];
  let offset = 0, offsetUs = 0;
  if (timeBytes !== null) {
    const end = timeBytes.length;
    let tz = 0;
    do {
      const c = at(timeBytes, tz);
      if (c === 43 || c === 45) break;
    } while (++tz < end);
    const rv = hhmmss(timeBytes, 0, tz, t);
    if (rv < 0) return null;
    if (tz === end) {
      if (rv === 1) return null;
    } else {
      const tzlen = end - tz;
      if (tzlen !== 6 && tzlen !== 9 && tzlen !== 16) return null;
      const sign = at(timeBytes, tz) === 45 ? -1 : 1;
      const z = [0, 0, 0, 0];
      const zr = hhmmss(timeBytes, tz + 1, end, z);
      if (zr !== 0) return null;
      offset = sign * (z[0] * 3600 + z[1] * 60 + z[2]);
      offsetUs = sign * z[3];
      // timezone() takes an offset strictly inside a day.
      if (Math.abs(offset * 1e6 + offsetUs) >= 86400e6) return null;
    }
  }
  if (year < 1 || month < 1 || month > 12) return null;
  if (day < 1 || day > daysIn(year, month)) return null;
  if (t[0] > 23 || t[1] > 59 || t[2] > 59) return null;
  const secs = daysFromCivil(year, month, day) * 86400 +
    t[0] * 3600 + t[1] * 60 + t[2] - offset;
  // total_seconds() divides whole microseconds by a million, once.
  return (secs * 1e6 + t[3] - offsetUs) / 1e6;
}

// ════════════════════════════════════════════════════════════════════════════
// The version-1 reading.
// ════════════════════════════════════════════════════════════════════════════

export function safeText(value: unknown, maximum = 128): string | null {
  if (typeof value !== "string" || !value) return null;
  // len() counts code points, not UTF-16 units.
  if ([...value].length > maximum) return null;
  for (const ch of value) {
    const c = ch.codePointAt(0)!;
    if (c < 32 || (c >= 127 && c <= 159)) return null;
  }
  return value;
}

export const MIN_EPOCH = 0.0, MAX_EPOCH = 4102444800.0;  // 1970 through 2100

export function epoch(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) && value >= MIN_EPOCH && value <= MAX_EPOCH
      ? value : null;
  }
  if (typeof value === "string") {
    const stamp = fromIsoformat(value.replaceAll("Z", "+00:00"));
    return stamp !== null && stamp >= MIN_EPOCH && stamp <= MAX_EPOCH
      ? stamp : null;
  }
  return null;
}

export function number(value: unknown, upper: number | null = null):
    number | null {
  if (typeof value === "boolean") return null;
  const n = pyFloat(value);
  if (n === null || !Number.isFinite(n) || n < 0) return null;
  if (upper !== null && n > upper) return null;
  return n;
}

const TOKEN_NAMES = ["input_tokens", "cached_input_tokens", "output_tokens",
                     "reasoning_output_tokens"];

export function tokens(value: unknown): Dict {
  const v = isDict(value) ? value : {};
  const out: { [k: string]: number | null } = {};
  for (const name of TOKEN_NAMES) out[name] = number(pyGet(v, name));
  // Cached read is a subset of input; creation is input but not cache-read.
  const inp = out.input_tokens, cached = out.cached_input_tokens;
  if (inp !== null && cached !== null && cached > inp) return {};
  const outp = out.output_tokens, reasoning = out.reasoning_output_tokens;
  if (outp !== null && reasoning !== null && reasoning > outp) return {};
  const kept: Dict = {};
  for (const name of TOKEN_NAMES) {
    if (out[name] !== null) kept[name] = out[name];
  }
  return kept;
}

// Whitelist the v1 source fields; malformed numbers are unavailable.
export function normalise(value: unknown, source = ""): Reading {
  if (!isDict(value) || pyGet(value, "schema_version") !== 1) return {};
  const wins: Dict[] = [];
  const rawBuckets = pyGet(value, "buckets");
  let windows: Dict[];
  // Buckets are canonical.  Do not combine them with an old flat shadow,
  // since a cached canonical result can otherwise double every quota.
  if (rawBuckets !== null) {
    if (!Array.isArray(rawBuckets)) return {};
    windows = [];
    for (const bucket of rawBuckets) {
      if (!isDict(bucket)) continue;
      const bucketId = safeText(pyGet(bucket, "id"), 128);
      const nested = pyGet(bucket, "windows");
      if (bucketId === null || !Array.isArray(nested)) continue;
      for (const nestedWindow of nested) {
        if (!isDict(nestedWindow)) continue;
        const copy: Dict = { ...nestedWindow, bucket_id: bucketId };
        if (Object.hasOwn(bucket, "label") &&
            !Object.hasOwn(copy, "heading")) {
          copy.heading = bucket.label;
        }
        for (const field of ["model", "feature"]) {
          if (Object.hasOwn(bucket, field) && !Object.hasOwn(copy, field)) {
            copy[field] = bucket[field];
          }
        }
        windows.push(copy);
      }
    }
  } else {
    const flat = pyGet(value, "windows", []);
    if (!Array.isArray(flat)) return {};
    windows = flat.filter(isDict).map((w) => ({ ...w }));
  }
  for (const w of windows) {
    const ident = safeText(pyGet(w, "id"));
    if (ident === null) continue;
    const item: Dict = {
      id: ident,
      duration_seconds: number(pyGet(w, "duration_seconds")),
      used_percent: number(pyGet(w, "used_percent"), 100),
      resets_at: epoch(pyGet(w, "resets_at")),
    };
    for (const field of ["bucket_id", "heading", "model", "feature"]) {
      const safe = safeText(pyGet(w, field), 128);
      if (safe !== null) item[field] = safe;
    }
    // Missing usage is a valid quota window; it is not invented as zero.
    wins.push(item);
  }
  const rawAccount = pyGet(value, "account");
  const account: Dict = isDict(rawAccount) ? rawAccount : {};
  const safeAccount: Dict = {};
  for (const name of ["period_start", "period_end"]) {
    const e = epoch(pyGet(account, name));
    if (e !== null) safeAccount[name] = e;
  }
  Object.assign(safeAccount, tokens(account));
  const cost = number(pyGet(account, "cost_usd"));
  if (cost !== null) safeAccount.cost_usd = cost;
  const scope = safeText(pyGet(account, "scope"), 64);
  if (scope !== null) safeAccount.scope = scope;
  const ps = safeAccount.period_start, pe = safeAccount.period_end;
  if (typeof ps === "number" && typeof pe === "number" && pe < ps) return {};
  // A Map, not an object: an object would put a bucket called "1" before
  // one called "a" whatever order they came in.
  const grouped = new Map<string, Dict>();
  for (const window of wins) {
    const bucketId = (window.bucket_id as string | undefined) || "default";
    let bucket = grouped.get(bucketId);
    if (bucket === undefined) {
      bucket = { id: bucketId,
                 label: (window.heading as string | undefined) || "default",
                 windows: [] };
      grouped.set(bucketId, bucket);
    }
    for (const field of ["model", "feature"]) {
      if (window[field] !== undefined) bucket[field] = window[field];
    }
    const child: Dict = {};
    for (const [k, v] of Object.entries(window)) {
      if (!["bucket_id", "heading", "model", "feature"].includes(k)) {
        child[k] = v;
      }
    }
    (bucket.windows as Dict[]).push(child);
  }
  return { schema_version: 1, source, as_of: epoch(pyGet(value, "as_of")),
           buckets: [...grouped.values()], account: safeAccount };
}

// An envelope alone is not a source response and must not replace cache.
export function hasReading(value: unknown): boolean {
  if (!isDict(value)) return false;
  const rawAccount = pyGet(value, "account");
  const account: Dict = isDict(rawAccount) ? rawAccount : {};
  const buckets = pyGet(value, "buckets");
  for (const bucket of Array.isArray(buckets) ? buckets : []) {
    const windows = isDict(bucket) ? pyGet(bucket, "windows") : null;
    for (const window of Array.isArray(windows) ? windows : []) {
      if (isDict(window) && number(pyGet(window, "used_percent")) !== null) {
        return true;
      }
    }
  }
  return ["input_tokens", "cached_input_tokens", "output_tokens",
          "reasoning_output_tokens", "cost_usd"]
    .some((name) => number(pyGet(account, name)) !== null);
}

// Re-whitelist cache content and make stale/expired state visible.
export function cachedReading(value: unknown, source: string, now: number,
                              ttl: number): Reading {
  const clean = normalise(value, source);
  if (!hasReading(clean)) return {};
  const asOf = epoch(pyGet(value as Dict, "as_of"));
  clean.as_of = asOf;
  clean.stale = asOf === null || now - asOf >= ttl;
  for (const name of ["fetched_at", "attempted_at", "retry_at",
                      "fail_count"]) {
    const n = number(pyGet(value as Dict, name));
    if (n !== null) clean[name] = n;
  }
  // A quota whose reset has passed is historical, not a live availability.
  for (const bucket of clean.buckets as Dict[]) {
    for (const window of bucket.windows as Dict[]) {
      const reset = window.resets_at;
      if (typeof reset === "number" && reset <= now) window.expired = true;
    }
  }
  return clean;
}

// Refresh cadence follows fetch time, never an old provider observation.
export function refreshDue(rawCache: unknown, now: number,
                           ttl: number): boolean {
  const cache = isDict(rawCache) ? rawCache : null;
  const retryAt = cache ? number(pyGet(cache, "retry_at")) : null;
  if (retryAt !== null && now < retryAt) return false;
  const fetched = cache ? number(pyGet(cache, "fetched_at")) : null;
  return fetched === null || now - fetched >= ttl;
}

export function failureCache(rawCache: unknown, now: number, _ttl: number,
                             retryAfter: number | null = null): Dict {
  const value: Dict = isDict(rawCache) ? { ...rawCache } : {};
  const count = Math.trunc(number(pyGet(value, "fail_count")) || 0) + 1;
  let delay = Math.min(300.0, 2 ** Math.min(count, 8));
  if (retryAfter !== null) {
    delay = Math.min(300.0, Math.max(delay, retryAfter));
  }
  Object.assign(value, { attempted_at: now, fail_count: count,
                         retry_at: now + delay,
                         fetched_at: pyGet(value, "fetched_at") });
  return value;
}

// Attach non-secret scope to every returned normalized reading.
export function tagIdentity(reading: Reading, agent: string, source: string,
                            namespace: string, periodKey: string): Reading {
  if (!isDict(reading) || !pyTruthy(reading)) return reading;
  return { ...reading, agent,
           source: source || pyGet(reading, "source", ""),
           account_name: namespace, period_start: periodKey };
}

export function validateSource(agent: string, spec: string | null): string {
  spec = spec || "auto";
  if (spec.startsWith("cmd:")) return spec;
  if (!(VALID_SOURCES as readonly string[]).includes(spec)) {
    throw new Error("unknown usage source '" + spec + "'");
  }
  if (agent === "claude" && ["codex-app-server", "openai-admin",
                             "experimental-codex-api"].includes(spec)) {
    throw new Error(spec + " is a Codex source");
  }
  if (agent === "codex" && ["claude-usage-tracker", "anthropic-admin",
                            "experimental-claude-oauth"].includes(spec)) {
    throw new Error(spec + " is a Claude source");
  }
  return spec;
}

// The UTC period an account reading covers, as [start, end].  End is now
// as Python returns it: through a datetime, so to the microsecond.
export function periodBounds(kind: string, now: number): [number, number] {
  const [secs, us] = splitTimestamp(now);
  const day = Math.floor(secs / 86400);
  let startDay: number;
  if (kind === "day") startDay = day;
  // 1970-01-01 was a Thursday: Monday is three days on.
  else if (kind === "week") startDay = day - ((day + 3) % 7 + 7) % 7;
  else if (kind === "month") {
    const d = new Date(day * 86400000);
    startDay = daysFromCivil(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
  } else throw new Error("account period must be day, week, or month");
  return [startDay * 86400, (secs * 1e6 + us) / 1e6];
}

const CREDENTIALS: { [spec: string]: string } = {
  "anthropic-admin": "ANTHROPIC_ADMIN_KEY",
  "openai-admin": "OPENAI_ADMIN_KEY",
  "experimental-claude-oauth": "CLAUDE_OAUTH_ACCESS_TOKEN",
  "experimental-codex-api": "CODEX_USAGE_ACCESS_TOKEN",
};

// Avoid cache reuse after an implicit managed-account switch.  The
// credentials are read from `env`, which the edge passes in.
export function cacheNamespace(spec: string, account: string, context: unknown,
                               env: { [k: string]: string | undefined }):
    string {
  if (account && account !== "default") return String(account);
  const ctx = isDict(context) ? context : {};
  // os.environ.get("") is "" in practice, as the empty name is never set.
  const name = CREDENTIALS[spec] ?? "";
  let value = (name && env[name]) || "";
  if (spec === "experimental-codex-api") {
    value += "\0" + (env.CODEX_USAGE_ACCOUNT_ID ?? "");
  }
  if (value) {
    return "credential:" +
      sha256Hex(value).slice(0, 24);
  }
  const session = safeText(pyGet(ctx, "session"), 256);
  if (session) return "session:" + session;
  return "default";
}

// Translate a transcript/native quota snapshot without inventing fields.
export function nativeWindows(value: unknown): Dict[] {
  const raw = isDict(value) ? pyGet(value, "rate_limits", value) : {};
  const windows: Dict[] = [];
  if (!isDict(raw)) return windows;
  const sourceBucket = pyStr(pyTruthy(raw.limit_id) ? raw.limit_id
    : pyTruthy(raw.limitId) ? raw.limitId : "default");
  for (const key of ["five_hour", "seven_day", "primary", "secondary"]) {
    const item = pyGet(raw, key);
    if (!isDict(item)) continue;
    const usage = pyGet(item, "used_percentage", pyGet(item, "used_percent"));
    if (usage === null) continue;
    let duration = pyGet(item, "duration_seconds",
      pyGet(item, "limit_window_seconds", pyGet(item, "window_minutes")));
    if (pyGet(item, "window_minutes") !== null &&
        pyGet(item, "duration_seconds") === null &&
        pyGet(item, "limit_window_seconds") === null) {
      const n = number(duration);
      duration = n !== null ? n * 60 : null;
    }
    if (duration === null && key === "five_hour") duration = 5 * 3600;
    if (duration === null && key === "seven_day") duration = 7 * 86400;
    windows.push({
      id: key, duration_seconds: duration, used_percent: usage,
      resets_at: pyGet(item, "resets_at", pyGet(item, "reset_at")),
      bucket_id: pyStr(firstTruthy(pyGet(item, "bucket_id"),
                                   pyGet(item, "limit_id"), sourceBucket)),
      heading: pyStr(firstTruthy(pyGet(item, "heading"), sourceBucket)),
    });
  }
  // Codex native rateLimit snapshots have primary/secondary windows nested.
  const snapshots: { snapshot: unknown; mapKey: string | null }[] = [];
  const byId = pyGet(raw, "rateLimitsByLimitId");
  if (isDict(byId)) {
    for (const [key, snapshot] of Object.entries(byId)) {
      snapshots.push({ snapshot, mapKey: key });
    }
  }
  for (const snapshot of [pyGet(raw, "rateLimits"), raw]) {
    if (!isDict(snapshot)) continue;
    const ident = pyGet(snapshot, "limitId");
    if (isDict(byId) && ident !== null && Object.hasOwn(byId, pyStr(ident))) {
      continue;
    }
    snapshots.push({ snapshot, mapKey: null });
  }
  for (const { snapshot, mapKey } of snapshots) {
    if (!isDict(snapshot)) continue;
    for (const slot of ["primary", "secondary"]) {
      const item = pyGet(snapshot, slot);
      if (!isDict(item) || !Object.hasOwn(item, "usedPercent")) continue;
      const bucketId = pyStr(firstTruthy(pyGet(snapshot, "limitId"),
                                         pyGet(item, "limitId"), mapKey,
                                         "rate_limit"));
      windows.push({
        id: slot,
        duration_seconds:
          ((number(pyGet(item, "windowDurationMins")) || 0) * 60) || null,
        used_percent: pyGet(item, "usedPercent"),
        resets_at: pyGet(item, "resetsAt"),
        bucket_id: bucketId,
        heading: pyStr(firstTruthy(pyGet(snapshot, "limitName"), bucketId)),
        model: pyGet(snapshot, "normalModelSlug"),
        feature: pyGet(snapshot, "feature"),
      });
    }
  }
  const unique: Dict[] = [];
  const seen = new Set<string>();
  for (const item of windows) {
    // Keyed on the values normalise will keep, which always hash: a list
    // in `resets_at` raised TypeError here and took the line down.  Joined
    // into a string, as a Set of arrays would keep every one.
    const key = JSON.stringify([item.bucket_id, item.id,
                                number(item.duration_seconds),
                                epoch(item.resets_at)]);
    if (!seen.has(key)) { seen.add(key); unique.push(item); }
  }
  return unique;
}

// `a or b or c`.
function firstTruthy(...values: unknown[]): unknown {
  for (const v of values.slice(0, -1)) if (pyTruthy(v)) return v;
  return values[values.length - 1];
}

// Native readings are supplied by the active agent, never refreshed.
export function nativeReading(_agent: string, context: unknown): Reading {
  const ctx = isDict(context) ? context : {};
  const raw = firstTruthy(pyGet(ctx, "rate_limits"), pyGet(ctx, "rateLimits"),
                          pyGet(ctx, "quota"), {});
  const windows = nativeWindows(raw);
  if (!windows.length) return {};
  return normalise({ schema_version: 1, as_of: pyGet(ctx, "as_of"),
                     windows }, "native");
}

// The tracker's figures, read down by trackerReading, as a v1 reading.
// sources.py does this inside claude_usage_tracker, between the read and
// its except; split out here so the reading is pure and the read is not.
export function trackerV1(raw: Dict): Reading {
  const windows: Dict[] = [];
  for (const [ident, pct, reset, duration] of [
    ["five_hour", pyGet(raw, "session_pct"),
     pyGet(raw, "session_resets_at"), 18000],
    ["seven_day", pyGet(raw, "weekly_pct"),
     pyGet(raw, "weekly_resets_at"), 604800],
    ["seven_day_opus", pyGet(raw, "weekly_opus_pct"),
     pyGet(raw, "weekly_resets_at"), 604800],
  ] as const) {
    if (pct !== null) {
      windows.push({ id: ident, duration_seconds: duration,
                     used_percent: pct, resets_at: reset });
    }
  }
  return normalise({ schema_version: 1, as_of: pyGet(raw, "as_of"), windows },
                   "claude-usage-tracker");
}

// What a command is handed on stdin: the scalar scope, never a payload.
// Inline in command_reading in Python; json.dumps writes the period bounds
// as floats, so they keep their ".0" here too.
export function commandInput(context: unknown): string {
  const ctx = isDict(context) ? context : {};
  const safe: Dict = {};
  for (const key of ["agent", "session", "model", "account", "period"]) {
    const text = safeText(pyGet(ctx, key), 256);
    if (text !== null) safe[key] = text;
  }
  for (const key of ["period_start", "period_end"]) {
    const value = epoch(pyGet(ctx, key));
    if (value !== null) safe[key] = value;
  }
  return pyJsonDumps(safe, false, ["period_start", "period_end"]);
}

// A command's stdout, as a reading: strict UTF-8, one JSON value, and the
// old flat adapter shape still accepted.  {} for anything else.
export function commandOutput(output: Uint8Array): Reading {
  let value: unknown;
  try {
    const text = utf8(output, true, true);
    value = pyJsonLoads(text);
  } catch {
    return {};
  }
  if (isDict(value) && !Object.hasOwn(value, "schema_version") &&
      ["session_pct", "weekly_pct", "session_resets_at", "weekly_resets_at"]
        .some((key) => Object.hasOwn(value as Dict, key))) {
    // old flat adapter
    value = { schema_version: 1, as_of: pyGet(value, "as_of"), windows: [
      { id: "session", used_percent: pyGet(value, "session_pct"),
        resets_at: pyGet(value, "session_resets_at") },
      { id: "week", used_percent: pyGet(value, "weekly_pct"),
        resets_at: pyGet(value, "weekly_resets_at") }] };
  }
  return normalise(value, "cmd");
}

// ════════════════════════════════════════════════════════════════════════════
// collect: which reading, from where.
// ════════════════════════════════════════════════════════════════════════════

// The scoped cache, as state.py keeps it.  sources_node.ts's fileStore is
// the real one in Node; the mod's reads through `$`, so each method may
// answer with a promise.
export interface Store {
  load(agent: string, source: string, account: string,
       periodStart: string): Dict | Promise<Dict>;
  save(agent: string, source: string, account: string, periodStart: string,
       value: Dict): void | Promise<void>;
  findCompatible(agent: string, account: string,
                 periodStart: string): Dict | Promise<Dict>;
}

// Runs one collector.  `failure` may be given a retry_after, as the HTTP
// sources do; none of the ported ones sets it.
export type Fetch = (selected: string, context: Dict, start: number,
                     end: number, failure: Dict) => Promise<unknown>;

export type Env = { [name: string]: string | undefined };

const HTTP_SOURCES = ["anthropic-admin", "openai-admin",
                      "experimental-claude-oauth", "experimental-codex-api"];

// Collect one selected reading with source/account/UTC-period isolation.
//
// The cache and the collectors are arguments, so this decides and they do.
// Python takes a non-blocking flock around the refresh, so two renders do
// not run one command twice; Node has no flock, and the cost of two
// refreshes racing is one extra tracker read, so the lock and the re-read
// under it are left out.
export async function collect(agent: string, spec: string | null,
                              account: string, period: string,
                              context: unknown, now: number, store: Store,
                              fetch: Fetch, env: Env = {}): Promise<Reading> {
  spec = validateSource(agent, spec);
  const [start, end] = periodBounds(period, now);
  const periodKey = String(start);
  const ctx: Dict = { ...(isDict(context) ? context : {}), agent, account,
                      period, period_start: start, period_end: end };
  const namespace = cacheNamespace(spec, account, ctx, env);
  const native = nativeReading(agent, ctx);
  let staleNative: Reading = {};
  const rawNativeCache = await store.load(agent, "native", namespace, periodKey);
  let cachedNative = cachedReading(rawNativeCache, "native", now, 60);
  let currentNative = pyTruthy(native)
    ? cachedReading(native, "native", now, 60) : {};
  // Native intake is local data, but a fresh normalized observation must be
  // available to a later Stop payload that contains no native quota block.
  // Stale input remains authoritative for this invocation only and may not
  // downgrade a newer cached observation.
  if (pyTruthy(currentNative) && !pyTruthy(currentNative.stale)) {
    const saved = tagIdentity(currentNative, agent, "native", namespace,
                              periodKey);
    saved.fetched_at = now;
    await store.save(agent, "native", namespace, periodKey, saved);
    cachedNative = currentNative = saved;
  }
  // Auto starts with active native data, then only its native cache;
  // external fallback is deliberately restricted to the local managed
  // integrations.
  if (spec === "native") {
    // A supplied native snapshot is live input, not a cache candidate.
    // In particular do not mask it behind the previous fetch TTL.
    return tagIdentity(pyTruthy(native) ? currentNative : cachedNative,
                       agent, "native", namespace, periodKey);
  }
  if (spec === "auto" && pyTruthy(native)) {
    if (!pyTruthy(currentNative.stale)) return currentNative;
    staleNative = currentNative;
  }
  if (spec === "none" || spec === "off") {
    const cachedAny = await store.findCompatible(agent, namespace, periodKey);
    const source = pyTruthy(native) ? "native"
      : String(pyGet(cachedAny, "source", ""));
    return tagIdentity(pyTruthy(native) ? currentNative
                       : cachedReading(cachedAny, source, now, 300),
                       agent, source, namespace, periodKey);
  }
  let selected = spec;
  if (spec === "auto") {
    if (pyTruthy(cachedNative) && !pyTruthy(cachedNative.stale)) {
      return cachedNative;
    }
    selected = agent === "codex" ? "codex-app-server" : "claude-usage-tracker";
  }
  const ttl = HTTP_SOURCES.includes(selected) ? 300 : 60;
  const rawCache = await store.load(agent, selected, namespace, periodKey);
  const cached = cachedReading(rawCache, selected, now, ttl);
  if (!refreshDue(rawCache, now, ttl)) return cached;
  const failure: Dict = {};
  let fresh: unknown = await fetch(selected, ctx, start, end, failure);
  // All built-in/command collectors return the validated v1 form.  Do
  // not normalize it a second time: buckets are already canonical.
  fresh = pyTruthy(fresh) && isDict(fresh) && fresh.schema_version === 1
    ? fresh : {};
  if (pyTruthy(fresh) && hasReading(fresh)) {
    const f = fresh as Dict;
    // A source as_of is evidence: never relabel a stale reading fresh.
    f.as_of = pyGet(f, "as_of") !== null ? f.as_of : now;
    const done = cachedReading(f, selected, now, ttl);
    Object.assign(done, { agent, account_name: namespace,
                          period_start: periodKey, fetched_at: now,
                          attempted_at: now, fail_count: 0 });
    await store.save(agent, selected, namespace, periodKey, done);
    return done;
  }
  const retryAfter = pyGet(failure, "retry_after");
  const failed = failureCache(rawCache, now, ttl,
    typeof retryAfter === "number" ? retryAfter : null);
  Object.assign(failed, { agent, account_name: namespace,
                          period_start: periodKey });
  await store.save(agent, selected, namespace, periodKey, failed);
  return tagIdentity(pyTruthy(cached) ? cached : staleNative, agent,
                     pyTruthy(cached) ? selected : "native", namespace,
                     periodKey);
}

export function identity(values: unknown[]): string[] {
  return values.map((x) => (pyTruthy(x) ? pyStr(x) : ""));
}

export function cacheName(agent: string, source: string, account: string,
                          periodStart: string): string {
  const raw = identity([agent, source, account, periodStart]).join("\0");
  return sha256Hex(raw) + ".json";
}
