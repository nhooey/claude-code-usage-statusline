#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The main transcript's folds, broken anywhere.

read_transcript and read_turns are each a fold of the transcript's records
and a finish over it.  A fold finished at any record, or with a
half-written last line folded on a copy, reads on to what the whole fold
reads: the finish leaves the fold as it was.  mod/test/main_fold.test.ts
holds the TypeScript's side of the same cases.

Run:  python3 tests/fold.py
"""

import os
import subprocess
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DIR)
sys.path.insert(0, ROOT)
os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = tempfile.mkdtemp()

from _checks import check, tally  # noqa: E402
from coding_agent_usage_line import claude_records as cr  # noqa: E402


def fixtures():
    """Every fixture transcript that is a session's own, not an agent's."""
    out = subprocess.run(["git", "ls-files", "tests/fixtures"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [os.path.join(ROOT, f) for f in out.split()
            if f.endswith(".jsonl")
            and not os.path.basename(f).startswith("agent-")]


def dicts(records):
    """The records that are objects: what the TypeScript's _recordsOf
    keeps, and the only ones a fold is handed.  The Python's _records
    yields the rest too, and its first reader raises on them."""
    return [r for r in records if isinstance(r, dict)]


def records_of(data: bytes):
    """_records' reading of `data`, as though it were the whole file."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as fh:
        fh.write(data)
    try:
        return dicts(cr._records(fh.name))
    finally:
        os.remove(fh.name)


def fold_all(records, f=None):
    tr, tu = f if f is not None else (None, None)
    return (cr.fold_transcript_all(records, tr),
            cr.fold_turns_all(records, tu))


def finish(path, f):
    """Both finishes of `f`, with the agents beside `path` and a clock, so
    every input a finish takes is in play; with what the turns held.  A
    finish that raises reads as what it raised: a fixture's odd record can
    make the read of a prefix raise, as it did before the fold."""
    etas = []
    agents = cr.agent_records(path, etas=etas)
    held = {}
    try:
        return (cr.transcript_finish(f[0], agents, etas, 1e10),
                cr.turns_finish(f[1], None, path, held), held)
    except Exception as e:  # noqa: BLE001
        return ("raises", type(e).__name__, str(e))


def main():
    files = fixtures()
    check("there are fixture transcripts to fold", len(files) > 10, True)
    for path in files:
        name = os.path.relpath(path, ROOT)
        records = dicts(cr._records(path))
        whole = finish(path, fold_all(records))
        broken = []
        for k in range(len(records) + 1):
            f = fold_all(records[:k])
            if finish(path, f) != finish(path, fold_all(records[:k])):
                broken.append(("finished", k))
            fold_all(records[k:], f)
            if finish(path, f) != whole:
                broken.append(("read on", k))
        check("%s: finished at any record, reads on as whole" % name,
              broken, [])

        with open(path, "rb") as fh:
            data = fh.read()
        broken = []
        end = data.find(b"\n")
        while end >= 0:
            start = data.rfind(b"\n", 0, end) + 1
            for cut in sorted({start + (end - start) // 2, end}):
                f = fold_all(records_of(data[:start]))
                before = finish(path, f)
                tail = records_of(data[start:cut])
                view = (cr.transcript_fold_with(f[0], tail),
                        cr.turns_fold_with(f[1], tail))
                if finish(path, view) != finish(path, fold_all(
                        records_of(data[:cut]))):
                    broken.append(("half-written", cut))
                if finish(path, f) != before:
                    broken.append(("left as it was", cut))
                fold_all(records_of(data[start:]), f)
                if finish(path, f) != whole:
                    broken.append(("completed", cut))
            end = data.find(b"\n", end + 1)
        check("%s: a half-written last line reads now and once completed"
              % name, broken, [])

    print()
    line, status = tally()
    print(line)
    return status


if __name__ == "__main__":
    sys.exit(main())
