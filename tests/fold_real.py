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
cut there does, and the fold completed must read as the whole.

One line a file, then a total; the exit status is the number of files that
broke.  mod/tools/check-fold.ts is the TypeScript's side; `check-folds` in
the dev shell runs both.  See agents/plans/saved-running-totals.md.
"""

import argparse
import glob
import io
import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from coding_agent_usage_line import claude_records as cr  # noqa: E402


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
        finish(f, path)
    fold_all(records[done:], f)
    if finish(f, path) != whole:
        broke.append("read on from %d breaks" % len(at))
    nl =data.rfind(b"\n", 0, rng.randint(1, max(1, len(data))))
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
    return broke, len(records), sum(map(cr.is_compaction, records)), len(at)


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
    total = 0
    for path in files:
        t = time.time()
        size = os.path.getsize(path)
        total += size
        broke, n, comp, nb = check(path, rng)
        bad += bool(broke)
        print("%-4s %7.1f MB %7d records %3d compactions %3d breaks %6.1fs  %s%s"
              % ("ok" if not broke else "FAIL", size / 1e6, n, comp, nb,
                 time.time() - t, os.path.relpath(path, os.path.expanduser(
                     "~/.claude/projects")),
                 "" if not broke else "  (" + "; ".join(broke) + ")"),
              flush=True)
    print("%d files, %.1f GB, %d broke, %.0fs"
          % (len(files), total / 1e9, bad, time.time() - t0))
    return min(bad, 255)


if __name__ == "__main__":
    sys.exit(main())
