"""The main transcript's two folds saved as text, so a read goes on from
where the last one stopped.

mod/src/main_fold.ts is the port, and the two write the same bytes for the
same fold.  spec/state.jsonc's "main-fold" row names the files and the
format; agents/plans/saved-running-totals.md has the design.

What never changes once folded is a log, one JSON array a line, tagged with
what it adds to, in parts of at most part_bytes of UTF-8: a part only grows,
and every part but the last is never written again.  The rest is a head,
written after the parts, which names the parts, how many entries each
holds, the byte offset folded to and the transcript's check digests.  Until
a head is written the one before it reads true, since its counts take a
prefix of each part.  Heads go to two slots in turn, each with a sequence
number, since the mod's $.fs.write truncates and then writes, and a reader
can see the file torn.

Numbers are written as JavaScript writes them (js_dumps), since the
TypeScript cannot tell 1.0 from 1; reading back, each float field is made a
float again, and each tuple a tuple, so the fold reads on as it was.

    python3 -m coding_agent_usage_line.main_fold save TRANSCRIPT DIR \\
        [--from DIR] [--upto OFFSET]

folds TRANSCRIPT's whole lines, from the state saved in --from or from its
start, up to OFFSET or its last newline, and writes the whole fold's state
into DIR, as a first save writes it.  The tests use it to hand state from
one port to the other.
"""
import hashlib
import io
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from . import claude_records as cr
from .state_spec import STATE_KINDS

_ROW = STATE_KINDS["main-fold"]
MAIN_FOLD_FORMAT = _ROW["format"]
# At most this many bytes of UTF-8 a part, except a single entry longer than
# that; and no head longer is saved.
FOLD_PART_BYTES = _ROW["part_bytes"]
# The bytes a head's check digests are taken over.
FOLD_CHECK_BYTES = _ROW["check_bytes"]
# The two slots a head is written to in turn.
HEAD_SLOTS = ("head-a.cache", "head-b.cache")


def part_name(i: int) -> str:
    return "part-%d.cache" % i


class MainFold:
    """Both folds of the main transcript, fed the same records."""

    __slots__ = ("tr", "tu")

    def __init__(self):
        self.tr = cr.TranscriptFold()
        self.tu = cr.TurnsFold()


def fold_main(f: MainFold, r: dict) -> None:
    cr.fold_transcript(f.tr, r)
    cr.fold_turns(f.tu, r)


def fold_meta(data: bytes, offset: int) -> dict:
    """What a saved fold says of the transcript it was folded from: the
    byte offset folded to, a whole line's end, and the sha256 of the first
    FOLD_CHECK_BYTES and of the FOLD_CHECK_BYTES before the offset, over the
    transcript's `data` from its start up to `offset` at least."""
    return {"offset": offset,
            "first": hashlib.sha256(
                data[:min(FOLD_CHECK_BYTES, offset)]).hexdigest(),
            "tail": hashlib.sha256(
                data[max(0, offset - FOLD_CHECK_BYTES):offset]).hexdigest()}


# ── Writing as JavaScript writes ────────────────────────────────────────────

_SURROGATE = re.compile("[\ud800-\udfff]")


def js_num(x: float) -> str:
    """A float as JavaScript's Number#toString spells it: the shortest
    digits that round-trip, as repr finds them, laid out by its rules."""
    if x != x or x in (float("inf"), float("-inf")):
        return "null"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    mant, _, exp = repr(abs(x)).partition("e")
    ip, _, fp = mant.partition(".")
    raw = ip + fp
    digits = raw.lstrip("0")
    n = len(ip) + int(exp or 0) - (len(raw) - len(digits))
    digits = digits.rstrip("0")
    k = len(digits)
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * -n + digits
    else:
        e = n - 1
        s = (digits[0] + ("." + digits[1:] if k > 1 else "") + "e"
             + ("+" if e >= 0 else "-") + str(abs(e)))
    return sign + s


def _js_str(s: str) -> str:
    # A lone surrogate is escaped, as JSON.stringify escapes it.
    return _SURROGATE.sub(lambda m: "\\u%04x" % ord(m.group()),
                          json.dumps(s, ensure_ascii=False))


