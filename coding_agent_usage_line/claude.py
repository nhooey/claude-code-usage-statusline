#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Code status line and prompt-cost line, in one program.

Two readouts, two modes, one set of facts:

    --mode status   stdin: the status-line JSON payload
                    stdout: three rows, redrawn continuously
    --mode cost     stdin: the Stop-hook JSON payload
                    stdout: {"systemMessage": "<two rows>"}, once per turn
    --mode subagent stdin: the agent panel's task list
                    stdout: one {"id", "content"} line per task, every tick
    --selftest      draws specimen rows on the tty and asks the terminal
                    where the cursor landed; needs a real terminal tab

They were separate programs in separate languages (statusline.sh and
cost-line.py plus its hook), sharing glyphs, column widths, billing weights
and a whole width-measurement layer by copy.  The copies drifted, and the
drift could only be repaired by hand because nothing could be imported across
the language boundary.  This file exists so those facts are stated once.

── BEFORE YOU EDIT: READ docs/ ─────────────────────────────────────────────

README.md is the short pitch; docs/ carries what is worth knowing BEFORE
opening this file, rather than while standing at one line of it.  Four
things in particular, each of which has cost time to relearn and each of
which is short there:

  * docs/glyphs-and-terminals.md — JediTerm disagrees with every
    published width table AND with itself, so widths are MEASURED, never
    inferred from which row looks wrong.  Also how to tell a layout bug from
    a paint bug, which is the first question to settle, not the last.
  * The same file, "Why vis_width is not a correct Unicode implementation" —
    it counts per
    codepoint with a hand-maintained table.  Both look like bugs and both are
    deliberate.  Swapping in wcwidth or unicodedata.east_asian_width breaks
    the alignment of every row; it is tempting and has been attempted before.
  * docs/layout.md, "The layout rule" — fixed field widths, fixed segment
    reservations, one right-aligned constant.  Switching tabs must not move
    the numbers.
  * The same file, '"Stop says: ", and the eleven columns' — the chrome the
    cost line is laid out against, and why its rows ship as ONE
    systemMessage.

