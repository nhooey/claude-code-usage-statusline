"""Pure Claude subagent-panel row layout.

Preparation (sidecar lookup, usage parsing, limits/source selection and JSON
serialization) belongs to orchestration.  This module only lays out supplied
task facts.  Its cells return spans (see spans.py); render_task_rows hands
each row to the redesigned grid (grid.py, agents/plans/redesign.md) as its
label's pieces and its cells, and joins what the grid draws into escape
codes, where the panel prints it.
"""
import time
from typing import Optional, Sequence

from . import formatting as fmt
from . import grid
from .formatting import *
from .claude_render import (render_cost, render_diff, render_tokens, model_spec,
                            effort_glyph, eta_reading,
                            inherit_eta)
from .claude_records import Limits, squash, eta_finish, WAITING_TOOLS
from .spans import Span, ink, join, paint, rstrip, spans, width
from .spec import CHROME_DEPTH, GRID_CELLS, LABEL_MIN, RIGHT_EDGE

A_STATE_W, A_CLOCK_W, A_RATE_W, A_TICK_S = 2, 6, 8, 5.0
# 🤖 🔧 🚦, each two columns of mark and GAUGE_W of gauge, one space apart.
A_SPLIT_W = 3 * (2 + GAUGE_W) + 2
A_LIMIT_W = 2 + LIM_FIG_W
# 🪫 one column wider than 🔋, for the decimal limit_pct adds at digits=4.
A_LIMIT_WEEK_W = A_LIMIT_W + 1
# ⛳ and five for the figure: dur_fmt's widest is four, and an overrun
# spends one more on its "+".  The cell's whole width, ⛳ measured on this
# terminal, is grid.cell_width("A_ETA_W").
A_ETA_FIG_W = 5
A_SPIN_W = 1
# 🧠's two fields, the size and its share of the agent's window: the status
# line's cell, "🧠 124k 12٪", with its widest share, "100٪".  The cell's
# whole width is grid.cell_width("A_CTX_W"), and 💾's, the status line's own
# cell unnarrowed, grid.cell_width("A_DIFF_W").
A_CTX_PCT_W = 4
# The 🤖 state trades its rate for how long the agent has written nothing
# once that is A_SILENT_S, and turns amber at A_SILENT_WARN_S: long enough
# that no tool round or request it is still waiting on explains it by itself.
# See render_doing.
A_SILENT_S, A_SILENT_WARN_S = QUIET_S, QUIET_WARN_S
# The most a worktree's branch spends of the label, 🌿 not counted.
A_BRANCH_W = 16
# The blanks between the label's name, branch and activity.
A_LABEL_GAP = 2
KIND_MARK = {"general-purpose":"🔩", "claude":"🎩", "Explore":"🔍", "Plan":"📐",
             "claude-code-guide":"📚", "statusline-setup":"📟", "fork":"🍴",
             "local_agent":"👥", "local_bash":"🐚", "local_workflow":"🔗",
             "remote_agent":"🌐", "in_process_teammate":"🎎"}
END_MARK = {"completed":E_MODE_DONE, "failed":E_MODE_FAILED, "killed":E_MODE_KILLED}
PAUSE_MARK = {"bash":E_MODE_SHELL, "monitor":E_MODE_MONITOR}

def token_rate(samples, status):
    if status != "running" or not isinstance(samples, list) or len(samples) < 2: return None
    try: first, last = float(samples[0]), float(samples[-1])
    except (TypeError, ValueError): return None
    return max(0.0, last - first) / (A_TICK_S * (len(samples) - 1))

def render_agent_limit(emoji, pct_s, share, colour, billed=True, dim=False, digits=3):
    """`emoji` and the agent's share of the window; `colour` names the row's
    F_* constant, as render_limit's does."""
    if not pct_s or fmt._pct_num(pct_s) is None or not billed: return []
    style = ink(colour, dim)
    w = LIM_FIG_W + digits - 3
    if share is None: fig = Span(pad_val(w, "?"), "F_CRM", True)
    elif share >= 99.5: fig = paint(style, pad_val(w, E_HUNDRED + E_PCT))
    else: fig = paint(style, pad_val(w, limit_pct(share, digits) + E_PCT))
    return [Span(emoji), fig]