def js_dumps(v) -> str:
    """JSON.stringify's text of `v`: no spaces, numbers as js_num."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return js_num(v)
    if isinstance(v, str):
        return _js_str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(js_dumps(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(_js_str(str(k)) + ":" + js_dumps(x)
                              for k, x in v.items()) + "}"
    raise TypeError("not JSON: %r" % (v,))


def _fl(x):
    return None if x is None else float(x)


# ── The log and the head ────────────────────────────────────────────────────

class SaveMark:
    """What a save has written of a fold, for the next to write only what
    is new: the parts' entry counts, the last part's text, how many of
    each list's entries are logged, and the maps as logged."""

    __slots__ = ("seq", "counts", "last", "last_bytes", "logged", "ends",
                 "uends", "pids")

    def __init__(self):
        self.seq = 0
        self.counts: List[int] = []
        self.last = ""
        self.last_bytes = 0
        self.logged: Dict[str, int] = {}
        self.ends: dict = {}
        self.uends: dict = {}
        self.pids: dict = {}


def _turn_json(t: dict) -> dict:
    return {"ts": t["ts"], "text": t["text"], "fresh": t["fresh"],
            "cw": t["cw"], "cr": t["cr"], "out": t["out"], "ctx": t["ctx"],
            "n": t["n"], "usd": t["usd"], "an": t["an"], "aids": t["aids"],
            "t0": t["t0"], "t1": t["t1"], "parts": t["parts"],
            "tools": t["tools"], "waits": t["waits"], "am": t["am"],
            "at": t["at"], "pid": t["pid"], "tidx": t["tidx"], "la": t["la"],
            "lr": t["lr"], "eta": t["eta"], "dur": t.get("dur"),
            "compact": t.get("compact")}


def _turn_of(o: dict) -> dict:
    t = {"ts": o["ts"], "text": o["text"], "fresh": o["fresh"],
         "cw": o["cw"], "cr": o["cr"], "out": o["out"], "ctx": o["ctx"],
         "n": o["n"], "usd": [float(x) for x in o["usd"]], "an": o["an"],
         "aids": o["aids"], "t0": _fl(o["t0"]), "t1": _fl(o["t1"]),
         "parts": [(_fl(e), float(c)) for e, c in o["parts"]],
         "tools": [(float(a), float(b)) for a, b in o["tools"]],
         "waits": [(float(a), float(b)) for a, b in o["waits"]],
         "am": float(o["am"]), "at": float(o["at"]), "pid": o["pid"],
         "tidx": o["tidx"], "la": o["la"], "lr": o["lr"],
         "eta": tuple(float(x) for x in o["eta"])}
    if o["dur"] is not None:
        t["dur"] = float(o["dur"])
    if o["compact"] is not None:
        t["compact"] = o["compact"]
    return t


def _part_of(p) -> list:
    """An own part read back: [epoch, dollars], or a compaction's
    [epoch, [cache-read dollars, output dollars]]."""
    e, c = p
    return [_fl(e), [float(c[0]), float(c[1])] if isinstance(c, list)
            else float(c)]


def _closed_parts(tr) -> int:
    return len(tr.parts) if tr.compacting is None else tr.compacting


def _new_entries(f: MainFold, mark: SaveMark):
    """The entries `f` holds past what `mark` logged, each as its line's
    text, in the order the tags are listed; and the logged counts and maps
    they bring `mark` to."""
    lines: List[str] = []
    logged = dict(mark.logged)

    def since(tag, items, upto, entry):
        done = logged.get(tag, 0)
        i = 0
        for x in items:
            if i >= upto:
                break
            if i >= done:
                lines.append(js_dumps(entry(x)))
            i += 1
        logged[tag] = max(done, min(i, upto))

    def changed(tag, now, was):
        for k, v in now.items():
            if k not in was or was[k] != v:
                lines.append(js_dumps([tag, k, v]))
        return dict(now)

    tr, tu = f.tr, f.tu
    inf = float("inf")
    since("r", tr.reqs, inf, lambda k: ["r", k])
    since("w", tr.wrote, inf, lambda k: ["w", k])
    ends = changed("e", tr.ends, mark.ends)
    since("s", tr.spans, inf, lambda s: ["s", s[0], s[1]])
    since("t", tr.tools, inf, lambda s: ["t", s[0], s[1]])
    since("b", tr.blocked, inf, lambda s: ["b", s[0], s[1]])
    since("p", tr.parts, _closed_parts(tr), lambda p: ["p", p[0], p[1]])
    since("S", tu.seen, inf, lambda k: ["S", k])
    since("W", tu.wrote, inf, lambda k: ["W", k])
    uends = changed("E", tu.ends, mark.uends)
    pids = changed("P", tu.by_pid, mark.pids)
    since("T", tu.turns, max(0, len(tu.turns) - 1),
          lambda t: ["T", _turn_json(t)])
    return lines, logged, ends, uends, pids


