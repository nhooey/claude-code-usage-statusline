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
print("ok pure Claude subagent rows")