Style: pure functions over frozen NamedTuple records.  Nothing here reads
mutable module state; the module-level names are constants, and the few that
depend on the terminal are computed once at import and passed as default
arguments so a test can substitute them.  Standard library only, and written
to run on Python 3.9 — the macOS Command Line Tools interpreter — so it works
in any project, not only one whose devshell supplies newer packages.
"""

import fcntl
import functools
import glob
import hashlib
import json
import os
import plistlib
import re
import struct
import subprocess
import sys
import termios
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple


from . import formatting as fmt
from . import state
from .formatting import *  # immutable display API and pure helpers
_UTC = fmt._UTC

# Claude records/parsing is separate from all terminal rendering.
from .claude_records import *
from .claude_records import (_agent_dir, _dedupe_usage, _num, _price,
                             _records, _stamp_utc, _usd, ts_epoch)
from .claude_render import *
from .claude_cost_render import (COLOUR_INK, PLAIN_INK, CostOpts, Ink,
                                 place, render_cost_line as _pure_cost_render)
from .claude_sources import prepare_claude_reading
from . import claude_subagent_render as subagent_render

CALIB_TTL = 300        # the scan walks transcripts; five minutes is plenty
# The expensive calibration scan is private and scope-keyed below
# ``state.state_dir()``.  This exact path override is deliberately for
# fixture injection only; it is never a broad cross-account default.
CALIB_CACHE_OVERRIDE = os.environ.get("CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE", "")

# This is external Claude history, not application state.  It remains opt-in
# configurable, while all writes use the product's private state directory.
PROJECTS_DIR = os.environ.get("CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR",
                              os.path.expanduser("~/.claude/projects"))

# The smallest plan reading that can serve as the DIVISOR of a calibration.
#
# used_percentage arrives quantised to whole percent, so a reading of n means
# the truth is somewhere in a band half a point wide either side of it: at
# n=1 that is ±50٪ — a factor of three across the band — and every share
# divided by a unit derived from it inherits the whole of that.  At 2 the band
# is ±25٪, at 5 it is ±10٪.  Two is where a figure stops being wrong by more
# than itself, which is the only threshold this reading can actually support;
# it is not where the figure becomes precise, and nothing here can make it so,
# because the payload does not publish a finer one.
#
# What this costs is the 🔋 shares for the first few minutes of every 5-hour
# window, which then read "?" — see render_limit's fig(), which draws exactly
# that for a figure it does not have.  What it buys is that they never again
# read 18٪ under an account total of 1٪.  The weekly window sits above this
# for all but the first hours of a week, so it pays almost nothing.
CALIB_MIN_PCT = 2.0


def frozen_now() -> Optional[float]:
    """The wall clock, pinned, or None to read the real one.

    Every renderer that needs the time already takes `now` and defaults it to
    time.time(); this is the one place that fills it in, and it fills it in
    from the environment so a test can pin it without touching an argument
    list.  None everywhere else, which is what the live status line passes.

    It exists because the differential test that preceded the golden files
    could not pin the clock at all.  Both programs read it independently, so a
    second ticking between the two runs was a false failure, and the harness
    answered that by running the reference twice and comparing only when the
    two agreed — up to six attempts per comparison, and a SKIP when the clock
    beat all six.  A clean run skipped 15 of 78.  Those 15 were not passes and
    were not failures; they were comparisons that did not happen, and which
    ones varied per run.  Pinning the clock costs one environment variable and
    makes the other 63 reproducible as well as green.

    TZ is the caller's business: the readout formats in local time, so a golden
    file records the zone it was generated in and the harness sets TZ to match.
    """
    v = os.environ.get("CODING_AGENT_USAGE_LINE_NOW", "")
    try:
        return float(v) if v else None
    except ValueError:
        return None


# ════════════════════════════════════════════════════════════════════════════
# Git.
# ════════════════════════════════════════════════════════════════════════════

def _git(*args: str) -> Optional[str]:
    """Run git with locking disabled, or None if it fails."""
    try:
        p = subprocess.run(("git", "--no-optional-locks") + args,
                           capture_output=True, text=True)
    except Exception:
        return None
    return p.stdout.rstrip("\n") if p.returncode == 0 else None


def _main_root(common: str, toplevel: str) -> Tuple[str, bool]:
    """Resolve --git-common-dir to the MAIN repo root, and say if we are in a
    linked worktree.

    --show-toplevel returns the CURRENT worktree's root, which for a linked
    worktree is the worktree directory and not the main repo.  --git-common-dir
    always points at the main repo's .git, shared across all worktrees, so
    dirname of it is the main repo root wherever we are.  That is what makes a
    worktree at ~/repo/.claude/worktrees/foo show the project as "repo" rather
    than "foo" — the worktree's branch is already conveyed by the 🌿 segment.
    """
    if not common.startswith("/"):
        common = toplevel + "/" + common
    root = common[:-5] if common.endswith("/.git") else common.rsplit("/", 1)[0]
    return root, bool(toplevel and toplevel != root)


def detect_git() -> Git:
    """Read the git context in three invocations.

    --abbrev-ref and --short cannot both be asked for in one rev-parse: flag
    modes apply globally to every rev in the call, so mixing them clobbers one.
    Hence the separate symbolic-ref.
    """
    out = _git("rev-parse", "--show-toplevel", "--git-common-dir", "--short",
               "HEAD")
    if out is None:
        # Either not a repo, or a repo with no commits yet.  Distinguish them
        # cheaply so the empty-repo case still gets a project name.
        if _git("rev-parse", "--is-inside-work-tree") is None:
            return NO_GIT
        toplevel = _git("rev-parse", "--show-toplevel") or ""
        common = _git("rev-parse", "--git-common-dir") or ""
        root, wt = _main_root(common, toplevel) if common else ("", False)
        return Git(True, "", False, toplevel, root, wt)

    lines = out.split("\n")
    toplevel = lines[0] if len(lines) > 0 else ""
    common = lines[1] if len(lines) > 1 else ""
    sha = lines[2] if len(lines) > 2 else ""
    root, wt = _main_root(common, toplevel)
    branch = _git("symbolic-ref", "--short", "HEAD")
    if branch is None:
        branch = sha                       # detached HEAD
    dirty = _git("diff", "--quiet", "HEAD") is None    # staged + unstaged
    return Git(True, branch, dirty, toplevel, root, wt)




def ctx_window_for(size: str, name: str) -> int:
    """The context window: Claude Code's own figure, or a guess from the name.

    The payload carries context_window.context_window_size, which is the
    number the thing enforcing the window is actually using.  Prefer it
    absolutely.  Reading the model's NAME for a "1m" was always inference
    dressed as fact, and it is wrong in both directions: a model whose window
    is not written into its id reads as 200k whatever it really is, which is
    why switching to Fable dropped the ruler to 200k, and why coming back to
    an Opus selected without the [1m] suffix left it there.

    The name remains the fallback, for a payload that predates the field or
    omits it.  Kept deliberately: a ruler that guesses is better than a row
    with a hole in it, and the guess is right for the id it was written for.
    """
    if size.isdigit() and int(size) > 0:
        return int(size)
    low = name.lower()
    return CTX_1M if ("1m" in low or "1000000" in low) else CTX_DEF


# ════════════════════════════════════════════════════════════════════════════
# Plan limits.
# ════════════════════════════════════════════════════════════════════════════

def _pct_num(v) -> Optional[float]:
    """A carried percentage back as a number, or None if it is not one.

    None rather than 0.0 for the unparseable case, because a missing figure and
    a window at zero are the two things this section spends most of its care
    keeping apart.
    """
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct_str(v: Optional[float]) -> str:
    """A percentage as the limit rows carry it, or "" for a missing figure.

    Nothing is rounded here, which is the point: the payload's used_percentage
    is a float and this used to meet it with "%.0f", so a window at 0.38٪
    reached the renderer as "0" and no later code could tell that from a window
    at nothing.  Precision is now thrown away once, in limit_pct, where the
    column budget is actually known.

    "%g" rather than "%s" for two reasons.  It writes a whole percentage as
    "15", not "15.0" — the baseline file this string goes into was read by
    statusline.sh with a digits-only test that "15.0" fails.  That reader is
    retired (archive/), so only the second reason still binds: "%g" holds the
    figure to six significant digits, so subtracting two readings cannot write
    "0.19999999999999996" into a file the next render has to parse.
    """
    return "" if v is None else "%g" % v


# Claude Usage Tracker parsing is retained as a local, credential-minimising
# adapter.  Source choice, command execution, validation and caching live in
# ``sources.py``; this module only translates its tracker store fields.

APPLE_EPOCH = 978307200         # 2001-01-01 UTC, in Unix seconds.  Every
                                # timestamp in a macOS app's own store is in
                                # this epoch; every one in this program is in
                                # Unix.  Converted at the boundary, once.


def _stamp(t: float) -> str:
    """A Unix epoch as the stamp every channel here carries."""
    return time.strftime(STAMP_FMT, time.localtime(t))


def _as_epoch(v) -> Optional[float]:
    """A carried time back as a Unix epoch, whichever way it was carried.

    Sources differ and are allowed to: the menu-bar app stores Apple-epoch
    floats, Claude Code's payload sends Unix epochs, a hand-written script is
    likeliest to print the stamp it already had.  All three arrive here and
    only one shape leaves.

    An epoch is distinguished from a stamp by being a number, not by its
    magnitude — no threshold, because a threshold is a rule that works until
    the day it does not and then fails silently in the direction of a
    plausible wrong answer.
    """
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            pass
        try:
            return time.mktime(time.strptime(s, STAMP_FMT))
        except (ValueError, OverflowError):
            return None
    return None


class ClaudeUsageTrackerSource:
    """Claude Usage Tracker, the macOS menu-bar app.

        https://github.com/hamed-elfayome/Claude-Usage-Tracker

    It polls Anthropic on its own schedule and keeps the answer in its
    UserDefaults store, which is why this is worth reading at all: no OAuth
    handling here, no network call, no token to keep — the figures are already
    on disk and somebody else's program is responsible for refreshing them.

    Read through `defaults export` rather than by opening the .plist, because
    a running app's preferences live in cfprefsd and reach the file when
    cfprefsd feels like it.  The app writes a reading every 30 seconds and the
    file lagged it by minutes in testing.  One subprocess, and it replaces the
    three the shell wrapper spawned.

    CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST overrides that with a path to
    an exported plist
    file.  It is the seam tests/usage-source.sh drives — a fixture store, on
    any platform, with no app installed — and it doubles as the escape hatch
    for reading a store copied off another machine.
    """

    name = "claude-usage-tracker"
    DOMAIN = "HamedElfayome.Claude-Usage"
    PLIST = "~/Library/Preferences/HamedElfayome.Claude-Usage.plist"
    ENV = "CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST"

    def available(self) -> bool:
        if os.environ.get(self.ENV):
            return True
        # The file is the CHEAP test — `defaults export` on an unknown domain
        # succeeds and prints an empty dict, so asking it costs a process to
        # learn nothing.  The file lags the live store, which makes it a bad
        # source and a perfectly good existence check.
        return (sys.platform == "darwin"
                and os.path.isfile(os.path.expanduser(self.PLIST)))

    def _store(self) -> dict:
        path = os.environ.get(self.ENV)
        if path:
            with open(os.path.expanduser(path), "rb") as fh:
                return plistlib.load(fh)
        p = subprocess.run(["defaults", "export", self.DOMAIN, "-"],
                           capture_output=True, timeout=15)
        return plistlib.loads(p.stdout) if p.stdout else {}

    def read(self) -> dict:
        try:
            return tracker_reading(self._store())
        except Exception:
            return {}


def tracker_reading(store: dict) -> dict:
    """The tracker's UserDefaults, read down to the figures this program uses.

    Separated from the source that fetches the store so it can be tested
    without a Mac, an app, or a subprocess: hand it a dict and read the answer.
    Every part of this that is worth getting wrong is in here.

    WHERE THE FIGURES LIVE.  `profiles_v3` is a JSON array stored as bytes —
    one record per configured account — and each record carries a
    `claudeUsage` object with the current reading in it:

        sessionPercentage       5-hour window, whole plan
        sessionResetTime        Apple epoch
        weeklyPercentage        7-day window
        weeklyResetTime         Apple epoch
        opusWeeklyPercentage    the Opus sub-limit
        lastUpdated             when the app took this reading

    `activeProfileId` at the top level of the store names the record to read;
    `isSelectedForDisplay` is the fallback, and the first record is the
    fallback's fallback, because a store with one account has nothing to
    choose between and should not need to be configured to say so.

    NOTHING ELSE IS TOUCHED, and the reason is two keys along from the one
    that is: the same profile record holds `oauthAccountJSON` and an API
    session key.  This function names the six fields it wants and
    The shared collector whitelists the returned v1 fields before private,
    scoped caching; a credential therefore cannot enter application state.

    THE OLD SHAPE IS GONE.  Until 2026-09 the store held `usageHistory_<uuid>`
    — a rolling array of {sessionReset, weeklyReset} snapshots — and the 5-hour
    reset was NOT in it: on a sessionReset snapshot `triggeringResetTime` was
    a copy of the snapshot's own timestamp, so the wrapper script derived the
    window instead, from the most recent 0٪ → non-zero transition in the
    history.  That history now lives in a file
    (~/Library/Application Support/Claude Usage/history/) and the reset is
    published directly and correctly, so the derivation is not ported.  It is
    written down here rather than carried as code because carrying it means
    parsing nine megabytes of JSON on the off-chance, and because the thing it
    worked around is fixed: reviving it is a matter of reading that file, not
    of remembering what it did.
    """
    profs = store.get("profiles_v3")
    if isinstance(profs, (bytes, bytearray)):
        profs = profs.decode("utf-8", "replace")
    if isinstance(profs, str):
        try:
            profs = json.loads(profs)
        except ValueError:
            return {}
    if not isinstance(profs, list) or not profs:
        return {}

    want = store.get("activeProfileId")
    prof = (next((p for p in profs
                  if isinstance(p, dict) and p.get("id") == want), None)
            or next((p for p in profs
                     if isinstance(p, dict) and p.get("isSelectedForDisplay")),
                    None)
            or (profs[0] if isinstance(profs[0], dict) else None))
    if not prof:
        return {}
    u = prof.get("claudeUsage")
    if not isinstance(u, dict):
        return {}

    def unix(v):
        t = _as_epoch(v)
        return None if t is None else t + APPLE_EPOCH

    return {
        "session_pct": u.get("sessionPercentage"),
        "session_resets_at": unix(u.get("sessionResetTime")),
        "weekly_pct": u.get("weeklyPercentage"),
        "weekly_opus_pct": u.get("opusWeeklyPercentage"),
        "weekly_resets_at": unix(u.get("weeklyResetTime")),
        "as_of": unix(u.get("lastUpdated")),
    }


_SNAPSHOT = None


def limits_snapshot() -> dict:
    """The collector projection selected for this one Claude invocation.

    Status, cost, and panel orchestration seed this before any historical
    accounting.  There is intentionally no hidden second collector/cache
    fallback here: source choice and account scope must remain visible and
    consistent across every derived percentage.
    """
    return _SNAPSHOT or {}


def seed_limits_snapshot(lim: Limits, reading: Optional[dict] = None) -> dict:
    """Install a selected v1 projection for local accounting only.

    ``reading`` contributes a non-secret identity used to scope calibration
    files.  It is never rendered or persisted verbatim.
    """
    global _SNAPSHOT
    if lim == NO_LIMITS:
        _SNAPSHOT = {}
        return _SNAPSHOT
    source = reading.get("source") if isinstance(reading, dict) else ""
    account = reading.get("account_name") if isinstance(reading, dict) else ""
    period = reading.get("period_start") if isinstance(reading, dict) else ""
    scope = "\0".join(str(value or "") for value in (source, account, period))
    # The percentages go in as NUMBERS, the form the old plan cache carried
    # and the one calibration compares against CALIB_MIN_PCT.  Limits carries
    # them as strings for the renderer, and seeding those verbatim made
    # `sp >= 2.0` a TypeError — caught by _with_shares' catch-all and drawn
    # as `?` in every share cell, on every render, with nothing on stderr.
    _SNAPSHOT = {"session_pct": _pct_num(lim.session_pct),
                 "session_resets_at": lim.session_reset,
                 "weekly_pct": _pct_num(lim.weekly_pct),
                 "weekly_resets_at": lim.weekly_reset,
                 "_scope": scope}
    return _SNAPSHOT


def calibration_cache_path(windows: str) -> str:
    """A private calibration cache keyed by source/account/period/windows."""
    if CALIB_CACHE_OVERRIDE:
        return os.path.expanduser(CALIB_CACHE_OVERRIDE)
    scope = limits_snapshot().get("_scope", "")
    key = hashlib.sha256((scope + "\0" + windows).encode("utf-8")).hexdigest()
    return os.path.join(state.state_dir(), "claude-calibration-" + key + ".json")


def _session_state_path(kind: str, session_id: str) -> str:
    """Private session state with no raw session id in its pathname."""
    digest = hashlib.sha256((kind + "\0" + session_id).encode("utf-8")).hexdigest()
    return os.path.join(state.state_dir(), "claude-" + kind + "-" + digest + ".json")


def _ctxwin_path(session_id: str) -> str:
    return _session_state_path("context", session_id)


def publish_ctx_window(session_id: str, win: int) -> None:
    """Leave the status line's window reading where the Stop hook can find it.

    The two readouts do not get the same facts.  The status-line payload
    carries context_window.context_window_size and a display name that says
    "(1M context)"; the Stop payload carries neither, and the transcript
    records the model as plain "claude-opus-5" for both variants.  So the one
    that knows writes it down for the one that cannot — the same shape as the
    plan cache, and for the same reason.

    It is keyed by a one-way session-id digest inside the application's
    mode-0700 state directory, so concurrent sessions remain isolated without
    leaking session identifiers into a shared temporary directory.

    Re-read before writing so an unchanged value costs no write.  This runs on
    every status render, which is to say constantly.
    """
    if not session_id or win <= 0:
        return
    p = _ctxwin_path(session_id)
    try:
        with open(p) as fh:
            if fh.read().strip() == str(win):
                return
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
        tmp = "%s.%d" % (p, os.getpid())
        with open(tmp, "w") as fh:
            fh.write("%d\n" % win)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except OSError:
        pass


def _rate_path(session_id: str) -> str:
    return _session_state_path("rate", session_id)


def session_rate(session_id: str, tokens: Optional[int],
                 now: Optional[float] = None) -> Optional[float]:
    """🛫 for the main thread: how fast 🧩's total is climbing, in tokens per
    second, or None while there is nothing to divide.

    The agent panel hands its rows sixteen samples of a token count, taken
    at a five-second tick, and the row takes the slope.  The status line is
    handed no such thing — every render sees one total and no history — so
    it keeps the history itself, in a file beside the published context
    window: a list of [epoch, tokens] pairs, appended to when the last is
    RATE_TICK_S or more old and cut to the last RATE_SAMPLES.  The rate is
    the rise over the run from the oldest sample to the newest, over the
    time between them — the timestamps recorded, not the tick assumed, since
    the status line is redrawn when the session changes and not on a timer,
    so the gap between two samples is at least the tick and often more.

    What it measures is what 🧩 counts: the billable-equivalent total of
    every request the session and its agents made, cache reads at their
    weight.  That climbs by a request's whole prompt at each request and
    rests while a tool runs, so like the panel's figure it is a reading of
    pace and of life rather than a generation rate; between turns it falls
    to zero and says so, which on this row is a fact and not a stall.

    None for the first tick of a session — one sample has no slope — and
    for a session with no id or no transcript, both of which are a row with
    nothing to sample.  Its path is a hashed id in private state, like the
    published context-window store.
    Any fault in the file — absent, truncated, not a list — starts the
    history over rather than propagating; the worst it costs is one blank
    tick.
    """
    if not session_id or tokens is None:
        return None
    t = float(now if now is not None else time.time())
    p = _rate_path(session_id)
    samples = []
    try:
        with open(p) as fh:
            raw = json.load(fh)
        if isinstance(raw, list):
            samples = [[float(a), float(b)] for a, b in raw]
    except (OSError, ValueError, TypeError):
        samples = []
    if not samples or t - samples[-1][0] >= RATE_TICK_S:
        samples.append([t, float(tokens)])
        samples = samples[-RATE_SAMPLES:]
        try:
            os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
            tmp = "%s.%d" % (p, os.getpid())
            with open(tmp, "w") as fh:
                json.dump(samples, fh)
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
        except OSError:
            pass
    if len(samples) < 2:
        return None
    span = samples[-1][0] - samples[0][0]
    if span <= 0:
        return None
    return max(0.0, samples[-1][1] - samples[0][1]) / span


def stored_ctx_window(session_id: str) -> int:
    """What the status line last published for this session, or 0."""
    if not session_id:
        return 0
    try:
        with open(_ctxwin_path(session_id)) as fh:
            v = int(fh.read().strip())
        return v if v > 0 else 0
    except (OSError, ValueError):
        return 0


def _with_shares(lim: Limits, transcript: str,
                 agents: Optional[Sequence[AgentRec]] = None
                 ) -> Tuple[Limits, CacheShares]:
    """Attach how much of each window this session, and its last turn, used.

    Returns the 📖 📝 shares of column 3 alongside -- the same turn's, and
    the session's -- off the same read, because they need exactly the turn
    this picked and reading the transcript a second time to find it again
    would be both slower and free to disagree.

    (The turn's wall-clock seconds came back here too until 2026-09-25, for
    ⌛'s first field.  That field is 🔧 now and reads off the transcript
    the status line has already summed, so nothing asks for it here.)
    Those need no plan reading and no calibration, only the transcript, so
    they are derived before the limits are looked at and a session with no
    usable window still gets its column; the limits' early return is
    below them, not above.

    The same derivation the cost line's totals row uses — session_shares over
    this transcript's turns, bounded by the window and divided by
    calibration's dollars-per-point — so the two readouts now report one
    quantity rather than two things with one name.

    WHAT THIS REPLACES, because the old figure looked plausible for months.
    There was no transcript here at all: the share was the plan-wide reading
    now minus the plan-wide reading this session first saw, stored per session
    id under TMPDIR.  A subtraction of two plan-wide readings contains every
    other session's consumption over the interval as well as this one's, and
    the baseline only ever moved DOWN — it was rewritten whenever the reading
    fell, on the correct theory that a fall means the window rolled over.

    Which makes it worthless the moment a session outlives a window, and the
    5-hour window rolls over every five hours.  At the rollover the reading
    goes to zero, the baseline follows it to zero, and nothing raises it
    again, so from then on `now - 0` IS the plan-wide total: both halves of
    the cell print the same number, and a session that has ever crossed a
    reset never reports a share again.  Measured 2026-08-25 on a four-day-old
    session: the status row said `62٪ / 62٪` and `6٪ / 6٪` while the cost row,
    counting the same session's own turns, said 16.2٪ and 1.57٪.  The 4.4
    weekly points between them were other sessions, charged here.

    What the subtraction alone could see and this cannot is usage from another
    machine — a phone, the web app — because the scan reads transcripts. That
    made it a true ceiling.  A ceiling that sits at 100٪ of the window for the
    rest of the session is not worth the column.

    Left as "" when there is no transcript to sum or no calibration to divide
    by, which render_limit draws as "?" rather than as a zero.

    BOUNDED BY THE WINDOW, both figures.  The 🎤 cell was `turn_cost(last)`
    over the unit, with no boundary on it at all, while 🎮 beside it was
    bounded — so a turn that straddled a reset was charged in full to a cell
    whose two neighbours had already dropped it, and column 4 printed
    `🎤 18٪  🎮 0٪  💳 1٪`: a part larger than the whole it belongs to, twice
    over.  Both now go through the split; see turn_cost_since.  What the
    reader gets is the one thing the column claims — turn ≤ session ≤ account
    — as an identity rather than as a coincidence that holds while no window
    happens to reset mid-answer.

    WHICH TURN the 🎤 figure is about is not turns[-1].  It is the last turn
    that made calls and was not a compaction — `prompts[-1]`, character for
    character the selection render_cost_line makes — so the 🎤 on this row and
    the 🎤 row of the cost line under it always describe the same turn.  Take
    turns[-1] instead and the two disagree whenever the last thing that
    happened was a compaction or a batch drained without billing.
    """
    if not transcript or not os.path.isfile(transcript):
        return lim, NO_CACHE_SHARES
    try:
        turns = read_turns(transcript, agents)
        prompts = [t for t in turns if t.calls and not t.compact
                   and not t.agent]
        last = prompts[-1] if prompts else None
        cache = NO_CACHE_SHARES
        if turns:
            cache = CacheShares(*(turn_shares(last) if last is not None
                                  else (None, None)),
                                *session_cache_shares(turns))
    except Exception:
        return lim, NO_CACHE_SHARES
    if not lim.session_pct and not lim.weekly_pct:
        return lim, cache
    try:
        calib = calibration()
        sh = session_shares(turns, calib)
        tn = {"sess": None, "week": None}
        if last is not None:
            tn = window_shares(last, calib)
    except Exception:
        return lim, cache
    return (lim._replace(session_share=_pct_str(sh["sess"]),
                         weekly_share=_pct_str(sh["week"]),
                         session_turn=_pct_str(tn["sess"]),
                         weekly_turn=_pct_str(tn["week"])),
            cache)


# ════════════════════════════════════════════════════════════════════════════
# Cost line.
#
# The per-prompt analogue of line 3, emitted once per turn by the Stop hook.
# Same glyphs, same gaps, same humanize, same billing weights, same cache
# tiering.  The session-cumulative segments are re-scoped to the last prompt,
# and 🧠 is re-scoped further: the status line reads context as a level, this
# reads it as the CHANGE in that level over one turn, which a cumulative row
# cannot show.
# ════════════════════════════════════════════════════════════════════════════

def turn_cost(t: Turn) -> float:
    """List-price cost of one turn: the four sums read_turns priced per
    record, at each record's own model.  Not the token sums times one
    model's rates — a Sonnet fork inside an Opus turn is billed at Sonnet
    rates, and pricing the sums could not say so."""
    return t.usd_in + t.usd_out + t.usd_cr + t.usd_cw


def turn_cost_since(t: Turn, start: Optional[datetime]) -> float:
    """The part of one turn's cost that was billed at or after `start`.

    A turn is not an instant.  This one ran 56 calls over five minutes and a
    plan window opened in the middle of it, and until 2026-09-03 every reader
    here charged the whole turn to whichever window its PROMPT was typed in —
    `Turn.ts`, which is when the user pressed return and not when any of the
    money was spent.  Measured on the turn that exposed it: prompt at
    14:57:32, window open at 15:00:00, $1.02 billed across 13 calls before the
    reset and $3.85 across 43 calls after it.  All $4.87 went to the window
    that had closed, and the status row reported this session's share of the
    live one as 0٪ — under a 🎤 cell reporting the same turn at 18٪, because
    that cell had no window bound on it at all.  A column whose three fields
    are the same window read at three scopes printed turn > session > account,
    which is not a rounding error but an ordering that cannot happen.

    The machine-wide scan had it right the whole time and is worth reading
    beside this: _window_costs filters INDIVIDUAL assistant records by their
    own stamps.  The per-session tally was the only place a turn was still
    atomic, so calibration's denominator was split at the boundary and the
    numerator divided into it was not.

    A stamp that will not parse counts IN, which is _window_costs' rule and
    session_shares' before it: both windows end at now, so the likelier of the
    two errors is to drop a call that belongs.

    Falls back to the old whole-turn test when there are no parts to split.
    That is a COMPACTION and only a compaction — it bills through no usage
    record, so its cost comes off the boundary metadata and there is nothing
    stamped to divide.  `t.compact` is tested rather than `not t.parts` alone
    because a /compact prompt can carry both its own calls and the boundary,
    and splitting on the calls would then charge the window a fraction of a
    figure the calls never accounted for.
    """
    if start is None:
        return turn_cost(t)
    edge = start.timestamp()
    if t.compact or not t.parts:
        ts = _local_naive(t.ts)
        return turn_cost(t) if ts is None or ts >= start else 0.0
    return sum(c for e, c in t.parts if e is None or e >= edge)


def window_shares(t: Turn, calib: Dict[str, Optional[float]]
                  ) -> Dict[str, Optional[float]]:
    """One turn's share of each live window, counting only what it billed in.

    The per-prompt half of what session_shares does for the whole session, on
    the same boundaries and the same split, so the 🎤 figure is a part of the
    🎮 figure beneath it by construction rather than by coincidence.  Both
    read _window_starts, which reads limits_snapshot, which is memoised for
    the life of the render — so the two cells cannot end up bounded by
    different moments, which is the failure limits_snapshot exists to stop.
    """
    starts = dict(zip(("sess", "week"), _window_starts()))
    out = {"sess": None, "week": None}
    for key, start in starts.items():
        unit = calib.get(key)
        if unit:
            out[key] = turn_cost_since(t, start) / unit
    return out


def turn_shares(t: Turn) -> Tuple[Optional[int], Optional[int]]:
    """What fraction of one prompt's cost went on re-reading, and on caching.

    The two components of a turn's bill that are ABOUT THE CONTEXT rather than
    about the answer: cache_read, which is the conversation so far being sent
    again, and cache_creation, which is this turn's own new material being
    put where the next request can read it.  Output is the remainder and is
    deliberately not reported -- it is the one part of the bill no amount of
    /compact or /clear can reclaim, so a reading of it would not inform the
    decision these two are here for.

    WHOLE PERCENT, because the field is 💳's three columns and because these
    are ratios to act on rather than figures to add up.  Rounded, not floored:
    nothing sums to them, so the truncation cost_totals_group's note argues
    against has no equivalent here, and half a point of bias in a number read
    as "roughly a third" is worse than the rounding.

    (None, None) for a turn with no cost to take a share OF.  That is a
    compaction, which issues no request of its own -- the same case ctx
    handles by walking back to the last turn that HAS a reading.  Here there
    is nothing to walk back to that would be true of this turn, so the cell
    goes blank rather than borrowing its neighbour's answer.
    """
    c = turn_cost(t)
    if c <= 0:
        return None, None
    return (int(round(100 * t.usd_cr / c)),
            int(round(100 * t.usd_cw / c)))


def session_cache_shares(turns: Sequence[Turn]
                         ) -> Tuple[Optional[int], Optional[int]]:
    """turn_shares over the whole session: 📖 and 📝 as shares of every
    dollar the session has spent, for the status line's 🎮 fields.

    Summed BEFORE dividing, not an average of the per-turn shares, for the
    reason cost_totals_group recomputes the cache rate that way: an average
    would weight a hundred-token turn like a hundred-thousand-token one, and
    the question this answers -- of what this sitting has cost, how much was
    the transcript charging for still being there -- is a question about
    dollars, not about turns.  Every turn, compactions and the late-agents
    row included, because the denominator is the same sum the cost line's
    totals row prints beside 💰, and a share of a figure the reader can see
    should be a share of exactly that figure.  Not bounded by any window:
    the plan windows are column 4's business, and this column is about the
    session's own bill, however old the session is.
    """
    c = sum(turn_cost(t) for t in turns)
    if c <= 0:
        return None, None
    return (int(round(100 * sum(t.usd_cr for t in turns) / c)),
            int(round(100 * sum(t.usd_cw for t in turns) / c)))


def window_for(turns: Sequence[Turn], session_id: str = "") -> int:
    """The context window in force: what the status line published, else a guess.

    The published figure is Claude Code's own context_window_size, taken from
    the status-line payload — the number the thing enforcing the window is
    using.  It wins outright rather than being reconciled against the guess
    below.  It is refreshed on every status render, so it is at worst seconds
    old, where the guess can be wrong for the whole session.

    THE GUESS, for a session no status line has rendered: the largest reading
    seen.  Not the model name, which the transcript records as plain
    "claude-opus-5" whether or not this is the 1M variant.  A reading above
    200k is proof of the larger window, since the smaller could not have held
    it.

    Its failure mode was called self-correcting, and the correction never came
    in the session that exposed it: a 1M session that has not yet passed 200k
    reads as 200k, so every 🧠 figure runs 5x high — and COMPACTING is what
    keeps it under the line.  This session compacted twice, at 176k and 157k,
    and read 51.3٪ where the truth was 10.3٪.  The habit that keeps a session
    healthy is the one that stops the window ever being proved.  Hence the
    published figure: the guess erring toward a SMALL window is the better of
    two wrong answers, not an acceptable one.
    """
    published = stored_ctx_window(session_id)
    if published:
        return published
    biggest = max((t.ctx for t in turns), default=0)
    return CTX_1M if biggest > CTX_DEF else CTX_DEF




def _local_naive(ts: str) -> Optional[datetime]:
    """A transcript's UTC "…Z" stamp as a naive LOCAL datetime.

    The window boundaries arrive from the plan cache as naive local times, so
    both sides of every comparison have to be in that one frame.  Shared by
    the machine-wide scan and by the per-session tally, which have to agree
    about which turns fall inside a window or the two halves of a limit cell
    are measuring different spans.
    """
    try:
        base = ts.split(".")[0].rstrip("Z")
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=_UTC).astimezone().replace(tzinfo=None)
    except Exception:
        return None


def _window_starts() -> Tuple[Optional[datetime], Optional[datetime]]:
    """When the 5-hour and the weekly window opened, or None for either.

    Derived by subtracting each window's length from the reset time the plan
    cache publishes, which is the only end of it that is stated.

    Off limits_snapshot, not off its own read of the source.  A boundary taken
    from one snapshot while the percentage after the "/" comes from another is
    how five hours of turns were once charged to a window that had not opened
    when they ran.
    """
    lim = limits_snapshot()

    def start(key, delta):
        v = lim.get(key)
        if not v:
            return None
        try:
            return datetime.strptime(v, STAMP_FMT) - delta
        except Exception:
            return None

    return (start("session_resets_at", timedelta(hours=5)),
            start("weekly_resets_at", timedelta(days=7)))


def _window_costs(sess_start: Optional[datetime],
                  week_start: Optional[datetime]) -> Tuple[float, float]:
    """Total spend on this machine since each window opened.

    Bounded by FILE MTIME, which the bash and the old Python were not.  The
    scan reads every assistant record in every project's every transcript, and
    json.loads dominates: at roughly ten times the current corpus it crosses
    the Stop hook's timeout and the row simply vanishes with no diagnosis.
    Nothing older than the weekly window can contribute to either figure, so
    skipping those files bounds the work by WINDOW LENGTH instead of by
    history, which does not grow.

    A slack day is allowed either side of the boundary because mtime is when
    the file was last appended to, not when its earliest qualifying record was
    written.

    The agent files are in the scan — `<sid>/subagents/**/agent-*.jsonl`
    beside each transcript, see agent_records — and the reason is the
    division this feeds.  The unit is machine spend over the plan reading,
    and the reading is Anthropic's count, which includes every agent.  A
    numerator without them was short by the agent share of the window, so
    the unit was small and every share divided by it was high, by a factor
    that changed with which sessions had been running forks.  Measured
    2026-09-11 with the eight-day cutoff: 42 agent files admitted of 2,134,
    0.49 s on top of the main files' 2.34 s.
    """
    sess = week = 0.0
    seen = set()
    cutoff = None
    if week_start is not None:
        cutoff = (week_start - timedelta(days=1)).timestamp()
    files = (glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
             + glob.glob(os.path.join(PROJECTS_DIR, "*", "*", "subagents",
                                      "**", "agent-*.jsonl"), recursive=True))
    for fp in files:
        if cutoff is not None:
            try:
                if os.path.getmtime(fp) < cutoff:
                    continue
            except OSError:
                continue
        for r in _records(fp):
            if r.get("type") != "assistant":
                continue
            u = (r.get("message") or {}).get("usage")
            ts = r.get("timestamp")
            if not u or not ts:
                continue
            k = r.get("requestId") or (r.get("message") or {}).get("id")
            if k in seen:
                continue
            seen.add(k)
            t = _local_naive(ts)
            if t is None:
                continue
            if week_start and t < week_start:
                continue
            pi, po, pr, pw = _price((r.get("message") or {}).get("model"))
            c = (u.get("input_tokens", 0) * pi + u.get("output_tokens", 0) * po
                 + u.get("cache_read_input_tokens", 0) * pr
                 + u.get("cache_creation_input_tokens", 0) * pw)
            week += c
            if sess_start and t >= sess_start:
                sess += c
    return sess, week


def calibration() -> Dict[str, Optional[float]]:
    """Dollars per one percent of each plan window.

    The plist exposes only aggregate percentages, never a per-prompt or
    per-token-class breakdown, so this is DERIVED:

        $/1%          = (cost of everything in the window) / (percent consumed)
        prompt share  = prompt cost / $/1%

    The percentage is the one limits_snapshot publishes — the same reading
    plan_totals prints after the "/" and _window_starts bounds the sum with,
    so all three describe one moment.  Letting them differ would put the two
    🔋 cells of one readout on different scales, which is the same
    disagreement as plan_totals', one row apart — and it happened, by way of
    the DISK cache below: the ratio was stored, so a unit another session had
    derived from a live reading was divided into a share bounded by a stale
    one.

    WHAT IS CACHED IS THE SCAN, NOT THE RATIO, and since 2026-09-03 the
    READING THE SCAN WAS TAKEN WITH goes to disk beside it.  The expensive
    half is _window_costs, which walks transcripts — 1.3 s here, far too slow
    for a status line that redraws as you type; the percentages are free.  So
    the costs go to disk keyed by the WINDOWS they were measured over, the
    reading of that same instant goes with them, and the division happens
    fresh on every call — against that pair, not against a live reading.  A
    rate cannot be estimated from a numerator and a denominator taken minutes
    apart, and at a reset the minutes between them are the whole window: see
    the note at the cache read below for what that printed.

    The unit still cannot disagree with the figure beside it, the scan is
    still paid for at most once per CALIB_TTL, and the cache is still
    invalidated by the only event that actually invalidates it — a reset,
    which moves a boundary.

    NOT DERIVED AT ALL below CALIB_MIN_PCT.  A percentage quantised to whole
    numbers is not a divisor at 1; the shares that would come out of it are
    uncertain by half of themselves, and "?" is what the row has always
    printed for a figure it does not have.

    Self-calibrating — it re-derives from live data each time rather than
    carrying a constant that silently goes stale.  Two honest caveats: it
    assumes limit consumption is proportional to list-price cost (unverified —
    the real weighting is unpublished), and it can only see transcripts on this
    machine.  The second one used to be written down backwards.  Usage from
    elsewhere raises the PERCENTAGE without raising the cost this scan can
    see, so it DEFLATES $/1% and therefore OVERSTATES every share divided by
    it: $14 spent here against a 1٪ reading gives $14 a point, but if a phone
    consumed as much again the reading is 2٪, the unit falls to $7, and the
    same $14 session reads 2٪ when its true share is 1٪.

    Written via a temp file and os.replace: the path is shared by every
    session on the machine, and two hooks finishing together were previously
    able to interleave a write.
    """
    snap = limits_snapshot()
    ss, ws = _window_starts()
    out = {"sess": None, "week": None}
    sp, wp = snap.get("session_pct"), snap.get("weekly_pct")
    cached = _read_calib_cache("%s|%s" % (ss, ws))
    if cached is not None and "windows" not in cached:
        # A planted fixture, which states the two UNITS directly and holds
        # them still.  The goldens need that: the real form is keyed by
        # window boundaries the payloads move on every case, so a fixture in
        # the real form would miss on all thirteen and send the suite off to
        # scan this machine's transcripts.  See tests/pin-env.sh.
        return {"sess": cached.get("sess"), "week": cached.get("week")}
    if cached is not None:
        # BOTH HALVES OFF THE CACHE, which is the 2026-09-03 change and the
        # whole of it.  The scan was cached and the reading was taken live, so
        # a numerator measured five minutes ago was divided by a denominator
        # measured now — and a rate estimated across two moments is only as
        # good as the assumption that nothing moved between them.  At a
        # RESET everything moves: the scan is written seconds into the new
        # window holding seconds of spending, the reading climbs while it
        # sits there, and the unit comes out far too small.  Every share
        # divided by it is then far too large, which is how 🎤 came to print
        # 18٪ of a window whose own account total read 1٪ — a part three
        # times the whole it belongs to.  Same instant on both sides and that
        # cannot happen: this session's transcripts are IN the scan, so its
        # cost is at most sc, so its share is at most sp.
        #
        # This does not contradict the note above about caching the scan and
        # not the ratio.  What must not be cached is the ratio's ANSWER,
        # because a share bounded by one window divided by a unit derived
        # under another is the failure the window key exists to stop.  The
        # two measurements that go INTO it have to be simultaneous, and the
        # window key still holds them to this window.
        sc, wc = cached.get("sess_cost"), cached.get("week_cost")
        sp, wp = cached.get("sess_pct"), cached.get("week_pct")
    elif ss is None and ws is None:
        return out
    else:
        sc, wc = _window_costs(ss, ws)
        _write_calib_cache("%s|%s" % (ss, ws), sc, wc, sp, wp)
    # See CALIB_MIN_PCT: below it the reading's own quantisation is worth
    # more than the figure, and "?" is the honest reading of a scale that
    # cannot be drawn yet.
    # Through _pct_num whichever branch supplied them: a cache entry written
    # while the snapshot still carried strings would otherwise poison every
    # render for CALIB_TTL after the fix that stopped writing them.
    sp, wp = _pct_num(sp), _pct_num(wp)
    if sp and sp >= CALIB_MIN_PCT and sc is not None:
        out["sess"] = sc / sp
    if wp and wp >= CALIB_MIN_PCT and wc is not None:
        out["week"] = wc / wp
    return out


def _read_calib_cache(windows: str) -> Optional[dict]:
    """The cached scan, if it is fresh AND measured over these windows.

    A dict with no "windows" key is a planted fixture and is returned as-is
    for the caller to read as units; anything else has to match, because a
    scan bounded by yesterday's boundary is not an answer about today's.
    """
    path = calibration_cache_path(windows)
    try:
        if os.path.getmtime(path) <= time.time() - CALIB_TTL:
            return None
        with open(path) as fh:
            d = json.load(fh)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    if "windows" not in d:
        return d
    if d.get("windows") != windows:
        return None
    # An entry written before 2026-09-03 carries no reading to pair the scan
    # with, and pairing it with a live one is the bug this key was added to
    # fix.  Treated as a miss, which costs one rescan on the first render
    # after an upgrade and nothing after that.
    return d if "sess_pct" in d else None


def _write_calib_cache(windows: str, sc: float, wc: float,
                       sp: Optional[float], wp: Optional[float]) -> None:
    """The scan, and the two readings it was SIMULTANEOUS with.

    The readings are stored because the division happens later — possibly in
    another process, up to CALIB_TTL after this — and a rate is only estimable
    from a cost and a percentage measured at one moment.  See calibration.
    """
    path = calibration_cache_path(windows)
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, mode=0o700, exist_ok=True)
        tmp = "%s.%d" % (path, os.getpid())
        with open(tmp, "w") as fh:
            json.dump({"windows": windows, "sess_cost": sc, "week_cost": wc,
                       "sess_pct": sp, "week_pct": wp}, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        pass


def plan_totals() -> Dict[str, Optional[float]]:
    """The selected collector projection as numeric cost-grid totals."""
    lim = limits_snapshot()
    sp, wp = _pct_num(lim.get("session_pct")), _pct_num(lim.get("weekly_pct"))
    if sp is None or wp is None:
        return {}
    return {"sess": sp, "week": wp}

def share_half(emoji: str, share: Optional[int], ink: Ink) -> str:
    """The fmt.C_LIM_TOT half of a PER-PROMPT limit cell, under limit_cell's.

    Same shape as the half it stacks on -- a leading blank, the mark, fmt.MARK_SP,
    and one whole-percent reading in three columns -- so the two figures land
    in one column and the row can be read downward.  It is the blank the
    per-prompt row used to pad with, now spent on a reading; the width is
    unchanged, which is the point.  fmt.MARK_SP is read HERE and not captured,
    because --no-mark-spacing rebinds it after import and this cell has to
    close with the rest of them.

    A missing share still returns the full seven columns.  seg() pads the cost
    row on the LEFT, so a short cell does not leave a gap at its end: it
    shoves the whole cell right, off the column it has to stack on.  That is
    the same miscount fmt.C_LIM_TOT's note warns about, one row up.
    """
    if share is None:
        return " " * fmt.C_LIM_TOT
    return " %s%s%s%s%s" % (emoji, fmt.MARK_SP, ink.amb, pad_val(3, pct(share)),
                            ink.r)


def cost_group(t: Turn, calib: Dict[str, Optional[float]], win: int, ink: Ink,
               now: Optional[float] = None, acct: bool = True,
               stamps: bool = True) -> str:
    """The constant-width segment group for one prompt.

    Every value is padded to its field width HERE rather than by seg(), so the
    emoji column is fixed too.  Padding the segment as a whole would hold each
    value's right edge but let its icon drift left and right as the value grew
    — which reads as a font problem rather than a layout one, and sends you
    looking in the wrong place.
    """
    # NOT floored.  See cost_totals_group for why the truncation that used to
    # live here is gone from both paths rather than from one of them.
    up = t.fresh + W_CACHE_WRITE * t.cache_write + W_CACHE_READ * t.cache_read
    in_all = t.fresh + t.cache_write + t.cache_read
    cpct = int(100 * t.cache_read / in_all) if in_all else -1
    c = turn_cost(t)
    rd, wr = turn_shares(t)
    # 🔋 and 🪫 below report this prompt's share of each PLAN WINDOW, so what
    # they divide is the part of it billed inside that window — not `c`, which
    # is the whole turn and is what 💰 to their left is for.  The two differ
    # only for a turn that straddles a reset, and for that turn the difference
    # is the whole figure: see turn_cost_since.  The totals row underneath
    # sums the same split over every turn, which is what lets these deltas
    # total the figure beneath them across a reset as well as within one.
    tsh = window_shares(t, calib)
    stamp = time.localtime(now) if now is not None else time.localtime()
    lim_w = fmt.C_SESS if acct else fmt.C_SESS - fmt.C_LIM_TOT
    cells = [
        seg(fmt.C_TOK, "%s%s%s%s%s%s" % (
            E_TOK + fmt.MARK_SP, ink.tup, E_UP + pad_val(4, humanize(up)),
            ink.tdn, " " + E_DOWN + pad_val(4, humanize(t.out)), ink.r),
            left=False),
        seg(fmt.C_CACHE, "%s%s%s%s" % (E_CACHE + fmt.MARK_SP, _cache_ink(cpct, ink),
                                   pad_val(3, pct(cpct)), ink.r)
            if cpct >= 0 else "", left=False),
        # Percentage then size, matching render_ctx — and the totals row
        # below repeats the order, because these two rows stack field under
        # field and a swap in one alone would tear that apart.
        seg(C_CTX, "%s%s%s %s%s%s" % (
            E_CTX, ink.pnk2, signed_pct(t.dctx, win),
            ink.pnk, signed(t.dctx), ink.r)
            if t.dctx is not None else "", left=False),
        # "+", not a sign: a prompt cannot cost less than nothing, so there
        # is no negative case to distinguish and the mark is free to mean
        # "added" — the same constant, in the same column, as the two limit
        # cells after it.  Every figure on this row is what ONE prompt put on
        # the reading directly beneath it.
        seg(C_COST, "%s%s+%s%s" % (E_COST, ink.yel,
                                   money_cell(c), ink.r),
            left=False),
        # The second half of each cell is the fmt.C_LIM_TOT the row below spends
        # on 💳 and the window's own reading.  It was seven blanks until
        # 2026-09-03 — reserved so the emoji above lands over the emoji below,
        # and otherwise wasted.  It now carries where THIS prompt's money
        # went: 📖 the part spent re-reading the conversation, 📝 the part
        # spent caching what this turn added.  See turn_shares for why those
        # two and not a third, and E_READ for why they are shares of the turn
        # rather than of the window whose glyph opens the cell.
        #
        # The reservation is unchanged either way, and it must be: seg() pads
        # the cost row on the LEFT, so a cell narrower than the one below it
        # is not a gap at the end of a row but a whole cell pushed right, off
        # the column it has to stack on.  With --no-account-totals there is no
        # 💳 half below to stack ON, so the halves go together — which is why
        # share_half is reached through the same `acct` test the blank was.
        seg(lim_w, "%s%s+%s%s%s" % (
            E_SESS, ink.amb,
            dec_align(plan_pct(tsh["sess"]), 2, 2, E_PCT), ink.r,
            share_half(E_READ, rd, ink) if acct else "")
            if tsh.get("sess") is not None else "", left=False),
        seg(lim_w, "%s%s+%s%s%s" % (
            E_WEEK, ink.amb,
            dec_align(plan_pct(tsh["week"]), 2, 2, E_PCT), ink.r,
            share_half(E_WRITE, wr, ink) if acct else "")
            if tsh.get("week") is not None else "", left=False),
        # "+" as on 💰, 🔋 and 📆 beside it: every figure on this row is what
        # ONE prompt added to the reading directly beneath it, and this one is
        # the time it took.  The totals row prints a space in the column.
        # Blank on the agents row: that row is not an answer, and the
        # agents ran in parallel with answers already timed on their own
        # rows, so "+0s" would be wrong and any other figure double-counted.
        seg(C_ELAPSED, "%s%s+%s%s" % (S_WORK, ink.crm,
                                      pad_val(4, dur_fmt(t.dur_s)), ink.r)
            if not t.agent else "", left=False),
        # Blank on a compaction, and the CELL is kept so the columns to its
        # left still stack.  The stamp is `now` — when this line is being
        # drawn — which is honest for the prompt just answered and a lie for
        # a compaction, which happened at some earlier point in the session
        # and is only being reported now because `/compact` fires no Stop of
        # its own.  Printing the moment of the REPORT beside the cost of the
        # EVENT invites reading one as the other.  The agents row is the
        # same case, word for word.
        seg(C_STAMP, "%s%s%s%s" % (
            S_DATE, ink.crm,
            pad_val(10, time.strftime("%Y-%m-%d", stamp)), ink.r)
            if not (t.compact or t.agent) else "", left=False),
    ]
    # Dropped, not blanked.  An empty seg() is still exactly its reservation,
    # so blanking would leave thirteen columns of nothing at the right edge
    # and buy the narrow window none of the room the option is asked for.
    if not stamps:
        cells.pop()
    return (" " * C_SEG_GAP).join(cells)


def _cache_ink(p: int, ink: Ink) -> str:
    if p <= CACHE_CRIT:
        return ink.red
    if p <= CACHE_WARN:
        return ink.amb
    return ink.grn


def session_shares(turns: Sequence[Turn],
                   calib: Dict[str, Optional[float]]
                   ) -> Dict[str, Optional[float]]:
    """What THIS session put into each plan window, as a percentage of it.

    Both readouts, since 2026-08-25.  The status line derived its own version
    by subtracting plan-wide readings, which counted every other session's
    consumption as this one's and collapsed onto the plan-wide total the
    moment a window reset under a live session — see _with_shares for what
    that looked like on screen.  One derivation, two rows.

    The totals row's 🔋 and 🪫 were the plan-wide readings — every session on
    this machine, plus anything run off it — printed under a label that says
    "Session".  They were the only two cells on the row that did not total
    the column above them, and nothing in the row said so.  Now they do total
    it, and the plan-wide figure moves to the far side of a "/", which is the
    arrangement the status line already uses for this same pair.

    Bounded by the WINDOW, not by the session.  A session outliving its
    5-hour window still holds turns that reset with it, and charging those to
    the current window would report a share the window never saw.  That is
    the ordinary case rather than the corner: the session this was written in
    was nine hours old against a five-hour window.

    Same derivation as the per-prompt cell directly above — cost over dollars
    per one percent — so the deltas on that row now sum to the figure beneath
    them, which is what the column claims and could not previously deliver.

    Each turn is SPLIT at the boundary rather than tested against it.  It used
    to be tested — `_local_naive(t.ts) >= start`, on the stamp of the prompt —
    and a turn that straddles a reset then went wholly to the window it was
    typed in, which by then was the window that had closed.  See
    turn_cost_since for the measurement; the short version is that a five
    minute turn put $3.85 into the live 5-hour window and this function
    reported 0.  A turn whose stamp will not parse is still counted IN, for
    the reason it always was: both windows end at now, so the likelier of the
    two errors is to drop spending that belongs.
    """
    out = {"sess": None, "week": None}
    if not calib:
        return out
    starts = dict(zip(("sess", "week"), _window_starts()))
    for key, start in starts.items():
        unit = calib.get(key)
        if not unit or start is None:
            continue
        out[key] = sum(turn_cost_since(t, start) for t in turns) / unit
    return out


def limit_cell(emoji: str, share: Optional[float], total: Optional[float],
               ink: Ink, acct: bool = True) -> str:
    """A totals-row limit cell: this session's share, then 💳, the window's.

    Two figures about one window — before the mark, what this session spent;
    after it, what the window has consumed altogether — and the mark between
    them is the status line's, because the figure it introduces is the status
    line's.  💳 sits beside that same reading in column 4, so a reader moving
    between the readouts meets one glyph for one quantity.

    It was a spaced slash until 2026-08-27, and the note here claimed the
    slash as "the status line's idiom for exactly this pair".  That was never
    true: column 4 divides its four fields with marks and has no slash on it
    anywhere.  What the two readouts genuinely shared was the PAIR, and a
    slash is the one divider that says nothing about which half is which — it
    reads as "out of", which is wrong twice over here, since the share is a
    percentage of the same window and not a part of the total beside it.
    💳 names the second figure instead of merely separating it.

    render_diff dropped its own slash on the same argument and is worth
    reading beside this: "the signs already say which half is which, so the
    slash was a column spent repeating them".  Here the mark does not merely
    avoid repeating something — it says the one thing the cell could not
    otherwise say, which of the two windows-worth of spending is the account's.

    The two halves are formatted differently on purpose.  The share keeps
    plan_pct's decimals because it has to stack under the per-prompt delta
    above it, and dec_align holds its point in a fixed column; the total is
    whole percent, because it is context for the share rather than a figure
    to act on, and because its source quantises to whole points anyway.

    The mark takes fmt.MARK_SP after it, exactly as the three scope marks do on
    the status line, so --no-mark-spacing closes this blank with those and the
    cell comes back to the six columns the slash form spent.

    The cost of holding that decimal column is that the gap BEFORE the mark
    floats: a share with no fraction leaves up to three further blanks there.
    Worth it — the point column is the one this row is read down, and the
    total after 💳 still lands in a fixed column either way.

    💯 stands in for a full window here exactly as it does on the status
    line's 💳 field, and that is not decoration.  This total and that field
    are THE SAME READING from the same source, so before it the two readouts
    disagreed at the one moment either of them matters: the status line drew
    💯 and this row printed "99٪" — not a rounding but pct's clamp, which is
    to say a figure that was never true.  A three-column field cannot hold
    "100٪", so the glyph is what makes the honest reading fit, in both places,
    in the same three columns.  With 💳 ahead of it the pair now renders as
    the status line's own 💳 💯٪ -- the unit included, because the glyph
    replaces the FIGURE and not the unit after it, and a column read downward
    should not lose its unit at the one reading that matters.  "💯٪" is three
    columns, which is what " 💯" was.
    """
    if share is None and (total is None or not acct):
        return ""
    left = (dec_align(plan_pct(share), 2, 2, E_PCT) if share is not None
            else pad_val(fmt.C_SESS - fmt.C_LIM_TOT - 3, "?"))
    if not acct:
        return "%s%s %s%s" % (emoji, ink.amb, left, ink.r)
    # The threshold is render_limit's, so the two readouts can never draw
    # different things for one window: 99.5 up is full, and 💯 says so.
    if total is None:
        right = "?"
    elif total >= 99.5:
        right = E_HUNDRED + E_PCT
    else:
        right = pct(round(total))
    return "%s%s %s%s %s%s%s%s%s" % (emoji, ink.amb, left, ink.r,
                                     E_ACCT, fmt.MARK_SP,
                                     ink.amb, pad_val(3, right), ink.r)


def cost_totals_group(turns: Sequence[Turn], totals: Dict[str, Optional[float]],
                      win: int, ink: Ink, now: Optional[float] = None,
                      calib: Optional[Dict[str, Optional[float]]] = None,
                      acct: bool = True, stamps: bool = True) -> str:
    """The session-to-date row that sits under the per-prompt one.

    Same segment order and the same widths, so each total lands directly
    beneath the figure it totals.  Two of the seven have no meaningful total:

      🧠  not a delta but the absolute reading the deltas have summed to.
      🕐  blank.  A clock has no total, and an elapsed figure would be a
          different metric wearing the same icon.

    🔋📆 carry two figures each and are the reason this note changed.  They
    used to carry only the windows' plan-wide consumption, which is a total
    of every session on the machine rather than of the column above it — the
    one place this row printed something other than what its label promised.
    The session's own share now leads the cell and the plan-wide reading
    follows a "/", so the column sums and the wider context survives.  See
    session_shares and limit_cell.

    The cache rate is recomputed over every request rather than averaged over
    the per-prompt rates, which would weight a hundred-token turn like a
    hundred-thousand-token one.

    The weighted ▴ figure is never truncated, here or in the per-prompt row.
    The implementation this replaces floored it once per turn and then summed,
    so the total drifted below a true tally by up to a token per turn without
    bound — 7 tokens over a 14-turn transcript, measured.  That is invisible at
    humanize()'s three significant digits, which is how it survived.

    Flooring only the total would have been worse than leaving it: the
    per-prompt rows would then no longer sum to the row beneath them, which is
    a more confusing kind of wrong than being seven tokens light.  So the
    truncation is gone from BOTH paths rather than fixed in one.  It bought
    nothing in the first place — the value is weighted by 2.0 and 0.1, so it is
    fractional by construction, and humanize() formats it to three significant
    digits whether or not it arrives whole.
    """
    up = sum(t.fresh + W_CACHE_WRITE * t.cache_write
             + W_CACHE_READ * t.cache_read for t in turns)
    out_tok = sum(t.out for t in turns)
    cr = sum(t.cache_read for t in turns)
    in_all = sum(t.fresh + t.cache_write + t.cache_read for t in turns)
    cpct = int(100 * cr / in_all) if in_all else -1
    # The last turn that HAS a reading, not simply the last turn.  A
    # compaction has none — it issues no request whose usage could be counted
    # — and reading straight off the end blanked this cell for the one row
    # printed immediately after a compaction, which is where the absolute
    # figure is most worth having.
    ctx = next((t.ctx for t in reversed(turns) if t.ctx), 0)
    c = sum(turn_cost(t) for t in turns)
    # Source/calibration preparation belongs to orchestration.  This group is
    # also injected into the pure cost renderer, so it must never trigger a
    # cache refresh merely because a direct caller omitted an optional value.
    calib = calib if isinstance(calib, dict) else {"sess": None, "week": None}
    mine = session_shares(turns, calib)
    stamp = time.localtime(now) if now is not None else time.localtime()
    # Every turn's answering time, summed — the total of the figure directly
    # above it, which is what every other cell on this row is.  It is NOT the
    # session's age: an age counts the hours the session sat waiting for
    # someone to type, and no per-prompt row can add up to that.  The status
    # line is where the age belongs, and it has it, next to this same total
    # and to the difference between them.
    work_s = sum(t.dur_s for t in turns)
    lim_w = fmt.C_SESS if acct else fmt.C_SESS - fmt.C_LIM_TOT
    cells = [
        seg(fmt.C_TOK, "%s%s%s%s%s%s" % (
            E_TOK + fmt.MARK_SP, ink.tup, E_UP + pad_val(4, humanize(up)),
            ink.tdn, " " + E_DOWN + pad_val(4, humanize(out_tok)), ink.r),
            left=False),
        seg(fmt.C_CACHE, "%s%s%s%s" % (E_CACHE + fmt.MARK_SP, _cache_ink(cpct, ink),
                                   pad_val(3, pct(cpct)), ink.r)
            if cpct >= 0 else "", left=False),
        # A space where the per-prompt row prints its sign, then the same
        # dec_align — so the two readings stack digit under digit and the
        # column reads as one figure changing rather than two figures.  This
        # is what 💰, 🔋 and 📆 do further along the row.
        seg(C_CTX, "%s%s %s %s %s%s" % (
            E_CTX, ink.pnk2,
            dec_align("%.1f" % (100.0 * ctx / win), 2, 1, E_PCT),
            ink.pnk, pad_val(4, humanize(ctx)), ink.r)
            if ctx else "", left=False),
        seg(C_COST, "%s%s %s%s" % (E_COST, ink.yel,
                                   money_cell(c), ink.r),
            left=False),
        seg(lim_w, limit_cell(E_SESS, mine.get("sess"),
                              totals.get("sess") if totals else None, ink,
                              acct),
            left=False),
        seg(lim_w, limit_cell(E_WEEK, mine.get("week"),
                              totals.get("week") if totals else None, ink,
                              acct),
            left=False),
        # The pair the status line's column 4 makes, split across the two
        # rows this readout already has: what the last prompt took, over how
        # long the session has been alive.  And the stamp beside it splits the
        # same way — the date on the row above the clock it belongs to, which
        # is what a line printed at 00:03 needs and a bare clock cannot give.
        seg(C_ELAPSED, "%s%s %s%s" % (S_WORK, ink.crm,
                                      pad_val(4, dur_fmt(work_s)), ink.r),
            left=False),
        seg(C_STAMP, "%s%s%s%s" % (
            S_TIME, ink.crm,
            pad_val(10, time.strftime("%H:%M:%S", stamp)), ink.r), left=False),
    ]
    if not stamps:            # dropped rather than blanked; see cost_group
        cells.pop()
    return (" " * C_SEG_GAP).join(cells)


def render_cost_line(turns: Sequence[Turn], opts: CostOpts,
                     now: Optional[float] = None) -> str:
    """Prepare accounting once, then delegate byte layout to the pure renderer."""
    return _pure_cost_render(turns, opts, window_for(turns, opts.session_id),
                             calibration(), plan_totals(), now,
                             cost_group, cost_totals_group)


# ════════════════════════════════════════════════════════════════════════════
# Alignment self-test.
#
# Answers "are the width tables right for this terminal?" in one glance,
# without a live session and without counting columns by eye.
#
# It renders representative rows from synthetic data, draws each on the tty,
# then asks the terminal where the cursor actually landed (DSR) and reports the
# difference from what vis_width predicted.  That difference IS the correction.
#
#   delta 0    the tables are right for this row
#   delta > 0  the terminal advanced further than predicted — a glyph on this
#              row belongs in `icons`; on a live line this shows up as the row
#              being cut off with an ellipsis
#   delta < 0  the terminal advanced less — a glyph belongs in `narrow`; on a
#              live line the row sits short of the right margin
#
# Rows are chosen to exercise the glyphs that have actually caused trouble,
# including one carrying several at once: errors accumulate along a row, so a
# single-glyph row can be wrong without being visibly wrong.
# ════════════════════════════════════════════════════════════════════════════

def selftest() -> int:
    try:
        tty = open("/dev/tty", "r+b", buffering=0)
    except OSError:
        print("needs a real terminal tab (DSR has no tty here)")
        return 1

    import tty as ttymod
    fd = tty.fileno()
    old = termios.tcgetattr(fd)
    cols = term_cols() or 80

    # Report to stdout so it can be redirected; rows are drawn on the tty and
    # LEFT there.  Both halves are needed and they are not the same thing: the
    # numbers say whether the width tables are right, and the drawn rows are
    # the only way to catch a fault that measures correctly and renders wrong —
    # 🕰 dropped the colons of the time beside it while every measurement of it
    # was perfect.  Redirecting the report must not cost that.
    print("--- claude-code-usage-statusline --selftest ---")
    print("profile:           %s" % PROFILE)
    print("TERMINAL_EMULATOR: %s" % os.environ.get("TERMINAL_EMULATOR", "unset"))
    print("TERM_PROGRAM:      %s" % os.environ.get("TERM_PROGRAM", "unset"))
    print("TERM:              %s" % os.environ.get("TERM", "unset"))
    print("TMUX:              %s" % ("set" if os.environ.get("TMUX") else "unset"))
    print("python:            %s" % sys.version.split()[0])
    print("terminal width:    %s (rows should reach %s)"
          % (cols, cols - RIGHT_MARGIN))
    print("narrow=%s  icons=%s  clusters=%s\n"
          % (sorted(WIDTHS.narrow), sorted(WIDTHS.icons), WIDTHS.clusters))

    rows = [
        ("rate-cache", render_rate_cache(138.0, 98)),
        # Column 3, both shapes a field can take: a spelled share and the
        # 💯 that stands in for a full one.  The glyph is two columns in a
        # field of three, so a miscount here shows as the 🎮 after it
        # drifting a column.
        ("cache-share", render_cache_share(S_READ, 100, 34)),
        ("limit-session", render_limit(S_SESS, "38", "5", "", "0.4")),
        ("limit-weekly", render_limit(S_WEEK, "84", "2", "", "0.05",
                                      F_LIM_WEEK)),
        # Both fields in their fraction form.  Every limit_pct branch fills
        # its four characters, so this one is not wider than the whole
        # percentages above — it is the one whose glyphs are all punctuation
        # and digits with no leading pad to hide a miscount.
        ("limit-fractional",
         render_limit(S_WEEK, "0.384", "0.04", "", "0.004", F_LIM_WEEK)),
        ("elapsed-clock", pair(S_IDLE + pad_val(RST_W, "45s", True),
                               render_time(), fmt.RIGHT_GRID[-1])),
        # The same cell with nothing elapsed to report, which is how every
        # session starts and the state in which the clock used to wander.
        ("clock-alone", pair("", render_time(), fmt.RIGHT_GRID[-1])),
        ("model-effort", render_model("Opus 5 (1M context)", "high")),
        # The two side by side, as column 2's first row draws them: the
        # model's half is held to width whether or not the glyph is there,
        # and a miscount of the glyph shows as the 💰 drifting.
        ("model-cost", render_model_cost("Opus 5 (1M context)", "high",
                                         "115.2")),
        ("model-cost-plain", render_model_cost("Sonnet 4.6", "", "1234.5")),
        ("diff", render_diff("302", "70")),
        ("tokens", render_tokens(9900000, 460000)),
        ("context", render_ctx(11, 115000)),
        ("mixed", grid_row((render_style("explanatory"),
                            render_model_cost("Opus 5", "high", "115.2"),
                            render_cache_share(S_WRITE, 7, 61),
                            render_limit(S_SESS, "38", "5", "", "0.4")))),
        ("cost-row", cost_group(
            # dctx explicitly: the specimen is built positionally, so a new
            # field with no default silently turns this row into a TypeError
            # that only fires in a real terminal — the tty guard returns
            # first everywhere else.  It did, for as long as dctx existed.
            # The four dollar sums are the same specimen priced at Opus
            # rates, which is what read_turns would have produced from it.
            Turn("", "", 40000, 8000, 900000, 3000, 640000, 3, 142000, None,
                 *_usd(None, 40000, 8000, 900000, 3000)),
            {"sess": 0.5, "week": 2.0}, CTX_1M, COLOUR_INK)),
        # The TOTALS row, which the per-prompt specimen above cannot stand in
        # for.  It used to be the WIDER of the two — 🔋 and 🪫 carried a
        # second figure each where the row above them carried blanks — and
        # since 2026-09-03 it is not: 📖 and 📝 fill that half on the
        # per-prompt row, so both rows now spend fmt.C_SESS on content.  Which is
        # why this specimen still has to be measured separately rather than
        # dropped as the narrower case: what differs now is the CONTENT of
        # those seven columns, not their width, and it is content with its own
        # ways to miscount — dec_align's fixed point, the "?" fallback, and 💯
        # standing in for a full window.  fmt.C_SESS is still the width whose
        # failure shows up as the two 📊 refusing to stack rather than as
        # anything near this cell.
        #
        # Whether session_shares finds a live plan cache does not matter to
        # what is being measured — dec_align returns exactly six columns for
        # every value, and the "?" it falls back to is padded to the same six
        # — so the row is this width either way.
        ("cost-totals", cost_totals_group(
            (Turn("2026-08-24T12:00:00.000Z", "", 40000, 8000, 900000, 3000,
                  640000, 3, 142000, None, *_usd(None, 40000, 8000, 900000,
                                                 3000)),),
            {"sess": 26.0, "week": 80.0}, CTX_1M, COLOUR_INK,
            calib={"sess": 0.5, "week": 2.0})),
    ]

    try:
        ttymod.setcbreak(fd)
        for name, row in rows:
            expect = vis_width(strip_ansi(row))
            tty.write(("\r\033[K%s\033[6n" % row).encode("utf-8"))
            resp = b""
            while not resp.endswith(b"R"):
                ch = tty.read(1)
                if not ch:
                    break
                resp += ch
            tty.write(b"\n")
            try:
                actual = int(resp.decode("ascii", "replace")
                             .rstrip("R").split(";")[-1]) - 1
            except ValueError:
                actual = 0
            delta = actual - expect
            hint = ""
            if delta > 0:
                hint = "  -> a glyph here belongs in `icons`"
            elif delta < 0:
                hint = "  -> a glyph here belongs in `narrow`"
            print("%-14s predicted %-3s actual %-3s delta %+d%s"
                  % (name, expect, actual, delta, hint))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        tty.close()

    print("\nall deltas 0 means the tables are right for this terminal.")
    print("the rows above are drawn on the terminal even when this report is")
    print("redirected: look at them too, since a glyph can measure correctly")
    print("and still render wrong, and no number will tell you that.")
    return 0


# ════════════════════════════════════════════════════════════════════════════
# Entry points.
#
# The mode dispatch is the outermost thing in the program, deliberately.  The
# two modes have OPPOSITE failure policies and neither may leak into the other:
#
#   status  fails visibly.  A blank status line is its own error message, and
#           swallowing a traceback there would hide a broken render forever.
#   cost    fails SILENT.  It runs as a Stop hook under a timeout, and a
#           traceback attaches noise to every turn.  Every failure path prints
#           "{}" — a valid no-op hook response — and exits 0.
# ════════════════════════════════════════════════════════════════════════════

def _flag(argv: Sequence[str], name: str, default: str = "") -> str:
    """Value of a `--name value` argument.

    Matched by MEMBERSHIP, not position: reading argv positionally once meant
    `--last` alone silently turned colour on.
    """
    try:
        return argv[argv.index(name) + 1]
    except (ValueError, IndexError):
        return default


# ════════════════════════════════════════════════════════════════════════════
# The subagent rows — `--mode subagent`.
#
# Claude Code's agent panel lists every task the session is running — Agent
# tool calls, forks, background shells, workflows, teammates — one row each,
# and `subagentStatusLine` in settings.json lets a command REPLACE the text of
# any of those rows.  Every few seconds the panel runs the command with one
# JSON object on stdin and reads back one JSON object per line:
#
#     stdin   {"session_id", "transcript_path", "cwd", "columns",
#              "tasks": [{"id", "name", "type", "status", "description",
#                         "label", "startTime", "model", "effort",
#                         "contextWindowSize", "tokenCount", "tokenSamples",
#                         "cwd"}, ...]}
#     stdout  {"id": "<task id>", "content": "<row text>"}   per task
#
# A task left out keeps the panel's own row; `content: ""` hides it.  Read
# out of Claude Code 2.1.268 on 2026-09-13; regression fixtures keep that
# observed shape explicit as the panel protocol evolves.
#
# WHAT THE PAYLOAD DOES NOT SAY is most of what is worth reading.  It carries
# the harness's own `tokenCount` — the last request's input plus every output
# token, a shape that is neither the context nor the bill — and nothing about
# cache, cost, or the plan windows.  But a local agent's task id IS its agent
# id, and agent_records already knows where `agent-<id>.jsonl` lives, so the
# row is built the way the status line's is: from the transcript, priced per
# record at its own model, with the plan figures taken from the snapshot the
# status line just published.  The panel's figure is not printed at all.
# ════════════════════════════════════════════════════════════════════════════

class AgentUsage(NamedTuple):
    """What one agent's transcript says it billed.  See read_agent_usage."""
    tok_up: Optional[int]   # billable-equivalent input, as the status line's
    tok_down: int
    cache_pct: int          # -1 for no usage at all
    ctx_tokens: int         # the last request's whole input: its window
    cost: float
    parts: Tuple[Tuple[Optional[float], float], ...]  # (epoch, usd) per
                            # request, for the window split
    model: str              # the last record's model id; the payload's
                            # `model` is an alias and may be missing
    effort: str
    calls: int
    last_epoch: Optional[float]   # the last billed record's stamp: when a
                            # finished agent stopped, which the payload does
                            # not say
    # What this agent WROTE, counted off its own tool results.  Defaulted so
    # every construction that predates the pair still builds, and zero for an
    # agent that only read.  See agent_diff.
    lines_added: int = 0
    lines_removed: int = 0
    tool_s: float = 0.0     # seconds inside a tool, this agent's own and
                            # every agent it spawned.  Filled by the caller,
                            # not by read_agent_usage: it is the one figure on
                            # the row that needs files other than this one.
                            # See agent_tool_spans.


