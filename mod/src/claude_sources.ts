// Prepared shared usage readings for Claude orchestration.
//
// A port of coding_agent_usage_line/claude_sources.py: collect once, and
// project the reading into the two plan windows the band draws.  It also
// holds what that needs from claude.py, which is not otherwise ported: the
// tracker's store (ClaudeUsageTrackerSource, trackerReading and the plist
// it is read from) and the context main_status hands the collector.
//
// NOT PORTED: account_summary, the account line under the status line,
// which is a renderer and goes with the cells (build step 4).  So
// PreparedClaudeReading has no accountText yet.

import * as fs from "node:fs";
import { spawn } from "node:child_process";
import { STAMP_FMT } from "./spec.ts";
import {
  collect, expandUser, fetchSource, fileStore, isDict, pyFloatText, pyGet,
  pyJsonLoads,
  pyStrip, pyTruthy, splitTimestamp,
} from "./sources.ts";
import type { Dict, Env, Fetch, Reading, Store } from "./sources.ts";

// The two plan windows, as claude_records.Limits holds them.  Percentages
// are strings because a missing figure is the empty string throughout.
// The fields keep Python's names, as the reading's do, so the shared cases
// compare them as they are.  When claude_records.ts lands with its own
// Limits, this one should become an import of it.
export type Limits = {
  readonly session_pct: string;
  readonly session_reset: string;
  readonly session_share: string;
  readonly weekly_pct: string;
  readonly weekly_reset: string;
  readonly weekly_share: string;
  readonly session_turn: string;
  readonly weekly_turn: string;
};

export const NO_LIMITS: Limits = {
  session_pct: "", session_reset: "", session_share: "",
  weekly_pct: "", weekly_reset: "", weekly_share: "",
  session_turn: "", weekly_turn: "",
};

// NamedTuples compare by value; these are records, so by field.
export function limitsEqual(a: Limits, b: Limits): boolean {
  return (Object.keys(NO_LIMITS) as (keyof Limits)[])
    .every((k) => a[k] === b[k]);
}

export type PreparedClaudeReading = {
  readonly reading: Reading;
  readonly limits: Limits;
};

// "%.6f" without its trailing zeros.  toFixed and "%.6f" agree but on an
// exact tie, which toFixed rounds up and Python to even: a figure that is
// an odd number of 128ths, 0.0078125 say.
export function pct(value: unknown): string {
  let n: number | null;
  if (typeof value === "number") n = value;
  else if (typeof value === "string") n = pyFloatText(value);
  else if (typeof value === "boolean") n = value ? 1 : 0;
  else n = null;
  if (n === null) return "";
  let text = n.toFixed(6);
  const scaled = n * 128;
  if (Number.isFinite(n) && Number.isInteger(scaled) && scaled % 2 !== 0 &&
      Math.abs(n) < 2 ** 40) {
    // An exact tie at the seventh decimal: take the even neighbour.
    const below = Math.floor(Math.abs(n) * 1e6);
    const even = below % 2 === 0 ? below : below + 1;
    text = (n < 0 ? "-" : "") + (even / 1e6).toFixed(6);
  }
  if (!Number.isFinite(n)) {
    text = Number.isNaN(n) ? "nan" : n > 0 ? "inf" : "-inf";
  }
  return text.replace(/0+$/, "").replace(/\.$/, "");
}

// Legacy Claude STAMP_FMT strings are parsed as local wall time, and so
// written as it.
export function reset(value: unknown): string {
  if (value === null || value === undefined) return "";
  const t = typeof value === "number" ? value
    : typeof value === "string" ? pyFloatText(value) : null;
  if (t === null || !Number.isFinite(t)) return "";
  const [secs] = splitTimestamp(t);
  return formatLocal(secs);
}

