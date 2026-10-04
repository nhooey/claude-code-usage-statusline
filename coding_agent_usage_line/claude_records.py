#!/usr/bin/env python3
"""Claude payload records and transcript/accounting parser.

This module owns Claude-specific JSONL interpretation and price accounting.
It deliberately has no terminal rendering or hook stdin/stdout orchestration.
"""
import functools
import glob
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from . import formatting as fmt
from . import state
from .formatting import *

_UTC = fmt._UTC

# Billing weights relative to a fresh input token.  Raw ▴ traffic is ~99% cache
# reads in a typical session, so an unweighted sum says nothing about either
# cost or context size.  The write weight is TTL-dependent — 1.25x at the
# 5-minute default, 2x at the 1-hour TTL these sessions run on.
W_CACHE_WRITE, W_CACHE_READ = 2.0, 0.1

# Opus 5 list price, USD per token, for the cost line's per-prompt figure.
P_IN, P_OUT, P_CR, P_CW = 5e-6, 25e-6, 0.5e-6, 10e-6

# Per-model prices.  For the calibration scan, which sees other sessions'
# turns and so cannot assume one model; and since 2026-09-11 for every
# record read_turns prices, because an agent can run a model its session
# does not.  $/token: fresh, output, cache-read, cache-write at the 2x TTL.
#
# FIRST MATCH WINS, so the specific rows sit above the family they refine.
# Figures are Claude Code's own: its binary bakes in a model catalog
# (`pricing_tiers` / `models[].pricing`), read out of 2.1.268 on 2026-09-11.
# Fable 5.1 differs from Fable 5 in one field, cache-read, and Sonnet 5 is
# not Sonnet 4.x — the old "sonnet" row was 3/15/6/0.3, which is the 4.x
# tier and priced every Sonnet 5 fork half again too high.  The bare
# "opus" row stays as _price's fallback for a model it has never heard of:
# the deliberate ceiling rather than a guess in the other direction.
MODEL_PRICE = (
    ("opus", (5e-6, 25e-6, 0.5e-6, 10e-6)),
    ("fable-5-1", (10e-6, 50e-6, 0.25e-6, 20e-6)),
    ("fable", (10e-6, 50e-6, 1e-6, 20e-6)),
    ("sonnet-5", (2e-6, 10e-6, 0.2e-6, 4e-6)),
    ("sonnet", (3e-6, 15e-6, 0.3e-6, 6e-6)),
    ("haiku", (1e-6, 5e-6, 0.1e-6, 2e-6)),
)


# ════════════════════════════════════════════════════════════════════════════
# Records.
# ════════════════════════════════════════════════════════════════════════════

class Payload(NamedTuple):
    """The status-line JSON, reduced to what is actually read."""
    current_dir: str
    project_dir: str
    model: str
    model_id: str
    ctx_window: str         # context_window.context_window_size, when given
    transcript: str
    cost_usd: str
    lines_added: str
    lines_removed: str
    output_style: str
    effort: str
    session_id: str
    rl_session_pct: str
    rl_session_reset: str
    rl_weekly_pct: str
    rl_weekly_reset: str
    pr_number: str


class Transcript(NamedTuple):
    """What one pass over the transcript yields for the status line.

    `tok_up` is None only when there was no transcript to read at all, which is
    a different state from a transcript that exists and is empty: the first
    suppresses the token segment, the second renders it as zeros.  Two empty
    states, two renderings, and conflating them was how a fresh session grew a
    "▴0 ▾0" that looked like a stall.
    """
    tok_up: Optional[int]
    tok_down: int
    cache_pct: int          # -1 when there is no usage data at all
    ctx_tokens: int
    user_ts: str
    user_text: str
    asst_ts: str
    asst_text: str
    busy_s: float           # seconds this thread spent answering, its own
                            # tool calls in — see thread_clock
    start_s: float          # epoch of the first STAMPED record, 0 if none
    tool_s: float = 0.0     # of that answering, the part spent inside a tool —
                            # this thread's own, LESS the waiting spans
                            # below.  See tool_spans.
                            # Defaulted so EMPTY_TRANSCRIPT and the fixtures
                            # that predate it still build.
    blocked_s: float = 0.0  # and the part spent inside a tool that was
                            # waiting: a question put to the user, or an
                            # agent it dispatched.  It is answering time by
                            # the transcript's reckoning and waiting time by
                            # any reader's, so the row hands it to 🚦 — see
                            # WAITING_TOOLS and render_elapsed.
    turn_s: float = 0.0     # epoch of the prompt the current turn opened on
    eta: Tuple[float, ...] = ()  # (epoch, seconds left) off the last ETA the
                            # main thread reported IN THAT TURN, while it is
                            # still answering; () otherwise.  See eta_report.
    agent_etas: Tuple[Tuple[float, Optional[float]], ...] = ()
                            # (finish epoch, last record epoch) for every
                            # agent still answering with a live ETA: what the
                            # main thread's ⛳ inherits.  See agent_records.
    queued: int = 0         # messages waiting for this thread's next turn;
                            # see queue_step
    compactions: int = 0    # how often this window has been compacted; see
                            # is_compaction
    shells: int = 0         # background shells this thread started and has
                            # not heard the end of; see scan_background
    monitors: int = 0       # and Monitors, likewise
    tool_at: float = 0.0    # epoch the oldest tool call of the current turn
                            # still waiting on its result started, on a live
                            # read; 0 if none.  WAITING_TOOLS are left out:
                            # a question or an agent is not a tool running.
                            # The 🛫 cell shows its age; see render_rate_cache.


EMPTY_TRANSCRIPT = Transcript(None, 0, -1, 0, "", "", "", "", 0.0, 0.0)


class Git(NamedTuple):
    in_git: bool
    branch: str
    dirty: bool
    toplevel: str
    main_root: str
    is_worktree: bool


NO_GIT = Git(False, "", False, "", "", False)


class Limits(NamedTuple):
    """The two plan windows.  Percentages are strings because a missing figure
    is the empty string throughout, which is what makes a blank row blank.

    They carry whatever precision their source gave them — see _pct_str — and
    are not rounded until limit_pct draws them.  A percentage here may be
    "0.38", so read one with _pct_num, never int().
    """
    session_pct: str
    session_reset: str
    session_share: str
    weekly_pct: str
    weekly_reset: str
    weekly_share: str
    # What the ONE turn just answered put into each window.  Defaulted, so
    # every construction that predates the field still builds, and left ""
    # by orchestration: only _with_shares has a transcript to derive it from.
    session_turn: str = ""
    weekly_turn: str = ""


NO_LIMITS = Limits("", "", "", "", "", "")


class CacheShares(NamedTuple):
    """Where the money went, as whole percent of a bill: 📖 the part spent
    re-reading the conversation (cache_read) and 📝 the part spent caching
    what was added (cache_creation) -- turn_shares' pair, at two scopes.

    `turn_*` is the prompt just answered, the same turn _with_shares picks
    for column 4's 🎤, and `sess_*` is every turn of the session summed
    before dividing, which is the totals-row 💰 of the cost line taken
    apart.  None is a figure that could not be derived -- no cost to take a
    share of -- and draws "?"; all four None is a session with no transcript
    to read, and the column is not drawn at all.  Integers, not strings,
    because unlike Limits' percentages these never arrive from a source in a
    precision of their own: they are rounded here, once, to the whole point
    the three-column field holds.
    """
    turn_read: Optional[int] = None
    turn_write: Optional[int] = None
    sess_read: Optional[int] = None
    sess_write: Optional[int] = None


NO_CACHE_SHARES = CacheShares()


class Turn(NamedTuple):
    """One prompt the user typed, and everything billed while answering it.

    "Everything" includes what the turn's AGENTS billed — subagents, forks,
    workflow agents — which Claude Code writes to files of their own beside
    the transcript; see agent_records.  The token sums and the dollar sums
    carry both; `calls` is the main thread alone and `agent_calls` the rest,
    because read_turns_settled waits on the main thread's tail and an agent's
    first request landing early must not end that wait.
    """
    ts: str
    text: str
    fresh: int
    cache_write: int
    cache_read: int
    out: int
    ctx: int                # a READING, not a sum — see read_turns
    calls: int
    dur_s: float            # wall-clock seconds this turn took to answer
    dctx: Optional[int]     # growth over the previous turn; None where there
                            # is no previous reading to subtract
    usd_in: float           # the four components of the bill, each priced
    usd_out: float          # PER RECORD at that record's model and summed.
    usd_cr: float           # turn_cost is their total and turn_shares their
    usd_cw: float           # ratios, so a Sonnet fork inside an Opus turn is
                            # billed at Sonnet rates in both — pricing the
                            # token sums above at one model's rates cannot say
                            # that.  A compaction puts its preTokens here at
                            # the cache-read rate, which is what lets
                            # turn_cost drop the "unless compact" clause it
                            # used to need.
    compact: bool = False   # a compaction rather than a prompt.  Its figures
                            # come from the boundary record, not from usage
    reported: bool = False  # a Stop hook has already run at a point AFTER this
                            # turn, so whatever this line owed for it has been
                            # printed once already.  See read_turns.
    parts: Tuple[Tuple[Optional[float], float], ...] = ()
                            # (epoch, dollars) for each billed call, in the
                            # order the transcript wrote them.  The fields
                            # above are SUMS, and a sum cannot be split at a
                            # window boundary that falls inside the turn — see
                            # turn_cost_since, which is the only reader.  The
                            # epoch is None where the stamp would not parse;
                            # the cost is still carried, so these always total
                            # turn_cost() whatever the stamps did.
                            # A compaction's own cost is NOT in here — it
                            # bills through no usage record — though records
                            # of the answer an auto compaction landed inside
                            # are; turn_cost_since tests `compact` for that.
    agent_calls: int = 0    # agent requests folded into the sums above
    agent_ids: Tuple[str, ...] = ()
                            # their requestIds, in the order folded.  Read
                            # by tests/agents-once.py, which replays a
                            # session's Stops and needs to say WHICH request
                            # printed where; rows print money, not ids.
    agent: bool = False     # a synthetic turn holding agent spend that
                            # arrived after its own turn was reported.  Its
                            # `calls` is 0, which keeps it out of every
                            # selection of "the prompt to report" and out of
                            # the settle wait.  See late_agent_turn.
    tool_s: float = 0.0     # of dur_s, the part spent inside a tool, less
                            # the waiting calls below — the status line's 🔧,
                            # read over this turn's span alone.  See
                            # turn_clock.
    blocked_s: float = 0.0  # and the part spent inside a WAITING_TOOLS call:
                            # a question put to the user, or an agent this
                            # thread dispatched and sat on.  Neither 🤖 nor
                            # 🔧; the status line's 🚦.
    agent_model_s: float = 0.0
    agent_tool_s: float = 0.0
                            # the 🤖 and 🔧 of the agent requests folded in
                            # above, by each agent's own clock.  Not part of
                            # dur_s: agents run beside the answer, so these
                            # are agent-seconds and can outrun it.  See
                            # turn_times.
    prompt_id: str = ""     # the promptId Claude Code stamps on every user
                            # record of the turn, and the receipt's 🔖 prints
                            # the head of.  Empty on a compaction, a late
                            # agent turn, and a transcript too old to carry it.
    turn_index: Optional[int] = None
                            # turnPosition.turnIndex off the same records:
                            # Claude Code's own count of the session's turns,
                            # printed beside it.  None where it is not
                            # written; never counted here instead, because a
                            # count of THIS file's turns restarts on a resume
                            # and would name a different turn than Claude
                            # Code does.


class AgentRec(NamedTuple):
    """One billed request from an agent's transcript, with what is needed to
    file it under a turn of the main transcript.  See agent_records."""
    epoch: Optional[float]
    prompt_id: str          # the main-transcript turn that spawned or resumed
                            # the agent; "" where the agent file never said
    model: Optional[str]
    fresh: int
    cache_write: int
    cache_read: int
    out: int
    request_id: str
    path: str               # the agent file, for the offsets the Stop hook
    offset: int             # keeps — see agent_offsets
    model_s: float = 0.0    # the agent's 🤖 and 🔧 since its previous billed
    tool_s: float = 0.0     # request, so each second is filed where this
                            # request's tokens are; see split_clock


