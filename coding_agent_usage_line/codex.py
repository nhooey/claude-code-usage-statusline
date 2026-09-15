"""Tolerant, read-only accounting for Codex rollout JSONL files.

Codex's current records distinguish a *thread* ID from the persisted session
ID.  We retain both and only sum request-level ``usage``; turn/thread usage is
cumulative context and is never a billable request.
"""
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone

from .models import TokenUsage, UsageRequest


def _number(value):
    if isinstance(value, bool): return None
    try:
        value = float(value)
        return int(value) if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError, OverflowError): return None


def _stamp(value):
    if isinstance(value, bool): return None
    if isinstance(value, (int, float)):
        try:
            value = float(value)
            datetime.fromtimestamp(value, timezone.utc)
            return value if math.isfinite(value) else None
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    if not isinstance(value, str): return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        value = (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)).timestamp()
        datetime.fromtimestamp(value, timezone.utc)
        return value if math.isfinite(value) else None
    except (ValueError, OverflowError, OSError): return None


def _get(value, *names):
    if not isinstance(value, dict): return None
    for name in names:
        if name in value: return value[name]
    return None


def _text(value, maximum=256):
    if not isinstance(value, str) or len(value) > maximum: return ""
    return value if not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value) else ""


def token_usage(value):
    """Normalize per-request tokens without adding cached/reasoning subsets."""
    value = value if isinstance(value, dict) else {}
    inp = _number(_get(value, "input_tokens", "inputTokens"))
    cached = _number(_get(value, "cached_input_tokens", "cachedInputTokens"))
    out = _number(_get(value, "output_tokens", "outputTokens"))
    reasoning = _number(_get(value, "reasoning_output_tokens", "reasoningOutputTokens"))
    if inp is not None and cached is not None and cached > inp: return TokenUsage()
    if out is not None and reasoning is not None and reasoning > out: return TokenUsage()
    return TokenUsage(inp, cached, out, reasoning)


def _nonempty(usage): return any(value is not None for value in usage)


def _parse_jsonl_once(path):
    """Return complete records and whether a writer left an unfinished tail."""
    records, incomplete = [], False
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.endswith("\n"):
                incomplete = True; continue
            try: item = json.loads(line)
            except (TypeError, ValueError): continue
            if isinstance(item, dict): records.append(item)
    return records, incomplete


def parse_jsonl(path, tail_attempts=2):
    """Read complete object records only; ignore a concurrently-written tail."""
    try:
        for attempt in range(max(0, int(tail_attempts)) + 1):
            records, incomplete = _parse_jsonl_once(path)
            if not incomplete or attempt >= tail_attempts: return records
            # Stop can race Codex's final append.  A very small bounded retry
            # picks up a completed line without ever waiting for lifecycle.
            time.sleep(0.02)
    except (OSError, UnicodeError, ValueError, OverflowError):
        return []


def _payload(record):
    value = _get(record, "payload", "data")
    return value if isinstance(value, dict) else record


def _metadata(records, fallback_session=""):
    """Index current metadata and context by their real identities."""
    threads, contexts, parents = {}, {}, {}
    owner_thread = ""
    for record in records:
        typ = _text(_get(record, "type", "record_type", "kind"))
        payload = _payload(record)
        if typ == "session_meta":
            thread = _text(payload.get("id")); session = _text(payload.get("session_id")) or fallback_session
            if thread:
                owner_thread = thread
                threads[thread] = {"session": session, "model": _text(payload.get("model")),
                                   "effort": _text(payload.get("reasoning_effort")), "parent": ""}
                source = payload.get("source")
                sub = source.get("subagent") if isinstance(source, dict) else None
                spawn = sub.get("thread_spawn") if isinstance(sub, dict) else None
                if isinstance(spawn, dict):
                    parent = _text(spawn.get("parent_thread_id"))
                    if parent:
                        threads[thread]["parent"] = parent; parents[thread] = parent
        elif typ == "turn_context":
            thread = _text(payload.get("thread_id")) or owner_thread; turn = _text(payload.get("turn_id"))
            if thread or turn:
                contexts[(thread, turn)] = {"model": _text(payload.get("model")),
                                             "effort": _text(payload.get("reasoning_effort", payload.get("effort"))),
                                             "root": _text(payload.get("root_turn_id"))}
    return threads, contexts, parents


