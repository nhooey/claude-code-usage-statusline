#!/usr/bin/env python3
"""Every agent request is reported on at most one cost row, and on exactly
one where a row could carry it.  Replayed against real sessions.

The sibling of compaction-once.py, for the other late-reported spend.  An
agent's records live in files beside the transcript and can land after the
turn that spawned them has printed; the program files those on a 👥 row at
the next Stop and keeps a per-session state file saying how far into each
agent file it has reported.  Whether that adds up to "once" is a property of
the whole sequence of Stops, so it is checked by replaying one.

Each Stop record in the main transcript is a point where the hook ran.  The
replay reconstructs what that hook saw — the main file up to the Stop record,
and each agent file up to the last record stamped before it — reads the turns
in-process, notes which agent requests are on a row that prints (the 🎤 turn,
or a 👥 turn), publishes the state file the way the hook does, and moves on.

What is asserted, per agent request: on a 🎤 or 👥 row at the Stop that
first saw it, and on a 👥 row at no later Stop.  The first half is what the
👥 row exists for — a turn that shares its Stop with a later one gets no 🎤
row, and before the 👥 rule was widened to cover that, 766 of 766 requests
in one workflow session printed nowhere.  The second half is the state file
doing its job.

Usage:  agents-once.py [TRANSCRIPT...]
With no arguments it finds every transcript under ~/.claude/projects that has
a subagents directory and a Stop record.  Rows print money, not ids, so the
check is on read_turns directly — the program is imported, not run.
"""
import glob
import importlib.util
import json
import os
import shutil
import sys
import tempfile

PROG = os.environ.get("COST_PROG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir,
    "coding-agent-usage-line.py")


def load_program():
    global _agent_dir, _agent_state_path, ts_epoch
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from coding_agent_usage_line import claude
    from coding_agent_usage_line.claude_records import _agent_dir, _agent_state_path, ts_epoch
    return claude


def find_sessions():
    out = []
    for tr in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        sub = os.path.join(tr[:-len(".jsonl")], "subagents")
        if not os.path.isdir(sub):
            continue
        with open(tr, encoding="utf-8", errors="replace") as fh:
            if any('"stop_hook_summary"' in line for line in fh):
                out.append(tr)
    return sorted(out)


def replay(sl, transcript, work):
    """One session.  Returns (requests, twice, never)."""
    lines = open(transcript, encoding="utf-8", errors="replace").readlines()
    stops = []
    for i, line in enumerate(lines):
        if '"stop_hook_summary"' not in line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("subtype") == "stop_hook_summary" and not r.get("isSidechain"):
            stops.append((i, ts_epoch(r.get("timestamp") or "")))
    # Every agent file, parsed once, with each line's stamp.
    src = sl.agent_files(transcript)
    agent_lines = {}
    for path in src:
        rel = os.path.relpath(path, _agent_dir(transcript))
        rows = []
        with open(path, "rb") as fh:
            for raw in fh:
                try:
                    r = json.loads(raw)
                except ValueError:
                    r = {}
                rows.append((ts_epoch((r.get("timestamp") or "")
                                         if isinstance(r, dict) else ""), raw))
        agent_lines[rel] = rows

    sid = os.path.basename(transcript)[:-len(".jsonl")]
    cut_tr = os.path.join(work, sid + ".jsonl")
    cut_dir = os.path.join(work, sid, "subagents")
    printed = {}        # requestId → number of Stops that printed it
    seen_ids = set()
    unreportable = set()
    late_seen = {}      # requestId → the Stops at which it sat on a 👥 turn
    for i, stop_epoch in stops:
        # What the hook saw: the main file before its own Stop record, and
        # each agent file up to the last record stamped before the Stop.
        with open(cut_tr, "w", encoding="utf-8") as fh:
            fh.writelines(lines[:i])
        if os.path.isdir(cut_dir):
            shutil.rmtree(cut_dir)
        for rel, rows in agent_lines.items():
            keep = [raw for ep, raw in rows
                    if ep is not None and stop_epoch is not None
                    and ep <= stop_epoch]
            if not keep:
                continue
            p = os.path.join(cut_dir, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.writelines(keep)
        agents = sl.agent_records(cut_tr)
        turns = sl.read_turns(cut_tr, agents)
        # The rows that print at this Stop: the 🎤 turn and every 👥 turn.
        # A request new to this Stop is on one of them or on no row at all.
        prompts = [t for t in turns if t.calls and not t.compact
                   and not t.agent]
        rows = [t for t in turns if t.agent] + prompts[-1:]
        on_rows = set(rid for t in rows for rid in t.agent_ids)
        for a in agents:
            rid = a.request_id
            if rid in seen_ids:
                # Seen by an earlier Stop.  It may still sit on `last` if
                # that turn is being reported again (a Stop that could not
                # see its own prompt) — that is the main thread's existing
                # double-report, not this feature's, and is not counted.
                continue
            seen_ids.add(rid)
            if rid in on_rows:
                printed[rid] = printed.get(rid, 0) + 1
            else:
                unreportable.add(rid)
        # A request on a 👥 turn at two Stops is the double print this
        # test exists to catch: the row is built only from records no Stop
        # has seen, so a second appearance means the state file lied.
        for t in turns:
            if t.agent:
                for rid in t.agent_ids:
                    late_seen.setdefault(rid, set()).add(i)
        sl.publish_agent_offsets(cut_tr, agents)
    try:
        os.remove(_agent_state_path(cut_tr))
    except OSError:
        pass
    twice = [k for k, at in late_seen.items() if len(at) > 1]
    never = sorted(unreportable)
    return len(seen_ids), twice, never


def main(argv):
    sl = load_program()
    paths = argv[1:] or find_sessions()
    if not paths:
        print("no session with agents and a Stop record found")
        return 0
    work = tempfile.mkdtemp(prefix="agents-once.")
    os.environ["TMPDIR"] = work
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = os.path.join(work, "state")
    bad = 0
    try:
        for tr in paths:
            n, twice, never = replay(sl, tr, work)
            tag = "ok  " if not (twice or never) else "FAIL"
            if twice or never:
                bad += 1
            print("  %s  %-40s  %5d requests  twice %d  never %d"
                  % (tag, os.path.basename(tr)[:40], n, len(twice),
                     len(never)))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("\nsessions %d   fail %d" % (len(paths), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
