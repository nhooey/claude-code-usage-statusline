"""The agent panel's inbox counts, read on from a saved fold, so a panel
tick reads only what each file had appended since the last.

claude_records.inbox_counts reads every file that can send whole on every
tick: on a session with a 165 MB main transcript, 350 ms of a 380 ms tick.
This keeps, for each file, its sends and its deliveries folded to an
offset, and counts from those as inbox_counts counts from the whole files.

mod/src/inbox_fold.ts is the port, and the Node port's inboxFoldCounts
writes the same bytes for the same files.  spec/state.jsonc's "inbox-fold"
row names the directory and the format;
agents/plans/_implemented/saved-running-totals.md has the design.

The fold is the whole session's, one JSON object, written to one of two
slots in turn, each with a sequence number, as the agent folds are:

    {"format":N,"seq":S,"files":[[PATH,POS,MTIME,TAIL,SENDS,GOT],...]}

one entry per file, sorted by path: the offset its whole lines are folded
to, its mtime in nanoseconds (a string, since JavaScript's numbers cannot
hold it) when it was folded, the sha256 of the FOLD_CHECK_BYTES before the
offset, its sends as [epoch, agent id] and its deliveries as epochs, each
in file order (none for the session's own transcript: see fold_entry).  An
entry at the file's size with the file's mtime is taken
as it stands; any other is read on from only where its check digest still
matches, and else folded afresh.  A last line with no newline yet is
counted and not saved.  tests/fixtures/inbox-state/ holds each fixture
file's entry at each line end, which both ports must write byte for byte.
"""
import hashlib
import json
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

from . import claude_records as cr
from . import state
from .main_fold import js_dumps
from .state_spec import STATE_KINDS

_ROW = STATE_KINDS["inbox-fold"]
INBOX_FOLD_FORMAT = _ROW["format"]
# The bytes before an entry's offset that its check digest is taken over.
FOLD_CHECK_BYTES = _ROW["check_bytes"]
# The two slots the fold is written to in turn, in its directory.
SLOTS = ("inbox-a.cache", "inbox-b.cache")
_SEQ = re.compile(r'\{"format":(\d+),"seq":(\d+),')


class Entry:
    """One file's fold: see the module's docstring."""

    __slots__ = ("pos", "mtime", "tail", "sends", "got")

    def __init__(self):
        self.pos = 0
        self.mtime = ""
        self.tail = tail_digest(b"")
        self.sends: List[Tuple[float, str]] = []
        self.got: List[float] = []


def fold_dir(transcript: str) -> str:
    """The directory a session's inbox fold is saved in."""
    return state.state_path("inbox-fold", transcript)


def tail_digest(data: bytes) -> str:
    """The check digest of an entry at an offset: the sha256 of `data`, the
    FOLD_CHECK_BYTES of the file before it, or all of them where the offset
    is closer to the start."""
    return hashlib.sha256(data).hexdigest()


def fold_entry(e: Entry, data: bytes, main: bool = False) -> None:
    """Fold `data`, the whole lines of a file from `e.pos` on, into `e`.
    `main` for the session's own transcript, whose deliveries are not
    folded: it is no agent's file, so nothing counts them, and the search
    for them is most of a cold read (half a second of a 165 MB transcript,
    whose words "peer" and "coordinator" are common)."""
    e.sends.extend(cr.inbox_sends_of(data))
    if not main:
        e.got.extend(cr.inbox_deliveries_of(data))
    e.pos += len(data)


def entry_text(path: str, e: Entry) -> str:
    """`e`, the fold of file `path`, as the fold's text writes it."""
    return js_dumps([path, e.pos, e.mtime, e.tail,
                     [[t, aid] for t, aid in e.sends], e.got])


def fold_text(entries: Dict[str, Entry], seq: int) -> str:
    """The session's fold as the text a save writes, with its sequence
    number: compact, numbers as JavaScript writes them, the files sorted by
    path.  The mod's inboxFoldText writes the same bytes."""
    return ('{"format":%d,"seq":%d,"files":[' % (INBOX_FOLD_FORMAT, seq)
            + ",".join(entry_text(p, entries[p]) for p in sorted(entries))
            + "]}")


