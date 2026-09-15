"""Public CLI and orchestration; adapters/renderers never read each other."""
import json
import os
import sys

from .codex import native_quota, parse_jsonl, read_request_tree, root_context, rollout_identity
from .codex import origin_turn
from .render import account_summary, clean_text, codex_report, codex_stop_report, codex_summary
from .sources import collect, period_bounds, validate_source
from .state import claim_reportable_requests

USAGE = """usage: coding-agent-usage-line.py --agent {claude|codex} [--mode status|cost|subagent] [options]

One-shot coding-agent usage status and Stop-hook reports. --agent is required
except for --help and --selftest.

Modes:
  status                 Print a human-readable status (default).
  cost                   Print Stop-hook JSON; --all prints plain history.
  subagent               Claude panel output; Codex suggests --mode cost --all.

Shared options:
  --agent NAME           claude or codex.
  --transcript PATH      Read one transcript; never waits for stdin.
  --usage-source SPEC    auto, native, none/off, claude-usage-tracker,
                         codex-app-server, anthropic-admin, openai-admin,
                         experimental-claude-oauth, experimental-codex-api,
                         or cmd:PATH.
  --account NAME         Non-secret account cache namespace (default: default).
  --account-period P     day, week, or month (default: day; UTC boundaries).
  --cols N               Non-negative terminal width (0 means unknown width).
  --all                  Plain cost history without consuming Stop state.
  --diagnose             Redacted source/coverage diagnostics on stderr.

Claude display options:
  --color, --no-column-rules, --no-totals, --no-right-align,
  --no-account-totals, --no-datetime, --no-usage-text, --force-newline,
  --mark-spacing/--no-mark-spacing, --subscript-decimals.

Codex uses its built-in /statusline for a live footer; this command provides
one-shot status, Stop warnings and historical reports. Use --help with no
vendor credentials or transcript required.
"""

_VALUE_FLAGS = set(("--agent", "--mode", "--transcript", "--usage-source", "--account",
                    "--account-period", "--cols", "--prefix", "--label"))
_COMMON_FLAGS = _VALUE_FLAGS | set(("--all", "--diagnose", "--selftest", "-h", "--help"))
_CLAUDE_FLAGS = _COMMON_FLAGS | set(("--subscript-decimals", "--no-mark-spacing", "--mark-spacing",
    "--no-column-rules", "--column-rules", "--color", "--no-totals", "--no-right-align",
    "--no-account-totals", "--no-datetime", "--no-usage-text", "--force-newline"))


def _parse(argv, allowed):
    values = {}
    index = 0
    while index < len(argv):
        item = argv[index]
        if not item.startswith("-"):
            raise ValueError("unexpected argument %r" % item)
        if item not in allowed:
            raise ValueError("unknown option %s" % item)
        if item in _VALUE_FLAGS:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise ValueError("%s requires a value" % item)
            values[item] = argv[index + 1]; index += 2
        else:
            values[item] = True; index += 1
    return values


def _safe_payload(raw):
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError): return {}


def _diagnostic_source(value):
    value = str(value or "auto")
    if value.startswith("cmd:"): return "cmd"
    return clean_text(value, 48) or "unknown"


def _emit_codex_diagnose(options, reading, coverage, reason=""):
    """One redacted diagnostic line; never exposes command paths or payloads."""
    source = _diagnostic_source((reading.get("source") if isinstance(reading, dict) else "")
                                or options.get("--usage-source", "auto"))
    available = bool(reading and reading.get("as_of") is not None)
    fields = ("diagnose source=%s reading=%s stale=%s as_of=%s retry_at=%s "
              "child_threads=%s child_coverage=%s ambiguous_legacy=%s" %
              (source, "available" if available else "unavailable",
               bool(reading.get("stale")) if isinstance(reading, dict) else False,
               reading.get("as_of", "") if isinstance(reading, dict) else "",
               reading.get("retry_at", "") if isinstance(reading, dict) else "",
               coverage.get("child_threads", 0), coverage.get("child_coverage", "unknown"),
               coverage.get("ambiguous_legacy_records", 0)))
    if reason: fields += " reason=" + clean_text(reason, 48)
    sys.stderr.write(fields + "\n")