def rollout_identity(records, turn_id=""):
    """Read only stable identity/configuration metadata from one rollout."""
    threads, contexts, _ = _metadata(records)
    session = next((meta.get("session", "") for meta in threads.values() if meta.get("session")), "")
    model = effort = ""
    if turn_id:
        for (thread, turn), context in contexts.items():
            if turn == turn_id:
                model, effort = context.get("model", ""), context.get("effort", "")
                if model or effort: break
    # Without a selected Stop turn, use the latest root context in this
    # rollout, never a fork/child context copied into another history.
    if not model or not effort:
        for (thread, turn), context in reversed(list(contexts.items())):
            if context.get("root"):
                continue
            model = model or context.get("model", "")
            effort = effort or context.get("effort", "")
            if model and effort: break
    if not model or not effort:
        for meta in threads.values():
            model = model or meta.get("model", "")
            effort = effort or meta.get("effort", "")
    return {"session_id": session, "model": model, "effort": effort}


def _legacy_delta(now, before):
    values = []
    for current, old in zip(now, before):
        if current is None: values.append(None)
        elif old is None: values.append(current)
        elif current >= old: values.append(current - old)
        else: values.append(None) # reset: establish baseline, do not invent spend
    return TokenUsage(*values)


def _message_text(content):
    """Extract a bounded, terminal-safe message summary for an in-memory row."""
    if isinstance(content, str):
        values = [content]
    elif not isinstance(content, list):
        return ""
    else:
        values = []
        for item in content:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str): values.append(value)
    value = "".join(c for c in " ".join(values)
                    if ord(c) >= 32 and not 127 <= ord(c) <= 159)
    return value[:512]


def _turn_details(records, fallback_session=""):
    """Best-effort lifecycle/message data; absent metadata remains absent."""
    threads, contexts, _ = _metadata(records, fallback_session)
    details = {}
    thread = ""; turn = ""
    for record in records:
        typ = _text(_get(record, "type", "record_type", "kind"))
        payload = _payload(record)
        if typ == "session_meta":
            thread = _text(payload.get("id")) or thread
        elif typ == "turn_context":
            thread = _text(payload.get("thread_id")) or thread
            turn = _text(payload.get("turn_id")) or turn
        event_type = _text(payload.get("type")) if typ == "event_msg" else ""
        event_turn = _text(payload.get("turn_id")) or turn
        if event_type in ("task_started", "task_complete"):
            turn = event_turn or turn
        key = (thread, event_turn or turn)
        if not key[1]: continue
        detail = details.setdefault(key, {"started_at": None, "completed_at": None,
                                         "user_message": "", "assistant_message": "", "completed": False})
        stamp = _stamp(_get(record, "timestamp", "created_at", "createdAt"))
        if event_type == "task_started":
            # A resumed task can reuse a turn ID.  Its new lifecycle is open
            # until another completion record arrives.
            detail["started_at"] = stamp; detail["completed"] = False; detail["completed_at"] = None
        elif event_type == "task_complete":
            detail["completed"] = True; detail["completed_at"] = stamp
        elif typ == "response_item" and payload.get("type") == "message":
            message = _message_text(payload.get("content"))
            if payload.get("role") == "user" and message: detail["user_message"] = message
            elif payload.get("role") == "assistant" and message: detail["assistant_message"] = message
    return details


