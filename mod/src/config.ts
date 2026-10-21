// The configuration files: where they are, what they say, what is wrong
// with them, and the options merged from them (agents/plans/config-merge.md,
// "Files" and "Merge semantics").
//
// A port of coding_agent_usage_line/config.py, of options.merge and of
// cli._merged's usage-source check, held to the Python's answers by the
// shared cases, tests/fixtures/config/cases.json (test/config.test.ts):
// the same files found, the same values kept, the same warnings word for
// word.  Each function keeps its Python name in camelCase.  The mod has no
// command line, so there is no flags layer here, and the cases with flags
// are the Python's alone.
//
// Under the files is the defaults file, defaults/config.jsonc in the mod's
// folder, every option a file may set with its default, read strictly by
// parseDefaults: anything wrong with it is a DefaultsError, never a value
// made up in its place (config-merge.md, Decided 18).
//
// Pure: the files are reached through a ConfigFs the caller hands in, `$.fs`
// in the mod (hooks/edges.ts, configVia), a fake built from a case's files
// in the tests; the environment is a plain object.  Paths are POSIX, and the
// path functions are posixpath's.
//
// What Python gives for free and this file spells out, because a warning's
// text would otherwise drift: json.loads keeping a dict's keys in the order
// written (a JavaScript object puts "1" first) and telling 1 from 1.0, and
// json.dumps with and without ensure_ascii.

import { OPTIONS } from "./options_spec.ts";
import type { Options } from "./options_spec.ts";
import { PY_SPACE, pyFloatRepr, pyStrip } from "./py.ts";
import { pyJsonDumps, validateSource } from "./sources.ts";

export const NAME = "coding-agent-usage-line";
export const PROJECT_FILE = "config.jsonc";
export const LOCAL_FILE = "config.local.jsonc";
// A config file is a few hundred bytes; one this size is something else.
export const MAX_BYTES = 64 * 1024;
// The user-global directory, for the tests, as _STATE_DIR is for state.
export const CONFIG_DIR_ENV = "CODING_AGENT_USAGE_LINE_CONFIG_DIR";

// The file layers, highest first.
export const FILE_LAYERS = ["project-local", "project", "user"] as const;
export type FileLayer = typeof FILE_LAYERS[number];

// ── What the caller hands in ──────────────────────────────────────────────

/** A path's stat, following links: `$.fs.stat`'s fields this reads. */
export type FileStat = {
  kind: "file" | "dir" | "other";
  size: number;
  mtimeMs: number;
};

/** The file system as the walk reaches it.  Each answers null where the
 * Python's call would fail or answer False. */
export type ConfigFs = {
  /** The path's stat, or null when it leads nowhere. */
  stat(path: string): Promise<FileStat | null>;
  /** The file's text, strictly UTF-8 with a byte-order mark kept, or null
   * when it cannot be read or decoded. */
  read(path: string): Promise<string | null>;
  /** Where the path lands with every link followed, or null. */
  realPath(path: string): Promise<string | null>;
};

/** The environment variables the walk reads, by name. */
export type ConfigEnv = { readonly [name: string]: string | undefined };

/** The names ConfigEnv is read for. */
export const CONFIG_ENV = ["HOME", "XDG_CONFIG_HOME", CONFIG_DIR_ENV] as const;

// ── The spec, loosely typed ───────────────────────────────────────────────

type Scalar = { type: string; items?: readonly string[];
  minimum?: number; fixed?: readonly string[] };
type OptionRec = Scalar & {
  // An option no file sets has its default here; one a file may set has
  // it in the defaults file alone (Defaults).
  default?: unknown;
  file: boolean;
  fields?: { readonly [field: string]: Scalar };
  rows?: readonly string[];
  derived?: { from: string; map: { readonly [key: string]: unknown } };
};
const SPEC = OPTIONS as unknown as { readonly [name: string]: OptionRec };
const NAMES = Object.keys(SPEC);

// ── JSON as Python reads and writes it ────────────────────────────────────

/** A value json.loads gives: an int as a bigint and a float as a number,
 * since Python tells 1 from 1.0, and an object as a Map, whose keys keep
 * the order written (a repeated key keeps its first place and its last
 * value, as a dict's does). */
