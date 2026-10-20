#!/usr/bin/env python3
"""Write the saved state of every fixture transcript's main fold, and of
every fixture agent's fold.

    python3 tests/fixtures/gen/state.py

tests/fixtures/state/<path>.json, for each committed transcript that is a
session's own (not an agent's), holds the texts a first save of its whole
fold writes, as main_fold.fold_save writes them, with the format they were
written under:

    {"format": N, "transcript": PATH, "parts": [TEXT, ...], "head": TEXT}

tests/fold.py and mod/test/main_fold.test.ts save each fold again and fail
where the text differs while spec/state.jsonc's "main-fold" format is still
the fixture's: a change to either fold, or to what is saved of it, cannot
land without a new format, and the two ports cannot drift apart.  Bump the
format, then run this.

tests/fixtures/agent-state/<path>.json, for each committed agent
transcript, holds the text agent_fold.fold_text writes of its fold at each
line end K, as a first save writes it, under spec/state.jsonc's
"agent-fold" format:

    {"format": N, "agent": PATH, "texts": [[K, TEXT], ...]}

tests/fold.py and mod/test/agent_fold.test.ts check both ports write each
byte for byte, and read each back on to the last.

tests/fixtures/inbox-state/<path>.json, for each committed transcript that
holds an inbox mark (claude_records.SEND_QUEUED_MARK or INBOX_MARKS), holds
the text inbox_fold.entry_text writes of its entry at each line end K,
folded from the start with no mtime, under spec/state.jsonc's "inbox-fold"
format; `main` for a session's own transcript, whose deliveries are not
folded:

    {"format": N, "file": PATH, "main": BOOL, "texts": [[K, TEXT], ...]}

tests/fold.py and mod/test/inbox_fold.test.ts check both ports write each
byte for byte, and read each back on to the last.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(FIXTURES))
sys.path.insert(0, ROOT)

from coding_agent_usage_line import agent_fold as af  # noqa: E402
from coding_agent_usage_line import claude_records as cr  # noqa: E402
from coding_agent_usage_line import inbox_fold as ib  # noqa: E402
from coding_agent_usage_line import main_fold as mf  # noqa: E402

OUT = os.path.join(FIXTURES, "state")
AGENT_OUT = os.path.join(FIXTURES, "agent-state")
INBOX_OUT = os.path.join(FIXTURES, "inbox-state")


def committed():
    out = subprocess.run(["git", "ls-files", "tests/fixtures"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split() if f.endswith(".jsonl")]


def transcripts():
    """Every committed fixture transcript that is a session's own, as a
    path from the repository root."""
    return sorted(f for f in committed()
                  if not os.path.basename(f).startswith("agent-"))


def agents():
    """Every committed fixture agent transcript, as a path from the
    repository root."""
    return sorted(f for f in committed()
                  if os.path.basename(f).startswith("agent-"))


def agent_texts(path: str) -> dict:
    """The text of `path`'s fold at each line end, as a first save writes
    it."""
    with open(os.path.join(ROOT, path), "rb") as fh:
        data = fh.read()
    f, at, texts = cr.AgentFold(), 0, []
    for k in mf.line_ends(data):
        cr.fold_agent_bytes(f, data[at:k])
        at = k
        texts.append([k, af.fold_text(f, 1, af.tail_digest(
            data[max(0, k - af.FOLD_CHECK_BYTES):k]))])
    return {"format": af.AGENT_FOLD_FORMAT, "agent": path, "texts": texts}


def inbox_files():
    """Every committed fixture transcript holding an inbox mark, as a path
    from the repository root."""
    marks = (cr.SEND_QUEUED_MARK,) + tuple(cr.INBOX_MARKS)
    out = []
    for f in sorted(committed()):
        with open(os.path.join(ROOT, f), "rb") as fh:
            data = fh.read()
        if any(m in data for m in marks):
            out.append(f)
    return out


def inbox_texts(path: str) -> dict:
    """The text of `path`'s inbox entry at each line end, folded from the
    start."""
    with open(os.path.join(ROOT, path), "rb") as fh:
        data = fh.read()
    main = not os.path.basename(path).startswith("agent-")
    e, at, texts = ib.Entry(), 0, []
    for k in mf.line_ends(data):
        ib.fold_entry(e, data[at:k], main)
        at = k
        e.tail = ib.tail_digest(data[max(0, k - ib.FOLD_CHECK_BYTES):k])
        texts.append([k, ib.entry_text(path, e)])
    return {"format": ib.INBOX_FOLD_FORMAT, "file": path, "main": main,
            "texts": texts}


def fixture_name(path: str) -> str:
    """tests/fixtures/a/b.jsonl's fixture: a--b.jsonl.json."""
    return os.path.relpath(path, "tests/fixtures").replace("/", "--") \
        + ".json"


def saved(path: str) -> dict:
    """A first save of `path`'s whole fold, to its last newline."""
    with open(os.path.join(ROOT, path), "rb") as fh:
        data = fh.read()
    end = data.rfind(b"\n") + 1
    f = mf.MainFold()
    for r in mf.records_of(data[:end]):
        mf.fold_main(f, r)
    parts, head, _slot, _mark = mf.fold_save(f, mf.fold_meta(data, end))
    return {"format": mf.MAIN_FOLD_FORMAT, "transcript": path,
            "parts": [t for _, t in parts], "head": head}


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    for path in transcripts():
        with open(os.path.join(OUT, fixture_name(path)), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(saved(path), ensure_ascii=False, indent=1)
                     + "\n")
    print("state/  %d saved folds" % len(transcripts()))
    os.makedirs(AGENT_OUT, exist_ok=True)
    for f in os.listdir(AGENT_OUT):
        os.remove(os.path.join(AGENT_OUT, f))
    for path in agents():
        with open(os.path.join(AGENT_OUT, fixture_name(path)), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(agent_texts(path), ensure_ascii=False,
                                indent=1) + "\n")
    print("agent-state/  %d agents' folds" % len(agents()))
    os.makedirs(INBOX_OUT, exist_ok=True)
    for f in os.listdir(INBOX_OUT):
        os.remove(os.path.join(INBOX_OUT, f))
    files = inbox_files()
    for path in files:
        with open(os.path.join(INBOX_OUT, fixture_name(path)), "w",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(inbox_texts(path), ensure_ascii=False,
                                indent=1) + "\n")
    print("inbox-state/  %d files' inbox folds" % len(files))


if __name__ == "__main__":
    main()
