"""Pure Claude subagent-panel row layout.

Preparation (sidecar lookup, usage parsing, limits/source selection and JSON
serialization) belongs to orchestration.  This module only lays out supplied
task facts and returns strings.
"""
import time
from typing import Optional, Sequence

from . import formatting as fmt
from .formatting import *
from .claude_render import (render_cost, render_diff, render_tokens, model_spec,
                            effort_glyph, eta_reading,
                            inherit_eta)
from .claude_records import Limits, squash, eta_finish, WAITING_TOOLS

A_KIND_W, A_ID_W, A_STATE_W = 2, 10, 4
A_HEAD_GAP, A_NAME_MIN, A_ACT_MIN, A_CLOCK_W, A_RATE_W, A_GAP, A_TICK_S = 1, 8, 8, 6, 7, 2, 5.0
# 🤖 🔧 🚦, each two columns of mark and GAUGE_W of gauge, one space apart.
A_SPLIT_W = 3 * (2 + GAUGE_W) + 2
A_LIMIT_W, A_TREE_W = 2 + LIM_FIG_W, 2
# ⛳ and five for the figure: dur_fmt's widest is four, and an overrun
# spends one more on its "+".
A_ETA_FIG_W = 5
A_ETA_W = vis_width(E_ETA) + A_ETA_FIG_W
A_SPIN_W = 1
# The name room a row must still have after paying for the tree beside its
# right group.  The copy is for a wide window, where the panel's own tree is
# far from the figures; in a narrow one the two are close, and the activity
# is the better use of the columns.
A_TREE_ROOM = 40
# 💾 and the eleven columns render_diff lays after it: a blank, two signs
# and two figures of four.  The status line's own cell, unnarrowed — the
# pair means the same thing on both readouts and reads as one shape.
A_DIFF_W = vis_width(S_DIFF) + 11
# 🧠's two fields, the size and its share of the agent's window: the status
# line's cell, "🧠 124k 12٪", with its widest share, "100٪".
A_CTX_PCT_W = 4
A_CTX_W = vis_width(S_CTX) + 4 + 1 + A_CTX_PCT_W
# 🔇 draws once a running agent has written nothing for A_SILENT_S, and turns
# amber at A_SILENT_WARN_S: long enough that no tool round or request it is
# still waiting on explains it by itself.
A_SILENT_S, A_SILENT_WARN_S = 60.0, 600.0
A_SILENT_W = vis_width(E_SILENT) + 4
# The most a worktree's branch spends of the name's room, 🌿 not counted.
A_BRANCH_W = 16
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

def render_agent_limit(emoji, pct_s, share, colour, billed=True, dim=False):
    if not pct_s or fmt._pct_num(pct_s) is None or not billed: return ""
    colour = DIM + colour if dim else colour
    if share is None: fig = "%s%s%s" % (DIM + F_CRM, pad_val(LIM_FIG_W, "?"), R)
    elif share >= 99.5: fig = "%s%s%s" % (colour, pad_val(LIM_FIG_W, E_HUNDRED + E_PCT), R)
    else: fig = "%s%s%s" % (colour, pad_val(LIM_FIG_W, limit_pct(share) + E_PCT), R)
    return emoji + fig

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
    whose last answer died on an API error.
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
    return ("%s%s%s" % (F_AMB, status[:2], R), "") if status else ("", "")
def render_state(status, usage=None, waiting_on=False):
    """The phase circle and the mode mark after it: see agent_state.

    Claude Code's status alone says completed both for an agent that has
    finished and for one that ended its turn to wait on work it started,
    so the circle is the phase read off everything the row knows — 🟢
    running, 🟡 paused, ⚫ ended — and the mark after it says what the agent
    is doing in it.  A status never seen is two amber letters and no mark.
    """
    return "".join(agent_state(status, usage, waiting_on))
def render_spin(status, usage=None):
    """A running agent's spinner, one frame on for each ⏺ it has written; see E_SPIN.

    Blank on any other row, and on one with no transcript to count in.
    """
    if status != "running" or getattr(usage, "eta", None) is None: return ""
    frames = E_SPIN + E_SPIN[::-1]
    return "%s%s%s" % (F_SPIN, frames[(getattr(usage, "blocks", 0) or 0) % len(frames)], R)
