"""Pure Claude subagent-panel row layout.

Preparation (sidecar lookup, usage parsing, limits/source selection and JSON
serialization) belongs to orchestration.  This module only lays out supplied
task facts and returns strings.
"""
import time
from typing import Optional, Sequence

from . import formatting as fmt
from .formatting import *
from .claude_render import render_cost, render_tokens, model_spec, effort_glyph
from .claude_records import Limits, squash

A_KIND_W, A_ID_W, A_STATE_W = 2, 10, 2
A_HEAD_GAP, A_NAME_MIN, A_ACT_MIN, A_CLOCK_W, A_RATE_W, A_GAP, A_TICK_S = 1, 8, 8, 6, 7, 2, 5.0
A_LIMIT_W = 2 + LIM_FIG_W
KIND_MARK = {"general-purpose":"🔧", "claude":"🎩", "Explore":"🔍", "Plan":"📐",
             "claude-code-guide":"📚", "statusline-setup":"📟", "fork":"🍴",
             "local_agent":"👥", "local_bash":"🐚", "local_workflow":"🔗",
             "remote_agent":"🌐", "in_process_teammate":"🎎"}
STATE_MARK = {"running":"🟢", "pending":"🟡", "completed":"🔵", "killed":"⚫", "failed":"🔴"}

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
def render_state(status): return "" if not status else STATE_MARK.get(status, "%s%s%s" % (F_AMB, status[:2], R))
def render_agent_model(model_id, effort):
    if not model_id: return ""
    return "%s%s%s%s%s" % (E_MOD, F_PUR, pad_val(2, model_spec(model_id)), R, effort_glyph(effort) if effort and effort != "null" else "")
def render_agent_cache(cache_pct):
    if cache_pct is None or cache_pct < 0: return ""
    return "%s%s%s%s%s" % (E_CACHE, cache_color(cache_pct), E_HUNDRED if cache_pct >= 100 else pad_val(2, "%d" % cache_pct), E_PCT, R)
def render_agent_ctx(ctx_tokens):
    return "" if ctx_tokens <= 0 else "%s%s%s%s" % (S_CTX, mag_dim(ctx_tokens, MAG_TOK) + F_PNK, pad_val(4, humanize(ctx_tokens)), R)
def render_agent_clock(start_ms, now, end=None):
    try: t0=float(start_ms)/1000.0
    except (TypeError, ValueError): return ""
    t=time.time() if now is None else now
    if end is not None: t=min(t, max(end, t0))
    run=max(0.0, t-t0)
    return "%s%s%s%s" % (E_IDLE, mag_dim(run, MAG_DUR_S) + F_PRW, pad_val(4, dur_fmt(run)), R)
def render_agent_rate(rate):
    return "" if rate is None else "%s%s%s/s%s" % (E_RATE, mag_dim(rate, MAG_RATE) + F_RATE, pad_val(3, rate_fig(rate)), R)
def render_who(name, act, room):
    if not name and not act: return ""
    if not name: return "%s%s%s" % (F_CHAT_B, fit_cols(act, room), R)
    left=room-vis_width(name)-A_HEAD_GAP
    if act and left >= A_ACT_MIN: return "%s%s%s%s%s%s%s" % (F_BLU, name, R, " " * A_HEAD_GAP, F_CHAT_B, fit_cols(act, left), R)
    return "%s%s%s" % (F_BLU, fit_cols(name, room), R)

def render_agent_row(task, usage, meta, shares, limits, cols=None, now=None):
    """Render one fully prepared task; it performs no reads or accounting."""
    task, meta, shares = task or {}, meta or {}, shares or {}
    tid, status, kind = str(task.get("id") or ""), str(task.get("status") or ""), str(task.get("type") or "")
    model = str(task.get("model") or "") or getattr(usage, "model", "") or str(meta.get("model") or "")
    light = shares.get("week") is not None and shares["week"] < MAG_SHARE_AGENT
    gap=" " * A_GAP
    right=gap.join(seg(w,c) for w,c in (
        (6, render_agent_model(model, str(task.get("effort") or "") or getattr(usage,"effort", ""))),
        (A_CLOCK_W, render_agent_clock(task.get("startTime"), now, None if status == "running" else getattr(usage,"last_epoch",None))),
        (vis_width(S_TOK)+VAL_W+VAL2_W, render_tokens(getattr(usage,"tok_up",None), getattr(usage,"tok_down",0))),
        (A_RATE_W, render_agent_rate(token_rate(task.get("tokenSamples"),status))),
        (5, render_agent_cache(getattr(usage,"cache_pct",-1))),
        (vis_width(S_CTX)+4, render_agent_ctx(getattr(usage,"ctx_tokens",0))),
        (vis_width(S_COST)+4, render_cost("%.4f" % getattr(usage,"cost",0)) if getattr(usage,"parts",()) else ""),
        (A_LIMIT_W, render_agent_limit(E_SESS, limits.session_pct, shares.get("sess"), F_LIM_SESS, bool(getattr(usage,"parts",())), light)),
        (A_LIMIT_W, render_agent_limit(E_WEEK, limits.weekly_pct, shares.get("week"), F_LIM_WEEK, bool(getattr(usage,"parts",())), light))))
    desc=squash(str(task.get("description") or "")); name=str(task.get("name") or "") or desc; act=squash(str(task.get("label") or ""))
    if act == desc: act=""
    head=(" "*A_HEAD_GAP).join(seg(w,c) for w,c in ((A_KIND_W+A_STATE_W, render_kind(str(meta.get("agentType") or ""),kind)+render_state(status)), (A_ID_W, DIM+F_BLU2+fit_cols(tid,A_ID_W)+R)))
    room=A_NAME_MIN if not cols else max(A_NAME_MIN, cols-vis_width(strip_ansi(head))-A_HEAD_GAP-vis_width(strip_ansi(right))-A_GAP)
    return (head+" "*A_HEAD_GAP+seg(room,render_who(name,act,room))+gap+right).rstrip()

def render_task_rows(prepared_tasks, limits, cols=None, now=None):
    """Return `(task_id, row)` pairs for prepared `(task, usage, meta, shares)` facts."""
    rows=[]
    for task, usage, meta, shares in prepared_tasks:
        if isinstance(task, dict) and task.get("id"):
            rows.append((str(task["id"]), render_agent_row(task, usage, meta, shares, limits, cols, now)))
    return rows