def requests_from_records(records, session_id="", diagnostics=None):
    """Build request rows while retaining session/thread identity and ancestry.

    Per-response records win only for their matching turn.  Legacy counter
    deltas on unrelated older turns remain useful during a mixed-format rollout.
    """
    threads, contexts, parents = _metadata(records, session_id)
    details = _turn_details(records, session_id)
    response_rows, response_turns, legacy = [], set(), []
    seen_response = set()
    active_thread = ""; active_turn = ""; active_root = ""; active_session = session_id
    for ordinal, record in enumerate(records):
        typ = _text(_get(record, "type", "record_type", "kind"))
        payload = _payload(record)
        if typ == "session_meta":
            active_thread = _text(payload.get("id")) or active_thread
            active_session = _text(payload.get("session_id")) or active_session
        elif typ == "turn_context":
            active_thread = _text(payload.get("thread_id")) or active_thread
            context_turn = _text(payload.get("turn_id"))
            if context_turn:
                # A new context with no root is a root (or unassociated)
                # turn, not a continuation of the preceding child's root.
                active_turn = context_turn
                active_root = _text(payload.get("root_turn_id"))
            elif _text(payload.get("root_turn_id")):
                active_root = _text(payload.get("root_turn_id"))
        elif typ == "event_msg" and payload.get("type") in ("task_started", "task_complete"):
            active_turn = _text(payload.get("turn_id")) or active_turn
        outer_time = _stamp(_get(record, "timestamp", "created_at", "createdAt"))
        thread = _text(payload.get("thread_id")) or active_thread
        meta = threads.get(thread, {})
        sid = _text(payload.get("session_id")) or meta.get("session", "") or active_session or session_id
        turn = _text(payload.get("turn_id")) or active_turn; root = _text(payload.get("root_turn_id")) or active_root
        context = contexts.get((thread, turn), {}) or contexts.get(("", turn), {})
        root = root or context.get("root", "")
        model = _text(payload.get("model")) or context.get("model", "") or meta.get("model", "")
        effort = _text(payload.get("reasoning_effort", payload.get("effort"))) or context.get("effort", "") or meta.get("effort", "")
        parent = _text(payload.get("parent_thread_id")) or meta.get("parent", "")
        detail = details.get((thread, turn), {})
        usage = payload.get("usage")
        rid = _text(_get(payload, "response_id", "responseId", "request_id", "requestId"))
        if typ == "token_usage_record" and isinstance(usage, dict):
            normalized = token_usage(usage)
            # Forks can copy a request prefix. A response ID has global
            # identity; if absent use enough real identities to stay stable.
            key = rid or "anon:%s:%s:%s" % (thread or sid, turn, ordinal)
            if key in seen_response or not _nonempty(normalized): continue
            seen_response.add(key); response_turns.add((thread or sid, turn or root))
            response_rows.append(UsageRequest(key, sid, turn, root, parent, outer_time,
                                 model, effort, normalized, None, thread, bool(parent),
                                 detail.get("started_at"), detail.get("completed_at"),
                                 detail.get("user_message", ""), detail.get("assistant_message", ""),
                                 detail.get("completed", False)))
            continue
        if typ == "event_msg" and payload.get("type") == "token_count":
            legacy.append((thread, sid, turn, root, parent, model, effort, outer_time, payload))
        elif "token_count" in typ:
            legacy.append((thread, sid, turn, root, parent, model, effort, outer_time, payload))
    # Cumulative legacy snapshots need a first complete baseline. Suppress only
    # the same turn that has current per-response rows, not every legacy row.
    prior = {}; legacy_rows = []
    for thread, sid, turn, root, parent, model, effort, stamp, payload in legacy:
        info = payload.get("info") if isinstance(payload.get("info"), dict) else payload
        total = _get(info, "total_token_usage", "totalTokenUsage", "token_count", "tokenCount")
        now = token_usage(total if isinstance(total, dict) else info)
        key = (thread or sid, turn or root)
        # Legacy counters are cumulative at the thread/session scope, not a
        # fresh baseline for every turn.  Keeping this scope lets a resumed
        # or upgraded recording contribute its later delta.
        counter_key = thread or sid
        before = prior.get(counter_key); prior[counter_key] = now
        mixed = key in response_turns
        if before is None:
            # Current legacy snapshots carry the just-completed request. This
            # is the only safe way to count the first complete history row.
            last = token_usage(info.get("last_token_usage")) if isinstance(info, dict) else TokenUsage()
            delta = last
        else:
            delta = _legacy_delta(now, before)
        if mixed:
            # Token counts are not request identity.  A legacy `last` can
            # differ merely because it exposes a cached/reasoning subset, and
            # distinct requests can have identical counts.  Per-response rows
            # therefore win for this same-turn overlap; retain an explicit
            # diagnostic rather than inventing a complete mixed-format total.
            if isinstance(diagnostics, dict):
                diagnostics["ambiguous_legacy_records"] = diagnostics.get("ambiguous_legacy_records", 0) + 1
            continue
        if _nonempty(delta):
            detail = details.get((thread, turn), {})
            legacy_rows.append(UsageRequest("legacy:%s:%d" % (key[0], len(legacy_rows)), sid,
                               turn, root, parent, stamp, model, effort, delta, None,
                               thread, bool(parent), detail.get("started_at"),
                               detail.get("completed_at"), detail.get("user_message", ""),
                               detail.get("assistant_message", ""), detail.get("completed", False)))
    return response_rows + legacy_rows