def render_kids(n):
    """👶🏻 and how many agents hang under this row on the panel; see render_task_rows."""
    return "" if not n else "%s%s%d%s" % (E_KIDS, F_CRM, n, R)
def render_agent_model(model_id, effort):
    if not model_id: return ""
    return "%s%s%s%s%s" % (E_MOD, F_PUR, pad_val(2, model_spec(model_id)), R, effort_glyph(effort) if effort and effort != "null" else "")
def render_agent_cache(cache_pct):
    if cache_pct is None or cache_pct < 0: return ""
    return "%s%s%s%s%s" % (E_CACHE, cache_color(cache_pct), E_HUNDRED if cache_pct >= 100 else pad_val(2, "%d" % cache_pct), E_PCT, R)
def render_agent_ctx(ctx_tokens, window=0):
    """🧠, the agent's context size and its share of its own window, as the
    status line's cell draws the main thread's.  The share is blank where the
    payload gives no window; its column stays, so the cells after it hold."""
    if ctx_tokens <= 0: return ""
    pct = "%d%s" % (int(ctx_tokens * 100 / window), E_PCT) if window > 0 else ""
    return "%s%s%s%s %s%s%s" % (S_CTX, mag_dim(ctx_tokens, MAG_TOK) + F_PNK, pad_val(4, humanize(ctx_tokens)), R,
                                F_PNK, pad_val(A_CTX_PCT_W, pct), R)
def render_compactions(n):
    """🤏 and how often the agent's window has been compacted; "" for never."""
    return "" if not n else "%s%s%d%s" % (E_ROW_COMPACT, F_PNK, n, R)
def render_inbox(n):
    """📨 and how many messages wait for the agent's next tool round."""
    return "" if not n else "%s%s%d%s" % (E_INBOX, F_CYN, n, R)
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
    return "" if not n else "%s%s%d%s" % (mark, F_CRM, n, R)
def silence(status, usage, now):
    """Seconds a running agent has written nothing, once that is A_SILENT_S
    or more; None otherwise.  A tool round, a request, a progress line: any
    stamped record ends a silence.  Not while it waits on a question or an
    agent it started, the 🚦 its state already shows: that wait writes
    nothing for as long as it lasts, and is not the agent stalling."""
    last = getattr(usage, "last_seen", None)
    if status != "running" or last is None: return None
    if any(n in WAITING_TOOLS for _, n in getattr(usage, "pending", ()) or ()): return None
    quiet = (time.time() if now is None else now) - last
    return quiet if quiet >= A_SILENT_S else None
def render_silence(quiet):
    """🔇 and how long; dim until A_SILENT_WARN_S, amber from there."""
    if quiet is None: return ""
    return "%s%s%s%s" % (E_SILENT, F_AMB if quiet >= A_SILENT_WARN_S else DIM + F_CRM,
                         pad_val(A_SILENT_W - vis_width(E_SILENT), dur_fmt(quiet)), R)
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
    if run is None: return ""
    return "%s%s%s%s" % (E_IDLE, mag_dim(run, MAG_DUR_S) + F_PRW, pad_val(4, dur_fmt(run)), R)
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
    return "%s%s%s%s" % (mark, mag_dim(secs, MAG_DUR_S) + F_PRW, cells, R)
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
    if model_s is None or elapsed is None: return ""
    model_s, tool_s = max(0.0, model_s), max(0.0, tool_s or 0.0)
    parts = (model_s, tool_s, max(0.0, elapsed - model_s - tool_s))
    return " ".join(render_gauge(m, s, n) for m, s, n in
                    zip((E_WORK, E_TOOL, E_WAIT), parts, gauge_dots(parts)))
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
        return ""
    if not got:
        return "%s%s%s%s" % (E_ETA, DIM + F_ETA, pad_val(A_ETA_FIG_W, "?"), R)
    left = got[1]
    if left < 0:
        return "%s%s%s%s" % (E_ETA, F_OVER if signed_off else F_AMB,
                             pad_val(A_ETA_FIG_W, "+" + dur_fmt(-left)), R)
    return "%s%s%s%s" % (E_ETA, mag_dim(left, MAG_DUR_S) + F_ETA,
                         pad_val(A_ETA_FIG_W, dur_fmt(left)), R)
def render_agent_rate(rate):
    return "" if rate is None else "%s%s%s/s%s" % (E_RATE, mag_dim(rate, MAG_RATE) + F_RATE, pad_val(3, rate_fig(rate)), R)