def _pending_json(p) -> list:
    return [[k, t, name] for k, (t, name) in p.items()]


def _head_text(f: MainFold, meta: dict, counts, seq: int) -> str:
    tr, tu = f.tr, f.tu
    e = tr.eta_state
    return js_dumps({
        "format": MAIN_FOLD_FORMAT, "seq": seq, "offset": meta["offset"],
        "first": meta["first"], "tail": meta["tail"], "counts": counts,
        "tr": {"fresh": tr.fresh, "cwrite": tr.cwrite, "cread": tr.cread,
               "down": tr.down, "parts": tr.parts[_closed_parts(tr):],
               "compacting": tr.compacting, "opener": tr.opener,
               "own_est": tr.own_est, "ctx": tr.ctx,
               "first_ctx": tr.first_ctx, "ctx_est": tr.ctx_est,
               "user_ts": tr.user_ts, "user_text": tr.user_text,
               "asst_ts": tr.asst_ts, "asst_text": tr.asst_text,
               "pending": _pending_json(tr.pending), "first": tr.first,
               "open_at": tr.open_at, "prev": tr.prev,
               "eta": [e[0], e[1], e[2], e[3]], "queued": tr.queued,
               "compactions": tr.compactions,
               "background": [[k, v] for k, v in tr.background.items()],
               "idle_at": tr.idle_at, "last_seen": tr.last_seen,
               "opened": [tr.opened["pid"], tr.opened["tidx"]],
               "added": tr.added, "removed": tr.removed},
        "tu": {"settled": tu.settled, "last_stop": tu.last_stop,
               "pending": _pending_json(tu.pending),
               "open": _turn_json(tu.turns[-1]) if tu.turns else None}})


def fold_save(f: MainFold, meta: dict, mark: Optional[SaveMark] = None,
              part_bytes: int = FOLD_PART_BYTES,
              head_bytes: int = FOLD_PART_BYTES):
    """A save of `f`: the parts to write, as (index, text), then the head
    and its slot, and the mark the save brings `mark` to once all are
    written; with no mark, the whole fold.  None where the head would be
    over `head_bytes`, which is not saved.  The sizes are the tests'."""
    mark = SaveMark() if mark is None else mark
    lines, logged, ends, uends, pids = _new_entries(f, mark)
    counts = list(mark.counts)
    last, last_bytes = mark.last, mark.last_bytes
    at = len(counts) - 1
    # Each part's lines, joined once: a part grown a line at a time is
    # copied whole on each.
    texts: Dict[int, List[str]] = {}
    for line in lines:
        size = len(line.encode("utf-8")) + 1
        if at < 0 or (counts[at] > 0
                      and last_bytes + size > part_bytes):
            counts.append(0)
            at = len(counts) - 1
            last_bytes = 0
            texts[at] = []
        elif at not in texts:
            texts[at] = [last]
        texts[at].append(line + "\n")
        last_bytes += size
        counts[at] += 1
    parts = {i: "".join(t) for i, t in texts.items()}
    last = parts.get(at, last)
    seq = mark.seq + 1
    head = _head_text(f, meta, counts, seq)
    if len(head.encode("utf-8")) > head_bytes:
        return None
    new = SaveMark()
    new.seq, new.counts, new.last, new.last_bytes = seq, counts, last, \
        last_bytes
    new.logged, new.ends, new.uends, new.pids = logged, ends, uends, pids
    return list(parts.items()), head, HEAD_SLOTS[seq % 2], new


