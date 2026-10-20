#!/usr/bin/env python3
"""Say how the grid fixtures changed since a commit, case by case.

    python3 tools/diff-grid-fixtures.py              # against HEAD
    python3 tools/diff-grid-fixtures.py master~3     # against a commit
    python3 tools/diff-grid-fixtures.py HEAD iterm-tmux.json --show 10

tests/fixtures/grid/*.json are far too long to read as a diff: thousands of
draw cases, each a row drawn at a width under a set of cells, hidden paths
and spill.  After regenerating them (mod/tools/gen-grid-cases.ts), this
matches each draw case with the one at BASE that has the same row, cells,
width, hidden paths and spill, and prints one line a file:

  layout   how many layout cases each side has, and whether every old one
           is still there;
  rows     whether the rows the cases draw are the same;
  draw     how many cases each side has, how many changed, and of those how
           many changed only in colour or spacing of spans and not in text;
           how many were added and removed.

Then, for the first --show cases (3 by default) whose text changed, the case
and its old and new text.  Files are names in tests/fixtures/grid/; with
none, every one there.  A file BASE does not have is said so and skipped.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID = os.path.join("tests", "fixtures", "grid")


def at(base, name):
    """The fixture as BASE has it, or None if BASE has no such file."""
    r = subprocess.run(["git", "-C", REPO, "show",
                        "%s:%s/%s" % (base, GRID, name)],
                       capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def key(case):
    """What a draw case is drawn from: two with the same key are one case."""
    return json.dumps([case["row"], case["keys"], case["cols"],
                       case["hide"], case["spill"]])


def text(case):
    return "".join(span[0] for span in case["spans"])


def compare(name, base, show):
    old = at(base, name)
    if old is None:
        print(name, "not at", base)
        return
    with open(os.path.join(REPO, GRID, name), encoding="utf-8") as fh:
        new = json.load(fh)
    o = {key(c): c for c in old["draw"]}
    n = {key(c): c for c in new["draw"]}
    changed = [k for k in o if k in n and o[k] != n[k]]
    retext = [k for k in changed if text(o[k]) != text(n[k])]
    lo = {json.dumps(c, sort_keys=True) for c in old["layout"]}
    ln = {json.dumps(c, sort_keys=True) for c in new["layout"]}
    print("%s  layout %d/%d%s  rows %s  draw %d/%d changed %d "
          "(text %d, spans only %d) added %d removed %d"
          % (name, len(lo), len(ln), "" if lo <= ln else " (old ones gone)",
             "same" if old["rows"] == new["rows"] else "DIFFER",
             len(o), len(n), len(changed), len(retext),
             len(changed) - len(retext), len(set(n) - set(o)),
             len(set(o) - set(n))))
    for k in retext[:show]:
        print("  case", k)
        print("    old", repr(text(o[k])))
        print("    new", repr(text(n[k])))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("base", nargs="?", default="HEAD",
                    help="the commit to compare with (default: HEAD)")
    ap.add_argument("files", nargs="*",
                    help="fixture names in %s (default: all)" % GRID)
    ap.add_argument("--show", type=int, default=3, metavar="N",
                    help="print the text of the first N cases whose text "
                         "changed, per file (default: 3)")
    args = ap.parse_args()
    names = args.files or sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(REPO, GRID, "*.json")))
    if not names:
        sys.exit("diff-grid-fixtures: no fixtures in %s" % GRID)
    for name in names:
        compare(name, args.base, args.show)


if __name__ == "__main__":
    main()