def render_who(name, act, room, branch=""):
    """The name, then 🌿 and the branch of a worktree the agent works in
    apart from the session's, then what it is doing, in that order of claim
    on `room`.  The first is cut to fit; the branch is drawn whole or not at
    all; the activity needs A_ACT_MIN."""
    tag = E_GIT_OK + fit_cols(branch, A_BRANCH_W) if branch else ""
    out, left = [], room
    for col, text, least in ((F_BLU, name, 0), (F_GRN, tag, None), (F_CHAT_B, act, A_ACT_MIN)):
        if not text: continue
        have = left - (A_HEAD_GAP if out else 0)
        if not out: text = fit_cols(text, have)
        elif least is None:
            if have < vis_width(text): continue
        elif have < least: continue
        else: text = fit_cols(text, have)
        out.append("%s%s%s" % (col, text, R))
        left = have - vis_width(text)
    return (" " * A_HEAD_GAP).join(out)

def tree_cols(task, meta, depth=None):
    """The columns the panel spends before a NESTED row, which `cols` is not net of.

    The payload's width is already net of the panel's chrome for a row the
    session itself started — the ◯ pointer and two columns after it — and says
    nothing about the `├ ` the panel draws for a row under another agent, one
    per level of nesting and before the pointer.  Left unpaid, a child's right
    group runs A_TREE_W past the edge its parent's lands on and the panel cuts
    the 🪫 cell off to get the row back inside the terminal.  `depth` is the
    row's depth as the panel draws it (see tree_shape); without one it is the
    agent's own `spawnDepth`, 1 for a task the session started, and a task
    with no sidecar (a shell, a remote agent) hangs off nothing and pays
    nothing.
    """
    return A_TREE_W * ((spawn_depth(task, meta) if depth is None else depth) - 1)

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

def tree_marks(prepared_tasks, shape=None):
    """The panel's tree, drawn again for each task id: `⏺`, `├ ◯`, `│ └ ◯`.

    Only as much of it as the sidecars say, with each row's parent and depth
    from tree_shape.  A child is the last of its siblings when none started
    after it, which is the panel's order: siblings by `startTime`, the
    payload's order breaking a tie.  An ancestor carries a `│` down its
    column while one of its own siblings is still to come.

    The panel marks the row the cursor is on with `❯ ⏺`, and the payload does
    not say which row that is.  But the panel shows a row's children only once
    that row is expanded, and only the selected row is, so a row with a child
    on the panel takes the filled `⏺`.  The `❯` goes in the gutter left of the
    panel's tree, which the copy has no counterpart for.
    """
    shape = tree_shape(prepared_tasks) if shape is None else shape
    tasks = [t for t, _, _, _ in prepared_tasks if isinstance(t, dict) and t.get("id")]
    def started(t):
        try: return float(t.get("startTime") or 0)
        except (TypeError, ValueError): return 0.0
    order = [str(t["id"]) for _, t in sorted(enumerate(tasks), key=lambda it: (started(it[1]), it[0]))]
    parent = {tid: shape[tid][0] for tid in order}
    open_ = set(parent.values())
    last = {tid: not any(parent[q] == parent[tid] for q in order[i + 1:]) for i, tid in enumerate(order)}
    out = {}
    for tid in order:
        p, depth = shape[tid]
        marks, up = [E_TREE_END if last[tid] else E_TREE_MID] if depth > 1 else [], p
        for _ in range(depth - 2):
            marks.append(" " if last.get(up, True) else E_TREE_BAR)
            up = parent.get(up, "")
        out[tid] = " ".join(list(reversed(marks)) + [E_TREE_OPEN if tid in open_ else E_TREE_NODE])
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
    The tree is the sidecars' `parentAgentId`, as tree_marks reads it; a
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