NO_AGENT_USAGE = AgentUsage(None, 0, -1, 0, 0.0, (), "", "", 0, None)


def agent_file_for(transcript: str, task_id: str) -> str:
    """The transcript of the agent whose task id is `task_id`, or "".

    Two depths, as agent_files says: directly under subagents/ for the Agent
    tool and forks, one directory further for a workflow's agents.  Only a
    local agent has one; a shell task or a remote agent leaves this "".
    """
    d = _agent_dir(transcript)
    if not d or not task_id or not os.path.isdir(d):
        return ""
    direct = os.path.join(d, "agent-%s.jsonl" % task_id)
    if os.path.isfile(direct):
        return direct
    hits = glob.glob(os.path.join(d, "workflows", "*", "agent-%s.jsonl"
                                  % task_id))
    return hits[0] if hits else ""


_KIDS: Dict[str, Dict[str, List[str]]] = {}


def _agent_id(path: str) -> str:
    """The agent id in `<dir>/agent-<id>.jsonl`, or "" for anything else."""
    base = os.path.basename(path)
    if not base.startswith("agent-") or not base.endswith(".jsonl"):
        return ""
    return base[len("agent-"):-len(".jsonl")]


def _children_by_parent(directory: str) -> Dict[str, List[str]]:
    """Every agent transcript under `directory`, grouped by the agent that
    spawned it.

    Built once per directory and memoised for the life of the process, which
    is one render: a session with 86 agents would otherwise read 86 sidecars
    per row and 7,396 in total, and this is a status line.
    """
    hit = _KIDS.get(directory)
    if hit is not None:
        return hit
    kids: Dict[str, List[str]] = {}
    for f in sorted(glob.glob(os.path.join(directory, "**", "agent-*.jsonl"),
                              recursive=True)):
        parent = agent_meta(f).get("parentAgentId")
        if parent:
            kids.setdefault(str(parent), []).append(f)
    _KIDS[directory] = kids
    return kids


