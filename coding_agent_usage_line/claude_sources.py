"""Prepared shared usage readings for Claude orchestration.

This module deliberately does not alter the historical Claude source/cache
path.  Callers choose when to use the returned legacy projection.
"""
from datetime import datetime, timezone
from typing import NamedTuple

from . import sources
from .claude_records import Limits, NO_LIMITS
from .render import account_summary


class PreparedClaudeReading(NamedTuple):
    reading: dict
    limits: Limits
    account_text: str


def _pct(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return ("%.6f" % number).rstrip("0").rstrip(".")


def _reset(value):
    if value is None:
        return ""
    try:
        # Legacy Claude STAMP_FMT strings are parsed as local wall time.
        return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def legacy_limits(reading):
    """Project only an unassociated default quota bucket into Claude chrome."""
    if not isinstance(reading, dict):
        return NO_LIMITS
    if reading.get("stale"):
        return NO_LIMITS
    buckets = reading.get("buckets")
    if not isinstance(buckets, list) or len(buckets) != 1:
        return NO_LIMITS
    bucket = buckets[0]
    if not isinstance(bucket, dict) or bucket.get("id") != "default":
        return NO_LIMITS
    if bucket.get("model") or bucket.get("feature") or bucket.get("label") not in (None, "", "default"):
        return NO_LIMITS
    five = week = None
    for window in bucket.get("windows", []):
        if not isinstance(window, dict) or window.get("used_percent") is None or window.get("expired"):
            continue
        duration = window.get("duration_seconds")
        if duration == 18000 and five is None: five = window
        elif duration == 604800 and week is None: week = window
    if five is None and week is None:
        return NO_LIMITS
    return Limits(_pct(five.get("used_percent")) if five else "",
                  _reset(five.get("resets_at")) if five else "", "",
                  _pct(week.get("used_percent")) if week else "",
                  _reset(week.get("resets_at")) if week else "", "")


def prepare_claude_reading(spec, account, period, context, now=None):
    """Collect once and return canonical, legacy-safe, and account render forms."""
    safe = context if isinstance(context, dict) else {}
    reading = sources.collect("claude", spec, account, period, safe, now)
    return PreparedClaudeReading(reading, legacy_limits(reading),
                                 account_summary(reading, account, period, now))