function formatLocal(secs: number): string {
  const d = new Date(secs * 1000);
  const two = (n: number) => String(n).padStart(2, "0");
  // STAMP_FMT is "%Y-%m-%d %H:%M"; written out, as JavaScript has no
  // strftime, and checked against the spec so a change to it shows here.
  if (STAMP_FMT !== "%Y-%m-%d %H:%M") throw new Error("STAMP_FMT changed");
  return String(d.getFullYear()).padStart(4, "0") + "-" +
    two(d.getMonth() + 1) + "-" + two(d.getDate()) + " " +
    two(d.getHours()) + ":" + two(d.getMinutes());
}

// Project only an unassociated default quota bucket into Claude chrome.
export function legacyLimits(reading: unknown): Limits {
  if (!isDict(reading)) return NO_LIMITS;
  // A stale reading still projects.  "stale" is the collector's word for an
  // as_of older than its refresh cadence, sixty seconds for the tracker app,
  // which polls on its own schedule of about a minute, so roughly half of
  // all renders arrived here stale.  The age is reported, never enforced:
  // a figure a minute old is the best figure there is.
  const buckets = pyGet(reading, "buckets");
  if (!Array.isArray(buckets) || buckets.length !== 1) return NO_LIMITS;
  const bucket = buckets[0];
  if (!isDict(bucket) || pyGet(bucket, "id") !== "default") return NO_LIMITS;
  const label = pyGet(bucket, "label");
  if (pyTruthy(pyGet(bucket, "model")) || pyTruthy(pyGet(bucket, "feature")) ||
      !(label === null || label === "" || label === "default")) {
    return NO_LIMITS;
  }
  let five: Dict | null = null, week: Dict | null = null;
  const windows = pyGet(bucket, "windows", []);
  for (const window of Array.isArray(windows) ? windows : []) {
    if (!isDict(window) || pyGet(window, "used_percent") === null ||
        pyTruthy(pyGet(window, "expired"))) continue;
    const duration = pyGet(window, "duration_seconds");
    if (duration === 18000 && five === null) five = window;
    else if (duration === 604800 && week === null) week = window;
  }
  if (five === null && week === null) return NO_LIMITS;
  return {
    ...NO_LIMITS,
    session_pct: five ? pct(pyGet(five, "used_percent")) : "",
    session_reset: five ? reset(pyGet(five, "resets_at")) : "",
    weekly_pct: week ? pct(pyGet(week, "used_percent")) : "",
    weekly_reset: week ? reset(pyGet(week, "resets_at")) : "",
  };
}

// Collect once and return the canonical and legacy-safe forms.  The cache,
// the collectors and the environment default to the real ones.
export async function prepareClaudeReading(
    spec: string | null, account: string, period: string, context: unknown,
    now: number, env: Env = process.env, store: Store = fileStore(env),
    fetch: Fetch = fetchSource(env)): Promise<PreparedClaudeReading> {
  const safe = isDict(context) ? context : {};
  const reading = await collect("claude", spec, account, period, safe, now,
                                store, fetch, env);
  return { reading, limits: legacyLimits(reading) };
}

// What main_status hands the collector: the session's scope, the time the
// payload was observed (so native data without its own as_of is not marked
// stale for lacking one), and the payload's own rate_limits, but only for
// the sources that may read them.  An explicit external command receives
// no quota envelope.  Inline in claude.py; a function here.
export function statusSourceContext(spec: string, session: string,
                                    model: string, asOf: number,
                                    payload: unknown): Dict {
  const context: Dict = { session, model, as_of: asOf };
  if (["", "auto", "native", "none", "off"].includes(spec) &&
      isDict(payload)) {
    const native = pyGet(payload, "rate_limits");
    if (isDict(native)) context.rate_limits = native;
  }
  return context;
}

// ════════════════════════════════════════════════════════════════════════════
// The Claude Usage Tracker's store, from claude.py.
// ════════════════════════════════════════════════════════════════════════════

export const APPLE_EPOCH = 978307200;  // 2001-01-01 UTC, in Unix seconds.
                                       // Every timestamp in a macOS app's
                                       // own store is in this epoch.

// Python's ==, as far as a profile id needs it: True is 1.
function pyEq(a: unknown, b: unknown): boolean {
  const n = (v: unknown) => (typeof v === "boolean" ? Number(v) : v);
  return n(a) === n(b);
}