export type Json = null | boolean | bigint | number | string | Json[] |
  Map<string, Json>;

const NUMBER = /-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?/y;
const ESCAPES: { readonly [c: string]: string } = {
  '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r",
  t: "\t" };

/** json.loads(text), or a SyntaxError. */
export function jsonLoads(text: string): Json {
  let i = 0;
  const fail = (): never => {
    throw new SyntaxError("invalid JSON at " + i);
  };
  const ws = () => {
    while (i < text.length && " \t\n\r".includes(text[i])) i++;
  };
  const string = (): string => {
    i++;
    let out = "";
    for (;;) {
      if (i >= text.length) fail();
      const ch = text[i++];
      if (ch === '"') return out;
      if (ch < " ") fail();
      if (ch !== "\\") {
        out += ch;
        continue;
      }
      const esc = text[i++];
      if (esc !== undefined && Object.hasOwn(ESCAPES, esc)) {
        out += ESCAPES[esc];
      } else if (esc === "u") {
        const hex = text.slice(i, i + 4);
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail();
        out += String.fromCharCode(parseInt(hex, 16));
        i += 4;
      } else fail();
    }
  };
  const value = (): Json => {
    ws();
    const ch = text[i];
    if (ch === "{") {
      i++;
      const obj = new Map<string, Json>();
      ws();
      if (text[i] === "}") {
        i++;
        return obj;
      }
      for (;;) {
        ws();
        if (text[i] !== '"') fail();
        const key = string();
        ws();
        if (text[i++] !== ":") fail();
        obj.set(key, value());
        ws();
        const sep = text[i++];
        if (sep === "}") return obj;
        if (sep !== ",") fail();
      }
    }
    if (ch === "[") {
      i++;
      const arr: Json[] = [];
      ws();
      if (text[i] === "]") {
        i++;
        return arr;
      }
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
      ["null", null], ["NaN", NaN], ["Infinity", Infinity],
      ["-Infinity", -Infinity]] as const) {
      if (text.startsWith(word, i)) {
        i += word.length;
        return val;
      }
    }
    NUMBER.lastIndex = i;
    const m = NUMBER.exec(text);
    if (!m) return fail();
    i += m[0].length;
    return m[1] === undefined && m[2] === undefined
      ? BigInt(m[0]) : Number(m[0]);
  };
  const result = value();
  ws();
  if (i !== text.length) fail();
  return result;
}

/** json.dumps(s), ensure_ascii and all, of a string. */
const dumps = (s: string): string => pyJsonDumps(s);

const SHORT: { readonly [c: string]: string } = {
  '"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t",
  "\b": "\\b", "\f": "\\f" };

/** json.dumps(value, ensure_ascii=False). */
export function dumpsUnicode(value: Json): string {
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "number") {
    if (Number.isNaN(value)) return "NaN";
    if (!Number.isFinite(value)) return value > 0 ? "Infinity" : "-Infinity";
    return pyFloatRepr(value);
  }
  if (typeof value === "string") {
    return '"' + value.replace(/[\x00-\x1f\\"]/g, (c) => SHORT[c] ??
      "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0")) + '"';
  }
  if (Array.isArray(value)) return "[" + value.map(dumpsUnicode).join(", ") + "]";
  return "{" + [...value].map(([k, v]) => dumpsUnicode(k) + ": " +
    dumpsUnicode(v)).join(", ") + "}";
}

// ── JSONC ─────────────────────────────────────────────────────────────────

const IS_SPACE = new RegExp(`^[${PY_SPACE}]$`, "u");

/** `text` with each `//` comment and each trailing comma blanked to
 * spaces, outside strings, so jsonLoads reads what is left.  A trailing
 * comma is one followed, past blanks and comments, by `}` or `]`. */
