#!/usr/bin/env python3
"""Throwaway subagentStatusLine for the alignment test.

While align-probe.on sits beside this file, every task's row is the
redesign mockup's first agent row, drawn for the terminal's width.  Without
it, the real status line's subagent mode runs, so leaving this in
settings.json changes nothing.  See agents/plans/redesign.md, "Rerunning
the alignment test".
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
REAL = [os.path.join(REPO, "coding-agent-usage-line.py"), "--agent", "claude", "--mode",
        "subagent", "--mark-spacing", "--usage-source", "claude-usage-tracker"]

raw = sys.stdin.read()
if not os.path.exists(os.path.join(HERE, "align-probe.on")):
    sys.exit(subprocess.run(REAL, input=raw, text=True).returncode)
pay = json.loads(raw)
# The payload's columns are the terminal's less 6; the mockup wants the terminal's.
cols = int(pay.get("columns") or 154) + 6
rows = subprocess.run(["node", os.path.join(REPO, "mod/tools/layout-mockup.ts"),
                       "--plain", "--part", "panel", "--phase", "running", "--agents", "1",
                       "--cols", str(cols)], capture_output=True, text=True).stdout.splitlines()
for task in pay.get("tasks") or ():
    print(json.dumps({"id": task["id"], "content": rows[0] if rows else ""}, ensure_ascii=False))