def render_kind(agent_type, task_kind): return KIND_MARK.get(agent_type or task_kind, E_ROW_AGENTS)
def agent_state(status, usage=None, waiting_on=False):
    """The row's two state marks, `(phase, mode)`: see render_state.

    Running, the mode is who has the floor, in the ⌛ split's marks: 🚦 a
    question or an agent it is blocked on, 🔧 any other tool still waiting on
    its result, 🤖 the model; and none for a task with no transcript to say.
    Paused, it is what the agent waits on, in the order it is likeliest to
    be the thing that wakes it: 💤 its agents, then 💻 a background shell,
    📡 a Monitor, ⛳ only the ETA it gave (see parked); 🥚 is a task not
    started.  Ended, it is how: ✅ ❌ 🛑.  💥, paused or ended, is an agent
    whose last answer died on an API error.  A status never seen is its
    first two letters, which render_phase paints amber.
    """
    if status == "running":
        names = [n for _, n in (getattr(usage, "pending", ()) or ())]
        mode = ("" if getattr(usage, "eta", None) is None else
                E_WAIT if any(n in WAITING_TOOLS for n in names) else
                E_TOOL if names else E_WORK)
        return E_PHASE_RUN, mode
    if status == "pending":
        return E_PHASE_PAUSE, E_MODE_QUEUED
    if getattr(usage, "api_error", False) and status in ("completed", "failed"):
        # Claude Code calls an agent whose last request failed for good
        # completed, as if it had answered.  Paused or ended as it otherwise
        # is, but the mark says why it stopped.
        return (E_PHASE_PAUSE if parked(status, getattr(usage, "eta", None), waiting_on,
                                        getattr(usage, "background", ())) else E_PHASE_END,
                E_MODE_API_ERROR)
    if parked(status, getattr(usage, "eta", None), waiting_on, getattr(usage, "background", ())):
        kinds = [k for _, k in getattr(usage, "background", ()) or ()]
        return E_PHASE_PAUSE, (E_MODE_AGENTS if waiting_on else
                               next((PAUSE_MARK[k] for k in ("bash", "monitor") if k in kinds), E_MODE_ETA))
    if status in END_MARK:
        return E_PHASE_END, END_MARK[status]
    return (status[:2], "") if status else ("", "")
PHASES = (E_PHASE_RUN, E_PHASE_PAUSE, E_PHASE_END, "")
def render_state(status, usage=None, waiting_on=False):
    """The phase circle and the mode mark after it: see agent_state.

    Claude Code's status alone says completed both for an agent that has
    finished and for one that ended its turn to wait on work it started,
    so the circle is the phase read off everything the row knows — 🟢
    running, 🟡 paused, ⚫ ended — and the mark after it says what the agent
    is doing in it.  A status never seen is two amber letters and no mark.
    """
    phase, mode = agent_state(status, usage, waiting_on)
    return spans([_phase_span(phase), mode])
def render_phase(status, usage=None, waiting_on=False):
    """The phase circle alone: the mode is the 🛫 column's now, beside how
    long the agent has been in it; see render_doing."""
    return spans(_phase_span(agent_state(status, usage, waiting_on)[0]))
def _phase_span(phase):
    """The phase circle, or a status never seen in amber."""
    return Span(phase, None if phase in PHASES else "F_AMB")
def render_spin(status, usage=None):
    """A running agent's spinner, one frame on for each ⏺ it has written; see E_SPIN.

    Blank on any other row, and on one with no transcript to count in.
    """
    if status != "running" or getattr(usage, "eta", None) is None: return []
    frames = E_SPIN + E_SPIN[::-1]
    return [Span(frames[(getattr(usage, "blocks", 0) or 0) % len(frames)], "F_SPIN")]
def render_kids(n):
    """👶🏻 and how many agents hang under this row on the panel; see render_task_rows."""
    return [] if not n else [Span(E_KIDS), Span("%d" % n, "F_CRM")]
def render_agent_model(model_id, effort):
    if not model_id: return []
    return spans([E_MOD, Span(pad_val(2, model_spec(model_id)), "F_PUR"),
                  effort_glyph(effort) if effort and effort != "null" else ""])
def render_agent_cache(cache_pct):
    if cache_pct is None or cache_pct < 0: return []
    return [Span(E_CACHE), paint(cache_color(cache_pct), (E_HUNDRED if cache_pct >= 100 else pad_val(2, "%d" % cache_pct)) + E_PCT)]
def render_agent_ctx(ctx_tokens, window=0):
    """🧠, the agent's context size and its share of its own window, as the
    status line's cell draws the main thread's.  The share is blank where the
    payload gives no window; its column stays, so the cells after it hold."""
    if ctx_tokens <= 0: return []
    pct = "%d%s" % (int(ctx_tokens * 100 / window), E_PCT) if window > 0 else ""
    style = ink("F_PNK", mag_dim(ctx_tokens, MAG_TOK))
    return [Span(S_CTX), paint(style, pad_val(4, humanize(ctx_tokens))), Span(" "),
            paint(style, pad_val(A_CTX_PCT_W, pct))]