export function stripJsonc(text: string): string {
  const out = text.split("");
  const n = text.length;
  let i = 0;
  let inString = false;
  let comma: number | null = null;
  while (i < n) {
    const c = text[i];
    if (inString) {
      if (c === "\\") {
        i += 2;
        continue;
      }
      if (c === '"') inString = false;
    } else if (c === '"') {
      inString = true;
      comma = null;
    } else if (c === "/" && text.startsWith("//", i)) {
      while (i < n && text[i] !== "\n") {
        out[i] = " ";
        i++;
      }
      continue;
    } else if (c === ",") {
      comma = i;
    } else if (c === "}" || c === "]") {
      if (comma !== null) out[comma] = " ";
      comma = null;
    } else if (!IS_SPACE.test(c)) {
      comma = null;
    }
    i++;
  }
  return out.join("");
}

// ── Paths, as posixpath has them ──────────────────────────────────────────

export function isabs(p: string): boolean {
  return p.startsWith("/");
}

export function join(a: string, ...parts: string[]): string {
  let path = a;
  for (const b of parts) {
    if (b.startsWith("/")) path = b;
    else if (!path || path.endsWith("/")) path += b;
    else path += "/" + b;
  }
  return path;
}

export function normpath(path: string): string {
  if (path === "") return ".";
  let initial = path.startsWith("/") ? 1 : 0;
  if (initial && path.startsWith("//") && !path.startsWith("///")) initial = 2;
  const comps: string[] = [];
  for (const comp of path.split("/")) {
    if (comp === "" || comp === ".") continue;
    if (comp !== ".." || (!initial && !comps.length) ||
        (comps.length && comps[comps.length - 1] === "..")) {
      comps.push(comp);
    } else if (comps.length) {
      comps.pop();
    }
  }
  return "/".repeat(initial) + comps.join("/") || ".";
}

/** os.path.abspath, for a session whose directory is `/`: the mod's
 * starts are absolute, so the working directory never enters. */
export function abspath(p: string): string {
  return normpath(isabs(p) ? p : join("/", p));
}

export function dirname(p: string): string {
  let head = p.slice(0, p.lastIndexOf("/") + 1);
  if (head && head !== "/".repeat(head.length)) head = head.replace(/\/+$/, "");
  return head;
}

export function basename(p: string): string {
  return p.slice(p.lastIndexOf("/") + 1);
}

export function relpath(path: string, start: string): string {
  const s = abspath(start).split("/").filter(Boolean);
  const p = abspath(path).split("/").filter(Boolean);
  let i = 0;
  while (i < s.length && i < p.length && s[i] === p[i]) i++;
  const rel = [...Array(s.length - i).fill(".."), ...p.slice(i)];
  return rel.length ? join(rel[0], ...rel.slice(1)) : ".";
}

// ── Where the files are ───────────────────────────────────────────────────

/** The user-global configuration directory. */
export function userDir(env: ConfigEnv): string {
  const given = env[CONFIG_DIR_ENV];
  if (given) return given;
  const xdg = env.XDG_CONFIG_HOME;
  // The XDG spec has a relative path ignored.
  if (xdg && isabs(xdg)) return join(xdg, NAME);
  return join(env.HOME ?? "", ".config", NAME);
}

function projectFiles(d: string): [string, string] {
  const base = join(d, ".config", NAME);
  return [join(base, LOCAL_FILE), join(base, PROJECT_FILE)];
}

/** `start` and each directory above it, up to but not including $HOME or
 * /: $HOME's .config is the user-global file's, never a project's. */
async function ancestors(start: string, env: ConfigEnv, fs: ConfigFs):
    Promise<string[]> {
  const home = abspath(env.HOME ?? "");
  const stops = new Set([home, (await fs.realPath(home)) ?? home]);
  const out: string[] = [];
  let d = abspath(start);
  while (!stops.has(d) && dirname(d) !== d) {
    out.push(d);
    d = dirname(d);
  }
  return out;
}

const isFile = async (fs: ConfigFs, p: string) =>
  (await fs.stat(p))?.kind === "file";
const exists = async (fs: ConfigFs, p: string) => (await fs.stat(p)) !== null;

/** A file's first line, stripped, as readline().strip() reads it with
 * universal newlines; null when it cannot be read. */
async function firstLine(fs: ConfigFs, p: string): Promise<string | null> {
  const text = await fs.read(p);
  return text === null ? null : pyStrip(text.split(/\r\n|\r|\n/)[0]);
}

