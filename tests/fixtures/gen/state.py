#!/usr/bin/env python3
"""Write the saved state of every fixture transcript's main fold.

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
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(FIXTURES))
sys.path.insert(0, ROOT)

from coding_agent_usage_line import main_fold as mf  # noqa: E402

OUT = os.path.join(FIXTURES, "state")


def transcripts():
    """Every committed fixture transcript that is a session's own, as a
    path from the repository root."""
    out = subprocess.run(["git", "ls-files", "tests/fixtures"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return sorted(f for f in out.split() if f.endswith(".jsonl")
                  and not os.path.basename(f).startswith("agent-"))


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


if __name__ == "__main__":
    main()
