#!/usr/bin/env python3
"""Run the shared golden cases in tests/fixtures/cases.json.

    python3 tests/run-cases.py                  # every case
    python3 tests/run-cases.py --suite status   # or cost
    python3 tests/run-cases.py --regen          # re-record, then read the diff

Each case is an input, a width, flags and a named environment from
tests/fixtures/env/.  This file turns the environment into what the program
reads -- variables, a calibration cache, a usage-source command, a tracker
store, a git repository to run in -- renders, and compares stdout byte for
byte with tests/golden/<suite>/<id>.txt.  The cost suite compares the hook's
systemMessage, not the JSON around it, so a diff is readable.

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


def fill(text):
    return (text.replace("${HOME}", os.path.expanduser("~"))
                .replace("${FIXTURES}", FIXTURES))


def render(python, suite, case):
    env, cwd = suite.environ(case["env"])
    argv = [python, PROGRAM, "--agent", "claude",
            "--mode", case["suite"], "--cols", str(case["cols"])]
    path = os.path.join(FIXTURES, case["input"])
    if case["suite"] == "status":
        with open(path, encoding="utf-8") as fh:
            stdin = fill(fh.read()).encode("utf-8")
    else:
        argv += ["--transcript", path]
        stdin = b""
    argv += case["flags"]
    got = subprocess.run(argv, input=stdin, cwd=cwd, env=env,
                         capture_output=True).stdout
    if case["suite"] == "cost":
        got = (json.loads(got).get("systemMessage", "")
               .encode("utf-8") if got.strip() else b"")
    # The shell suites captured with $( ), which drops trailing newlines.
    return got.rstrip(b"\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=("status", "cost"))
    ap.add_argument("--regen", action="store_true")
    ap.add_argument("--python", default="/usr/bin/python3")
    args = ap.parse_args()

    with open(os.path.join(FIXTURES, "cases.json")) as fh:
        cases = json.load(fh)["cases"]
    totals = {"pass": 0, "fail": 0, "missing": 0, "wrote": 0}
    for name in ("status", "cost"):
        if args.suite and args.suite != name:
            continue
        gold = os.path.join(HERE, "golden", name)
        out = os.path.join(HERE, "out" if name == "status" else "out-cost")
        os.makedirs(gold, exist_ok=True)
        os.makedirs(out, exist_ok=True)
        for f in os.listdir(out):   # else a stale failure looks like a live one
            if f.endswith((".got", ".want")):
                os.remove(os.path.join(out, f))
        print("=== golden: %s mode ===" % name)
        scratch = tempfile.mkdtemp(prefix="claude-golden-%s." % name)
        try:
            suite = Suite(scratch)
            for case in (c for c in cases if c["suite"] == name):
                got = render(args.python, suite, case)
                want_path = os.path.join(gold, case["id"] + ".txt")
                if args.regen:
                    with open(want_path, "wb") as fh:
                        fh.write(got)
                    totals["wrote"] += 1
                elif not os.path.exists(want_path):
                    print("  MISS  %-32s (no golden — run --regen)"
                          % case["id"])
                    totals["missing"] += 1
                else:
                    with open(want_path, "rb") as fh:
                        want = fh.read().rstrip(b"\n")
                    if got == want:
                        print("  ok    %s" % case["id"])
                        totals["pass"] += 1
                    else:
                        print("  FAIL  %s" % case["id"])
                        shutil.copy(want_path,
                                    os.path.join(out, case["id"] + ".want"))
                        with open(os.path.join(out, case["id"] + ".got"),
                                  "wb") as fh:
                            fh.write(got)
                        totals["fail"] += 1
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    print()
    if args.regen:
        print("wrote %d goldens under tests/golden/" % totals["wrote"])
        print("READ THE DIFF before accepting them: this is the step where a")
        print("layout regression gets blessed as the new expected output.")
        return 0
    print("pass %(pass)d   fail %(fail)d   missing %(missing)d" % totals)
    return 0 if totals["fail"] == 0 and totals["missing"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
