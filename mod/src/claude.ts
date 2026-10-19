// The glue in claude.py that strings the accounting together per render:
// the status and cost figures documents, from what the edge has read.
//
// claude_records.ts reads a transcript, claude_calib.ts works out the plan
// shares and their calibration, claude_sources.ts reads the usage source;
// this is the Python's orchestration of them, `status_figures`,
// `cost_figures`, `_with_shares`, `window_for` and `ctx_window_for`, and
// `detect_git`'s reading of git's answers.  Each keeps its Python name in
// camelCase, so a change to one names the place to change in the other.
//
// Pure, as the modules it strings together are: the Python reads files,
// runs git, and reads the clock and the environment inside these
// functions, and here each of those comes in as an argument, read by the
// edge.  The mod's edge is its handlers (mod/hooks/), which read through
// `$`; the tests' is Node.  Where the Python catches everything around a
// read so that a figure it cannot have is missing rather than a failed
// render, the edge passes null for what it could not read.
import { CTX_1M, CTX_DEF } from "./spec.ts";
import { pyFormatF, pyIntDigits, pyIsDigit } from "./py.ts";
import type { Dict } from "./py.ts";
import {
  cacheShares, NO_CACHE_SHARES, NO_GIT, NO_LIMITS, openTurn,
} from "./claude_records.ts";
import type {
  CacheShares, Git, Limits, Payload, Transcript, Turn,
} from "./claude_records.ts";
import {
  costAccounting, ownAccounting, sessionAccounting, sessionCacheShares,
  sessionShares, turnAccounting, turnShares, windowShares,
} from "./claude_calib.ts";
import type { Calib, Snapshot } from "./claude_calib.ts";
import type { PreparedClaudeReading } from "./claude_sources.ts";
import {
  encodeCacheShares, encodeGit, encodeLimits, encodePayload,
  encodeTranscript, FIGURES_SCHEMA, stampEpoch,
} from "./figures.ts";
import { encodeTurn } from "./claude_cost.ts";

// ════════════════════════════════════════════════════════════════════════════
// Git.
// ════════════════════════════════════════════════════════════════════════════

/** Runs `git --no-optional-locks <args>` in the session's directory and
 * answers its stdout less the trailing newlines, or null when it fails:
 * the Python's `_git`, which the edge supplies. */
export type GitRun = (args: readonly string[]) => Promise<string | null>;

/** Resolve --git-common-dir to the MAIN repo root, and say if we are in a
 * linked worktree.  --show-toplevel is the current worktree's root, and
 * --git-common-dir always the main repo's .git, so its dirname is the main
 * root wherever we are: a worktree shows the project as the repo's name. */
export function _mainRoot(common: string, toplevel: string):
  [string, boolean] {
  if (!common.startsWith("/")) common = toplevel + "/" + common;
  const root = common.endsWith("/.git") ? common.slice(0, -5)
    : common.slice(0, Math.max(0, common.lastIndexOf("/")));
  return [root, Boolean(toplevel && toplevel !== root)];
}

/** The git context in three invocations, as detect_git reads it.
 *
 * --abbrev-ref and --short cannot both be asked for in one rev-parse, so
 * the branch is a symbolic-ref of its own; a detached HEAD shows its short
 * sha.  An empty repo still gets its project name. */
export async function detectGit(git: GitRun): Promise<Git> {
  const out = await git(["rev-parse", "--show-toplevel", "--git-common-dir",
    "--short", "HEAD"]);
  if (out === null) {
    if (await git(["rev-parse", "--is-inside-work-tree"]) === null) {
      return NO_GIT;
    }
    const toplevel = (await git(["rev-parse", "--show-toplevel"])) || "";
    const common = (await git(["rev-parse", "--git-common-dir"])) || "";
    const [root, wt] = common ? _mainRoot(common, toplevel) : ["", false];
    return { in_git: true, branch: "", dirty: false, toplevel,
      main_root: root, is_worktree: wt };
  }
  const lines = out.split("\n");
  const toplevel = lines[0] ?? "", common = lines[1] ?? "";
  const sha = lines[2] ?? "";
  const [root, wt] = _mainRoot(common, toplevel);
  const branch = (await git(["symbolic-ref", "--short", "HEAD"])) ?? sha;
  // Staged and unstaged: `diff --quiet` fails on either.
  const dirty = (await git(["diff", "--quiet", "HEAD"])) === null;
  return { in_git: true, branch, dirty, toplevel, main_root: root,
    is_worktree: wt };
}

// ════════════════════════════════════════════════════════════════════════════
// The context window.
// ════════════════════════════════════════════════════════════════════════════