def render_compactions(n):
    """🤏 and how often the agent's window has been compacted; "" for never."""
    return [] if not n else [Span(E_ROW_COMPACT), Span("%d" % n, "F_PNK")]
def render_inbox(n):
    """📨 and how many messages wait for the agent's next tool round."""
    return [] if not n else [Span(E_INBOX), Span("%d" % n, "F_CYN")]
def background_count(status, usage, kind):
    """How many background tasks of `kind`, "bash" or "monitor", the agent
    started and has not heard the end of; 0 once it failed or was killed,
    whose tasks Claude Code stops with it and sends no word of."""
    if status in ("failed", "killed"): return 0
    return sum(1 for _, k in getattr(usage, "background", ()) or () if k == kind)
def render_background(mark, n):
    """💻 or 📡 and how many shells or Monitors it has running; "" for none.
    The paused mark says which one wakes it; this says how many there are,
    and says it while the agent is still running too."""
    return [] if not n else [Span(mark), Span("%d" % n, "F_CRM")]
def render_agent_diff(usage):
    """The agent's own +adds/-removes, in the status line's 💾 cell.

    Drawn even at "+0 -0", as the status line draws it: an agent that has
    changed nothing is a fact about the agent, and a cell that blanks on zero
    would make the panel's rows disagree about what an empty column means.
    A task with no transcript to count — a shell, a remote agent — is blanked
    by the caller, the way 💰 is.
    """
    return render_diff("%d" % getattr(usage, "lines_added", 0),
                       "%d" % getattr(usage, "lines_removed", 0))
def agent_elapsed(start_ms, now, end=None, first=None):
    """Seconds from the agent's first record, `first`, or its startTime, to
    now or to `end`, where a finished agent stopped; None with neither.  A
    PARKED agent has not finished, and the caller passes no `end` for it:
    see parked.

    The earlier of the two starts, because Claude Code sets startTime afresh
    when it resumes an agent: a two-hour agent SendMessage woke 25 minutes
    ago has a startTime 25 minutes old, and its first working span, off its
    transcript, is still two hours back.  The time it sat finished between
    the two is in the figure, and render_agent_split gives it to 🚦.
    """
    starts = [] if first is None else [first]
    try: starts.append(float(start_ms)/1000.0)
    except (TypeError, ValueError): pass
    if not starts: return None
    t0 = min(starts)
    t = time.time() if now is None else now
    if end is not None: t = min(t, max(end, t0))
    return max(0.0, t - t0)
def render_agent_elapsed(start_ms, now, end=None, first=None):
    """⌛ and the agent's age; see agent_elapsed.

    Its whole life, where the 🤖 before it until 2026-09-27 was the life less
    its tools: the split is render_agent_split's now, drawn after it as
    shares, so the one figure left is the one no share can be read without.
    """
    run = agent_elapsed(start_ms, now, end, first)
    if run is None: return []
    return [Span(E_IDLE), Span(pad_val(4, dur_fmt(run)), "F_PRW", mag_dim(run, MAG_DUR_S))]
def gauge_dots(parts, dots=4*GAUGE_W):
    """`parts` shared out as whole dots that always sum to `dots`.

    Largest remainder, so the gauges on a row read as one whole split three
    ways, ties going to the earlier part.  A part of at least 1% that rounds
    to nothing is raised to one dot, taken from the largest, so "a little"
    never reads as "none"; under 1% it is the noise two clocks read off
    different records leave behind, and stays blank.
    """
    total = sum(parts)
    if total <= 0: return [0] * len(parts)
    exact = [dots * p / total for p in parts]
    n = [int(x) for x in exact]
    for i in sorted(range(len(parts)), key=lambda i: n[i] - exact[i])[:dots - sum(n)]:
        n[i] += 1
    for i, p in enumerate(parts):
        if n[i] == 0 and p >= 0.01 * total:
            n[n.index(max(n))] -= 1
            n[i] = 1
    return n
def render_gauge(mark, secs, n):
    """`mark` and `n` dots of E_GAUGE, dim under MAG_DUR_S of its own seconds
    the way every duration on the row is."""
    cells = "".join(E_GAUGE[max(0, min(4, n - 4 * k))] for k in range(GAUGE_W))
    return [Span(mark), Span(cells, "F_PRW", mag_dim(secs, MAG_DUR_S))]
