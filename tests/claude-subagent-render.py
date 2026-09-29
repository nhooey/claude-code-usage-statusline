#!/usr/bin/env python3
"""Prepared Claude subagent row rendering has no transcript/source inputs."""
import os, sys
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line.claude_records import NO_LIMITS
from coding_agent_usage_line.claude_subagent_render import render_task_rows

usage=SimpleNamespace(tok_up=10, tok_down=2, cache_pct=50, ctx_tokens=20,
                      cost=.01, parts=((1,.01),), model="opus", effort="high", last_epoch=2)
rows=render_task_rows(([{"id":"task","status":"running","type":"Explore","description":"find","startTime":0}, usage, {"agentType":"Explore"}, {"sess":None,"week":None}],), NO_LIMITS, 120, 10)
assert rows[0][0] == "task" and "task" in rows[0][1]

# A finished task stops its clock where its transcript does, and a shell has
# none: its ⌛ is blank, not counting a task that ended up to now.
from coding_agent_usage_line.formatting import strip_ansi
def row(task, u, now):
    return strip_ansi(render_task_rows(([task, u, {}, {"sess":None,"week":None}],), NO_LIMITS, 160, now)[0][1])
shell={"id":"b1","status":"completed","type":"local_bash","description":"sleep 5","startTime":0}
early, late = row(shell, SimpleNamespace(), 10), row(shell, SimpleNamespace(), 3600)
assert early == late and "\u231b" not in early, (early, late)
agent={"id":"a1","status":"completed","type":"local_agent","description":"x","startTime":0}
killed=SimpleNamespace(work=((0.0, 5.0),), last_epoch=None, model_s=4.0, tool_s=0.0)
assert row(agent, killed, 10) == row(agent, killed, 3600) and "\u231b  5s" in row(agent, killed, 3600), row(agent, killed, 3600)
print("ok pure Claude subagent rows")
