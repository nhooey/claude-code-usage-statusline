#!/usr/bin/env python3
"""grid.py against the grid's shared cases, tests/fixtures/grid/.

    /usr/bin/python3 tests/grid.py

The TypeScript writes these cases (mod/tools/gen-grid-cases.ts) and this
only reads them: every `layout` and `draw` case of each file is replayed
under each terminal profile the file names, with the environment set and
formatting reloaded as a process with that environment has it, comparing
the kept keys, the spans and the joined line.  A disagreement is grid.py's
to fix, never the fixture's.
"""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
CASES = os.path.join(HERE, "fixtures", "grid")

from coding_agent_usage_line import formatting as fm  # noqa: E402
from coding_agent_usage_line import grid  # noqa: E402
from coding_agent_usage_line.spans import Span, join  # noqa: E402

PROFILE_VARS = ("TMUX", "TERMINAL_EMULATOR", "TERM_PROGRAM")


def configure(env):
    """formatting.py as a process with this environment has it."""
    for var in PROFILE_VARS:
        os.environ.pop(var, None)
    os.environ.update(env)
    importlib.reload(fm)


def span_from(a):
    """A span as the cases write it: [text, colour, dim, bold, bg], the
    trailing defaults left off."""
    a = list(a) + [None] * (5 - len(a))
    return Span(a[0], a[1], bool(a[2]), bool(a[3]), a[4])


def span_json(s):
    out = list(s)
    while len(out) > 1 and out[-1] in (None, False):
        out.pop()
    return out


def row_from(r):
    return grid.Row(
        r["scope"],
        [grid.Piece(p["path"], [span_from(s) for s in p["spans"]], p["drop"])
         for p in r["label"]],
        {k: [span_from(s) for s in v] for k, v in r["cells"].items()},
        r.get("depth"))


passed = failed = 0


def check(ok, where, got, want):
    global passed, failed
    if ok:
        passed += 1
        return
    failed += 1
    if failed <= 10:
        print("  FAIL  %s\n          got  %r\n          want %r"
              % (where, got, want))


saved = {v: os.environ.get(v) for v in PROFILE_VARS}
try:
    for name in sorted(f for f in os.listdir(CASES) if f.endswith(".json")):
        with open(os.path.join(CASES, name), encoding="utf-8") as fh:
            data = json.load(fh)
        rows = {k: row_from(r) for k, r in data["rows"].items()}
        for profile, env in sorted(data["settings"]["profiles"].items()):
            configure(env)
            n = passed
            for c in data["layout"]:
                got = grid.layout([rows[i] for i in c["rows"]], c["cols"],
                                  c["hide"], c["fixed"])
                check(got == c["keys"], "%s %s layout %s" % (
                    name, profile, json.dumps(c, ensure_ascii=False)),
                    got, c["keys"])
            for c in data["draw"]:
                got = grid.draw(rows[c["row"]], c["keys"], c["cols"],
                                c["hide"], c["spill"])
                where = "%s %s draw %s" % (name, profile, json.dumps(
                    [c["row"], c["cols"], c["hide"], c["spill"]]))
                check([span_json(s) for s in got] == c["spans"],
                      where + " spans", got, c["spans"])
                check(join(got) == c["line"], where + " line",
                      join(got), c["line"])
            print("  %-22s %-9s %5d checks" % (name, profile, passed - n))
finally:
    for var, val in saved.items():
        if val is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = val
    importlib.reload(fm)

# At a right edge of 0, as --right-edge 0 sets it for the band under the
# footer line (asked 2026-10-20), a row ends at `cols` itself, and the
# layout keeps a column the default edge drops, as grid.test.ts has it.
any_case = sorted(f for f in os.listdir(CASES) if f.endswith(".json"))[0]
with open(os.path.join(CASES, any_case), encoding="utf-8") as fh:
    data = json.load(fh)
rows = {k: row_from(r) for k, r in data["rows"].items()}
c = data["draw"][0]
row = rows[c["row"]]
keys = [g["key"] for g in grid.GRID_CELLS]
fm.set_right_edge(0)
try:
    for cols in (120, 160, 196):
        got = fm.vis_width(join(grid.draw(row, keys, cols, [])))
        check(got == cols, "right edge 0: draw at %d" % cols, got, cols)
    wide = [rows[k] for k in rows]
    at = {e: None for e in (0, fm.RIGHT_EDGE)}
    for e in at:
        fm.set_right_edge(e)
        # The narrowest width that keeps every column.
        at[e] = next(n for n in range(1, 1000)
                     if len(grid.layout(wide, n, [])) == len(
                         grid.layout(wide, 1 << 30, [])))
    check(at[fm.RIGHT_EDGE] - at[0] == fm.RIGHT_EDGE,
          "right edge 0: every column kept RIGHT_EDGE columns sooner",
          at, fm.RIGHT_EDGE)
finally:
    fm.set_right_edge(fm.RIGHT_EDGE)

# A hide path names itself and every path under it, as grid.test.ts has it.
for pats, path, want in (
        (["turn.time"], "turn.time.eta", True),
        (["*.work"], "session.work.diff", True),
        (["account"], "account", True),
        (["turn.time.eta"], "turn.time", False),
        (["*.work"], "session", False),
        (["t?rn.[a-c]*"], "turn.chat.prompt", True),
        (["t?rn.[!a-c]*"], "turn.chat.prompt", False)):
    got = grid.hidden(pats, path)
    check(got == want, "hidden(%r, %r)" % (pats, path), got, want)

print("\npass %d   fail %d" % (passed, failed))
sys.exit(1 if failed else 0)