/** The context window: Claude Code's own figure, or a guess from the
 * model's name.  The figure is the one the thing enforcing the window
 * uses, so it wins outright; the name is the fallback for a payload that
 * omits it. */
export function ctxWindowFor(size: string, name: string): number {
  // str.isdigit and int(): any script's decimal digits.
  if (pyIsDigit(size) && pyIntDigits(size) > 0) return pyIntDigits(size);
  const low = name.toLowerCase();
  return low.includes("1m") || low.includes("1000000") ? CTX_1M : CTX_DEF;
}

/** The context window in force for the cost line: what the status line
 * published (`published`, 0 for none), else the largest reading seen,
 * since a reading above 200k proves the larger window.  The mod publishes
 * to itself: the band's last window is the receipt's. */
export function windowFor(turns: readonly Turn[], published: number):
  number {
  if (published > 0) return published;
  let biggest = 0;
  for (const t of turns) biggest = Math.max(biggest, t.ctx);
  return biggest > CTX_DEF ? CTX_1M : CTX_DEF;
}

// ════════════════════════════════════════════════════════════════════════════
// The shares.
// ════════════════════════════════════════════════════════════════════════════

/** "%g" % v: six significant digits, trailing zeros dropped, and an
 * exponent past them; Python rounds half to even, as pyFormatF does. */
export function pyG(v: number): string {
  if (!Number.isFinite(v)) {
    return Number.isNaN(v) ? "nan" : v > 0 ? "inf" : "-inf";
  }
  if (v === 0) return Object.is(v, -0) ? "-0" : "0";
  const exp = parseInt(Math.abs(v).toExponential(5).split("e")[1], 10);
  const strip = (s: string) =>
    s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
  if (exp >= -4 && exp < 6) return strip(pyFormatF(v, 5 - exp));
  const [m, e] = v.toExponential(5).split("e");
  const n = parseInt(e, 10);
  return strip(m) + "e" + (n < 0 ? "-" : "+") +
    String(Math.abs(n)).padStart(2, "0");
}

/** A percentage as the limit rows carry it, or "" for a missing figure:
 * nothing rounded, "%g" so a whole one reads "15". */
export function _pctStr(v: number | null): string {
  return v === null ? "" : pyG(v);
}

/** What _with_shares adds to the status document: the turn the receipt
 * would bill, the turn opened last, and the accounting of each, of the
 * session and of the main thread alone. */
export type SharesExtra = {
  readonly turn: Dict | null;
  readonly open_turn: Dict | null;
  readonly accounting: {
    readonly turn: Dict | null;
    readonly open_turn: Dict | null;
    readonly session: Dict | null;
    readonly own: Dict | null;
  };
};

const NONE: SharesExtra = { turn: null, open_turn: null,
  accounting: { turn: null, open_turn: null, session: null, own: null } };

/** Attach how much of each window this session, and its last turn, used.
 *
 * `turns` is readTurns' reading of the transcript, or null where there is
 * no transcript or it could not be read; `main` the main thread's own
 * Transcript; `snap` the plan snapshot seeded from `lim`; `calib` the
 * calibration, which the edge asks for only while `lim` has a reading,
 * null when it could not be had.  Returns the limits with the session's
 * and the turn's shares in, the 📖 📝 cache shares, and the status
 * document's `turn`, `open_turn` and `accounting`.
 *
 * WHICH TURN the 🎤 figure is about is the last that made calls and is
 * neither a compaction nor an agent's, the receipt's pick, so the two
 * describe the same turn.  claude.py's docstring has the history. */
export function _withShares(lim: Limits, turns: readonly Turn[] | null,
  main: Transcript, snap: Snapshot, calib: Calib | null):
  [Limits, CacheShares, SharesExtra] {
  if (turns === null) return [lim, NO_CACHE_SHARES, NONE];
  let last: Turn | null = null;
  let cache = NO_CACHE_SHARES;
  let opened: Turn | null;
  try {
    for (const t of turns) {
      if (t.calls && !t.compact && !t.agent) last = t;
    }
    opened = openTurn(turns);
    if (turns.length) {
      const [tr, tw] = last !== null ? turnShares(last) : [null, null];
      const [sr, sw] = sessionCacheShares(turns);
      cache = cacheShares({ turn_read: tr, turn_write: tw, sess_read: sr,
        sess_write: sw });
    }
  } catch {
    return [lim, NO_CACHE_SHARES, NONE];
  }
  const figures = (c: Calib): SharesExtra => {
    // A figure the grid cannot have is missing, never a failed render.
    try {
      return {
        turn: last === null ? null : encodeTurn(last),
        open_turn: opened === null ? null : encodeTurn(opened),
        accounting: {
          turn: last === null ? null : turnAccounting(last, c, snap),
          open_turn: opened === null ? null
            : turnAccounting(opened, c, snap),
          session: turns.length ? sessionAccounting(turns, c, snap) : null,
          own: ownAccounting(main, c, snap),
        },
      } as SharesExtra;
    } catch {
      return NONE;
    }
  };
  if (!lim.session_pct && !lim.weekly_pct) return [lim, cache, figures({})];
  let sh: { sess: number | null; week: number | null };
  let tn: { sess: number | null; week: number | null } =
    { sess: null, week: null };
  try {
    if (calib === null) throw new Error("no calibration");
    sh = sessionShares(turns, calib, snap);
    if (last !== null) tn = windowShares(last, calib, snap);
  } catch {
    return [lim, cache, figures({})];
  }
  return [{ ...lim, session_share: _pctStr(sh.sess),
    weekly_share: _pctStr(sh.week), session_turn: _pctStr(tn.sess),
    weekly_turn: _pctStr(tn.week) }, cache, figures(calib)];
}

