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

from _checks import (check, drawn, near, tally, unpainted,  # noqa: E402
                     write_jsonl)


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


# 2026-08-16 02:23:20 UTC — the shared cases' PIN_NOW, so the two suites agree
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


ETA = "\u26F3 skills/coding-agent-usage-line-report-eta: ETA "


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
        rc = sl.main_subagent(sl.from_argv(argv), json.dumps(payload))
    finally:
        sys.stdout = old
    rows = {}
    for line in buf.getvalue().splitlines():
        d = json.loads(line)
        rows[d["id"]] = unpainted(d["content"])
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
                                unpainted(r)).groups()
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
          [unpainted(sr.render_agent_split(e, m, t)) for e, m, t in (
              (900.0, 600.0, 300.0), (3600.0, 900.0, 450.0), (60.0, 0.0, 0.0))],
          ["\U0001F916\u2836\u2804 \U0001F527\u2826\u2800 \U0001F6A6\u2800\u2800",
           "\U0001F916\u2806\u2800 \U0001F527\u2804\u2800 \U0001F6A6\u2836\u2804",
           "\U0001F916\u2800\u2800 \U0001F527\u2800\u2800 \U0001F6A6\u2836\u2836"])
    check("a tool reading larger than the run is shared against the sum, "
          "and a task with no transcript draws no split",
          [unpainted(sr.render_agent_split(60.0, 0.0, 9999.0)),
           unpainted(sr.render_agent_split(60.0, None, 0.0))],
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
    rrow = unpainted(sr.render_agent_row(rtask, ru, rm, rsh, sl.NO_LIMITS,
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
    check("words after the figure, past a dash, say what is left and are "
          "not read; the figure must still come first",
          [sl.eta_report([{"type": "assistant", "timestamp": ts(11),
                           "message": {"content": [{"type": "text", "text":
                               "skills/coding-agent-usage-line-report-eta: ETA "
                               + d}]}}])[1:]
           for d in ("4m \u2014 two lanes left", "1h 5m - the e2e runs",
                     "several hours", "done")],
          [(240.0,), (3900.0,), (), ()])
    check("the 🏁 the skill asked for before ⛳ is still read",
          sl.eta_report([{"type": "assistant", "timestamp": ts(11),
                          "message": {"content": [{"type": "text", "text":
                              "\U0001F3C1 skills/coding-agent-usage-line-"
                              "report-eta: ETA 4m"}]}}])[1:],
          (240.0,))
    check("no report is (), and no transcript is None",
          (sl.read_agent_usage(sl.agent_file_for(et, "n")).eta,
           sl.read_agent_usage("").eta),
          ((), None))
    eta = lambda *a, **k: unpainted(sr.render_agent_eta(*a, **k))
    start = int((NOW - 600) * 1000)
    check("the figure is what is left of the ETA, counted down since the "
          "report", eta((NOW - 120, 480.0), start, NOW), "\u26F3   6m")
    check("past the estimate the figure is how late it is",
          eta((NOW - 300, 60.0), start, NOW), "\u26F3  +4m")
    # Decided 2026-10-19: ⛳ with no estimate is blank, not a dim "?", which
    # said nothing a blank does not.
    check("an agent that has not reported draws nothing, as a task with "
          "nothing to report in does",
          (eta((), start, NOW), eta(None, start, NOW)), ("", ""))
    check("a last report of zero is the sign-off, not a missing estimate: 0s "
          "as it is written, then late by however long the agent keeps going; "
          "a completed agent with a report left is parked and counts down to "
          "now; a killed one is read at its last record, as its clock is",
          (eta((NOW, 0.0), start, NOW),
           eta((NOW - 60, 0.0), start, NOW),
           eta((NOW - 300, 900.0), start, NOW, "completed", NOW - 200),
           eta((NOW - 300, 300.0), start, NOW, "killed", NOW - 300)),
          ("\u26F3   0s", "\u26F3  +1m", "\u26F3  10m", "\u26F3   5m"))
    from types import SimpleNamespace as NS
    over = lambda own, shown=False: [
        c in drawn(sr.render_agent_row(task("o", startTime=start), NS(eta=own),
                                       {}, {}, sl.NO_LIMITS, now=NOW, eta=shown))
        for c in (sl.F_OVER, sl.F_AMB)]
    check("late past a sign-off is bright red, late past an estimate amber, "
          "and a sign-off a child's later finish overruns is amber too",
          (over((NOW - 60, 0.0)), over((NOW - 300, 60.0)),
           over((NOW - 120, 0.0), (NOW - 600, 500.0))),
          ([True, False], [False, True], [False, True]))
    check("a run whose sign-off lands the moment it starts is all done, not "
          "a division by zero",
          sr.eta_reading((NOW, 0.0), int(NOW * 1000), NOW), (1.0, 0.0))
    check("a report older than the start, from an agent resumed after it "
          "wrote one, counts down from the report and not from the start",
          eta((NOW - 600, 900.0), int((NOW - 60) * 1000), NOW),
          "\u26F3   5m")
    check("the status line collects every agent still answering with a live "
          "ETA, as (finish, last record), off the same walk",
          sorted(sl.read_transcript(et).agent_etas),
          sorted([(sl.ts_epoch(ts(12)) + 90.0, sl.ts_epoch(ts(16))),
                  (sl.ts_epoch(ts(11)) + 5400.0, sl.ts_epoch(ts(11)))]))
    ended = lambda n: {"type": "user", "timestamp": ts(n),
                       "promptSource": "system", "message": {
                           "role": "user", "content":
                           "<task-notification>\n<task-id>e</task-id>\n"
                           "<status>killed</status>\n</task-notification>"}}
    with open(et, "a") as fh:
        fh.write(json.dumps(ended(14)) + "\n")
    check("an agent the main transcript says ended before its last record "
          "was resumed, and keeps its ETA",
          len(sl.read_transcript(et).agent_etas), 2)
    with open(et, "a") as fh:
        fh.write(json.dumps(ended(20)) + "\n")
    check("one it says ended after it, killed mid-answer, drops its ETA: "
          "its file reads as still answering, and its last report pushed ⛳ "
          "past its finish for half an hour",
          sl.read_transcript(et).agent_etas,
          ((sl.ts_epoch(ts(11)) + 5400.0, sl.ts_epoch(ts(11))),))
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
    row = lambda *agents: re.sub(r"\s+", " ", unpainted(sl.render_elapsed(
        3600.0, NOW - 7200.0, 900.0, NOW, 0.0, (NOW - 60, 240.0), NOW - 300,
        agents)))
    check("the status line inherits the same way from every agent still "
          "answering, and one silent for half an hour is taken for dead",
          [" ".join(row(*a).split()[:3]) for a in
           ((), ((NOW + 600, NOW - 5),), ((NOW + 600, NOW - 4000),))],
          ["\u231B \u26F3 3m", "\u231B \u26F3 10m",
           "\u231B \u26F3 3m"])
    flag = lambda own, *agents: [c in drawn(sl.render_elapsed(
        3600.0, NOW - 7200.0, 900.0, NOW, 0.0, own, NOW - 300, agents))
        for c in (sl.F_OVER, sl.F_AMB)]
    check("the status line's \u26F3 late past the main thread's sign-off is "
          "bright red, past its estimate amber, and amber too when a live "
          "agent's later finish is what it overran",
          (flag((NOW - 120, 0.0)), flag((NOW - 240, 60.0)),
           flag((NOW - 120, 0.0), (NOW - 60, NOW - 5))),
          ([True, False], [False, True], [False, True]))
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
    signs = []
    for tail in ([ended(agent_says(23, "Done.\n" + ETA + "0s"))],
                 [agent_says(23, ETA + "0s"), agent_says(24, "One more fix.")]):
        write_jsonl(main, [dict(r, isSidechain=False) for r in turn + tail])
        signs.append(sl.read_transcript(main, agents=()).eta)
    check("but a 0s there is the sign-off, and finishes the answer; a 0s "
          "written while it keeps working stays live, so the work after it "
          "reads as late",
          signs, [(), (sl.ts_epoch(ts(23)), 0.0)])
    parts =[agent_says(12, ETA + "5m"), ended(agent_says(12, "Standing by."))]
    pk = session(tmp, "parked", agents=[
        ("agent-f", [agent_user(10), agent_says(11, ETA + "10m"),
                     ended(agent_says(12, "Done."))], None),
        ("agent-g", [agent_user(10), ended(agent_says(12, ETA + "5m"))], None),
        ("agent-h", [agent_user(10)] + parts, None),
        ("agent-i", [agent_user(10)] + parts + [
            agent_user(14), ended(agent_says(15, "All done."))], None),
        ("agent-j", [agent_user(10), agent_says(12, ETA + "0s"),
                     ended(agent_says(12, "All done."))], None)])
    check("an agent's row reads the same: a report in the message that ends "
          "its turn stays live, whichever of the message's records holds "
          "it, while one that ends later without a line is finished, and so "
          "is one that signs off with 0s as it ends",
          [sl.read_agent_usage(sl.agent_file_for(pk, a)).eta
           for a in ("f", "g", "h", "i", "j")],
          [(), (sl.ts_epoch(ts(12)), 300.0), (sl.ts_epoch(ts(12)), 300.0),
           (), ()])

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
    # The panel never runs the scan: Claude Code kills its command at five
    # seconds, which a cold scan can outlast.  It divides by a cached scan
    # of these windows however old, and with none draws "?".
    calib_path = os.environ["CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE"]
    with open(calib_path) as fh:
        planted = fh.read()
    scans = []
    scan = sl._window_costs
    sl._window_costs = lambda *a: scans.append(a) or (0.0, 0.0)
    key = "%s|%s" % sl._window_starts()
    with open(calib_path, "w") as fh:
        json.dump({"windows": key, "sess_cost": 41.0, "week_cost": 630.0,
                   "sess_pct": 41, "week_pct": 63}, fh)
    os.utime(calib_path, (NOW - 3600, NOW - 3600))
    sh = sl.agent_window_shares(u)
    near("an hour-old scan of these windows still prices the panel's share",
         sh["sess"], want)
    os.remove(calib_path)
    check("with no scan cached the panel draws ? and does not scan",
          (sl.agent_window_shares(u), scans), ({"sess": None, "week": None}, []))
    sl._window_costs = scan
    with open(calib_path, "w") as fh:
        fh.write(planted)

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
          [unpainted(sr.render_kind(a, k)) for a, k in (
              ("Explore", "local_agent"), ("", "local_bash"),
              ("", "local_agent"), ("my-reviewer", "local_agent"))],
          ["\U0001F50D", "\U0001F41A", "\U0001F465", "\U0001F465"])
    read = sl.NO_AGENT_USAGE._replace(eta=())
    check("the state cell: the phase's circle, then what it is doing in it, "
          "or two letters for a state never seen",
          [unpainted(sr.render_state(x)) for x in
           ("running", "completed", "killed", "failed", "pending", "odd", "")],
          ["\U0001F7E2", "\u26AB\u2705", "\u26AB\U0001F6D1", "\u26AB\u274C",
           "\U0001F7E1\U0001F95A", "od", ""])
    check("running, the mode is who has the floor: the model, a tool, or a "
          "question or agent it waits on",
          [unpainted(sr.render_state("running", read._replace(pending=p)))
           for p in (
              (), ((NOW, "Bash"),), ((NOW, "Bash"), (NOW, "Agent")),
              ((NOW, "AskUserQuestion"),))],
          ["\U0001F7E2\U0001F916", "\U0001F7E2\U0001F527",
           "\U0001F7E2\U0001F6A6", "\U0001F7E2\U0001F6A6"])
    check("completed but paused, on what it would wake for: its agents first, "
          "then a shell, a Monitor, and last only the ETA it gave",
          [unpainted(sr.render_state("completed",
                                 read._replace(eta=e, background=b), w))
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
          [unpainted(sr.render_agent_cache(v)) for v in (94, 100, 5, -1)],
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
        # 🧠, then its share of the 200k window the payload gives.
        "\U0001F9E0 41k  20\u066A",
        sl.seg(sl.vis_width(sl.S_TOK) + sl.VAL_W + sl.VAL2_W,
               unpainted(sl.render_tokens(u.tok_up, u.tok_down))),
        "\U0001F3AF%d%s" % (u.cache_pct, sl.E_PCT),
        # Then the time, before the 5h and 1w: ⌛ runs from its first record;
        # ⛳ is blank, its width kept, because a1 has reported no ETA; and it
        # has been working since 01:10 with no tool paired and no wait, so 🤖
        # holds all eight dots.
        "\u231B1.2h " + " " * sr.grid.cell_width("A_ETA_W")
        + " \U0001F916\u2836\u2836 "
        "\U0001F527\u2800\u2800 \U0001F6A6\u2800\u2800",
        "\U0001F50B" + sl.pad_val(4, pct(want)),
        # 🪫 a column wider, for limit_pct's fourth digit.
        "\U0001FAAB" + sl.pad_val(5, sl.limit_pct(want / 10.0, 4) + sl.E_PCT),
        unpainted(sl.render_diff("12", "4"))))
    # The spinner's first frame, for a transcript with no text or tool call
    # in it; then 🟢 running, and the name.  The Doing field is the grid's
    # 🛫 column now, after the model: 🤖, no call waiting on its result, and
    # nothing written for 1.2h, so the quiet time rather than the rate.
    right = right.replace("\U0001F3C3  ", "\U0001F3C3  \U0001F916 1.2h  ", 1)
    head = "·\U0001F50D\U0001F7E2 "
    # The payload's columns are the terminal's less PANEL_COLUMNS_SHORT, and
    # the rows are laid out for the terminal's, less the chrome Claude Code
    # draws ("  ◯ " at the top level) and the RIGHT_EDGE every readout keeps.
    edge = 200 + sl.PANEL_COLUMNS_SHORT - sl.RIGHT_EDGE - sl.PANEL_CHROME
    check("an agent's row: the kind and state, the name, then the grid's "
          "columns, ending RIGHT_EDGE short of the terminal behind the chrome",
          rows["a1"], head + sl.seg(edge - sl.vis_width(head) - 2
                                    - sl.vis_width(right), "Marigold")
          + "  " + right)
    check("the row fills the terminal's width less the chrome and RIGHT_EDGE",
          sl.vis_width(rows["a1"]), edge)
    # a2 wrote nothing, so its 💾 is blank and the panel's rstrip ends it
    # sooner; its columns are where a1's are.
    check("the columns start at the same column on every row",
          len({sl.vis_width(r[:r.index("⌛")])
               for r in (rows["a1"], rows["a2"])}), 1)
    check("no sidecar: the task's kind, and the transcript's model where "
          "the payload has none",
          # No spinner on a row not running, and no blank for it, then ⚫,
          # and its ✅ with the time since it finished, a minute after its
          # last record, in the 🛫 column.
          (rows["a2"].startswith("\U0001F465⚫ Zephyr"),
           "\U0001F916O⁵\U0001F3C3  ✅" in rows["a2"]),
          (True, True))
    check("a finished agent shows no rate", "\U0001F6EB" in rows["a2"], False)
    # Decided 2026-10-19: a cell that says nothing draws nothing, so 💾 at
    # "+0 -0" is blank; a blank 💾 means none changed or none counted.
    check("an agent that wrote nothing draws a blank 💾, as a task with no "
          "transcript to count does, and as its 💰 does",
          ("\U0001F4BE" in rows["a2"], "\U0001F4BE" in rows["bash-1"]),
          (False, False))
    check("and its clock stopped at its last record, not at now",
          re.search(r"⌛\s*(\S+)", rows["a2"]).group(1), "1m")
    check("an unnamed task takes its description for a name, then its "
          "label for what it is doing; a shell shows nothing it did not "
          "bill, and its label runs on over the blank columns to its ⌛",
          re.sub(r" {2,}", "  ", rows["bash-1"]),
          # No spinner, 🟢 and no mode: a shell has no transcript to count
          # in or to say who has the floor.
          "\U0001F41A\U0001F7E2 npm test  npm test --watch  ⌛ 13m")
    label = lambda name, act, room, branch="": unpainted(sr.grid.label_text(
        sr.grid.Row("agent", sr.agent_label(
            task("x", name=name, label=act, status="completed"),
            NS(branch=branch), {}), {}, 1), [], room))
    check("a name and its activity, and a label that only repeats the "
          "description is not drawn",
          [label(n, a, 40) for n, a in (
              ("Marigold", "Reading the plan"), ("Marigold", ""),
              ("", "Reading the plan"), ("", ""),
              ("Marigold", "Review the plan"))],
          # The description stands in for a missing name.
          ["\U0001F465⚫ Marigold  Reading the plan",
           "\U0001F465⚫ Marigold",
           "\U0001F465⚫ Review the plan  Reading the plan",
           "\U0001F465⚫ Review the plan",
           "\U0001F465⚫ Marigold"])
    check("the label is cut from the end: the activity gives way first, "
          "then the branch, then the name",
          [label("Marigold", "Reading the plan, slowly", w, "fix-inbox")
           for w in (50, 30, 20, 12)],
          ["\U0001F465⚫ Marigold  \U0001F33Ffix-inbox  Reading the plan, slo…",
           "\U0001F465⚫ Marigold  \U0001F33Ffix-inbox  R…",
           "\U0001F465⚫ Marigold  \U0001F33Ffi…",
           "\U0001F465⚫ Marigo…"])
    check("a row's depth, the chrome Claude Code indents it by, is its own "
          "spawnDepth where the panel's tree gives none; a task with no "
          "sidecar is a root",
          [sr.spawn_depth({}, m) for m in (
              {"spawnDepth": 1}, {"spawnDepth": 2}, {"spawnDepth": 3}, {},
              {"spawnDepth": "two"})],
          [1, 2, 3, 1, 1])
    nested = dict(pay, columns=201, tasks=[task("a1"), task("a3"), task("a4")])
    rows_n = render(sl, nested)[1]
    chrome = lambda d: sl.PANEL_CHROME + 2 * (d - 1)
    # a3 and a4 wrote nothing, so their 💾 is blank and the rstrip ends them
    # before it; up to 🪫 the chrome plus the row is one width, and a1, which
    # draws 💾, ends RIGHT_EDGE short of the terminal.
    at_week = lambda r: sl.vis_width(r[:r.index("\U0001FAAB")])
    check("a nested row pays for the two columns a level Claude Code indents "
          "its chrome by, so the chrome plus the row is one width at every "
          "depth",
          ([at_week(rows_n[t]) + chrome(d)
            for t, d in (("a1", 1), ("a3", 2), ("a4", 3))],
           sl.vis_width(rows_n["a1"]) + chrome(1)),
          ([at_week(rows_n["a1"]) + chrome(1)] * 3,
           201 + sl.PANEL_COLUMNS_SHORT - sl.RIGHT_EDGE))
    # --right-edge 0, for the mod's band under the footer line, where there
    # is no [-] (asked 2026-10-20): the same rows end at the terminal's edge,
    # and the columns stay where they were relative to it.
    sl.set_right_edge(0)
    try:
        rows_0 = render(sl, nested)[1]
    finally:
        sl.set_right_edge(sl.RIGHT_EDGE)
    check("under --right-edge 0 a row ends at the terminal's edge, and every "
          "column moves right by RIGHT_EDGE",
          (sl.vis_width(rows_0["a1"]) + chrome(1),
           at_week(rows_0["a1"]) - at_week(rows_n["a1"])),
          (201 + sl.PANEL_COLUMNS_SHORT, sl.RIGHT_EDGE))
    check("👶🏻 counts the rows under each one, and every row keeps a cell for it "
          "once any row has one",
          [unpainted(rows_n[t])[:unpainted(rows_n[t]).index("Marigold")]
           for t in ("a1", "a3", "a4")],
          # The counts follow the kind and state, 👶🏻 first.  E_KIDS is two
          # codepoints, and its width the terminal's.
          ["·\U0001F50D\U0001F7E2 " + sl.E_KIDS + "1 ",
           "·\U0001F50D\U0001F7E2 " + sl.E_KIDS + "1 ",
           "·\U0001F50D\U0001F7E2 " + " " * (sl.vis_width(sl.E_KIDS) + 1) + " "])
    spun = os.path.join(tmp, "spin.jsonl")
    tool = agent_says(12, "")
    tool["message"]["content"] = [{"type": "thinking", "thinking": "hm"},
                                  {"type": "text", "text": "  "},
                                  {"type": "tool_use", "id": "t1", "name": "Read",
                                   "input": {}}]
    write_jsonl(spun, [agent_says(10, "Plan."), agent_says(11, "Go."), tool])
    spin = lambda st, eta, n: unpainted(sr.render_spin(st, NS(eta=eta, blocks=n)))
    check("a running agent's spinner steps one frame for each ⏺ it has "
          "written, a text or tool-call block and not a thought or a blank, "
          "forward through Claude Code's glyphs and back; a row not running, "
          "or with no transcript, draws none",
          (sl.read_agent_usage(spun).blocks,
           [spin("running", (), n) for n in (0, 1, 5, 6, 11, 12)],
           spin("completed", (), 3), spin("running", None, 3)),
          (3, ["·", "✢", "✽", "✽", "·", "·"],
           "", ""))
    at_head = lambda r: sl.vis_width(r[:r.index("\U0001F50D")])   # past the spinner
    check("and its label starts right after the chrome at every depth: no "
          "lead, the chrome is Claude Code's",
          [at_head(rows_n[t]) for t in ("a1", "a3", "a4")], [1, 1, 1])
    at_clock = lambda r: sl.vis_width(r[:r.index("⌛")])
    check("and the grid's columns are what hold: the label gives",
          [at_clock(rows_n[t]) + chrome(d)
           for t, d in (("a1", 1), ("a3", 2), ("a4", 3))],
          [at_clock(rows_n["a1"]) + chrome(1)] * 3)
    check("the panel's tree is not drawn again: its chrome is Claude Code's",
          [any(g in rows_n[t] for g in (sl.E_TREE_NODE, sl.E_TREE_OPEN,
                                         sl.E_TREE_MID, sl.E_TREE_END,
                                         sl.E_TREE_BAR))
           for t in ("a1", "a3", "a4")],
          [False] * 3)
    meta = lambda parent, depth: {"parentAgentId": parent, "spawnDepth": depth}
    check("the tree as far as the sidecars say: a shell is a root, and so is "
          "a task whose parent is not in the payload",
          {t: d for t, (_, d) in sr.tree_shape(
              [(task(t), None, m, None) for t, m in (
                  ("p", {}), ("c1", meta("p", 2)), ("g1", meta("c1", 3)),
                  ("g2", meta("c1", 3)), ("c2", meta("p", 2)),
                  ("bash-1", {}), ("o", meta("gone", 3)))]).items()},
          {"p": 1, "c1": 2, "g1": 3, "g2": 3, "c2": 2, "bash-1": 1, "o": 1})
    ms = lambda t0: int((NOW - t0) * 1000)
    done_kid = lambda st: [(task(t, status=s_, startTime=ms(a)), None, m, None)
                           for t, s_, a, m in (
                               ("p", "running", 90, {}),
                               ("c", "completed", 60, meta("p", 2)),
                               ("g", st, 30, meta("c", 3)))]
    check("an ancestor that finished and waits on nothing is stepped over, "
          "as the panel drops it: its child hangs from the next one up, a "
          "level higher",
          sr.tree_shape(done_kid("completed"))["g"], ("p", 2))
    check("but one parked on a child still running keeps it",
          sr.tree_shape(done_kid("running"))["g"], ("c", 3))
    long = "Review the plan, then the code under it, then the docs beside it"
    wide = dict(pay, tasks=[task("a1", name="", description=long)])
    unknown = render(sl, dict(wide, columns=None), ["--cols", "0"])[1]["a1"]
    # ⛳ is not among the marks the unknown width shows: a1 has reported no
    # ETA, so its ⛳ is blank.
    check("the name takes what the columns leave, and is cut to it; at an "
          "unknown width every column shows and the label keeps LABEL_MIN "
          "beside them, and two more at the top level",
          (render(sl, dict(wide, columns=400))[1]["a1"].count(long),
           re.search(r"Review the plan, [^…]*…  \U0001F916",
                     render(sl, dict(wide, columns=160))[1]["a1"]) is not None,
           unknown.count(long[:sl.LABEL_MIN + 2 - sl.vis_width(head) - 1] + "…"),
           all(unpainted(c) in unpainted(unknown) for c in (
               "\U0001F916O", "\U0001F4B0", "\U0001F9E0", "\U0001F3AF",
               "⌛", "\U0001F50B", "\U0001FAAB", "\U0001F4BE"))),
          (1, True, 1, True))
    edge = [len({at_clock(r) + chrome(d) for r, d in zip(
                (lambda rs: [rs["a1"], rs["a3"], rs["a4"]])(
                    render(sl, dict(nested, columns=c))[1]), (1, 2, 3))})
            for c in range(150, 212)]
    check("the grid's ⌛ holds one screen column on every row, at every width",
          sorted(set(edge)), [1])
    rc, rows = render(sl, dict(pay, tasks=[task("a1"), {"no": "id"}, 7]))
    check("a task without an id is skipped, not fatal", sorted(rows), ["a1"])
    for raw in ("", "not json", "[]", "null"):
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            rc = sl.main_subagent(sl.from_argv([]), raw)
        finally:
            sys.stdout = old
        check("bad input %r: exit 0 and nothing printed, so the panel's "
              "own rows stand" % raw, (rc, buf.getvalue()), (0, ""))

    print("--- the inbox, the silence, the compactions, the API error ---")
    def send(minute, target, second=0):
        """A SendMessage result: the message waits for `target`'s next round."""
        return {"type": "user", "timestamp": ts(minute, second),
                "message": {"content": [{"type": "tool_result",
                                         "tool_use_id": "sm%d%s" % (minute, target)}]},
                "toolUseResult": {"success": True, "message":
                                  "Message queued for delivery to %s at its "
                                  "next tool round." % target,
                                  "pin": {"id": target}}}
    def delivered(minute, kind="coordinator", **origin):
        return {"type": "attachment", "isSidechain": True, "timestamp": ts(minute),
                "attachment": {"type": "queued_command", "prompt": "hello",
                               "origin": dict(origin, kind=kind)}}
    ibox = os.path.join(tmp, "inbox")
    itr = session(ibox, "s2", agents=[
        ("agent-b1", [delivered(5),                        # woke it: queued
                      agent_user(10), agent_answer(11, "b", 10, 0, 0, 10),  # by nobody
                      delivered(12),                       # the 01:11 send
                      delivered(20, "peer", handback=True),  # a report home
                      delivered(21, "human"),              # typed in its pane
                      {"type": "user", "isSidechain": True, "isMeta": True,
                       "timestamp": ts(37), "origin": {"kind": "coordinator"},
                       "message": {"content": "The coordinator sent a message "
                                   "while you were working:\nhello"}},  # 01:35's
                      {"type": "system", "subtype": "compact_boundary",
                       "timestamp": ts(22)}],
         {"agentType": "Explore"}),
        ("agent-b2", [agent_user(10), send(30, "b1"),     # b2 sends b1 one
                      agent_answer(40, "c", 10, 0, 0, 10)], {"agentType": "Plan"}),
    ])
    write_jsonl(itr, [{"type": "user", "userType": "external",
                       "timestamp": ts(1), "message": {"content": "go"}},
                      send(11, "b1"), send(35, "b1"), send(36, "gone")])
    b1 = sl.agent_file_for(itr, "b1")
    check("sends matched to deliveries by time, in both shapes a delivery "
          "takes: two delivered, a peer's still waiting; a delivery with "
          "nothing queued before it, a hand-back and a typed message take none "
          "away, and a send to an agent not on the panel counts for nothing",
          sl.inbox_counts([itr, sl.agent_file_for(itr, "b2")], {"b1": b1}),
          {"b1": 1})
    check("a compaction is counted, and the last record of any kind is when "
          "it was last heard from",
          (sl.read_agent_usage(b1).compactions, sl.read_agent_usage(b1).last_seen),
          (1, sl.ts_epoch(ts(22))))
    ipay = {"session_id": "s2", "transcript_path": itr, "columns": 220, "cwd": ibox,
            "tasks": [task("b1"), task("b2", contextWindowSize=None,
                                       status="completed")]}
    irows = render(sl, ipay)[1]
    # The spinner keeps no column (2026-10-19), so past it.
    unspun = lambda r: r.lstrip(sl.E_SPIN)
    check("📨 and 🤏 on the row that has them, and a blank of their width on "
          "the row that does not, so the columns after them hold",
          ("\U0001F4E81 " in irows["b1"], "\U0001F90F1" in irows["b1"],
           sl.vis_width(unspun(irows["b1"])[:unspun(irows["b1"]).index("Marigold")])
           == sl.vis_width(irows["b2"][:irows["b2"].index("Marigold")]),
           sl.vis_width(irows["b1"][:irows["b1"].index("⌛")])
           == sl.vis_width(irows["b2"][:irows["b2"].index("⌛")])),
          (True, True, True, True))
    wide = {"inbox": 3, "compact": 3}
    plain, padded = (unpainted(sr.render_agent_row(task("x"), sl.NO_AGENT_USAGE, {}, {},
                                                     sl.NO_LIMITS, 300, now=NOW, kids_w=kw,
                                                     widths=w))
                     for kw, w in ((0, {}), (3, wide)))
    at = plain.index("Marigold")                # where the name starts
    check("the counts only some panels draw follow the kind and state: on a "
          "row that draws none of them they are one blank there, the name "
          "after it, and the grid's columns are where a panel without them "
          "has them",
          (padded[:at], padded.index("Marigold") - at,
           padded[padded.index("\U0001F916O"):]),
          (plain[:at], 3 + 1 + 3 + 1 + 3 + 1, plain[plain.index("\U0001F916O"):]))
    check("🧠's share is blank where the payload gives no window",
          re.search("\U0001F9E0 *\\S+ +(\\S+)", irows["b2"]).group(1)[0], "\U0001F9E9")
    nothing = sl.NO_AGENT_USAGE
    check("none of the four costs a column on a panel where no row has one",
          sr.panel_widths([(task("x"), nothing, {}, None)], NOW),
          {"inbox": 0, "compact": 0, "shells": 0, "monitors": 0})
    bg = nothing._replace(background=(("s1", "bash"), ("s2", "bash"), ("m1", "monitor")))
    check("💻 and 📡 count its open shells and Monitors while it runs and while "
          "it is paused on them, and not once it failed or was killed",
          [(unpainted(sr.render_background(sr.E_MODE_SHELL, sr.background_count(st, bg, "bash"))),
            unpainted(sr.render_background(sr.E_MODE_MONITOR, sr.background_count(st, bg, "monitor"))))
           for st in ("running", "completed", "failed", "killed")],
          [("\U0001F4BB2", "\U0001F4E11"), ("\U0001F4BB2", "\U0001F4E11"),
           ("", ""), ("", "")])
    check("each kept on every row once any row has one, as wide as the widest",
          sr.panel_widths([(task("x"), bg, {}, None),
                           (task("y"), nothing._replace(background=tuple(
                               ("s%d" % i, "bash") for i in range(12))), {}, None),
                           (task("z", status="killed"), bg, {}, None)], NOW),
          {"inbox": 0, "compact": 0, "shells": 4, "monitors": 3})
    bgrow = unpainted(sr.render_agent_row(task("x"), bg, {}, {}, sl.NO_LIMITS, 300, now=NOW,
                                             widths={"shells": 3, "monitors": 3}))
    check("on the row after 🤏's place and before 📨's, right of the state",
          bgrow[:bgrow.index("Marigold")].split()[-2:], ["\U0001F4BB2", "\U0001F4E11"])
    doing = lambda st, u, w=False, rate=None, t=None: unpainted(sr.render_doing(st, u, w, rate, NOW, t))
    quiet = nothing._replace(eta=(), last_seen=NOW - 90)
    check("the Doing cell says what a running agent is doing and for how "
          "long: 🔧 or 🚦 since the oldest call of its kind, the unit where "
          "the rate's / stands",
          [doing("running", quiet._replace(pending=p)) for p in (
              ((NOW - 42, "Bash"), (NOW - 5, "Read")),
              ((NOW - 90, "Agent"), (NOW - 5, "Bash")),
              ((NOW - 700, "AskUserQuestion"),))],
          ["\U0001F527  42s", "\U0001F6A6 1.5m", "\U0001F6A6  12m"])
    check("🤖 keeps the rate while it writes, and trades it for how long it "
          "has written nothing from a minute, amber from ten",
          ([doing("running", nothing._replace(eta=(), last_seen=NOW - q), rate=200.0)
            for q in (30, 90, 700)],
           sl.F_AMB in drawn(sr.render_doing(
               "running", nothing._replace(eta=(), last_seen=NOW - 700),
               False, 200.0, NOW)),
           sl.F_AMB in drawn(sr.render_doing("running", quiet, False, 200.0,
                                             NOW))),
          (["\U0001F916 200 ", "\U0001F916 1.5m", "\U0001F916  12m"], True, False))
    check("paused or ended, since its last record; not started, since its "
          "startTime; a shell keeps 🛫 and its rate",
          [doing("completed", quiet._replace(background=(("b1", "bash"),))),
           doing("completed", quiet, True),
           doing("pending", nothing, t={"startTime": int((NOW - 20) * 1000)}),
           doing("completed", quiet), doing("killed", quiet),
           doing("running", nothing, rate=80.0), doing("running", nothing)],
          ["\U0001F4BB 1.5m", "\U0001F4A4 1.5m", "\U0001F95A  20s",
           "\u2705 1.5m", "\U0001F6D1 1.5m", "\U0001F6EB  80 ", ""])
    died = nothing._replace(api_error=True)
    check("💥: an agent whose last answer died on an API error, ended or "
          "parked; a killed one is still 🛑, and a running one is running",
          [unpainted(sr.render_state(st, u, w)) for st, u, w in (
              ("completed", died, False), ("completed", died, True),
              ("failed", died, False), ("killed", died, False),
              ("running", died, False))],
          ["⚫\U0001F4A5", "\U0001F7E1\U0001F4A5", "⚫\U0001F4A5",
           "⚫\U0001F6D1", "\U0001F7E2"])
    check("read off its last assistant record: an error it answered past "
          "is forgotten",
          [sl.read_agent_usage(write_jsonl(os.path.join(tmp, "e%d.jsonl" % i), recs)
                               or os.path.join(tmp, "e%d.jsonl" % i)).api_error
           for i, recs in enumerate((
               [agent_answer(11, "a", 1, 0, 0, 1),
                dict(agent_answer(12, "b", 0, 0, 0, 0), isApiErrorMessage=True)],
               [dict(agent_answer(11, "a", 0, 0, 0, 0), isApiErrorMessage=True),
                agent_answer(12, "b", 1, 0, 0, 1)]))],
          [True, False])

    print("--- the worktree an agent works in ---")
    def checkout(path, head, linked=False):
        os.makedirs(path, exist_ok=True)
        gitdir = os.path.join(path, ".git")
        if linked:
            gitdir = os.path.join(tmp, "gitdirs", os.path.basename(path))
            os.makedirs(gitdir, exist_ok=True)
            with open(os.path.join(path, ".git"), "w") as fh:
                fh.write("gitdir: %s\n" % gitdir)
        else:
            os.makedirs(gitdir, exist_ok=True)
        with open(os.path.join(gitdir, "HEAD"), "w") as fh:
            fh.write(head + "\n")
    repo = os.path.join(tmp, "repo")
    wt = os.path.join(repo, ".claude", "worktrees", "agent-x")
    checkout(repo, "ref: refs/heads/master")
    checkout(wt, "ref: refs/heads/fix-inbox", linked=True)
    checkout(os.path.join(tmp, "detached"), "0123456789abcdef")
    os.makedirs(os.path.join(repo, "src"), exist_ok=True)
    check("a linked worktree's branch, even under the session's checkout; "
          "nothing for the session's own checkout or no checkout at all; a "
          "detached HEAD by its commit",
          [sl.worktree_branch(c, repo) for c in (
              wt, os.path.join(repo, "src"), "", os.path.join(tmp, "detached"))],
          ["fix-inbox", "", "", "0123456"])
    # The label's pieces, each under the path --hide names it by.
    pieces = lambda br: [(p.path, unpainted(p.spans)) for p in sr.agent_label(
        task("x", label="Reading"), NS(branch=br), {})[1:]]
    check("🌿 and the branch after the name, ahead of the activity, a long "
          "one cut to A_BRANCH_W",
          (pieces("fix-inbox"), pieces("feature/a-long-branch-name")[1][1]),
          ([("name.label", "Marigold  "),
            ("workspace.branch", "\U0001F33Ffix-inbox  "),
            ("chat.doing", "Reading")],
           "\U0001F33F" + sl.fit_cols("feature/a-long-branch-name", sr.A_BRANCH_W) + "  "))

    rc, rows = render(sl, pay, ["--usage-source", "native"])
    check("no plan reading: the 🔋 and 🪫 cells are blank, the rest stands",
          ("\U0001F50B" in rows["a1"], "\U0001F4B0" in rows["a1"]),
          (False, True))
    rc, hid = render(sl, pay, ["--hide", "*.work", "--hide", "agent.state.rate",
                               "--hide", "agent.name.kind"])
    at_cost = lambda r: sl.vis_width(r[:r.index("\U0001F4B0")])
    check("--hide, repeatable: 💾 hidden on every row is removed and the "
          "columns close up to the right edge; the 🛫 column, hidden on agent "
          "rows alone, keeps its place blank, since the band's 🤖💬 row can "
          "draw it; and the kind leaves the label",
          ("\U0001F4BE" in hid["a1"], "1.2h   \U0001F4B0" in hid["a1"],
           at_cost(hid["a1"]) - at_cost(rows["a1"]),
           hid["a1"].startswith("Marigold")),
          (False, False, sr.grid.cell_width("A_DIFF_W") + 2, True))

    print()
    line, status = tally()
    print(line)
    return status


if __name__ == "__main__":
    sys.exit(main())