def render_agent_row(task, usage, meta, shares, limits, cols=None, now=None, tree="", tree_w=0,
                     eta=False, waiting_on=False, depth=None, kids=0, kids_w=0, lead=0,
                     widths=None):
    """Render one fully prepared task; it performs no reads or accounting.

    `tree` is this row's copy of the panel's tree and `tree_w` the widest
    copy on the panel, which every row pads to so the right groups still
    share their columns.  It opens the right group, and only when the
    name keeps A_TREE_ROOM after paying for it.  Every row has the same
    room, so the panel draws the copy on all of its rows or on none.
    `waiting_on` says an agent under it is still running; see parked.
    `depth` is the row's depth as the panel draws it; see tree_shape.
    `kids` is how many rows hang under it, and `kids_w` the widest 👶🏻 cell
    on the panel, 0 where no row has any, which drops the cell from all.
    `lead` is the blank a row opens with so that its cells start where the
    deepest row's do; see render_task_rows.  `widths` holds the panel's
    widest 🔇, 📨, 📡, 💻 and 🤏 cells, as `kids_w` does 👶🏻's; see panel_widths.
    """
    task, meta, shares, widths = task or {}, meta or {}, shares or {}, widths or {}
    if cols: cols = max(0, cols - tree_cols(task, meta, depth) - lead)
    tid, status, kind = str(task.get("id") or ""), str(task.get("status") or ""), str(task.get("type") or "")
    model = str(task.get("model") or "") or getattr(usage, "model", "") or str(meta.get("model") or "")
    light = shares.get("week") is not None and shares["week"] < MAG_SHARE_AGENT
    gap=" " * A_GAP
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
    eta_args=(shown_eta, task.get("startTime"), now, status, getattr(usage,"last_epoch",None), signed_off)
    right=gap.join(seg(w,c) for w,c in (
        # The model and effort, right before the 💰 they priced.
        (6, render_agent_model(model, str(task.get("effort") or "") or getattr(usage,"effort", ""))),
        (vis_width(S_COST)+4, render_cost("%.4f" % getattr(usage,"cost",0)) if billed else ""),
        (A_CTX_W, render_agent_ctx(getattr(usage,"ctx_tokens",0), getattr(usage,"ctx_window",0))),
        (vis_width(S_TOK)+VAL_W+VAL2_W, render_tokens(getattr(usage,"tok_up",None), getattr(usage,"tok_down",0))),
        (A_RATE_W, render_agent_rate(token_rate(task.get("tokenSamples"),status))),
        (5, render_agent_cache(getattr(usage,"cache_pct",-1))),
        # ⌛ ⛳ 🤖 🔧 🚦, one space apart as one segment, right before the
        # 5h and 1w it spent: how long it has run, how long it says it has
        # left, and how the run split — the status line's ⌛ row in the same
        # order, with shares where it has figures.
        (A_CLOCK_W + A_ETA_W + A_SPLIT_W + 2,
         seg(A_CLOCK_W, render_agent_elapsed(task.get("startTime"), now, end, first) if clocked else "") + " "
         + seg(A_ETA_W, render_agent_eta(*eta_args)) + " "
         + render_agent_split(agent_elapsed(task.get("startTime"), now, end, first) if clocked else None,
                              getattr(usage,"model_s",None), getattr(usage,"tool_s",0.0))),
        (A_LIMIT_W, render_agent_limit(E_SESS, limits.session_pct, shares.get("sess"), F_LIM_SESS, billed, light)),
        (A_LIMIT_W, render_agent_limit(E_WEEK, limits.weekly_pct, shares.get("week"), F_LIM_WEEK, billed, light)),
        (A_DIFF_W, render_agent_diff(usage) if billed else "")) if w)
    desc=squash(str(task.get("description") or "")); name=str(task.get("name") or "") or desc; act=squash(str(task.get("label") or ""))
    if act == desc: act=""
    # The cells a panel draws only while some row needs one sit together,
    # right after the kind and state, which keep their column however many
    # of them the panel draws; what comes and goes moves only the id, the
    # name and nothing of the right group.  The steadiest first — 👶🏻 and 🤏
    # stay once they come; 💻 and 📡 last as long as a shell or a Monitor
    # runs; 📨 and 🔇 pass quickest — so the passing ones shift the fewest.
    head=(" "*A_HEAD_GAP).join(seg(w,c) for w,c in ((A_SPIN_W+A_KIND_W+A_STATE_W, seg(A_SPIN_W, render_spin(status, usage))+render_kind(str(meta.get("agentType") or ""),kind)+render_state(status, usage, waiting_on)),
                                                     (kids_w, render_kids(kids)),
                                                     (widths.get("compact", 0), render_compactions(getattr(usage,"compactions",0))),
                                                     (widths.get("shells", 0), render_background(E_MODE_SHELL, background_count(status, usage, "bash"))),
                                                     (widths.get("monitors", 0), render_background(E_MODE_MONITOR, background_count(status, usage, "monitor"))),
                                                     (widths.get("inbox", 0), render_inbox(getattr(usage,"inbox",0))),
                                                     (widths.get("silent", 0), render_silence(silence(status, usage, now))),
                                                     (A_ID_W, DIM+F_BLU2+fit_cols(tid,A_ID_W)+R)) if w)
    room=A_NAME_MIN if not cols else max(A_NAME_MIN, cols-vis_width(strip_ansi(head))-A_HEAD_GAP-vis_width(strip_ansi(right))-A_GAP)
    branch=str(getattr(usage,"branch","") or "")
    # Decided on the room a row would have with neither the panel's indent
    # nor the lead: those add up to the same on every row, and deciding on
    # its own room would drop the copy from some rows alone in a window a
    # few columns past the line.
    if tree and room + tree_cols(task, meta, depth) + lead - tree_w - A_HEAD_GAP >= A_TREE_ROOM:
        room -= tree_w + A_HEAD_GAP
        right = seg(tree_w, DIM + tree + R) + " " * A_HEAD_GAP + right
    return (" "*lead+head+" "*A_HEAD_GAP+seg(room,render_who(name,act,room,branch))+gap+right).rstrip()