def fold_writes(f: MainFold, meta: dict, mark: Optional[SaveMark] = None,
                part_bytes: int = FOLD_PART_BYTES):
    """The files a save of `f` writes, in order, as (name, text), and the
    mark it brings `mark` to; None where the head is over its cap.  With no
    mark, a fold started over, both heads are emptied first, so neither
    reads a part it was not written beside; then the parts; then the head.
    The mod's saveMainFold (hooks/edges.ts) writes foldWrites' list, the
    same one."""
    got = fold_save(f, meta, mark, part_bytes)
    if got is None:
        return None
    parts, head, slot, new = got
    writes = [] if mark is not None else [(s, "") for s in HEAD_SLOTS]
    writes += [(part_name(i), t) for i, t in parts]
    writes.append((slot, head))
    return writes, new


def fold_head_of(text: Optional[str]):
    """A head's text read back, as (seq, meta, counts, head), or None for
    one that will not parse, is of another format, or is not a head."""
    if text is None:
        return None
    try:
        o = json.loads(text)
    except ValueError:
        return None
    if (not isinstance(o, dict) or o.get("format") != MAIN_FOLD_FORMAT
            or not isinstance(o.get("seq"), int)
            or not isinstance(o.get("offset"), int)
            or not isinstance(o.get("counts"), list)
            or not isinstance(o.get("tr"), dict)
            or not isinstance(o.get("tu"), dict)):
        return None
    return (o["seq"], {"offset": o["offset"], "first": o.get("first"),
                       "tail": o.get("tail")}, o["counts"], o)


def _pending_of(xs) -> dict:
    return {k: (float(t), name) for k, t, name in xs}


def fold_of_saved(got, parts):
    """The fold a head and its parts' texts hold, with the mark a save from
    it starts at, as (fold, mark); None where a part is missing, torn or
    holds fewer entries than the head names."""
    seq, _meta, counts, head = got
    f = MainFold()
    tr, tu = f.tr, f.tu
    logged: Dict[str, int] = {}
    last = ""
    try:
        for i, n in enumerate(counts):
            text = parts[i] if i < len(parts) else None
            if text is None:
                return None
            lines = text.split("\n")
            if len(lines) - 1 < n:
                return None
            last = "".join(l + "\n" for l in lines[:n])
            for line in lines[:n]:
                e = json.loads(line)
                tag = e[0]
                logged[tag] = logged.get(tag, 0) + 1
                if tag == "r":
                    tr.reqs.add(e[1])
                elif tag == "w":
                    tr.wrote.add(e[1])
                elif tag == "e":
                    tr.ends[e[1]] = float(e[2])
                elif tag in ("s", "t", "b"):
                    {"s": tr.spans, "t": tr.tools, "b": tr.blocked}[tag] \
                        .append((float(e[1]), float(e[2])))
                elif tag == "p":
                    tr.parts.append(_part_of(e[1:]))
                elif tag == "S":
                    tu.seen.add(e[1])
                elif tag == "W":
                    tu.wrote.add(e[1])
                elif tag == "E":
                    tu.ends[e[1]] = float(e[2])
                elif tag == "P":
                    tu.by_pid[e[1]] = e[2]
                elif tag == "T":
                    tu.turns.append(_turn_of(e[1]))
                else:
                    return None
        for tag in ("e", "E", "P"):
            logged.pop(tag, None)
        h, u = head["tr"], head["tu"]
        tr.fresh, tr.cwrite, tr.cread, tr.down = (
            h["fresh"], h["cwrite"], h["cread"], h["down"])
        tr.parts.extend(_part_of(p) for p in h["parts"])
        tr.compacting = h["compacting"]
        tr.opener = h["opener"]
        tr.own_est = h["own_est"]
        tr.ctx, tr.first_ctx, tr.ctx_est = (
            h["ctx"], h["first_ctx"], h["ctx_est"])
        tr.user_ts, tr.user_text = h["user_ts"], h["user_text"]
        tr.asst_ts, tr.asst_text = h["asst_ts"], h["asst_text"]
        tr.pending = _pending_of(h["pending"])
        tr.first, tr.open_at, tr.prev = (
            _fl(h["first"]), _fl(h["open_at"]), _fl(h["prev"]))
        eta = h["eta"]
        tr.eta_state = [tuple(float(x) for x in eta[0]), eta[1],
                        _fl(eta[2]), eta[3]]
        tr.queued, tr.compactions = h["queued"], h["compactions"]
        tr.background = {k: v for k, v in h["background"]}
        tr.idle_at, tr.last_seen = float(h["idle_at"]), float(h["last_seen"])
        tr.opened = {"pid": h["opened"][0], "tidx": h["opened"][1]}
        tr.added, tr.removed = h["added"], h["removed"]
        tu.settled = u["settled"]
        tu.last_stop = _fl(u["last_stop"])
        tu.pending = _pending_of(u["pending"])
        if u["open"] is not None:
            tu.turns.append(_turn_of(u["open"]))
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    mark = SaveMark()
    mark.seq, mark.counts, mark.last = seq, list(counts), last
    mark.last_bytes = len(last.encode("utf-8"))
    mark.logged = logged
    mark.ends, mark.uends, mark.pids = (dict(tr.ends), dict(tu.ends),
                                        dict(tu.by_pid))
    return f, mark


