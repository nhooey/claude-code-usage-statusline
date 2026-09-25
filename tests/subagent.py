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


def agent_result(minute, tid, second=0):
    """And the result that answers it, which is where the tool's clock stops."""
    return {"type": "user", "isSidechain": True, "timestamp": ts(minute, second),
            "message": {"content": [{"type": "tool_result",
                                     "tool_use_id": tid}]}}


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
    # The recursion is over parentAgentId, which is the only place the tree
    # is written down: p spawned k, and x is a sibling that belongs to
    # neither.
    tt = session(tmp, "tools", agents=[
        ("agent-p", [agent_user(10), agent_call(11, "r1", "t1"),
                     agent_result(14, "t1")], {"agentType": "Explore"}),
        ("agent-k", [agent_user(20), agent_call(21, "r2", "t2"),
                     agent_result(29, "t2")],
         {"agentType": "Explore", "parentAgentId": "p", "spawnDepth": 2}),
        ("agent-x", [agent_user(30), agent_call(31, "r3", "t3"),
                     agent_result(35, "t3")], {"agentType": "Explore"}),
    ])
    check("an agent's tool time is its own and every descendant's, and an "
          "agent it did not spawn is not in it",
          round(sl.union_seconds(
              sl.agent_tool_spans(sl.agent_file_for(tt, "p"))) / 60),
          3 + 8)
    check("the child's own reading is the child alone",
          round(sl.union_seconds(
              sl.agent_tool_spans(sl.agent_file_for(tt, "k"))) / 60), 8)
    check("a task with no transcript — a shell — has none",
          sl.agent_tool_spans(""), [])
    check("the two cells split the agent's life: the clock is its run less "
          "its tools, and \U0001F527 blanks at nothing rather than drawing a zero",
          [ANSI.sub("", x) for x in (
              sr.render_agent_clock(int((NOW - 900) * 1000), NOW, None, 300.0),
              sr.render_agent_tool(300.0), sr.render_agent_tool(0.0))],
          ["\U0001F916 10m", "\U0001F527  5m", ""])
    check("a tool reading larger than the run cannot drive the clock below "
          "zero", ANSI.sub("", sr.render_agent_clock(
              int((NOW - 60) * 1000), NOW, None, 9999.0)),
          "\U0001F916  0s")

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
    check("the state cell: a coloured circle, or two letters for a state "
          "never seen",
          [ANSI.sub("", sr.render_state(x)) for x in
           ("running", "completed", "killed", "failed", "pending", "odd", "")],
          ["\U0001F7E2", "\U0001F535", "\u26AB", "\U0001F534", "\U0001F7E1",
           "od", ""])
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
        "\U0001F916O\u2075\U0001F3C3",
        " " * sr.A_CLOCK_W,             # 🔧: a1 pairs no tool call
        "\U0001F916 13m",
        sl.seg(sl.vis_width(sl.S_COST) + 4,
               "\U0001F4B0" + sl.pad_val(4, sl.money_fig(u.cost))),
        "\U0001F9E0 41k",
        sl.seg(sl.vis_width(sl.S_TOK) + sl.VAL_W + sl.VAL2_W,
               ANSI.sub("", sl.render_tokens(u.tok_up, u.tok_down))),
        "\U0001F6EB200/s",
        "\U0001F3AF%d%s" % (u.cache_pct, sl.E_PCT),
        "\U0001F50B" + sl.pad_val(4, pct(want)),
        "\U0001FAAB" + sl.pad_val(4, pct(want / 10.0)),
        ANSI.sub("", sl.render_diff("12", "4"))))
    head = "\U0001F50D\U0001F7E2 a1         "
    check("an agent's row: the left group, the name, then the right group, "
          "filling the payload's columns exactly",
          rows["a1"], head + sl.seg(200 - sl.vis_width(head) - 2
                                    - sl.vis_width(right), "Marigold")
          + "  " + right)
    check("no margin: the panel's width is already net of its chrome",
          sl.vis_width(rows["a1"]), 200)
    check("the right group ends at the same column on every row",
          len({sl.vis_width(r) for r in (rows["a1"], rows["a2"])}), 1)
    check("no sidecar: the task's kind, and the transcript's model where "
          "the payload has none",
          (rows["a2"].startswith("\U0001F465\U0001F535 "),
           "\U0001F916O\u2075" in rows["a2"]),
          (True, True))
    check("a finished agent shows no rate", "\U0001F6EB" in rows["a2"], False)
    check("an agent that wrote nothing still states it; a task with no "
          "transcript to count states nothing, as its 💰 does",
          ("\U0001F4BE +   0 -   0" in ANSI.sub("", rows["a2"]),
           "\U0001F4BE" in rows["bash-1"]),
          (True, False))
    check("and its clock stopped at its last record, not at now",
          re.search(r"\U0001F916\s+(\S+)", rows["a2"]).group(1), "1m")
    check("an unnamed task takes its description for a name, then its "
          "label for what it is doing; a shell shows nothing it did not bill",
          re.sub(r" {2,}", "  ", rows["bash-1"]),
          "\U0001F41A\U0001F7E2 bash-1  npm test npm test --watch  \U0001F916 13m")
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
    at_model = lambda r: sl.vis_width(r[:r.index("\U0001F916")])
    check("and the right group is what holds its column: the name gives",
          [at_model(rows_n[t]) + 2 * (d - 1)
           for t, d in (("a1", 1), ("a3", 2), ("a4", 3))],
          [at_model(rows_n["a1"])] * 3)
    long = "Review the plan, then the code under it, then the docs beside it"
    wide = dict(pay, tasks=[task("a1", name="", description=long)])
    check("the name takes what the metrics leave, and gives way first",
          (render(sl, dict(wide, columns=400))[1]["a1"].count(long),
           re.search(r"Review the plan, [^…]*…  \U0001F916",
                     # 138 and not the 130 it was: the right group grew by the
                     # 🔧 cell and its gap, and this case is about a width
                     # that squeezes the NAME, not one that squeezes it away.
                     render(sl, dict(wide, columns=138))[1]["a1"]) is not None,
           render(sl, dict(wide, columns=None), ["--cols", "0"])[1]["a1"]
           .count(long[:sr.A_NAME_MIN - 1] + "…")),
          (1, True, 1))

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
