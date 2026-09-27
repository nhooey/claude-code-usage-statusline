#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The subagent rows: what --mode subagent reads, derives, and prints.

The agent panel hands the program a task list and reads back one JSON line
per row.  These cases pin the three things the row depends on that the
panel does not say: where a task's transcript is, what it billed, and what
that is against the plan windows — plus the row's shape, as stripped text,
so a reordering shows up as a diff of one line and not of a golden file.

Every fixture is generated.  Nothing in here is a real transcript.

Run:  python3 tests/subagent.py
"""

import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile

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
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path: sys.path.insert(0, root)
    from coding_agent_usage_line import claude
    return claude


def load_renderer():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path: sys.path.insert(0, root)
    from coding_agent_usage_line import claude_subagent_render
    return claude_subagent_render


ANSI = re.compile(r"\x1b\[[0-9;]*m")

# 2026-08-16 02:23:20 UTC — pin-env.sh's PIN_NOW, so the two suites agree
# about what "now" is and the plan cache below is read as fresh.
NOW = 1786847000.0


def ts(minute, second=0):
    return "2026-08-16T01:%02d:%02dZ" % (minute, second)


def agent_user(minute, pid="p1"):
    return {"type": "user", "userType": "external", "isSidechain": True,
            "promptId": pid, "timestamp": ts(minute),
            "message": {"content": "do a thing"}}


def agent_answer(minute, rid, fresh, cw, cr, out, model="claude-opus-5",
                 effort="high", second=0):
    return {"type": "assistant", "requestId": rid, "isSidechain": True,
            "timestamp": ts(minute, second), "effort": effort,
            "message": {"id": rid, "model": model, "usage": {
                "input_tokens": fresh,
                "cache_creation_input_tokens": cw,
                "cache_read_input_tokens": cr,
                "output_tokens": out}}}


def agent_edit(minute, tid, added, removed):
    """One Edit result: a hunk with `added` "+" lines and `removed` "-" ones."""
    return {"type": "user", "isSidechain": True, "timestamp": ts(minute),
            "message": {"content": [{"type": "tool_result",
                                     "tool_use_id": tid}]},
            "toolUseResult": {"filePath": "/f", "structuredPatch": [
                {"oldStart": 1, "oldLines": 1, "newStart": 1, "newLines": 1,
                 "lines": ([" keep"] + ["-old"] * removed
                           + ["+new"] * added)}]}}


def agent_write(minute, tid, text):
    """A Write to a NEW file: no patch to count, the whole file in `content`."""
    return {"type": "user", "isSidechain": True, "timestamp": ts(minute),
            "message": {"content": [{"type": "tool_result",
                                     "tool_use_id": tid}]},
            "toolUseResult": {"type": "create", "filePath": "/g",
                              "content": text, "structuredPatch": []}}


def agent_call(minute, rid, tid, second=0):
    """An agent record that asks for a tool."""
    r = agent_answer(minute, rid, 1, 0, 0, 1, second=second)
    r["message"]["content"] = [{"type": "tool_use", "id": tid, "name": "Bash"}]
    return r


def agent_delegate(minute, rid, tid, second=0):
    """An agent record that starts an agent of its own."""
    r = agent_call(minute, rid, tid, second)
    r["message"]["content"][0]["name"] = "Agent"
    return r


def agent_ask(minute, rid, tid, second=0):
    """A question, which an agent has nobody to put — but the reader reads
    every file the same way rather than assuming that."""
    r = agent_call(minute, rid, tid, second)
    r["message"]["content"][0]["name"] = "AskUserQuestion"
    return r


def agent_result(minute, tid, second=0):
    """And the result that answers it, which is where the tool's clock stops."""
    return {"type": "user", "isSidechain": True, "timestamp": ts(minute, second),
            "message": {"content": [{"type": "tool_result",
                                     "tool_use_id": tid}]}}


def agent_says(minute, text, second=0):
    """An agent record whose answer is `text`."""
    r = agent_answer(minute, "say%d_%d" % (minute, second), 1, 0, 0, 1,
                     second=second)
    r["message"]["content"] = [{"type": "text", "text": text}]
    return r


ETA = "\U0001F3C1 skills/coding-agent-usage-line-report-eta: ETA "


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def session(root, name, agents=(), workflow=()):
    """A transcript and its agent files, laid out as Claude Code lays them:
    `agents` directly under subagents/, `workflow` one directory further."""
    tr = os.path.join(root, name + ".jsonl")
    write_jsonl(tr, [{"type": "user", "userType": "external",
                      "timestamp": ts(1), "message": {"content": "go"}}])
    sub = os.path.join(root, name, "subagents")
    for base, recs, meta in agents:
        write_jsonl(os.path.join(sub, base + ".jsonl"), recs)
        if meta is not None:
            with open(os.path.join(sub, base + ".meta.json"), "w") as fh:
                json.dump(meta, fh)
    for base, recs, meta in workflow:
        d = os.path.join(sub, "workflows", "wf_x")
        write_jsonl(os.path.join(d, base + ".jsonl"), recs)
        with open(os.path.join(d, base + ".meta.json"), "w") as fh:
            json.dump(meta, fh)
    return tr


def task(tid, **kw):
    t = {"id": tid, "name": "Marigold", "type": "local_agent",
         "status": "running", "description": "Review the plan",
         "startTime": int((NOW - 754) * 1000), "model": "claude-opus-5",
         "effort": "high", "contextWindowSize": 200000, "tokenCount": 0,
         "tokenSamples": [], "cwd": "/x"}
    t.update(kw)
    return t


def render(sl, payload, argv=()):
    """Run main_subagent the way the panel does, and hand back the rows as
    {id: stripped content}."""
    sl._SNAPSHOT = None                     # a new process per tick
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = sl.main_subagent(list(argv), json.dumps(payload))
    finally:
        sys.stdout = old
    rows = {}
    for line in buf.getvalue().splitlines():
        d = json.loads(line)
        rows[d["id"]] = ANSI.sub("", d["content"])
    return rc, rows