# ── Files ───────────────────────────────────────────────────────────────────

def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, ValueError):
        return None


def load(read, fits=lambda meta: True):
    """The fold saved in the files `read` reads by name (None for none),
    as (fold, meta, mark), from the newest head that `fits` takes the meta
    of and whose parts read whole; None for none."""
    heads = [h for h in (fold_head_of(read(s)) for s in HEAD_SLOTS)
             if h is not None]
    for got in sorted(heads, key=lambda h: -h[0]):
        if not fits(got[1]):
            continue
        parts = [read(part_name(i)) for i in range(len(got[2]))]
        back = fold_of_saved(got, parts)
        if back is not None:
            return back[0], got[1], back[1]
    return None


def load_dir(d: str):
    """load over the files in directory `d`."""
    return load(lambda name: _read(os.path.join(d, name)))


def _write(path: str, text: str) -> None:
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def save_dir(d: str, f: MainFold, meta: dict,
             mark: Optional[SaveMark] = None,
             part_bytes: int = FOLD_PART_BYTES) -> Optional[SaveMark]:
    """fold_save written into directory `d`: the parts, then the head.
    The new mark, or None where the head was over its cap."""
    got = fold_save(f, meta, mark, part_bytes)
    if got is None:
        return None
    parts, head, slot, new = got
    os.makedirs(d, exist_ok=True)
    for i, text in parts:
        _write(os.path.join(d, part_name(i)), text)
    _write(os.path.join(d, slot), head)
    return new


