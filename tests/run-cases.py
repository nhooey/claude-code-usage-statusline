#!/usr/bin/env python3
"""Run the shared golden cases in tests/fixtures/cases.json.

    python3 tests/run-cases.py                  # every case
    python3 tests/run-cases.py --suite status   # or cost, subagent, panel
    python3 tests/run-cases.py --regen          # re-record, then read the diff
    python3 tests/run-cases.py --regen-figures  # the figures alone

Each case is an input, a width, flags and a named environment from
tests/fixtures/env/.  This file turns the environment into what the program
reads -- variables, a calibration cache, a usage-source command, a tracker
store, a git repository to run in -- renders, and compares stdout byte for
byte with tests/golden/<suite>/<id>.txt.  The cost suite compares the hook's
systemMessage, not the JSON around it, so a diff is readable.

Each case is checked in the two stages the program runs in besides
(tests/README.md, "Figures"):

  figures  the figures document the run wrote, compared byte for byte with
           tests/fixtures/figures/<suite>/<id>.json;
  render   that committed document alone, drawn again with
           --from-figures at the case's width and flags, compared with the
           same golden.  Nothing but the document goes in, so this is the
           drawing checked apart from the accounting.

--regen rewrites the goldens and the figures; --regen-figures the figures
only, for when the document's shape changes and the drawing must not.

The subagent suite is the agent panel's: a subagentStatusLine payload on
stdin, the JSON lines the program prints compared whole with
tests/golden/subagent/<id>.txt.  The panel writes no figures document, so
its two stages are the `panel` suite instead: tests/fixtures/panel/, the
renderer's inputs and the rows it draws for them, written again by
fixtures/gen/panel.py and compared with what is committed.  --regen
rewrites those too.

The program runs under the interpreter given by --python, /usr/bin/python3 by
default, the version floor on macOS.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
FIGURES = os.path.join(FIXTURES, "figures")
PROGRAM = os.path.join(os.path.dirname(HERE), "coding-agent-usage-line.py")


def git(*args):
    subprocess.run(["git"] + list(args), check=True, capture_output=True)


def make_repos(scratch):
    """The two working directories: one clean commit, and one with a staged
    file on top, so 🍂 and ✱ are covered."""
    repos = {}
    for state in ("clean", "dirty"):
        # The directory's name is the 📦 project name, so it is the one the
        # goldens were recorded under: `repo` and `repo-dirty`.
        path = os.path.join(scratch,
                            "repo" if state == "clean" else "repo-" + state)
        git("init", "-q", "-b", "golden-" + state, path)
        git("-C", path, "-c", "user.name=golden",
            "-c", "user.email=golden@invalid",
            "commit", "-q", "--allow-empty", "-m", "fixture")
        if state == "dirty":
            with open(os.path.join(path, "changed.txt"), "w") as fh:
                fh.write("uncommitted\n")
            git("-C", path, "add", "changed.txt")
        repos[state] = path
    return repos


TRACKER = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>activeProfileId</key><string>golden</string>
<key>profiles_v3</key><string>[{"id":"golden","claudeUsage":%s}]</string>
</dict></plist>
"""


class Suite:
    """One suite's scratch directory and the state its cases share."""

    def __init__(self, scratch):
        self.scratch = scratch
        self.tmp = os.path.join(scratch, "tmp")
        os.makedirs(self.tmp)
        self.repos = make_repos(scratch)
        self.envs = {}

    def environ(self, name):
        e = self.envs.get(name)
        if e is None:
            with open(os.path.join(FIXTURES, "env", name + ".json")) as fh:
                e = self.envs[name] = json.load(fh)
        env = {k: v for k, v in os.environ.items()
               if k not in ("TMUX", "TERM_PROGRAM", "TERMINAL_EMULATOR")
               and not k.startswith("CODING_AGENT_USAGE_LINE_")}
        env.update(e["terminal"])
        env.update({
            "CODING_AGENT_USAGE_LINE_NOW": str(e["now"]),
            "TZ": e["tz"],
            "LC_ALL": e["locale"],
            "TMPDIR": self.tmp,
            "CODING_AGENT_USAGE_LINE_STATE_DIR":
                os.path.join(self.tmp, "source-state"),
            "CODING_AGENT_USAGE_LINE_TEST_SOURCE_DIR": self.tmp,
            "CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE":
                os.path.join(self.tmp, "calib.json"),
            "CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST":
                os.path.join(self.tmp, "tracker.plist"),
            "CODING_AGENT_USAGE_LINE_USAGE_SOURCE": "auto",
        })
        # Written before every case, not once: the program may rewrite the
        # calibration cache, and a case must see its environment's.
        with open(env["CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE"], "w") as fh:
            json.dump(e["calib"], fh)
        with open(env["CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST"],
                  "w") as fh:
            fh.write(TRACKER % json.dumps(e["tracker"],
                                          separators=(",", ":")))
        if e["source"] is not None:
            # One command per environment.  The collector caches by command,
            # so two environments sharing a path would read each other's
            # reading.
            cmd = os.path.join(self.tmp, "claude-source-" + name)
            if not os.path.exists(cmd):
                with open(cmd, "w") as fh:
                    fh.write("#!/bin/sh\nprintf '%%s\\n' '%s'\n"
                             % json.dumps(e["source"], separators=(",", ":")))
                os.chmod(cmd, 0o700)
            env["CODING_AGENT_USAGE_LINE_USAGE_SOURCE"] = "cmd:" + cmd
        return env, self.repos[e["repo"]]