// A STAMP_FMT string as time.strptime and time.mktime read it: local wall
// time, one or two digits where %m %d %H %M allow it.
const STAMP_RE = new RegExp(
  "^([0-9]{4})-(1[0-2]|0[1-9]|[1-9])-(3[01]|[12][0-9]|0[1-9]|[1-9]| [1-9])" +
  "[" + "\\s" + "]+(2[0-3]|[0-1][0-9]|[0-9]):([0-5][0-9]|[0-9])$");

function stampEpoch(s: string): number | null {
  const m = STAMP_RE.exec(s);
  if (!m) return null;
  const [y, mo, d, h, mi] = m.slice(1).map((x) => Number(x.trim()));
  if (y < 1) return null;
  const leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  const dim = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (d > dim[mo - 1]) return null;
  const date = new Date(2000, 0, 1, h, mi, 0, 0);
  date.setFullYear(y, mo - 1, d);
  date.setHours(h, mi, 0, 0);
  return date.getTime() / 1000;
}

// A carried time back as a Unix epoch, whichever way it was carried: a
// number, a number as text, or a STAMP_FMT stamp.
export function asEpoch(v: unknown): number | null {
  if (typeof v === "boolean" || v === null || v === undefined) return null;
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const s = pyStrip(v);
    if (!s) return null;
    const n = pyFloatText(s);
    if (n !== null) return n;
    return stampEpoch(s);
  }
  return null;
}

// The tracker's UserDefaults, read down to the figures this program uses.
// `profiles_v3` is a JSON array, stored as bytes, of one record per
// account; `activeProfileId` names the one to read, `isSelectedForDisplay`
// is the fallback and the first record the fallback's fallback.  The same
// record holds an OAuth account and a session key, so this names the six
// fields it wants and touches nothing else.
export function trackerReading(store: unknown): Dict {
  if (!isDict(store)) throw new TypeError("the store is not a dict");
  let profs = pyGet(store, "profiles_v3");
  if (profs instanceof Uint8Array) {
    // Python's decode keeps a byte-order mark, and json.loads refuses one.
    profs = new TextDecoder("utf-8", { ignoreBOM: true }).decode(profs);
  }
  if (typeof profs === "string") {
    try {
      profs = pyJsonLoads(profs);
    } catch {
      return {};
    }
  }
  if (!Array.isArray(profs) || !profs.length) return {};
  const want = pyGet(store, "activeProfileId");
  const first = (pred: (p: Dict) => boolean) =>
    profs.find((p: unknown) => isDict(p) && pred(p)) ?? null;
  let prof: unknown = first((p) => pyEq(pyGet(p, "id"), want));
  if (!pyTruthy(prof)) {
    prof = first((p) => pyTruthy(pyGet(p, "isSelectedForDisplay")));
  }
  if (!pyTruthy(prof)) prof = isDict(profs[0]) ? profs[0] : null;
  if (!pyTruthy(prof)) return {};
  const u = pyGet(prof as Dict, "claudeUsage");
  if (!isDict(u)) return {};
  const unix = (v: unknown) => {
    const t = asEpoch(v);
    return t === null ? null : t + APPLE_EPOCH;
  };
  return {
    session_pct: pyGet(u, "sessionPercentage"),
    session_resets_at: unix(pyGet(u, "sessionResetTime")),
    weekly_pct: pyGet(u, "weeklyPercentage"),
    weekly_opus_pct: pyGet(u, "opusWeeklyPercentage"),
    weekly_resets_at: unix(pyGet(u, "weeklyResetTime")),
    as_of: unix(pyGet(u, "lastUpdated")),
  };
}

// ════════════════════════════════════════════════════════════════════════════
// XML property lists, as plistlib reads them.
// ════════════════════════════════════════════════════════════════════════════

