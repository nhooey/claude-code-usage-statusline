#!/usr/bin/env python3
"""Write the receipt cases that pin mod/src/claude_cost.ts and
mod/src/claude_cost_render.ts to the Python's render stage, past what the
cost goldens reach.

    /usr/bin/python3 tests/fixtures/gen/receipt.py

The 87 cost goldens are drawn without --color, under one terminal and one
zone, so they never reach the colour runs spans.join keeps for the receipt,
the flush-left layout, --no-totals, --prefix and --label, or a clock in
another zone.  This draws each distinct cost figures document under each of
VARIANTS, by running the program's render stage (--from-figures) as
run-cases.py does, and writes what it printed to
tests/fixtures/receipt/cases.json, one case to a line:

    {"figures": "<id>.json" under figures/cost/, "cols", "flags",
     "terminal": the profile variables, "tz": the zone the document's clock
     is drawn in, "out": the systemMessage, "" for none}

A document's placeholders are filled as run-cases.py fills them; none of
them is drawn.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(FIXTURES))
PROGRAM = os.path.join(REPO, "coding-agent-usage-line.py")
FIGURES = os.path.join(FIXTURES, "figures", "cost")
OUT = os.path.join(FIXTURES, "receipt")

JEDITERM = {"TERMINAL_EMULATOR": "JetBrains-JediTerm"}

# (cols, flags, terminal, tz): widths that cut the labels and put the turn
# tag on a line of its own, each layout switch, and zones either side of
# UTC.  A cols of 0 is a width that is unknown.
VARIANTS = (
    (196, ["--color"], JEDITERM, "UTC"),
    (72, ["--color"], JEDITERM, "UTC"),
    (40, ["--color"], {}, "UTC"),
    (196, ["--color", "--no-right-align"], {"TERM_PROGRAM": "iTerm.app"},
     "UTC"),
    (150, ["--no-totals", "--prefix", "»", "--label", "Last"], JEDITERM,
     "UTC"),
    (0, ["--color", "--no-mark-spacing", "--subscript-decimals"], JEDITERM,
     "Asia/Kolkata"),
    (60, ["--force-newline", "--no-usage-text"], {"TMUX": "/tmp/t,1,0"},
     "America/New_York"),
    (120, ["--color", "--no-account-totals", "--no-datetime"], {},
     "Australia/Lord_Howe"),
)


def fill(text):
    """run-cases.py's fill, with a scratch directory nothing reads."""
    return (text.replace("${HOME}", os.path.expanduser("~"))
                .replace("${FIXTURES}", FIXTURES)
                .replace("${SCRATCH}", "/nonexistent-scratch"))


def documents():
    """Each distinct cost figures document once, under its first name:
    the flag cases' documents repeat the plain ones'."""
    seen, out = set(), []
    for name in sorted(os.listdir(FIGURES)):
        with open(os.path.join(FIGURES, name), encoding="utf-8") as fh:
            text = fh.read()
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest not in seen:
            seen.add(digest)
            out.append((name, text))
    return out


def environ(terminal):
    env = {k: v for k, v in os.environ.items()
           if k not in ("TMUX", "TERM_PROGRAM", "TERMINAL_EMULATOR")
           and not k.startswith("CODING_AGENT_USAGE_LINE_")}
    env.update(terminal)
    return env


def draw(path, cols, flags, terminal):
    argv = [sys.executable, PROGRAM, "--agent", "claude", "--mode", "cost",
            "--cols", str(cols), "--from-figures", path] + flags
    got = subprocess.run(argv, stdin=subprocess.DEVNULL,
                         env=environ(terminal), capture_output=True,
                         check=True).stdout
    return json.loads(got).get("systemMessage", "") if got.strip() else ""


def main():
    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "figures.json")
        for name, text in documents():
            fig = json.loads(fill(text))
            for cols, flags, terminal, tz in VARIANTS:
                fig["clock"]["tz"] = tz
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(fig, fh, ensure_ascii=False)
                cases.append({"figures": name, "cols": cols, "flags": flags,
                              "terminal": terminal, "tz": tz,
                              "out": draw(path, cols, flags, terminal)})
    os.makedirs(OUT, exist_ok=True)
    opts = dict(sort_keys=True, ensure_ascii=False)
    with open(os.path.join(OUT, "cases.json"), "w", encoding="utf-8") as fh:
        fh.write('{"cases": [\n' + ",\n".join(json.dumps(c, **opts)
                                              for c in cases) + "\n]}\n")


if __name__ == "__main__":
    main()
