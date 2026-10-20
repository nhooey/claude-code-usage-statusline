#!/usr/bin/env python3
"""What the window-cost scan costs here, cold and off its cache.

    python3 tools/time-window-costs.py [--runs N]

Not in CI: it reads ~/.claude/projects, which is private.  It runs
claude._window_costs over the real transcripts with the windows a plan has
now (the 5-hour one from five hours ago, the week from seven days ago),
against a scratch state directory: first with nothing cached, then N times
more off the cache the first left.  The cache in the real state directory
is never read or written.  mod/tools/time-window-costs.ts is the Node
port's side; `time-window-costs` in the dev shell runs both.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=int, default=3,
                    help="scans off the cache after the cold one")
    args = ap.parse_args()
    scratch = tempfile.mkdtemp(prefix="window-costs-")
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = scratch
    from coding_agent_usage_line import claude
    now = datetime.now()
    ss, ws = now - timedelta(hours=5), now - timedelta(days=7)
    try:
        t = time.perf_counter()
        sess, week = claude._window_costs(ss, ws)
        cold = time.perf_counter() - t
        hits = []
        for _ in range(args.runs):
            t = time.perf_counter()
            claude._window_costs(ss, ws)
            hits.append(time.perf_counter() - t)
        size = sum(os.path.getsize(os.path.join(scratch, n))
                   for n in os.listdir(scratch))
        print("python: cold %.0f ms, cached %s ms, cache %.2f MB, "
              "sess $%.2f, week $%.2f" % (
                  cold * 1000, " ".join("%.0f" % (h * 1000) for h in hits),
                  size / 1e6, sess, week))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
