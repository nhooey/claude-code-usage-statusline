"""Pure, terminal-safe rendering for agent-neutral snapshots."""
import math
from datetime import datetime, timezone
from .codex import grouped_turns, origin_turn, totals
from . import formatting as fmt
from .formatting import dur_fmt, humanize


def clean_text(value, maximum=80):
    if not isinstance(value, str): return ""
    value = "".join(c for c in value if ord(c) >= 32 and not 127 <= ord(c) <= 159)
    return value[:maximum]


def format_tokens(value):
    if value is None: return "?"
    return humanize(value).rstrip()


def _paint(ink, value, dim=False):
    """A small, self-contained terminal segment with its colour reset."""
    return (fmt.DIM if dim else "") + ink + value + fmt.R


def _model(model, effort):
    """One model cell; effort stays spelled out because it is Codex metadata."""
    label = clean_text(model, 48) or "Codex"
    effort = clean_text(effort, 32)
    return fmt.E_MOD + _paint(fmt.F_PUR, label + ("/" + effort if effort else ""))


def _tokens(usage):
    """Input/output are distinct, including a genuinely unavailable total."""
    # Keep the words: cost-hook consumers and copied terminal output both use
    # them as the least surprising account of the two directions.
    return "%s in %s out %s" % (fmt.E_TOK, format_tokens(usage.input_total),
                                 format_tokens(usage.output_total))


def _window_label(window):
    label = clean_text(window.get("id"), 48) or "quota"
    duration = window.get("duration_seconds")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and math.isfinite(duration) and duration > 0:
        if duration % 86400 == 0: label += " %dd" % (duration / 86400)
        elif duration % 3600 == 0: label += " %dh" % (duration / 3600)
        elif duration % 60 == 0: label += " %dm" % (duration / 60)
        else: label += " %ds" % duration
    return label