// Only the XML form: `defaults export` writes it, and so does any export.
// A binary plist (a copy of the app's own file in ~/Library/Preferences)
// is refused, where Python's plistlib would read it.
export function plistLoads(bytes: Uint8Array): unknown {
  let start = 0;
  if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) start = 3;
  const head = new TextDecoder("latin1").decode(bytes.subarray(start,
                                                               start + 6));
  if (!head.startsWith("<?xml") && !head.startsWith("<plist")) {
    throw new Error("not an XML plist");
  }
  // Expat refuses malformed UTF-8 rather than replacing it.
  const text = new TextDecoder("utf-8", { fatal: true })
    .decode(bytes.subarray(start));
  return parsePlistXml(text);
}

const ENTITIES: { [name: string]: string } = {
  lt: "<", gt: ">", amp: "&", quot: '"', apos: "'",
};

function decodeEntities(text: string): string {
  return text.replace(/&([^;&]*);|&/g, (whole, name: string | undefined) => {
    if (name === undefined) throw new Error("bad entity");
    if (Object.hasOwn(ENTITIES, name)) return ENTITIES[name];
    const m = /^#(?:x([0-9a-fA-F]+)|([0-9]+))$/.exec(name);
    if (!m) throw new Error("undefined entity " + whole);
    const code = m[1] !== undefined ? parseInt(m[1], 16) : parseInt(m[2], 10);
    const ok = code === 9 || code === 10 || code === 13 ||
      (code >= 0x20 && code <= 0xd7ff) || (code >= 0xe000 && code <= 0xfffd) ||
      (code >= 0x10000 && code <= 0x10ffff);
    if (!ok) throw new Error("bad character reference");
    return String.fromCodePoint(code);
  });
}

// int() of a plist <integer>: base 10, or 16 after 0x.
function pyIntText(raw: string): number {
  const s = pyStrip(raw);
  const hex = /^0[xX]_?([0-9a-fA-F](?:_?[0-9a-fA-F])*)$/.exec(s);
  if (raw.startsWith("0x") || raw.startsWith("0X")) {
    if (!hex) throw new Error("invalid literal for int()");
    return Number(BigInt("0x" + hex[1].replaceAll("_", "")));
  }
  const dec = /^([+-]?)([0-9](?:_?[0-9])*)$/.exec(s);
  if (!dec) throw new Error("invalid literal for int()");
  const n = Number(BigInt(dec[2].replaceAll("_", "")));
  return dec[1] === "-" ? -n : n;
}

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

// binascii.a2b_base64 as plistlib calls it: characters outside the
// alphabet are skipped, padding ends the input, and a short quad is an
// error.
function a2bBase64(text: string): Uint8Array {
  if (/[^\x00-\x7f]/.test(text)) throw new Error("non-ASCII base64");
  const out: number[] = [];
  let quad = 0, left = 0, bits = 0;
  const valid = (c: string) => c === "=" || B64.includes(c);
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "=") {
      // At the third place, padding counts only if a second one follows.
      let next = "";
      for (let j = i + 1; j < text.length; j++) {
        if (valid(text[j])) { next = text[j]; break; }
      }
      if (quad < 2 || (quad === 2 && next !== "=")) continue;
      left = 0;
      break;
    }
    const v = B64.indexOf(c);
    if (v < 0) continue;
    quad = (quad + 1) & 3;
    bits = (bits << 6) | v;
    left += 6;
    if (left >= 8) {
      left -= 8;
      out.push((bits >> left) & 0xff);
      bits &= (1 << left) - 1;
    }
  }
  if (left !== 0) throw new Error("incorrect base64 padding");
  return Uint8Array.from(out);
}

const DATE_RE = new RegExp("^([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2})" +
  "(?:T([0-9]{2})(?::([0-9]{2})(?::([0-9]{2}))?)?)?)?)?Z");