/** The main checkout of the worktree whose top directory is `top`, or
 * null: `top/.git` is a file naming the worktree's git directory, whose
 * `commondir` names the repository's.  A submodule's git directory has no
 * `commondir`, and a bare repository's is no checkout's `.git`. */
export async function mainCheckout(top: string, fs: ConfigFs):
    Promise<string | null> {
  const line = await firstLine(fs, join(top, ".git"));
  if (line === null || !line.startsWith("gitdir:")) return null;
  const gitdir = join(top, pyStrip(line.slice("gitdir:".length)));
  const common = await firstLine(fs, join(gitdir, "commondir"));
  if (common === null) return null;
  const dir = normpath(join(gitdir, common));
  return basename(dir) === ".git" ? dirname(dir) : null;
}

export type Paths = { [layer in FileLayer]: string | null };

/** The project root and the three files' paths, walking up from `start`
 * (config-merge.md, "Finding the root").
 *
 * The first directory holding either project file is the root; the walk
 * stops at a `.git` (a directory, or a worktree's file), at $HOME and at
 * /.  A worktree with no local file of its own takes its main checkout's,
 * at the same place under it (Decided 6). */
export async function find(start: string, env: ConfigEnv, fs: ConfigFs):
    Promise<{ root: string | null; paths: Paths }> {
  let root: string | null = null;
  let top: string | null = null;
  for (const d of await ancestors(start, env, fs)) {
    const [local, project] = projectFiles(d);
    if (await isFile(fs, local) || await isFile(fs, project)) {
      root = d;
      break;
    }
    if (await exists(fs, join(d, ".git"))) {
      top = d;
      break;
    }
  }
  if (root !== null) {
    for (const d of await ancestors(root, env, fs)) {
      if (await exists(fs, join(d, ".git"))) {
        top = d;
        break;
      }
    }
  }
  const paths: Paths = { "user": join(userDir(env), PROJECT_FILE),
    "project-local": null, "project": null };
  if (root !== null) {
    [paths["project-local"], paths.project] = projectFiles(root);
  }
  if (paths["project-local"] && await isFile(fs, paths["project-local"])) {
    return { root, paths };
  }
  const main = top !== null ? await mainCheckout(top, fs) : null;
  if (main === null || top === null) return { root, paths };
  if (root !== null) {
    const local = projectFiles(normpath(join(main, relpath(root, top))))[0];
    if (await isFile(fs, local)) paths["project-local"] = local;
    return { root, paths };
  }
  // No project file in the worktree: the main checkout's local file, from
  // the place under it that `start` is under the worktree.
  const mirrored = normpath(join(main, relpath(abspath(start), top)));
  for (const d of await ancestors(mirrored, env, fs)) {
    const local = projectFiles(d)[0];
    if (await isFile(fs, local)) {
      paths["project-local"] = local;
      return { root: d, paths };
    }
    if (d === main) break;
  }
  return { root, paths };
}

// ── What the files say ────────────────────────────────────────────────────

/** The known word nearest `word`, by edits (a swap of two neighbours
 * counts one), when it is near enough to be the one meant; else null.
 * Ties go to the first in `known`, the spec's order, as the Python's do. */
export function nearest(word: string, known: readonly string[]):
    string | null {
  let best: string | null = null;
  let bestD = -1;
  for (const k of known) {
    const d = distance(word, k);
    if (bestD < 0 || d < bestD) {
      best = k;
      bestD = d;
    }
  }
  return bestD >= 0 && bestD <= Math.max(1, Math.floor([...word].length / 3))
    ? best : null;
}

