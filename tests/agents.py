#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent spend: the files beside the transcript, and where each record lands.

Claude Code writes what a subagent, a fork, or a workflow agent bills to
`<sid>/subagents/**/agent-*.jsonl` beside the session's own `.jsonl`, and
until 2026-09-11 nothing here opened those files: every readout was the main
thread calling itself the session.  These cases pin the reader and the
fold-in — which turn a record is filed under, what it adds to, and what it
must leave alone — as values with names, because "a Sonnet fork is priced at
Sonnet rates" and "🧠 did not move" are assertions, not rows to diff.

The golden suites carry the LAYOUT of the agent row; this file carries the
arithmetic under it.  Both generate their fixtures: nothing in here is a real
transcript.

Run:  python3 tests/agents.py
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(DIR, "..", "claude-code-usage-statusline.py")

pass_n = fail_n = 0


def ok(name):
    global pass_n
    pass_n += 1
    print("  ok    %s" % name)


def bad(name, detail=""):
    global fail_n
    fail_n += 1
    print("  FAIL  %s" % name)
    if detail:
        for line in str(detail).splitlines():
            print("          " + line)


def check(name, got, want):
    if got == want:
        ok(name)
    else:
        bad(name, "got  %r\nwant %r" % (got, want))


def near(name, got, want, tol=1e-9):
    if got is not None and want is not None and abs(got - want) <= tol:
        ok(name)
    else:
        bad(name, "got  %r\nwant %r" % (got, want))


