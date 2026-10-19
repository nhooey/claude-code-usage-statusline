// The figures boundary: a figures document back as the records the
// renderers take, and stage two of each readout drawn from it.
//
// A port of the render half of "The figures boundary" in
// coding_agent_usage_line/claude.py: decode_record and its tables, and
// render_status_figures with the argv reading it does.  tests/README.md,
// "Figures", is the document's schema.  The cost line's half lives beside
// its own renderer.
//
// The Python's render stage reads two things from outside the document:
// the terminal profile, from the environment, and HOME, to show the
// working directory as "~".  Here both are the caller's, the profile as
// the Settings it builds (statusSettings) and HOME as an argument.  It
// also points TZ at the document's clock.tz and calls tzset; JavaScript
// reads TZ afresh for every Date, so the edge sets process.env.TZ before
// drawing and nothing here touches the environment.
import { STAMP_FMT } from "./spec.ts";
import { settings } from "./formatting.ts";
import type { Env, Settings } from "./formatting.ts";
import type {
  CacheShares, Git, Limits, Payload, Transcript,
} from "./claude_records.ts";
import { renderStatus } from "./claude_render.ts";
import { isDict, pyIsDigit, pyIntDigits } from "./py.ts";
import type { Dict } from "./py.ts";

export const FIGURES_SCHEMA = 1;

// ════════════════════════════════════════════════════════════════════════════
// Records.
// ════════════════════════════════════════════════════════════════════════════

/** How decode_record reads a field back, from the record's annotation:
 * "str", a string written null when empty; "stamp", a STAMP_FMT local time
 * written as an epoch; and "value", anything else, which JSON already
 * carries as the record holds it.  A JavaScript number is a float and an
 * int at once, so _fig_typed's float() and int() have nothing to do. */
type Kind = "str" | "stamp" | "value";

type Fields = { readonly [field: string]: Kind };

const PAYLOAD: Fields = {
  current_dir: "str", project_dir: "str", model: "str", model_id: "str",
  ctx_window: "str", transcript: "str", cost_usd: "str", lines_added: "str",
  lines_removed: "str", output_style: "str", effort: "str",
  session_id: "str", rl_session_pct: "str", rl_session_reset: "str",
  rl_weekly_pct: "str", rl_weekly_reset: "str", pr_number: "str",
};

const TRANSCRIPT: Fields = {
  tok_up: "value", tok_down: "value", cache_pct: "value",
  ctx_tokens: "value", user_ts: "str", user_text: "str", asst_ts: "str",
  asst_text: "str", busy_s: "value", start_s: "value", tool_s: "value",
  blocked_s: "value", turn_s: "value", eta: "value", agent_etas: "value",
  queued: "value", compactions: "value", ctx_est: "value", shells: "value",
  monitors: "value", tool_at: "value", wait_at: "value", idle_at: "value",
  last_seen: "value",
};

const GIT: Fields = {
  in_git: "value", branch: "str", dirty: "value", toplevel: "str",
  main_root: "str", is_worktree: "value",
};

// _FIG_STAMPS: the two reset times, carried as epochs.
const LIMITS: Fields = {
  session_pct: "str", session_reset: "stamp", session_share: "str",
  weekly_pct: "str", weekly_reset: "stamp", weekly_share: "str",
  session_turn: "str", weekly_turn: "str",
};

const CACHE_SHARES: Fields = {
  turn_read: "value", turn_write: "value", sess_read: "value",
  sess_write: "value",
};

// _FIG_MISSING: the record's value for "missing", which the document
// writes null.
const TRANSCRIPT_MISSING: Dict = {
  cache_pct: -1, start_s: 0.0, turn_s: 0.0, tool_at: 0.0, wait_at: 0.0,
  idle_at: 0.0, last_seen: 0.0,
};

/** _epoch_stamp: an epoch as time.strftime(STAMP_FMT, localtime(e)) writes
 * it in the process's zone, or "" for none.  localtime floors a fraction
 * to the second; the stamp then drops the seconds, as the Python's does,
 * so a countdown to it is read to the minute. */
