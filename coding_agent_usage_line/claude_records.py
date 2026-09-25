#!/usr/bin/env python3
"""Claude payload records and transcript/accounting parser.

This module owns Claude-specific JSONL interpretation and price accounting.
It deliberately has no terminal rendering or hook stdin/stdout orchestration.
"""
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
    busy_s: float           # seconds spent answering, summed over every turn
    start_s: float          # epoch of the first STAMPED record, 0 if none
    tool_s: float = 0.0     # of that answering, the part spent inside a tool —
                            # this thread's and every agent's, unioned, LESS
                            # the blocking prompts below.  See tool_spans.
                            # Defaulted so EMPTY_TRANSCRIPT and the fixtures
                            # that predate it still build.
    blocked_s: float = 0.0  # and the part spent inside a tool that was a
                            # question put to the user.  It is answering time
                            # by the transcript's reckoning and waiting time
                            # by any reader's, so the row hands it to 👤 —
                            # see BLOCKING_TOOLS and render_elapsed.


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
                  spans: Optional[list] = None,
                  tools: Optional[list] = None,
                  blocked: Optional[list] = None) -> Tuple[AgentRec, ...]:
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

    `spans` is an out-parameter, and it is one because this walk already
    parses every line of every agent file: pass a list and each agent's
    WORKING spans are appended to it — the same segmentation read_transcript
    does on the main thread, an agent's prompt to the last record its answer
    produced — so the one read serves both the token totals and the clock.
    An agent resumed by a later SendMessage opens a second span rather than
    one long one, so the hours it spent waiting to be resumed are not
    charged to it.

    `tools` is the second out-parameter of the same kind, for ⌛'s 🔧: pass a
    list and every agent's TOOL spans are appended to it, off the same read
    again.  An agent that spawned agents of its own needs no special case —
    its Task span already covers the child's whole run, and the child's own
    spans are appended here too, so the union counts the nesting once.
    `blocked` takes the blocking-prompt subset of those, which for an agent
    file is normally empty — an agent has nobody to ask — and is read anyway
    rather than assumed.
    """
    seen = set() if seen is None else seen
    out = []
    for path in agent_files(transcript):
        pid = ""
        open_at = prev = None
        pending = {}
        try:
            fh = open(path, "rb")
        except OSError:
            continue
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
                if tools is not None:
                    scan_tool_spans(r, pending, tools, blocked)
                if spans is not None:
                    t = ts_epoch(r.get("timestamp") or "")
                    if t is not None:
                        if turn_start_text(r) is not None:
                            if open_at is not None and prev > open_at:
                                spans.append((open_at, prev))
                            open_at = prev = t
                        elif open_at is not None and is_work(r):
                            prev = t
                if r.get("type") == "user":
                    pid = r.get("promptId") or pid
                    continue
                if r.get("type") != "assistant":
                    continue
                m = r.get("message") or {}
                u = m.get("usage")
                if not u:
                    continue
                k = r.get("requestId") or m.get("id") or "?"
                if k in seen:
                    continue
                seen.add(k)
                fresh = u.get("input_tokens") or 0
                cw = u.get("cache_creation_input_tokens") or 0
                cr = u.get("cache_read_input_tokens") or 0
                o = u.get("output_tokens") or 0
                if not (fresh or cw or cr or o):
                    continue
                out.append(AgentRec(ts_epoch(r.get("timestamp") or ""), pid,
                                    m.get("model"), fresh, cw, cr, o, k,
                                    path, pos))
        if spans is not None and open_at is not None and prev > open_at:
            spans.append((open_at, prev))
    # Stamp order across files, unparseable stamps last: the fold-in walks
    # turns forward and a record that cannot be placed in time is handed to
    # the last turn rather than the first.
    out.sort(key=lambda a: (a.epoch is None, a.epoch or 0.0))
    return tuple(out)


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


def ts_epoch(ts: str) -> Optional[float]:
    """A transcript timestamp as a Unix epoch, or None if it is not one.

    Transcript stamps are UTC with a trailing "Z", which 3.9's fromisoformat
    rejects outright — hence strptime on a stripped string with the zone
    reattached, the same dance elapsed_short does.
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
    exceed Σ the moment anything runs in parallel and turns 👤 into a
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
# and given to 👤 because of what the cell is read for.  🔧 answers "how
# much of the working time was the machine waiting on a shell, a file, a
# subagent"; a dialog that sat open for ninety seconds while someone chose
# between two options is not that, and charging it to 🔧 made the cell
# report the reader's own deliberation back at them.  👤 is already "time
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
    BLOCKING_TOOLS — a subset and not a partition, so a reader that wants
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
                if blocked is not None and hit[1] in BLOCKING_TOOLS:
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