def fold_of_text(text: Optional[str]):
    """A fold's text read back, as (seq, {path: Entry}), or None for text
    that will not parse, is of another format, or is not a fold."""
    if not text:
        return None
    try:
        o = json.loads(text)
        if (not isinstance(o, dict) or o.get("format") != INBOX_FOLD_FORMAT
                or not isinstance(o.get("seq"), int)):
            return None
        entries = {}
        for path, pos, mtime, tail, sends, got in o["files"]:
            if not isinstance(pos, int) or not isinstance(path, str):
                return None
            e = Entry()
            e.pos, e.mtime, e.tail = pos, str(mtime), str(tail)
            e.sends = [(float(t), str(aid)) for t, aid in sends]
            e.got = [float(t) for t in got]
            entries[path] = e
    except (ValueError, TypeError, KeyError):
        return None
    return o["seq"], entries


def _seq_of(text: Optional[str]) -> int:
    """The sequence number a slot's text starts with, without parsing the
    rest; -1 for none."""
    m = _SEQ.match(text or "")
    return int(m.group(2)) if m else -1


def load(texts: Sequence[Optional[str]]) -> Tuple[Dict[str, Entry], int]:
    """The fold the newest of the slots' `texts` that reads back holds, and
    its sequence number; for none, no entries and the highest sequence
    number either slot starts with, so the next save goes to the slot after
    that one."""
    for text in sorted(texts, key=lambda t: -_seq_of(t)):
        got = fold_of_text(text)
        if got is not None:
            return got[1], got[0]
    return {}, max([0] + [_seq_of(t) for t in texts])


def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, ValueError):
        return None


def _write(path: str, text: str) -> None:
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _tail_at(fh, pos: int) -> str:
    lo = max(0, pos - FOLD_CHECK_BYTES)
    fh.seek(lo)
    return tail_digest(fh.read(pos - lo))


def read_on(entries: Dict[str, Entry], path: str, main: bool = False):
    """File `path`'s entry in `entries`, read on to the file's end, and
    what its last line, with no newline yet, holds: (entry, sends,
    deliveries), with the entry replaced in `entries` where it moved; None
    for a file that will not open, whose entry is dropped.  Also whether
    `entries` changed.  `main` as fold_entry takes it."""
    try:
        fh = open(path, "rb")
    except OSError:
        return None, entries.pop(path, None) is not None
    with fh:
        st = os.fstat(fh.fileno())
        size, mtime = st.st_size, str(st.st_mtime_ns)
        e = entries.get(path)
        if e is not None and e.pos == size and e.mtime == mtime:
            return (e, [], []), False
        if e is None or e.pos > size or _tail_at(fh, e.pos) != e.tail:
            e = Entry()
        fh.seek(e.pos)
        data = fh.read(size - e.pos)
        whole = data.rfind(b"\n") + 1
        fold_entry(e, data[:whole], main)
        e.tail, e.mtime = _tail_at(fh, e.pos), mtime
    entries[path] = e
    rest = data[whole:]
    if not rest:
        return (e, [], []), True
    return (e, cr.inbox_sends_of(rest),
            [] if main else cr.inbox_deliveries_of(rest)), True


def counts(transcript: str, files: Sequence[str], targets: Dict[str, str],
           since: Optional[float] = None, d: str = "") -> Dict[str, int]:
    """claude_records.inbox_counts, read on from the fold saved for
    `transcript`'s session, and saved back where anything moved.  `d` is
    fold_dir(transcript)."""
    d = d or fold_dir(transcript)
    entries, seq = load([_read(os.path.join(d, n)) for n in SLOTS])
    changed = False
    seen: Dict[str, object] = {}

    def at(path):
        nonlocal changed
        if path not in seen:
            seen[path], moved = read_on(entries, path, path == transcript)
            changed = changed or moved
        return seen[path]

    sent: Dict[str, List[float]] = {}
    for f in files:
        try:
            if since is not None and os.path.getmtime(f) < since:
                continue
        except OSError:
            continue
        got = at(f)
        if got is None:
            continue
        e, rest, _ = got
        for t, target in e.sends + rest:
            if target in targets:
                sent.setdefault(target, []).append(t)

    def delivered(aid):
        if targets[aid] == transcript:
            # Its deliveries are not folded (fold_entry): read whole.  The
            # panel never names the transcript as an agent's file.
            return cr.inbox_deliveries(transcript)
        got = at(targets[aid])
        return [] if got is None else got[0].got + got[2]

    out = cr.inbox_tally(sent, delivered)
    if changed:
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
            _write(os.path.join(d, SLOTS[(seq + 1) % 2]),
                   fold_text(entries, seq + 1))
        except OSError:
            pass
    return out