// _PlistParser over a small XML reader: elements, text, entities, CDATA,
// comments and processing instructions, and a DOCTYPE with no entity
// declarations in it, which plistlib refuses.
function parsePlistXml(source: string): unknown {
  const text = source.replace(/\r\n?/g, "\n");
  const stack: unknown[] = [];
  const open: string[] = [];
  let currentKey: string | null = null;
  let root: unknown = null;
  let data: string[] = [];
  let seenRoot = false;
  let pos = 0;

  const getData = () => {
    const joined = data.join("");
    data = [];
    return joined;
  };
  const top = () => {
    if (!stack.length) throw new Error("unexpected element");
    return stack[stack.length - 1];
  };
  const addObject = (value: unknown) => {
    if (currentKey !== null) {
      const d = top();
      if (!isDict(d)) throw new Error("unexpected element");
      d[currentKey] = value;
      currentKey = null;
    } else if (!stack.length) {
      root = value;
    } else {
      const a = top();
      if (!Array.isArray(a)) throw new Error("unexpected element");
      a.push(value);
    }
  };
  const begin = (name: string) => {
    data = [];
    if (name === "dict") {
      const d: Dict = Object.create(null);
      addObject(d);
      stack.push(d);
    } else if (name === "array") {
      const a: unknown[] = [];
      addObject(a);
      stack.push(a);
    }
  };
  const end = (name: string) => {
    switch (name) {
      case "dict":
        if (currentKey) throw new Error("missing value for key");
        stack.pop();
        break;
      case "key":
        if (currentKey || !isDict(top())) throw new Error("unexpected key");
        currentKey = getData();
        break;
      case "array": stack.pop(); break;
      case "true": addObject(true); break;
      case "false": addObject(false); break;
      case "integer": addObject(pyIntText(getData())); break;
      case "real": {
        const n = pyFloatText(getData());
        if (n === null) throw new Error("could not convert to float");
        addObject(n);
        break;
      }
      case "string": addObject(getData()); break;
      case "data": addObject(a2bBase64(getData())); break;
      case "date": {
        const m = DATE_RE.exec(getData());
        if (!m || m[3] === undefined) throw new Error("bad date");
        const p = m.slice(1).map((x) => Number(x ?? 0));
        addObject(new Date(Date.UTC(p[0], p[1] - 1, p[2], p[3], p[4], p[5])));
        break;
      }
    }
  };

  const NAME = /[A-Za-z_:][-\w.:]*/y;
  const ATTR = /\s+([A-Za-z_:][-\w.:]*)\s*=\s*("[^"<]*"|'[^'<]*')/y;
  while (pos < text.length) {
    if (text.startsWith("<?", pos)) {
      const close = text.indexOf("?>", pos);
      if (close < 0) throw new Error("unclosed processing instruction");
      pos = close + 2;
    } else if (text.startsWith("<!--", pos)) {
      const close = text.indexOf("-->", pos);
      if (close < 0) throw new Error("unclosed comment");
      pos = close + 3;
    } else if (text.startsWith("<!DOCTYPE", pos)) {
      const bracket = text.indexOf("[", pos);
      let close = text.indexOf(">", pos);
      if (bracket >= 0 && bracket < close) {
        const subsetEnd = text.indexOf("]", bracket);
        if (subsetEnd < 0) throw new Error("unclosed DOCTYPE");
        if (text.slice(bracket, subsetEnd).includes("<!ENTITY")) {
          throw new Error("XML entity declarations are not supported");
        }
        close = text.indexOf(">", subsetEnd);
      }
      if (close < 0) throw new Error("unclosed DOCTYPE");
      pos = close + 1;
    } else if (text.startsWith("<![CDATA[", pos)) {
      const close = text.indexOf("]]>", pos);
      if (close < 0 || !open.length) throw new Error("bad CDATA");
      data.push(text.slice(pos + 9, close));
      pos = close + 3;
    } else if (text.startsWith("</", pos)) {
      NAME.lastIndex = pos + 2;
      const m = NAME.exec(text);
      if (!m) throw new Error("bad end tag");
      const after = /\s*>/y;
      after.lastIndex = NAME.lastIndex;
      if (!after.exec(text)) throw new Error("bad end tag");
      if (open.pop() !== m[0]) throw new Error("mismatched tag");
      end(m[0]);
      pos = after.lastIndex;
    } else if (text[pos] === "<") {
      NAME.lastIndex = pos + 1;
      const m = NAME.exec(text);
      if (!m) throw new Error("bad start tag");
      if (!open.length && seenRoot) throw new Error("junk after document");
      let at = NAME.lastIndex;
      for (;;) {
        ATTR.lastIndex = at;
        const a = ATTR.exec(text);
        if (!a) break;
        decodeEntities(a[2].slice(1, -1));
        at = ATTR.lastIndex;
      }
      const close = /\s*(\/?)>/y;
      close.lastIndex = at;
      const c = close.exec(text);
      if (!c) throw new Error("bad start tag");
      pos = close.lastIndex;
      seenRoot = true;
      open.push(m[0]);
      begin(m[0]);
      if (c[1]) {
        open.pop();
        end(m[0]);
      }
    } else {
      let next = text.indexOf("<", pos);
      if (next < 0) next = text.length;
      const chunk = text.slice(pos, next);
      if (!open.length) {
        if (/[^ \t\n]/.test(chunk)) throw new Error("text outside the root");
      } else {
        if (chunk.includes("]]>")) throw new Error("']]>' in text");
        data.push(decodeEntities(chunk));
      }
      pos = next;
    }
  }
  if (!seenRoot || open.length) throw new Error("no element found");
  return root;
}

