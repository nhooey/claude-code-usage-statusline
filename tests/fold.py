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

import json
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
from coding_agent_usage_line import main_fold as mf  # noqa: E402

STATE = os.path.join(ROOT, "tests", "fixtures", "state")


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


def saved(f, data, end, mark=None, part_bytes=mf.FOLD_PART_BYTES):
    """fold_save's texts, as the fixtures hold them."""
    parts, head, _slot, _mark = mf.fold_save(f, mf.fold_meta(data, end), mark,
                                             part_bytes)
    return {"parts": [t for _, t in parts], "head": head}


def loaded(texts):
    """The fold a first save's texts hold."""
    files = {mf.part_name(i): t for i, t in enumerate(texts["parts"])}
    seq = mf.fold_head_of(texts["head"])[0]
    files[mf.HEAD_SLOTS[seq % 2]] = texts["head"]
    return mf.load(files.get)


def check_saves(path):
    """The saved state of `path`'s fold: the fixture's text, read back at
    every line end and read on to the same text, saved in many parts and
    as it grows, and read past a torn head."""
    name = os.path.relpath(path, ROOT)
    with open(path, "rb") as fh:
        data = fh.read()
    end = data.rfind(b"\n") + 1
    ends = mf.line_ends(data)
    whole = mf.MainFold()
    for r in mf.records_of(data[:end]):
        mf.fold_main(whole, r)
    fixture = os.path.join(STATE, os.path.relpath(path, os.path.join(
        ROOT, "tests", "fixtures")).replace("/", "--") + ".json")
    with open(fixture, encoding="utf-8") as fh:
        want = json.load(fh)
    if want["format"] != mf.MAIN_FOLD_FORMAT:
        check("%s: tests/fixtures/state/ is at the spec's format; run "
              "tests/fixtures/gen/state.py" % name, want["format"],
              mf.MAIN_FOLD_FORMAT)
        return
    want = {"parts": want["parts"], "head": want["head"]}
    check("%s: saved as tests/fixtures/state/ holds it; a change to the "
          "fold needs a new format in spec/state.jsonc" % name,
          saved(whole, data, end), want)

    broke = []
    f, done = mf.MainFold(), 0
    for k in ends:
        for r in mf.records_of(data[done:k]):
            mf.fold_main(f, r)
        done = k
        back = loaded(saved(f, data, k))
        if back is None or back[1]["offset"] != k:
            broke.append(("not read back", k))
            continue
        g = back[0]
        if finish(path, (g.tr, g.tu)) != finish(path, (f.tr, f.tu)):
            broke.append(("reads otherwise", k))
        for r in mf.records_of(data[k:end]):
            mf.fold_main(g, r)
        if saved(g, data, end) != want:
            broke.append(("read on otherwise", k))
    check("%s: saved at any line end, read back and read on" % name,
          broke, [])

    # As the mod saves it: a part at a time as the fold grows, each save
    # the last part and the new ones, then a head in the other slot.
    broke, files, mark = [], {}, None
    f, done = mf.MainFold(), 0
    for k in ends:
        for r in mf.records_of(data[done:k]):
            mf.fold_main(f, r)
        done = k
        parts, head, slot, mark = mf.fold_save(
            f, mf.fold_meta(data, k), mark, 300)
        files.update((mf.part_name(i), t) for i, t in parts)
        files[slot] = head
        back = mf.load(files.get)
        if back is None or finish(path, (back[0].tr, back[0].tu)) != \
                finish(path, (f.tr, f.tu)):
            broke.append(("grown", k))
    if len(ends) > 1:
        # The newest head torn: the one before it reads, and reads on.
        newest = mf.HEAD_SLOTS[mark.seq % 2]
        files[newest] = files[newest][:len(files[newest]) // 2]
        back = mf.load(files.get)
        if back is None or back[1]["offset"] != ends[-2]:
            broke.append(("torn", ends[-2]))
        else:
            for r in mf.records_of(data[back[1]["offset"]:end]):
                mf.fold_main(back[0], r)
            if saved(back[0], data, end) != want:
                broke.append(("torn, read on", ends[-2]))
    check("%s: saved as it grows, in parts, past a torn head" % name,
          broke, [])


def main():
    check("a float is written as JavaScript writes it",
          [mf.js_num(x) for x in (1.0, 0.1, 1e-7, 1.5e-7, 1e21, 1e20,
                                  123456789012345680000.0, 0.000001, -2.5,
                                  1700000000.123, 5e-324,
                                  1.7976931348623157e308, 0.0000012345,
                                  float(2 ** 53 + 2), 1e-6 * 3, -0.0)],
          ["1", "0.1", "1e-7", "1.5e-7", "1e+21", "100000000000000000000",
           "123456789012345680000", "0.000001", "-2.5", "1700000000.123",
           "5e-324", "1.7976931348623157e+308", "0.0000012345",
           "9007199254740994", "0.000003", "0"])
    check("a lone surrogate is escaped, a pair kept",
          mf.js_dumps(["\ud800", "\U0001f600", "\x1f\n\u2028"]),
          '["\\ud800","\U0001f600","\\u001f\\n\u2028"]')
    big = mf.MainFold()
    big.tr.user_text = "x" * 2000
    check("a head over its cap is not saved",
          mf.fold_save(big, mf.fold_meta(b"", 0), None, 1000, 1000), None)
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
        check_saves(path)

    print()
    line, status = tally()
    print(line)
    return status


if __name__ == "__main__":
    sys.exit(main())
