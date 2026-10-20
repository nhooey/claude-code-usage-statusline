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
import shutil
import subprocess
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DIR)
sys.path.insert(0, ROOT)
os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = tempfile.mkdtemp()

from _checks import check, tally  # noqa: E402
from coding_agent_usage_line import agent_fold as af  # noqa: E402
from coding_agent_usage_line import claude  # noqa: E402
from coding_agent_usage_line import claude_records as cr  # noqa: E402
from coding_agent_usage_line import inbox_fold as ib  # noqa: E402
from coding_agent_usage_line import main_fold as mf  # noqa: E402

STATE = os.path.join(ROOT, "tests", "fixtures", "state")
AGENT_STATE = os.path.join(ROOT, "tests", "fixtures", "agent-state")
INBOX_STATE = os.path.join(ROOT, "tests", "fixtures", "inbox-state")


def fixtures():
    """Every fixture transcript that is a session's own, not an agent's."""
    out = subprocess.run(["git", "ls-files", "tests/fixtures"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [os.path.join(ROOT, f) for f in out.split()
            if f.endswith(".jsonl")
            and not os.path.basename(f).startswith("agent-")]


def check_agent_fold(path):
    """An agent's fold: saved at each line end as tests/fixtures/
    agent-state/ holds it, which mod/test/agent_fold.test.ts holds the
    TypeScript to as well; each text read back and read on to the last;
    and the panel's reading and agent_records' of what was read on, the
    whole file's."""
    name = os.path.relpath(path, ROOT)
    fixture = os.path.join(AGENT_STATE, os.path.relpath(path, os.path.join(
        ROOT, "tests", "fixtures")).replace("/", "--") + ".json")
    with open(fixture, encoding="utf-8") as fh:
        want = json.load(fh)
    if want["format"] != af.AGENT_FOLD_FORMAT:
        check("%s: tests/fixtures/agent-state/ is at the spec's format; run "
              "tests/fixtures/gen/state.py" % name, want["format"],
              af.AGENT_FOLD_FORMAT)
        return
    with open(path, "rb") as fh:
        data = fh.read()
    texts = want["texts"]
    if not texts:
        return
    f, at, got = cr.AgentFold(), 0, []
    for k, _ in texts:
        cr.fold_agent_bytes(f, data[at:k])
        at = k
        got.append([k, af.fold_text(f, 1, af.tail_digest(
            data[max(0, k - af.FOLD_CHECK_BYTES):k]))])
    check("%s: each line end's fold saved as tests/fixtures/agent-state/ "
          "holds it; a change to the fold needs a new format in "
          "spec/state.jsonc" % name, got, texts)
    last = texts[-1][1]
    broke = []
    for k, text in texts:
        seq, _tail, g = af.fold_of_text(text)
        if af.fold_text(g, seq, _tail) != text:
            broke.append(("read back otherwise", k))
        cr.fold_agent_bytes(g, data[k:texts[-1][0]])
        if af.fold_text(g, 1, _tail_of(data, texts[-1][0])) != last:
            broke.append(("read on otherwise", k))
        if (claude.agent_usage_of(g), cr.agent_reading_of(g)) != (
                claude.agent_usage_of(f), cr.agent_reading_of(f)):
            broke.append(("reads otherwise", k))
    check("%s: read back at any line end, read on to the whole" % name,
          broke, [])


def _tail_of(data, k):
    return af.tail_digest(data[max(0, k - af.FOLD_CHECK_BYTES):k])


def check_inbox_entry(fixture):
    """A file's inbox entry: folded at each line end as tests/fixtures/
    inbox-state/ holds it, which mod/test/inbox_fold.test.ts holds the
    TypeScript to as well; and each text, read back and read on, the
    last."""
    with open(fixture, encoding="utf-8") as fh:
        want = json.load(fh)
    name = want["file"]
    if want["format"] != ib.INBOX_FOLD_FORMAT:
        check("%s: tests/fixtures/inbox-state/ is at the spec's format; run "
              "tests/fixtures/gen/state.py" % name, want["format"],
              ib.INBOX_FOLD_FORMAT)
        return
    with open(os.path.join(ROOT, name), "rb") as fh:
        data = fh.read()
    texts, main = want["texts"], want["main"]
    e, at, got = ib.Entry(), 0, []
    for k, _ in texts:
        ib.fold_entry(e, data[at:k], main)
        at = k
        e.tail = ib.tail_digest(data[max(0, k - ib.FOLD_CHECK_BYTES):k])
        got.append([k, ib.entry_text(name, e)])
    check("%s: each line end's inbox entry as tests/fixtures/inbox-state/ "
          "holds it; a change to the fold needs a new format in "
          "spec/state.jsonc" % name, got, texts)
    end, last = texts[-1]
    broke = []
    for k, text in texts:
        fold = '{"format":%d,"seq":3,"files":[%s]}' % (ib.INBOX_FOLD_FORMAT,
                                                       text)
        seq, entries = ib.fold_of_text(fold)
        if ib.fold_text(entries, seq) != fold:
            broke.append(("read back otherwise", k))
        g = entries[name]
        ib.fold_entry(g, data[k:end], main)
        g.tail = ib.tail_digest(data[max(0, end - ib.FOLD_CHECK_BYTES):end])
        if ib.entry_text(name, g) != last:
            broke.append(("read on otherwise", k))
    check("%s: read back at any line end, read on to the whole" % name,
          broke, [])


def check_inbox_counts():
    """inbox_fold.counts against inbox_counts, which reads every file
    whole: a session copied in a line, and half a line, at a time; the
    slots it saves to; and a fold of other bytes passed over."""
    src = os.path.join(ROOT, "tests", "fixtures", "records", "inputs")
    for session in ("inbox-now", "session"):
        tmp = tempfile.mkdtemp(dir=WORK)
        tr = os.path.join(tmp, session + ".jsonl")
        agents = sorted(os.listdir(os.path.join(src, session, "subagents")))
        agents = [a for a in agents if a.endswith(".jsonl")]
        os.makedirs(os.path.join(tmp, session, "subagents"))
        paths = [tr] + [os.path.join(tmp, session, "subagents", a)
                        for a in agents]
        datas = []
        for p in [os.path.join(src, session + ".jsonl")] + [
                os.path.join(src, session, "subagents", a) for a in agents]:
            with open(p, "rb") as fh:
                datas.append(fh.read())
        targets = {cr.agent_label_id(p): p for p in paths[1:]}
        d = os.path.join(tmp, "state")
        # Every file grown together, a step at a time: each line end, and
        # the middle of each line, of the longest.
        steps = sorted({k for data in datas for e in mf.line_ends(data)
                        for k in (e, e - 7)} | {0})
        broke, saves = [], set()
        for k in steps:
            for p, data in zip(paths, datas):
                with open(p, "wb") as fh:
                    fh.write(data[:k])
            for since in (None, 0.0, 4e9):
                want = cr.inbox_counts(paths, targets, since)
                got = ib.counts(tr, paths, targets, since, d)
                if got != want:
                    broke.append((k, since, got, want))
            saves.update(n for n in os.listdir(d) if n in ib.SLOTS)
        check("%s: the inbox read on from its fold, grown a line and half "
              "a line at a time, counts as the whole files" % session,
              broke, [])
        check("%s: saved to both slots in turn" % session,
              sorted(saves), sorted(ib.SLOTS))
    # The last session's fold: both slots, the newer one torn.
    texts = {n: open(os.path.join(d, n), encoding="utf-8").read()
             for n in ib.SLOTS}
    newer = max(ib.SLOTS, key=lambda n: ib._seq_of(texts[n]))
    older = min(ib.SLOTS, key=lambda n: ib._seq_of(texts[n]))
    check("the newer slot read first",
          ib.load([texts[older], texts[newer]])[1], ib._seq_of(texts[newer]))
    check("a torn newer slot passed over for the older",
          ib.load([texts[newer][:30], texts[older]])[1],
          ib._seq_of(texts[older]))
    check("with neither, no entries and the highest seq either starts with",
          ib.load([texts[newer][:30], None]),
          ({}, ib._seq_of(texts[newer])))
    with open(os.path.join(d, newer), "w") as fh:
        fh.write(texts[newer][:len(texts[newer]) // 2])
    want = cr.inbox_counts(paths, targets)
    check("a torn newer slot: read on from the older, counted the same",
          ib.counts(tr, paths, targets, None, d), want)
    check("and saved over the torn one, after the older's seq",
          ib.fold_of_text(open(os.path.join(d, newer)).read())[0],
          ib._seq_of(texts[older]) + 1)
    # An entry at the file's size and mtime is taken as it stands; a
    # rewrite to the same size, at another mtime, is read afresh.
    a1 = targets["a1"]
    with open(a1, "rb") as fh:
        data = fh.read()
    st = os.stat(a1)
    swapped = data.replace(b"20:", b"21:")
    with open(a1, "wb") as fh:
        fh.write(swapped)
    os.utime(a1, ns=(st.st_atime_ns, st.st_mtime_ns))
    entries, _ = ib.load([open(os.path.join(d, n)).read() for n in ib.SLOTS])
    check("an entry at the file's size and mtime is not read",
          ib.read_on(entries, a1)[1], False)
    os.utime(a1, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    want = cr.inbox_counts(paths, targets)
    check("a rewrite to the same size, at another mtime, read afresh",
          (ib.counts(tr, paths, targets, None, d), len(data) == len(swapped)),
          (want, True))
    with open(a1, "wb") as fh:
        fh.write(data)
    check("a file gone has its entry dropped",
          ib.read_on(entries, os.path.join(tmp, "gone.jsonl")), (None, False))


def agent_fixtures():
    out = subprocess.run(["git", "ls-files", "tests/fixtures"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [os.path.join(ROOT, f) for f in out.split()
            if f.endswith(".jsonl")
            and os.path.basename(f).startswith("agent-")]


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
    check_worker(path, data, want)


# The mod's cold read, mod/scripts/agent_lines.py's fold mode, under the
# 3.9 the mod may find as python3: macOS's own, where there is one.
PY39 = "/usr/bin/python3"
WORKER = os.path.join(ROOT, "mod", "scripts", "agent_lines.py")
# The worker's directories, removed at the end.
WORK = tempfile.mkdtemp()


def dir_texts(d):
    out = {}
    for n in sorted(os.listdir(d)):
        with open(os.path.join(d, n), encoding="utf-8", newline="") as fh:
            out[n] = fh.read()
    return out


def check_worker(path, data, want):
    """fold_on, the worker, from nothing: the fixture's text, both heads
    emptied first; read on from a state halfway, the same text read back;
    and again with nothing new, nothing written.
    mod/test/main_fold.test.ts checks the worker against the mod's own
    saves byte for byte."""
    name = os.path.relpath(path, ROOT)
    end = data.rfind(b"\n") + 1
    ends = mf.line_ends(data)
    d = tempfile.mkdtemp(dir=WORK)
    to = mf.fold_on(path, d)
    texts = {mf.part_name(i): t for i, t in enumerate(want["parts"])}
    texts.update({mf.HEAD_SLOTS[0]: "", mf.HEAD_SLOTS[1]: want["head"]})
    check("%s: the worker saves from nothing as the fixture" % name,
          (to, dir_texts(d)), (end, texts) if end else (0, {}))
    if len(ends) < 2:
        return
    half = ends[len(ends) // 2 - 1]
    d = tempfile.mkdtemp(dir=WORK)
    f = mf.MainFold()
    for r in mf.records_of(data[:half]):
        mf.fold_main(f, r)
    mf.save_dir(d, f, mf.fold_meta(data, half))
    to = mf.fold_on(path, d)
    got = mf.load_dir(d)
    check("%s: the worker reads on from halfway to the fixture" % name,
          (to, got[1]["offset"], saved(got[0], data, end)),
          (end, end, want))
    was = dir_texts(d)
    check("%s: the worker with nothing new writes nothing" % name,
          (mf.fold_on(path, d), dir_texts(d)), (end, was))
    if os.path.exists(PY39):
        d = tempfile.mkdtemp(dir=WORK)
        out = subprocess.run([PY39, WORKER, "fold", path, str(len(data)), d],
                             capture_output=True, text=True)
        check("%s: the worker under %s" % (name, PY39),
              (out.returncode, out.stderr, out.stdout, dir_texts(d)),
              (0, "", "%d\n" % end, texts if end else {}))


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

    print("--- the agents' folds ---")
    for path in agent_fixtures():
        check_agent_fold(path)

    print("--- the inbox's fold ---")
    inbox = sorted(os.listdir(INBOX_STATE))
    check("there are fixture inbox entries", len(inbox) > 3, True)
    for name in inbox:
        check_inbox_entry(os.path.join(INBOX_STATE, name))
    check_inbox_counts()

    print()
    shutil.rmtree(WORK)
    line, status = tally()
    print(line)
    return status


if __name__ == "__main__":
    sys.exit(main())
