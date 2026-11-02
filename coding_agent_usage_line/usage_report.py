"""`--mode usage`: the account's plan windows as one JSON object.

No payload is read.  The reading comes from sources.collect, the same
chain the agent panel and the Stop hook use when their payload holds no
plan windows: a cached native reading, else the source's fallback.  The
session that scopes a cached reading under `--account default` is
`--transcript`'s, else (Claude) $CLAUDE_CODE_SESSION_ID, which Claude Code
sets for the commands it runs.  Nothing here writes hook state; collect
may refresh a fallback's cache, as every mode's call does.
"""
import json
import os
import time

from .sources import collect

SCHEMA_VERSION = 1
# No reading, or one without a plan window.  2 stays the usage error.
EXIT_NO_READING = 1


def _now():
    """The clock, which CODING_AGENT_USAGE_LINE_NOW pins for the tests."""
    value = os.environ.get("CODING_AGENT_USAGE_LINE_NOW", "")
    try:
        return float(value) if value else time.time()
    except ValueError:
        return time.time()


def _context(agent, transcript):
    """The session, model and native quota collect is given: from a named
    transcript, else (Claude) the session Claude Code runs the command in."""
    if agent == "codex":
        if not transcript or not os.path.isfile(transcript):
            return {}
        from .codex import native_quota, parse_jsonl, rollout_identity
        records = parse_jsonl(transcript)
        identity = rollout_identity(records, "")
        context = {"session": str(identity.get("session_id") or ""),
                   "model": str(identity.get("model") or "")}
        native = native_quota(records)
        if isinstance(native, dict) and native:
            if isinstance(native.get("rate_limits"), dict):
                context["rate_limits"] = native["rate_limits"]
                context["as_of"] = native.get("as_of")
            else:
                context["rate_limits"] = native
        return context
    if transcript:
        name = os.path.basename(transcript)
        session = name[:-len(".jsonl")] if name.endswith(".jsonl") else ""
    else:
        session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    return {"session": session}


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _windows(reading):
    """Every bucket's windows, flattened, with only the whitelisted fields."""
    out = []
    buckets = reading.get("buckets") if isinstance(reading, dict) else None
    for bucket in buckets if isinstance(buckets, list) else []:
        if not isinstance(bucket, dict):
            continue
        for window in bucket.get("windows") or []:
            if not isinstance(window, dict):
                continue
            used = _number(window.get("used_percent"))
            out.append({
                "id": window.get("id"),
                "bucket": bucket.get("id"),
                "label": bucket.get("label"),
                "used_percent": used,
                "left_percent": None if used is None else max(0.0, 100.0 - used),
                "resets_at": _number(window.get("resets_at")),
                "duration_seconds": _number(window.get("duration_seconds")),
                "expired": bool(window.get("expired")),
            })
    return out


def report(agent, options):
    """(the JSON object to print, the exit status)."""
    now = _now()
    try:
        context = _context(agent, options["transcript"])
        reading = collect(agent, options["usage-source"], options["account"],
                          options["account-period"], context, now)
    except Exception:
        reading = {}
    windows = _windows(reading)
    as_of = _number(reading.get("as_of")) if isinstance(reading, dict) else None
    out = {"schema_version": SCHEMA_VERSION, "agent": agent,
           "source": (reading.get("source") if windows else None) or None,
           "as_of": as_of if windows else None,
           "age_seconds": (round(max(0.0, now - as_of), 3)
                           if windows and as_of is not None else None),
           "stale": bool(reading.get("stale")) if windows else None,
           "windows": windows}
    if not windows:
        out["reason"] = "no-reading"
        return out, EXIT_NO_READING
    return out, 0


def main(agent, options):
    out, status = report(agent, options)
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return status