export function epochStamp(e: number | null): string {
  if (e === null) return "";
  if (STAMP_FMT !== "%Y-%m-%d %H:%M") throw new Error("STAMP_FMT changed");
  const d = new Date(Math.floor(e) * 1000);
  const two = (n: number): string => String(n).padStart(2, "0");
  return String(d.getFullYear()).padStart(4, "0") + "-" +
    two(d.getMonth() + 1) + "-" + two(d.getDate()) + " " +
    two(d.getHours()) + ":" + two(d.getMinutes());
}

/** decode_record: every field must be present, since a document missing
 * one is from another schema, not a record with a default. */
function decodeRecord<T>(fields: Fields, d: unknown,
  missing: Dict = {}): T {
  if (!isDict(d)) throw new TypeError("a figures record is not an object");
  const out: Dict = {};
  for (const [field, kind] of Object.entries(fields)) {
    if (!Object.hasOwn(d, field)) throw new Error("no field " + field);
    const v = d[field];
    if (kind === "stamp") out[field] = epochStamp(v as number | null);
    else if (v === null && Object.hasOwn(missing, field)) {
      out[field] = missing[field];
    } else if (v === null && kind === "str") out[field] = "";
    else out[field] = v;
  }
  return out as T;
}

export function decodePayload(d: unknown): Payload {
  return decodeRecord<Payload>(PAYLOAD, d);
}

export function decodeTranscript(d: unknown): Transcript {
  return decodeRecord<Transcript>(TRANSCRIPT, d, TRANSCRIPT_MISSING);
}

export function decodeGit(d: unknown): Git {
  return decodeRecord<Git>(GIT, d);
}

export function decodeLimits(d: unknown): Limits {
  return decodeRecord<Limits>(LIMITS, d);
}

export function decodeCacheShares(d: unknown): CacheShares {
  return decodeRecord<CacheShares>(CACHE_SHARES, d);
}

// ════════════════════════════════════════════════════════════════════════════
// The flags a render reads.
// ════════════════════════════════════════════════════════════════════════════

/** _flag: the value after `--name`, matched by membership. */
export function flag(argv: readonly string[], name: string,
  dflt = ""): string {
  const i = argv.indexOf(name);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : dflt;
}

/** column_rules: the ASK for the rules; rulesOn decides the room. */
export function columnRules(argv: readonly string[]): boolean {
  return argv.includes("--column-rules") &&
    !argv.includes("--no-column-rules");
}

/** _cols: --cols as a width, "--cols 0" an unknown one, and anything else
 * the terminal's width, which the edge measures and passes as `termCols`
 * (term_cols in formatting.ts). */
export function cols(argv: readonly string[],
  termCols: number | null = null): number | null {
  const s = flag(argv, "--cols");
  if (!pyIsDigit(s)) return termCols;
  return pyIntDigits(s) || null;
}

/** The settings a render draws under: the terminal profile from `env`, and
 * the two switches main() sets from argv before anything is drawn. */
export function statusSettings(env: Env, argv: readonly string[]): Settings {
  return settings(env, !argv.includes("--no-mark-spacing"),
    argv.includes("--subscript-decimals"));
}

// ════════════════════════════════════════════════════════════════════════════
// Stage two.
// ════════════════════════════════════════════════════════════════════════════

/** render_status_figures: the status document drawn at --cols under the
 * flags in argv, reading no file and no clock.  `home` stands for HOME. */
export function renderStatusFigures(st: Settings, fig: Dict,
  argv: readonly string[], home: string,
  termCols: number | null = null): string {
  const clock = fig.clock as Dict;
  const rate = fig.rate as number | null;
  let output = renderStatus(st,
    decodePayload(fig.payload), decodeTranscript(fig.transcript),
    decodeGit(fig.git), decodeLimits(fig.limits), cols(argv, termCols),
    clock.now as number, columnRules(argv),
    Math.trunc(fig.context_window as number), rate,
    decodeCacheShares(fig.cache_shares), home);
  const text = (fig.usage as Dict).account_text;
  if (text) output += (text as string) + "\n";
  return output;
}