def _reading(agent, options, payload, native=None):
    source = options.get("--usage-source", os.environ.get("CODING_AGENT_USAGE_LINE_USAGE_SOURCE", "auto"))
    account = options.get("--account", "default")
    period = options.get("--account-period", "day")
    context = {"agent": agent, "session": payload.get("session_id", ""),
               "model": payload.get("model", ""), "account": account, "period": period}
    if isinstance(payload.get("rate_limits"), dict): context["rate_limits"] = payload["rate_limits"]
    if isinstance(native, dict) and native:
        if isinstance(native.get("rate_limits"), dict):
            context["rate_limits"] = native["rate_limits"]; context["as_of"] = native.get("as_of")
        else: context["rate_limits"] = native
    return collect(agent, source, account, period, context)


def codex_main(options, raw):
    mode = options.get("--mode", "status")
    if mode == "subagent":
        sys.stderr.write("Codex has no subagent-panel hook; use --mode cost --all for child reports.\n")
        return 2
    explicit = "--transcript" in options
    payload = {} if explicit else _safe_payload(raw)
    transcript = options.get("--transcript") or payload.get("transcript_path") or payload.get("rollout_path")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        if options.get("--diagnose"):
            sys.stderr.write("diagnose source=%s reading=unavailable reason=missing-transcript\n" %
                             _diagnostic_source(options.get("--usage-source", "auto")))
        if mode == "cost": print("{}")
        else: print("Codex: usage unavailable")
        return 0
    try:
        session = str(payload.get("session_id") or payload.get("sessionId") or "")
        root_records = parse_jsonl(transcript)
        # Metadata is usable even when Stop runs before its response usage has
        # been appended, so explicit history never falls into a shared default
        # cache namespace merely because it has no request rows yet.
        turn = str(payload.get("turn_id") or payload.get("turnId") or "")
        identity = rollout_identity(root_records, turn)
        coverage = {}
        rows = read_request_tree(transcript, session, diagnostics=coverage)
        if not session:
            session = next((row.session_id for row in rows if row.session_id), identity.get("session_id", ""))
        # Stop's turn ID is authoritative. An explicit historical transcript
        # intentionally reports all rows and never consumes hook state.
        selected = [row for row in rows if not turn or origin_turn(row) == turn]
        if options.get("--all") and mode == "cost":
            if options.get("--diagnose"):
                # History is transcript-only; do not refresh a selected
                # external account source merely to produce diagnostics.
                _emit_codex_diagnose(options, {}, coverage, "history-no-account-refresh")
            print(codex_report(rows)); return 0
        # Explicit history has no hook payload.  Its real session/model still
        # scopes custom-command context and cache identities.
        reading_payload = dict(payload)
        if session: reading_payload["session_id"] = session
        root_rows = [row for row in selected if not row.child]
        session_row = root_rows[-1] if root_rows else (selected[-1] if selected else None)
        # A Stop for an older root must retain that root's own model/effort,
        # rather than inheriting the most recent session turn's configuration.
        model = str((session_row.model if session_row and session_row.model else
                     payload.get("model") or identity.get("model")) or "")
        effort = str((session_row.effort if session_row and session_row.effort else
                      payload.get("effort") or payload.get("reasoning_effort") or identity.get("effort")) or "")
        if model: reading_payload["model"] = model
        reading = _reading("codex", options, reading_payload, native_quota(root_records))
        line = codex_summary(selected if turn else rows, model, effort)
        context_usage, capacity, occupancy = root_context(root_records)
        if capacity and occupancy is not None:
            line += " | context %s/%s" % (occupancy, capacity)
        account_line = account_summary(reading, options.get("--account", "default"), options.get("--account-period", "day"))
        if account_line: line += "\n" + account_line
        if options.get("--diagnose"):
            _emit_codex_diagnose(options, reading, coverage)
        if mode != "cost":
            print(line); return 0
        claimable = selected if turn else rows
        if not explicit:
            # Prepare all fallible source/render work before marking report
            # state. A failed source/render therefore never consumes usage.
            if not turn:
                print("{}"); return 0
            fresh_ids = set(claim_reportable_requests(
                session, turn, [(row.request_id, origin_turn(row) or ("child:" + row.thread_id + ":" + row.turn_id)) for row in rows], consume=True))
            if not fresh_ids:
                print("{}"); return 0
            fresh_current = [row for row in selected if row.request_id in fresh_ids]
            late = {}
            for row in rows:
                root = origin_turn(row) or ("child:" + row.thread_id + ":" + row.turn_id)
                if row.request_id in fresh_ids and root != turn:
                    late.setdefault(root, []).append(row)
            line = codex_stop_report(turn, fresh_current, rows, late, model, effort)
            if account_line: line += "\n" + account_line
        print(json.dumps({"systemMessage": line}, separators=(",", ":")))
        return 0
    except Exception:
        # Hooks must never interfere with the agent's execution.
        if mode == "cost": print("{}")
        else: print("Codex: usage unavailable")
        return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(USAGE); return 0
    if "--selftest" in argv:
        from . import claude
        return claude.main(argv)
    # Validate before stdin so malformed hooks cannot hang waiting for input.
    rough_agent = argv[argv.index("--agent") + 1] if "--agent" in argv and argv.index("--agent") + 1 < len(argv) else ""
    try:
        options = _parse(argv, _CLAUDE_FLAGS if rough_agent == "claude" else _COMMON_FLAGS)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n"); return 2
    agent = options.get("--agent")
    if agent not in ("claude", "codex"):
        sys.stderr.write("--agent claude|codex is required\n"); return 2
    mode = options.get("--mode", "status")
    if mode not in ("status", "cost", "subagent"):
        sys.stderr.write("unknown --mode %r\n" % mode); return 2
    try:
        if "--cols" in options:
            cols = int(options["--cols"])
            if cols < 0: raise ValueError("--cols must be a non-negative integer")
        validate_source(agent, options.get("--usage-source", os.environ.get("CODING_AGENT_USAGE_LINE_USAGE_SOURCE", "auto")))
        period_bounds(options.get("--account-period", "day"))
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n"); return 2
    if agent == "codex" and mode == "subagent":
        sys.stderr.write("Codex has no subagent-panel hook; use --mode cost --all for child reports.\n")
        return 2
    if agent == "claude":
        # Do not initialize Claude-specific cache/display state in a Codex
        # invocation; selection was validated above.
        from . import claude
        # Claude rendering remains its tested adapter. Prefer the product env
        # spelling while retaining old fixture settings during migration.
        forwarded = []
        index = 0
        # Account scope is part of the shared source contract for Claude too;
        # retain it for the adapter rather than silently dropping it here.
        omitted = set(("--agent",))
        while index < len(argv):
            item = argv[index]
            if item in omitted:
                index += 2
            else:
                forwarded.append(item)
                if item in _VALUE_FLAGS:
                    forwarded.append(argv[index + 1]); index += 2
                else:
                    index += 1
        if "--usage-source" not in forwarded and os.environ.get("CODING_AGENT_USAGE_LINE_USAGE_SOURCE"):
            forwarded.extend(("--usage-source", os.environ["CODING_AGENT_USAGE_LINE_USAGE_SOURCE"]))
        return claude.main(forwarded)
    raw = ""
    if "--transcript" not in options:
        try: raw = sys.stdin.read()
        except Exception: raw = ""
    return codex_main(options, raw)