def read_requests(path, session_id=""):
    return requests_from_records(parse_jsonl(path), session_id)


def totals(rows):
    values, present, complete = [0, 0, 0, 0], [False, False, False, False], [True, True, True, True]
    for row in rows:
        for index, value in enumerate(row.usage):
            if value is not None:
                values[index] += value; present[index] = True
            else:
                complete[index] = False
    # A partial sum is useful only if it is labelled partial.  TokenUsage has
    # no estimated state, so retain unknown rather than presenting a known
    # subset as the turn/session total.
    return TokenUsage(*[values[i] if present[i] and complete[i] else None for i in range(4)])


def origin_turn(row):
    """The root turn which owns a request, without guessing a child root."""
    if row.root_turn_id: return row.root_turn_id
    return "" if row.child else row.turn_id


def grouped_turns(rows):
    """Group a report into root-inclusive and separately inspectable child turns."""
    groups = {}
    for row in rows:
        root = origin_turn(row) or ("unattributed-child:" + (row.thread_id or row.turn_id or "unknown"))
        entry = groups.setdefault(root, {"root": [], "children": {}})
        if row.child:
            entry["children"].setdefault((row.thread_id, row.turn_id), []).append(row)
        else:
            entry["root"].append(row)
    return groups


def sqlite_child_edges(thread_id, db_path=None):
    """Best-effort read-only state_5 lookup; schema drift simply returns []."""
    if not thread_id: return []
    if not db_path:
        home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
        db_path = os.path.join(home, "state_5.sqlite")
    if not os.path.isfile(db_path): return []
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            result = connection.execute("SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=?", (thread_id,)).fetchall()
            return [_text(row[0]) for row in result if _text(row[0])]
        finally: connection.close()
    except (sqlite3.Error, OSError): return []


def _sqlite_thread_path(thread_id, db_path):
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            row = connection.execute("SELECT rollout_path FROM threads WHERE id=?", (thread_id,)).fetchone()
            return _text(row[0], 4096) if row else ""
        finally: connection.close()
    except (sqlite3.Error, OSError): return ""


def _sqlite_subagent_paths(db_path, diagnostics=None):
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            rows = connection.execute("SELECT id, rollout_path FROM threads WHERE source='subagent'").fetchall()
            return [(_text(row[0]), _text(row[1], 4096)) for row in rows]
        finally: connection.close()
    except (sqlite3.Error, OSError):
        if isinstance(diagnostics, dict): diagnostics["child_coverage"] = "incomplete-schema"
        return []


