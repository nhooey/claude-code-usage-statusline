"""Each agent transcript's fold saved as text, so a read goes on from where
the last one stopped.

mod/src/agent_fold.ts is the port, and the two write the same bytes for the
same fold.  spec/state.jsonc's "agent-fold" row names the files and the
format; agents/plans/_implemented/saved-running-totals.md has the design.

A fold is claude_records.AgentFold, saved whole as one JSON object to one
of two slots in turn, each with a sequence number, since the mod's
$.fs.write truncates and then writes, and a reader can see the file torn.
A reader takes the newer slot that parses and still fits the file, and
else the other.  Numbers are written as JavaScript writes them
(main_fold.js_dumps); reading back, each float field is made a float again,
and each tuple a tuple, so the fold reads on as it was.
tests/fixtures/agent-state/ holds the text of each fixture agent's fold at
each line end, which both ports must write byte for byte.
"""
import hashlib
import json
import os
import re
from typing import Callable, List, Optional, Tuple

from . import claude_records as cr
from . import state
from .main_fold import js_dumps
from .state_spec import STATE_KINDS

_ROW = STATE_KINDS["agent-fold"]
AGENT_FOLD_FORMAT = _ROW["format"]
# The bytes before a fold's offset that its check digest is taken over.
FOLD_CHECK_BYTES = _ROW["check_bytes"]
# The two slots a fold is written to in turn, after its path's digest.
SLOTS = ("-a.cache", "-b.cache")
_SEQ = re.compile(r'\{"format":(\d+),"seq":(\d+),')


def fold_dir(transcript: str) -> str:
    """The directory a session's agent folds are saved in."""
    return state.state_path("agent-fold", transcript)


def slot_names(path: str) -> Tuple[str, str]:
    """The two files agent file `path`'s fold is saved to in turn."""
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
    return digest + SLOTS[0], digest + SLOTS[1]


def tail_digest(data: bytes) -> str:
    """The check digest of a fold at an offset: the sha256 of `data`, the
    FOLD_CHECK_BYTES of the file before it, or all of them where the offset
    is closer to the start."""
    return hashlib.sha256(data).hexdigest()


def _fl(x):
    return None if x is None else float(x)


def fold_text(f: cr.AgentFold, seq: int, tail: str) -> str:
    """`f` as the text a save writes, with its sequence number and check
    digest: compact, in this key order, numbers as JavaScript writes them.
    The mod's agentFoldText writes the same bytes."""
    e = f.eta_state
    return js_dumps({
        "format": AGENT_FOLD_FORMAT, "seq": seq, "pos": f.pos, "tail": tail,
        "pid": f.pid, "eta": [e[0], e[1], e[2], e[3]],
        "span": f.span_state, "work": f.work,
        "pending": [[k, t, name] for k, (t, name) in f.pending.items()],
        "tools": f.tools, "waiting": f.waiting, "recs": f.recs,
        "wrote": list(f.wrote), "added": f.added, "removed": f.removed,
        "compactions": f.compactions, "last_seen": f.last_seen,
        "api_error": f.api_error, "cwd": f.cwd, "blocks": f.blocks,
        "background": [[k, v] for k, v in f.background.items()],
        "effort": f.effort})


def fold_of_text(text: Optional[str]):
    """A fold's text read back, as (seq, tail, fold), or None for text that
    will not parse, is of another format, or is not a fold."""
    if not text:
        return None
    try:
        o = json.loads(text)
        if (not isinstance(o, dict) or o.get("format") != AGENT_FOLD_FORMAT
                or not isinstance(o.get("seq"), int)
                or not isinstance(o.get("pos"), int)):
            return None
        f = cr.AgentFold()
        f.pos = o["pos"]
        f.pid = o["pid"]
        e = o["eta"]
        f.eta_state = [tuple(float(x) for x in e[0]), bool(e[1]), _fl(e[2]),
                       e[3]]
        f.span_state = [_fl(o["span"][0]), _fl(o["span"][1])]
        f.work = [(float(a), float(b)) for a, b in o["work"]]
        f.pending = {k: (float(t), name) for k, t, name in o["pending"]}
        f.tools = [(float(a), float(b)) for a, b in o["tools"]]
        f.waiting = [(float(a), float(b)) for a, b in o["waiting"]]
        f.recs = [(_fl(r[0]),) + tuple(r[1:]) for r in o["recs"]]
        for k in o["wrote"]:
            f.wrote.add(k)
        f.added, f.removed = o["added"], o["removed"]
        f.compactions = o["compactions"]
        f.last_seen = _fl(o["last_seen"])
        f.api_error = bool(o["api_error"])
        f.cwd, f.blocks = o["cwd"], o["blocks"]
        f.background = {k: v for k, v in o["background"]}
        f.effort = o["effort"]
        f.keys = {r[7] for r in f.recs}
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    return o["seq"], o["tail"], f


def _seq_of(text: Optional[str]) -> int:
    """The sequence number a slot's text starts with, without parsing the
    rest; -1 for none."""
    m = _SEQ.match(text or "")
    return int(m.group(2)) if m else -1


def load(texts: List[Optional[str]], fits: Callable[[int, str], bool]):
    """The fold the newest of the slots' `texts` holds that `fits` takes
    the offset and check digest of, and its sequence number; for none, a
    new fold and the highest sequence number either slot starts with, so
    the next save goes to the slot after that one."""
    for text in sorted(texts, key=lambda t: -_seq_of(t)):
        got = fold_of_text(text)
        if got is not None and fits(got[2].pos, got[1]):
            return got[2], got[0]
    return cr.AgentFold(), max([0] + [_seq_of(t) for t in texts])


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


def fold_file(transcript: str, path: str, d: str = ""
              ) -> Optional[cr.AgentFold]:
    """Agent file `path`'s fold, read on from the one saved for it under
    `transcript`'s session to the file's end, and saved back where it
    folded anything.  A saved fold is read only where the file still holds
    the bytes it was folded from: its offset within the file, and the
    digest of the bytes before it the same, so a file rewritten to the same
    size reads afresh.
    With neither slot, the fold starts over from the file's start.  A last line with no newline
    yet is folded on a copy, which is returned and not saved.  None for a
    file that will not open.  `d` is fold_dir(transcript), for a caller
    reading many."""
    d = d or fold_dir(transcript)
    names = slot_names(path)
    try:
        fh = open(path, "rb")
    except OSError:
        return None
    with fh:
        size = os.fstat(fh.fileno()).st_size
        got = load([_read(os.path.join(d, n)) for n in names],
                   lambda pos, tail: pos <= size
                   and _tail_at(fh, pos) == tail)
        fold, seq = got
        start = fold.pos
        fh.seek(start)
        data = fh.read(size - start)
        whole = data.rfind(b"\n") + 1
        cr.fold_agent_bytes(fold, data[:whole])
        tail = _tail_at(fh, fold.pos) if fold.pos > start else ""
    if fold.pos > start:
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
            _write(os.path.join(d, names[(seq + 1) % 2]),
                   fold_text(fold, seq + 1, tail))
        except OSError:
            pass
    return cr.fold_with(fold, data[whole:])