/** The optimal string alignment distance of `a` and `b`, by code point. */
function distance(a: string, b: string): number {
  const x = [...a], y = [...b];
  const rows: number[][] = [Array.from({ length: y.length + 1 }, (_, j) => j)];
  for (let i = 1; i <= x.length; i++) {
    const row = [i, ...Array(y.length).fill(0)];
    for (let j = 1; j <= y.length; j++) {
      const cost = x[i - 1] === y[j - 1] ? 0 : 1;
      row[j] = Math.min(rows[i - 1][j] + 1, row[j - 1] + 1,
        rows[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && x[i - 1] === y[j - 2] && x[i - 2] === y[j - 1]) {
        row[j] = Math.min(row[j], rows[i - 2][j - 2] + 1);
      }
    }
    rows.push(row);
  }
  return rows[rows.length - 1][y.length];
}

function hint(word: string, known: readonly string[]): string {
  const near = nearest(word, known);
  return near !== null ? ` (did you mean ${dumps(near)}?)` : "";
}

const quoted = (items: readonly string[]) =>
  items.map((i) => dumpsUnicode(i)).join(", ");

/** One row of a table, field by field. */
export type Row = { [field: string]: string | boolean };
/** A table's value: its rows, by name. */
export type Rows = { [row: string]: Row };
/** An option's value, as a file or a default gives it. */
export type Value = string | boolean | number | readonly string[] | Rows |
  null;

type Checked = { got: Value; bad: null } | { got: null; bad: string };

/** `value` checked as a `kind`. */
function scalar(kind: string, value: Json, spec: Scalar, where: string):
    Checked {
  if (kind === "bool") {
    if (typeof value === "boolean") return { got: value, bad: null };
    return { got: null, bad: `${where} must be true or false` };
  }
  if (kind === "int") {
    // A whole float is an int: the Python takes 3.0 as 3.
    if (typeof value === "number" && Number.isInteger(value)) {
      value = BigInt(value);
    }
    const least = spec.minimum;
    if (typeof value === "bigint" &&
        (least === undefined || value >= BigInt(least))) {
      return { got: Number(value), bad: null };
    }
    return { got: null, bad: least === undefined
      ? `${where} must be a whole number`
      : `${where} must be a whole number, ${least} or more` };
  }
  if (kind === "string") {
    if (typeof value === "string") return { got: value, bad: null };
    return { got: null, bad: `${where} must be a string` };
  }
  if (kind === "enum") {
    const items = spec.items ?? [];
    if (typeof value === "string" && items.includes(value)) {
      return { got: value, bad: null };
    }
    const near = typeof value === "string" ? hint(value, items) : "";
    return { got: null, bad: `${where} must be one of ${quoted(items)}${near}` };
  }
  if (kind === "list") {
    if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
      return { got: [...value] as string[], bad: null };
    }
    return { got: null, bad: `${where} must be a list of strings` };
  }
  throw new Error("no such type: " + kind);
}

/** A table's value checked field by field: the rows and fields that
 * passed, and why for each that did not.  `fixed` is the table's default,
 * which a fixed field may not move from; null while the defaults are what
 * is being read. */
function table(name: string, option: OptionRec, value: Json,
    fixed: Rows | null): { kept: Rows; why: string[] } {
  if (!(value instanceof Map)) {
    return { kept: {}, why: [`${dumps(name)} must be an object`] };
  }
  const fields = option.fields ?? {};
  const rows = option.rows ?? [];
  const kept: Rows = {};
  const why: string[] = [];
  for (const [row, rec] of value) {
    let where = dumps(`${name}.${row}`);
    if (!rows.includes(row)) {
      why.push(`${where} is no row${hint(row, rows)}`);
      continue;
    }
    if (!(rec instanceof Map)) {
      why.push(`${where} must be an object`);
      continue;
    }
    for (const [field, v] of rec) {
      where = dumps(`${name}.${row}.${field}`);
      if (!Object.hasOwn(fields, field)) {
        why.push(`${where} is no field${hint(field, Object.keys(fields))}`);
        continue;
      }
      const spec = fields[field];
      let { got, bad } = scalar(spec.type, v, spec, where);
      if (bad === null && fixed !== null && (spec.fixed ?? []).includes(row) &&
          got !== fixed[row][field]) {
        bad = `${where} is always ${dumpsUnicode(fixed[row][field])}`;
      }
      if (bad !== null) why.push(bad);
      else (kept[row] ??= {})[field] = got as string | boolean;
    }
  }
  return { kept, why };
}

/** The option a file may set by `name`, or why not. */
function known(name: string): { option: OptionRec; why: null } |
    { option: null; why: string } {
  if (!Object.hasOwn(SPEC, name)) {
    return { option: null, why: `${dumps(name)} is no option${hint(name, NAMES)}` };
  }
  const option = SPEC[name];
  if (!option.file) {
    return { option: null,
      why: `${dumps(name)} describes one run, so no file sets it` };
  }
  return { option, why: null };
}

