"""What the assertion suites share: agents.py, rate.py and subagent.py.

Each check prints a line, ok or FAIL with what it got and wanted, and is
counted in `passed` or `failed` for the suite's closing line.
"""
import json
import os
import re

passed = failed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok    %s" % name)


def bad(name, detail=""):
    global failed
    failed += 1
    print("  FAIL  %s" % name)
    if detail:
        for line in str(detail).splitlines():
            print("          " + line)


def check(name, got, want):
    if got == want:
        ok(name)
    else:
        bad(name, "got  %r\nwant %r" % (got, want))


def near(name, got, want, tol=1e-9):
    if got is not None and want is not None and abs(got - want) <= tol:
        ok(name)
    else:
        bad(name, "got  %r\nwant %r" % (got, want))


def tally():
    """The closing line, and the suite's exit status."""
    return "pass %d   fail %d" % (passed, failed), 1 if failed else 0


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def drawn(cell):
    """A cell's spans joined into escape codes, as the terminal gets them."""
    if isinstance(cell, str):
        return cell
    from coding_agent_usage_line.spans import join
    return join(cell)


def unpainted(cell):
    """A cell's text alone, its escape codes dropped."""
    return ANSI.sub("", drawn(cell))


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
