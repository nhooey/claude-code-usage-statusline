#!/usr/bin/env python3
"""The configuration files, read by the Python: the shared cases in
tests/fixtures/config/cases.json, --show-config, files reaching the
renderers, and the goldens kept off this machine's own files.

    python3 tests/config.py

Every run here points the program at scratch directories: no test reads
the developer's config files, state or ~/.claude.json.
"""
import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROGRAM = str(ROOT / "coding-agent-usage-line.py")
CASES = HERE / "fixtures" / "config" / "cases.json"
DEFAULTS_CASES = HERE / "fixtures" / "config" / "defaults-cases.json"
D = Path(".config") / "coding-agent-usage-line"
# The floor the goldens are recorded under, as run-cases.py runs them.
PYTHON = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE / "fixtures" / "gen"))
from coding_agent_usage_line import config, formatting  # noqa: E402
from coding_agent_usage_line.options import from_argv, merge  # noqa: E402
from coding_agent_usage_line.options_spec import OPTIONS  # noqa: E402
import config as gen  # noqa: E402  (tests/fixtures/gen/config.py)


def load_run_cases():
    spec = importlib.util.spec_from_file_location("run_cases", HERE / "run-cases.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def environ(**changes):
    saved = dict(os.environ)
    os.environ.update(changes)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class SharedCases(unittest.TestCase):
    def test_every_case_as_recorded(self):
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        self.assertEqual([c["id"] for c in cases], [c["id"] for c in gen.CASES],
                         "cases.json is stale: run tests/fixtures/gen/config.py")
        for case in cases:
            with self.subTest(case["id"]):
                self.assertEqual(gen.run(case), case["expected"])

    def test_a_file_over_64_kib_is_skipped_unread(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.jsonc"
            write(path, '{"prefix": "%s"}' % ("x" * config.MAX_BYTES))
            self.assertEqual(config.read(str(path)),
                             ({}, ["%s: over 64 KiB, so the file is skipped" % path]))

    def test_the_derived_label_is_the_one_the_rows_draw(self):
        self.assertEqual(from_argv([])["label"], formatting.C_LABEL)
        self.assertEqual(from_argv(["--no-usage-text"])["label"], formatting.E_ROW_PROMPT)


class DefaultsFile(unittest.TestCase):
    """mod/defaults/config.jsonc, read strictly: the shared cases in
    tests/fixtures/config/defaults-cases.json, which the mod runs too, and
    what is the Python's alone."""

    def test_every_defaults_case_as_recorded(self):
        cases = json.loads(DEFAULTS_CASES.read_text(encoding="utf-8"))
        self.assertEqual(cases, gen.defaults_cases(),
                         "defaults-cases.json is stale: run tests/fixtures/gen/config.py")
        by_id = {c["id"]: c["expected"] for c in cases}
        # The shipped file passes; a missing key, an extra key and a wrong
        # type each fail, naming the key and the file.
        self.assertIsNone(by_id["shipped"])
        path = gen.DEFAULTS_PATH
        self.assertEqual(by_id["missing-key"], '%s: "account" is missing' % path)
        self.assertTrue(by_id["unknown-key"].startswith('%s: "acount" is no option' % path))
        self.assertEqual(by_id["wrong-type"], '%s: "totals" must be true or false' % path)

    def test_the_shipped_file_holds_every_option_a_file_may_set(self):
        values = config.read_defaults(config.DEFAULTS_FILE)
        self.assertEqual(set(values), set(OPTIONS))
        self.assertEqual(values["usage-source"], "auto")
        self.assertIsNone(values["right-edge"])
        # An option no file sets keeps the spec's default.
        self.assertEqual(values["mode"], "status")

    def test_a_missing_or_unreadable_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.jsonc"
            with self.assertRaises(config.DefaultsError) as got:
                config.read_defaults(str(path))
            self.assertEqual(str(got.exception), "%s: missing" % path)
            path.write_bytes(b"\xff")
            with self.assertRaises(config.DefaultsError) as got:
                config.read_defaults(str(path))
            self.assertEqual(str(got.exception), "%s: unreadable" % path)

    def test_a_copy_with_one_change_differs_by_that_change_alone(self):
        shipped = config.DEFAULTS_FILE
        text = Path(shipped).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            user = Path(tmp) / "config.jsonc"
            write(user, text.replace('"hint-inset": 2', '"hint-inset": 3'))
            values, warnings = config.read(str(user))
        self.assertEqual(warnings, [])
        files = [config.Layer("user", str(user), values)]
        mine = merge({}, files, ("py", "mod"))
        plain = merge({}, (), ("py", "mod"))
        changed = {k for k in plain if mine[k] != plain[k]}
        self.assertEqual(changed, {"hint-inset"})
        self.assertEqual(mine["hint-inset"], 3)
        # Derived still: the copy's null is no setting.
        self.assertEqual((mine.layer("right-edge"), mine.layer("label")),
                         ("derived", "derived"))


class Program(unittest.TestCase):
    """The program run whole, in a scratch tree: HOME, the state and the
    config directory are all under it, and a .git ends every walk."""

    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="calu-config-")
        self.addCleanup(scratch.cleanup)
        # Resolved, as the working directory --show-config walks from is.
        self.tmp = Path(scratch.name).resolve()
        self.home = self.tmp / "home"
        self.project = self.home / "p"
        (self.project / ".git").mkdir(parents=True)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CODING_AGENT_USAGE_LINE_", "CLAUDE_", "XDG_"))}
        self.env.update({
            "HOME": str(self.home),
            "CODING_AGENT_USAGE_LINE_STATE_DIR": str(self.tmp / "state"),
            "CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR": str(self.tmp / "projects"),
            "CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE": str(self.tmp / "calib.json"),
            "CODING_AGENT_USAGE_LINE_CONFIG_DIR": str(self.tmp / "user"),
            "CODING_AGENT_USAGE_LINE_NOW": "1789380000",
            "CLAUDE_CONFIG_DIR": str(self.tmp / "claude"),
            "CODEX_HOME": str(self.tmp / "codex"),
            "TZ": "UTC"})
        self.transcript = HERE / "fixtures" / "transcripts" / "cost" / "01-plain.jsonl"

    def run_program(self, *args, stdin="", cwd=None):
        return subprocess.run([sys.executable, PROGRAM] + list(args), input=stdin,
                              text=True, capture_output=True, env=self.env,
                              cwd=str(cwd or self.project), timeout=20)

    def cost(self, *flags):
        result = self.run_program("--agent", "claude", "--mode", "cost", "--usage-source",
                                  "none", "--transcript", str(self.transcript),
                                  "--cols", "160", *flags)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_a_file_and_a_flag_say_the_same(self):
        plain = self.cost().stdout
        for key, flag in (("totals", "--no-totals"), ("usage-text", "--no-usage-text"),
                          ("datetime", "--no-datetime")):
            with self.subTest(key):
                local = self.project / D / "config.local.jsonc"
                write(local, json.dumps({key: False}))
                from_file = self.cost()
                local.unlink()
                self.assertNotEqual(from_file.stdout, plain)
                self.assertEqual(from_file.stdout, self.cost(flag).stdout)
                self.assertEqual(from_file.stderr, "")

    def test_the_flag_beats_the_file(self):
        plain = self.cost().stdout
        write(self.project / D / "config.jsonc", '{"usage-text": false}')
        self.assertNotEqual(self.cost().stdout, plain)
        self.assertEqual(self.cost("--usage-text").stdout, plain)

    def test_show_config(self):
        write(self.tmp / "user" / "config.jsonc", '{"account": "u", "hide": ["a"]}')
        write(self.project / D / "config.local.jsonc",
              '{\n  // mine\n  "rows": {"turn": {"live": "always"}},\n  "rwos": 1,\n}')
        result = self.run_program("--show-config", "--hide", "b", cwd=self.project / ".git")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        lines = result.stdout.splitlines()
        local = self.project / D / "config.local.jsonc"
        self.assertEqual(lines[:6], [
            "Configuration, read from %s:" % (self.project / ".git"),
            "  flag           the command line",
            "  project-local  %s" % local,
            "  project        %s (none)" % (self.project / D / "config.jsonc"),
            "  user           %s" % (self.tmp / "user" / "config.jsonc"),
            "  default        %s" % config.DEFAULTS_FILE])
        rows = {line.split()[0]: line.split(None, 2)[1:] for line in lines[7:]
                if line and not line.startswith(" ") and line != "Warnings:"}
        self.assertEqual(rows["account"], ["user", '"u"'])
        self.assertEqual(rows["hide"], ["flag", '["b"]'])
        self.assertEqual(rows["rows.turn.live"], ["project-local", '"always"'])
        self.assertEqual(rows["rows.turn.transcript"], ["default", "true"])
        self.assertEqual(rows["label"], ["derived", '"🎤 Usage: Prompt (last)  "'])
        self.assertNotIn("mode", rows)
        self.assertEqual(lines[lines.index("Warnings:") + 1:], [
            '  %s: "rwos" is no option (did you mean "rows"?); skipped' % local,
            "  %s: --hide on the command line overrides its \"hide\" here, "
            "which the mod reads" % (self.tmp / "user" / "config.jsonc")])

    def test_a_bad_file_still_draws_the_panel_with_the_warning_on_stderr(self):
        write(self.project / D / "config.jsonc", '{"hide": "agent", "rows": nope}')
        payload = {"session_id": "s", "cwd": str(self.project), "columns": 160, "tasks": [
            {"id": "a1", "name": "Marigold", "type": "local_agent", "status": "running",
             "description": "Review the plan", "startTime": 1789379000000,
             "model": "claude-opus-5", "cwd": str(self.project)}]}
        result = self.run_program("--agent", "claude", "--mode", "subagent",
                                  "--usage-source", "none", "--cols", "160",
                                  stdin=json.dumps(payload), cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r["id"] for r in rows], ["a1"])
        self.assertEqual(result.stderr, "%s: not valid JSONC, so the file is skipped\n"
                         % (self.project / D / "config.jsonc"))

    def test_a_broken_defaults_file_is_drawn_in_place_of_every_output(self):
        # A copy of the program whose defaults file leaves out "account":
        # the checkout's own file is never touched.
        app = self.tmp / "app"
        app.mkdir()
        shutil.copy(PROGRAM, str(app))
        shutil.copytree(str(ROOT / "coding_agent_usage_line"),
                        str(app / "coding_agent_usage_line"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        text = Path(config.DEFAULTS_FILE).read_text(encoding="utf-8")
        broken = app / "mod" / "defaults" / "config.jsonc"
        write(broken, text.replace('  "account": "default",\n', ""))
        error = ("coding-agent-usage-line: the defaults file is wrong: "
                 '%s: "account" is missing' % broken)
        program = str(app / "coding-agent-usage-line.py")

        def run(*args, stdin=""):
            return subprocess.run([sys.executable, program] + list(args), input=stdin,
                                  text=True, capture_output=True, env=self.env,
                                  cwd=str(self.project), timeout=20)
        status = run("--agent", "claude", stdin="{}")
        self.assertEqual((status.returncode, status.stdout, status.stderr),
                         (0, "⚠ " + error + "\n", error + "\n"))
        cost = run("--agent", "claude", "--mode", "cost", stdin="{}")
        self.assertEqual((cost.returncode, json.loads(cost.stdout)),
                         (0, {"systemMessage": "⚠ " + error}))
        panel = run("--agent", "claude", "--mode", "subagent",
                    stdin=json.dumps({"tasks": [{"id": "a1"}, {"id": "a2"}]}))
        self.assertEqual([json.loads(l) for l in panel.stdout.splitlines()],
                         [{"id": "a1", "content": "⚠ " + error},
                          {"id": "a2", "content": "⚠ " + error}])
        for by_hand in (("--show-config",), ("--help",),
                        ("--agent", "claude", "--mode", "cost", "--all",
                         "--transcript", str(self.transcript))):
            with self.subTest(by_hand[0]):
                result = run(*by_hand)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, "", error + "\n"))

    def test_the_panel_reads_hide_from_the_payloads_project(self):
        payload = {"session_id": "s", "cwd": str(self.project), "columns": 160, "tasks": [
            {"id": "a1", "name": "Marigold", "type": "local_agent", "status": "running",
             "description": "Review the plan", "startTime": 1789379000000,
             "model": "claude-opus-5", "cwd": str(self.project)}]}
        def panel():
            result = self.run_program("--agent", "claude", "--mode", "subagent",
                                      "--usage-source", "none", "--cols", "160",
                                      stdin=json.dumps(payload), cwd=self.tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        plain = panel()
        write(self.project / D / "config.jsonc", '{"hide": ["agent.time.elapsed"]}')
        self.assertNotEqual(panel(), plain)

    def test_codex_starts_from_the_rollouts_cwd_and_diagnose_counts_warnings(self):
        rollout = self.tmp / "rollout.jsonl"
        write(rollout, json.dumps({"type": "session_meta", "payload": {
            "id": "root", "session_id": "s", "cwd": str(self.project)}}) + "\n")
        write(self.project / D / "config.jsonc",
              '{"usage-source": "claude-usage-tracker", "acount": "x"}')
        result = self.run_program("--agent", "codex", "--mode", "status", "--diagnose",
                                  "--transcript", str(rollout), cwd=self.tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.project / D / "config.jsonc"
        lines = result.stderr.splitlines()
        self.assertEqual(lines[:2], [
            '%s: "acount" is no option (did you mean "account"?); skipped' % path,
            '%s: "usage-source" "claude-usage-tracker" is no source codex reads; '
            'skipped' % path])
        self.assertIn("diagnose source=auto ", lines[2])
        self.assertTrue(lines[2].endswith(" config_warnings=2"), lines[2])


class GoldensAreHermetic(unittest.TestCase):
    """The goldens' harness must not read this machine's config files, or a
    developer's own file would change what they render (and pass in CI).
    Every place one could be is planted with a file that changes what each
    suite draws; the cases must still match their goldens, and the same
    run without the harness's guard must not."""

    POISON = {"usage-text": False, "prefix": "X", "totals": False, "hide": ["agent.chat"],
              "mark-spacing": False, "subscript-decimals": True, "column-rules": True,
              "usage-source": "none", "right-edge": 9}

    def test_planted_config_files_change_no_golden(self):
        rc = load_run_cases()
        with tempfile.TemporaryDirectory(prefix="calu-poison-") as tmp:
            tmp = Path(tmp)
            home = tmp / "home"
            text = json.dumps(self.POISON)
            # The user file under each of its three names, and a project
            # file above the directory the status payloads name.
            write(home / D / "config.jsonc", text)
            write(tmp / "xdg" / "coding-agent-usage-line" / "config.jsonc", text)
            write(tmp / "cfg" / "config.jsonc", text)
            write(home / "src" / "statusline-fixture" / D / "config.jsonc", text)
            cases = json.loads((HERE / "fixtures" / "cases.json").read_text())["cases"]
            picked = [next(c for c in cases if c["suite"] == s)
                      for s in ("status", "cost", "subagent")]
            with environ(HOME=str(home), XDG_CONFIG_HOME=str(tmp / "xdg"),
                         CODING_AGENT_USAGE_LINE_CONFIG_DIR=str(tmp / "cfg"),
                         CODING_AGENT_USAGE_LINE_PROJECT_DIR=str(home / "src")):
                suite = rc.Suite(str(tmp / "suite"))
                guarded = suite.environ
                for case in picked:
                    with self.subTest(case["suite"]):
                        env, cwd = guarded(case["env"])
                        self.assertTrue(env["CODING_AGENT_USAGE_LINE_CONFIG_DIR"]
                                        .startswith(str(tmp / "suite")))
                        self.assertEqual(env["CODING_AGENT_USAGE_LINE_PROJECT_DIR"], cwd)
                        want = (HERE / "golden" / case["suite"] / (case["id"] + ".txt")).read_bytes()
                        got, _figures = rc.render(PYTHON, suite, case)
                        self.assertEqual(got, want.rstrip(b"\n"))

                # Without the guard the planted files are read: the test
                # above would pass for nothing if they could not be.
                def unguarded(name, drop=("CODING_AGENT_USAGE_LINE_CONFIG_DIR",
                                          "CODING_AGENT_USAGE_LINE_PROJECT_DIR")):
                    env, cwd = guarded(name)
                    for key in drop:
                        env.pop(key)
                    return env, cwd
                suite.environ = unguarded
                for case in picked:
                    with self.subTest("unguarded " + case["suite"]):
                        want = (HERE / "golden" / case["suite"] / (case["id"] + ".txt")).read_bytes()
                        got, _figures = rc.render(PYTHON, suite, case)
                        self.assertNotEqual(got, want.rstrip(b"\n"))
                # The project file alone, with the user directory still the
                # harness's: the status payload's directory finds it.
                status = picked[0]
                suite.environ = lambda name: unguarded(
                    name, ("CODING_AGENT_USAGE_LINE_PROJECT_DIR",))
                want = (HERE / "golden" / "status" / (status["id"] + ".txt")).read_bytes()
                got, _figures = rc.render(PYTHON, suite, status)
                self.assertNotEqual(got, want.rstrip(b"\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