/** One key of a file: the value to merge, or null to skip it, and why for
 * each part skipped.  A derived option's null is the defaults file's own
 * spelling of "not set", so a copy of that file says nothing. */
export function check(name: string, value: Json, defaults: Defaults):
    { got: Value; why: string[] } {
  const { option, why: unknown } = known(name);
  if (option === null) return { got: null, why: [unknown] };
  if (value === null && option.derived) return { got: null, why: [] };
  if (option.type === "table") {
    const { kept, why } = table(name, option, value, defaults[name] as Rows);
    return { got: Object.keys(kept).length ? kept : null, why };
  }
  const { got, bad } = scalar(option.type, value, option, dumps(name));
  return { got, why: bad === null ? [] : [bad] };
}

/** One file's part in the merge: its layer, its path, its modification
 * time, and the values it gave that passed their checks, by option name.
 * A table's value holds only the rows and fields the file set. */
export type Layer = { name: FileLayer | ModLayer; path: string;
  mtimeMs: number; values: { [option: string]: Value } };

/** The mod's own settings (hooks/config.ts, SETTINGS), a layer under the
 * files that the Python has no counterpart of: the settings the mod drew
 * with before it read files, until the user's file holds them. */
export const MOD_LAYER = "mod";
export type ModLayer = typeof MOD_LAYER;

type Read = { values: Layer["values"]; warnings: string[];
  mtimeMs: number | null };

/** The file's text, or why it cannot be read; null when there is no
 * file.  `st` is its stat. */
async function textOf(path: string, fs: ConfigFs, st: FileStat | null):
    Promise<{ text: string; why: null } | { text: null; why: string | null }> {
  if (st === null || st.kind !== "file") return { text: null, why: null };
  if (st.size > MAX_BYTES) {
    return { text: null, why: `over ${MAX_BYTES / 1024} KiB` };
  }
  const text = await fs.read(path);
  return text === null ? { text: null, why: "unreadable" } : { text, why: null };
}

/** The JSONC object `text` holds, or why not. */
function objectOf(text: string):
    { data: Map<string, Json>; why: null } | { data: null; why: string } {
  let data: Json;
  try {
    data = jsonLoads(stripJsonc(text));
  } catch {
    return { data: null, why: "not valid JSONC" };
  }
  if (!(data instanceof Map)) return { data: null, why: "not an object" };
  return { data, why: null };
}

/** Why a file's "version" is not one this program reads, or null.  The
 * key is reserved for a later change of shape. */
function versionFault(value: Json): string | null {
  if (value === 1n || value === 1) return null;
  return `"version" ${dumpsUnicode(value)} is not one this program reads`;
}

/** One file's checked values, by option name, its warnings, each "PATH:
 * what", and its modification time; nothing when there is no file. */
export async function readFile(path: string, fs: ConfigFs,
    defaults: Defaults): Promise<Read> {
  const st = await fs.stat(path);
  const skipped = (why: string): Read => ({ values: {},
    warnings: [`${path}: ${why}, so the file is skipped`],
    mtimeMs: st?.mtimeMs ?? null });
  const got = await textOf(path, fs, st);
  if (got.text === null) {
    return got.why === null ? { values: {}, warnings: [], mtimeMs: null }
      : skipped(got.why);
  }
  const { data, why } = objectOf(got.text);
  if (data === null) return skipped(why);
  const values: Layer["values"] = {};
  const warnings: string[] = [];
  for (const [name, value] of data) {
    if (name === "version") {
      const fault = versionFault(value);
      if (fault === null) continue;
      return skipped(fault);
    }
    const { got, why } = check(name, value, defaults);
    warnings.push(...why.map((w) => `${path}: ${w}; skipped`));
    if (got !== null) values[name] = got;
  }
  return { values, warnings, mtimeMs: st?.mtimeMs ?? null };
}

// ── The defaults file ─────────────────────────────────────────────────────

/** The defaults file's path under the mod's folder (`$.plugin.root`): the
 * plugin carries it wherever it is installed, and the Python reads the
 * same file beside it in the checkout. */