def render_agent_split(elapsed, model_s, tool_s=0.0):
    """🤖 🔧 🚦, each with a gauge of its share of the agent's ⌛.

    🤖 is its working time outside its own tools and 🔧 its time inside
    them, both its own alone (agent_clock), and 🚦 whatever of ⌛ is left:
    a question put to the reader, an agent it started, in the foreground or
    the background, the time it sat parked or finished before something
    woke it.  The status line's ⌛ row splits the main thread by the same
    rule, thread_clock, in the same order, and prints figures where this
    prints shares: the panel has one column of time to spare, and ⌛ is in
    it.

    The two figures come off records and ⌛ off the task's clock as well, so
    they can overrun it by a stamp's worth; the shares are then of their sum
    and 🚦 is empty.  Blank with no transcript to read the split from — a
    shell, a remote agent — where ⌛ alone is still drawn.
    """
    if model_s is None or elapsed is None: return []
    model_s, tool_s = max(0.0, model_s), max(0.0, tool_s or 0.0)
    parts = (model_s, tool_s, max(0.0, elapsed - model_s - tool_s))
    out = []
    for m, s, n in zip((E_WORK, E_TOOL, E_WAIT), parts, gauge_dots(parts)):
        out += ([Span(" ")] if out else []) + render_gauge(m, s, n)
    return out
def parked(status, eta, waiting_on=False, background=()):
    """Whether a task Claude Code calls completed is only waiting.

    An agent that ends its turn to wait on background work is marked
    completed while it waits, and its clock has to keep running through the
    wait, or ⌛ stops where its last record did and the wait is counted
    nowhere.  Claude Code knows what it waits on and the payload does not
    say, so this reads it back: an agent under it on the panel still
    running or not started, a background shell or Monitor it started and
    has not heard the end of (scan_background), or an ETA still live in its
    last message (live_eta).
    """
    return status == "completed" and (bool(eta) or waiting_on or bool(background))
def running_parents(prepared_tasks):
    """The ids with an agent running or not yet started anywhere under them on the panel."""
    parent = {str(t["id"]): str((m or {}).get("parentAgentId") or "")
              for t, _, m, _ in prepared_tasks if isinstance(t, dict) and t.get("id")}
    out = set()
    for t, _, _, _ in prepared_tasks:
        if isinstance(t, dict) and t.get("id") and t.get("status") in ("running", "pending"):
            up, seen = parent.get(str(t["id"]), ""), set()
            while up and up not in seen:
                seen.add(up)
                out.add(up)
                up = parent.get(up, "")
    return out
def render_agent_eta(eta, start_ms, now, status="running", end=None, signed_off=False):
    """⛳ and how long the agent says it has left; see eta_reading.

    Past its estimate the figure turns amber with a "+": the agent is late by
    that much and has not said so.  A last report of zero reads 0s, then
    counts up late the same way while the agent keeps going, but in bright
    red: `signed_off` says the zero is the finish the figure counts to, so
    the agent said it was done and is running over.  With no live
    estimate the cell is "?" — no report yet, or a run that completed — and
    never a manufactured "0s": an agent that has not said is not an agent
    with nothing left.  A task with no transcript to say it in draws nothing, the
    way every other cell on its row does.
    """
    got = eta_reading(eta, start_ms, now, status, end)
    if got is None:
        return []
    if not got:
        return [Span(E_ETA), Span(pad_val(A_ETA_FIG_W, "?"), "F_ETA", True)]
    left = got[1]
    if left < 0:
        return [Span(E_ETA), Span(pad_val(A_ETA_FIG_W, "+" + dur_fmt(-left)),
                                  "F_OVER" if signed_off else "F_AMB")]
    return [Span(E_ETA), Span(pad_val(A_ETA_FIG_W, dur_fmt(left)), "F_ETA",
                              mag_dim(left, MAG_DUR_S))]
def render_agent_rate(rate, mark=E_RATE):
    return [] if rate is None else [Span(mark + " "), Span(pad_val(3, rate_fig(rate)) + "/s", "F_RATE", mag_dim(rate, MAG_RATE))]
def state_since(status, usage, phase, mode, task=None):
    """The epoch the agent entered the state `mode` names, or None.

    Running, it is the oldest call it is waiting on, for 🚦 among the
    WAITING_TOOLS and for 🔧 among the rest, and its last record for 🤖:
    the request it has out went after it.  Paused, it is its last record,
    the end of the turn it ended to wait, and ended, likewise: how long ago
    it finished, which says how stale the row is.  Not started, it is the
    task's startTime.  None where the row has no transcript to say.
    """
    pending = getattr(usage, "pending", ()) or ()
    if status == "running":
        if mode == E_WAIT:
            starts = [t for t, n in pending if n in WAITING_TOOLS]
        elif mode == E_TOOL:
            starts = [t for t, n in pending if n not in WAITING_TOOLS]
        elif mode == E_WORK:
            starts = [getattr(usage, "last_seen", None)]
        else:
            starts = []
        starts = [t for t in starts if t is not None]
        return min(starts) if starts else None
    if status == "pending":
        try: return float((task or {}).get("startTime")) / 1000.0
        except (TypeError, ValueError): return None
    if phase in (E_PHASE_PAUSE, E_PHASE_END):
        return (getattr(usage, "last_seen", None)
                or getattr(usage, "last_epoch", None))
    return None
