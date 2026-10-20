"""Public CLI and orchestration; adapters/renderers never read each other."""
import json
import os
import sys
import textwrap

from . import config
from .codex import native_quota, parse_jsonl, read_request_tree, root_context, rollout_identity
from .codex import origin_turn, rollout_cwd
from .options import LAYERS, flag_values, from_flags, merge, parse
from .options_spec import OPTIONS
from .render import account_summary, clean_text, codex_report, codex_stop_report, codex_summary
from .sources import collect, period_bounds, validate_source
from .state import claim_reportable_requests

# The options this command line takes, from spec/options.jsonc.
_FLAGGED = [o for o in OPTIONS.values() if o["flag"] and "py" in o["ports"]]


def _negative(option):
    return "--no-" + option["flag"][2:]


def _spellings(option):
    """Every way the command line may write the option: its flag, the
    flag's aliases, and the `--no-` form of a negatable one."""
    names = [option["flag"]] + list(option.get("aliases", ()))
    if option.get("negatable"):
        names.append(_negative(option))
    return names


def _agent_flags(agent):
    """The spellings `--agent AGENT` accepts: every agent's, and those of
    the options whose `agents` name it."""
    return frozenset(name for o in _FLAGGED
                     if agent in o.get("agents", (agent,))
                     for name in _spellings(o))


_VALUE_FLAGS = frozenset(o["flag"] for o in _FLAGGED if o["type"] != "bool")
# Without a known --agent, only the flags every agent takes.
_COMMON_FLAGS = frozenset(name for o in _FLAGGED if "agents" not in o
                          for name in _spellings(o))
_CLAUDE_FLAGS = _agent_flags("claude")
_CODEX_FLAGS = _agent_flags("codex")

_WIDTH = 79
_GUTTER = 25


def _usage_entry(option):
    """One flag's lines of USAGE: its spellings, the default's opposite
    first for a negatable bool, and its usage text with its modes."""
    names = _spellings(option)
    if option.get("negatable") and option["default"] is True:
        names = [names[-1]] + names[:-1]
    names = [n for n in names if n.startswith("--")]
    names = [n for n in option.get("aliases", ()) if not n.startswith("--")] + names
    head = ", ".join(names)
    if option["type"] != "bool":
        head += " " + (option.get("metavar") or "|".join(option["items"]))
    text = option["usage"]
    modes = option.get("modes")
    if modes and len(modes) < 3:
        text += " [%s]" % ", ".join(modes)
    body = textwrap.wrap(text, _WIDTH - _GUTTER, break_on_hyphens=False)
    head = "  " + head
    if len(head) + 2 > _GUTTER:
        return [head] + [" " * _GUTTER + line for line in body]
    return ([head.ljust(_GUTTER) + body[0]]
            + [" " * _GUTTER + line for line in body[1:]])


def _usage_section(title, options):
    lines = [title + ":"]
    for option in options:
        lines += _usage_entry(option)
    return "\n".join(lines) + "\n"


USAGE = ("""usage: coding-agent-usage-line.py --agent {claude|codex} [--mode status|cost|subagent] [options]

One-shot coding-agent usage status and Stop-hook reports. --agent is required
except for --help and --selftest.

Modes:
  status                 Print a human-readable status (default).
  cost                   Print Stop-hook JSON; --all prints plain history.
  subagent               Claude panel output; Codex suggests --mode cost --all.

""" + _usage_section("Shared options",
                     [o for o in _FLAGGED if o["doc-table"] == "shared"])
    + "\n" + _usage_section(
        "Claude display options, in the modes in brackets",
        [o for o in _FLAGGED if o["doc-table"] == "display"])
    + "\n" + _usage_section(
        "Other", [o for o in _FLAGGED if o["doc-table"] is None])
    + """
Codex uses its built-in /statusline for a live footer; this command provides
one-shot status, Stop warnings and historical reports. Use --help with no
vendor credentials or transcript required.
""")


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
                                or options["usage-source"])
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
    if options.warnings: fields += " config_warnings=%d" % len(options.warnings)
    sys.stderr.write(fields + "\n")


def _reading(agent, options, payload, native=None):
    source = options["usage-source"]
    account = options["account"]
    period = options["account-period"]
    context = {"agent": agent, "session": payload.get("session_id", ""),
               "model": payload.get("model", ""), "account": account, "period": period}
    if isinstance(payload.get("rate_limits"), dict): context["rate_limits"] = payload["rate_limits"]
    if isinstance(native, dict) and native:
        if isinstance(native.get("rate_limits"), dict):
            context["rate_limits"] = native["rate_limits"]; context["as_of"] = native.get("as_of")
        else: context["rate_limits"] = native
    return collect(agent, source, account, period, context)


def codex_main(options, raw):
    mode = options["mode"]
    if mode == "subagent":
        sys.stderr.write("Codex has no subagent-panel hook; use --mode cost --all for child reports.\n")
        return 2
    explicit = options.given("transcript")
    payload = {} if explicit else _safe_payload(raw)
    transcript = options["transcript"] or payload.get("transcript_path") or payload.get("rollout_path")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        if options["diagnose"]:
            sys.stderr.write("diagnose source=%s reading=unavailable reason=missing-transcript\n" %
                             _diagnostic_source(options["usage-source"]))
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
        if options["all"] and mode == "cost":
            if options["diagnose"]:
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
        account_line = account_summary(reading, options["account"], options["account-period"])
        if account_line: line += "\n" + account_line
        if options["diagnose"]:
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