def load_program():
    spec = importlib.util.spec_from_file_location("statusline", PROG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Fixture records ─────────────────────────────────────────────────────────
#
# The same minimum shapes mkcorpus-cost.py writes, plus the two fields this
# file is about: promptId on the main side's user records, and the agent
# side's user/assistant pair.

T0 = "2026-08-16T01:%02d:%02dZ"


def ts(minute, second=0):
    return T0 % (minute, second)


def prompt(minute, text, pid=None):
    r = {"type": "user", "userType": "external", "promptSource": "typed",
         "timestamp": ts(minute), "message": {"content": text}}
    if pid:
        r["promptId"] = pid
    return r


def queued(minute, text):
    """A prompt delivered from the queue: opens a turn, carries no promptId."""
    return {"type": "queue-operation", "operation": "remove",
            "timestamp": ts(minute), "content": text}


def tool_result(minute, pid=None):
    r = {"type": "user", "userType": "external", "timestamp": ts(minute),
         "message": {"content": [{"type": "tool_result", "content": "ok"}]}}
    if pid:
        r["promptId"] = pid
    return r


def answer(minute, rid, fresh, cw, cr, out, model=None, second=0):
    r = {"type": "assistant", "requestId": rid,
         "timestamp": ts(minute, second), "isSidechain": False,
         "message": {"id": rid, "usage": {
             "input_tokens": fresh,
             "cache_creation_input_tokens": cw,
             "cache_read_input_tokens": cr,
             "output_tokens": out}}}
    if model:
        r["message"]["model"] = model
    return r


def agent_user(minute, pid):
    """The record that opens or resumes an agent, and the one place the
    turn's promptId is written on the agent's side."""
    return {"type": "user", "isSidechain": True, "promptId": pid,
            "timestamp": ts(minute), "message": {"content": "do a thing"}}


def agent_answer(minute, rid, fresh, cw, cr, out, model="claude-opus-5",
                 second=0):
    r = answer(minute, rid, fresh, cw, cr, out, model, second)
    r["isSidechain"] = True
    return r


def boundary(minute, pre, ms):
    return {"type": "system", "subtype": "compact_boundary",
            "timestamp": ts(minute),
            "compactMetadata": {"trigger": "auto", "preTokens": pre,
                                "postTokens": 8737, "durationMs": ms}}


def stop(minute):
    return {"type": "system", "subtype": "stop_hook_summary",
            "timestamp": ts(minute), "isSidechain": False}


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def session(root, name, main, agents=(), workflow=()):
    """A transcript and its agent files, laid out as Claude Code lays them.

    `agents` and `workflow` are (basename, records) pairs; the second goes
    under `subagents/workflows/wf_x/`, which is the other depth the reader
    has to find.  Every agent file gets a sidecar because every real one
    has one.
    """
    tr = os.path.join(root, name + ".jsonl")
    write_jsonl(tr, main)
    sub = os.path.join(root, name, "subagents")
    for base, recs in agents:
        write_jsonl(os.path.join(sub, base + ".jsonl"), recs)
        with open(os.path.join(sub, base + ".meta.json"), "w") as fh:
            json.dump({"agentType": "general-purpose", "spawnDepth": 1}, fh)
    for base, recs in workflow:
        d = os.path.join(sub, "workflows", "wf_x")
        write_jsonl(os.path.join(d, base + ".jsonl"), recs)
        with open(os.path.join(d, base + ".meta.json"), "w") as fh:
            json.dump({"agentType": "workflow-subagent", "spawnDepth": 1}, fh)
    return tr


def main():
    os.environ["TZ"] = "UTC"
    if hasattr(os, "tzset"):
        os.tzset()
    tmp = tempfile.mkdtemp(prefix="statusline-agents.")
    try:
        return run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(tmp):
    sl = load_program()
    OPUS = sl._price("claude-opus-5")
    SONNET = sl._price("claude-sonnet-5")
    check("the price rows resolve most specific first",
          (sl._price("claude-fable-5-1")[2], sl._price("claude-fable-5")[2],
           sl._price("claude-sonnet-5")[0], sl._price("claude-sonnet-4-6")[0],
           sl._price(None)),
          (0.25e-6, 1e-6, 2e-6, 3e-6, OPUS))

    print("--- the reader ---")
    tr = session(tmp, "reader", [prompt(10, "go", "p1")], agents=[
        ("agent-a1", [
            agent_user(10, "p1"),
            agent_answer(11, "a1-r1", 100, 200, 300, 40),
            agent_answer(11, "a1-r1", 100, 200, 300, 40, second=30),  # retry
            agent_answer(12, "a1-err", 0, 0, 0, 0),           # API error
            agent_user(20, "p2"),                             # resumed later
            agent_answer(21, "a1-r2", 10, 20, 30, 4),
        ]),
    ], workflow=[
        ("agent-w1", [agent_user(15, "wf-own-id"),
                      agent_answer(16, "w1-r1", 1, 2, 3, 4)]),
    ])
    recs = sl.agent_records(tr)
    check("both depths found, retry and error skipped",
          [r.request_id for r in recs], ["a1-r1", "w1-r1", "a1-r2"])
    check("promptId carried per record, not per file",
          [r.prompt_id for r in recs], ["p1", "wf-own-id", "p2"])
    check("offsets are byte positions after each record's line",
          [open(r.path, "rb").read(r.offset).count(b"\n") for r in recs],
          [2, 2, 6])
    check("no subagents directory reads as nothing",
          sl.agent_records(session(tmp, "bare", [prompt(10, "x")])), ())
    check("read_turns takes the reading it is handed",
          sl.read_turns(tr, recs)[0].agent_calls, 3)

    print("--- the fold-in ---")
    # Two prompts.  An agent under the first, resolved through the TOOL
    # RESULT that carries its promptId, keeps billing after the second
    # prompt opened — and stays on the first.  A Sonnet fork under the
    # second, priced at Sonnet rates.
    tr = session(tmp, "fold", [
        prompt(10, "first", "p1"),
        answer(11, "m1", 1000, 0, 50000, 500),
        tool_result(12, "p1"),
        stop(13),
        prompt(20, "second", "p2"),
        answer(21, "m2", 1000, 0, 60000, 500),
    ], agents=[
        ("agent-a1", [agent_user(11, "p1"),
                      agent_answer(12, "a1", 100, 0, 1000, 10),
                      agent_answer(22, "a2", 100, 0, 1000, 10)]),
        ("agent-a2", [agent_user(21, "p2"),
                      agent_answer(22, "s1", 100, 0, 1000, 10,
                                   model="claude-sonnet-5")]),
    ])
    t1, t2, late = sl.read_turns(tr)
    check("agent tokens sum into the spawning turn",
          (t1.fresh, t1.cache_read, t1.out), (1100, 51000, 510))
    check("a record after the spawning turn's Stop is late, not the "
          "next prompt's", (t1.agent_calls, t2.agent_calls, late.agent_calls),
          (1, 1, 1))
    check("the late turn is what its name says",
          (late.agent, late.calls, late.ctx, late.reported, late.text),
          (True, 0, 0, False, "agents (other)"))
    check("calls stays the main thread's", (t1.calls, t2.calls), (1, 1))
    check("ctx is the main thread's reading", (t1.ctx, t2.ctx),
          (51000, 61000))
    near("the Sonnet fork is priced at Sonnet rates",
         sl.turn_cost(t2),
         1000 * OPUS[0] + 60000 * OPUS[2] + 500 * OPUS[1]
         + 100 * SONNET[0] + 1000 * SONNET[2] + 10 * SONNET[1])
    near("parts total turn_cost exactly", sum(c for _, c in t2.parts),
         sl.turn_cost(t2))
    check("turn_shares divides dollars by dollars",
          sl.turn_shares(t2),
          (int(round(100 * (60000 * OPUS[2] + 1000 * SONNET[2])
                     / sl.turn_cost(t2))), 0))
    check("the turn's end is not moved by an agent",   # 10:00 to the Stop
          round(t1.dur_s), 180)                          # at 13:00, not 22:00

    # Status-line side: the totals move, the reading does not.
    st = sl.read_transcript(tr)
    check("status 🧩 counts agents",
          (st.tok_up, st.tok_down),
          (int(2300 + 0.1 * (50000 + 60000 + 3000)), 1030))
    check("status 🧠 does not", st.ctx_tokens, 61000)

    print("--- the fallback ---")
    # No promptId anywhere on the main side: the stamp decides, and a
    # compaction turn open at that stamp is skipped for the prompt before it.
    tr = session(tmp, "fallback", [
        answer(5, "early", 1, 0, 1, 1),        # before any turn: dropped
        prompt(10, "first"),
        answer(11, "m1", 1000, 0, 50000, 500),
        boundary(12, 292645, 41000),
        answer(13, "m1b", 1000, 0, 9000, 500),  # lands on the compaction
        prompt(20, "second"),
        answer(21, "m2", 1000, 0, 60000, 500),
    ], agents=[
        ("agent-a1", [agent_user(11, "nobody-has-this"),
                      agent_answer(13, "a1", 100, 0, 1000, 10),
                      agent_answer(21, "a2", 100, 0, 1000, 10, second=30)]),
        ("agent-a0", [agent_user(4, "x"),
                      agent_answer(4, "a0", 100, 0, 1000, 10)]),
    ])
    turns = sl.read_turns(tr)
    # "first" shares its (absent) Stop with "second", so its record goes on
    # the 👥 row; what matters here is that it did NOT land on the
    # compaction turn open at its stamp.
    check("turn shapes", [(t.text[:8], t.compact, t.calls, t.agent_calls)
                          for t in turns],
          [("first", False, 1, 0), ("/compact", True, 2, 0),
           ("agents (", False, 0, 1), ("second", False, 1, 1)])
    check("a record before every turn is dropped",
          sum(t.agent_calls for t in turns), 2)
    check("a queued prompt resolves through its tool result",
          [t.agent_calls for t in sl.read_turns(session(tmp, "queued", [
              prompt(10, "typed", "p1"),
              answer(11, "m1", 10, 0, 100, 5),
              queued(20, "from the queue"),
              answer(21, "m2", 10, 0, 100, 5),
              tool_result(22, "p2"),
          ], agents=[("agent-q", [agent_user(21, "p2"),
                                  agent_answer(22, "q1", 1, 0, 1, 1)])]))],
          [0, 1])

    print("--- the late row ---")
    # One agent under the first prompt that keeps billing after that
    # prompt's Stop.  Three Stops read the same session, each at the cut the
    # live hook sees — before its own Stop record is written — and each
    # publishing where it got to, the way the live hook does.  The late
    # record must print at the second and not the third.
    main = [
        prompt(10, "first", "p1"),
        answer(11, "m1", 1000, 0, 50000, 500),
        stop(12),
        prompt(20, "second", "p2"),
        answer(21, "m2", 1000, 0, 60000, 500),
        stop(22),
        prompt(30, "third", "p3"),
        answer(31, "m3", 1000, 0, 70000, 500),
    ]
    agent = [agent_user(11, "p1"),
             agent_answer(11, "a1", 100, 0, 1000, 10, second=30),
             agent_answer(21, "a2", 100, 0, 1000, 10, second=30)]
    os.environ["TMPDIR"] = tmp
    tr = session(tmp, "late", main[:2], agents=[("agent-a", agent[:2])])
    recs = sl.agent_records(tr)
    turns = sl.read_turns(tr, recs)
    check("first Stop: nothing is late",
          [(t.text[:6], t.agent_calls) for t in turns], [("first", 1)])
    sl.publish_agent_offsets(tr, recs)
    check("the state file holds the extent reported",
          sl.agent_offsets(tr), {recs[0].path: recs[0].offset})

    tr = session(tmp, "late", main[:5], agents=[("agent-a", agent)])
    recs = sl.agent_records(tr)
    turns = sl.read_turns(tr, recs)
    check("second Stop: the new record is late, and the spawning turn "
          "does not also carry it",
          [(t.text[:6], t.agent_calls, t.agent) for t in turns],
          [("first", 1, False), ("second", 0, False),
           ("agents", 1, True)])
    check("the late turn sits at its record's stamp",
          sl.ts_epoch(turns[2].ts), sl.ts_epoch(ts(21, 30)))
    late = turns[2]
    sl.publish_agent_offsets(tr, recs)

    tr = session(tmp, "late", main[:8], agents=[("agent-a", agent)])
    turns = sl.read_turns(tr)
    check("third Stop: reported once, now back on its turn for the totals",
          [(t.text[:6], t.agent_calls, t.agent) for t in turns],
          [("first", 2, False), ("second", 0, False), ("third", 0, False)])

    # Without the state file the stamp decides: after the last Stop record
    # is late, before it is taken as reported.
    os.remove(sl._agent_state_path(tr))
    check("stamp fallback: a record before the last Stop is not late",
          [t.agent for t in sl.read_turns(tr)], [False, False, False])
    tr = session(tmp, "late", main[:5], agents=[("agent-a", agent)])
    check("stamp fallback: a record after the last Stop is",
          [t.agent for t in sl.read_turns(tr)], [False, False, True])
    check("a record under the CURRENT turn is never late",
          [t.agent_calls for t in sl.read_turns(session(
              tmp, "current", main[:4] + [answer(21, "m2", 1, 0, 1, 1)],
              agents=[("agent-b", [agent_user(21, "p2"),
                                   agent_answer(25, "b1", 1, 0, 1, 1)])]))],
          [0, 1])

    # A turn that shares its Stop with a later one never gets a 🎤 row; its
    # agent spend goes on the 👥 row at that Stop rather than on no row.
    check("agents of a turn the 🎤 row will not report go on the 👥 row",
          [(t.text[:6], t.agent_calls, t.agent) for t in sl.read_turns(
              session(tmp, "shared", [
                  prompt(10, "first", "p1"),
                  answer(11, "m1", 10, 0, 100, 5),
                  queued(12, "queued while running"),
                  answer(13, "m2", 10, 0, 100, 5),
              ], agents=[("agent-c", [agent_user(11, "p1"),
                                      agent_answer(11, "c1", 1, 0, 1, 1,
                                                   second=30)])]))],
          [("first", 0, False), ("agents", 1, True),
           ("queued", 0, False)])

    # The settle wait looks past the synthetic turn to the live one.
    check("the settle test ignores the agents turn",
          (sl._settled(sl.read_turns(tr)),
           sl._settled(tuple(t._replace(calls=0) for t in sl.read_turns(tr)))),
          (True, False))

    # And the rendered rows: the label, and the blanks in ⌛ and 📅.
    calib = {"sess": 5.5, "week": 4.1}
    row = sl.strip_ansi(sl.cost_group(late, calib, sl.CTX_1M, sl.PLAIN_INK,
                                      1786847000.0))
    check("agents row blanks its clock and date",
          (sl.S_WORK + "+" in row, "2026-08-16" in row), (False, False))
    opts = sl.CostOpts(prefix="P", label="L", totals_label="T", cols=0,
                       colour=False, totals=True, right_align=False,
                       agents_label="A")
    lines = sl.strip_ansi(sl.render_cost_line(sl.read_turns(tr), opts,
                                              1786847000.0))
    check("the agents row is labelled and leads the block",
          [l.strip()[:3] for l in lines.split("\n")],
          ["P A", "", "P L", "P T"])

    print("--- the calibration scan ---")
    # A scratch projects tree: one main file, one agent beside it, one
    # workflow agent, and one file aged out by the cutoff.  Each admitted
    # request counts once.
    root = os.path.join(tmp, "projects")
    proj = os.path.join(root, "-proj")
    session(proj, "s1", [prompt(10, "x"), answer(11, "m1", 0, 0, 0, 1000)],
            agents=[("agent-a", [agent_user(10, "p"),
                                 agent_answer(12, "a", 0, 0, 0, 1000),
                                 agent_answer(12, "m1", 0, 0, 0, 1000)])],
            workflow=[("agent-w", [agent_user(10, "w"),
                                   agent_answer(12, "w", 0, 0, 0, 1000)])])
    old = session(proj, "old", [prompt(10, "x"),
                                answer(11, "old", 0, 0, 0, 1000)])
    os.utime(old, (0, 0))
    sl.PROJECTS_DIR = root
    from datetime import datetime
    sess, week = sl._window_costs(datetime(2026, 8, 16, 1, 11, 30),
                                  datetime(2026, 8, 1))
    near("week: main + agent + workflow, retry and aged file excluded",
         week, 3000 * OPUS[1])
    near("session window splits per record", sess, 2000 * OPUS[1])

    print()
    print("pass %d   fail %d" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
