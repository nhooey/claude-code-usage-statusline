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


ANSI = re.compile(r"\x1b\[[0-9;]*m")

# 2026-08-16 02:23:20 UTC — pin-env.sh's PIN_NOW, so the two suites agree
# about what "now" is and the plan cache below is read as fresh.
NOW = 1786847000.0


def ts(minute, second=0):
    return "2026-08-16T01:%02d:%02dZ" % (minute, second)


def agent_user(minute, pid="p1"):
    return {"type": "user", "isSidechain": True, "promptId": pid,
            "timestamp": ts(minute), "message": {"content": "do a thing"}}


def agent_answer(minute, rid, fresh, cw, cr, out, model="claude-opus-5",
                 effort="high", second=0):
    return {"type": "assistant", "requestId": rid, "isSidechain": True,
            "timestamp": ts(minute, second), "effort": effort,
            "message": {"id": rid, "model": model, "usage": {
                "input_tokens": fresh,
                "cache_creation_input_tokens": cw,
                "cache_read_input_tokens": cr,
                "output_tokens": out}}}


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
    os.environ["CLAUDE_STATUSLINE_NOW"] = "%d" % NOW
    os.environ["CLAUDE_PLAN_CACHE"] = os.path.join(tmp, "plan.json")
    os.environ["CLAUDE_CALIB_CACHE"] = os.path.join(tmp, "calib.json")
    os.environ["CLAUDE_LIMIT_CACHE"] = os.path.join(tmp, "app.json")
    os.environ["CLAUDE_USAGE_SOURCE"] = "none"
    os.environ["TMPDIR"] = tmp          # the debug tap writes here if armed
    os.environ.pop("TMUX", None)
    os.environ.pop("TERM_PROGRAM", None)
    os.environ["TERMINAL_EMULATOR"] = "JetBrains-JediTerm"
    with open(os.environ["CLAUDE_PLAN_CACHE"], "w") as fh:
        json.dump({"session_pct": "41", "session_resets_at": "2026-08-16 04:00",
                   "weekly_pct": "63", "weekly_resets_at": "2026-08-18 01:00",
                   "as_of": "2026-08-16 02:20"}, fh)
    with open(os.environ["CLAUDE_CALIB_CACHE"], "w") as fh:
        json.dump({"sess": 1.0, "week": 10.0}, fh)   # $1 and $10 per point

    sl = load_program()
    OPUS = sl._price("claude-opus-5")

    print("--- finding the transcript ---")
    tr = session(tmp, "s1", agents=[
        ("agent-a1", [agent_user(10),
                      agent_answer(11, "r1", 100, 2000, 30000, 400),
                      agent_answer(11, "r1", 100, 2000, 30000, 400,
                                   second=30),                 # a retry
                      agent_answer(12, "err", 0, 0, 0, 0),     # an API error
                      agent_answer(13, "r2", 50, 1000, 40000, 600,
                                   model="claude-sonnet-5", effort="low")],
         {"agentType": "Explore", "model": "sonnet"}),
        ("agent-a2", [agent_user(10), agent_answer(11, "x", 10, 0, 0, 10)],
         None),                                                # no sidecar
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
         sl.token_rate([100, 200, 400], "running"), 300 / 10.0)
    check("no rate for a finished task or a single sample",
          (sl.token_rate([100, 200], "completed"),
           sl.token_rate([100], "running"), sl.token_rate(None, "running")),
          (None, None, None))
    check("the type cell: sidecar type first, then the task kind, then 👥",
          [ANSI.sub("", sl.render_kind(a, k)) for a, k in (
              ("Explore", "local_agent"), ("", "local_bash"),
              ("", "local_agent"), ("my-reviewer", "local_agent"))],
          ["\U0001F50D", "\U0001F41A", "\U0001F465", "\U0001F465"])
    check("the state cell: a coloured circle, or two letters for a state "
          "never seen",
          [ANSI.sub("", sl.render_state(x)) for x in
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
          [ANSI.sub("", sl.render_agent_cache(v)) for v in (94, 100, 5, -1)],
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
        "⌛ 13m",
        sl.seg(sl.vis_width(sl.S_TOK) + sl.VAL_W + sl.VAL2_W,
               ANSI.sub("", sl.render_tokens(u.tok_up, u.tok_down))),
        "\U0001F6EB200/s",
        "\U0001F3AF%d%s" % (u.cache_pct, sl.E_PCT),
        "\U0001F9E0 41k",
        sl.seg(sl.vis_width(sl.S_COST) + 4,
               "\U0001F4B0" + sl.pad_val(4, sl.money_fmt(u.cost))),
        "\U0001F50B" + sl.pad_val(4, pct(want)),
        "\U0001FAAB" + sl.pad_val(4, pct(want / 10.0))))
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
    check("and its clock stopped at its last record, not at now",
          re.search(r"⌛\s*(\S+)", rows["a2"]).group(1), "1m")
    check("an unnamed task takes its description for a name, then its "
          "label for what it is doing; a shell shows nothing it did not bill",
          re.sub(r" {2,}", "  ", rows["bash-1"]),
          "\U0001F41A\U0001F7E2 bash-1  npm test npm test --watch  ⌛ 13m")
    check("a name and its activity, and a label that only repeats the "
          "description is not drawn",
          [ANSI.sub("", sl.render_who(n, a, 40)) for n, a in (
              ("Marigold", "Reading the plan"), ("Marigold", ""),
              ("", "Reading the plan"), ("", ""))],
          ["Marigold Reading the plan", "Marigold", "Reading the plan", ""])
    check("the activity gives way first, then the name",
          [ANSI.sub("", sl.render_who("Marigold", "Reading the plan, slowly",
                                      w)) for w in (30, 20, 12, 6)],
          ["Marigold Reading the plan, sl…", "Marigold Reading th…",
           "Marigold", "Marig…"])
    long = "Review the plan, then the code under it, then the docs beside it"
    wide = dict(pay, tasks=[task("a1", name="", description=long)])
    check("the name takes what the metrics leave, and gives way first",
          (render(sl, dict(wide, columns=400))[1]["a1"].count(long),
           re.search(r"Review the plan, [^…]*…  \U0001F916",
                     render(sl, dict(wide, columns=130))[1]["a1"]) is not None,
           render(sl, dict(wide, columns=None), ["--cols", "0"])[1]["a1"]
           .count(long[:sl.A_NAME_MIN - 1] + "…")),
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

    os.unlink(os.environ["CLAUDE_PLAN_CACHE"])
    rc, rows = render(sl, pay)
    check("no plan reading: the 🔋 and 🪫 cells are blank, the rest stands",
          ("\U0001F50B" in rows["a1"], "\U0001F4B0" in rows["a1"]),
          (False, True))

    print()
    print("pass %d   fail %d" % (pass_n, fail_n))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
