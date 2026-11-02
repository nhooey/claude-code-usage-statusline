"""What the assertion suites share: agents.py, rate.py and subagent.py, and
the fixture commands of run-cases.py and app-server.py (write_executable).

Each check prints a line, ok or FAIL with what it got and wanted, and is
counted in `passed` or `failed` for the suite's closing line.
"""
import json
import os
import re

passed = failed = 0


def pin_colour(env=None):
    """Claude Code's 256-colour level, the one the fixtures are drawn at,
    for this process (or `env`) and what it runs, whatever the developer's
    terminal draws: the colour variables set to that and no others."""
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from coding_agent_usage_line.spans import COLOUR_VARS
    env = os.environ if env is None else env
    for var in COLOUR_VARS:
        env.pop(var, None)
    env["TERM"] = "xterm-256color"
    return env


def write_executable(path, text):
    """Write a fixture command, make it executable, and run it once, with
    nothing on stdin and no deadline, before the program under test does.

    macOS checks every new executable on its first run, in one daemon
    shared by the whole machine, and a file it has checked once it lets
    run.  The check is about a tenth of a second alone, but it queues: with
    the suites of tests/all.sh writing commands side by side it was
    measured at 15 seconds a run.  The program gives a usage command five
    seconds (sources.command_reading) and the Codex app-server two in its
    test, so a first run that landed in the queue came back as no reading,
    and a frozen clock then kept the failure's retry time from passing for
    every later case of that session: the agent rows lost 🔋 and 🪫.  Run
    here, the check is paid where nothing is timed."""
    import stat
    import subprocess
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, stat.S_IRWXU)
    subprocess.run([path], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
