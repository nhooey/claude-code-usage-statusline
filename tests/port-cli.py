#!/usr/bin/env python3
"""Independent public-CLI acceptance checks; no live history or credentials."""
import concurrent.futures
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMMAND = [sys.executable, str(ROOT / "coding-agent-usage-line.py")]


def record(kind, payload, second=0):
    return {"type": kind, "timestamp": "2026-09-14T10:00:%02dZ" % second,
            "payload": payload}


def request(thread, turn, response, inp, out, root=None):
    return record("token_usage_record", {
        "thread_id": thread, "session_id": "review-conversation",
        "turn_id": turn, "root_turn_id": root or turn, "response_id": response,
        "usage": {"input_tokens": inp, "output_tokens": out},
        "turn_token_usage": {"input_tokens": 99999, "output_tokens": 99999},
        "thread_token_usage": {"input_tokens": 99999, "output_tokens": 99999}})


class PublicPortTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="calu-public-")
        self.addCleanup(self.scratch.cleanup)
        self.home = Path(self.scratch.name)
        self.env = {key: val for key, val in os.environ.items()
                    if not key.startswith(("CODING_AGENT_USAGE_LINE_", "CLAUDE_"))}
        self.env.update({"CODEX_HOME": str(self.home),
                         "CODING_AGENT_USAGE_LINE_STATE_DIR": str(self.home / "state"),
                         "CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR": str(self.home / "projects"),
                         "CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE": str(self.home / "calibration.json")})
        self.path = self.home / "root.jsonl"
        self.root_request = request("root", "turn-one", "root-one", 100, 20)
        self.write(self.path, [
            record("session_meta", {"id": "root", "session_id": "review-conversation"}),
            record("turn_context", {"turn_id": "turn-one", "model": "gpt-5.6-terra", "effort": "high"}),
            self.root_request, self.root_request,
            record("event_msg", {"type": "task_complete", "turn_id": "turn-one"}, 10),
            record("turn_context", {"turn_id": "turn-two", "model": "gpt-5.6-terra", "effort": "medium"}),
            request("root", "turn-two", "root-two", 200, 30)])
        self.child = self.home / "child.jsonl"
        self.write(self.child, [
            record("session_meta", {"id": "child", "session_id": "review-conversation",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "root"}}}}),
            self.root_request,
            record("turn_context", {"turn_id": "child-one", "root_turn_id": "turn-one",
                                     "model": "gpt-5.6-luna", "effort": "low"}),
            request("child", "child-one", "child-one", 40, 10, "turn-one"),
            record("event_msg", {"type": "task_complete", "turn_id": "child-one"}, 12)])
        grand = self.home / "grand.jsonl"
        self.write(grand, [
            record("session_meta", {"id": "grand", "session_id": "review-conversation",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "child"}}}}),
            record("turn_context", {"turn_id": "grand-one", "root_turn_id": "turn-two",
                                     "model": "gpt-5.6-luna", "effort": "low"}),
            request("grand", "grand-one", "grand-one", 60, 15, "turn-two"),
            record("event_msg", {"type": "task_complete", "turn_id": "grand-one"}, 15)])
        with sqlite3.connect(str(self.home / "state_5.sqlite")) as db:
            db.execute("CREATE TABLE threads(id TEXT, rollout_path TEXT, source TEXT)")
            db.execute("CREATE TABLE thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT, status TEXT)")
            db.executemany("INSERT INTO threads VALUES (?,?,?)", [
                ("root", str(self.path), "cli"), ("child", str(self.child), "subagent"),
                ("grand", str(grand), "subagent")])
            # Empty spawn edges deliberately exercise explicit metadata fallback.

    def write(self, path, records, append=False):
        with path.open("a" if append else "w", encoding="utf-8") as stream:
            for item in records:
                stream.write(json.dumps(item) + "\n")

    def run_cli(self, *args, payload=None):
        result = subprocess.run(COMMAND + list(args), input=json.dumps(payload or {}),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self.env, cwd=str(self.home), timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def stop(self, turn):
        return json.loads(self.run_cli("--agent", "codex", "--mode", "cost",
            "--usage-source", "none", payload={"session_id": "review-conversation",
            "turn_id": turn, "transcript_path": str(self.path)}))

    def test_historical_root_effort_and_session_scope(self):
        report = self.stop("turn-one")["systemMessage"]
        self.assertIn("high", report.splitlines()[0])
        self.assertIn("140", report)
        self.assertIn("30", report)
        self.assertIn("session", report.lower())
        self.assertIn("400", report)
        self.assertIn("75", report)
        self.assertEqual(self.stop("turn-one"), {})

    def test_late_child_is_claimed_once_across_concurrent_stops(self):
        self.stop("turn-one")
        self.stop("turn-two")
        self.write(self.child, [request("child", "child-one", "child-late", 5, 2, "turn-one")], append=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            reports = list(pool.map(lambda _: self.stop("turn-two"), range(6)))
        emitted = [item["systemMessage"] for item in reports if item]
        self.assertEqual(len(emitted), 1, reports)
        self.assertIn("turn-one", emitted[0])
        self.assertIn("late", emitted[0].lower())
        self.assertIn("405", emitted[0])
        self.assertIn("77", emitted[0])
        self.assertNotIn("turn turn-two", emitted[0])
        self.assertEqual(self.stop("turn-two"), {})

    def test_continued_turn_reports_only_fresh_usage(self):
        self.stop("turn-two")
        self.write(self.path, [request("root", "turn-two", "root-two-more", 7, 3)], append=True)
        report = self.stop("turn-two")["systemMessage"]
        current = report.splitlines()[0]
        self.assertIn("incremental", current)
        self.assertIn("in 7 out 3", current)
        self.assertNotIn("in 267", current)
        self.assertIn("407", report)
        self.assertIn("78", report)
        self.assertEqual(self.stop("turn-two"), {})

    def test_all_groups_turns_and_does_not_consume_stop_state(self):
        report = self.run_cli("--agent", "codex", "--mode", "cost", "--all",
            "--usage-source", "none", "--transcript", str(self.path))
        self.assertIn("140", report)
        self.assertIn("260", report)
        self.assertIn("child", report.lower())
        self.assertTrue(self.stop("turn-one"))

    def test_history_diagnostics_do_not_refresh_or_expose_command_path(self):
        command = self.home / "private-source-name.sh"
        marker = self.home / "unexpected-refresh"
        command.write_text("#!/bin/sh\nprintf 'called' > '" + str(marker) + "'\n",
                           encoding="utf-8")
        result = subprocess.run(COMMAND + ["--agent", "codex", "--mode", "cost", "--all",
            "--diagnose", "--usage-source", "cmd:" + str(command),
            "--transcript", str(self.path)], input="", text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env,
            cwd=str(self.home), timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("diagnose", result.stderr)
        self.assertIn("source=cmd", result.stderr)
        self.assertNotIn(str(command), result.stderr)
        self.assertFalse(marker.exists(), "History must not refresh account sources")
        self.assertIn("thread", result.stdout)
        self.assertTrue(self.stop("turn-one"))

    def test_claude_diagnostics_are_separate_from_panel_json(self):
        payload = {"session_id": "diagnostic-panel", "columns": 120,
                   "tasks": [{"id": "diagnostic-task", "type": "local_bash",
                              "description": "fixture", "status": "running"}]}
        result = subprocess.run(COMMAND + ["--agent", "claude", "--mode", "subagent",
            "--usage-source", "native", "--diagnose"], input=json.dumps(payload),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env,
            cwd=str(self.home), timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("diagnose", result.stderr)
        self.assertIn("source=native", result.stderr)
        self.assertEqual([json.loads(line)["id"] for line in result.stdout.splitlines()],
                         ["diagnostic-task"])

    def test_explicit_transcripts_do_not_wait_for_stdin(self):
        for agent in ("claude", "codex"):
            proc = subprocess.Popen(COMMAND + ["--agent", agent, "--usage-source", "native",
                "--transcript", str(self.path)], stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=self.env, cwd=str(self.home))
            try:
                self.assertEqual(proc.wait(timeout=4), 0, agent)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdin.close()
                proc.stderr.close()

    def test_bucket_map_identity_and_explicit_command_precedence(self):
        reset = int(time.time()) + 86400
        quota = {"rateLimitsByLimitId": {
            "general": {"limitName": "general", "secondary": {
                "usedPercent": 97, "windowDurationMins": 10080, "resetsAt": reset}},
            "spark": {"limitName": "Spark", "primary": {
                "usedPercent": 100, "windowDurationMins": 300, "resetsAt": reset},
                "secondary": {"usedPercent": 100, "windowDurationMins": 10080, "resetsAt": reset}}}}
        self.write(self.path, [record("event_msg", {"type": "token_count", "rate_limits": quota})], append=True)
        report = self.run_cli("--agent", "codex", "--usage-source", "native", "--transcript", str(self.path))
        self.assertIn("general", report)
        self.assertIn("Spark", report)
        general = report.split("general", 1)[1].split("Spark", 1)[0]
        self.assertIn("97%", general)
        self.assertNotIn("100%", general)
        command = self.home / "reading.sh"
        reading = {"schema_version": 1, "as_of": time.time(), "buckets": [
            {"id": "selected", "label": "selected-command", "windows": [
                {"id": "weekly", "used_percent": 23, "duration_seconds": 604800}]}]}
        command.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps(reading) + "'\n", encoding="utf-8")
        report = self.run_cli("--agent", "codex", "--usage-source", "cmd:" + str(command),
            "--transcript", str(self.path))
        self.assertIn("selected-command", report)
        self.assertIn("23%", report)
        self.assertNotIn("Spark", report)

    def test_claude_command_receives_scope_and_overrides_native_intake(self):
        command = self.home / "claude-source.py"
        marker = self.home / "command-context.json"
        reading = {"schema_version": 1, "as_of": time.time(), "account": {
            "period_start": 1789344000, "period_end": 1789387200,
            "cost_usd": 7.25, "input_tokens": 314, "output_tokens": 27,
            "scope": "organization"}}
        command.write_text("#!" + sys.executable + "\nimport json,sys\n"
            "context=json.load(sys.stdin)\n"
            "with open(" + repr(str(marker)) + ", 'w') as stream: json.dump(context,stream)\n"
            "print(" + repr(json.dumps(reading)) + ")\n", encoding="utf-8")
        command.chmod(0o700)
        payload = {"session_id": "claude-review", "cwd": str(self.home),
            "model": {"display_name": "Opus", "id": "claude-opus-4-6"},
            "rate_limits": {"five_hour": {"used_percentage": 11,
                                          "resets_at": time.time() + 18000}}}
        report = self.run_cli("--agent", "claude", "--usage-source", "cmd:" + str(command),
            "--account", "review-account", "--account-period", "week", "--cols", "196",
            payload=payload)
        self.assertTrue(marker.is_file(), "Explicit command was not called for Claude")
        context = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(context["agent"], "claude")
        self.assertEqual(context["session"], "claude-review")
        self.assertEqual(context["account"], "review-account")
        self.assertEqual(context["period"], "week")
        self.assertNotIn("rate_limits", context)
        self.assertIn("7.25", report)
        self.assertIn("organization", report.lower())

    def test_claude_native_cache_survives_next_render_without_crossing_accounts(self):
        payload = {"session_id": "native-cache-review", "cwd": str(self.home),
                   "rate_limits": {"five_hour": {"used_percentage": 31,
                                                  "resets_at": time.time() + 18000}}}
        args = ("--agent", "claude", "--usage-source", "native", "--cols", "196")
        self.run_cli(*args, "--account", "first-account", payload=payload)
        del payload["rate_limits"]
        same = self.run_cli(*args, "--account", "first-account", payload=payload)
        other = self.run_cli(*args, "--account", "second-account", payload=payload)
        strip_ansi = lambda text: re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
        self.assertRegex(strip_ansi(same), r"31\s*[%٪]")
        self.assertNotRegex(strip_ansi(other), r"31\s*[%٪]")

    def test_claude_auto_tracker_is_optional_and_never_caches_credentials(self):
        now = time.time()
        canary = "fixture-oauth-credential-must-not-be-cached"
        tracker = self.home / "tracker.plist"
        profile = {"id": "fixture", "oauthAccountJSON": canary, "claudeUsage": {
            "sessionPercentage": 98, "sessionResetTime": now + 18000 - 978307200,
            "weeklyPercentage": 10, "weeklyResetTime": now + 604800 - 978307200,
            "lastUpdated": now - 978307200}}
        with tracker.open("wb") as stream:
            plistlib.dump({"activeProfileId": "fixture",
                          "profiles_v3": json.dumps([profile]).encode()}, stream)
        self.env["CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST"] = str(tracker)
        payload = {"session_id": "tracker-review", "cwd": str(self.home)}
        report = self.run_cli("--agent", "claude", "--usage-source", "auto",
                              "--cols", "196", payload=payload)
        strip_ansi = lambda text: re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
        self.assertRegex(strip_ansi(report), r"98\s*[%٪]")
        cache_files = list((self.home / "state").glob("*.json"))
        self.assertTrue(cache_files, "Auto tracker did not write normalized source cache")
        for path in cache_files:
            self.assertNotIn(canary, path.read_text(encoding="utf-8"))
        self.env["CODING_AGENT_USAGE_LINE_STATE_DIR"] = str(self.home / "empty-state")
        offline = self.run_cli("--agent", "claude", "--usage-source", "none",
                               "--cols", "196", payload=payload)
        self.assertNotRegex(strip_ansi(offline), r"98\s*[%٪]")

    def test_claude_cost_uses_selected_account_source(self):
        transcript = self.home / "claude.jsonl"
        self.write(transcript, [
            {"type": "user", "userType": "external", "promptSource": "typed",
             "timestamp": "2026-09-14T10:00:00Z", "message": {"content": "Fixture question"}},
            {"type": "assistant", "requestId": "claude-answer", "timestamp": "2026-09-14T10:00:02Z",
             "message": {"id": "claude-answer", "model": "claude-opus-4-6",
                "content": [{"type": "text", "text": "Fixture answer"}],
                "usage": {"input_tokens": 20, "output_tokens": 5,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}}])
        command = self.home / "cost-source.sh"
        reading = {"schema_version": 1, "as_of": time.time(),
                   "account": {"scope": "organization", "cost_usd": 7.25}}
        command.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps(reading) + "'\n", encoding="utf-8")
        result = json.loads(self.run_cli("--agent", "claude", "--mode", "cost",
            "--transcript", str(transcript), "--usage-source", "cmd:" + str(command),
            "--account", "cost-account", "--account-period", "month"))
        report = result["systemMessage"]
        self.assertIn("organization", report.lower())
        self.assertIn("cost-account", report)
        self.assertIn("7.25", report)

    def test_claude_panel_keeps_jsonl_with_selected_source(self):
        command = self.home / "panel-source.sh"
        marker = self.home / "panel-context.json"
        reading = {"schema_version": 1, "as_of": time.time(),
                   "account": {"scope": "organization", "cost_usd": 7.25}}
        command.write_text("#!/bin/sh\nIFS= read -r context || :\nprintf '%s' \"$context\" > "
            + str(marker) + "\nprintf '%s\\n' '" + json.dumps(reading) + "'\n", encoding="utf-8")
        report = self.run_cli("--agent", "claude", "--mode", "subagent",
            "--usage-source", "cmd:" + str(command), "--account", "panel-account",
            payload={"session_id": "panel-review", "columns": 120,
                     "tasks": [{"id": "shell-fixture", "type": "local_bash", "status": "running",
                                "description": "fixture command", "name": "Fixture shell"}]})
        self.assertTrue(marker.is_file(), "Panel did not use selected shared source")
        context = marker.read_text()
        self.assertTrue(context, "Panel source received no scoped JSON context")
        self.assertEqual(json.loads(context)["account"], "panel-account")
        lines = [json.loads(line) for line in report.splitlines()]
        self.assertEqual([line["id"] for line in lines], ["shell-fixture"])
        self.assertTrue(all(isinstance(line["content"], str) for line in lines))

    def test_failed_claude_source_is_not_retried_through_legacy_intake(self):
        command = self.home / "unavailable.sh"
        attempts = self.home / "attempts.txt"
        command.write_text("#!/bin/sh\nprintf 'attempt\\n' >> '" + str(attempts)
            + "'\nprintf '{}\\n'\n", encoding="utf-8")
        self.run_cli("--agent", "claude", "--usage-source", "cmd:" + str(command),
            "--account", "isolated-account", payload={"session_id": "failed-source",
                "cwd": str(self.home), "rate_limits": {"five_hour": {
                    "used_percentage": 11, "resets_at": time.time() + 18000}}})
        self.assertEqual(attempts.read_text().splitlines(), ["attempt"],
                         "A failed explicit source must not re-enter legacy collection")


if __name__ == "__main__":
    unittest.main(verbosity=2)