// ════════════════════════════════════════════════════════════════════════════
// The edge: the store itself.
// ════════════════════════════════════════════════════════════════════════════

// Claude Usage Tracker, the macOS menu-bar app, which polls Anthropic on
// its own schedule and keeps the answer in its UserDefaults.  Read through
// `defaults export` rather than by opening the .plist, because a running
// app's preferences live in cfprefsd and reach the file when cfprefsd
// feels like it.  CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST names an
// exported store to read instead.
export class ClaudeUsageTrackerSource {
  static readonly DOMAIN = "HamedElfayome.Claude-Usage";
  static readonly PLIST =
    "~/Library/Preferences/HamedElfayome.Claude-Usage.plist";
  static readonly ENV = "CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST";

  env: Env;

  constructor(env: Env) {
    this.env = env;
  }

  available(): boolean {
    if (this.env[ClaudeUsageTrackerSource.ENV]) return true;
    // The file is the cheap test: `defaults export` on an unknown domain
    // succeeds and prints an empty dict.
    try {
      return process.platform === "darwin" && fs.statSync(
        expandUser(ClaudeUsageTrackerSource.PLIST)).isFile();
    } catch {
      return false;
    }
  }

  async store(): Promise<unknown> {
    const path = this.env[ClaudeUsageTrackerSource.ENV];
    if (path) return plistLoads(fs.readFileSync(expandUser(path)));
    const out = await defaultsExport(ClaudeUsageTrackerSource.DOMAIN, 15);
    return out.length ? plistLoads(out) : {};
  }

  async read(): Promise<Dict> {
    try {
      return trackerReading(await this.store());
    } catch {
      return {};
    }
  }
}

function defaultsExport(domain: string, timeout: number): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const proc = spawn("defaults", ["export", domain, "-"],
                       { stdio: ["ignore", "pipe", "ignore"],
                         timeout: timeout * 1000 });
    const chunks: Buffer[] = [];
    proc.stdout.on("data", (c: Buffer) => chunks.push(c));
    proc.on("error", reject);
    proc.on("close", (_code: number | null, signal: string | null) => {
      if (signal) reject(new Error("defaults export timed out"));
      else resolve(Buffer.concat(chunks));
    });
  });
}

// The figures sources.claude_usage_tracker reads, or null when the app is
// not there.  The override file's errors propagate, to be no reading at
// all; a failed `defaults export` is an empty store, as read() has it.
export async function readTracker(env: Env): Promise<Dict | null> {
  const source = new ClaudeUsageTrackerSource(env);
  if (env[ClaudeUsageTrackerSource.ENV]) {
    return trackerReading(await source.store());
  }
  if (!source.available()) return null;
  return source.read();
}