def agent_tool_spans(path: str, blocked: Optional[list] = None
                     ) -> List[Tuple[float, float]]:
    """(start, end) for every tool call this agent ran, its descendants' in.

    `blocked` is the out-parameter scan_tool_spans fills with the
    blocking-prompt subset.  An agent has nobody to put a question to, so it
    is normally empty and is read rather than assumed; net_tool_seconds takes
    the two and hands back what the machine actually spent.

    The recursion is over `parentAgentId` in the sidecars, which is the only
    place the tree is written down: an agent an agent spawned sits in the
    same `subagents/` directory as its parent and is told apart from a
    sibling by that field alone.

    It is belt-and-braces rather than the mechanism.  A child's whole run is
    already inside the parent's own Task span, so the union would come out
    the same for an agent that waited on its children — which is the usual
    case, and the reason scan_tool_spans can call itself recursive for free.
    What this catches is the case where it is not: an agent dispatched in the
    BACKGROUND returns its tool result at once and keeps working, and its
    tools then run outside every span its parent recorded.  Unioned, so the
    ordinary case is not counted twice.
    """
    if not path:
        return []
    directory = os.path.dirname(path)
    kids = _children_by_parent(directory) if directory else {}
    out: List[Tuple[float, float]] = []
    seen = set()
    queue = [path]
    while queue:
        cur = queue.pop()
        if cur in seen:
            continue
        seen.add(cur)
        out.extend(tool_spans(list(_records(cur)), blocked))
        queue.extend(kids.get(_agent_id(cur), ()))
    return out