export const DEFAULTS_REL = "defaults/config.jsonc";

/** Every option's default, by name: those a file may set from the
 * defaults file, null where derived, and those no file sets from the
 * spec. */
export type Defaults = { readonly [option: string]: Value };

/** The defaults file cannot be used: its path and every fault found,
 * "PATH: what; what". */
export class DefaultsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DefaultsError";
  }
}

/** The defaults file's text strictly read: every option, by name, with its
 * default.  Throws a DefaultsError naming the file and each key at fault:
 * a key missing, one that is no option or describes one run, or a value
 * not of its option's type (null only for a derived option, whose default
 * it follows).  config.parse_defaults' words, held to them by
 * tests/fixtures/config/defaults-cases.json. */
export function parseDefaults(path: string, text: string): Defaults {
  const { data, why } = objectOf(text);
  if (data === null) throw new DefaultsError(`${path}: ${why}`);
  const faults: string[] = [];
  const values: { [name: string]: Value } = {};
  for (const [name, value] of data) {
    if (name === "version") {
      const fault = versionFault(value);
      if (fault !== null) faults.push(fault);
      continue;
    }
    const { option, why: unknown } = known(name);
    if (option === null) {
      faults.push(unknown);
      continue;
    }
    const where = dumps(name);
    if (option.derived) {
      if (value !== null) {
        faults.push(`${where} must be null, to follow ` +
          dumps(option.derived.from));
      }
      values[name] = null;
      continue;
    }
    if (option.type === "table") {
      const got = defaultsTable(name, option, value);
      faults.push(...got.faults);
      values[name] = got.rows;
      continue;
    }
    const { got, bad } = scalar(option.type, value, option, where);
    if (bad !== null) faults.push(bad);
    values[name] = got;
  }
  for (const [name, option] of Object.entries(SPEC)) {
    if (option.file && !data.has(name)) faults.push(`${dumps(name)} is missing`);
  }
  if (faults.length) throw new DefaultsError(`${path}: ${faults.join("; ")}`);
  const out: { [name: string]: Value } = {};
  for (const [name, option] of Object.entries(SPEC)) {
    out[name] = option.file ? values[name] : option.default as Value;
  }
  return out;
}

/** A table's default, and each fault: every row and every field must be
 * there. */
function defaultsTable(name: string, option: OptionRec, value: Json):
    { rows: Rows | null; faults: string[] } {
  const { kept, why: faults } = table(name, option, value, null);
  if (!(value instanceof Map)) return { rows: null, faults };
  const rows: Rows = {};
  for (const row of option.rows ?? []) {
    rows[row] = { ...kept[row] };
    const rec = value.get(row);
    if (!value.has(row)) {
      faults.push(`${dumps(`${name}.${row}`)} is missing`);
      continue;
    }
    if (!(rec instanceof Map)) continue;
    for (const field of Object.keys(option.fields ?? {})) {
      if (!rec.has(field)) {
        faults.push(`${dumps(`${name}.${row}.${field}`)} is missing`);
      }
    }
  }
  return { rows, faults };
}

/** The defaults file at `path`, strictly read (parseDefaults). */
export async function readDefaults(path: string, fs: ConfigFs):
    Promise<Defaults> {
  const got = await textOf(path, fs, await fs.stat(path));
  if (got.text === null) {
    throw new DefaultsError(`${path}: ${got.why ?? "missing"}`);
  }
  return parseDefaults(path, got.text);
}

// ── The merge ─────────────────────────────────────────────────────────────

/** The layer an option's value came from: a file's, "default", or
 * "derived" for a value worked out from another option's. */
export type LayerName = Layer["name"] | "default" | "derived";

/** Every option's merged value and layer, each table field's layer where
 * a file set it (keyed "name.row.field"), and the files' warnings. */
export type Merged = {
  values: { [option: string]: Value };
  layers: { [option: string]: LayerName };
  fields: { [path: string]: Layer["name"] };
  warnings: readonly string[];
};

function deriveKey(value: Value): string {
  return typeof value === "boolean" ? (value ? "true" : "false")
    : String(value);
}