def render_doing(status, usage, waiting_on=False, rate=None, now=None, task=None):
    """What the agent is doing, and for how long: the mode mark agent_state
    reads, then the time since state_since: the row's 🛫 column, the grid's
    `rate` — "🔧  42s " where a rate reads "🛫 200/s", a space after the mark
    either way.  The unit stands where the rate's "/" does,
    so the figures stack down the panel.

    🤖 keeps the rate while the agent's records keep landing: the figure
    says it is moving and how fast.  Once it has written nothing for
    A_SILENT_S the figure is how long it has been quiet instead, amber from
    A_SILENT_WARN_S — the reading 🔇 drew in a cell of its own until
    2026-10-05.  A row with no mode, a shell, keeps the rate under 🛫.
    """
    phase, mode = agent_state(status, usage, waiting_on)
    if not mode:
        return render_agent_rate(rate)
    t = time.time() if now is None else now
    since = state_since(status, usage, phase, mode, task)
    secs = None if since is None else max(0.0, t - since)
    fig_w = A_RATE_W - vis_width(mode) - 2
    if mode == E_WORK and status == "running" and rate is not None and (
            secs is None or secs < A_SILENT_S):
        return render_agent_rate(rate, mode)
    if secs is None:
        return [Span(mode)]
    style = (ink("F_AMB") if mode == E_WORK and secs >= A_SILENT_WARN_S
             else ink("F_PRW", mag_dim(secs, MAG_DUR_S)))
    return [Span(mode + " "), paint(style, pad_val(fig_w, dur_fmt(secs)) + " ")]
def spawn_depth(task, meta):
    """1 for a task the session started, 2 for one an agent started, and so on."""
    try: return max(1, int(meta.get("spawnDepth") or task.get("spawnDepth") or 1))
    except (TypeError, ValueError): return 1

def tree_shape(prepared_tasks):
    """Each task id's parent and depth as the panel draws them: `{id: (parent, depth)}`.

    The sidecars' `parentAgentId`, resolved the way Claude Code's panel
    resolves it.  An ancestor that has finished and waits on nothing is
    stepped over, and the row hangs from the next one up: the panel drops
    such an agent and moves its children to its parent.  An ancestor not in
    the payload ends the walk, and the row is top level, since the payload
    lists every agent the panel can show.  The panel's own test for
    "waits on nothing" reads state the payload does not carry, so this takes
    parked's for it: completed, with no live ETA and nothing under it
    running.  The depth counts the ancestors left, 1 for a top-level row.
    """
    rows = {str(t["id"]): (t, u, m or {}) for t, u, m, _ in prepared_tasks
            if isinstance(t, dict) and t.get("id")}
    busy = running_parents(prepared_tasks)
    raw = {tid: str(m.get("parentAgentId") or "") for tid, (_, _, m) in rows.items()}
    def done(tid):
        t, u, _ = rows[tid]
        status = str(t.get("status") or "")
        return status == "completed" and not parked(status, getattr(u, "eta", None), tid in busy,
                                                    getattr(u, "background", ()))
    def up(tid):
        p, seen = raw[tid], {tid}
        while p in rows and p not in seen:
            if not done(p): return p
            seen.add(p)
            p = raw[p]
        return ""
    parent = {tid: up(tid) for tid in rows}
    out = {}
    for tid in rows:
        depth, p, seen = 1, parent[tid], {tid}
        while p and p not in seen:
            seen.add(p)
            depth, p = depth + 1, parent[p]
        out[tid] = (parent[tid], depth)
    return out

