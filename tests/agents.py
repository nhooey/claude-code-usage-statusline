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
import time

DIR = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(DIR, "..", "coding-agent-usage-line.py")

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
    global _agent_state_path, _settled
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path: sys.path.insert(0, root)
    from coding_agent_usage_line import claude
    from coding_agent_usage_line.claude_records import _agent_state_path, _settled
    return claude


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
    return {"type": "user", "userType": "external", "isSidechain": True,
            "promptId": pid, "timestamp": ts(minute),
            "message": {"content": "do a thing"}}


def agent_answer(minute, rid, fresh, cw, cr, out, model="claude-opus-5",
                 second=0):
    r = answer(minute, rid, fresh, cw, cr, out, model, second)
    r["isSidechain"] = True
    return r


def calls(minute, rid, *ids, **kw):
    """An assistant record that asks for tools: one tool_use block per id."""
    r = answer(minute, rid, 1, 0, 0, 1, second=kw.get("second", 0))
    r["message"]["content"] = [{"type": "tool_use", "id": i, "name": "Bash"}
                               for i in ids]
    return r


def asks(minute, rid, *ids, **kw):
    """The same, for a tool that is a QUESTION put to the user.  Its span is
    somebody reading, which is why \U0001F527 does not want it."""
    r = calls(minute, rid, *ids, **kw)
    for b in r["message"]["content"]:
        b["name"] = "AskUserQuestion"
    return r


def delegates(minute, rid, *ids, **kw):
    """The same, for a tool that starts an AGENT.  Its span is another
    thread working, which is the caller's \U0001F6A6 and not its \U0001F527."""
    r = calls(minute, rid, *ids, **kw)
    for b in r["message"]["content"]:
        b["name"] = "Agent"
    return r