// ════════════════════════════════════════════════════════════════════════════
// The documents.
// ════════════════════════════════════════════════════════════════════════════

/** The plan reading the accounting divided by: the snapshot, with its
 * window ends as epochs.  All null when there was none. */
export function _figPlan(snap: Snapshot): Dict {
  const at = (k: string): number | null => {
    const v = snap[k];
    return typeof v === "string" ? stampEpoch(v) : null;
  };
  return { session_pct: snap.session_pct ?? null,
    session_resets_at: at("session_resets_at"),
    weekly_pct: snap.weekly_pct ?? null,
    weekly_resets_at: at("weekly_resets_at") };
}

/** What the usage source gave: its version-1 reading and the plan figures
 * taken from it.  The account summary row is not ported (see
 * claude_sources.ts), so `account_text` is always null here. */
export function _figUsage(prepared: PreparedClaudeReading, snap: Snapshot):
  Dict {
  const reading = prepared.reading;
  return { reading: reading && Object.keys(reading).length ? reading : null,
    plan: _figPlan(snap), account_text: null };
}

/** The limits a reading projects, or none without a reading: a failed
 * named source is unavailable, not permission to quote another. */
export function baseLimits(prepared: PreparedClaudeReading): Limits {
  const r = prepared.reading;
  return r && Object.keys(r).length ? prepared.limits : NO_LIMITS;
}

/** Everything the status document is made from, as the edge read it. */
export type StatusInputs = {
  readonly payload: Payload;          // current_dir and project_dir filled
  readonly transcript: Transcript;    // EMPTY_TRANSCRIPT with none
  readonly turns: readonly Turn[] | null;
  readonly git: Git;
  readonly prepared: PreparedClaudeReading;
  readonly snap: Snapshot;            // seedLimitsSnapshot of the reading
  readonly calib: Calib | null;       // asked for only with a plan reading
  readonly now: number;
  readonly tz: string | null;
  readonly rate: number | null;
};

/** Stage one of the status line, past its reads: the figures document the
 * band draws.  `_with_shares` over the read, the context window from the
 * payload, and the usage source's reading. */
export function statusFigures(inp: StatusInputs): Dict {
  const [lim, cache, extra] = _withShares(baseLimits(inp.prepared),
    inp.turns, inp.transcript,
    inp.snap, inp.calib);
  const pay = inp.payload;
  return {
    schema: FIGURES_SCHEMA, mode: "status",
    clock: { now: inp.now, tz: inp.tz },
    payload: encodePayload(pay),
    transcript: encodeTranscript(inp.transcript),
    git: encodeGit(inp.git),
    limits: encodeLimits(lim),
    cache_shares: encodeCacheShares(cache),
    context_window: ctxWindowFor(pay.ctx_window, pay.model + pay.model_id),
    rate: inp.rate,
    turn: extra.turn,
    open_turn: extra.open_turn,
    accounting: extra.accounting,
    usage: _figUsage(inp.prepared, inp.snap),
  };
}

/** Stage one of the cost line, past the transcript read: the context
 * window, the calibration and the plan reading the turns are divided by,
 * and what each turn and the session come to. */
export function costFigures(turns: readonly Turn[], win: number,
  calib: Calib, snap: Snapshot, prepared: PreparedClaudeReading,
  now: number, tz: string | null): Dict {
  return {
    schema: FIGURES_SCHEMA, mode: "cost",
    clock: { now, tz },
    turns: turns.map(encodeTurn),
    context_window: win,
    calibration: { sess: calib.sess ?? null, week: calib.week ?? null },
    accounting: costAccounting(turns, calib, snap),
    usage: _figUsage(prepared, snap),
  };
}