def inherited_etas(prepared_tasks):
    """Each task's ETA, pushed out to the latest finish below it on the panel.

    A parent is not done until the children it is waiting on are, so a row's
    ⛳ counts to the latest of its own finish and every running
    descendant's, recursively — and its own wins when its own work runs
    longer.  Agents report their own work only (the skill says so), which
    is what makes this sum honest rather than double.  A killed or failed
    descendant counts for nothing.  A completed one counts only while its
    transcript still holds a live ETA, which is an agent parked on
    background work (see live_eta); one that finished has nothing left.
    The tree is the sidecars' `parentAgentId`, as tree_shape reads it; a
    task whose parent is not on the panel is a root.
    """
    rows = {str(t["id"]): (t, u, m or {}) for t, u, m, _ in prepared_tasks
            if isinstance(t, dict) and t.get("id")}
    kids = {}
    for tid, (_, _, m) in rows.items():
        p = str(m.get("parentAgentId") or "")
        if p in rows:
            kids.setdefault(p, []).append(tid)
    memo = {}
    def finish(tid, seen=()):
        if tid in memo: return memo[tid]
        t, u, _ = rows[tid]
        own = (eta_finish(getattr(u, "eta", None) or ())
               if str(t.get("status") or "") not in ("killed", "failed") else None)
        ends = [own] + [finish(k, seen + (tid,)) for k in kids.get(tid, ()) if k not in seen]
        ends = [e for e in ends if e is not None]
        memo[tid] = max(ends) if ends else None
        return memo[tid]
    out = {}
    for tid, (t, u, _) in rows.items():
        try: start = float(t.get("startTime")) / 1000.0
        except (TypeError, ValueError): start = None
        out[tid] = inherit_eta(getattr(u, "eta", None),
                               [finish(k) for k in kids.get(tid, ())], start)
    return out

# The cells each scope's rows can carry, as agents/plans/redesign.md's
# "Where each row's figures come from" has them: the band's 💳, 🎤, 🤖💬 and
# 🎮 rows, the receipt's 📊 🎤 and 📊 🎮 (scopes turn and session again), and
# an agent's.  The panel lays its rows out over a template of each, a row
# with no label and every cell it can carry, empty, so that it reaches the
# columns the mod reaches from the same width and --hide without either
# drawing the other's rows; see grid.layout.  Templates rather than the mod's
# own rows, whose figures the panel never reads: only which keys a row holds,
# and its scope for --hide, decide the columns.
SCOPE_CELLS = (
    ("account", ("five", "week")),
    ("turn", ("cost", "ctx", "tok", "cache", "clock", "eta", "split", "five",
              "week", "diff")),
    ("main", tuple(c["key"] for c in GRID_CELLS)),
    ("session", ("cost", "tok", "cache", "clock", "split", "five", "week",
                 "diff")),
    ("agent", tuple(c["key"] for c in GRID_CELLS)),
)


def possible_rows():
    """The templates of SCOPE_CELLS, as grid rows."""
    return [grid.Row(scope, (), {k: () for k in keys})
            for scope, keys in SCOPE_CELLS]


def panel_layout(cols=None, hide=()):
    """`(cols, keys)`: the terminal width a row is drawn for, and the
    columns every row draws there, as GRID_CELLS keys.

    `cols` is the terminal's width, which the caller works out from the
    payload's `columns` and PANEL_COLUMNS_SHORT; the chrome Claude Code draws
    before a row counts toward it.  With no width known, it is the narrowest
    that drops no column: every column --hide leaves, and LABEL_MIN for the
    label of a row CHROME_DEPTH deep.
    """
    rows = possible_rows()
    if not cols:
        keys = grid.layout(rows, 1 << 30, hide)
        room = {c["key"]: grid.cell_width(c["width"]) + c["gap"] for c in GRID_CELLS}
        cols = (RIGHT_EDGE + width(grid.chrome(CHROME_DEPTH)) + LABEL_MIN
                + sum(room[k] for k in keys))
    return cols, grid.layout(rows, cols, hide)