def records_of(data: bytes) -> List[dict]:
    """_records' reading of `data`, the objects alone: text mode's
    universal newlines, errors replaced."""
    out = []
    for line in io.TextIOWrapper(io.BytesIO(data), encoding="utf-8",
                                 errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def line_ends(data: bytes) -> List[int]:
    """The offset after each newline in `data`: where a fold can stop."""
    out, at = [], data.find(b"\n")
    while at >= 0:
        out.append(at + 1)
        at = data.find(b"\n", at + 1)
    return out


_NEWLINES = re.compile(r"\r\n|\r|\n")


def line_records(raw: bytes):
    """records_of's reading of one whole line, `raw`: errors replaced,
    split on \\r\\n, \\r and \\n, an object's each.  No sequence a decoder
    replaces holds a newline byte, so line by line reads as all at once."""
    text = raw.decode("utf-8", "replace")
    # Nearly every line ends in its one newline and holds no other.
    texts = (_NEWLINES.split(text) if b"\r" in raw
             else (text[:-1] if text.endswith("\n") else text,))
    for text in texts:
        if not text:
            continue
        try:
            r = json.loads(text)
        except ValueError:
            continue
        if isinstance(r, dict):
            yield r


def _meta_at(fh, offset: int) -> dict:
    """fold_meta of the open transcript `fh`, read only where it looks."""
    fh.seek(0)
    first = fh.read(min(FOLD_CHECK_BYTES, offset))
    lo = max(0, offset - FOLD_CHECK_BYTES)
    fh.seek(lo)
    tail = fh.read(offset - lo)
    return {"offset": offset, "first": hashlib.sha256(first).hexdigest(),
            "tail": hashlib.sha256(tail).hexdigest()}


def fold_on(transcript: str, d: str, end: Optional[int] = None) -> int:
    """The mod's cold read, run as a process (mod/scripts/agent_lines.py's
    fold mode): the fold saved in directory `d` for `transcript`, read on
    over its whole lines up to `end` (its end where None), and saved back
    into `d` as the mod saves it, in fold_writes' order, each file through
    os.replace.  A saved head is read only where the transcript still holds
    the bytes it was folded from, as the mod checks it; with none, the fold
    starts over from the transcript's start.  The offset saved to, which
    the mod reads the head and parts at; where nothing new was folded, or
    the head is over its cap, nothing is written and the offset is the one
    saved before (0 for none).  The transcript is read a line at a time,
    so only the fold is held."""
    with open(transcript, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        end = size if end is None else min(end, size)
        got = load(lambda name: _read(os.path.join(d, name)),
                   lambda meta: meta["offset"] <= size
                   and _meta_at(fh, meta["offset"]) == meta)
        f, mark = (got[0], got[2]) if got else (MainFold(), None)
        start = at = got[1]["offset"] if got else 0
        fh.seek(at)
        while at < end:
            raw = fh.readline(end - at)
            if not raw.endswith(b"\n"):
                break
            for r in line_records(raw):
                fold_main(f, r)
            at += len(raw)
        if at == start:
            return start
        save = fold_writes(f, _meta_at(fh, at), mark)
    if save is None:
        return start
    os.makedirs(d, exist_ok=True)
    for name, text in save[0]:
        _write(os.path.join(d, name), text)
    return at


def main(argv: List[str]) -> int:
    """save: one directory, as the module's docstring says.

    every TRANSCRIPT OUT [--part-bytes N]: the whole fold's state at each
    line end K, as a first save writes it, in OUT/K.

    readon TRANSCRIPT DIR [--part-bytes N]: for each DIR/K, the state there
    read on to TRANSCRIPT's last newline, printed as one JSON line,
    {"at": K, "parts": [...], "head": ...}, of its first save's texts."""
    if len(argv) < 3 or argv[0] not in ("save", "every", "readon"):
        sys.stderr.write(__doc__)
        return 2
    cmd, transcript, out = argv[0], argv[1], argv[2]
    opts = dict(zip(argv[3::2], argv[4::2]))
    size = int(opts.get("--part-bytes", FOLD_PART_BYTES))
    with open(transcript, "rb") as fh:
        data = fh.read()
    end = data.rfind(b"\n") + 1
    if cmd == "every":
        f, done = MainFold(), 0
        for k in line_ends(data):
            for r in records_of(data[done:k]):
                fold_main(f, r)
            done = k
            save_dir(os.path.join(out, str(k)), f, fold_meta(data, k),
                     part_bytes=size)
        return 0
    if cmd == "readon":
        for k in sorted(int(x) for x in os.listdir(out) if x.isdigit()):
            got = load_dir(os.path.join(out, str(k)))
            if got is None:
                sys.stdout.write(js_dumps({"at": k, "parts": None,
                                           "head": None}) + "\n")
                continue
            f = got[0]
            for r in records_of(data[got[1]["offset"]:end]):
                fold_main(f, r)
            parts, head, _slot, _mark = fold_save(f, fold_meta(data, end),
                                                  part_bytes=size)
            sys.stdout.write(js_dumps({"at": k,
                                       "parts": [t for _, t in parts],
                                       "head": head}) + "\n")
        return 0
    upto = int(opts.get("--upto", end))
    f, start = MainFold(), 0
    if "--from" in opts:
        got = load_dir(opts["--from"])
        if got is None:
            sys.stderr.write("no state in %s\n" % opts["--from"])
            return 1
        f, start = got[0], got[1]["offset"]
    for r in records_of(data[start:upto]):
        fold_main(f, r)
    return 0 if save_dir(out, f, fold_meta(data, upto),
                         part_bytes=size) is not None else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
