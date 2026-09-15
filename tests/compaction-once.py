#!/usr/bin/env python3
"""Every compaction is reported on exactly one cost line.  Replayed.

The differential test cannot see this one.  It compares two implementations
against each other on a fixed payload, and the rule being checked here is
about a SEQUENCE of invocations: a compaction writes no usage record, gets no
Stop of its own, and is reported by the next Stop — so "exactly once" is a
property of the whole session, not of any single line.  Both programs shared
the same wrong rule, and agreed with each other perfectly while losing the row.

So this replays a real session instead.  A transcript records where every Stop
hook ran (`stop_hook_summary`) and where every compaction happened
(`compact_boundary`), which is enough to reconstruct what each Stop saw and to
say what it owed.  Each Stop is rendered twice:

  settled  everything written before that Stop's own record — the view the
           hook gets when the transcript has caught up.
  racing   the same, minus the trailing assistant records of the turn being
           reported — the view it demonstrably gets when the transcript has
           not.  This is the one that used to drop the row.

Usage:  compaction-once.py [TRANSCRIPT...]
With no arguments it finds every transcript under ~/.claude/projects that has
both a compaction and a Stop record, which is the only corpus that can
exercise this.
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

# Beside this script, since it lives in the program's own repo now.
# Overridable so a candidate — or the version before a fix — can be replayed
# without touching the installed one.
PROG = os.environ.get("COST_PROG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir,
    "coding-agent-usage-line.py")
COMPACT_ROW = "\U0001F90F"          # 🤏, the compaction label's glyph


def records(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    out.append({})
    return out


def render(lines, cut, tmp):
    """The cost line as it would print against the first `cut` records."""
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.writelines(lines[:cut])
    p = subprocess.run([sys.executable, PROG, "--mode", "cost",
                        "--cols", "200", "--transcript", tmp],
                       capture_output=True, text=True)
    try:
        msg = json.loads(p.stdout).get("systemMessage", "")
    except ValueError:
        return []
    return msg.splitlines()


def racing_cut(rows, k):
    """`k`, walked back past the tail its turn had not yet flushed.

    The records timestamped during the turn but written after the hook: the
    assistant messages, and the attachments and system records that follow
    them.  A compact_boundary is left alone — it is written when the
    compaction happens, long before the Stop that reports it.
    """
    j = k - 1
    while j > 0 and (rows[j].get("type") in ("attachment", "system")
                     and rows[j].get("subtype") != "compact_boundary"):
        j -= 1
    while j > 0 and rows[j].get("type") == "assistant":
        j -= 1
    return j + 1


def check(path, tmp):
    rows = records(path)
    stops = [i for i, r in enumerate(rows)
             if r.get("subtype") == "stop_hook_summary"
             and not r.get("isSidechain")]
    compacts = [i for i, r in enumerate(rows)
                if r.get("subtype") == "compact_boundary"]
    if not stops or not compacts:
        return None
    lines = [l for l in open(path, encoding="utf-8", errors="replace") if l.strip()]
    # A compaction BEFORE the first Stop record is not a miss.  It means the
    # hook was not running when it happened — one transcript in this corpus
    # has 19 completed turns before its first `stop_hook_summary`, from the
    # session the hook was installed during — and no line existed to report
    # it on.  The first Stop's window therefore opens at itself, and the
    # transcript is flagged rather than failed, so the case stays visible.
    pre = [c for c in compacts if c < stops[0]]
    fails = []
    for view in ("settled", "racing"):
        prev = stops[0]
        for k in stops:
            # What this Stop owes: every compaction since the previous one.
            owed = len([c for c in compacts if prev < c < k])
            cut = k if view == "settled" else racing_cut(rows, k)
            got = sum(COMPACT_ROW in l for l in render(lines, cut, tmp))
            if got != owed:
                fails.append("    %-7s Stop@%-5d owed %d, printed %d"
                             % (view, k, owed, got))
            prev = k
    return fails, pre


def main(argv):
    paths = argv[1:]
    if not paths:
        paths = sorted(glob.glob(
            os.path.expanduser("~/.claude/projects/*/*.jsonl")))
    print("=== every compaction reported exactly once ===")
    fd, tmp = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    ok = bad = skipped = 0
    try:
        for p in paths:
            fails = check(p, tmp)
            name = os.path.basename(p)[:8]
            if fails is None:
                skipped += 1
                continue
            fails, pre = fails
            if fails:
                bad += 1
                print("  FAIL  %s" % name)
                for f in fails:
                    print(f)
            else:
                ok += 1
                print("  ok%s   %s%s" % ("*" if pre else " ", name,
                      "   (%d compaction(s) predate the first Stop record — "
                      "the hook was not running yet)" % len(pre) if pre else ""))
    finally:
        os.unlink(tmp)
    print("\npass %d   fail %d   skipped %d (no compaction, or no Stop record)"
          % (ok, bad, skipped))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