def agent_cells(task, usage, meta, shares, limits, now=None, eta=False, waiting_on=False):
    """The row's figures by GRID_CELLS key, each only where it has one: a
    key left out is a blank the label may run on over (grid.draw)."""
    status = str(task.get("status") or "")
    model = str(task.get("model") or "") or getattr(usage, "model", "") or str(meta.get("model") or "")
    light = shares.get("week") is not None and shares["week"] < MAG_SHARE_AGENT
    billed=bool(getattr(usage,"parts",()))
    live=status == "running" or parked(status, getattr(usage,"eta",None), waiting_on, getattr(usage,"background",()))
    # A finished row stops at its last billed stamp, else at its last working
    # span.  With neither, a finished shell or an agent killed before it
    # billed, there is nothing to stop at, and ⌛ is blank rather than a clock
    # counting a finished task up to now.
    end=None if live else (getattr(usage,"last_epoch",None)
                           or max((w[1] for w in getattr(usage,"work",()) or ()), default=None))
    clocked=live or end is not None
    # Where its transcript starts: its first working span, or the one still
    # open when it has closed none.  See agent_elapsed.
    firsts=[w[0] for w in (getattr(usage,"work",()) or ())[:1]]
    if getattr(usage,"open_at",None) is not None: firsts.append(usage.open_at)
    first=min(firsts) if firsts else None
    own_eta=getattr(usage,"eta",None)
    shown_eta=own_eta if eta is False else eta
    # Signed off: its own last report is zero and no descendant pushed the
    # finish past it, so the zero is what the figure counts to.
    signed_off=bool(own_eta) and own_eta[1] == 0 and bool(shown_eta) and eta_finish(shown_eta) <= eta_finish(own_eta) + 1e-6
    cells = (
        # The model and effort, right before the 💰 they priced.
        ("model", render_agent_model(model, str(task.get("effort") or "") or getattr(usage,"effort", ""))),
        # What it is doing and for how long, or its token rate: render_doing.
        ("rate", render_doing(status, usage, waiting_on, token_rate(task.get("tokenSamples"), status), now, task)),
        ("cost", render_cost("%.4f" % getattr(usage,"cost",0)) if billed else []),
        ("ctx", render_agent_ctx(getattr(usage,"ctx_tokens",0), getattr(usage,"ctx_window",0))),
        ("tok", render_tokens(getattr(usage,"tok_up",None), getattr(usage,"tok_down",0))),
        ("cache", render_agent_cache(getattr(usage,"cache_pct",-1))),
        # ⌛ ⛳ 🤖 🔧 🚦, right before the 5h and 1w it spent: how long it has
        # run, how long it says it has left, and how the run split — the
        # status line's ⌛ row in the same order, with shares where it has
        # figures.
        ("clock", render_agent_elapsed(task.get("startTime"), now, end, first) if clocked else []),
        ("eta", render_agent_eta(shown_eta, task.get("startTime"), now, status,
                                 getattr(usage,"last_epoch",None), signed_off)),
        ("split", render_agent_split(agent_elapsed(task.get("startTime"), now, end, first) if clocked else None,
                                     getattr(usage,"model_s",None), getattr(usage,"tool_s",0.0))),
        ("five", render_agent_limit(E_SESS, limits.session_pct, shares.get("sess"), "F_LIM_SESS", billed, light)),
        ("week", render_agent_limit(E_WEEK, limits.weekly_pct, shares.get("week"), "F_LIM_WEEK", billed, light, 4)),
        ("diff", render_agent_diff(usage) if billed else []))
    return {k: spans(v) for k, v in cells if spans(v)}


def agent_label(task, usage, meta, waiting_on=False, kids=0, kids_w=0, widths=None):
    """The row's label, as grid pieces under the agent scope.

    The kind's mark, with the spinner before it and the phase circle after
    (`name.kind`); the counts a panel draws only while some row needs one,
    each padded to the panel's widest so the names after them hold their
    column (`state.kids`, `state.compact`, `state.shells`, `state.monitors`,
    `state.inbox`); then the name (`name.label`), 🌿 and the branch of a
    worktree the agent works in apart from the session's
    (`workspace.branch`), and what it is doing (`chat.doing`).

    The kind, the name, the branch and the activity have no drop rank, as on
    the mockup's agent rows: a label too long for its room is cut from the
    end, the activity first, then the branch, then the name.  The counts
    leave whole before anything is cut, the quickest to pass first, so a
    narrow label keeps its name rather than the blanks that hold another
    row's 📨.  The steadiest stand first — 👶🏻 and 🤏 stay once they come;
    💻 and 📡 last as long as a shell or a Monitor runs; 📨 passes quickest
    — so the passing ones shift the fewest.
    """
    widths = widths or {}
    status, kind = str(task.get("status") or ""), str(task.get("type") or "")
    head = spans([seg(A_SPIN_W, render_spin(status, usage)),
                  render_kind(str(meta.get("agentType") or ""), kind),
                  seg(A_STATE_W, render_phase(status, usage, waiting_on)), " "])
    out = [grid.Piece("name.kind", head, 0)]
    for path, w, cell, drop in (
            ("state.kids", kids_w, render_kids(kids), 5),
            ("state.compact", widths.get("compact", 0), render_compactions(getattr(usage,"compactions",0)), 4),
            ("state.shells", widths.get("shells", 0), render_background(E_MODE_SHELL, background_count(status, usage, "bash")), 3),
            ("state.monitors", widths.get("monitors", 0), render_background(E_MODE_MONITOR, background_count(status, usage, "monitor")), 2),
            ("state.inbox", widths.get("inbox", 0), render_inbox(getattr(usage,"inbox",0)), 1)):
        if w: out.append(grid.Piece(path, seg(w, cell) + [Span(" ")], drop))
    desc=squash(str(task.get("description") or "")); name=str(task.get("name") or "") or desc; act=squash(str(task.get("label") or ""))
    if act == desc: act=""
    branch=str(getattr(usage,"branch","") or "")
    words = [(p, t, c) for p, t, c in (
        ("name.label", name, "F_BLU"),
        ("workspace.branch", E_GIT_OK + fit_cols(branch, A_BRANCH_W) if branch else "", "F_GRN"),
        ("chat.doing", act, "F_CHAT_B")) if t]
    for i, (path, text, colour) in enumerate(words):
        gap = [Span(" " * A_LABEL_GAP)] if i < len(words) - 1 else []
        out.append(grid.Piece(path, [Span(text, colour)] + gap, 0))
    return out