def fill(text, scratch=None):
    text = (text.replace("${HOME}", os.path.expanduser("~"))
                .replace("${FIXTURES}", FIXTURES))
    return text if scratch is None else text.replace("${SCRATCH}", scratch)


def unfill(text, scratch):
    """fill's inverse, for what a run wrote: the paths that differ between
    machines and runs go back to placeholders.  The most specific first,
    since the fixtures sit under HOME, and the scratch directory's real path
    before the one it was given, since a repository reports the real one."""
    for path, mark in ((os.path.realpath(scratch), "${SCRATCH}"),
                       (scratch, "${SCRATCH}"),
                       (FIXTURES, "${FIXTURES}"),
                       (os.path.expanduser("~"), "${HOME}")):
        text = text.replace(path, mark)
    return text


def stdout_of(case, got):
    if case["suite"] == "cost":
        got = (json.loads(got).get("systemMessage", "")
               .encode("utf-8") if got.strip() else b"")
    # The shell suites captured with $( ), which drops trailing newlines.
    return got.rstrip(b"\n")


def render(python, suite, case):
    """Both stages, as the program runs them: the drawn rows, and the
    figures document they were drawn from, with placeholders in."""
    env, cwd = suite.environ(case["env"])
    out = os.path.join(suite.scratch, "figures.json")
    if os.path.exists(out):
        os.remove(out)
    env["CODING_AGENT_USAGE_LINE_FIGURES_OUT"] = out
    argv = [python, PROGRAM, "--agent", "claude",
            "--mode", case["suite"], "--cols", str(case["cols"])]
    path = os.path.join(FIXTURES, case["input"])
    if case["suite"] == "status":
        with open(path, encoding="utf-8") as fh:
            stdin = fill(fh.read()).encode("utf-8")
    elif case["suite"] == "subagent":
        # The tasks' working directories are the fixture repositories.
        with open(path, encoding="utf-8") as fh:
            stdin = fill(fh.read(), suite.scratch).encode("utf-8")
    else:
        argv += ["--transcript", path]
        stdin = b""
    argv += case["flags"]
    got = subprocess.run(argv, input=stdin, cwd=cwd, env=env,
                         capture_output=True).stdout
    figures = None
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            figures = unfill(fh.read(), suite.scratch)
    return stdout_of(case, got), figures