def _lifecycle_parts(row, indent=""):
    """Known lifecycle fields only; resumes/missing events stay unlabelled."""
    parts = []
    if row.started_at is not None:
        try: parts.append("started " + datetime.fromtimestamp(row.started_at, timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"))
        except (OverflowError, OSError, ValueError): pass
    if row.completed_at is not None:
        try: parts.append("completed " + datetime.fromtimestamp(row.completed_at, timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"))
        except (OverflowError, OSError, ValueError): pass
    if row.started_at is not None and row.completed_at is not None and row.completed_at >= row.started_at:
        parts.append("elapsed " + dur_fmt(row.completed_at - row.started_at))
    if row.user_message: parts.append("user " + clean_text(row.user_message, 80))
    if row.assistant_message: parts.append("assistant " + clean_text(row.assistant_message, 80))
    return parts


def codex_summary(rows, model="", effort=""):
    usage = totals(rows)
    fields = []
    model, effort = clean_text(model), clean_text(effort)
    if model: fields.append(_model(model, effort))
    if usage.input_total is not None or usage.output_total is not None:
        fields.append(_tokens(usage))
    return "Codex " + (" | ".join(fields) if fields else "usage unavailable")


def account_summary(reading, account, period, now=None):
    """A separate account-period row: never a made-up session cost/share."""
    if not isinstance(reading, dict): return ""
    quota_fields, account_fields = [], []
    if isinstance(now, datetime):
        now_dt = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    elif isinstance(now, (int, float)) and not isinstance(now, bool):
        try: now_dt = datetime.fromtimestamp(now, timezone.utc)
        except (OverflowError, OSError, ValueError): now_dt = datetime.now(timezone.utc)
    else:
        now_dt = datetime.now(timezone.utc)
    buckets = reading.get("buckets")
    if not isinstance(buckets, list):
        buckets = [{"id": "default", "label": "default", "windows": reading.get("windows", [])}]
    for bucket in buckets:
        if not isinstance(bucket, dict) or not isinstance(bucket.get("windows"), list): continue
        windows = []
        for window in bucket["windows"]:
            if not isinstance(window, dict): continue
            label = _window_label(window)
            try: used = float(window.get("used_percent"))
            except (TypeError, ValueError, OverflowError): used = None
            item = label + (" " + "%.0f%%" % used
                            if used is not None and math.isfinite(used) else " unavailable")
            if window.get("expired"): item += " expired"
            reset = window.get("resets_at")
            if isinstance(reset, (int, float)) and not isinstance(reset, bool):
                try:
                    if math.isfinite(reset):
                        reset_dt = datetime.fromtimestamp(reset, timezone.utc)
                        stamp = "%H:%MZ" if reset_dt.date() == now_dt.date() else "%b %d %H:%MZ"
                        item += " %s %s" % (fmt.E_RESET, reset_dt.strftime(stamp))
                except (OverflowError, OSError, ValueError):
                    pass
            windows.append(item)
        if windows:
            heading = clean_text(bucket.get("label"), 48) or clean_text(bucket.get("id"), 48) or "quota"
            explicit = clean_text(bucket.get("model") or bucket.get("feature"), 48)
            quota_fields.append("%s %s%s: %s" % (fmt.E_SESS, heading,
                                (" (" + explicit + ")" if explicit else ""), ", ".join(windows)))
    acct = reading.get("account") if isinstance(reading.get("account"), dict) else {}
    if acct:
        parts = []
        usage = type("AccountUsage", (), {"input_total": acct.get("input_tokens"), "output_total": acct.get("output_tokens")})()
        if acct.get("input_tokens") is not None or acct.get("output_tokens") is not None: parts.append(_tokens(usage))
        try:
            if acct.get("cost_usd") is not None: parts.append(fmt.E_COST + _paint(fmt.F_YEL, "$%.2f" % float(acct["cost_usd"])))
        except (TypeError, ValueError, OverflowError): pass
        if parts: account_fields.append("%s organization %s %s%s: %s" %
                                       (fmt.E_ACCT, clean_text(account) or "default", period,
                                        " stale" if reading.get("stale") else "", " | ".join(parts)))
    fields = []
    if quota_fields: fields.append("quota%s\n  %s" % (" stale" if reading.get("stale") else "", "\n  ".join(quota_fields)))
    if account_fields:
        fields.extend(account_fields)
    return "\n".join(fields)


def codex_report(rows):
    """Plain historical report: root-inclusive totals plus completed children."""
    lines = []
    for root, group in grouped_turns(rows).items():
        all_rows = group["root"] + [row for child in group["children"].values() for row in child]
        primary = (group["root"] or all_rows or [None])[0]
        model = clean_text(primary.model if primary else "", 48) or "Codex"
        effort = clean_text(primary.effort if primary else "", 32)
        unattributed = root.startswith("unattributed-child:")
        label = "unattributed child/session usage" if unattributed else (clean_text(root, 48) or "turn")
        usage = totals(all_rows)
        prefix = label if unattributed else "turn " + label
        lines.append("%s %s %s total %s" %
                     (fmt.E_SUM, prefix, _model(model, effort), _tokens(usage)))
        if group["root"]:
            details = _lifecycle_parts(group["root"][0])
            if details: lines.append("  root " + " | ".join(details))
        for child_rows in group["children"].values():
            child = child_rows[0]
            if not child.completed:
                continue
            usage = totals(child_rows)
            child_label = clean_text(child.turn_id, 48) or "turn"
            thread = clean_text(child.thread_id, 48)
            if thread: child_label += " [thread " + thread + "]"
            parts = ["  " + fmt.E_ROW_AGENTS + " child " + child_label, "complete"]
            model = clean_text(child.model, 48)
            effort = clean_text(child.effort, 32)
            if model: parts.append(_model(model, effort))
            parts.extend(_lifecycle_parts(child))
            parts.append(_tokens(usage))
            lines.append(" | ".join(parts))
    return "\n".join(lines) or "Codex: usage unavailable"


def codex_stop_report(current_turn, current_rows, session_rows, late_rows, model="", effort=""):
    """Render a Stop scope without persisting or inspecting transcripts."""
    current = totals(current_rows)
    session = totals(session_rows)
    identity = next((row for row in current_rows if not row.child),
                    current_rows[0] if current_rows else None)
    selected_model = clean_text(identity.model if identity and identity.model else model, 48) or "Codex"
    selected_effort = clean_text(identity.effort if identity and identity.effort else effort, 32)
    label = clean_text(current_turn, 48) or "turn"
    lines = []
    if current_rows:
        lines.append("%s Codex turn %s incremental %s | %s" %
                     (fmt.E_TURN, label, _model(selected_model, selected_effort), _tokens(current)))
    lines.append("%s Codex session total | %s" % (fmt.E_SESSION, _tokens(session)))
    for root, rows in late_rows.items():
        usage = totals(rows)
        children = " child" if any(row.child for row in rows) else ""
        late_label = "unattributed child" if root.startswith("child:") else "late turn " + (clean_text(root, 48) or "turn") + children
        # A turn ID is not a thread identity: child rollouts can reuse it.
        # Keep each surviving thread visible on the late row, just as history
        # does, rather than silently combining it into a fictitious child.
        child_ids = []
        for row in rows:
            if not row.child: continue
            child_id = clean_text(row.turn_id, 48) or "turn"
            thread = clean_text(row.thread_id, 48)
            if thread: child_id += " [thread " + thread + "]"
            if child_id not in child_ids: child_ids.append(child_id)
        if child_ids: late_label += " (" + ", ".join(child_ids) + ")"
        lines.append("%s Codex %s | %s" % (fmt.E_ROW_AGENTS, late_label, _tokens(usage)))
    return "\n".join(lines)
