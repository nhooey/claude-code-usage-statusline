#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The main transcript's folds over the real transcripts on this machine.

    python3 tests/fold_real.py [--largest N] [--seed S] [FILE...]

Not in CI and not in tests/all.sh: it reads ~/.claude/projects, which is
private, and takes minutes over every file there.  For each transcript
(every *.jsonl under ~/.claude/projects, the agents' files too, or the FILEs
named; the N largest with --largest) it folds the records as
read_transcript and read_turns do, and breaks the fold at a seeded set of
points: three record boundaries, either side of every compaction, and one
cut inside a line.  At each break the fold is finished, and the fold read
on from there must finish as the whole fold does.  At the cut inside a
line, the line's records are folded on a copy, which must read as the file
cut there does, and the fold completed must read as the whole.  The mod's
cold read, the worker (main_fold.fold_on), must save from nothing and
from a state halfway the files a save of the whole fold writes; its time
from nothing is on the line.

One line a file, then a total; the exit status is the number of files that
broke.  mod/tools/check-fold.ts is the TypeScript's side; `check-folds` in
the dev shell runs both.  See
agents/plans/_implemented/saved-running-totals.md.
"""

import argparse
import glob
import io
import json
import os
import random
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from coding_agent_usage_line import claude_records as cr  # noqa: E402
from coding_agent_usage_line import main_fold as mf  # noqa: E402


def records_of(data: bytes):
    """_records' reading of `data`, objects only, as the folds take them:
    text mode's universal newlines, errors replaced."""
    out = []
    text = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8",
                            errors="replace")
    for line in text:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def fold_all(records, f=None):
    tr, tu = f if f is not None else (None, None)
    return (cr.fold_transcript_all(records, tr),
            cr.fold_turns_all(records, tu))


def finish(f, path):
    """Both finishes, with no agents: the agents never reach the fold."""
    return (cr.transcript_finish(f[0], (), (), 1e10),
            cr.turns_finish(f[1], (), path, {}))


def breaks(records, rng):
    """Where the fold is broken: three record boundaries, and either side
    of every compaction."""
    n = len(records)
    out = {rng.randint(0, n) for _ in range(3)} if n else {0}
    for i, r in enumerate(records):
        if cr.is_compaction(r):
            out.update((i, i + 1))
    return sorted(out)


def check(path, rng):
    """(what broke, records, compactions, breaks) for one transcript."""
    with open(path, "rb") as fh:
        data = fh.read()
    records = records_of(data)
    whole = finish(fold_all(records), path)
    at = breaks(records, rng)
    broke = []
    f = fold_all(())
    done = 0
    for k in at:
        fold_all(records[done:k], f)
        done = k
        here = finish(f, path)
        # Saved as text and read back, as a reload reads it.
        f = round_trip(f)
        if f is None:
            broke.append("not read back at record %d" % k)
            return broke, len(records), 0, len(at), None, 0.0
        if finish(f, path) != here:
            broke.append("read back otherwise at record %d" % k)
    fold_all(records[done:], f)
    if finish(f, path) != whole:
        broke.append("read on from %d breaks" % len(at))
    size = state_size(f)
    nl = data.rfind(b"\n", 0, rng.randint(1, max(1, len(data))))
    if nl > 0:
        start = data.rfind(b"\n", 0, nl) + 1
        cut = start + (nl - start) // 2
        f = fold_all(records_of(data[:start]))
        tail = records_of(data[start:cut])
        view = (cr.transcript_fold_with(f[0], tail),
                cr.turns_fold_with(f[1], tail))
        if finish(view, path) != finish(fold_all(records_of(data[:cut])),
                                        path):
            broke.append("cut at byte %d" % cut)
        fold_all(records_of(data[start:]), f)
        if finish(f, path) != whole:
            broke.append("completed after byte %d" % cut)
    took = worker(path, data, broke)
    return (broke, len(records), sum(map(cr.is_compaction, records)),
            len(at), size, took)


def dir_texts(d):
    out = {}
    for n in os.listdir(d):
        with open(os.path.join(d, n), encoding="utf-8", newline="") as fh:
            out[n] = fh.read()
    return out