def render_figures(python, suite, case, figures):
    """Stage two alone: the document drawn at the case's width and flags.

    The environment still carries the terminal profile, which the drawing
    reads.  It carries the case's clock too, which the drawing must not
    read: the document's own is the one drawn.  No stdin, and no state
    shared with the full run.
    """
    env, cwd = suite.environ(case["env"])
    path = os.path.join(suite.scratch, "from-figures.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(fill(figures, suite.scratch))
    argv = [python, PROGRAM, "--agent", "claude", "--mode", case["suite"],
            "--cols", str(case["cols"]), "--from-figures", path]
    argv += case["flags"]
    got = subprocess.run(argv, stdin=subprocess.DEVNULL, cwd=cwd, env=env,
                         capture_output=True).stdout
    return stdout_of(case, got)


def read(path, mode="r"):
    if not os.path.exists(path):
        return None
    with open(path, mode, **({} if "b" in mode else
                             {"encoding": "utf-8"})) as fh:
        return fh.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=("status", "cost", "subagent", "panel"))
    ap.add_argument("--regen", action="store_true")
    ap.add_argument("--regen-figures", action="store_true")
    ap.add_argument("--python", default="/usr/bin/python3")
    args = ap.parse_args()
    regen_figures = args.regen or args.regen_figures

    with open(os.path.join(FIXTURES, "cases.json")) as fh:
        cases = json.load(fh)["cases"]
    totals = {"pass": 0, "fail": 0, "missing": 0, "wrote": 0}
    stages = {s: {"pass": 0, "fail": 0} for s in ("figures", "render")}
    for name in ("status", "cost", "subagent"):
        if args.suite and args.suite != name:
            continue
        gold = os.path.join(HERE, "golden", name)
        out = os.path.join(HERE, "out" if name == "status" else "out-" + name)
        os.makedirs(gold, exist_ok=True)
        # By suite, as the goldens are: a status and a cost case can share
        # an id.
        figs = os.path.join(FIGURES, name)
        os.makedirs(figs, exist_ok=True)
        os.makedirs(out, exist_ok=True)
        for f in os.listdir(out):   # else a stale failure looks like a live one
            if f.endswith((".got", ".want")):
                os.remove(os.path.join(out, f))
        print("=== golden: %s mode ===" % name)
        scratch = tempfile.mkdtemp(prefix="claude-golden-%s." % name)
        try:
            suite = Suite(scratch)
            for case in (c for c in cases if c["suite"] == name):
                cid = case["id"]
                got, figures = render(args.python, suite, case)
                want_path = os.path.join(gold, cid + ".txt")
                fig_path = os.path.join(figs, cid + ".json")
                if regen_figures and figures is not None:
                    with open(fig_path, "w", encoding="utf-8") as fh:
                        fh.write(figures)
                if args.regen:
                    with open(want_path, "wb") as fh:
                        fh.write(got)
                    totals["wrote"] += 1
                    continue
                want = read(want_path, "rb")
                if want is None:
                    print("  MISS  %-32s (no golden — run --regen)" % cid)
                    totals["missing"] += 1
                    continue
                want = want.rstrip(b"\n")
                fails = []
                if got != want:
                    fails.append("rows")
                    with open(os.path.join(out, cid + ".got"), "wb") as fh:
                        fh.write(got)
                if name == "subagent":
                    # No figures document: the panel suite checks the
                    # drawing apart.
                    report(cid, fails, want_path, out, totals)
                    continue
                # Figures: what the run wrote against what is committed.
                kept = read(fig_path)
                if kept is None:
                    print("  MISS  %-32s (no figures — run --regen-figures)"
                          % cid)
                    totals["missing"] += 1
                    continue
                if figures == kept:
                    stages["figures"]["pass"] += 1
                else:
                    stages["figures"]["fail"] += 1
                    fails.append("figures")
                    with open(os.path.join(out, cid + ".figures.got"), "w",
                              encoding="utf-8") as fh:
                        fh.write(figures or "")
                # Render: the committed figures alone, drawn again.
                drawn = render_figures(args.python, suite, case, kept)
                if drawn == want:
                    stages["render"]["pass"] += 1
                else:
                    stages["render"]["fail"] += 1
                    fails.append("render")
                    with open(os.path.join(out, cid + ".render.got"),
                              "wb") as fh:
                        fh.write(drawn)
                report(cid, fails, want_path, out, totals)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    panel = None
    if not args.suite or args.suite == "panel":
        print("=== panel: the agent panel's rows from its inputs ===")
        sys.path.insert(0, os.path.join(FIXTURES, "gen"))
        import panel as gen_panel
        if args.regen:
            gen_panel.main_panel(args.python)
        else:
            n, fails = gen_panel.check(args.python)
            for f in fails:
                print("  FAIL  " + f)
            panel = (n, len(fails))
    print()
    if args.regen:
        print("wrote %d goldens under tests/golden/, and their figures"
              % totals["wrote"])
        print("READ THE DIFF before accepting them: this is the step where a")
        print("layout regression gets blessed as the new expected output.")
        return 0
    print("pass %(pass)d   fail %(fail)d   missing %(missing)d" % totals)
    print("  figures  pass %(pass)d   fail %(fail)d" % stages["figures"])
    print("  render   pass %(pass)d   fail %(fail)d" % stages["render"])
    if panel is not None:
        print("  panel    %d cases   %d files differ" % panel)
    return 0 if (totals["fail"] == 0 and totals["missing"] == 0
                 and not (panel and panel[1])) else 1


def report(cid, fails, want_path, out, totals):
    if not fails:
        print("  ok    %s" % cid)
        totals["pass"] += 1
    else:
        print("  FAIL  %-32s (%s)" % (cid, ", ".join(fails)))
        shutil.copy(want_path, os.path.join(out, cid + ".want"))
        totals["fail"] += 1


if __name__ == "__main__":
    sys.exit(main())
