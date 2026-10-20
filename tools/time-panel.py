#!/usr/bin/env python3
"""What one agent-panel tick costs here, on the session with most agents.

    python3 tools/time-panel.py [--runs N] [TRANSCRIPT]

Not in CI: it reads ~/.claude/projects, which is private.  It builds the
payload the panel would get for TRANSCRIPT (by default, the transcript
under ~/.claude/projects with the most agent files), one task per agent
file, and times claude.prepare_subagent_tasks, the panel's read: first
against an empty scratch state directory, then N times more off what the
first left there.  Each line also gives the part of the tick inbox_counts
took, which reads every file whole and is not the agents' folds.  The real
state directory is never read or written.
"""

import argparse
import glob
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


def busiest(projects: str) -> str:
    """The transcript with the most agent files under `projects`."""
    best, most = "", 0
    for d in glob.glob(os.path.join(projects, "*", "*", "subagents")):
        n = len(glob.glob(os.path.join(d, "**", "agent-*.jsonl"),
                          recursive=True))
        tr = os.path.dirname(d) + ".jsonl"
        if n > most and os.path.isfile(tr):
            best, most = tr, n
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=int, default=3,
                    help="ticks after the first")
    ap.add_argument("transcript", nargs="?", default="")
    args = ap.parse_args()
    projects = os.environ.get("CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR",
                              os.path.expanduser("~/.claude/projects"))
    tr = args.transcript or busiest(projects)
    if not tr:
        sys.exit("no transcript with agents under %s" % projects)
    scratch = tempfile.mkdtemp(prefix="time-panel-")
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = scratch
    from coding_agent_usage_line import claude
    files = claude.agent_files(tr)
    tasks = [{"id": os.path.basename(p)[len("agent-"):-len(".jsonl")],
              "name": "", "type": "local_agent", "status": "completed"}
             for p in files]
    pay = {"transcript_path": tr, "cwd": REPO, "tasks": tasks}
    size = sum(os.path.getsize(p) for p in files)
    inbox_s = [0.0]
    counts = claude.inbox_counts

    def timed_inbox(*a, **k):
        t = time.perf_counter()
        try:
            return counts(*a, **k)
        finally:
            inbox_s[0] += time.perf_counter() - t

    claude.inbox_counts = timed_inbox
    try:
        print("%s: %d agents, %.1f MB" % (os.path.basename(tr), len(files),
                                          size / 1e6))
        for i in range(args.runs + 1):
            inbox_s[0] = 0.0
            t = time.perf_counter()
            got = claude.prepare_subagent_tasks(pay)
            took = time.perf_counter() - t
            print("tick %d (%s): %.0f ms, inbox %.0f ms, the rest %.0f ms, "
                  "%d rows" % (i, "cold" if i == 0 else "warm", took * 1000,
                               inbox_s[0] * 1000,
                               (took - inbox_s[0]) * 1000, len(got)))
        kept = sum(os.path.getsize(os.path.join(dp, n))
                   for dp, _, ns in os.walk(scratch) for n in ns)
        print("state written: %.2f MB" % (kept / 1e6))
    finally:
        claude.inbox_counts = counts
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
