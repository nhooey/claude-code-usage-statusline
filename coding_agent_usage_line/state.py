"""Private, scoped on-disk state.

The cache deliberately stores normalized readings only. Its file name is a
hash, while the clear-text identity inside the file is used only to reject a
hash collision or corrupt entry; neither location contains provider payloads.
"""
import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager


def state_dir():
    path = os.environ.get("CODING_AGENT_USAGE_LINE_STATE_DIR")
    if not path:
        base = os.environ.get("XDG_STATE_HOME")
        if not base:
            base = os.path.join(os.path.expanduser("~"), ".local", "state")
        path = os.path.join(base, "coding-agent-usage-line")
    try: os.makedirs(path, mode=0o700, exist_ok=True)
    except OSError: pass
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _identity(agent, source, account, period_start):
    return tuple(str(x or "") for x in (agent, source, account, period_start))


def cache_name(agent, source, account, period_start):
    raw = "\0".join(_identity(agent, source, account, period_start))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() + ".json"


def _path(agent, source, account, period_start):
    return os.path.join(state_dir(), cache_name(agent, source, account, period_start))



def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def load(agent, source, account, period_start):
    try: value = _read(_path(agent, source, account, period_start))
    except OSError: return {}
    expected = _identity(agent, source, account, period_start)
    actual = _identity(value.get("agent"), value.get("source"),
                       value.get("account_name"), value.get("period_start"))
    return value if actual == expected else {}


def find_compatible(agent, account, period_start, sources=None):
    """Return a compatible cache, never one from another source/account."""
    newest = {}
    try:
        names = os.listdir(state_dir())
    except OSError:
        return newest
    allowed = set(sources) if sources else None
    for name in names:
        if not name.endswith(".json") or name.startswith("reported-"):
            continue
        value = _read(os.path.join(state_dir(), name))
        if (value.get("agent") != agent or value.get("account_name") != account
                or str(value.get("period_start")) != str(period_start)):
            continue
        if allowed is not None and value.get("source") not in allowed:
            continue
        try:
            newer = float(value.get("as_of")) > float(newest.get("as_of", -1))
        except (TypeError, ValueError):
            newer = not newest
        if newer:
            newest = value
    return newest


def _atomic_json(path, value):
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, sort_keys=True, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def save(agent, source, account, period_start, value):
    if not isinstance(value, dict):
        return
    stored = dict(value)
    stored.update({"agent": str(agent), "source": str(source),
                   "account_name": str(account), "period_start": str(period_start)})
    try: _atomic_json(_path(agent, source, account, period_start), stored)
    except OSError: pass


@contextmanager
def refresh_lock(agent, source, account, period_start):
    """A nonblocking per-reading lock; false means another process refreshes."""
    try: path = _path(agent, source, account, period_start) + ".lock"
    except OSError:
        yield False; return
    fh = None
    try:
        fh = open(path, "a+")
        os.chmod(path, 0o600)
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if fh:
            fh.close()
        yield False
        return
    try:
        yield True
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
            fh.close()
        except OSError:
            pass


def unreported_requests(session_id, turn_id, request_ids, consume=True):
    """Return request IDs not emitted for an authoritative session/turn."""
    unique = list(dict.fromkeys(x for x in request_ids if x))
    if not session_id or not turn_id:
        return unique
    digest = hashlib.sha256((str(session_id) + "\0" + str(turn_id)).encode()).hexdigest()
    path = os.path.join(state_dir(), "reported-" + digest + ".json")
    lock_path = path + ".lock"
    try:
        lock = open(lock_path, "a+")
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
    except OSError:
        return []
    try:
        seen = set(x for x in _read(path).get("request_ids", []) if isinstance(x, str))
        fresh = [x for x in unique if x not in seen]
        if consume and fresh:
            _atomic_json(path, {"request_ids": sorted(seen | set(fresh))})
        return fresh
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        except OSError:
            pass


def _report_path(session_id):
    """The report journal is scoped to a real Codex session, not a Stop."""
    digest = hashlib.sha256(("codex-report\0" + str(session_id)).encode("utf-8")).hexdigest()
    return os.path.join(state_dir(), "reported-session-" + digest + ".json")


def claim_reportable_requests(session_id, current_turn, request_origins, consume=True):
    """Atomically claim requests visible to one Codex Stop.

    ``request_origins`` contains ``(request_id, root_turn_id)`` pairs.  The
    current root turn is reportable, as are newly appended requests for roots
    that have already been reported.  The latter is what makes a late child
    charged to an older root visible without re-emitting either root's old
    requests.  No prompt or response text is persisted.

    Older releases wrote one journal per session/turn.  We only consult those
    exact, derivable legacy paths for origins in this call, which keeps the
    migration scoped and avoids treating an arbitrary state-file ID as proof
    for another session.
    """
    items = []
    for request_id, origin in request_origins:
        request_id, origin = str(request_id or ""), str(origin or "")
        if request_id and origin:
            items.append((request_id, origin))
    # Preserve transcript order while accepting copied records defensively.
    items = list(dict.fromkeys(items))
    if not session_id or not current_turn:
        return [request_id for request_id, origin in items if origin == current_turn]
    path = _report_path(session_id)
    try:
        lock = open(path + ".lock", "a+")
        os.chmod(path + ".lock", 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
    except OSError:
        return []
    try:
        state = _read(path)
        seen = set(x for x in state.get("request_ids", []) if isinstance(x, str))
        reported_turns = set(x for x in state.get("turn_ids", []) if isinstance(x, str))
        # A safe, one-way migration of exact legacy turn journals.
        for origin in set(origin for _, origin in items):
            legacy_digest = hashlib.sha256((str(session_id) + "\0" + origin).encode()).hexdigest()
            legacy = _read(os.path.join(state_dir(), "reported-" + legacy_digest + ".json"))
            legacy_ids = set(x for x in legacy.get("request_ids", []) if isinstance(x, str))
            if legacy_ids:
                seen.update(legacy_ids)
                reported_turns.add(origin)
        allowed = reported_turns | {str(current_turn)}
        fresh = [request_id for request_id, origin in items
                 if (origin in allowed or origin.startswith("child:")) and request_id not in seen]
        if consume:
            seen.update(fresh)
            # Mark the current root even when its Stop raced the response;
            # this is necessary for a later child append to become a late row.
            reported_turns.add(str(current_turn))
            _atomic_json(path, {"request_ids": sorted(seen),
                                "turn_ids": sorted(reported_turns)})
        return fresh
    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        except OSError:
            pass