/** The files' layers (highest first) over `defaults`, every option of the
 * spec: lists replace and tables merge per field (Decided 3 and 10); a
 * derived value is worked out after, from the merged one it follows. */
export function merge(files: readonly Layer[], warnings: readonly string[],
    defaults: Defaults): Merged {
  const values: Merged["values"] = {};
  const layers: Merged["layers"] = {};
  const fields: Merged["fields"] = {};
  for (const [name, option] of Object.entries(SPEC)) {
    if (option.type === "table") {
      const rows: Rows = {};
      for (const [row, rec] of Object.entries(defaults[name] as Rows)) {
        rows[row] = { ...rec };
      }
      let layer: LayerName = "default";
      for (const f of [...files].reverse()) {
        if (!Object.hasOwn(f.values, name)) continue;
        layer = f.name;
        for (const [row, rec] of Object.entries(f.values[name] as Rows)) {
          for (const [field, v] of Object.entries(rec)) {
            rows[row][field] = v;
            fields[`${name}.${row}.${field}`] = f.name;
          }
        }
      }
      values[name] = rows;
      layers[name] = layer;
      continue;
    }
    const f = files.find((l) => Object.hasOwn(l.values, name));
    values[name] = f ? f.values[name] : defaults[name];
    layers[name] = f ? f.name : "default";
  }
  for (const [name, option] of Object.entries(SPEC)) {
    const derived = option.derived;
    if (derived && layers[name] === "default") {
      // The map names every value the option followed can take
      // (tools/gen-spec.py holds it to that).
      values[name] = derived.map[deriveKey(values[derived.from])] as Value;
      layers[name] = "derived";
    }
  }
  return { values, layers, fields, warnings: [...warnings] };
}

/** `name` in camel case, as the Options type names it: `usage-source`
 * is `usageSource`. */
export const camel = (name: string): string =>
  name.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());

/** The merged options the mod reads, by the camel case of their names:
 * every option with "mod" in its ports. */
export function optionsOf(merged: Merged): Options {
  const out: { [name: string]: Value } = {};
  for (const [name, option] of Object.entries(OPTIONS)) {
    if ((option.ports as readonly string[]).includes("mod")) {
      out[camel(name)] = merged.values[name];
    }
  }
  return out as unknown as Options;
}

/** What `load` found: where the walk started, the project root (null for
 * none), each file layer's path whether or not a file is there (null for a
 * project layer with no root), the layers read, and the merged options with
 * every warning. */
export type Found = {
  start: string;
  root: string | null;
  paths: Paths;
  layers: readonly Layer[];
  options: Merged;
};

/** Every file layer from `start`'s project and the user, highest first,
 * read, checked and merged over `defaults` (readDefaults).  A usage-source
 * a file gives that `agent` (any agent, for null) cannot read is skipped,
 * as any bad value is, and the layer under it supplies one
 * (cli._merged). */
export async function load(start: string, env: ConfigEnv, fs: ConfigFs,
    defaults: Defaults, agent: string | null = null): Promise<Found> {
  const { root, paths } = await find(start, env, fs);
  let files: Layer[] = [];
  const warnings: string[] = [];
  for (const name of FILE_LAYERS) {
    const path = paths[name];
    if (path === null) continue;
    const got = await readFile(path, fs, defaults);
    warnings.push(...got.warnings);
    if (Object.keys(got.values).length && got.mtimeMs !== null) {
      files.push({ name, path, mtimeMs: got.mtimeMs, values: got.values });
    }
  }
  for (;;) {
    const options = merge(files, warnings, defaults);
    const layer = options.layers["usage-source"];
    const bad = files.find((f) => f.name === layer);
    if (bad === undefined) break;
    const spec = options.values["usage-source"] as string;
    try {
      validateSource(agent ?? "", spec);
      break;
    } catch {
      warnings.push(`${bad.path}: "usage-source" ${dumpsUnicode(spec)} is ` +
        `no source ${agent ?? "any agent"} reads; skipped`);
      const { ["usage-source"]: _, ...rest } = bad.values;
      files = files.map((f) => f === bad ? { ...f, values: rest } : f);
    }
  }
  return { start: abspath(start), root, paths, layers: files,
    options: merge(files, warnings, defaults) };
}