def main():
    os.environ["TZ"] = "UTC"
    if hasattr(os, "tzset"):
        os.tzset()
    tmp = tempfile.mkdtemp(prefix="statusline-subagent.")
    try:
        return run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(tmp):
    # Every file the row reads that is not the payload, planted.  The plan
    # cache is what the status line writes from Claude Code's rate_limits;
    # the calibration cache without a "windows" key is the planted-fixture
    # form _read_calib_cache returns as units.
    os.environ["CODING_AGENT_USAGE_LINE_NOW"] = "%d" % NOW
    os.environ["CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE"] = os.path.join(tmp, "calib.json")
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = os.path.join(tmp, "state")
    # The panel uses the same v1 collector contract as status/cost.  Keep
    # this test's quota fixture at that boundary rather than reviving its old
    # global Claude cache as an implicit source.
    fixture_source = os.path.join(tmp, "quota-source")
    fixture = {"schema_version": 1, "as_of": NOW, "buckets": [{
        "id": "default", "label": "default", "windows": [
            {"id": "session", "duration_seconds": 18000,
             "used_percent": 41, "resets_at": NOW + 2 * 3600},
            {"id": "week", "duration_seconds": 604800,
             "used_percent": 63, "resets_at": NOW + 3 * 86400}]}]}
    with open(fixture_source, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\nprintf '%%s\\n' '%s'\n" %
                 (json.dumps(fixture, separators=(",", ":"))))
    os.chmod(fixture_source, 0o700)
    os.environ["CODING_AGENT_USAGE_LINE_USAGE_SOURCE"] = "cmd:" + fixture_source
    os.environ.pop("CLAUDE_USAGE_SOURCE", None)
    os.environ["TMPDIR"] = tmp          # isolate subprocess scratch files too
    os.environ.pop("TMUX", None)
    os.environ.pop("TERM_PROGRAM", None)
    os.environ["TERMINAL_EMULATOR"] = "JetBrains-JediTerm"
    with open(os.environ["CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE"], "w") as fh:
        json.dump({"sess": 1.0, "week": 10.0}, fh)   # $1 and $10 per point

    sl = load_program()
    sr = load_renderer()
    # Agent accounting consumes an already selected source snapshot; this is
    # the legacy projection that the orchestration adapter receives from the
    # v1 fixture source below, not a second cache lookup by the renderer.
    sl.seed_limits_snapshot(sl.Limits(
        "41", "2026-08-16 04:00", "", "63", "2026-08-18 01:00", ""))
    OPUS = sl._price("claude-opus-5")

    print("--- finding the transcript ---")
    tr = session(tmp, "s1", agents=[
        ("agent-a1", [agent_user(10),
                      agent_answer(11, "r1", 100, 2000, 30000, 400),
                      agent_answer(11, "r1", 100, 2000, 30000, 400,
                                   second=30),                 # a retry
                      agent_answer(12, "err", 0, 0, 0, 0),     # an API error
                      agent_answer(13, "r2", 50, 1000, 40000, 600,
                                   model="claude-sonnet-5", effort="low"),
                      agent_edit(11, "t1", 9, 4),
                      agent_edit(11, "t1", 9, 4),         # the same result
                      agent_write(12, "t2", "a\nb\nc\n")],
         {"agentType": "Explore", "model": "sonnet"}),
        ("agent-a2", [agent_user(10), agent_answer(11, "x", 10, 0, 0, 10)],
         None),                                                # no sidecar
        ("agent-a3", [agent_user(10), agent_answer(11, "y", 10, 0, 0, 10)],
         {"agentType": "Explore", "parentAgentId": "a1",        # a1's child:
          "spawnDepth": 2}),                                   # one `├ ` deep
        ("agent-a4", [agent_user(10), agent_answer(11, "z", 10, 0, 0, 10)],
         {"agentType": "Explore", "parentAgentId": "a3",        # and its own
          "spawnDepth": 3}),
    ], workflow=[
        ("agent-w1", [agent_user(10), agent_answer(11, "w", 10, 0, 0, 10)],
         {"agentType": "workflow-subagent"}),
    ])
    sub = os.path.join(tmp, "s1", "subagents")
    check("a local agent's file sits beside the transcript",
          sl.agent_file_for(tr, "a1"), os.path.join(sub, "agent-a1.jsonl"))
    check("a workflow agent's file is one directory further",
          sl.agent_file_for(tr, "w1"),
          os.path.join(sub, "workflows", "wf_x", "agent-w1.jsonl"))
    check("a task with no file — a shell — finds nothing",
          sl.agent_file_for(tr, "bash-1"), "")
    check("a path that is not a transcript finds nothing",
          sl.agent_file_for("/nowhere", "a1"), "")
    check("the sidecar is read", sl.agent_meta(sl.agent_file_for(tr, "a1")),
          {"agentType": "Explore", "model": "sonnet"})
    check("no sidecar is {}", sl.agent_meta(sl.agent_file_for(tr, "a2")), {})

    print("--- reading what it billed ---")
    u = sl.read_agent_usage(sl.agent_file_for(tr, "a1"))
    check("requests deduped and the error skipped", u.calls, 2)
    check("▴ is the billable-equivalent sum, ▾ the output",
          (u.tok_up, u.tok_down),
          (int(150 + 2.0 * 3000 + 0.1 * 70000), 1000))
    check("cache rate over all input", u.cache_pct,
          int(100 * 70000 / (150 + 3000 + 70000)))
    check("context is the LAST request's whole input", u.ctx_tokens,
          50 + 1000 + 40000)
    want = (sum(sl._usd("claude-opus-5", 100, 2000, 30000, 400))
            + sum(sl._usd("claude-sonnet-5", 50, 1000, 40000, 600)))
    near("priced per record at its own model", u.cost, want)
    check("the last record's model, effort and stamp are carried",
          (u.model, u.effort, u.last_epoch),
          ("claude-sonnet-5", "low", sl.ts_epoch(ts(13))))
    check("no file reads as no usage", sl.read_agent_usage(""),
          sl.NO_AGENT_USAGE)

    print("--- what the agent wrote ---")
    check("a patch counted a line at a time, a new file counted whole, and "
          "a result that appears twice counted once",
          (u.lines_added, u.lines_removed), (9 + 3, 4))
    check("an agent that only read wrote nothing, which is zero and not "
          "unknown",
          (lambda x: (x.lines_added, x.lines_removed))(
              sl.read_agent_usage(sl.agent_file_for(tr, "a2"))), (0, 0))
    check("a result with no tool-use id is still counted; nothing else "
          "identifies it",
          sl.agent_diff([dict(agent_edit(11, "t9", 2, 1), message={})]),
          (2, 1))
    check("records that are not tool results, and malformed ones, count "
          "nothing",
          sl.agent_diff([agent_user(10), {"toolUseResult": "text"},
                         {"toolUseResult": {"structuredPatch": "no"}},
                         {"toolUseResult": {"type": "create",
                                            "content": None}}]),
          (0, 0))

    print("--- time inside a tool ---")
    # p spawned k, and x is a sibling that belongs to neither.  Each row's
    # 🔧 is its own agent's alone: k's tools are on k's row.
    tt = session(tmp, "tools", agents=[
        ("agent-p", [agent_user(10), agent_call(11, "r1", "t1"),
                     agent_result(14, "t1")], {"agentType": "Explore"}),
        ("agent-k", [agent_user(20), agent_call(21, "r2", "t2"),
                     agent_result(29, "t2")],
         {"agentType": "Explore", "parentAgentId": "p", "spawnDepth": 2}),
        ("agent-x", [agent_user(30), agent_call(31, "r3", "t3"),
                     agent_result(35, "t3")], {"agentType": "Explore"}),
    ])
    clock = lambda path, running=False, now=None: [round(x / 60) for x in
        sl.agent_clock(sl.read_agent_usage(path), running, now)]
    check("an agent's tool time is its own, not its children's",
          [clock(sl.agent_file_for(tt, t))[1] for t in ("p", "k", "x")],
          [3, 8, 4])
    check("a task with no transcript — a shell — has none",
          clock(""), [0, 0])
    bt = session(tmp, "blocking", agents=[
        ("agent-q", [agent_user(10), agent_call(11, "r1", "t1"),
                     agent_result(16, "t1"), agent_ask(20, "r2", "q1"),
                     agent_result(27, "q1")], {"agentType": "Explore"}),
    ])
    check("a question is read as the tool call it is and then taken back "
          "out, so the row reports the five minutes and not the twelve",
          clock(sl.agent_file_for(bt, "q"))[1], 5)
    # A coordinator: it dispatches an agent in the background, says how long
    # the rest will take, and ends its turn to wait.  Claude Code marks it
    # completed; its child runs on.
    parks = lambda r: dict(r, message=dict(r["message"], stop_reason="end_turn"))
    ct = session(tmp, "coordinator", agents=[
        ("agent-c", [agent_user(10), agent_delegate(11, "r1", "d1"),
                     agent_result(11, "d1", second=5),
                     parks(agent_says(12, "Waiting on it.\n" + ETA + "1h"))],
         {"agentType": "general-purpose"}),
        ("agent-d", [agent_user(11), agent_call(12, "r2", "t2")],
         {"agentType": "Explore", "parentAgentId": "c", "spawnDepth": 2}),
    ])
    cnow = sl.ts_epoch(ts(30))
    crows = dict(sr.render_task_rows(sl.prepare_subagent_tasks(
        {"transcript_path": ct, "tasks": [
            task("c", status="completed", startTime=int(sl.ts_epoch(ts(10)) * 1000)),
            task("d", status="running", startTime=int(sl.ts_epoch(ts(11)) * 1000))]},
        cnow), sl.NO_LIMITS, 200, cnow))
    split = lambda r: re.search("\u231B *(\\S+).*?(\U0001F916\\S+ \U0001F527\\S+ \U0001F6A6\\S+)",
                                ANSI.sub("", r)).groups()
    check("a coordinator parked on its agents keeps its \u231B running, and "
          "the wait is its \U0001F6A6: two minutes working of twenty",
          split(crows["c"]),
          ("20m", "\U0001F916\u2804\u2800 \U0001F527\u2800\u2800 "
                  "\U0001F6A6\u2836\u2826"))
    check("and its child, still in its tool, reads the tool to now as \U0001F527",
          split(crows["d"]),
          ("19m", "\U0001F916\u2804\u2800 \U0001F527\u2836\u2826 "
                  "\U0001F6A6\u2800\u2800"))
    check("the dots share out eight: largest remainder, ties to the "
          "earlier part, and a share of 1% or more never rounds to none",
          [sr.gauge_dots(p) for p in ((600, 300, 0), (1, 1, 0), (5, 395, 0),
                                      (1, 999, 0), (0, 0, 0))],
          [[5, 3, 0], [4, 4, 0], [1, 7, 0], [0, 8, 0], [0, 0, 0]])
    check("each mark takes a gauge of its share of \u231B, two cells of the "
          "middle dot rows, and \U0001F6A6 is what the other two leave",
          [ANSI.sub("", sr.render_agent_split(e, m, t)) for e, m, t in (
              (900.0, 600.0, 300.0), (3600.0, 900.0, 450.0), (60.0, 0.0, 0.0))],
          ["\U0001F916\u2836\u2804 \U0001F527\u2826\u2800 \U0001F6A6\u2800\u2800",
           "\U0001F916\u2806\u2800 \U0001F527\u2804\u2800 \U0001F6A6\u2836\u2804",
           "\U0001F916\u2800\u2800 \U0001F527\u2800\u2800 \U0001F6A6\u2836\u2836"])
    check("a tool reading larger than the run is shared against the sum, "
          "and a task with no transcript draws no split",
          [ANSI.sub("", sr.render_agent_split(60.0, 0.0, 9999.0)),
           sr.render_agent_split(60.0, None, 0.0)],
          ["\U0001F916\u2800\u2800 \U0001F527\u2836\u2836 \U0001F6A6\u2800\u2800", ""])
    # Resumed: it worked 01:10-01:20 with a 3-minute tool, ended its turn,
    # sat finished until SendMessage woke it at 01:50, and has been working
    # since with a 2-minute tool.  Claude Code restarted its startTime at
    # 01:50, which is all the old clock had to go on.
    done = lambda r: dict(r, message=dict(r["message"], stop_reason="end_turn"))
    woken = [agent_user(10), agent_call(11, "r1", "t1"), agent_result(14, "t1"),
             done(agent_says(20, "Done.")), agent_user(50),
             agent_call(51, "r2", "t2"), agent_result(53, "t2"),
             agent_says(55, "Carrying on.")]
    rt = session(tmp, "resumed", agents=[
        ("agent-r", woken, {"agentType": "general-purpose"}),
        ("agent-w", woken + [agent_call(56, "r3", "t3")],
         {"agentType": "general-purpose"})])
    at = lambda m: sl.ts_epoch(ts(m))
    bot = lambda tid, status: [
        u.model_s for t, u, _, _ in sl.prepare_subagent_tasks(
            {"transcript_path": rt, "tasks": [task(
                tid, status=status, startTime=int(at(50) * 1000))]}, at(58))][0]
    check("a resumed agent's \U0001F916 is its working time less its tools, off "
          "the transcript: the 30 minutes it sat finished are not in it, "
          "and neither is the startTime Claude Code restarted",
          [round(bot("r", s) / 60) for s in ("running", "completed")],
          [(10 - 3) + (58 - 50 - 2), (10 - 3) + (55 - 50 - 2)])
    check("and a tool still waiting on its result stops the clock at the "
          "call, not at now",
          round(bot("w", "running") / 60), (10 - 3) + (56 - 50 - 2))
    [(rtask, ru, rm, rsh)] = sl.prepare_subagent_tasks(
        {"transcript_path": rt, "tasks": [task(
            "r", status="running", startTime=int(at(50) * 1000))]}, at(58))
    rrow = ANSI.sub("", sr.render_agent_row(rtask, ru, rm, rsh, sl.NO_LIMITS,
                                            200, at(58)))
    check("its \u231B runs from its first record, not the restarted "
          "startTime, and the 30 minutes it sat finished are \U0001F6A6's: "
          "13m thinking, 5m in tools, 30m waiting, of 48m",
          (re.search("\u231B *(\\S+)", rrow).group(1),
           re.search("\U0001F916\\S+ \U0001F527\\S+ \U0001F6A6\\S+", rrow).group(0)),
          ("48m", "\U0001F916\u2806\u2800 \U0001F527\u2804\u2800 "
                  "\U0001F6A6\u2836\u2804"))

    bg = session(tmp, "background", agents=[
        ("agent-p", [agent_user(10), agent_says(12, "Thinking."),
                     agent_says(30, "Still thinking.")], None),
        ("agent-k", [agent_user(14), agent_call(15, "r1", "t1"),
                     agent_result(25, "t1")],
         {"agentType": "Explore", "parentAgentId": "p", "spawnDepth": 2})])
    [(_, pu, _, _)] = sl.prepare_subagent_tasks(
        {"transcript_path": bg, "tasks": [task("p", status="completed")]},
        at(58))
    check("a child in the background running tools while its parent thinks "
          "is on the child's row: the parent's \U0001F916 is all its own "
          "thinking and its \U0001F527 is empty",
          (round(pu.model_s / 60), round(pu.tool_s / 60)), (20, 0))

    print("--- the background work it waits on ---")
    def started(n, tid, **res):
        r = agent_result(n, tid)
        r["toolUseResult"] = res
        return r
    def notice(n, task_id, status=True, as_user=False):
        text = ("<task-notification>\n<task-id>%s</task-id>\n%s"
                "<summary>done</summary>\n</task-notification>"
                % (task_id, "<status>completed</status>\n" if status else ""))
        if as_user:
            return {"type": "user", "timestamp": ts(n), "promptSource": "system",
                    "message": {"role": "user", "content": text}}
        return {"type": "attachment", "timestamp": ts(n),
                "attachment": {"type": "queued_command", "prompt": text,
                               "commandMode": "task-notification"}}
    bgw = session(tmp, "bgw", agents=[
        ("agent-w", [agent_user(10),
                     agent_call(11, "r1", "t1"),
                     started(12, "t1", backgroundTaskId="sh1"),
                     agent_call(13, "r2", "t2"),
                     started(14, "t2", backgroundTaskId="sh2",
                             timedOutAfterMs=600000),
                     agent_call(15, "r3", "t3"),
                     started(16, "t3", taskId="mon1", timeoutMs=600000,
                             persistent=False),
                     agent_call(17, "r4", "t4"),
                     started(18, "t4", taskId="mon2", timeoutMs=600000),
                     agent_call(19, "r5", "t5"),
                     started(20, "t5", backgroundTaskId="sh3"),
                     notice(21, "sh1"),                  # finished
                     notice(22, "mon1", status=False),   # an event, not the end
                     notice(23, "mon2", as_user=True),   # its stream ended
                     agent_call(24, "r6", "t6"),
                     started(25, "t6", message="Successfully stopped task",
                             task_id="sh3", task_type="local_bash"),
                     agent_says(26, "Waiting on the build.")],
         {"agentType": "Explore"})])
    check("the background tasks it has not heard the end of: a shell moved "
          "there by its timeout, and a Monitor whose events carry no status; "
          "not one that notified with a status, in either shape, or one it "
          "stopped itself",
          sl.read_agent_usage(sl.agent_file_for(bgw, "w")).background,
          (("sh2", "bash"), ("mon1", "monitor")))
    open_ = {"a9": "bash"}
    sl.scan_background({"type": "user", "toolUseResult": {
        "retrieval_status": "success",
        "task": {"task_id": "a9", "status": "completed"}}}, open_)
    check("TaskOutput reading it finished ends it, as Claude Code counts it "
          "delivered", open_, {})

    print("--- the ETA an agent reports ---")
    quoted = agent_result(14, "t9")
    quoted["message"]["content"][0]["content"] = ETA + "9m"
    et = session(tmp, "eta", agents=[
        ("agent-e", [agent_user(10),
                     agent_says(11, "Plan first.\n" + ETA + "20m\nThen go."),
                     agent_says(12, "`" + ETA + "90s`"),
                     quoted,                             # a tool result
                     agent_says(15, "The skill says to write " + ETA + "4m"),
                     agent_says(16, "skills/coding-agent-usage-line-report-eta:"
                                    " ETA <number><s|m|h>")],
         {"agentType": "Explore"}),
        ("agent-n", [agent_user(10), agent_says(11, "Working.")],
         {"agentType": "Explore"}),
        ("agent-b", [agent_says(11, "skills/coding-agent-usage-line-report-eta:"
                                    " ETA 1.5h")],
         {"agentType": "Explore"}),
    ])
    check("the last report the agent wrote on a line of its own, in "
          "backticks or not: not a tool result that quotes one, not one "
          "mentioned mid-sentence, not the skill's template",
          sl.eta_report(list(sl._records(sl.agent_file_for(et, "e")))),
          (sl.ts_epoch(ts(12)), 90.0))
    check("the flag is for the eye and may be missing; minutes and hours "
          "become seconds",
          sl.eta_report(list(sl._records(sl.agent_file_for(et, "b")))),
          (sl.ts_epoch(ts(11)), 5400.0))
    check("a figure in two units is their sum, as an agent with hours left "
          "writes it, joined or spaced",
          [sl.eta_report([{"type": "assistant", "timestamp": ts(11),
                           "message": {"content": [{"type": "text", "text":
                               "skills/coding-agent-usage-line-report-eta: ETA "
                               + d}]}}])[1:] for d in ("6h30m", "1h 5m", "2m30s")],
          [(23400.0,), (3900.0,), (150.0,)])
    check("no report is (), and no transcript is None",
          (sl.read_agent_usage(sl.agent_file_for(et, "n")).eta,
           sl.read_agent_usage("").eta),
          ((), None))
    eta = lambda *a, **k: ANSI.sub("", sr.render_agent_eta(*a, **k))
    start = int((NOW - 600) * 1000)
    check("the figure is what is left of the ETA, counted down since the "
          "report", eta((NOW - 120, 480.0), start, NOW), "\u26F3   6m")
    check("past the estimate the figure is how late it is",
          eta((NOW - 300, 60.0), start, NOW), "\u26F3  +4m")
    check("an agent that has not reported is ?, and a task with nothing to "
          "report in draws nothing",
          (eta((), start, NOW), eta(None, start, NOW)), ("\u26F3    ?", ""))
    check("? and never a made-up 0 for a last report of zero; a completed "
          "agent with a report left is parked and counts down to now; a "
          "killed one is read at its last record, as its clock is",
          (eta((NOW - 60, 0.0), start, NOW),
           eta((NOW - 300, 900.0), start, NOW, "completed", NOW - 200),
           eta((NOW - 300, 300.0), start, NOW, "killed", NOW - 300)),
          ("\u26F3    ?", "\u26F3  10m", "\u26F3   5m"))
    check("a report older than the start, from an agent resumed after it "
          "wrote one, counts down from the report and not from the start",
          eta((NOW - 600, 900.0), int((NOW - 60) * 1000), NOW),
          "\u26F3   5m")
    check("the status line collects every agent still answering with a live "
          "ETA, as (finish, last record), off the same walk",
          sorted(sl.read_transcript(et).agent_etas),
          sorted([(sl.ts_epoch(ts(12)) + 90.0, sl.ts_epoch(ts(16))),
                  (sl.ts_epoch(ts(11)) + 5400.0, sl.ts_epoch(ts(11)))]))
    from types import SimpleNamespace as NS
    left = lambda e, st: sr.eta_reading(e, int(st * 1000), NOW)[1]
    fam = lambda own_p: [
        (task("p", startTime=int((NOW - 600) * 1000)), NS(eta=own_p), {}, {}),
        (task("c", startTime=int((NOW - 300) * 1000)), NS(eta=(NOW - 30, 330.0)),
         {"parentAgentId": "p"}, {}),
        (task("g", startTime=int((NOW - 100) * 1000)), NS(eta=(NOW - 10, 610.0)),
         {"parentAgentId": "c"}, {}),
        (task("d", status="completed"), NS(eta=()),     # its read cleared
         {"parentAgentId": "p"}, {}),                     # the report
        (task("k", status="killed"), NS(eta=(NOW - 10, 9999.0)),
         {"parentAgentId": "p"}, {}),
        (task("q", startTime=int((NOW - 50) * 1000)), NS(eta=()),
         {"parentAgentId": "p"}, {})]
    inh = sr.inherited_etas(fam((NOW - 60, 120.0)))
    check("a row's ETA is the latest finish of its own and every running "
          "descendant's, recursively; a finished or killed child counts for "
          "nothing",
          [round(left(inh[t], NOW - s_)) for t, s_ in
           (("p", 600), ("c", 300), ("g", 100))], [600, 600, 600])
    check("and its own wins when its own plan runs longer, while an agent "
          "with no report of its own and no child reporting stays ?",
          (round(left(sr.inherited_etas(fam((NOW - 60, 1260.0)))["p"],
                      NOW - 600)),
           sr.eta_reading(inh["q"], int((NOW - 50) * 1000), NOW)),
          (1200, ()))
    row = lambda *agents: re.sub(r"\s+", " ", ANSI.sub("", sl.render_elapsed(
        3600.0, NOW - 7200.0, 900.0, NOW, 0.0, (NOW - 60, 240.0), NOW - 300,
        agents)))
    check("the status line inherits the same way from every agent still "
          "answering, and one silent for half an hour is taken for dead",
          [" ".join(row(*a).split()[:3]) for a in
           ((), ((NOW + 600, NOW - 5),), ((NOW + 600, NOW - 4000),))],
          ["\u231B \u26F3 3m", "\u231B \u26F3 10m",
           "\u231B \u26F3 3m"])
    main = os.path.join(tmp, "eta-main.jsonl")
    prompt = lambda m, text: {"type": "user", "userType": "external",
                              "timestamp": ts(m), "message": {"content": text}}
    ended = lambda r: dict(r, message=dict(r["message"], stop_reason="end_turn"))
    turn = [prompt(10, "one"), agent_says(11, ETA + "10m"), prompt(20, "two"),
            agent_says(21, ETA + "4m"), agent_says(22, "Still going.")]
    reads = []
    for recs in (turn, turn + [ended(agent_says(23, "Done."))], turn[:3]):
        write_jsonl(main, [dict(r, isSidechain=False) for r in recs])
        t = sl.read_transcript(main, agents=())
        reads.append((t.turn_s, t.eta))
    check("the status line's ETA is the main thread's, in the turn it is "
          "answering: a new prompt clears the last one's, and the answer "
          "ending clears its own",
          reads,
          [(sl.ts_epoch(ts(20)), (sl.ts_epoch(ts(21)), 240.0)),
           (sl.ts_epoch(ts(20)), ()), (sl.ts_epoch(ts(20)), ())])
    write_jsonl(main, [dict(r, isSidechain=False) for r in
                       turn + [ended(agent_says(23, ETA + "6m\nWaiting on "
                                                "the build."))]])
    check("unless the message that ends the answer carries the report: "
          "that is a thread parked on background work, not finished",
          sl.read_transcript(main, agents=()).eta,
          (sl.ts_epoch(ts(23)), 360.0))
    parts = [agent_says(12, ETA + "5m"), ended(agent_says(12, "Standing by."))]
    pk = session(tmp, "parked", agents=[
        ("agent-f", [agent_user(10), agent_says(11, ETA + "10m"),
                     ended(agent_says(12, "Done."))], None),
        ("agent-g", [agent_user(10), ended(agent_says(12, ETA + "5m"))], None),
        ("agent-h", [agent_user(10)] + parts, None),
        ("agent-i", [agent_user(10)] + parts + [
            agent_user(14), ended(agent_says(15, "All done."))], None)])
    check("an agent's row reads the same: a report in the message that ends "
          "its turn stays live, whichever of the message's records holds "
          "it, while one that ends later without a line is finished",
          [sl.read_agent_usage(sl.agent_file_for(pk, a)).eta
           for a in ("f", "g", "h", "i")],
          [(), (sl.ts_epoch(ts(12)), 300.0), (sl.ts_epoch(ts(12)), 300.0),
           ()])

    print("--- the plan windows ---")
    sh = sl.agent_window_shares(u)
    near("share of the 5-hour window: cost over the unit", sh["sess"], want)
    near("share of the weekly window", sh["week"], want / 10.0)
    late = sl.AgentUsage(1, 1, 0, 1, 1.0, ((NOW - 6 * 3600, 1.0),),
                         "m", "", 1, None)
    near("a record before the 5-hour boundary is not in that window",
         sl.agent_window_shares(late)["sess"], 0.0)
    near("but is in the weekly one", sl.agent_window_shares(late)["week"],
         0.1)
    check("no records, no share", sl.agent_window_shares(sl.NO_AGENT_USAGE),
          {"sess": None, "week": None})

    print("--- the small formatters ---")
    check("model ids and aliases become display names",
          [sl.model_label(m) for m in (
              "claude-opus-5[1m]", "claude-haiku-4-5-20251001", "sonnet",
              "claude-fable-5-1", "Opus 5", "")],
          ["Opus 5", "Haiku 4.5", "Sonnet", "Fable 5.1", "Opus 5", ""])
    near("token rate is the slope over the panel's samples at its tick",
         sr.token_rate([100, 200, 400], "running"), 300 / 10.0)
    check("no rate for a finished task or a single sample",
          (sr.token_rate([100, 200], "completed"),
           sr.token_rate([100], "running"), sr.token_rate(None, "running")),
          (None, None, None))
    check("the type cell: sidecar type first, then the task kind, then 👥",
          [ANSI.sub("", sr.render_kind(a, k)) for a, k in (
              ("Explore", "local_agent"), ("", "local_bash"),
              ("", "local_agent"), ("my-reviewer", "local_agent"))],
          ["\U0001F50D", "\U0001F41A", "\U0001F465", "\U0001F465"])
    read = sl.NO_AGENT_USAGE._replace(eta=())
    check("the state cell: the phase's circle, then what it is doing in it, "
          "or two letters for a state never seen",
          [ANSI.sub("", sr.render_state(x)) for x in
           ("running", "completed", "killed", "failed", "pending", "odd", "")],
          ["\U0001F7E2", "\u26AB\u2705", "\u26AB\U0001F6D1", "\u26AB\u274C",
           "\U0001F7E1\U0001F95A", "od", ""])
    check("running, the mode is who has the floor: the model, a tool, or a "
          "question or agent it waits on",
          [sr.render_state("running", read._replace(pending=p)) for p in (
              (), ((NOW, "Bash"),), ((NOW, "Bash"), (NOW, "Agent")),
              ((NOW, "AskUserQuestion"),))],
          ["\U0001F7E2\U0001F916", "\U0001F7E2\U0001F527",
           "\U0001F7E2\U0001F6A6", "\U0001F7E2\U0001F6A6"])
    check("completed but paused, on what it would wake for: its agents first, "
          "then a shell, a Monitor, and last only the ETA it gave",
          [sr.render_state("completed", read._replace(eta=e, background=b), w)
           for e, b, w in (
               ((NOW, 60.0), (("b1", "bash"),), True),
               ((NOW, 60.0), (("m1", "monitor"), ("b1", "bash")), False),
               ((), (("m1", "monitor"),), False),
               ((NOW, 60.0), (), False),
               ((), (), False))],
          ["\U0001F7E1\U0001F4A4", "\U0001F7E1\U0001F4BB",
           "\U0001F7E1\U0001F4E1", "\U0001F7E1\u26F3",
           "\u26AB\u2705"])
    check("a completed agent with a background task open is parked, and a "
          "pending child keeps its parent parked as a running one does",
          (sr.parked("completed", (), False, (("b1", "bash"),)),
           sr.running_parents([(task("p", status="completed"), None, {}, None),
                               (task("c", status="pending"), None,
                                {"parentAgentId": "p"}, None)])),
          (True, {"p"}))
    check("the rate in three characters: rounded to the unit past a thousand",
          [sl.rate_fig(v) for v in (49, 849, 1200, 1700, 9900, 12000, 150000)],
          ["49", "849", "1k", "2k", "10k", "12k", "150k"])
    check("two characters of model: initial and superscript major, or the "
          "family's head",
          [sl.model_spec(m) for m in (
              "claude-opus-5[1m]", "claude-haiku-4-5-20251001", "sonnet",
              "fable", "claude-fable-5-1", "Opus 5 (1M context)", "")],
          ["O\u2075", "H\u2074", "So", "Fa", "F\u2075", "O\u2075", ""])
    check("the cache cell: two characters, 💯 for a full one, blank for none",
          [ANSI.sub("", sr.render_agent_cache(v)) for v in (94, 100, 5, -1)],
          ["\U0001F3AF94٪", "\U0001F3AF\U0001F4AF٪", "\U0001F3AF 5٪", ""])

    print("--- the rows ---")
    pay = {"session_id": "s1", "transcript_path": tr, "columns": 200,
           "tasks": [
               task("a1", tokenSamples=[1000, 2000, 3000]),
               task("a2", name="Zephyr", status="completed", model="",
                    effort="", description="Sweep the tree",
                    startTime=int(sl.ts_epoch(ts(10)) * 1000)),
               task("bash-1", name="", type="local_bash", status="running",
                    label="npm test --watch", description="npm test",
                    model=None, effort=None, contextWindowSize=None),
           ]}
    rc, rows = render(sl, pay)
    check("exit 0, one row per task", (rc, sorted(rows)),
          (0, ["a1", "a2", "bash-1"]))
    pct = lambda v: sl.limit_pct(v) + sl.E_PCT
    right = "  ".join((
        "\U0001F916O\u2075\U0001F3C3",  # model and effort, before 💰, open it
        sl.seg(sl.vis_width(sl.S_COST) + 4,
               "\U0001F4B0" + sl.pad_val(4, sl.money_fig(u.cost))),
        "\U0001F9E0 41k",
        sl.seg(sl.vis_width(sl.S_TOK) + sl.VAL_W + sl.VAL2_W,
               ANSI.sub("", sl.render_tokens(u.tok_up, u.tok_down))),
        "\U0001F6EB200/s",
        "\U0001F3AF%d%s" % (u.cache_pct, sl.E_PCT),
        # Then the time, before the 5h and 1w: ⌛ runs from its first record; ⛳ is ? because a1 has reported
        # no ETA; and it has been working since 01:10 with no tool paired
        # and no wait, so 🤖 holds all eight dots.
        "\u231B1.2h \u26F3    ? \U0001F916\u2836\u2836 "
        "\U0001F527\u2800\u2800 \U0001F6A6\u2800\u2800",
        "\U0001F50B" + sl.pad_val(4, pct(want)),
        "\U0001FAAB" + sl.pad_val(4, pct(want / 10.0)),
        ANSI.sub("", sl.render_diff("12", "4"))))
    # 🟢 running, and 🤖: no tool call is waiting on its result.
    head = "\U0001F50D\U0001F7E2\U0001F916 a1         "
    tree = sl.E_TREE_NODE + " "         # no nesting: the tree is one ◯ wide
    check("an agent's row: the left group, the name, the panel's tree drawn "
          "again, then the right group, filling the payload's columns exactly",
          rows["a1"], head + sl.seg(200 - sl.vis_width(head) - 2
                                    - sl.vis_width(tree + right), "Marigold")
          + "  " + tree + right)
    check("no margin: the panel's width is already net of its chrome",
          sl.vis_width(rows["a1"]), 200)
    check("the right group ends at the same column on every row",
          len({sl.vis_width(r) for r in (rows["a1"], rows["a2"])}), 1)
    check("no sidecar: the task's kind, and the transcript's model where "
          "the payload has none",
          (rows["a2"].startswith("\U0001F465\u26AB\u2705 "),
           "\U0001F916O\u2075" in rows["a2"]),
          (True, True))
    check("a finished agent shows no rate", "\U0001F6EB" in rows["a2"], False)
    check("an agent that wrote nothing still states it; a task with no "
          "transcript to count states nothing, as its 💰 does",
          ("\U0001F4BE +   0 -   0" in ANSI.sub("", rows["a2"]),
           "\U0001F4BE" in rows["bash-1"]),
          (True, False))
    check("and its clock stopped at its last record, not at now",
          re.search(r"\u231B\s*(\S+)", rows["a2"]).group(1), "1m")
    check("an unnamed task takes its description for a name, then its "
          "label for what it is doing; a shell shows nothing it did not bill",
          re.sub(r" {2,}", "  ", rows["bash-1"]),
          # 🟢 and no mode: a shell has no transcript to say who has the floor.
          "\U0001F41A\U0001F7E2  bash-1  npm test npm test --watch  "
          "\u25EF  \u231B 13m")
    check("a name and its activity, and a label that only repeats the "
          "description is not drawn",
          [ANSI.sub("", sr.render_who(n, a, 40)) for n, a in (
              ("Marigold", "Reading the plan"), ("Marigold", ""),
              ("", "Reading the plan"), ("", ""))],
          ["Marigold Reading the plan", "Marigold", "Reading the plan", ""])
    check("the activity gives way first, then the name",
          [ANSI.sub("", sr.render_who("Marigold", "Reading the plan, slowly",
                                      w)) for w in (30, 20, 12, 6)],
          ["Marigold Reading the plan, sl…", "Marigold Reading th…",
           "Marigold", "Marig…"])
    check("the panel's tree costs two columns a level below the first, and "
          "a task with no sidecar is a root",
          [sr.tree_cols({}, m) for m in (
              {"spawnDepth": 1}, {"spawnDepth": 2}, {"spawnDepth": 3}, {},
              {"spawnDepth": "two"})],
          [0, 2, 4, 0, 0])
    nested = dict(pay, tasks=[task("a1"), task("a3"), task("a4")])
    rows_n = render(sl, nested)[1]
    check("a nested row pays for the `├ ` the panel draws before it, so the "
          "panel's own chrome plus the row is one width at every depth",
          [sl.vis_width(rows_n[t]) + 2 * (d - 1)
           for t, d in (("a1", 1), ("a3", 2), ("a4", 3))],
          [200, 200, 200])
    check("👶🏻 counts the rows under each one, and every row keeps a cell for it "
          "once any row has one",
          [ANSI.sub("", rows_n[t])[:ANSI.sub("", rows_n[t]).index(t) + 2].lstrip()
           for t in ("a1", "a3", "a4")],
          # E_KIDS is two codepoints, and its width the terminal's: see it.
          ["\U0001F50D\U0001F7E2\U0001F916 " + sl.E_KIDS + "1 a1",
           "\U0001F50D\U0001F7E2\U0001F916 " + sl.E_KIDS + "1 a3",
           "\U0001F50D\U0001F7E2\U0001F916 "
           + " " * (sl.vis_width(sl.E_KIDS) + 1) + " a4"])
    at_head = lambda r: sl.vis_width(r[:r.index("\U0001F50D")])
    check("and its cells start on one column at every depth: a shallower row "
          "opens with the blank the deeper ones spend on the panel's `├ `",
          [at_head(rows_n[t]) + 2 * (d - 1)
           for t, d in (("a1", 1), ("a3", 2), ("a4", 3))],
          [4, 4, 4])
    at_clock = lambda r: sl.vis_width(r[:r.index("\u231B")])
    check("and the right group is what holds its column: the name gives",
          [at_clock(rows_n[t]) + 2 * (d - 1)
           for t, d in (("a1", 1), ("a3", 2), ("a4", 3))],
          [at_clock(rows_n["a1"])] * 3)
    # The right group opens on the model, 🤖 and its family's initial.
    before_model = lambda r: r[r.index("\U0001F916O") - 6:r.index("\U0001F916O")]
    check("the tree is drawn again beside the figures, padded to its widest "
          "row: ├ or └ for a child, and a blank for an ancestor with no "
          "sibling left below it",
          [before_model(rows_n[t]) for t in ("a1", "a3", "a4")],
          ["\u23FA     ", "\u2514 \u23FA   ", "  \u2514 \u25EF "])
    meta = lambda parent, depth: {"parentAgentId": parent, "spawnDepth": depth}
    check("the tree as far as the sidecars say: a bar runs down an "
          "ancestor's column while its siblings go on, a row with a child "
          "showing is expanded and so selected, a shell is a root, and so "
          "is a task whose parent is not in the payload, as the panel "
          "draws it",
          sr.tree_marks([(task(t), None, m, None) for t, m in (
              ("p", {}), ("c1", meta("p", 2)), ("g1", meta("c1", 3)),
              ("g2", meta("c1", 3)), ("c2", meta("p", 2)),
              ("bash-1", {}), ("o", meta("gone", 3)))]),
          {"p": "\u23FA", "c1": "\u251C \u23FA", "g1": "\u2502 \u251C \u25EF",
           "g2": "\u2502 \u2514 \u25EF", "c2": "\u2514 \u25EF", "bash-1": "\u25EF",
           "o": "\u25EF"})
    ms = lambda t0: int((NOW - t0) * 1000)
    check("siblings go in the panel's order, by startTime, not the "
          "payload's",
          sr.tree_marks([(task(t, startTime=ms(a)), None, m, None)
                         for t, a, m in (("p", 90, {}),
                                         ("late", 10, meta("p", 2)),
                                         ("early", 60, meta("p", 2)))]),
          {"p": "\u23FA", "early": "\u251C \u25EF", "late": "\u2514 \u25EF"})
    done_kid = lambda st: [(task(t, status=s_, startTime=ms(a)), None, m, None)
                           for t, s_, a, m in (
                               ("p", "running", 90, {}),
                               ("c", "completed", 60, meta("p", 2)),
                               ("g", st, 30, meta("c", 3)))]
    check("an ancestor that finished and waits on nothing is stepped over, "
          "as the panel drops it: its child hangs from the next one up, and "
          "pays for one `├ ` less",
          (sr.tree_marks(done_kid("completed")),
           sr.tree_shape(done_kid("completed"))["g"]),
          ({"p": "\u23FA", "c": "\u251C \u25EF", "g": "\u2514 \u25EF"},
           ("p", 2)))
    check("but one parked on a child still running keeps it",
          (sr.tree_marks(done_kid("running")),
           sr.tree_shape(done_kid("running"))["g"]),
          ({"p": "\u23FA", "c": "\u2514 \u23FA", "g": "  \u2514 \u25EF"},
           ("c", 3)))
    long = "Review the plan, then the code under it, then the docs beside it"
    wide = dict(pay, tasks=[task("a1", name="", description=long)])
    check("the name takes what the metrics leave, and gives way first",
          (render(sl, dict(wide, columns=400))[1]["a1"].count(long),
           re.search(r"Review the plan, [^…]*…  \U0001F916",
                     # 154 and not the 130 it was: the right group grew by the
                     # 🔧 cell and then ⛳ and its bar, each with its gap, the
                     # state cell by the mode mark after its circle, and this
                     # case is about a width that squeezes the NAME, not one
                     # that squeezes it away.
                     render(sl, dict(wide, columns=154))[1]["a1"]) is not None,
           render(sl, dict(wide, columns=None), ["--cols", "0"])[1]["a1"]
           .count(long[:sr.A_NAME_MIN - 1] + "…")),
          (1, True, 1))
    check("a window too narrow to leave the name A_TREE_ROOM draws no copy "
          "of the tree, and one wide enough does",
          ["\u25EF" in render(sl, dict(wide, columns=c))[1]["a1"]
           for c in (152, 400)],
          [False, True])

    edge = [sum("\u25EF" in r or "\u23FA" in r[40:] for r in
                render(sl, dict(nested, columns=c))[1].values())
            for c in range(150, 200)]
    check("the copy of the tree is on every row or on none, at every width: "
          "a nested row decides on its parent's room, not its own",
          sorted(set(edge)), [0, 3])
    rc, rows = render(sl, dict(pay, tasks=[task("a1"), {"no": "id"}, 7]))
    check("a task without an id is skipped, not fatal", sorted(rows), ["a1"])
    for raw in ("", "not json", "[]", "null"):
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            rc = sl.main_subagent([], raw)
        finally:
            sys.stdout = old
        check("bad input %r: exit 0 and nothing printed, so the panel's "
              "own rows stand" % raw, (rc, buf.getvalue()), (0, ""))

    rc, rows = render(sl, pay, ["--usage-source", "native"])
    check("no plan reading: the 🔋 and 🪫 cells are blank, the rest stands",
          ("\U0001F50B" in rows["a1"], "\U0001F4B0" in rows["a1"]),
          (False, True))

    print()
    print("pass %d   fail %d" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