def worker(path, data, broke):
    """The mod's cold read, main_fold.fold_on, as mod/scripts/agent_lines.py
    runs it: from nothing, and from a state saved at the line end halfway,
    each must leave the files a save of the whole fold writes.  Appends
    what broke to `broke`; the worker's seconds from nothing."""
    end = data.rfind(b"\n") + 1
    if not end:
        return 0.0
    whole = mf.MainFold()
    for r in records_of(data[:end]):
        mf.fold_main(whole, r)
    meta = mf.fold_meta(data, end)
    with tempfile.TemporaryDirectory() as d:
        t = time.time()
        to = mf.fold_on(path, d, len(data))
        took = time.time() - t
        if (to, dir_texts(d)) != (end, dict(mf.fold_writes(whole, meta)[0])):
            broke.append("the worker from nothing")
    half = data.rfind(b"\n", 0, end // 2) + 1
    if half:
        f = mf.MainFold()
        for r in records_of(data[:half]):
            mf.fold_main(f, r)
        with tempfile.TemporaryDirectory() as d:
            want = dict(mf.fold_writes(f, mf.fold_meta(data, half))[0])
            for n, t in want.items():
                with open(os.path.join(d, n), "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(t)
            back = mf.load_dir(d)
            for r in records_of(data[half:end]):
                mf.fold_main(back[0], r)
            want.update(mf.fold_writes(back[0], meta, back[2])[0])
            to = mf.fold_on(path, d, len(data))
            if (to, dir_texts(d)) != (end, want):
                broke.append("the worker from byte %d" % half)
    return took


def _main_fold(f):
    m = mf.MainFold()
    m.tr, m.tu = f
    return m


# What a round trip's head says of the transcript, which no check reads.
_META = {"offset": 0, "first": "", "tail": ""}


def round_trip(f):
    """`f` saved as a first save writes it and read back, or None."""
    parts, head, slot, _mark = mf.fold_save(_main_fold(f), _META,
                                            head_bytes=1 << 62)
    files = {mf.part_name(i): t for i, t in parts}
    files[slot] = head
    got = mf.load(files.get)
    return None if got is None else (got[0].tr, got[0].tu)


def state_size(f):
    """(parts, bytes of the parts, bytes of the head) of `f` saved."""
    parts, head, _slot, _mark = mf.fold_save(_main_fold(f), _META,
                                             head_bytes=1 << 62)
    return (len(parts), sum(len(t.encode("utf-8")) for _, t in parts),
            len(head.encode("utf-8")))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--largest", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    files = a.files or glob.glob(os.path.expanduser(
        "~/.claude/projects/**/*.jsonl"), recursive=True)
    files = sorted(files, key=lambda p: (-os.path.getsize(p), p))
    if a.largest:
        files = files[:a.largest]
    rng = random.Random(a.seed)
    bad = 0
    t0 = time.time()
    total = biggest = 0
    for path in files:
        t = time.time()
        size = os.path.getsize(path)
        total += size
        broke, n, comp, nb, saved, took = check(path, rng)
        bad += bool(broke)
        state = ("%2d parts %6.2f MB + head %6.1f KB" % (
            saved[0], saved[1] / 1e6, saved[2] / 1e3) if saved else "")
        biggest = max(biggest, saved[1] + saved[2] if saved else 0)
        print("%-4s %7.1f MB %7d records %3d compactions %3d breaks  %s"
              "  worker %5.2fs  %6.1fs  %s%s"
              % ("ok" if not broke else "FAIL", size / 1e6, n, comp, nb,
                 state, took, time.time() - t,
                 os.path.relpath(path, os.path.expanduser(
                     "~/.claude/projects")),
                 "" if not broke else "  (" + "; ".join(broke) + ")"),
              flush=True)
    print("%d files, %.1f GB, %d broke, largest state %.2f MB, %.0fs"
          % (len(files), total / 1e9, bad, biggest / 1e6, time.time() - t0))
    return min(bad, 255)


if __name__ == "__main__":
    sys.exit(main())