def net_tool_seconds(spans: Sequence[Tuple[float, float]],
                     blocked: Sequence[Tuple[float, float]]) -> float:
    """Seconds inside a tool that were not a blocking prompt.

    A subtraction of two unions rather than an interval difference, and it is
    exact because `blocked` is a SUBSET of `spans`: the measure of a set less
    the measure of a subset is the measure of what is left, whatever either
    one overlaps.  Which matters — a question asked on the main thread can
    run straight through an agent's tool call, and those two spans have to
    come out as one second each, not two.
    """
    return max(0.0, union_seconds(spans) - union_seconds(blocked))


def read_transcript(path: str, agents: Optional[Sequence[AgentRec]] = None,
                    agent_spans: Sequence[Tuple[float, float]] = (),
                    agent_tools: Sequence[Tuple[float, float]] = (),
                    agent_blocked: Sequence[Tuple[float, float]] = ()
                    ) -> Transcript:
    """One pass for the status line: totals, cache rate, context, last texts.

    The token totals and the cache rate count what the session's AGENTS
    billed as well — `agents` is agent_records' reading of the files beside
    the transcript, or None to read them here — because it was billed, and
    a 🧩 that reports the main thread alone is short by whatever the forks
    and workflows spent, which in the sessions that use them is most of it.

    Busy time counts them too — `agent_spans`, which agent_records fills as
    it walks the same files.  An agent is the session working, and on the
    sessions here it is MOST of the working: a main thread that dispatches
    six agents and waits sits idle in its own file, so a 🤖 read off that
    file alone said 14% of a day where the machine was busy for 97% of it.
    Measured over the eight most recent sessions with agents on this
    machine, folding them in roughly doubles the figure.  The two clocks are
    UNIONED, never summed — see union_seconds — so 👤 and 🤖 still split Σ
    exactly, which is the one thing that pair promises.

    Tool time counts them the same way, and for the same reason — `agent_tools`
    beside `agent_spans`, off the one walk.  It is the part of the busy clock
    the session spent inside a tool rather than waiting on a model, and it is
    a partition with them rather than a share of them: 🔧 what the tools took,
    🤖 what is left of the answering, 👤 the wait.  Unioned like the rest,
    which is what makes an agent's tools inside a Task's own span count once
    instead of twice; see scan_tool_spans.

    A tool whose result is the USER'S answer comes out of 🔧 again and is
    reported separately as `blocked_s`, which render_elapsed gives to 👤.
    See BLOCKING_TOOLS for why by name and why not permission prompts.

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
        own = []                        # and take both clocks off it too
        own_tools = []
        own_blocked = []
        agents = agent_records(path, spans=own, tools=own_tools,
                               blocked=own_blocked)
        agent_spans = tuple(agent_spans) + tuple(own)
        agent_tools = tuple(agent_tools) + tuple(own_tools)
        agent_blocked = tuple(agent_blocked) + tuple(own_blocked)
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
    for r in records:
        scan_tool_spans(r, pending, tools, blocked)
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
    busy = union_seconds(spans + list(agent_spans))
    all_tools = tools + list(agent_tools)
    all_blocked = blocked + list(agent_blocked)
    tool = net_tool_seconds(all_tools, all_blocked)
    blocked_s = union_seconds(all_blocked)

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
            "t0": ts_epoch(ts), "t1": None, "parts": []}


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
    for r in _records(path):
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
                                else 0.0))))
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
                agent_ids=tuple(t["aids"]), agent=True)


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
