#!/usr/bin/env python3
"""Draw the agent panel for a subagentStatusLine payload at a width.

    python3 tools/draw-panel.py payloads/subagent/01-mixed.json 120
    python3 tools/draw-panel.py --env tmux payloads/subagent/02-parked.json 90
    python3 tools/draw-panel.py 01-mixed.json 80 --no-mark-spacing
    python3 tools/draw-panel.py --ansi payloads/subagent/01-mixed.json 150

The payload is a path under tests/fixtures/, or any path; a bare file name
is looked for in tests/fixtures/payloads/subagent/.  Arguments after the
width are passed to the program as they are.

The panel is drawn the way the subagent golden suite draws it: through
tests/run-cases.py's environment, so the clock, the calibration, the usage
source and the tasks' git repositories are a fixture environment's
(tests/fixtures/env/<name>.json, app-41-63 by default) and not this
machine's.  What it prints is each task's row, one a line, with the colour
codes taken out unless --ansi is given, so a change to the drawing can be
read at any width without recording a golden for it.
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def run_cases():
    """tests/run-cases.py as a module; its name is not an importable one."""
    path = os.path.join(REPO, "tests", "run-cases.py")
    spec = importlib.util.spec_from_file_location("run_cases", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def payload(arg):
    """The payload's path relative to tests/fixtures/, as a case names it."""
    for path in (arg, os.path.join(FIXTURES, arg),
                 os.path.join(FIXTURES, "payloads", "subagent", arg)):
        if os.path.isfile(path):
            return os.path.relpath(os.path.abspath(path), FIXTURES)
    sys.exit("draw-panel: no payload at %s" % arg)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        epilog="Arguments after COLS go to the program unchanged.")
    ap.add_argument("payload", help="subagentStatusLine payload (JSON)")
    ap.add_argument("cols", type=int, help="the width to draw at")
    ap.add_argument("--env", default="app-41-63",
                    help="fixture environment, from tests/fixtures/env/ "
                         "(default: app-41-63)")
    ap.add_argument("--ansi", action="store_true",
                    help="keep the colour codes")
    ap.add_argument("--python", default="/usr/bin/python3",
                    help="interpreter to run the program under "
                         "(default: /usr/bin/python3, the version floor)")
    args, flags = ap.parse_known_args()

    rc = run_cases()
    case = {"suite": "subagent", "env": args.env,
            "input": payload(args.payload), "cols": args.cols,
            "flags": flags}
    with tempfile.TemporaryDirectory() as scratch:
        out, _ = rc.render(args.python, rc.Suite(scratch), case)
    for line in out.decode("utf-8").splitlines():
        content = json.loads(line)["content"]
        print((content if args.ansi else ANSI.sub("", content)).rstrip())


if __name__ == "__main__":
    main()