def result(minute, *ids, **kw):
    """The results that answer them, by id.  A turn ends on one of these, so
    the shape is the tool_result shape is_work already knows: a LIST."""
    return {"type": "user", "userType": "external",
            "timestamp": ts(minute, kw.get("second", 0)),
            "message": {"content": [{"type": "tool_result", "tool_use_id": i,
                                     "content": "ok"} for i in ids]}}


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
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = os.path.join(tmp, "state")
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

    print("--- the reader's cache ---")
    from coding_agent_usage_line import claude_records as cr
    old = time.time() - 60
    for p in sl.agent_files(tr):
        os.utime(p, (old, old))
    first = sl.agent_records(tr)
    with open(cr._agent_cache_path(tr)) as fh:
        kept = sorted(json.load(fh)["files"])
    check("settled files are kept, and a kept reading is the reading",
          (kept, sl.agent_records(tr), first),
          (sl.agent_files(tr), recs, recs))
    a1 = os.path.join(tmp, "reader", "subagents", "agent-a1.jsonl")
    with open(a1, "a") as fh:
        fh.write(json.dumps(agent_answer(30, "a1-r3", 1, 1, 1, 1),
                            sort_keys=True) + "\n")
    os.utime(a1, (old + 30, old + 30))
    check("a file that changed since it was kept is read again",
          [r.request_id for r in sl.agent_records(tr)],
          ["a1-r1", "w1-r1", "a1-r2", "a1-r3"])
    live = session(tmp, "live", [prompt(10, "go", "p1")], agents=[
        ("agent-b1", [agent_user(10, "p1"),
                      agent_answer(11, "b1-r1", 1, 1, 1, 1)])])
    b1 = sl.agent_files(live)[0]
    sl.agent_records(live)
    stamp = os.stat(b1).st_mtime_ns
    write_jsonl(b1, [agent_user(10, "p1"),
                     agent_answer(11, "b1-r2", 1, 1, 1, 1)])
    os.utime(b1, ns=(stamp, stamp))
    check("a file written moments ago is not kept: a rewrite of the same "
          "size inside the clock's granularity still reads",
          [r.request_id for r in sl.agent_records(live)], ["b1-r2"])

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

    print("--- the clock is the main thread's own ---")
    # The main thread answers for a minute and then waits: everything after
    # is the agents working, on their own rows, and the main thread waiting
    # on them, which is its \U0001F6A6.
    busy = session(tmp, "busy", [prompt(10, "go", "p1"),
                                 answer(11, "m1", 10, 0, 0, 10),
                                 tool_result(11, "p1")], agents=[
        ("agent-a1", [agent_user(11, "p1"),
                      agent_answer(40, "b-a1", 10, 0, 0, 10)]),
        ("agent-a2", [agent_user(20, "p1"),            # overlaps a1
                      agent_answer(50, "b-a2", 10, 0, 0, 10)]),
        ("agent-a3", [agent_user(52, "p1"),            # after both, with a
                      agent_answer(55, "b-a3", 10, 0, 0, 10),   # gap before
                      agent_user(57, "p2"),            # resumed by a later
                      agent_answer(59, "b-a4", 10, 0, 0, 10)]), # turn
    ])
    check("its busy clock is its one minute, whether or not the agents' "
          "files are read: their work is on their rows",
          [round(sl.read_transcript(busy, a).busy_s) for a in (None, ())],
          [60, 60])
    check("overlapping spans merge and disjoint ones add",
          (sl.union_seconds(((0, 10), (5, 20), (30, 40))),
           sl.union_seconds(()), sl.union_seconds(((7, 7), (9, 3)))),
          (30.0, 0.0, 0.0))
    b = sl.read_transcript(busy)
    check("and never outruns the age it is a part of",
          b.busy_s <= sl.ts_epoch(ts(59)) - b.start_s, True)

    print("--- time inside a tool ---")
    # Two calls asked for at once and answered out of order.  Pairing them
    # off in file order would hand each the other's end, which is why
    # scan_tool_spans matches on the id and nothing else.
    tt = session(tmp, "tools", [
        prompt(10, "go", "p1"),
        calls(11, "m1", "t1", "t2"),
        result(16, "t2"),                   # 11 -> 16, five minutes
        result(13, "t1"),                   # 11 -> 13, two, INSIDE it
        calls(20, "m2", "t3"),
        result(22, "t3"),                   # 20 -> 22, disjoint
        result(23, "t9"),                   # answers nothing this file saw
    ])
    recs = list(sl._records(tt))
    check("three calls pair by id; the fourth result names no call and is "
          "not one", len(sl.tool_spans(recs)), 3)
    check("and the spans union rather than sum: 11-16 swallows 11-13",
          round(sl.union_seconds(sl.tool_spans(recs)) / 60), 5 + 2)

    # A Task's span covers its agent's whole run, so the agent's own tools
    # are already inside it.  A BACKGROUND agent's are not: its result comes
    # back at once and it keeps working after.
    nest = session(tmp, "nest", [
        prompt(10, "go", "p1"),
        calls(11, "m1", "t1"),
        result(40, "t1"),                   # a Task that waited: 11 -> 40
        calls(12, "m2", "t2"),
        result(12, "t2", second=30),        # a background dispatch: 30s
    ], agents=[
        ("agent-a1", [agent_user(11, "p1"), calls(20, "b1", "u1"),
                      result(30, "u1"),
                      agent_answer(35, "b2", 10, 0, 0, 10)]),
        ("agent-a2", [agent_user(12, "p1"), calls(50, "c1", "u2"),
                      result(58, "u2"),
                      agent_answer(59, "c2", 10, 0, 0, 10)]),
    ])
    check("an agent's tools are on its row, foreground or background: the "
          "main thread's \U0001F527 is what its own file pairs",
          [round(sl.read_transcript(nest, a).tool_s / 60) for a in (None, ())],
          [29, 29])
    check("and tool time never outruns the busy clock it is a part of",
          (lambda t: t.tool_s <= t.busy_s)(sl.read_transcript(nest)), True)
    check("no transcript, no tool time", sl.EMPTY_TRANSCRIPT.tool_s, 0.0)

    # A question put to the user is a tool call in the transcript and a
    # person reading in fact.  It comes out of \U0001F527 and, at the row, out of
    # \U0001F916 and into \U0001F6A6 -- see BLOCKING_TOOLS.
    ask = session(tmp, "ask", [
        prompt(10, "go", "p1"),
        calls(11, "m1", "t1"),
        result(15, "t1"),                   # a real tool: four minutes
        asks(20, "m2", "q1"),
        result(29, "q1"),                   # a question: nine, and not \U0001F527's
        calls(40, "m3", "t2"),
        asks(41, "m4", "q2"),               # a question INSIDE a tool span,
        result(44, "q2"),                   #   which is what the subtraction
        result(50, "t2"),                   #   of two unions is for: 40-50
    ])
    t = sl.read_transcript(ask)
    check("the question is not tool time; the two real calls are, and the "
          "one a question ran through keeps only the rest of itself",
          round(t.tool_s / 60), 4 + (10 - 3))
    check("and both questions are reported on their own, in whole",
          round(t.blocked_s / 60), 9 + 3)
    check("a blocking prompt is still work to every other reader, so the "
          "busy clock keeps it", round(t.busy_s / 60), 40)
    check("no blocking prompt, nothing to report",
          sl.read_transcript(nest).blocked_s, 0.0)

    # An Agent call is the caller waiting on another thread: out of
    # \U0001F527 and into the waiting subset, as a question is.
    dl = session(tmp, "delegate", [
        prompt(10, "go", "p1"),
        calls(11, "m1", "t1"),
        result(15, "t1"),                   # a real tool: four minutes
        delegates(20, "m2", "a1"),
        result(50, "a1"),                   # an agent: thirty, and waiting
    ])
    t = sl.read_transcript(dl)
    check("an agent the thread started is waiting, not tool time, and the "
          "busy clock still holds both",
          (round(t.tool_s / 60), round(t.blocked_s / 60), round(t.busy_s / 60)),
          (4, 30, 40))
    live = session(tmp, "inflight", [
        prompt(10, "go", "p1"), calls(11, "m1", "t1"), delegates(12, "m2", "a1")])
    check("a call still waiting on its result runs to now on a live session, "
          "and not on an offline read; where the two overlap, waiting wins, "
          "as a question inside a tool does",
          [(round(x.tool_s / 60), round(x.blocked_s / 60)) for x in (
              sl.read_transcript(live, (), now=sl.ts_epoch(ts(20))),
              sl.read_transcript(live, ()))],
          [(1, 8), (0, 0)])
    check("net_tool_seconds subtracts measures, not intervals: a subset "
          "that straddles two spans still comes out once",
          sl.net_tool_seconds(((0, 10), (20, 30)), ((5, 8),)), 17.0)
    check("and never goes below zero",
          sl.net_tool_seconds(((0, 1),), ((0, 9),)), 0.0)

    # \U0001F4BB and \U0001F4E1: the shells and Monitors the main thread
    # started and has not heard the end of, as an agent row counts its own.
    def started(minute, **res):
        return {"type": "user", "timestamp": ts(minute), "toolUseResult": res,
                "message": {"content": [{"type": "tool_result", "content": "ok"}]}}
    def notice(minute, tid, status=True):
        return {"type": "user", "timestamp": ts(minute), "message": {"content":
            "<task-notification><task-id>%s</task-id>%s</task-notification>"
            % (tid, "<status>completed</status>" if status else "<event>line</event>")}}
    bgt = session(tmp, "background", [
        prompt(10, "go", "p1"),
        started(11, taskId="m1", timeoutMs=600000),
        started(12, taskId="m2", timeoutMs=600000),
        started(13, backgroundTaskId="b1"),
        started(13, backgroundTaskId="b2"),
        started(13, backgroundTaskId="b3"),
        dict(started(14, taskId="m3", timeoutMs=600000), isSidechain=True),
        notice(15, "m1", status=False),     # an event, not the end
        notice(16, "m2"),                   # its stream ended
        notice(17, "b3"),                   # finished
    ])
    t = sl.read_transcript(bgt, ())
    check("\U0001F4BB counts the shells still open and \U0001F4E1 a Monitor "
          "whose events carry no status; not a task that ended, or an agent's",
          ((t.shells, t.monitors),
           (sl.EMPTY_TRANSCRIPT.shells, sl.EMPTY_TRANSCRIPT.monitors)),
          ((2, 1), (0, 0)))
    check("drawn shells first, each only while it has one",
          [sl.strip_ansi(sl.render_thread_background(*n)).replace(" ", "")
           for n in ((2, 1), (0, 3), (4, 0), (0, 0))],
          ["\U0001F4BB2\U0001F4E11", "\U0001F4E13", "\U0001F4BB4", ""])
    git = sl.Git(True, "main", False, "", "", False)
    plain = [sl.strip_ansi(sl.render_where_group(
        "p", "~/x", "main", git, sl.render_thread_background(*n)))
             for n in ((0, 0), (2, 1))]
    check("on the end of row 3's left half, after the branch",
          (plain[1][:len(plain[0])] == plain[0],
           plain[1][len(plain[0]):].replace(" ", "")),
          (True, "\U0001F4BB2\U0001F4E11"))

    print("--- the receipt splits each turn by the same rule ---")
    # The receipt's ⌛🤖 and 🔧 are the status line's 🤖 and 🔧 read over
    # one turn: a shell is 🔧, a question or an agent the turn sat on is
    # neither, and 🤖 is what the span has left.  Summed over the turns they
    # are the status line's own figures for the same file.
    rc = session(tmp, "receipt", [
        prompt(10, "go", "p1"),
        calls(11, "m1", "t1"), result(15, "t1"),        # a shell: four
        asks(16, "m2", "q1"), result(19, "q1"),         # a question: three
        answer(20, "m3", 1, 0, 0, 1),                   # 10-20: 🤖 three
        prompt(30, "again", "p2"),
        delegates(31, "m4", "a1"), result(40, "a1"),    # an agent: nine
        calls(41, "m5", "t2"), result(43, "t2"),        # a shell: two
        answer(45, "m6", 1, 0, 0, 1),                   # 30-45: 🤖 four
    ])
    t1, t2 = sl.read_turns(rc)
    check("each turn's 🤖, 🔧 and waiting, in minutes",
          [tuple(round(x / 60) for x in (sl.turn_model_s(t), t.tool_s,
                                         t.blocked_s)) for t in (t1, t2)],
          [(3, 4, 3), (4, 2, 9)])
    st = sl.read_transcript(rc)
    check("and summed, they are the status line's",
          tuple(round(sum(f(t) for t in (t1, t2)))
                for f in (sl.turn_model_s, lambda t: t.tool_s,
                          lambda t: t.blocked_s)),
          (round(st.busy_s - st.tool_s - st.blocked_s), round(st.tool_s),
           round(st.blocked_s)))
    row = sl.cost_group(t2, {}, 200000, sl.PLAIN_INK, sl.ts_epoch(ts(50)))
    check("the 🎤 row draws the two figures in their signed cells",
          "⌛🤖+  4m  🔧+  2m" in row, True)
    tot = sl.cost_totals_group((t1, t2), {}, 200000, sl.PLAIN_INK,
                               sl.ts_epoch(ts(50)))
    check("and the 🎮 row their sums, a blank where the sign was",
          "⌛🤖   7m  🔧   6m" in tot, True)
    check("the two rows are one width, so the cells stack",
          sl.vis_width(row), sl.vis_width(tot))
    check("turn_clock clips a call to the turn it returned in: the seconds "
          "before the prompt are nobody's",
          sl.turn_clock(((0.0, 10.0),), (), 5.0, 20.0), (5.0, 0.0))
    cp = sl.read_turns(session(tmp, "receipt-compact", [
        prompt(10, "go", "p1"),
        answer(11, "m1", 1, 0, 1000, 1),
        boundary(12, 292645, 41000),
        calls(13, "m2", "t1"), result(16, "t1"),        # the answer's tail
    ]))
    check("a compaction is its summariser's 41s and no tool time, even with "
          "a call in the answer it landed in",
          [(t.compact, round(t.tool_s), round(sl.turn_model_s(t)))
           for t in cp], [(False, 0, 60), (True, 0, 41)])
    check("the 👥 row times its agents as the 🎤 row does: a2's ten "
          "minutes since a1, none of them in a tool",
          "⌛🤖+ 10m  🔧+  0s" in sl.cost_group(late, {}, 200000,
                                               sl.PLAIN_INK), True)

    print("--- agent time goes where its tokens go ---")
    # An agent's 🤖 and 🔧 are cut at each of its billed requests and filed
    # with that request, so a row's time counts the agents its tokens do.
    # The main thread's wait on the Agent call is in neither figure, so the
    # agent's run is counted once, off its own file.
    check("split_clock cuts 🤖 (work less tools) and 🔧 (tools less "
          "waiting) at each cut, and past the last cut is nobody's yet",
          sl.split_clock(((0, 100),), ((20, 50), (60, 90)), ((60, 90),),
                         (30, 70)),
          [(20.0, 10.0), (10.0, 20.0)])
    check("so a stretch past it is billed once, by the request after it",
          [sl.split_clock(((0, 100),), ((40, 60),), (), cuts)
           for cuts in ((30,), (30, 100))],
          [[(30.0, 0.0)], [(30.0, 0.0), (50.0, 20.0)]])
    check("no cuts, no pairs", sl.split_clock(((0, 1),), (), (), ()), [])
    at = session(tmp, "agent-time", [
        prompt(10, "go", "p1"),
        delegates(11, "m1", "a1"), result(20, "a1"),   # nine minutes waiting
        answer(21, "m2", 1, 0, 0, 1),                  # 10-21: 🤖 two
    ], agents=[("agent-t", [
        agent_user(11, "p1"),
        calls(12, "t1", "b1"), result(15, "b1"),       # a shell: three
        agent_answer(17, "t2", 1, 0, 0, 1),            # 11-17: 🤖 three
    ])])
    recs = sl.agent_records(at)
    check("each request carries the agent's time since the one before it, "
          "in minutes",
          [(r.request_id, round(r.model_s / 60), round(r.tool_s / 60))
           for r in recs], [("t1", 1, 0), ("t2", 2, 3)])
    check("and they add up to the agent's own clock",
          tuple(round(sum(f(r) for r in recs) / 60)
                for f in (lambda r: r.model_s, lambda r: r.tool_s)),
          tuple(round(x / 60) for x in sl.agent_clock(sl.read_agent_usage(
              recs[0].path), False)))
    (tt,) = sl.read_turns(at, recs)
    check("the turn's own split leaves the agent out, as the status line's "
          "does", (round(sl.turn_model_s(tt) / 60), round(tt.tool_s / 60),
                   round(tt.blocked_s / 60)), (2, 0, 9))
    check("and the row adds it: 🤖 two and three, 🔧 three",
          tuple(round(x / 60) for x in sl.turn_times(tt)), (5, 3))

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

    # Two agents late at one Stop: a 👥 row each, not one row for both.
    b_first = [agent_user(11, "p1")]
    b_all = b_first + [agent_answer(21, "b2", 200, 0, 2000, 20, second=40)]
    tr2 = session(tmp, "late2", main[:2],
                  agents=[("agent-a", agent[:2]), ("agent-b", b_first)])
    sl.publish_agent_offsets(tr2, sl.agent_records(tr2))
    with open(os.path.join(tmp, "late2", "subagents", "agent-b.meta.json"), "w") as fh:
        json.dump({"agentType": "Explore", "description": "Find the callers"}, fh)
    tr2 = session(tmp, "late2", main[:5],
                  agents=[("agent-a", agent), ("agent-b", b_all)])
    with open(os.path.join(tmp, "late2", "subagents", "agent-b.meta.json"), "w") as fh:
        json.dump({"agentType": "Explore", "description": "Find the callers"}, fh)
    two = sl.read_turns(tr2)
    check("each late agent is a turn of its own, with its id and its "
          "description, or its type where it has none",
          [(t.agent_id, t.agent_name, t.agent_calls, t.out)
           for t in two if t.agent],
          [("a", "general-purpose", 1, 10), ("b", "Find the callers", 1, 20)])
    wide2 = sl.CostOpts(prefix="P", label="L", totals_label="T", cols=196,
                        colour=False, totals=True, right_align=True,
                        agents_label="A")
    out2 = sl.strip_ansi(sl.render_cost_line(two, wide2, 1786847000.0)).split("\n")
    check("and a 👥 row each, the name and then the id, padded to ten, "
          "C_MIN_GAP left of its 📊, so the ids stand in one column",
          ([l.strip()[:l.strip().index(" P ") + 1 - sl.C_MIN_GAP].rstrip() for l in out2[:2]],
           # The first line sits beside Claude Code's chrome, which takes
           # C_CHROME_LEFT - C_CHROME_CONT columns more than a continuation
           # line's, so on screen the two ids start together.
           len({out2[0].index(" a ") + sl.C_CHROME_LEFT - sl.C_CHROME_CONT,
                out2[1].index(" b ")})),
          (["general-purpose a", "Find the callers b"], 1))

    tr = session(tmp, "late", main[:8], agents=[("agent-a", agent)])
    turns = sl.read_turns(tr)
    check("third Stop: reported once, now back on its turn for the totals",
          [(t.text[:6], t.agent_calls, t.agent) for t in turns],
          [("first", 2, False), ("second", 0, False), ("third", 0, False)])

    # Without the state file the stamp decides: after the last Stop record
    # is late, before it is taken as reported.
    os.remove(_agent_state_path(tr))
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
          (_settled(sl.read_turns(tr)),
           _settled(tuple(t._replace(calls=0) for t in sl.read_turns(tr)))),
          (True, False))

    # And the rendered rows: the label, and the blanks in ⌛ and 📅.
    calib = {"sess": 5.5, "week": 4.1}
    row = sl.strip_ansi(sl.cost_group(late, calib, sl.CTX_1M, sl.PLAIN_INK,
                                      1786847000.0))
    check("agents row times its agents and blanks its date",
          (sl.S_WORK + "+ 10m" in row, "2026-08-16" in row), (True, False))
    opts = sl.CostOpts(prefix="P", label="L", totals_label="T", cols=0,
                       colour=False, totals=True, right_align=False,
                       agents_label="A")
    lines = sl.strip_ansi(sl.render_cost_line(sl.read_turns(tr), opts,
                                              1786847000.0))
    check("the agents row is labelled, leads the block, and opens with the "
          "name and id of the agent it bills",
          ([l.strip()[:3] for l in lines.split("\n")],
           lines.split("\n")[0].startswith("general-purpose a" + " " * 10 + "P A")),
          (["gen", "🔺🔖 ", "P L", "P T"], True))
    # With no width to right-align against, the turn tag takes a line of
    # its own directly above the 🎤 row it names, in place of the blank.
    check("the turn tag stands over the 🎤 row, not at the top",
          lines.split("\n")[1], sl.E_TURN_PAST + sl.E_TURN_ID + " p2")
    # With room, it goes in the 🎤 row's pad and on no other row, with or
    # without --force-newline, which leaves the chrome's line blank.
    wide = opts._replace(cols=196, right_align=True)
    for name, o in (("without", wide), ("with", wide._replace(force_newline=True))):
        out = sl.strip_ansi(sl.render_cost_line(sl.read_turns(tr), o,
                                                1786847000.0)).split("\n")
        if name == "with":
            check("--force-newline: the chrome's line stays blank", out[0], "")
            out = out[1:]
        check("%s --force-newline: the tag sits in the 🎤 row's pad, "
              "C_MIN_GAP left of its mark; the 👥 row has its agent's id" % name,
              ([l.strip()[:3] for l in out],
               out[2].lstrip().startswith(sl.E_TURN_PAST + sl.E_TURN_ID
                                          + " p2" + " " * sl.C_MIN_GAP + "P L")),
              (["gen", "", "🔺🔖 ", "P T"], True))

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
    # Just after a weekly reset the week opens INSIDE the 5-hour window, and
    # the 5-hour cost still counts from its own start.
    sess, week = sl._window_costs(datetime(2026, 8, 16, 1, 10, 30),
                                  datetime(2026, 8, 16, 1, 11, 30))
    near("a week that reset inside the 5-hour window does not clip it",
         sess, 3000 * OPUS[1])
    near("and the week still counts from its own start", week, 2000 * OPUS[1])

    print("--- the calibration scan's cache ---")
    # Every scan above kept each file's priced records.  A scan of files
    # that have not changed parses no line at all; one that has grown parses
    # only what was appended.
    parsed = []
    priced = sl._priced_record
    sl._priced_record = lambda line: parsed.append(line) or priced(line)
    windows = (datetime(2026, 8, 16, 1, 11, 30), datetime(2026, 8, 1))
    sess, week = sl._window_costs(*windows)
    check("an unchanged tree is read from the cache, line for line none",
          (len(parsed), round(week / OPUS[1])), (0, 3000))
    main_tr = os.path.join(proj, "s1.jsonl")
    with open(main_tr, "a") as fh:
        fh.write(json.dumps(answer(13, "m2", 0, 0, 0, 1000)) + "\n")
    sess, week = sl._window_costs(*windows)
    check("an appended record is the only line parsed, and it counts",
          (len(parsed), round(week / OPUS[1]), round(sess / OPUS[1])),
          (1, 4000, 3000))
    # A last line with no newline may be half written: billed if it parses,
    # but read again whole next time rather than kept.
    with open(main_tr, "a") as fh:
        fh.write(json.dumps(answer(14, "m3", 0, 0, 0, 1000)))
    del parsed[:]
    first = sl._window_costs(*windows)[1]
    second = sl._window_costs(*windows)[1]
    check("a line still being written counts, once, and is not kept",
          (round(first / OPUS[1]), round(second / OPUS[1]), len(parsed)),
          (5000, 5000, 2))
    # A file rewritten shorter, or with different bytes before where the
    # last scan stopped, is read again from the start.
    write_jsonl(main_tr, [prompt(10, "x"), answer(11, "m1", 0, 0, 0, 2000)])
    del parsed[:]
    week = sl._window_costs(*windows)[1]
    check("a rewritten file is read again from its start",
          (len(parsed), round(week / OPUS[1])), (2, 4000))
    # A scan killed part way, as Claude Code kills a status line the next
    # refresh overtakes, keeps what it had read: the next scan reads only
    # the files it had not reached.
    os.remove(os.path.join(os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"],
                           "claude-window-costs.cache"))
    every, sl.COST_SAVE_EVERY_S = sl.COST_SAVE_EVERY_S, -1.0

    def killed(line):
        if b'"w"' in line:
            raise KeyboardInterrupt
        return priced(line)
    sl._priced_record = killed
    try:
        sl._window_costs(*windows)
    except KeyboardInterrupt:
        pass
    sl._priced_record = lambda line: parsed.append(line) or priced(line)
    sl.COST_SAVE_EVERY_S = every
    del parsed[:]
    week = sl._window_costs(*windows)[1]
    check("a killed scan's files are kept, and the next reads only the "
          "workflow file's two lines it had not reached",
          (len(parsed), round(week / OPUS[1])), (2, 4000))
    sl._priced_record = priced

    print()
    print("pass %d   fail %d" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