# ════════════════════════════════════════════════════════════════════════════
# Reading the payload.
# ════════════════════════════════════════════════════════════════════════════

def _first(d: dict, *paths, **kw) -> str:
    """First present, non-null value among dotted `paths`, else `default`.

    Mirrors jq's `//` chain, including that it short-circuits on null or
    absent but NOT on a present falsy value like 0 or false.
    """
    default = kw.get("default", "")
    for path in paths:
        cur = d
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None and cur is not False:
            return cur if isinstance(cur, str) else _num(cur)
    return default


def _num(v) -> str:
    """A JSON number the way jq -r prints it: integers without a decimal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return "%d" % v
    return "%s" % v


def read_payload(raw: str) -> Payload:
    """Parse the status-line JSON.  A malformed payload yields empty fields
    rather than an exception: a status line that renders nothing is a worse
    failure than one that renders a row of blanks."""
    try:
        d = json.loads(raw)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    return Payload(
        current_dir=_first(d, "workspace.current_dir", "cwd"),
        project_dir=_first(d, "workspace.project_dir", "cwd"),
        model=_first(d, "model.display_name"),
        model_id=_first(d, "model.id"),
        ctx_window=_first(d, "context_window.context_window_size"),
        transcript=_first(d, "transcript_path"),
        cost_usd=_first(d, "cost.total_cost_usd"),
        lines_added=_first(d, "cost.total_lines_added", default="0"),
        lines_removed=_first(d, "cost.total_lines_removed", default="0"),
        output_style=_first(d, "output_style.name"),
        effort=_first(d, "effort.level"),
        session_id=_first(d, "session_id"),
        rl_session_pct=_first(d, "rate_limits.five_hour.used_percentage"),
        rl_session_reset=_first(d, "rate_limits.five_hour.resets_at"),
        rl_weekly_pct=_first(d, "rate_limits.seven_day.used_percentage"),
        rl_weekly_reset=_first(d, "rate_limits.seven_day.resets_at"),
        # Five alternate locations, first non-null wins.  Claude Code has moved
        # this field before and may again.
        pr_number=_first(d, "pr.number", "github.pr.number",
                         "github.pull_request.number", "github_pr.number",
                         "pull_request.number"),
    )


# ════════════════════════════════════════════════════════════════════════════
# Reading the transcript.
# ════════════════════════════════════════════════════════════════════════════

def _records(path: str):
    """Yield parsed JSONL records, skipping any line that will not parse.

    A transcript is appended to live, so the last line can be a partial write.
    Skipping is the only reasonable response; failing would blank the row for
    whichever frame caught the file mid-append.
    """
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                yield json.loads(line)
            except Exception:
                continue


def _dedupe_usage(records: Sequence[dict]) -> List[dict]:
    """Assistant records carrying usage, deduped FIRST-WINS on request id.

    Two reasons this matters, and the second is the one that gets forgotten:

      1. Claude Code writes one JSONL line per content block — thinking, text,
         each tool call — and repeats the whole usage object on every one.  A
         turn with ten parallel Reads writes twelve lines all claiming the same
         cache reads, so summing lines instead of requests inflates the total
         about fourfold.
      2. A RETRIED request appears again with the same id.  First-wins is what
         stops the retry being billed twice; last-wins or no dedupe both
         double-count it.

    Order-preserving, because callers below take the LAST non-sidechain entry
    and a re-sort would lose track of which request that was.
    """
    seen = set()
    out = []
    for r in records:
        if not (r.get("message") or {}).get("usage"):
            continue
        k = r.get("requestId") or (r.get("message") or {}).get("id") or "?"
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _agent_dir(transcript: str) -> str:
    """Where Claude Code keeps this session's agent transcripts.

    `<project>/<sid>.jsonl` is the session; `<project>/<sid>/subagents/` is
    everything it spawned.  "" for a path that is not a transcript at all.
    """
    if not transcript.endswith(".jsonl"):
        return ""
    return os.path.join(transcript[:-len(".jsonl")], "subagents")


def agent_files(transcript: str) -> List[str]:
    """Every agent transcript of this session, sorted so the walk is stable.

    Two depths and no others, measured over 2,134 files on 2026-09-11:
    `subagents/agent-<id>.jsonl` for the Agent tool, forks, and agents that
    agents spawned (those carry parentAgentId in their sidecar and sit in
    the same directory); `subagents/workflows/wf_<id>/agent-<id>.jsonl` for
    a workflow's agents.  The workflow's `journal.jsonl` beside them carries
    no usage and is not matched.
    """
    d = _agent_dir(transcript)
    if not d or not os.path.isdir(d):
        return []
    return sorted(glob.glob(os.path.join(d, "**", "agent-*.jsonl"),
                            recursive=True))


def agent_records(transcript: str, seen: Optional[set] = None,
                  etas: Optional[list] = None) -> Tuple[AgentRec, ...]:
    """Every billed request an agent of this session made, in stamp order.

    Nothing an agent bills is in the session's own transcript.  The main file
    carried `isSidechain: true` records once; across 231 transcripts on this
    machine it now carries none, and the agent work — 8% of all spend here,
    and most of it in the sessions that use agents at all — is in the files
    agent_files lists.  Every reader that adds up a transcript reads these
    through here as well, or it is reading the main thread and calling it
    the session.

    WHICH TURN each record belongs to is the `promptId` of the main-transcript
    turn that spawned the agent, and it is on the agent's USER records, not
    its assistant ones (0 of 19,408 assistant records carry it).  An agent
    that a later turn resumed with SendMessage gets a second user record
    with that later turn's id — 384 files here carry more than one — so the
    id is carried forward record by record, never taken once per file.
    read_turns resolves it against the id on every main record it read,
    tool results included; where no main record carries it — a workflow
    prompts its agents under ids of its own — the stamp decides instead.

    Skipped: records whose usage is all zero.  804 here are
    `model: "<synthetic>"` API-error placeholders, each with its own
    requestId, and counting them would inflate the call counts by 4% for
    nothing billed.

    Deduped first-wins on requestId across every file together, and against
    the main transcript when the caller passes its `seen` set: a retried
    request is the same request wherever it was retried.

    `offset` is the byte position after the record's own line.  It is what
    the Stop hook stores to say "I have reported everything up to here" —
    see agent_offsets — and it is bytes rather than a stamp because files
    that flush on their own schedules share no clock.

    It fed the status line's clocks as well until 2026-09-27, when ⌛ became
    the main thread's own — see thread_clock — and an agent's time moved to
    its row alone.  The receipt still wants it, so each record carries the
    agent's 🤖 and 🔧 since the one before it, by thread_clock's rule; see
    split_clock.  For a finished agent they add up to its own clock, and
    each second is filed with the request after it.  A
    record deduped away hands its time on to the next one this file keeps.

    `etas` is an out-parameter, because this walk already parses every
    line: for every agent still answering with a live ETA, (finish epoch,
    its last record's epoch) — see live_eta — which the status line's ⛳
    takes the latest of.

    Each file's own part of this is _read_agent_file's, and is kept between
    renders by _agent_file_readings; the dedup and the clock cut above are
    redone on every call, since what one file keeps depends on the others.
    """
    seen = set() if seen is None else seen
    out = []
    files = _agent_file_readings(transcript)
    for path, got in files:
        first = len(out)
        for epoch, pid, model, fresh, cw, cr, o, k, pos in got["recs"]:
            if k in seen:
                continue
            seen.add(k)
            if not (fresh or cw or cr or o):
                continue
            out.append(AgentRec(epoch, pid, model, fresh, cw, cr, o, k,
                                path, pos))
        if etas is not None and got["eta"] is not None:
            etas.append(tuple(got["eta"]))
        cuts, cut = [], float("-inf")
        for a in out[first:]:
            cut = max(cut, a.epoch) if a.epoch is not None else cut
            cuts.append(cut)
        for i, (m, tl) in enumerate(split_clock(got["work"], got["tools"],
                                                got["waiting"], cuts)):
            out[first + i] = out[first + i]._replace(model_s=m, tool_s=tl)
    # Stamp order across files, unparseable stamps last: the fold-in walks
    # turns forward and a record that cannot be placed in time is handed to
    # the last turn rather than the first.
    out.sort(key=lambda a: (a.epoch is None, a.epoch or 0.0))
    return tuple(out)


def _read_agent_file(path: str) -> Optional[dict]:
    """One agent file's part of agent_records, read from it alone.

    Everything here depends on this file's bytes and nothing else, which is
    what lets _agent_file_readings keep it from one render to the next.  So
    it stops short of the two steps that look across files: `recs` holds
    every record that carries usage, zero bills and repeated requestIds
    included, as (epoch, promptId, model, fresh, cache write, cache read,
    out, requestId, offset), and agent_records dedupes them against the
    session and cuts the clock at the ones it keeps.  `work`, `tools` and
    `waiting` are that clock's spans, and `eta` is the file's live ETA as
    agent_records hands it on, or None.  None for a file that will not open.
    """
    pid = ""
    eta_state = new_eta_state()
    span_state: list = [None, None]
    work: List[Tuple[float, float]] = []
    pending: Dict[str, Tuple[float, str]] = {}
    tools: List[Tuple[float, float]] = []
    waiting: List[Tuple[float, float]] = []
    recs = []
    try:
        fh = open(path, "rb")
    except OSError:
        return None
    with fh:
        pos = 0
        for line in fh:
            pos += len(line)
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not isinstance(r, dict):
                continue
            live_eta(r, eta_state)
            agent_span(r, span_state, work)
            scan_tool_spans(r, pending, tools, waiting)
            if r.get("type") == "user":
                pid = r.get("promptId") or pid
                continue
            if r.get("type") != "assistant":
                continue
            m = r.get("message") or {}
            u = m.get("usage")
            if not u:
                continue
            recs.append((ts_epoch(r.get("timestamp") or ""), pid,
                         m.get("model"), u.get("input_tokens") or 0,
                         u.get("cache_creation_input_tokens") or 0,
                         u.get("cache_read_input_tokens") or 0,
                         u.get("output_tokens") or 0,
                         r.get("requestId") or m.get("id") or "?", pos))
    close_agent_span(span_state, work)
    eta = None
    if eta_state[0] and not eta_state[1]:
        eta = (eta_finish(eta_state[0]), eta_state[2])
    return {"recs": recs, "work": work, "tools": tools, "waiting": waiting,
            "eta": eta}


# A file last written this long ago is SETTLED, and only a settled file's
# reading is kept.  Size and mtime are the whole test for a kept reading
# being current, and a file rewritten within the clock's granularity — a
# few milliseconds on Linux, whose mtime is the coarse clock — can come
# back the same size with the same stamp.  Git's index has the same race
# and the same cure: a stamp the writer may still share is not trusted.
# A live agent's file is never settled while it runs, and is read afresh.
AGENT_CACHE_SETTLE_S = 2.0


def _agent_cache_path(transcript: str) -> str:
    """Where agent_records keeps its readings of this session's agent files.

    Not .json: state.find_compatible reads every .json in the directory as
    a usage cache, and this one holds megabytes on a long session.
    """
    sid = os.path.basename(transcript)
    if sid.endswith(".jsonl"):
        sid = sid[:-len(".jsonl")]
    digest = hashlib.sha256(("claude-agent-files\0" + sid).encode("utf-8")).hexdigest()
    return os.path.join(state.state_dir(), "claude-agent-files-" + digest + ".cache")


@functools.lru_cache(maxsize=1)
def _agent_cache_version() -> str:
    """A digest of this package's source, so a reading kept by one version
    of the parsing is never served to another.  Every rule _read_agent_file
    leans on — live_eta's, agent_span's, scan_tool_spans' — lives in it, and
    a hand-bumped number would be forgotten the first time one changed."""
    h = hashlib.sha256()
    d = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(os.listdir(d)):
        if name.endswith(".py"):
            try:
                with open(os.path.join(d, name), "rb") as fh:
                    h.update(name.encode("utf-8") + b"\0" + fh.read())
            except OSError:
                pass
    return h.hexdigest()


def _agent_file_readings(transcript: str) -> List[Tuple[str, dict]]:
    """_read_agent_file for every agent file, in agent_files' order, from
    the cache where a file has not changed since it was kept.

    Without it, every render parsed every agent file the session ever ran.
    A session with 611 of them, 768 MB, took six seconds a render, longer
    than Claude Code's five-second refresh, and its status line stopped at
    the last frame that finished: on 2026-10-01 it held a 98٪ weekly figure
    for hours after the week had reset to 1٪.  A finished agent's file
    never changes, so a render now reads only the files that grew.

    A reading is current while the file's size and mtime match the ones
    stamped when it was read; see AGENT_CACHE_SETTLE_S for why only a
    settled file is kept.  The file is written back only when a reading was
    added or a file went away, so a session with nothing new costs one read.
    """
    paths = agent_files(transcript)
    if not paths:
        return []
    cpath = _agent_cache_path(transcript)
    version = _agent_cache_version()
    kept: dict = {}
    try:
        with open(cpath, "r") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and d.get("version") == version:
            kept = d.get("files") or {}
    except (OSError, ValueError):
        pass
    settled = time.time() - AGENT_CACHE_SETTLE_S
    out = []
    keep = {}
    dirty = False
    for path in paths:
        try:
            st = os.stat(path)
        except OSError:
            continue
        stamp = [st.st_size, st.st_mtime_ns]
        got = kept.get(path)
        if isinstance(got, dict) and got.get("stamp") == stamp:
            got = {"recs": [tuple(r) for r in got["recs"]],
                   "work": [tuple(w) for w in got["work"]],
                   "tools": [tuple(t) for t in got["tools"]],
                   "waiting": [tuple(w) for w in got["waiting"]],
                   "eta": got["eta"]}
            keep[path] = kept[path]
        else:
            # Stamped before the read: a file that grows during it comes
            # back with a newer stamp next time, and is read again.
            got = _read_agent_file(path)
            if got is None:
                continue
            if st.st_mtime < settled:
                keep[path] = dict(got, stamp=stamp)
                dirty = True
        out.append((path, got))
    if dirty or set(kept) != set(keep):
        try:
            os.makedirs(os.path.dirname(cpath), mode=0o700, exist_ok=True)
            tmp = "%s.%d" % (cpath, os.getpid())
            with open(tmp, "w") as fh:
                json.dump({"version": version, "files": keep}, fh,
                          separators=(",", ":"))
            os.chmod(tmp, 0o600)
            os.replace(tmp, cpath)
        except OSError:
            pass
    return out


def _usd(model: Optional[str], fresh: int, cw: int, cr: int, out: int
         ) -> Tuple[float, float, float, float]:
    """One record's bill, split four ways, at its own model's rates."""
    pi, po, pr, pw = _price(model)
    return fresh * pi, out * po, cr * pr, cw * pw


# Pictographs whose DEFAULT PRESENTATION IS TEXT, as sorted ranges.
#
# EAW_WIDE above blankets 1F300-1FBFF as two columns, and that blanket is
# wrong for about 1,600 codepoints in it.  UAX #11 gives Wide to a pictograph
# whose default presentation is emoji and Neutral to the rest, so this table
# is the blanket's exceptions: 🛢 U+1F6E2, 🕰 U+1F570, 🗓, 🗑, 🎟, 🌡 and the
# rest of that family.  With no emoji presentation they are drawn from
# whatever text font the terminal reaches for — one column in some, two in
# others, and 🛢 and 🕰 disagree with each other on the SAME terminal.
#
# It is not used to measure anything.  vis_width still trusts the blanket,
# because everything this file PRINTS is chosen to be emoji-presentation and
# the blanket is right for all of it.  This table is used by squash, to
# escape the ones that turn up in chat text, where nobody vets the glyphs.
#
# 1F1E6-1F1FF, the regional indicators, are in here for a different reason
# and belong: a flag is two of them, four columns where clusters are not
# folded and two where they are — the terminal decides, so it cannot be
# measured either.
#
# Generated from unicodedata (UCD 15.0.0), which is the right authority for this
# one question: what is asked is the codepoint's declared presentation, not
# what some terminal does with it.  KEEP IT SORTED — the scan stops at the
# first range starting above the codepoint.
EAW_TEXT_PRES = (
    (126976, 126979), (126981, 127182), (127184, 127373), (127375,
    127376), (127387, 127487), (127491, 127503), (127548, 127551),
    (127561, 127567), (127570, 127583), (127590, 127743), (127777,
    127788), (127798, 127798), (127869, 127869), (127892, 127903),
    (127947, 127950), (127956, 127967), (127985, 127987), (127989,
    127991), (128063, 128063), (128065, 128065), (128253, 128254),
    (128318, 128330), (128335, 128335), (128360, 128377), (128379,
    128404), (128407, 128419), (128421, 128506), (128592, 128639),
    (128710, 128715), (128717, 128719), (128723, 128724), (128728,
    128731), (128736, 128746), (128749, 128755), (128765, 128991),
    (129004, 129007), (129009, 129291), (129339, 129339), (129350,
    129350), (129536, 129647), (129661, 129663), (129673, 129679),
    (129726, 129726), (129734, 129741), (129756, 129759), (129769,
    129775), (129785, 130047),
)


def _text_pres(cp: int) -> bool:
    """Is this a pictograph the terminal will draw from a TEXT font?

    The table is sorted, so the scan stops at the first range starting above
    the codepoint — the same walk vis_width does.
    """
    for lo, hi in EAW_TEXT_PRES:
        if cp < lo:
            return False
        if cp <= hi:
            return True
    return False


def squash(s: str, fold: str = E_FOLD) -> str:
    """Make chat text safe to measure, and flatten it to one line.

    Chat text is the one part of the row nobody vets: it is whatever was said,
    and a single glyph whose width this file guesses wrong drags the whole
    metric block out of line — or pushes the row past the margin, where Ink
    cuts it off.

    So the glyphs that cannot be trusted are replaced by their codepoint in
    ASCII: <27F3> in place of a reset arrow.  That is wider than the glyph, but
    it is ASCII, so its width is exact and the row can be measured to the
    column.  It also SAYS what was there, which a dot did not — a row reading
    <1FAA3> is a bug report, where a row reading a dot is only a mystery.

    Two families qualify.  U+2190-U+2BFF is arrows, misc technical, misc
    symbols and dingbats, where terminals disagree glyph by glyph and a
    neighbouring codepoint is no guide.  Variation selectors are the other,
    being the construction behind every rendering fault recorded in this file.

    Pictographs used to be left alone wholesale, on the claim that everything
    from U+1F300 up measures two columns in both terminals.  That was wrong,
    and 🛢 U+1F6E2 is how it was found out: a pictograph with no default emoji
    presentation is drawn from whatever text font the terminal reaches for,
    which is one column in some and two in others — the same fault as the
    U+2190 block, in a range this function trusted.

    The test that separates them is already in the file.  UAX #11 gives East
    Asian Width Wide to pictographs whose default presentation is emoji and
    Neutral to the rest, so a pictograph MISSING from EAW_WIDE is exactly one
    whose width cannot be trusted — 🛢, 🕰, 🗓, 🗑, 🎟, 🌡 and about 1,600
    others.  Escaping by the table also means the two stay in step: a glyph
    this file cannot measure is a glyph it will not print.

    Regional indicators fall out of the same test and should.  A flag is two
    of them, drawn as one glyph by a terminal that folds clusters and two by
    one that does not — four columns against two, decided by the terminal.
    """
    out = []
    for ch in s:
        cp = ord(ch)
        if (8592 <= cp <= 11263) or (65024 <= cp <= 65039) \
                or _text_pres(cp):
            out.append("<%X>" % cp)
        else:
            out.append(ch)
    t = "".join(out).replace("\n", fold).replace("\t", " ")
    return re.sub(" +", " ", t)


@functools.lru_cache(maxsize=256)
def ts_epoch(ts: str) -> Optional[float]:
    """A transcript timestamp as a Unix epoch, or None if it is not one.

    Transcript stamps are UTC with a trailing "Z", which 3.9's fromisoformat
    rejects outright — hence strptime on a stripped string with the zone
    reattached, the same dance elapsed_short does.

    Cached, because one walk hands each record's stamp to several scans in a
    row (its ETA, its span, its tool calls, its bill), and strptime was most
    of agent_records' own time.
    """
    if not ts:
        return None
    try:
        return datetime.strptime(ts.split(".")[0].rstrip("Z"),
                                 "%Y-%m-%dT%H:%M:%S").replace(
                                     tzinfo=_UTC).timestamp()
    except ValueError:
        return None


def _stamp_utc(epoch: Optional[float]) -> str:
    """ts_epoch's inverse: a transcript-shaped UTC stamp, "" for None."""
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch, _UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _agent_state_path(transcript: str) -> str:
    """Where the Stop hook records how far into each agent file it reported.

    Per session, in private application state.  A one-way digest keeps a raw
    transcript/session id out of the path while preserving the hook's scope.
    """
    sid = os.path.basename(transcript)
    if sid.endswith(".jsonl"):
        sid = sid[:-len(".jsonl")]
    digest = hashlib.sha256(("claude-agent-offsets\0" + sid).encode("utf-8")).hexdigest()
    return os.path.join(state.state_dir(), "claude-agent-offsets-" + digest + ".json")


def agent_offsets(transcript: str) -> Optional[Dict[str, int]]:
    """The byte offset the last Stop reported each agent file up to, or None
    when no Stop has written one for this session.  See _fold_agents for
    what the distinction buys."""
    try:
        with open(_agent_state_path(transcript), "r") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    return {k: v for k, v in d.items()
            if isinstance(k, str) and isinstance(v, int)}


def publish_agent_offsets(transcript: str,
                          agents: Sequence[AgentRec]) -> None:
    """Record, after a Stop has rendered, how far into each agent file the
    records it folded in reached.

    Written from the records themselves rather than from the files' sizes,
    so that what is stored is exactly what was reported: the hook reads the
    agent files once, renders from that reading, and stores that reading's
    extent.  A file that grew between the read and this write is reported
    next time from where this reading stopped, which is the whole point.
    Files with no billed record yet are absent, and absent reads as 0.
    """
    ext = {}
    for a in agents:
        if a.offset > ext.get(a.path, 0):
            ext[a.path] = a.offset
    path = _agent_state_path(transcript)
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        tmp = "%s.%d" % (path, os.getpid())
        with open(tmp, "w") as fh:
            json.dump(ext, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        pass


def union_seconds(spans: Sequence[Tuple[float, float]]) -> float:
    """The length of the UNION of `spans`, in seconds.

    Overlapping spans are merged rather than added, which is the whole reason
    this is not a sum: five agents working the same ten minutes is ten minutes
    of the session's clock, not fifty.  The alternative — summing — makes 🤖
    exceed Σ the moment anything runs in parallel and turns 🚦 into a
    permanent zero, and the pair's only claim is that it splits the age.
    """
    total = 0.0
    cur = None
    for lo, hi in sorted(s for s in spans if s[1] > s[0]):
        if cur is None:
            cur = [lo, hi]
        elif lo <= cur[1]:
            cur[1] = max(cur[1], hi)
        else:
            total += cur[1] - cur[0]
            cur = [lo, hi]
    return total + (cur[1] - cur[0] if cur else 0.0)


# Tools whose result IS the user's answer, so their whole span is a person
# thinking rather than a machine working.
#
# These are counted as tools by every other reader — they are tool calls, and
# the transcript records them as tool calls — and they are taken out of 🔧
# and given to 🚦 because of what the cell is read for.  🔧 answers "how
# much of the working time was the machine waiting on a shell or a file";
# a dialog that sat open for ninety seconds while someone chose
# between two options is not that, and charging it to 🔧 made the cell
# report the reader's own deliberation back at them.  🚦 is already "time
# the session spent waiting for a person", which is exactly what this is.
#
# BY NAME, and only by name, because the name is the only thing in the
# transcript that says so.  A permission prompt has the same shape — a tool
# whose result arrives whenever the person gets round to approving it — and
# is NOT excluded: any tool can sit on one, nothing in the record marks it,
# and a Bash call that waited two minutes for approval did stall the turn
# somewhere the reader can act on.  What this set can name is the tools that
# are a question and nothing else.
BLOCKING_TOOLS = frozenset({"AskUserQuestion", "ExitPlanMode"})

# Tools whose span is ANOTHER AGENT's work: the thread that called one is
# waiting on the agent, not running a tool, and that agent's time is on its
# own row.  Both names, because Claude Code renamed Task to Agent and older
# transcripts still say Task.  A background dispatch returns at once, so its
# span is a second or two either way; a foreground one is the child's whole
# run, and without this it was the caller's 🔧.  See thread_clock.
DELEGATING_TOOLS = frozenset({"Agent", "Task"})

# What a thread's 🚦 takes out of its tool spans: a person answering, or
# another agent working.  Neither is this thread's machine doing anything.
WAITING_TOOLS = BLOCKING_TOOLS | DELEGATING_TOOLS


def scan_tool_spans(r: dict, pending: Dict[str, Tuple[float, str]],
                    out: List[Tuple[float, float]],
                    blocked: Optional[List[Tuple[float, float]]] = None
                    ) -> None:
    """Fold one record into a running scan for (start, end) of every tool call.

    A tool's clock starts on the ASSISTANT record that asked for it and stops
    on the `tool_result` that answers it, matched by `tool_use_id` — never by
    adjacency.  Adjacency is wrong here: one assistant record can carry four
    `tool_use` blocks that run at once and land in any order, and pairing them
    off in file order would hand each the wrong end.  The ids are always
    there — 106 of 106 results in the session this was written from paired,
    none dangling — and a result whose id names no call it has seen is simply
    not counted, which is the right answer for a transcript that was resumed
    mid-call.

    The span is the whole time the thread was inside the tool: the wait for a
    permission prompt is in it, because a turn that sat on a dialog for two
    minutes did spend two minutes not thinking.  And a Task's span is its
    agent's ENTIRE run, which is what makes the fold below recursive for
    free — an agent that ran ten minutes inside a Task contributes those ten
    minutes once, whether they are read here or off the agent's own file.

    `pending` and `out` are the caller's, so one walk of a file can feed this
    and the billing scan beside it; see agent_records.  `blocked` is the
    caller's too and takes the SUBSET of `out` whose tool is in
    WAITING_TOOLS — a subset and not a partition, so a reader that wants
    the machine's tool time alone subtracts one union from the other and
    needs no interval arithmetic of its own; see net_tool_seconds.
    """
    t = ts_epoch(r.get("timestamp") or "")
    if t is None:
        return
    blocks = (r.get("message") or {}).get("content")
    if not isinstance(blocks, list):
        return
    for b in blocks:
        if not isinstance(b, dict):
            continue
        kind = b.get("type")
        if kind == "tool_use":
            if b.get("id"):
                pending[str(b["id"])] = (t, str(b.get("name") or ""))
        elif kind == "tool_result":
            hit = pending.pop(str(b.get("tool_use_id") or ""), None)
            if hit is not None and t > hit[0]:
                out.append((hit[0], t))
                if blocked is not None and hit[1] in WAITING_TOOLS:
                    blocked.append((hit[0], t))


def tool_spans(records: Sequence[dict],
               blocked: Optional[List[Tuple[float, float]]] = None
               ) -> List[Tuple[float, float]]:
    """Every tool call in `records`, as (start, end).  See scan_tool_spans."""
    pending: Dict[str, Tuple[float, str]] = {}
    out: List[Tuple[float, float]] = []
    for r in records:
        scan_tool_spans(r, pending, out, blocked)
    return out


# The terminal states a TaskOutput reading can report for the task it read.
TASK_ENDED = frozenset({"completed", "failed", "killed", "stopped"})


def notification_text(r: dict) -> str:
    """The `<task-notification>` a record delivers, or "".

    An agent's file holds one as a `queued_command` attachment; a thread
    Claude Code woke with it holds a plain user record whose content is the
    notification itself.
    """
    a = r.get("attachment") or {}
    c = a.get("prompt") if a.get("type") == "queued_command" else (
        (r.get("message") or {}).get("content") if r.get("type") == "user"
        else None)
    if isinstance(c, list):
        c = "".join(b.get("text") or "" for b in c if isinstance(b, dict))
    return c if isinstance(c, str) and "<task-notification>" in c else ""


def scan_background(r: dict, open_: Dict[str, str]) -> None:
    """Fold one record into `open_`, {task id: "bash" or "monitor"}, the
    background tasks a thread started and has not heard the end of.

    These are what keep an agent that ended its turn alive while it waits:
    Claude Code parks it on `bash:<id>` or `monitor:<id>` and marks it
    completed, and the payload carries neither.  A task opens on the tool
    result that hands back its id — a Bash run in the background, or one
    that outran its timeout and was moved there, says `backgroundTaskId`,
    and a Monitor says `taskId` beside its `timeoutMs`.  It closes on a
    `<task-notification>` for that id that carries a `<status>`: a Monitor
    sends one per event with no status, and a last one with it when its
    stream ends.  Or on the thread ending it itself — TaskStop's result, or
    TaskOutput reading it finished, which Claude Code counts as delivered
    and sends no notification for.
    """
    res = r.get("toolUseResult")
    if isinstance(res, dict):
        if res.get("backgroundTaskId"):
            open_[str(res["backgroundTaskId"])] = "bash"
        elif res.get("taskId") and "timeoutMs" in res:
            open_[str(res["taskId"])] = "monitor"
        elif res.get("task_id") and "message" in res:
            open_.pop(str(res["task_id"]), None)
        task = res.get("task")
        if isinstance(task, dict) and task.get("status") in TASK_ENDED:
            open_.pop(str(task.get("task_id") or ""), None)
    text = notification_text(r)
    if text and "<status>" in text:
        m = re.search(r"<task-id>([^<]+)</task-id>", text)
        if m:
            open_.pop(m.group(1).strip(), None)


def net_tool_seconds(spans: Sequence[Tuple[float, float]],
                     blocked: Sequence[Tuple[float, float]]) -> float:
    """Seconds inside a tool that were not waiting on someone else.

    A subtraction of two unions rather than an interval difference, and it is
    exact because `blocked` is a SUBSET of `spans`: the measure of a set less
    the measure of a subset is the measure of what is left, whatever either
    one overlaps.  Which matters — a question asked on the main thread can
    run straight through an agent's tool call, and those two spans have to
    come out as one second each, not two.
    """
    return max(0.0, union_seconds(spans) - union_seconds(blocked))


def open_tool_spans(pending: Dict[str, Tuple[float, str]], now: float,
                    tools: List[Tuple[float, float]],
                    waiting: List[Tuple[float, float]]) -> None:
    """Run every tool call still waiting on its result on to `now`.

    `pending` is what scan_tool_spans has left unanswered at the end of a
    file: a Bash call still running, an agent still working in the
    foreground.  Its seconds are 🔧's — or 🚦's, for a WAITING_TOOLS call —
    as they happen, and not only once the result lands; left out, they sat
    in 🚦 as the remainder until then, so a thread ten minutes into a test
    run read as ten minutes waiting.  The caller passes a `now` only for a
    thread that is live: a finished one's unanswered calls were interrupted.
    """
    for t, name in pending.values():
        if now > t:
            tools.append((t, now))
            if name in WAITING_TOOLS:
                waiting.append((t, now))


def thread_clock(work: Sequence[Tuple[float, float]],
                 tools: Sequence[Tuple[float, float]],
                 waiting: Sequence[Tuple[float, float]]
                 ) -> Tuple[float, float, float]:
    """One thread's (busy, tool, waiting) seconds, off its OWN file alone.

    The status line reads the main thread through this and each agent row
    reads its agent, so ⌛ 🤖 🔧 🚦 mean the same thing on both: what THIS
    thread did with its time.  `work` is its working spans, `tools` every
    tool call it made and `waiting` the WAITING_TOOLS subset of those.

      busy     the union of its work and its tools
      tool     its tool spans, less the ones that were waiting
      waiting  the waiting spans

    so that busy - tool - waiting is 🤖, the model thinking, and the age less
    busy, plus waiting, is 🚦.  The three partition the age exactly: 🤖 holds
    no tool second, 🔧 no waiting one, and 🚦 is the rest by construction.

    OWN FILE ALONE, since 2026-09-27.  The status line unioned every agent's
    spans into its busy clock until then, and an agent row added its
    children's tools to its 🔧, so a coordinator parked on five background
    agents read as busy the whole time it sat waiting on them.  Waiting on an
    agent is 🚦 now, on either readout, and the agent's work is on its row.
    """
    return (union_seconds(list(work) + list(tools)),
            net_tool_seconds(tools, waiting), union_seconds(waiting))


def split_clock(work: Sequence[Tuple[float, float]],
                tools: Sequence[Tuple[float, float]],
                waiting: Sequence[Tuple[float, float]],
                cuts: Sequence[float]) -> List[Tuple[float, float]]:
    """thread_clock's 🤖 and 🔧, cut into one (model, tool) pair per cut.

    Pair i is the time after cut i-1 and up to cut i.  Nothing after the
    last cut is in any pair: agent_records cuts an agent's clock at each
    billed request, so its seconds can be filed under a turn the way its
    tokens are, and a stretch past the last request is time the NEXT one
    will bill.  Handed to the last one instead, it printed on that request's
    row at one Stop and on the next request's at the following Stop.  A
    finished agent's clock ends on its last request, so its pairs add up to
    thread_clock's `busy - tool - waiting` and `tool`; an interrupted one's
    tail is in none, as an unanswered call is in no offline read.  `cuts`
    must be in order.

    A sweep rather than thread_clock per cut: 🤖 is the work spans less the
    tool spans, and 🔧 the tool spans less the waiting ones, so each stretch
    between two span ends is one or the other or neither by what is open
    across it.
    """
    out = [[0.0, 0.0] for _ in cuts]
    if not cuts:
        return []
    ev = sorted((edge, k, d)
                for k, spans in enumerate((work, tools, waiting))
                for lo, hi in spans if hi > lo
                for edge, d in ((lo, 1), (hi, -1)))
    live = [0, 0, 0]
    prev = None
    j = 0
    for t, k, d in ev:
        lo = prev if prev is not None else t
        while lo < t:
            while j < len(cuts) - 1 and cuts[j] <= lo:
                j += 1
            if cuts[j] <= lo:
                break
            hi = min(t, cuts[j])
            if live[1] and not live[2]:
                out[j][1] += hi - lo
            elif live[0] and not live[1]:
                out[j][0] += hi - lo
            lo = hi
        live[k] += d
        prev = t
    return [(m, tl) for m, tl in out]


def turn_clock(tools: Sequence[Tuple[float, float]],
               waiting: Sequence[Tuple[float, float]],
               t0: Optional[float], t1: Optional[float]
               ) -> Tuple[float, float]:
    """One turn's (tool, waiting) seconds: thread_clock's two, over its span.

    The receipt's ⌛🤖 and 🔧 are the status line's 🤖 and 🔧 read over one
    turn rather than the whole session, and they come off the same scan —
    `tools` and `waiting` are what scan_tool_spans collected while this turn
    was open — so a session's 🎮 row and its status line agree second for
    second wherever every call returns inside the turn that made it and no
    compaction lands mid-answer; see read_turns for why a compaction's turn
    carries no tool time.

    Clipped to [t0, t1], because the turn's own span is what dur_s measures
    and what 🤖 is the remainder of.  A tool_result is `is_work`, so a call
    already ends inside the turn it returns in; the clip is for one that did
    not START there — asked for before the prompt its result arrived after —
    whose earlier seconds are in no turn's dur_s and would otherwise come
    out of this one's 🤖.
    """
    if t0 is None or t1 is None or t1 <= t0:
        return 0.0, 0.0

    def clip(spans: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
        return [(max(lo, t0), min(hi, t1)) for lo, hi in spans]

    tc, wc = clip(tools), clip(waiting)
    return net_tool_seconds(tc, wc), union_seconds(wc)


def turn_model_s(t: Turn) -> float:
    """The receipt's ⌛🤖: the turn's span less its tool and waiting seconds.

    The status line's 🤖, over one turn — the model thinking, and nothing a
    shell, a question or a dispatched agent held it up for.  Clamped at zero
    for the reason render_elapsed clamps its own: a negative would say the
    three add up to more than the span they split.
    """
    return max(0.0, t.dur_s - t.tool_s - t.blocked_s)


def turn_times(t: Turn) -> Tuple[float, float]:
    """The receipt's ⌛🤖 and 🔧 for a row: the main thread's, plus its agents'.

    A row's tokens and dollars count the agent requests filed under it, so
    its time does too, by the same filing; see split_clock.  The waiting
    calls stay out of both, so an agent's run is counted once, off its own
    file, and not a second time as the thread that dispatched it sitting on
    it.  Agents run beside each other and beside the answer, so these are
    agent-seconds rather than wall-clock: a row can read more than its turn
    took, and the 🎮 total is the status line's 🤖 and 🔧 plus every agent's.
    """
    return (turn_model_s(t) + t.agent_model_s, t.tool_s + t.agent_tool_s)


# The skill that has an agent report its ETA, and the line it has it write:
#
#     ⛳ skills/coding-agent-usage-line-report-eta: ETA 4m
#
# The skill's path is the part matched, so the line says where it comes from
# to anyone who searches for it; the flag is for the eye and may be missing,
# and the 🏁 the skill had it write before ⛳ is read as well.
# Backticks and bold around the line are forgiven, since a model shown the
# line in a code block will sometimes write it back in one.  The skill's own
# text writes `<number>` where the figure goes, so loading it into a
# transcript never matches.  The skill asks for one figure and one unit,
# and an agent with hours left writes `6h30m` all the same; read as the
# skill's form alone, that line matched nothing and the row kept counting
# down an older report, so a run of figure-and-unit pairs is one figure.
ETA_SKILL = "coding-agent-usage-line-report-eta"
ETA_PART = r"\d+(?:\.\d+)? ?[smh]"
ETA_LINE = re.compile(
    r"^[ \t`*]*(?:[%s%s][ \t]*)?skills/%s: ETA (%s(?:[ \t]*%s)*)[ \t`*]*$"
    % (E_ETA_REPORT, E_ETA_REPORT_OLD, re.escape(ETA_SKILL), ETA_PART, ETA_PART), re.MULTILINE)
ETA_SPLIT = re.compile(r"(\d+(?:\.\d+)?) ?([smh])")
ETA_UNIT_S = {"s": 1.0, "m": 60.0, "h": 3600.0}


def eta_report(records: Sequence[dict]) -> Tuple[float, ...]:
    """(epoch, seconds left) off the LAST ETA report in `records`, or ().

    The agent panel reads an agent's whole file with this; the status line
    reads the main thread's current turn (read_transcript).  Only what the
    agent itself wrote counts: the text blocks of assistant
    records.  A tool result that quotes the line — a grep of this very
    file, say — or the skill's text arriving as a user message is not a
    report, and matching the raw JSONL would take either for one.  The
    epoch is the record's own stamp, which is what lets the row count the
    estimate down between reports.
    """
    last: Tuple[float, ...] = ()
    for r in records:
        if not isinstance(r, dict) or r.get("type") != "assistant":
            continue
        content = (r.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            hits = ETA_LINE.findall(str(block.get("text") or ""))
            epoch = ts_epoch(r.get("timestamp") or "")
            if hits and epoch is not None:
                last = (epoch, sum(float(n) * ETA_UNIT_S[unit]
                                   for n, unit in ETA_SPLIT.findall(hits[-1])))
    return last


def eta_finish(eta: Tuple[float, ...]) -> Optional[float]:
    """When an ETA says its run ends: the report's epoch plus the time it said
    was left.  None only for no report.  A report of zero is the skill's
    sign-off, and says the run ends at the report: a run still going after
    it is late, the same as one past any other estimate."""
    if not eta:
        return None
    return eta[0] + eta[1]


def ends_turn(r: dict) -> bool:
    """True for an assistant record that ends its answer."""
    return (r.get("type") == "assistant" and
            (r.get("message") or {}).get("stop_reason") == "end_turn")


def new_eta_state() -> list:
    """A fresh `state` for live_eta: no report, not done, no stamp, no
    message."""
    return [(), False, None, None]


def live_eta(r: dict, state: list) -> None:
    """Fold one record into `state`, [eta, done, last epoch, report's
    message id], for one thread.

    The ETA belongs to the answer it was written in: a new prompt clears it,
    and so does the answer finishing — an assistant record that ends its
    turn, with no work after it.  A report from an answer that is over is
    not an estimate of anything still running.

    Unless the message that ends the turn is the one that carries the report.
    That is an agent PARKING rather than finishing: it has ended its turn to
    wait on a background task, whose notification will wake it, and says in
    the same breath how long it expects the rest to take.  Claude Code
    marks such an agent completed; the report is the only thing that says
    it is not.  The skill has a finished agent sign off with 0s, so a 0s in
    the message that ends the turn is finishing, not parking; and one that
    ends without a line in its last message reads as finished too.  A 0s
    written mid-answer stays live, so work after it reads as late.  A
    message is split over several records, one per block, so the test is on
    the message id and not on the record.
    """
    if turn_start_text(r) is not None:
        state[0], state[1], state[3] = (), False, None
    elif is_work(r):
        report = eta_report([r])
        mid = (r.get("message") or {}).get("id")
        if report:
            state[0], state[3] = report, mid
        parked = bool(state[0]) and state[0][1] > 0 and (
            bool(report) or (mid is not None and mid == state[3]))
        state[1] = ends_turn(r) and not parked
    t = ts_epoch(r.get("timestamp") or "")
    if t is not None:
        state[2] = t


def agent_span(r: dict, state: list, spans: list) -> None:
    """Fold one record of an AGENT's file into its working spans.

    `state` is [opened at, last work], both None between spans; a span is
    appended to `spans` as it closes, and the caller closes the last one —
    see close_agent_span.  A span runs from the record that opens it to the
    last record its answer produced, as read_transcript's turns do.

    What differs from the main thread is what opens and closes one.  An
    agent's resumptions are not prompts: a message SendMessage delivers to
    a finished agent, or a background task's notification waking a parked
    one, is written as a plain user record that turn_start_text does not
    recognise.  Read the main thread's way, a resumed agent's file was one
    span from its spawn to now, and every hour it sat finished or parked
    was charged to it as work.  So an answer that ENDS its turn closes the
    span, and whatever comes next opens the following one.  A prompt still
    closes and reopens it, for a file that has one.
    """
    t = ts_epoch(r.get("timestamp") or "")
    if t is None:
        return
    if state[0] is not None and turn_start_text(r) is not None:
        close_agent_span(state, spans)
    if state[0] is None:
        if r.get("type") not in ("user", "assistant"):
            return
        state[0] = state[1] = t
    elif is_work(r):
        state[1] = max(state[1], t)
    if ends_turn(r):
        close_agent_span(state, spans)


def close_agent_span(state: list, spans: list) -> None:
    """Append agent_span's open span, if it has any length, and clear it."""
    if state[0] is not None and state[1] > state[0]:
        spans.append((state[0], state[1]))
    state[0] = state[1] = None


def read_transcript(path: str, agents: Optional[Sequence[AgentRec]] = None,
                    agent_etas: Sequence[Tuple[float, Optional[float]]] = (),
                    now: Optional[float] = None) -> Transcript:
    """One pass for the status line: totals, cache rate, context, last texts.

    The token totals and the cache rate count what the session's AGENTS
    billed as well — `agents` is agent_records' reading of the files beside
    the transcript, or None to read them here — because it was billed, and
    a 🧩 that reports the main thread alone is short by whatever the forks
    and workflows spent, which in the sessions that use them is most of it.

    Time does NOT, since 2026-09-27: busy, tool and waiting time are this
    thread's own, off this file alone — see thread_clock, which an agent row
    reads its agent through too.  A main thread that dispatches six agents
    and waits is waiting, and says so in 🚦; the agents' work is on their
    rows.  The clocks unioned every agent's spans in until then, which read
    a coordinator parked on its agents as the busiest thread in the session.
    With a `now`, a tool call still running counts to it; see open_tool_spans.

    Context size does NOT.  It is a reading of THIS window — the one 🧠 is
    watched to decide when to compact — and every agent runs a window of its
    own that compacts, or does not, by itself.  Folding those in would make
    the main thread's occupancy jump as agents come and go and say nothing
    about when this session needs a /compact.  The `isSidechain` guard on
    the reading below is belt-and-braces: agent records carry the flag, but
    they never reach this loop, which reads the main file alone.
    """
    records = list(_records(path))
    reqs = _dedupe_usage(records)
    fresh = cwrite = cread = down = 0
    for r in reqs:
        u = r["message"]["usage"]
        fresh += u.get("input_tokens") or 0
        cwrite += u.get("cache_creation_input_tokens") or 0
        cread += u.get("cache_read_input_tokens") or 0
        down += u.get("output_tokens") or 0
    if agents is None:                  # no caller-supplied walk: do it here,
        own_etas = []                   # and take the agents' ETAs off it too
        agents = agent_records(path, etas=own_etas)
        agent_etas = tuple(agent_etas) + tuple(own_etas)
    for a in agents:
        fresh += a.fresh
        cwrite += a.cache_write
        cread += a.cache_read
        down += a.out
    in_all = fresh + cwrite + cread

    ctx = 0
    for r in reqs:
        if r.get("isSidechain") is not True:
            u = r["message"]["usage"]
            # Skip a request whose usage is all zero.  That is how an
            # interrupted request is recorded, and letting it win the
            # last-write would blank the whole 🧠 cell on the status line for
            # the rest of the session.  See read_turns for the count.
            _c = ((u.get("input_tokens") or 0)
                  + (u.get("cache_creation_input_tokens") or 0)
                  + (u.get("cache_read_input_tokens") or 0))
            if _c:
                ctx = _c

    user_ts = user_text = asst_ts = asst_text = ""
    for r in records:
        c = (r.get("message") or {}).get("content")
        if (r.get("type") == "user" and r.get("userType") == "external"
                and isinstance(c, str) and len(c) > 0
                and not c.startswith("<")):
            user_ts, user_text = r.get("timestamp") or "", c
        if r.get("type") == "assistant":
            blocks = (r.get("message") or {}).get("content") or []
            if isinstance(blocks, list):
                texts = [b for b in blocks
                         if isinstance(b, dict) and b.get("type") == "text"]
                if texts:
                    asst_text = texts[-1].get("text") or ""
                    asst_ts = r.get("timestamp") or ""

    # Time spent ANSWERING, which is not the time the session has existed.  A
    # turn runs from the prompt that opens it to the last record before the
    # next prompt, so summing those spans counts the working time and skips
    # every gap where the session sat waiting for someone to type.  The two
    # figures together are the point of the pair: 1.9h of work inside an 18h
    # session says something neither number says alone.
    spans = []
    tools = []
    blocked = []
    pending = {}
    first = open_at = prev = None
    # The ETA belongs to the turn it was written in: a new prompt clears it,
    # and so does the answer finishing — an assistant record that ends its
    # turn, with no work after it.  A report from a turn that is over is not
    # an estimate of anything still running.
    eta_state = new_eta_state()
    queued = compactions = 0
    background = {}
    for r in records:
        queued = max(0, queued + queue_step(r))
        compactions += is_compaction(r)
        scan_tool_spans(r, pending, tools, blocked)
        if r.get("isSidechain") is not True:
            live_eta(r, eta_state)
            scan_background(r, background)
        t = ts_epoch(r.get("timestamp") or "")
        if t is None:
            continue
        if first is None:
            first = t
        if turn_start_text(r) is not None:
            if open_at is not None and prev > open_at:
                spans.append((open_at, prev))
            open_at = prev = t
        elif open_at is not None and is_work(r):
            prev = t
    if open_at is not None and prev > open_at:
        spans.append((open_at, prev))
    # The oldest call still running, for the 🛫 cell: only one asked for in
    # the turn still open, since an older one left unanswered was cut off.
    running = [t for t, name in pending.values()
               if name not in WAITING_TOOLS and open_at and t >= open_at]
    if now is not None:
        open_tool_spans(pending, now, tools, blocked)
    busy, tool, blocked_s = thread_clock(spans, tools, blocked)

    return Transcript(
        busy_s=busy,
        # The first STAMPED record, not records[0]: a transcript can open with
        # an unstamped one, and taking its empty timestamp blanked the field
        # outright rather than degrading it.
        start_s=first or 0.0,
        tok_up=int(fresh + W_CACHE_WRITE * cwrite + W_CACHE_READ * cread),
        tok_down=down,
        # -1 is a sentinel meaning "no usage data at all", which is a different
        # state from a legitimate 0% and renders as no segment rather than as
        # a zero.
        cache_pct=int(100 * cread / in_all) if in_all > 0 else -1,
        ctx_tokens=ctx,
        user_ts=user_ts,
        user_text=squash(user_text),
        asst_ts=asst_ts,
        asst_text=squash(asst_text),
        tool_s=tool,
        blocked_s=blocked_s,
        turn_s=open_at or 0.0,
        eta=() if eta_state[1] else eta_state[0],
        agent_etas=tuple(agent_etas),
        queued=queued,
        compactions=compactions,
        shells=sum(1 for k in background.values() if k == "bash"),
        monitors=sum(1 for k in background.values() if k == "monitor"),
        tool_at=min(running) if now is not None and running else 0.0,
    )


def opens_turn(r: dict) -> bool:
    """True for a record that OPENS a turn — the unit the cost line reports.

    Two kinds do, and the second was missing for as long as this file has
    existed.  A prompt the user typed is one.  The other is a message
    DELIVERED to an idle session, which Claude Code writes as `type: user`
    with `promptSource: "system"`.  There are four of them, and across 130
    transcripts on this machine they are the only things that field ever
    marks: a `<task-notification>` from a background task finishing (253), a
    message from another session (92), a cross-session idle notice (6), and
    the usage limit resetting (4).  The session answers each of them exactly
    as it answers a typed prompt, and the answer is billed exactly the same
    way, so each is a turn.

    Left out, they were not merely mislabelled.  A wake message is often the
    FIRST thing in a transcript — another session writes to a session the user
    has not typed into yet — and `read_turns` drops assistant records that
    precede the first recognised prompt, because there is no turn to attribute
    them to.  Measured in one such session: 74 of its 87 requests, 15.7M of
    cache-read and 112k of output, reported by no row and counted in no total,
    and the Stop hook printing "(no prompts recorded yet)" 37 minutes in.
    Where a typed prompt did precede them, their work went onto ITS turn
    instead, so the 🎤 row reprinted the previous prompt with the peer turn's
    figures added to it.

    What is still excluded, and why each one has to be:

      * isCompactSummary — the summary /compact injects.  Prose, and it does
        not begin with '<', so the shape checks alone let it through.
      * strings opening with '<' — tool results and system reminders.  This
        does NOT apply to the wake branch: `<task-notification>` opens with
        the character, and `promptSource` is what tells the two apart.
      * isMeta on a TYPED record.  A wake message is usually marked isMeta as
        well, so the flag cannot be the test on that branch.
      * promptSource "queued" — a typed prompt handed over from the queue.
        Its turn boundary is the queue's own removal record, which carries the
        text and a timestamp of when the model actually got it; see
        `queued_text`.  Reading both would open the turn twice.

    The exclusion this replaces was written against a mid-turn injection —
    "four in a row landed inside one turn" — and that shape does not exist in
    any transcript here: of the 355 wake records, not one is preceded by an
    assistant record or a tool result.  Every one sits at a turn boundary,
    after a queue dequeue, a turn_duration, or another wake record delivered
    in the same batch.  A peer message that genuinely arrives mid-turn gets no
    `type: user` record at all — only a queue `remove`, whose content opens
    with '<' and is refused by `queued_text`.  A batch delivered together
    opens one turn each, the earlier ones with no requests under them, which
    is the queue-drain case `render_cost_line` already skips past.

    promptSource is checked permissively on the typed branch (absent counts as
    typed) so that transcripts written before the field existed still segment
    correctly.
    """
    c = (r.get("message") or {}).get("content")
    if (r.get("type") != "user" or r.get("userType") != "external"
            or r.get("isCompactSummary")
            or not isinstance(c, str) or len(c) == 0):
        return False
    if r.get("promptSource") == "system":
        return True
    return (not r.get("isMeta")
            and r.get("promptSource", "typed") == "typed"
            and not c.startswith("<"))


# Every enqueue is matched by exactly one of these — 1886 of each across 112
# transcripts — so a removal is a delivery, not a cancellation.  The three
# spellings are the queue draining one item, draining all of them, and the
# item being taken off the front; none of them means the message was dropped.
QUEUE_DELIVERED = ("remove", "dequeue", "popAll")


def queued_text(r: dict) -> Optional[str]:
    """The prompt a `queue-operation` record delivered, or None.

    A message typed while the assistant is working does NOT get a `type: user`
    record.  It goes into a queue, and the only trace in the transcript is a
    pair of `queue-operation` records — an enqueue when it was typed and a
    removal when it was handed to the model.  Nothing else is written: the
    text reaches the model inside the turn already in flight.

    Left unread, every queued prompt is invisible as a turn boundary and its
    work is filed under whichever message the user last typed while the
    assistant was IDLE.  Measured over 80 transcripts: 859 queued prompts
    against 991 typed ones, so in a session that uses the queue at all this
    was mis-segmenting close to half of them.  That is the whole of the
    "Prompt (last) is the prompt before last" complaint, and most of the
    "elapsed time is far too long" one — a merged turn spans every gap the
    user spent reading and typing between the messages it swallowed.

    The removal is the boundary, not the enqueue: the enqueue is stamped when
    the message was TYPED, which can be minutes before the assistant was free
    to read it, and that waiting is the user's, not the machine's.

    Unlike `opens_turn`, this one is TYPED-ONLY, and deliberately so.  A turn
    can also be opened by a message nobody typed — that is why `opens_turn` is
    not called `is_prompt` — but those arrive as `type: user` records with
    `promptSource: "system"`, never through this queue.  What DOES ride this
    queue alongside typed prompts is machinery, and the shape rule below
    refuses it.  So "prompt" is accurate here in a way it is not one function
    up.
    """
    if r.get("type") != "queue-operation":
        return None
    if r.get("operation") not in QUEUE_DELIVERED:
        return None
    c = r.get("content")
    # The same shape rule as opens_turn's TYPED branch — not as opens_turn as a
    # whole, which lets a `promptSource: "system"` record through regardless of
    # what it opens with.  Task notifications and other machinery ride this
    # queue too, and every one of them opens with '<'.
    return c if isinstance(c, str) and len(c) > 0 and not c.startswith("<") \
        else None


def queue_step(r: dict) -> int:
    """+1 for a message put on this thread's queue, -1 for one handed over.

    The running sum, never below zero, is how many messages are waiting for
    the thread's next turn: prompts typed while it was busy, task
    notifications, and what agents sent it with SendMessage, which answers
    them "Message queued for the main conversation's next turn."  Every
    enqueue is matched by one QUEUE_DELIVERED record (see there), so the sum
    of a finished session is zero.
    """
    if r.get("type") != "queue-operation":
        return 0
    op = r.get("operation")
    return 1 if op == "enqueue" else -1 if op in QUEUE_DELIVERED else 0


def is_compaction(r: dict) -> bool:
    """True for the marker a compaction writes, /compact's or the automatic
    one's: `type: system`, `subtype: compact_boundary`."""
    return r.get("type") == "system" and r.get("subtype") == "compact_boundary"


# What SendMessage answers when the agent it names is busy: the message waits
# in that agent's inbox until its next tool round, and Claude Code's panel
# counts it on the agent's row as "1 queued".  The payload the panel hands
# the subagent status line carries no such count, so inbox_counts rebuilds it
# from the two ends.  Read out of Claude Code 2.1.284 on 2026-09-30; 261 of
# 261 SendMessage results to an agent over six days read this way.
SEND_QUEUED_RE = re.compile(r"queued for delivery to (\S+) at its next tool round")
SEND_QUEUED_MARK = b"queued for delivery to"
# The origins inbox_delivery counts: tighter than `"queued_command"`, which
# every task notification carries too, and the value alone, so the search
# holds whether or not the JSON is spaced.
INBOX_MARKS = (b'"coordinator"', b'"peer"')


def queued_send(r: dict) -> str:
    """The agent id a SendMessage result says its message is waiting for, or ""."""
    res = r.get("toolUseResult")
    msg = res.get("message") if isinstance(res, dict) else None
    m = SEND_QUEUED_RE.search(msg) if isinstance(msg, str) else None
    return m.group(1) if m else ""


def inbox_delivery(r: dict) -> bool:
    """True for a SendMessage delivery taken off this agent's inbox.

    Claude Code writes one in the agent's own file in either of two shapes:
    a `queued_command` attachment, or a `type: user` record reading "The
    coordinator sent a message while you were working: …", and both are
    current.  Their `origin` — the attachment's, or the record's own — says
    who sent it: `coordinator` for the main thread and `peer` for another
    agent, both through SendMessage.  A peer message marked `handback` is a
    subagent's final report to its caller, not a send, and a `human` one was
    typed into the agent's pane, which leaves no trace on the sending side;
    a record with no origin is a task notification.
    """
    a = r.get("attachment")
    if isinstance(a, dict) and a.get("type") == "queued_command":
        o = a.get("origin")
    elif r.get("type") == "user":
        o = r.get("origin")
    else:
        return False
    if not isinstance(o, dict):
        return False
    kind = o.get("kind")
    return kind == "coordinator" or (kind == "peer" and not o.get("handback"))


def marked_records(path: str, marks: Sequence[bytes]):
    """Parse only the lines of `path` that hold one of `marks`, in file order.

    For a scan of the main transcript on every panel tick, where _records
    would parse a file that can run to 200MB to find a handful of lines: a
    byte search finds them in a fifth of a second.  A line that will not
    parse is skipped, as _records skips it.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return []
    starts = set()
    for mark in marks:
        i = data.find(mark)
        while i >= 0:
            s = data.rfind(b"\n", 0, i) + 1
            starts.add(s)
            e = data.find(b"\n", i)
            i = data.find(mark, e) if e >= 0 else -1
    out = []
    for s in sorted(starts):
        e = data.find(b"\n", s)
        try:
            out.append(json.loads(data[s:e if e >= 0 else len(data)]
                                  .decode("utf-8", "replace")))
        except Exception:
            continue
    return out


def inbox_sends(path: str) -> List[Tuple[float, str]]:
    """(epoch, target id) for each message this file queued for an agent."""
    out = []
    for r in marked_records(path, (SEND_QUEUED_MARK,)):
        t, target = ts_epoch(r.get("timestamp") or ""), queued_send(r)
        if t is not None and target:
            out.append((t, target))
    return out


def inbox_deliveries(path: str) -> List[float]:
    """The epoch of each SendMessage delivery in this agent's file."""
    return [t for t in (ts_epoch(r.get("timestamp") or "")
                        for r in marked_records(path, INBOX_MARKS)
                        if inbox_delivery(r)) if t is not None]


def inbox_counts(files: Sequence[str], targets: Dict[str, str],
                 since: Optional[float] = None) -> Dict[str, int]:
    """How many messages wait in each agent's inbox: `{agent id: count}`.

    `files` is every transcript that can send — the main thread's and each
    agent's — and `targets` maps each agent on the panel to its own file.
    The two ends are matched by time, not by text: a send raises the count,
    a delivery lowers it, and the count never goes below zero, so a delivery
    with no queued send behind it — a message that woke a stopped agent and
    was never queued — takes nothing from a later one.

    `since`, the earliest any target started, skips every file last written
    before it, which cannot hold a send to an agent that did not exist yet.
    A long session's agent files run to hundreds of megabytes, nearly all of
    them finished long before anything now on the panel started.
    """
    sent: Dict[str, List[float]] = {}
    for f in files:
        try:
            if since is not None and os.path.getmtime(f) < since:
                continue
        except OSError:
            continue
        for t, target in inbox_sends(f):
            if target in targets:
                sent.setdefault(target, []).append(t)
    out = {}
    for aid, times in sent.items():
        # A send and its delivery stamped alike: the send first.
        events = sorted([(t, 0, 1) for t in times]
                        + [(t, 1, -1) for t in inbox_deliveries(targets[aid])])
        n = 0
        for _, _, step in events:
            n = max(0, n + step)
        if n:
            out[aid] = n
    return out


def turn_start_text(r: dict) -> Optional[str]:
    """The text of the prompt this record opens, or None if it opens none."""
    if opens_turn(r):
        return (r.get("message") or {}).get("content")
    return queued_text(r)


def is_work(r: dict) -> bool:
    """True for a record written while the assistant was answering.

    What this excludes is the point.  A turn ends at the last record the
    ANSWER produced, and the transcript keeps appending long after that: the
    caveat and command records a slash command writes, the enqueue stamped
    when the user typed their next message, the compact summary.  Those carry
    the timestamp of whenever the user got round to it, so counting them as
    part of the turn charges the assistant for the user's reading time — an
    idle overnight gap turned one turn into 1.3h of "answering".

    Tool results are the case that has to stay IN: they arrive as `type: user`
    with a LIST of blocks, and a turn that finishes with one took until that
    result.  A person's message is always a plain string, so the shape of the
    content is what separates the two.
    """
    t = r.get("type")
    if t in ("assistant", "system"):
        return True
    if t == "user":
        return isinstance((r.get("message") or {}).get("content"), list)
    return False


# Characters per token for the compaction summary, calibrated against the
# metadata rather than assumed: the two compactions in this session summarised
# to 16,201 and 23,659 characters against postTokens of 6,597 and 8,737, and
# postTokens is the summary PLUS the handful of preserved messages.  At 4 the
# estimate leaves 700 and 2,800 tokens for those, which is the right order.
# Three would leave none, five would leave more than the messages can hold.
SUMMARY_CPT = 4.0


def _new_turn(ts: str, text: str) -> dict:
    """The mutable turn read_turns builds up, before it is frozen."""
    return {"ts": ts, "text": text,
            "fresh": 0, "cw": 0, "cr": 0, "out": 0, "ctx": 0, "n": 0,
            "usd": [0.0, 0.0, 0.0, 0.0], "an": 0, "aids": [],
            "t0": ts_epoch(ts), "t1": None, "parts": [],
            "tools": [], "waits": [], "am": 0.0, "at": 0.0,
            "pid": "", "tidx": None}


def _stamp_turn_id(cur: dict, r: dict) -> None:
    """Take the turn's promptId and turnIndex off `r`, where the turn has
    none yet.  First one wins: every user record of a turn carries the same
    promptId, and a turn a queue-operation record opened gets its id from
    the first tool result instead of from its opener."""
    pid = r.get("promptId")
    if pid and not cur["pid"]:
        cur["pid"] = str(pid)
    idx = (r.get("turnPosition") or {}).get("turnIndex")
    if cur["tidx"] is None and isinstance(idx, int) and not isinstance(idx, bool):
        cur["tidx"] = idx


def _add_usd(cur: dict, epoch: Optional[float], model: Optional[str],
             fresh: int, cw: int, cr: int, out: int) -> None:
    """Bill one record to a turn: the four dollar sums, and one part."""
    d = _usd(model, fresh, cw, cr, out)
    for i in range(4):
        cur["usd"][i] += d[i]
    cur["parts"].append((epoch, sum(d)))


def _fold_agents(turns: List[dict], by_pid: Dict[str, dict],
                 agents: Sequence[AgentRec],
                 last_stop: Optional[float] = None,
                 offsets: Optional[Dict[str, int]] = None) -> Optional[dict]:
    """File every agent record under a turn of the main transcript.

    By promptId where a main record carried it — the turn that spawned the
    agent, or resumed it, whenever it finished.  That is the rule rather
    than the stamp because 14% of agent records here are stamped after the
    NEXT turn opened: a background agent, a fork left running, a workflow.
    By stamp those would land on the next prompt's row and that row would
    lie by that much.

    By stamp only where no main record carries the id: transcripts that
    predate promptId, and workflow agents, which are prompted under ids of
    the workflow's own.  The stamp picks the last NON-COMPACTION turn open
    at that moment.  An auto compaction leaves the compaction turn open for
    the rest of the answer, and everything main-thread that follows lands
    on it already; agent spend must not join it there, because the 🤏 row
    is the compaction's and prompts exclude it.

    Dropped, as main records are, where no turn precedes the record.

    Into the turn: the token sums, the dollar sums, a part, and agent_calls
    — not `n`, which is the main thread's and is what the settle wait
    watches; not `ctx`; not `t1`.

    EXCEPT when the record is NEW and its turn is not the one the next
    Stop will report.  A Stop prints one 🎤 row, for the last turn with
    main-thread calls; a record filed anywhere else prints on no row.  Two
    ways that happens.  The turn was REPORTED already — one of the first
    `settled`, a Stop has run past it — and the record arrived after: a
    background agent, a fork left running, a workflow, each of which can
    finish after the turn that spawned it printed.  Or the turn shares its
    Stop with a later one — a queued prompt delivered inside the run
    already in flight opens a turn of its own, and the one Stop reports
    the last of them — so it never gets a 🎤 row at all; 43% of billed
    turns on this machine are that, and in a session that runs workflows
    under a stream of task notifications it is nearly all of them.  Filing
    the spend on such a turn counts it in the totals and prints it on no
    row, which is what happened to compactions before they got a row of
    their own.  Those records go into one turn of their own instead,
    returned here for read_turns to freeze, and print on the 👥 row at the
    next Stop.  The spawning turn does NOT get them — the totals sum every
    turn, and a record in two of them is billed twice.

    WHAT "not in the file when that happened" means is the delicate part.
    With `offsets` — the byte counts the last Stop hook stored for each
    agent file, see agent_offsets — it is exact: a record whose line ends
    beyond its file's stored offset was not there.  Without them, the only
    boundary is the last Stop record's stamp, and a record stamped after
    it is taken as late.  That is at-most-once, not exactly-once: an agent
    file flushes on its own schedule, and a record stamped before the Stop
    but written after it looks reported and prints nowhere.  Measured on
    this machine, about 1% of late-eligible records sit inside that window.
    The offsets exist to close it; the stamp is the fallback for the first
    Stop of a session and for a fixture.
    """
    if not agents or not turns:
        return None
    stamped = [(t["t0"], t) for t in turns
               if t["t0"] is not None and not t.get("compact")]
    # The turn the 🎤 row will be about: the same selection render_cost_line
    # and _with_shares make.  `n` is main-thread calls, so folding agents in
    # cannot move it.  With no such turn there is no 🎤 row to be "not on",
    # and everything is filed where it belongs.
    prompt = None
    for t in turns:
        if t["n"] and not t.get("compact"):
            prompt = t
    late = None
    for a in agents:
        cur = by_pid.get(a.prompt_id) if a.prompt_id else None
        if cur is None:
            for t0, t in reversed(stamped):
                if a.epoch is None or t0 <= a.epoch:
                    cur = t
                    break
            if cur is None:
                continue
        if prompt is not None and cur is not prompt:
            if offsets is not None:
                new = a.offset > offsets.get(a.path, 0)
            else:
                new = (last_stop is None
                       or (a.epoch is not None and a.epoch > last_stop))
            if new:
                if late is None:
                    late = _new_turn(_stamp_utc(a.epoch), "agents (other)")
                cur = late
        cur["fresh"] += a.fresh
        cur["cw"] += a.cache_write
        cur["cr"] += a.cache_read
        cur["out"] += a.out
        cur["an"] += 1
        cur["aids"].append(a.request_id)
        cur["am"] += a.model_s
        cur["at"] += a.tool_s
        _add_usd(cur, a.epoch, a.model, a.fresh, a.cache_write, a.cache_read,
                 a.out)
    return late


def read_turns(path: str, agents: Optional[Sequence[AgentRec]] = None
               ) -> Tuple[Turn, ...]:
    """Segment the transcript into prompts, with each turn's billed usage.

    `ctx` is LAST-WRITE-WINS within a turn and is the MAIN THREAD's — it is
    an instantaneous reading of how big the window is, not a sum of anything.
    A port that accumulates it produces a figure that looks like cumulative
    tokens and is not a context size at all.  Agent usage never touches it:
    an agent runs a window of its own, and 🧠 is read to decide when THIS
    one needs compacting.

    `agents` is what agent_records returns for this transcript; None reads
    it here.  A caller that also calls read_transcript passes the one it
    read, so a status-line redraw walks the agent files once.  Every agent
    record is folded into the turn whose promptId it carries, or — where no
    main record carries that id — into the turn open at its stamp, skipping
    compactions so that agent spend never prints on the 🤏 row.  Its tokens
    and dollars go into the same sums and its cost into `parts`, which is
    what lets a window boundary split it; its stamp does NOT move the turn's
    end, because agents run in parallel with the turn and a background one
    finishing an hour later is not an hour of answering.

    Assistant records appearing before the first recognised prompt are dropped:
    there is no turn to attribute them to.
    """
    turns = []      # built mutably here, frozen into NamedTuples on the way out
    settled = 0     # turns that a Stop hook has already run past
    cur = None
    seen = set()
    by_pid = {}     # promptId → the turn open when a record carrying it was read
    last_stop = None    # epoch of the last Stop record, for late_agent_turn
    pending = {}        # tool calls asked for and not yet answered; see below
    for r in _records(path):
        # Every tool call, onto the turn open when its RESULT arrives: the
        # scan read_transcript makes for the status line's 🔧, so the two
        # readouts count the same calls by the same rule.  `pending` spans
        # turns, as it spans the file there.  A record before the first
        # prompt still has to be scanned — its call can be answered inside
        # a turn — and its own spans go nowhere, as its billing does.
        scan_tool_spans(r, pending, cur["tools"] if cur else [],
                        cur["waits"] if cur else [])
        pid = r.get("promptId")
        text = turn_start_text(r)
        if text is not None:
            # A queued message can be recorded BOTH ways — once typed, once
            # delivered — in the one case in 859 where the queue drained
            # while the assistant was already idle.  The earlier of the two
            # has no records under it yet, so replacing it in place keeps one
            # turn rather than two, and keeps the later timestamp, which is
            # when the answering actually started.
            if (cur is not None and cur["n"] == 0 and cur["t1"] is None
                    and cur["text"] == text):
                cur["ts"] = r.get("timestamp") or cur["ts"]
                cur["t0"] = ts_epoch(r.get("timestamp") or "")
            else:
                cur = _new_turn(r.get("timestamp") or "", text)
                turns.append(cur)
            _stamp_turn_id(cur, r)
            if pid:
                by_pid[pid] = cur
            continue
        # Every user record of a turn carries the turn's promptId — the
        # opener, a queued delivery, a wake, and every tool result — so the
        # index is built from all of them, not from the opener alone.  A
        # turn opened by a queue-operation record has no id on its opener
        # and is indexed through its tool results instead.
        if pid and cur is not None and not cur.get("compact"):
            by_pid.setdefault(pid, cur)
            _stamp_turn_id(cur, r)
        if r.get("subtype") == "compact_boundary":
            # A compaction is the one expensive operation that leaves NO usage
            # record anywhere — the request that summarises the conversation
            # is never written to the transcript.  What IS written is this
            # boundary record, and between them its fields say almost
            # everything the row needs:
            #
            #   preTokens   what was fed to the summariser.  Measured against
            #               our own last reading before the boundary — 292,645
            #               against 289,457 — so it is the same quantity this
            #               file calls ctx, to within a percent.
            #   durationMs  how long it took, which is otherwise unknowable:
            #               the turn has no records to bound it with.
            #   postTokens  NOT comparable to our readings, and deliberately
            #               unused: it counts the compacted conversation
            #               alone, where every reading here also carries the
            #               system prompt and the tool definitions.  8,737
            #               against the 95,691 the next request measured.  The
            #               drop across the boundary is reported by that next
            #               turn, in units that can be checked.
            #
            # The input is charged at the cache-read rate.  The summariser is
            # handed the conversation that was live seconds earlier, so it
            # reads the prefix the session has been paying to keep warm; the
            # alternative — full rate on 300k tokens — would put the figure
            # ten times too high.
            # An AUTO compaction has no /compact prompt in front of it: the
            # boundary lands inside whatever turn was running, and filling
            # that turn in would overwrite a real prompt's figures with the
            # compaction's.  So the compaction gets a turn of its own unless
            # the one open is the /compact that asked for it.
            md = r.get("compactMetadata") or {}
            if cur is None or cur["n"] or cur["text"].strip() != "/compact":
                cur = _new_turn(r.get("timestamp") or "",
                                "/compact (%s)" % (md.get("trigger") or "auto"))
                turns.append(cur)
            cur["cr"] = md.get("preTokens") or 0
            cur["usd"][2] = cur["cr"] * P_CR
            cur["n"] = 1
            cur["dur"] = (md.get("durationMs") or 0) / 1000.0
            cur["compact"] = True
        elif (r.get("subtype") == "stop_hook_summary"
              and not r.get("isSidechain")):
            last_stop = ts_epoch(r.get("timestamp") or "") or last_stop
            # The transcript's own record that a Stop hook RAN, written after
            # the hook returns.  It is the only mark in the file of where a
            # previous cost line drew its window, and it is what makes
            # "report each compaction exactly once" true rather than nearly
            # true.
            #
            # The pairing it replaces inferred that boundary from the prompts:
            # a compaction falls between two consecutive answered prompts, and
            # the second of them reports it.  That holds only while every Stop
            # sees its own prompt.  When one does not — the transcript is not
            # flushed in step with the hook, see read_turns_settled — two
            # consecutive Stops share a window, the pair that straddles the
            # compaction never gets a Stop of its own, and the row is not
            # late: it is gone.  Measured, in this file's own transcript: 18k
            # of cache-read and 1.2m of wall clock reported nowhere.
            settled = len(turns)
        elif r.get("isCompactSummary") and cur is not None and cur.get("compact"):
            # The one figure the metadata does not carry is what the
            # summariser WROTE, and this is it — arriving one record after the
            # boundary, and with an earlier timestamp than it.  Estimated from
            # the text, and the only estimate on either row: everything else
            # here is read or measured.
            _c = (r.get("message") or {}).get("content")
            if isinstance(_c, str):
                cur["out"] = int(len(_c) / SUMMARY_CPT)
                cur["usd"][1] = cur["out"] * P_OUT
        elif r.get("type") == "assistant" and (r.get("message") or {}).get("usage"):
            k = r.get("requestId") or (r.get("message") or {}).get("id")
            if k in seen or cur is None:
                continue
            seen.add(k)
            u = r["message"]["usage"]
            cur["fresh"] += u.get("input_tokens", 0)
            cur["cw"] += u.get("cache_creation_input_tokens", 0)
            cur["cr"] += u.get("cache_read_input_tokens", 0)
            cur["out"] += u.get("output_tokens", 0)
            cur["n"] += 1
            # Priced here, per record, at the record's own model: the four
            # dollar sums are what turn_cost totals, and `parts` carries the
            # same figure so that a window-bounded share and an unbounded one
            # stay on one scale — the parts total the whole EXACTLY.
            _add_usd(cur, ts_epoch(r.get("timestamp") or ""),
                     r["message"].get("model"),
                     u.get("input_tokens", 0),
                     u.get("cache_creation_input_tokens", 0),
                     u.get("cache_read_input_tokens", 0),
                     u.get("output_tokens", 0))
            if not r.get("isSidechain"):
                # LAST-WRITE-WINS, but only over readings that exist.  An
                # interrupted request is written with every usage field zero,
                # and taking that as the reading WIPES the real one captured
                # seconds earlier — the turn then reports no context at all
                # and its 🧠 cell goes blank.  20 such records in 25,782, and
                # they cluster exactly where they hurt: a request is
                # interrupted when the user types over it, which is the same
                # moment they are watching the line for an answer.
                _ctx = (u.get("input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0))
                if _ctx:
                    cur["ctx"] = _ctx
        # Every stamped record of the ANSWER moves the turn's end, not just
        # the billed ones: a turn that finishes with a tool result took until
        # that result, and counting only usage records would stop the clock
        # early.  is_work is what keeps the user's own time out of it.
        if cur is not None and is_work(r):
            _t = ts_epoch(r.get("timestamp") or "")
            if _t is not None:
                cur["t1"] = _t

    late = _fold_agents(turns, by_pid,
                        agent_records(path, seen) if agents is None else agents,
                        last_stop, agent_offsets(path))

    # Context growth per turn: how much bigger the window got while this prompt
    # was answered.  The first turn of a transcript gets None rather than its
    # own absolute size — there is no previous reading to subtract, and
    # reporting the absolute figure as though it were growth would be a lie in
    # the one place nobody could check it.  A RESUMED session is the same case:
    # its first turn continues a window this transcript never saw, so a delta
    # across that boundary would be fiction.
    #
    # A compaction shows as a large negative, which is left signed rather than
    # clamped: it is the most useful thing this field can ever report.
    #
    # For it to show at all, prev has to SKIP a turn that carries no reading.
    # A /compact turn records ctx=0 — the compaction issues no request whose
    # usage could be counted — and advancing prev onto that zero blanked the
    # cell TWICE: once for the compact turn, and again for the prompt after
    # it, whose delta against nothing is unknowable.  Two rows lost, and the
    # one figure worth having lost with them.  Holding prev at the last real
    # reading spans the gap instead, so the next prompt reports the drop
    # across the compaction and this comment stops being a promise.
    out = []
    prev = None
    for t in turns:
        dctx = (t["ctx"] - prev["ctx"]
                if prev is not None and t["ctx"] else None)
        # A compaction's time is its durationMs, the summariser's, and the
        # summariser runs no tool.  The rest of an answer an auto compaction
        # lands in is billed to its turn but timed by neither figure — dur_s
        # has never counted it — and giving it tool seconds alone would put
        # a 🔧 beside a ⌛🤖 that does not contain it.
        tool_s, blocked_s = ((0.0, 0.0) if t.get("compact") else
                             turn_clock(t["tools"], t["waits"],
                                        t["t0"], t["t1"]))
        out.append(Turn(ts=t["ts"], text=t["text"], fresh=t["fresh"],
                        cache_write=t["cw"], cache_read=t["cr"], out=t["out"],
                        ctx=t["ctx"], calls=t["n"], dctx=dctx,
                        usd_in=t["usd"][0], usd_out=t["usd"][1],
                        usd_cr=t["usd"][2], usd_cw=t["usd"][3],
                        compact=bool(t.get("compact")),
                        reported=len(out) < settled,
                        parts=tuple(t["parts"]),
                        agent_calls=t["an"], agent_ids=tuple(t["aids"]),
                        dur_s=(t["dur"] if t.get("dur") else
                               (t["t1"] - t["t0"]
                                if t["t0"] and t["t1"] and t["t1"] > t["t0"]
                                else 0.0)),
                        tool_s=tool_s, blocked_s=blocked_s,
                        agent_model_s=t["am"], agent_tool_s=t["at"],
                        prompt_id="" if t.get("compact") else t["pid"],
                        turn_index=None if t.get("compact") else t["tidx"]))
        if t["ctx"]:
            prev = t
    if late is not None:
        out.append(late_agent_turn(late))
        out.sort(key=lambda t: t.ts)
    return tuple(out)


def late_agent_turn(t: dict) -> Turn:
    """Freeze the synthetic turn _fold_agents built for late agent records.

    `calls` is 0 and `agent` is set, which between them keep it out of every
    "the prompt to report" selection and out of the settle wait; `ctx` is 0
    so the Δctx walk steps over it; `reported` is False because the records
    in it are, by construction, ones no Stop has seen.  Its stamp is the
    earliest late record's, which is where render_cost_line orders it among
    the compactions.
    """
    return Turn(ts=t["ts"], text=t["text"], fresh=t["fresh"],
                cache_write=t["cw"], cache_read=t["cr"], out=t["out"],
                ctx=0, calls=0, dur_s=0.0, dctx=None,
                usd_in=t["usd"][0], usd_out=t["usd"][1],
                usd_cr=t["usd"][2], usd_cw=t["usd"][3],
                parts=tuple(t["parts"]), agent_calls=t["an"],
                agent_ids=tuple(t["aids"]), agent=True,
                agent_model_s=t["am"], agent_tool_s=t["at"])


# How long the Stop hook waits for the turn it is about to report to appear in
# the transcript, and how often it looks.  1.5s against a hook timeout of 20s
# and a typical run of 120ms: room for the write to land, nowhere near the
# budget that would make the hook itself the thing keeping the turn waiting.
SETTLE_S = 1.5
SETTLE_POLL_S = 0.025


def read_turns_settled(path: str, budget: float = SETTLE_S,
                       poll: float = SETTLE_POLL_S,
                       agents: Optional[Sequence[AgentRec]] = None
                       ) -> Tuple[Turn, ...]:
    """`read_turns`, having waited for the turn being reported to be written.

    The transcript is NOT flushed in step with the Stop hook.  The records the
    turn just produced carry timestamps from before the hook fires and are
    still not in the file when it reads:

        record 383  assistant +usage   12:06:59.976   ┐ both absent from the
        record 384  assistant +usage   12:07:00.296   ┘ file at 12:07:01.4
        record 387  system/stop_hook_summary  12:07:01.516

    A turn with no usage record looks like a prompt that was never answered,
    and `render_cost_line` deliberately falls back to the last prompt that WAS
    — printing a row of zeros for a prompt the user just watched being
    answered is the worse failure.  So the line silently reported the PREVIOUS
    prompt: the same figures twice, one record apart, `▴561k` and then `▴580k`
    for a single 28-minute turn.  Every `🎤` row was short of its own turn by
    whatever the last request billed; on a turn that made no tool calls it was
    short by the whole turn.

    Waiting is the only stateless fix, because nothing in the payload says
    which turn the hook was called for.  It costs nothing in the case that
    does not need it — the check is one `read_turns` that was going to happen
    anyway — and it is bounded in the case that never settles: a turn
    interrupted before it billed anything gets `budget` of dead time once and
    then reports exactly what it reports today.

    `st_size` gates the re-read so a wait that spans the whole budget parses
    the transcript once, not sixty times.
    """
    turns = read_turns(path, agents)
    if not budget or _settled(turns):
        return turns
    deadline = time.monotonic() + budget
    try:
        size = os.stat(path).st_size
    except OSError:
        return turns
    while time.monotonic() < deadline:
        time.sleep(poll)
        try:
            grown = os.stat(path).st_size
        except OSError:
            break
        if grown == size:
            continue
        size = grown
        turns = read_turns(path, agents)
        if _settled(turns):
            break
    return turns


def _settled(turns: Sequence[Turn]) -> bool:
    """Has the turn being reported billed anything yet?

    The last turn that is not the synthetic agents turn: that one is sorted
    in by stamp and can land after the live turn's opener — a background
    agent's record arriving mid-answer — and its `calls` is 0 by design, so
    testing turns[-1] would wait the whole budget on every such Stop.
    """
    for t in reversed(turns):
        if not t.agent:
            return bool(t.calls)
    return False



def _price(model: Optional[str]) -> Tuple[float, float, float, float]:
    m = (model or "").lower()
    for key, prices in MODEL_PRICE:
        if key in m:
            return prices
    return MODEL_PRICE[0][1]