def _rollout_parent_thread(path):
    """Read only early session metadata while locating fallback descendants."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for ordinal, line in enumerate(fh):
                if ordinal >= 64: break
                if not line.endswith("\n"): break
                try: record = json.loads(line)
                except (TypeError, ValueError): continue
                if _text(_get(record, "type", "record_type", "kind")) != "session_meta": continue
                payload = _payload(record)
                source = payload.get("source") if isinstance(payload, dict) else None
                sub = source.get("subagent") if isinstance(source, dict) else None
                spawn = sub.get("thread_spawn") if isinstance(sub, dict) else None
                return _text(spawn.get("parent_thread_id")) if isinstance(spawn, dict) else ""
    except (OSError, UnicodeError):
        return ""
    return ""


def _sqlite_index_available(db_path):
    """Whether the versioned index exposes the tables needed for coverage."""
    if not os.path.isfile(db_path): return False
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            connection.execute("SELECT 1 FROM threads LIMIT 1")
            connection.execute("SELECT 1 FROM thread_spawn_edges LIMIT 1")
            return True
        finally: connection.close()
    except (sqlite3.Error, OSError): return False


def _thread_id(records):
    for record in records:
        if _text(_get(record, "type", "record_type", "kind")) == "session_meta":
            value = _text(_payload(record).get("id"))
            if value: return value
    return ""


def read_request_tree(path, session_id="", db_path=None, diagnostics=None):
    """Read a root rollout and explicit sqlite-linked descendants once each."""
    root_records = parse_jsonl(path)
    root_thread = _thread_id(root_records)
    if not db_path:
        home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
        db_path = os.path.join(home, "state_5.sqlite")
    indexed = _sqlite_index_available(db_path)
    if isinstance(diagnostics, dict):
        diagnostics["child_coverage"] = "indexed" if indexed else "incomplete-no-index"
        diagnostics["child_threads"] = 0
        diagnostics["ambiguous_legacy_records"] = 0
    queue = [(root_thread, path, False)]
    visited, rows, seen_requests = set(), [], set()
    fallback_children = None
    while queue:
        thread, rollout, child = queue.pop(0)
        marker = thread or os.path.realpath(rollout)
        if marker in visited: continue
        visited.add(marker)
        records = root_records if os.path.realpath(rollout) == os.path.realpath(path) else parse_jsonl(rollout)
        for row in requests_from_records(records, session_id, diagnostics):
            # A copied ancestor response carries its original thread ID. It is
            # ignored by global request identity, not charged to the child.
            if row.request_id in seen_requests: continue
            seen_requests.add(row.request_id)
            rows.append(row._replace(child=child or row.child))
        current = thread or _thread_id(records)
        descendants = sqlite_child_edges(current, db_path)
        # Some state_5 versions leave spawn edges empty.  Source metadata is
        # still explicit ancestry, so scan only indexed subagent rollouts (not
        # the history directory) for a matching parent thread.
        if not descendants:
            if fallback_children is None:
                fallback_children = {}
                for candidate, candidate_path in _sqlite_subagent_paths(db_path, diagnostics):
                    if not candidate_path or not os.path.isfile(candidate_path):
                        if isinstance(diagnostics, dict): diagnostics["child_coverage"] = "incomplete-missing-rollout"
                        continue
                    parent = _rollout_parent_thread(candidate_path)
                    if parent: fallback_children.setdefault(parent, []).append(candidate)
            descendants.extend(fallback_children.get(current, []))
        for descendant in descendants:
            child_path = _sqlite_thread_path(descendant, db_path)
            if child_path and os.path.isfile(child_path):
                queue.append((descendant, child_path, True))
            elif isinstance(diagnostics, dict):
                diagnostics["child_coverage"] = "incomplete-missing-rollout"
    if isinstance(diagnostics, dict):
        diagnostics["child_threads"] = max(0, len(visited) - 1)
    return rows


def root_context(records):
    """Latest root thread context (never inherited from a child)."""
    latest = TokenUsage(); capacity = None; occupancy = None
    for record in records:
        payload = _payload(record)
        if (_text(_get(record, "type", "record_type", "kind")) == "event_msg"
                and payload.get("type") == "token_count"):
            info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
            usage = token_usage(info.get("last_token_usage"))
            if _nonempty(usage): latest = usage
            raw = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else {}
            observed_occupancy = _number(raw.get("total_tokens"))
            observed_capacity = _number(info.get("model_context_window"))
            if observed_occupancy is not None: occupancy = observed_occupancy
            if observed_capacity is not None: capacity = observed_capacity
    if occupancy is None and latest.input_total is not None and latest.output_total is not None:
        occupancy = latest.input_total + latest.output_total
    return latest, capacity, occupancy


def native_quota(records):
    """Latest rollout quota snapshot for source orchestration, if present."""
    latest = {}; observed = None
    for record in records:
        payload = _payload(record)
        if _text(_get(record, "type", "record_type", "kind")) == "event_msg":
            rate = payload.get("rate_limits") or payload.get("rateLimits")
            if isinstance(rate, dict):
                latest = rate; observed = _stamp(_get(record, "timestamp", "created_at", "createdAt"))
    return {"rate_limits": latest, "as_of": observed} if latest else {}