def agent_meta(path: str) -> dict:
    """The `.meta.json` sidecar beside an agent transcript: agentType,
    description, model alias, spawnDepth.  {} where there is none."""
    if not path.endswith(".jsonl"):
        return {}
    try:
        with open(path[:-len(".jsonl")] + ".meta.json", "r",
                  encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def agent_diff(records: Sequence[dict]) -> Tuple[int, int]:
    """+adds/-removes across everything this agent wrote, from its tool results.

    The status line takes the session's pair from the payload, which Claude
    Code fills in for the session and says nothing about per agent, so the
    agent row counts its own the way a diff is counted: over the
    `structuredPatch` an Edit's result carries, one hunk line at a time, `+`
    added and `-` removed.  A Write to a NEW file has no patch to count — the
    result is `type: "create"` with the whole file in `content` — and every
    line of it is an addition, which is the reading Claude Code's own total
    takes of the same call.

    Deduped on the tool-use id, for the reason _dedupe_usage dedupes on the
    request id: a resumed or compacted transcript can carry the same result
    twice, and counting one edit twice would double the figure the row is
    for.  A result with no id is counted; nothing else identifies it, and
    dropping it would undercount.
    """
    added = removed = 0
    seen = set()
    for r in records:
        res = r.get("toolUseResult")
        if not isinstance(res, dict):
            continue
        tid = ""
        for block in (r.get("message") or {}).get("content") or ():
            if isinstance(block, dict) and block.get("tool_use_id"):
                tid = str(block["tool_use_id"])
                break
        if tid:
            if tid in seen:
                continue
            seen.add(tid)
        patch = res.get("structuredPatch")
        if isinstance(patch, list) and patch:
            for hunk in patch:
                for line in (hunk or {}).get("lines") or ():
                    if not isinstance(line, str) or not line:
                        continue
                    if line[0] == "+":
                        added += 1
                    elif line[0] == "-":
                        removed += 1
        elif res.get("type") == "create" and isinstance(res.get("content"),
                                                        str):
            added += len(res["content"].splitlines())
    return added, removed


def read_agent_usage(path: str) -> AgentUsage:
    """One pass over an agent's transcript, the way read_transcript reads the
    session's: deduped on requestId, summed, priced per record.

    Context is the LAST non-zero request's whole input — fresh plus both
    cache classes — which is the same reading 🧠 takes on the status line,
    for the same window question: this agent's, not the session's.
    """
    if not path:
        return NO_AGENT_USAGE
    recs = list(_records(path))
    reqs = _dedupe_usage(recs)
    fresh = cwrite = cread = down = 0
    ctx = 0
    cost = 0.0
    parts = []
    model = effort = ""
    last = None
    for r in reqs:
        m = r.get("message") or {}
        u = m.get("usage") or {}
        f = u.get("input_tokens") or 0
        cw = u.get("cache_creation_input_tokens") or 0
        cr = u.get("cache_read_input_tokens") or 0
        o = u.get("output_tokens") or 0
        if not (f or cw or cr or o):
            continue                        # an interrupted request
        fresh += f
        cwrite += cw
        cread += cr
        down += o
        if f + cw + cr:
            ctx = f + cw + cr
        usd = sum(_usd(m.get("model"), f, cw, cr, o))
        cost += usd
        epoch = ts_epoch(r.get("timestamp") or "")
        parts.append((epoch, usd))
        last = epoch if epoch is not None else last
        model = m.get("model") or model
        effort = r.get("effort") or effort
    in_all = fresh + cwrite + cread
    if not parts:
        return NO_AGENT_USAGE
    return AgentUsage(
        int(fresh + W_CACHE_WRITE * cwrite + W_CACHE_READ * cread), down,
        int(100 * cread / in_all) if in_all > 0 else -1,
        ctx, cost, tuple(parts), model, effort, len(parts), last,
        *agent_diff(recs))


def agent_window_shares(u: AgentUsage) -> Dict[str, Optional[float]]:
    """This agent's share of each live plan window, in percent.

    turn_cost_since for a record list rather than a Turn: the same
    boundaries (_window_starts), the same unit (calibration), the same rule
    for an unstamped record — it counts IN.  None where either is missing,
    which render_agent_limit draws as "?".
    """
    out = {"sess": None, "week": None}
    if not u.parts:
        return out
    try:
        starts = dict(zip(("sess", "week"), _window_starts()))
        calib = calibration()
    except Exception:
        return out
    for key, start in starts.items():
        unit = calib.get(key)
        if not unit:
            continue
        edge = start.timestamp() if start is not None else None
        spent = sum(c for e, c in u.parts
                    if edge is None or e is None or e >= edge)
        out[key] = spent / unit
    return out




def prepare_subagent_tasks(pay: dict):
    """Read every task sidecar once and return renderer-ready task facts.

    The agent-panel renderer receives only these immutable-ish snapshots.  In
    particular it never opens a transcript while composing a row, which keeps
    panel layout safe to reuse by another coding-agent adapter.
    """
    transcript = str(pay.get("transcript_path") or "")
    prepared = []
    for task in pay.get("tasks") or ():
        if not isinstance(task, dict) or not task.get("id"):
            continue
        try:
            path = agent_file_for(transcript, str(task["id"]))
            blocked = []
            usage = read_agent_usage(path)._replace(
                tool_s=net_tool_seconds(agent_tool_spans(path, blocked),
                                        blocked))
            prepared.append((task, usage, agent_meta(path),
                             agent_window_shares(usage)))
        except Exception:
            # A malformed or concurrently replaced sidecar must leave the
            # panel's own task row intact rather than break every task.
            continue
    return tuple(prepared)


def render_subagent(prepared_tasks, cols: Optional[int], lim: Limits,
                    now: Optional[float] = None) -> str:
    """Serialize pure pre-rendered task rows for Claude Code's JSONL panel."""
    out = []
    for task_id, row in subagent_render.render_task_rows(prepared_tasks, lim,
                                                           cols, now):
        out.append(json.dumps({"id": task_id, "content": row},
                              ensure_ascii=False))
    return "".join(line + "\n" for line in out)


def emit_source_diagnose(spec: str, prepared) -> None:
    """Emit redacted collector state without contaminating hook stdout."""
    reading = prepared.reading if prepared is not None else {}
    source = str((reading.get("source") if isinstance(reading, dict) else "")
                 or spec or "auto")
    if source.startswith("cmd:"):
        source = "cmd"
    source = source.replace("\n", " ").replace("\r", " ")[:48]
    sys.stderr.write("diagnose source=%s reading=%s stale=%s as_of=%s retry_at=%s\n" %
                     (source, "available" if reading else "unavailable",
                      bool(reading.get("stale")) if isinstance(reading, dict) else False,
                      reading.get("as_of", "") if isinstance(reading, dict) else "",
                      reading.get("retry_at", "") if isinstance(reading, dict) else ""))


def main_subagent(argv: Sequence[str], raw: str) -> int:
    try:
        pay = json.loads(raw)
    except Exception:
        return 0                            # nothing printed: panel's rows stand
    if not isinstance(pay, dict):
        return 0
    cols_s = _flag(argv, "--cols")
    if cols_s.isdigit():
        cols = int(cols_s) or None
    else:
        c = pay.get("columns")
        cols = int(c) if isinstance(c, (int, float)) and c > 0 else term_cols()
    source_spec = _flag(argv, "--usage-source",
                        os.environ.get("CODING_AGENT_USAGE_LINE_USAGE_SOURCE", "auto"))
    account = _flag(argv, "--account", "default")
    period = _flag(argv, "--account-period", "day")
    prepared = prepare_claude_reading(
        source_spec, account, period,
        {"session": str(pay.get("session_id") or ""),
         "model": str(pay.get("model") or "")}, frozen_now())
    # A failed explicit source is unavailable, never a reason to revive a
    # global legacy limit cache.  Native/auto readings remain available via
    # the shared collector above.
    lim = prepared.limits if prepared.reading else NO_LIMITS
    seed_limits_snapshot(lim, prepared.reading)
    if "--diagnose" in argv:
        emit_source_diagnose(source_spec, prepared)
    # Panel stdout is JSONL task rows only; account scope is intentionally not
    # appended here because it would be mistaken for a panel task.
    sys.stdout.write(render_subagent(prepare_subagent_tasks(pay), cols, lim,
                                     frozen_now()))
    return 0


def main_status(argv: Sequence[str], raw: str) -> int:
    pay = read_payload(raw)
    # An explicit transcript is an offline invocation.  It deliberately does
    # not require a hook payload (and therefore must not make the launcher
    # wait for stdin); its path also wins over a stale path in that payload.
    transcript = _flag(argv, "--transcript")
    if transcript:
        pay = pay._replace(transcript=transcript)

    current = pay.current_dir or pay.project_dir
    pay = pay._replace(current_dir=current,
                       project_dir=pay.project_dir or current)

    # The agent files are walked ONCE here and handed to both readers.  Each
    # would otherwise walk them itself, and a session that has run many
    # agents has as many bytes there as in its own transcript.  The same walk
    # fills `spans` — when each agent was working, for ⌛🤖 — `tools` — when
    # each was inside a tool, for ⌛🔧 — and `blocked`, the blocking-prompt
    # subset of those, so none of the three clocks costs a second read.
    have_tr = bool(pay.transcript) and os.path.isfile(pay.transcript)
    spans = []
    tools = []
    blocked = []
    agents = (agent_records(pay.transcript, spans=spans, tools=tools,
                            blocked=blocked) if have_tr else ())
    tr = (read_transcript(pay.transcript, agents, spans, tools, blocked)
          if have_tr else EMPTY_TRANSCRIPT)
    # Offline transcript reports have no hook workspace.  Do not silently use
    # this command's cwd (nor run its potentially expensive dirty-tree probe)
    # as though it were the recorded session's project.
    git = detect_git() if current or not transcript else NO_GIT
    # The shared source collector is the only path for an explicitly selected
    # source.  Its command context contains only scalar scope fields; raw
    # payload quotas never reach an external command.  Legacy cache projection
    # is retained solely as the compatibility fallback when auto has no shared
    # reading available.
    source_spec = _flag(argv, "--usage-source",
                        os.environ.get("CODING_AGENT_USAGE_LINE_USAGE_SOURCE", "auto"))
    account = _flag(argv, "--account", "default")
    period = _flag(argv, "--account-period", "day")
    source_context = {"session": pay.session_id,
                      "model": pay.model_id or pay.model,
                      # A payload is observed at render intake; retain that
                      # evidence so the shared native collector does not mark
                      # it stale merely because it lacks its own timestamp.
                      "as_of": frozen_now() or time.time()}
    # Native payload data is trusted only for the native/auto path.  An
    # explicit external command receives no quota envelope through its stdin.
    if source_spec in ("", "auto", "native", "none", "off"):
        try:
            raw_payload = json.loads(raw or "{}")
            native = raw_payload.get("rate_limits") if isinstance(raw_payload, dict) else None
            if isinstance(native, dict):
                source_context["rate_limits"] = native
        except (TypeError, ValueError):
            pass
    prepared = prepare_claude_reading(source_spec, account, period,
                                      source_context, frozen_now())
    if "--diagnose" in argv:
        emit_source_diagnose(source_spec, prepared)
    # `none` disables external collection, not the native payload that Claude
    # already supplied.  Only a named external source supersedes that intake.
    explicit_source = source_spec not in ("", "auto", "native", "none", "off")
    if prepared.reading:
        base_limits = prepared.limits
    elif explicit_source:
        # A failed named source is unavailable, not permission to quote an
        # unrelated legacy cache or to retry the command by another route.
        base_limits = NO_LIMITS
    else:
        base_limits = NO_LIMITS
    seed_limits_snapshot(base_limits, prepared.reading)
    # Session/turn shares still require the one transcript scan performed
    # above; rendering itself receives only the prepared snapshot.
    lim, cache = _with_shares(base_limits, pay.transcript, agents)
    cols_s = _flag(argv, "--cols")
    # "--cols 0" means "pretend the width is unknown", which is the only way to
    # exercise the fallback layout deterministically from a test.
    cols = (int(cols_s) or None) if cols_s.isdigit() else term_cols()
    # Stateful measurements are prepared at the adapter boundary; the pure
    # renderer only receives their already-computed values.
    ctx_window = ctx_window_for(pay.ctx_window, pay.model + pay.model_id)
    publish_ctx_window(pay.session_id, ctx_window)
    tokens = None if tr.tok_up is None else tr.tok_up + tr.tok_down
    rate = session_rate(pay.session_id, tokens, frozen_now())
    output = render_status(pay, tr, git, lim, cols, frozen_now(),
                           "--no-column-rules" not in argv, ctx_window, rate,
                           cache)
    account_data = prepared.reading.get("account")
    has_account = (isinstance(account_data, dict) and
                   any(account_data.get(key) is not None
                       for key in ("input_tokens", "output_tokens", "cost_usd")))
    if prepared.account_text and (has_account or prepared.limits == NO_LIMITS):
        output += prepared.account_text + "\n"
    sys.stdout.write(output)
    return 0


def main_cost(argv: Sequence[str], raw: str) -> int:
    """The Stop hook.  Everything here is inside one catch-all.

    It replaces both cost-line.py and hooks/cost-line.sh: the hook used to
    parse the payload in bash, walk the ancestry for the width, then spawn a
    second Python to do the work.  One process now does all three.
    """
    try:
        transcript = _flag(argv, "--transcript")
        if not transcript:
            transcript = (json.loads(raw) or {}).get("transcript_path", "")
        if not transcript or not os.path.isfile(transcript):
            print("{}")
            return 0
        cols_s = _flag(argv, "--cols")
        # "--cols 0" means "pretend the width is unknown", which is the only
        # way to exercise the fallback layout deterministically from a test.
        cols = (int(cols_s) or None) if cols_s.isdigit() else term_cols()
        # --no-usage-text keeps each row's marker glyph and drops the words.
        # The glyph is what tells the three rows apart at a glance; the words
        # are the part that reads identically every turn, which is what makes
        # them the half worth being able to switch off.
        words = "--no-usage-text" not in argv
        opts = CostOpts(
            prefix=_flag(argv, "--prefix", E_COSTLINE),
            label=_flag(argv, "--label", C_LABEL if words else E_ROW_PROMPT),
            totals_label=C_TOTALS_LABEL if words else E_ROW_TOTAL,
            compact_label=C_COMPACT_LABEL if words else E_ROW_COMPACT,
            agents_label=C_AGENTS_LABEL if words else E_ROW_AGENTS,
            account_totals="--no-account-totals" not in argv,
            stamps="--no-datetime" not in argv,
            force_newline="--force-newline" in argv,
            cols=cols,
            colour="--color" in argv,
            totals="--no-totals" not in argv,
            right_align="--no-right-align" not in argv,
            # The transcript's BASENAME, not the payload's session_id, so the
            # live hook and --transcript take the same path — they are the
            # same string, and a lookup that only runs in production is a
            # lookup no harness can check.
            session_id=os.path.basename(transcript)[:-len(".jsonl")]
                       if transcript.endswith(".jsonl") else "",
        )
        source_spec = _flag(argv, "--usage-source",
                            os.environ.get("CODING_AGENT_USAGE_LINE_USAGE_SOURCE", "auto"))
        account = _flag(argv, "--account", "default")
        period = _flag(argv, "--account-period", "day")
        prepared = prepare_claude_reading(
            source_spec, account, period,
            {"session": opts.session_id}, frozen_now())
        if "--diagnose" in argv:
            emit_source_diagnose(source_spec, prepared)
        seed_limits_snapshot(prepared.limits if prepared.reading else NO_LIMITS,
                             prepared.reading)
        # The wait belongs to the LIVE hook alone.  `--transcript` names a
        # file nobody is appending to, so there is nothing to wait for and
        # every golden case would pay the budget for a turn that is never
        # coming.
        # The agent files, read once: the settle wait below may parse the
        # main file several times and must fold in the SAME agent reading
        # each time, because that reading's extent is what gets published
        # after the render as "reported up to here".
        agents = agent_records(transcript)
        turns = (read_turns(transcript, agents) if _flag(argv, "--transcript")
                 else read_turns_settled(transcript, agents=agents))

        # --all is the by-hand mode: every prompt in the transcript, listed,
        # as plain text rather than a hook response.  It is not what the hook
        # asks for and never emits JSON, so it cannot be mistaken for one.
        if "--all" in argv:
            ink = COLOUR_INK if opts.colour else PLAIN_INK
            win = window_for(turns, opts.session_id)
            calib = calibration()
            for i, t in enumerate(turns, 1):
                print("--- prompt #%d  %s  “%s…”  (%d calls)"
                      % (i, t.ts, t.text[:58], t.calls))
                print("    " + cost_group(t, calib, win, ink, None,
                                          opts.account_totals, opts.stamps))
            if turns and opts.totals:
                print("\n" + place(
                    cost_totals_group(turns, plan_totals(), win, ink,
                                      calib=calib, acct=opts.account_totals,
                                      stamps=opts.stamps),
                    opts, opts.totals_label, C_CHROME_CONT).rstrip())
            return 0

        line = render_cost_line(turns, opts, frozen_now())
        if not line.strip():
            print("{}")
            return 0
        account_data = prepared.reading.get("account") if isinstance(prepared.reading, dict) else {}
        has_account = (isinstance(account_data, dict) and
                       any(account_data.get(key) is not None
                           for key in ("input_tokens", "output_tokens", "cost_usd")))
        # A sole default bucket is already represented by the historical cost
        # grid.  Only organization/account metrics or an unprojectable bucket
        # receive a separate row.
        if prepared.account_text and (has_account or prepared.limits == NO_LIMITS):
            line += "\n" + prepared.account_text
        print(json.dumps({"systemMessage": line}))
        # The LIVE hook only, as with the settle wait: a golden case renders
        # one transcript at five widths in one TMPDIR, and a state file
        # written by the first would change what the second reports.  The
        # goldens therefore exercise the stamp fallback; tests/agents.py
        # exercises this.
        if not _flag(argv, "--transcript"):
            publish_agent_offsets(transcript, agents)
        return 0
    except Exception:
        # Fail silent, by contract.  "{}" is a valid no-op hook response, so
        # nothing appears in the terminal and the turn is not disturbed.
        print("{}")
        return 0


USAGE = """\
usage: claude-code-usage-statusline.py --mode {status|cost|subagent} [options]
       claude-code-usage-statusline.py --selftest

Renders the Claude Code status line, the per-prompt cost line and the agent
panel's rows from one set of glyphs, widths and formatters.  docs/, beside
this file, carries the design notes: the layout rule, the terminal width
tables, and the chrome the cost rows are laid out against.

modes:
  --mode status      read the status-line JSON on stdin, print three rows
  --mode cost        read the Stop-hook JSON on stdin, print a systemMessage
  --mode subagent    read the agent panel's task list on stdin, print one
                     {"id", "content"} line per task -- the subagentStatusLine
                     setting.  Each row, flush left: type, id, run state,
                     then the name (or the description, where the panel has
                     no name) filling what is left; flush right at fixed
                     widths: model, effort, elapsed and token rate, what the
                     agent's own transcript says it billed (tokens, cache
                     rate, context, cost), and its share of the two plan
                     windows.  --cols and --usage-source apply.
  --selftest         draw specimen rows and measure them against the terminal

options (all modes):
  --subscript-decimals
                     write a fraction in U+2080..U+2089 instead of after a
                     point: 🎤 1.2٪ becomes 🎤 1₂٪, 💰 29.8 becomes 💰 29₈.
                     Off by default.  The leading zero the status line drops
                     comes back — "₃₈" would read as 38 where ".38" cannot —
                     so a reading under 1٪ is the same width either way.
                     No field is narrowed yet: the saving is real but it is
                     only banked once a probe has measured these glyphs on
                     the terminal in use.
  --no-mark-spacing  close the blank between a mark and its value (🎤 .98٪
                     becomes 🎤.98٪).  Status: all four column-4 fields, so
                     the column narrows from 33 to 29, and column 3's two,
                     16 to 14.  Cost: 🧩, 🎯 and the
                     💳 inside a totals-row limit cell -- the marks with
                     nothing in that column.  The other five hold a "+" or the
                     blank the totals row stacks under it, and closing those
                     would unstack the two rows.
                     --mark-spacing is the default and is accepted so a
                     settings file can say which it wants
  --cols N           terminal width, overriding the ancestry walk.  Chiefly
                     for the golden test, which must be deterministic.  "0"
                     means "pretend the width is unknown".
  --usage-source SPEC
                     where to read the plan figures when Claude Code's own
                     payload carries none.  Claude Code's figures are always
                     preferred and this is never consulted while they are
                     there.  Default "auto"; also settable as
                     CODING_AGENT_USAGE_LINE_USAGE_SOURCE.
                       auto      native payload, then the managed tracker
                       none      do not refresh an external provider
                       claude-usage-tracker
                                 the Claude Usage Tracker menu-bar app
                                 (macOS), read from its UserDefaults store
                       cmd:PATH  any program that prints a reading as JSON on
                                 stdout, using the versioned source contract

options (--mode status):
  --no-column-rules  drop the faint "|" borders between the five right-hand
                     columns, leaving the plain gaps they are painted into.
                     They take no width either way, so this changes nothing
                     but the ink.  --column-rules is the default and is
                     accepted so a settings file can say which it wants.
                     Note the rules are ALREADY off below 180 columns, at an
                     unknown width, and under --no-mark-spacing; this switches
                     them off at the widths that would otherwise carry them.

options (--mode cost):
  --transcript PATH  read this transcript instead of the payload's
  --all              list every prompt as plain text instead of emitting a
                     hook response.  For reading a transcript by hand.
  --prefix TEXT      icon block at the head of the row
  --label TEXT       label after it, bolded at print time
  --color            emit colour (default: plain, which the hook needs)
  --no-totals        suppress the session-totals row
  --no-right-align   print flush left
  --no-account-totals
                     drop the "💳 99٪" half of the 🔋 and 🪫 cells (💳 💯 at
                     a full window), leaving this session's own share of each
  --no-datetime      drop the 📅 date and 🕐 clock cells
  --no-usage-text    drop the "Usage: ..." words from every row label, keeping
                     each row's marker glyph
  --force-newline    always open the message with a blank line.  Taken without
                     asking when the window is too narrow for the eleven
                     columns "Stop says: " costs the first row; this asks for
                     it at every width, because it reads better.
"""


def main(argv: Sequence[str]) -> int:
    # --selftest must be checked BEFORE reading stdin: a live invocation
    # supplies a payload and a self-test does not, so reading first would block
    # forever.
    if "--selftest" in argv:
        return selftest()
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(USAGE)
        return 0
    # Before anything renders: it moves the grid every renderer lays onto.
    set_mark_spacing("--no-mark-spacing" not in argv)
    # Same reason, one layer in: it changes what the five numeric formatters
    # emit, and every field on both readouts is measured from that.
    set_subscript_decimals("--subscript-decimals" in argv)
    mode = _flag(argv, "--mode", "status")
    # A named transcript is a complete offline input.  In particular, do not
    # wait for the still-open stdin pipe used by command-line callers.
    explicit_transcript = bool(_flag(argv, "--transcript"))
    if mode == "cost":
        try:
            raw = "" if explicit_transcript else sys.stdin.read()
        except Exception:
            print("{}")
            return 0
        return main_cost(argv, raw)
    if mode == "subagent":
        try:
            raw = sys.stdin.read()
        except Exception:
            return 0
        return main_subagent(argv, raw)
    if mode != "status":
        sys.stderr.write("unknown --mode %r\n" % mode)
        sys.stdout.write(USAGE)
        return 2
    try:
        raw = "" if explicit_transcript else sys.stdin.read()
    except Exception:
        raw = ""
    return main_status(argv, raw)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