def _payload_start(agent, mode, raw, transcript):
    """Where this run's project walk starts: the payload's directory, a
    Codex rollout's, else the process's (config-merge.md, "Finding the
    root")."""
    payload = _safe_payload(raw)
    rollout = None
    if agent == "codex" and not payload.get("cwd"):
        path = transcript or payload.get("transcript_path") or payload.get("rollout_path")
        rollout = rollout_cwd(path) if isinstance(path, str) and path else None
    return config.start_dir(agent, mode, payload, rollout)


def _merged(flags, found, agent=None, ports=("py",)):
    """The flags over the files `found`, with the files' warnings and the
    merge's own: a usage-source a file gives that this agent (any agent,
    for None) cannot read is skipped, as any bad value is, and a flag that overrides a file's value
    for an option the mod reads too is said (Decided 1), since the band
    then draws the file's."""
    files, warnings = list(found.layers), list(found.warnings)
    while True:
        options = merge(flags, files, ports, warnings)
        layer = options.layer("usage-source")
        if layer not in config.FILE_LAYERS:
            break
        try:
            validate_source(agent, options["usage-source"])
            break
        except ValueError:
            bad = next(f for f in files if f.name == layer)
            warnings.append("%s: \"usage-source\" %s is no source %s reads; "
                            "skipped" % (bad.path, json.dumps(
                                options["usage-source"], ensure_ascii=False),
                                agent or "any agent"))
            files = [f if f is not bad else f._replace(values={
                k: v for k, v in f.values.items() if k != "usage-source"})
                for f in files]
    for name in flags:
        option = OPTIONS[name]
        if "mod" not in option["ports"]:
            continue
        setter = next((f for f in files if name in f.values), None)
        if setter is not None:
            warnings.append("%s: %s on the command line overrides its %s here, "
                            "which the mod reads" % (setter.path, option["flag"],
                                                     json.dumps(name)))
    return merge(flags, files, ports, warnings)


def _show_config(found, options):
    """--show-config's text: where each layer is, every option a file may
    set with its value and layer, and the files' warnings."""
    out = ["Configuration, read from %s:" % found.start]
    where = {"flag": "the command line", "default": "spec/options.jsonc"}
    for layer in LAYERS:
        path = where.get(layer) or found.paths.get(layer)
        if path is None:
            path = "none: no project file between here and the walk's end"
        elif layer in config.FILE_LAYERS and not os.path.isfile(path):
            path += " (none)"
        out.append("  %-14s %s" % (layer, path))
    out += ["", "%-30s %-14s %s" % ("option", "layer", "value")]
    for name, option in OPTIONS.items():
        if not option["file"]:
            continue
        if option["type"] == "table":
            for row, rec in options[name].items():
                for field, value in rec.items():
                    out.append("%-30s %-14s %s" % (
                        "%s.%s.%s" % (name, row, field),
                        options.field_layer(name, row, field),
                        json.dumps(value, ensure_ascii=False)))
            continue
        value = options[name]
        out.append("%-30s %-14s %s" % (
            name, options.layer(name),
            json.dumps(list(value) if isinstance(value, tuple) else value,
                       ensure_ascii=False)))
    if options.warnings:
        out += ["", "Warnings:"] + ["  " + w for w in options.warnings]
    return "\n".join(out) + "\n"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(USAGE); return 0
    if "--selftest" in argv:
        from . import claude
        return claude.selftest()
    # Validate before stdin so malformed hooks cannot hang waiting for input.
    rough_agent = argv[argv.index("--agent") + 1] if "--agent" in argv and argv.index("--agent") + 1 < len(argv) else ""
    try:
        allowed = {"claude": _CLAUDE_FLAGS, "codex": _CODEX_FLAGS}.get(rough_agent, _COMMON_FLAGS)
        parsed = parse(argv, allowed)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n"); return 2
    # The last of each value flag, as written, for the checks below.
    written = dict(parsed)
    agent = written.get("--agent")
    if "--show-config" in written:
        # No payload: the walk starts where the command runs.
        found = config.load(os.getcwd())
        options = _merged(flag_values(parsed), found, agent, ("py", "mod"))
        sys.stdout.write(_show_config(found, options)); return 0
    if agent not in ("claude", "codex"):
        sys.stderr.write("--agent claude|codex is required\n"); return 2
    mode = written.get("--mode", "status")
    if mode not in ("status", "cost", "subagent"):
        sys.stderr.write("unknown --mode %r\n" % mode); return 2
    try:
        if "--cols" in written:
            cols = int(written["--cols"])
            if cols < 0: raise ValueError("--cols must be a non-negative integer")
        if "--right-edge" in written:
            edge = int(written["--right-edge"])
            if edge < 0: raise ValueError("--right-edge must be a non-negative integer")
        flagged = from_flags(parsed)
        validate_source(agent, flagged["usage-source"])
        period_bounds(flagged["account-period"])
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n"); return 2
    if agent == "codex" and mode == "subagent":
        sys.stderr.write("Codex has no subagent-panel hook; use --mode cost --all for child reports.\n")
        return 2
    # Stdin before the files: the payload says where the project is.  A
    # named transcript or figures document is a complete offline input, so
    # it never waits on a still-open pipe; the panel always has a payload.
    transcript = written.get("--transcript")
    if agent == "claude" and "--from-figures" in written:
        offline = True
    else:
        offline = mode != "subagent" and bool(transcript)
    raw = ""
    if not offline:
        try: raw = sys.stdin.read()
        except Exception: raw = ""
    found = config.load(_payload_start(agent, mode, raw, transcript))
    options = _merged(flag_values(parsed), found, agent)
    for warning in options.warnings:
        sys.stderr.write(warning + "\n")
    if agent == "claude":
        # Do not initialize Claude-specific cache/display state in a Codex
        # invocation; selection was validated above.
        from . import claude
        return claude.main(options, raw)
    return codex_main(options, raw)