def panel_widths(prepared_tasks, now=None):
    """The widest 🔇, 📨, 📡, 💻 and 🤏 cell on the panel, each 0 where no row
    draws one.

    As 👶🏻's: a cell that no row needs costs no row a column, and one that
    any row needs is kept on every row, so the columns after it hold.
    """
    live = [(str(t.get("status") or ""), u) for t, u, _, _ in prepared_tasks
            if isinstance(t, dict) and t.get("id")]
    return {"silent": A_SILENT_W if any(silence(st, u, now) is not None for st, u in live) else 0,
            "inbox": max([vis_width(E_INBOX) + len(str(getattr(u, "inbox", 0)))
                          for _, u in live if getattr(u, "inbox", 0)] or [0]),
            "compact": max([vis_width(E_ROW_COMPACT) + len(str(getattr(u, "compactions", 0)))
                            for _, u in live if getattr(u, "compactions", 0)] or [0]),
            "shells": max([vis_width(E_MODE_SHELL) + len(str(background_count(st, u, "bash")))
                           for st, u in live if background_count(st, u, "bash")] or [0]),
            "monitors": max([vis_width(E_MODE_MONITOR) + len(str(background_count(st, u, "monitor")))
                             for st, u in live if background_count(st, u, "monitor")] or [0])}

def render_task_rows(prepared_tasks, limits, cols=None, now=None):
    """Return `(task_id, row)` pairs for prepared `(task, usage, meta, shares)` facts."""
    rows=[]
    shape=tree_shape(prepared_tasks)
    trees=tree_marks(prepared_tasks, shape)
    etas=inherited_etas(prepared_tasks)
    busy=running_parents(prepared_tasks)
    tree_w=max([vis_width(t) for t in trees.values()] or [0])
    # 👶🏻 counts the rows hanging directly under each one, as tree_shape
    # resolves them, finished or not.  The panel's own count, the dim
    # " (+N)" after a collapsed row's name, is part of the row this line
    # replaces, so without 👶🏻 a decorated row says nothing of its children.
    kids={}
    for p, _ in shape.values():
        if p: kids[p]=kids.get(p, 0) + 1
    kids_w=max([vis_width(E_KIDS) + len(str(n)) for n in kids.values()] or [0])
    # The panel indents a nested row by its `├ ` and nothing else, so a
    # parent's cells started A_TREE_W left of its children's and the kind,
    # state, id and name columns broke at every level.  Each row opens with
    # the blank the deepest row spends on its tree, less its own, and every
    # row's cells start on one column, as its right group's end on one.
    deep=max([d for _, d in shape.values()] or [1])
    widths=panel_widths(prepared_tasks, now)
    for task, usage, meta, shares in prepared_tasks:
        if isinstance(task, dict) and task.get("id"):
            tid=str(task["id"])
            rows.append((tid, render_agent_row(task, usage, meta, shares, limits, cols, now, trees.get(tid, ""), tree_w, etas.get(tid, False), tid in busy, shape[tid][1], kids.get(tid, 0), kids_w, A_TREE_W * (deep - shape[tid][1]), widths)))
    return rows