def render_agent_row(task, usage, meta, shares, limits, cols=None, now=None, eta=False,
                     waiting_on=False, depth=None, kids=0, kids_w=0, widths=None, hide=()):
    """Render one fully prepared task on the grid; it performs no reads or
    accounting.

    `cols` is the terminal's width, None where it is not known; see
    panel_layout.  `eta` is the ⛳ the row draws, its own where False; see
    inherited_etas.  `waiting_on` says an agent under it is still running;
    see parked.  `depth` is the row's depth as the panel draws it (see
    tree_shape), its own spawnDepth where None: Claude Code indents a nested
    row's chrome two columns a level, and the grid takes them from its
    label.  `kids` is how many rows hang under it, and `kids_w` the widest
    👶🏻 cell on the panel, 0 where no row has any, which drops the piece
    from all; `widths` holds the panel's widest 📨, 📡, 💻 and 🤏, as
    `kids_w` does 👶🏻's (panel_widths).  `hide` is the --hide paths.

    The chrome, "  ◯ " and its indent, is Claude Code's: the grid counts it
    toward the width, and it is not printed.  Nor is a copy of the panel's
    tree, which the design does not draw.
    """
    task, meta, shares = task or {}, meta or {}, shares or {}
    cols, keys = panel_layout(cols, hide)
    row = grid.Row("agent",
                   agent_label(task, usage, meta, waiting_on, kids, kids_w, widths),
                   agent_cells(task, usage, meta, shares, limits, now, eta, waiting_on),
                   spawn_depth(task, meta) if depth is None else depth)
    return rstrip(grid.draw(row, keys, cols, hide)[len(grid.chrome(row.depth)):])

def panel_widths(prepared_tasks, now=None):
    """The widest 📨, 📡, 💻 and 🤏 cell on the panel, each 0 where no row
    draws one.

    As 👶🏻's: a cell that no row needs costs no row a column, and one that
    any row needs is kept on every row, so the columns after it hold.
    """
    live = [(str(t.get("status") or ""), u) for t, u, _, _ in prepared_tasks
            if isinstance(t, dict) and t.get("id")]
    return {"inbox": max([vis_width(E_INBOX) + len(str(getattr(u, "inbox", 0)))
                          for _, u in live if getattr(u, "inbox", 0)] or [0]),
            "compact": max([vis_width(E_ROW_COMPACT) + len(str(getattr(u, "compactions", 0)))
                            for _, u in live if getattr(u, "compactions", 0)] or [0]),
            "shells": max([vis_width(E_MODE_SHELL) + len(str(background_count(st, u, "bash")))
                           for st, u in live if background_count(st, u, "bash")] or [0]),
            "monitors": max([vis_width(E_MODE_MONITOR) + len(str(background_count(st, u, "monitor")))
                             for st, u in live if background_count(st, u, "monitor")] or [0])}

def render_task_rows(prepared_tasks, limits, cols=None, now=None, hide=()):
    """Return `(task_id, row)` pairs for prepared `(task, usage, meta, shares)` facts.

    `cols` is the terminal's width, the payload's `columns` plus
    PANEL_COLUMNS_SHORT, and `hide` the --hide paths; see render_agent_row.
    """
    rows=[]
    shape=tree_shape(prepared_tasks)
    etas=inherited_etas(prepared_tasks)
    busy=running_parents(prepared_tasks)
    # 👶🏻 counts the rows hanging directly under each one, as tree_shape
    # resolves them, finished or not.  The panel's own count, the dim
    # " (+N)" after a collapsed row's name, is part of the row this line
    # replaces, so without 👶🏻 a decorated row says nothing of its children.
    kids={}
    for p, _ in shape.values():
        if p: kids[p]=kids.get(p, 0) + 1
    kids_w=max([vis_width(E_KIDS) + len(str(n)) for n in kids.values()] or [0])
    widths=panel_widths(prepared_tasks, now)
    for task, usage, meta, shares in prepared_tasks:
        if isinstance(task, dict) and task.get("id"):
            tid=str(task["id"])
            rows.append((tid, join(render_agent_row(task, usage, meta, shares, limits, cols, now, etas.get(tid, False), tid in busy, shape[tid][1], kids.get(tid, 0), kids_w, widths, hide))))
    return rows
