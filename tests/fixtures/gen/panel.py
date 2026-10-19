#!/usr/bin/env python3
"""Write the agent panel's shared cases: its end-to-end inputs, and its rows
drawn from the renderer's own inputs.

    python3 tests/fixtures/gen/all.py       # this and the rest, together
    python3 tests/fixtures/gen/panel.py --check   # rerun, compare, write nothing

Two levels, so the TypeScript port can be checked at either:

  END TO END.  The subagentStatusLine payloads under payloads/subagent/ and
  the session transcripts they point at, under transcripts/subagent/.  The
  `subagent` suite in cases.json runs them through `--mode subagent` in a
  pinned environment, and tests/run-cases.py compares the JSON lines the
  program prints with tests/golden/subagent/.

  RENDER.  panel/<group>.json: render_task_rows' inputs — the prepared
  `(task, usage, meta, shares)` records, the plan Limits, the width and the
  clock — and the rows it draws for them, each as the joined string with its
  escape codes and as the spans it was joined from.  A group is one set of
  process settings, since the terminal profile is read at import and the
  two switches are set once per process: the profile's environment, mark
  spacing and subscript decimals.  `corpus*.json` are the inputs the
  end-to-end cases prepared, captured on their way into render_task_rows,
  so their rows are the goldens' rows; the rest are made here by hand, for
  the states that corpus does not reach, and say what each is for.

THE INPUT SHAPES.  A task, meta and shares are the dicts the renderer gets.
A usage is AgentUsage's fields by name, or null; a field missing from it
reads as the renderer's getattr default, which the hand-made `missing` group
pins, since the renderer is written against attributes and not the type.
Tuples are lists.  Limits are Limits' fields by name.  `cols` is the
terminal's width, and `hide`, the --hide paths, is left out where there are
none.  Floats are written
with repr; see records.py.  A row is {"id", "row", "spans"}: the pair
render_task_rows returns, and the spans render_agent_row made for it, which
it joins without `close` or `runs`; see span_json.  A case whose tasks hold
none with an id draws no rows.

ONLY THIS SIDE WRITES THEM.  Each group renders in a child process of its
own, `panel.py --render`, under /usr/bin/python3 by default; `--check` does
the same and compares, which is what tests/run-cases.py runs as its `panel`
stage.  The capture runs the program the way run-cases.py does, through its
Suite, so a corpus case and its golden are one run.
"""
import copy
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
TESTS = os.path.dirname(FIXTURES)
REPO = os.path.dirname(TESTS)
OUT = os.path.join(FIXTURES, "panel")
PYTHON = "/usr/bin/python3"

sys.path.insert(0, HERE)
from cases import PIN_NOW, SUBAGENT_PAYLOADS  # noqa: E402

NOW = float(PIN_NOW)


def iso(before):
    """A timestamp `before` seconds earlier than PIN_NOW."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(PIN_NOW - before))


def enc(v):
    """A value as JSON both languages read the same; see records.py."""
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        if math.isnan(v):
            return {"$float": "nan"}
        if math.isinf(v):
            return {"$float": "inf" if v > 0 else "-inf"}
        if v == 0 and math.copysign(1.0, v) < 0:
            return {"$float": "-0"}
        return v
    if hasattr(v, "_asdict"):
        return {k: enc(x) for k, x in v._asdict().items()}
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    if isinstance(v, dict):
        return {str(k): enc(x) for k, x in v.items()}
    if hasattr(v, "__dict__"):           # a SimpleNamespace usage
        return {k: enc(x) for k, x in sorted(vars(v).items())}
    raise TypeError("cannot write %r" % (v,))


def oneline(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def dump(data):
    """A group's file: a case's input on one line and each of its rows on
    one of its own, so a diff names the row that moved and the file stays a
    fraction of what indenting every span would make it."""
    cases = []
    for c in data["cases"]:
        rows = ",\n".join("   " + oneline(r) for r in c["rows"])
        cases.append('  {"id": %s,\n   "input": %s,\n   "rows": [%s]}'
                     % (oneline(c["id"]), oneline(c["input"]),
                        "\n" + rows + "\n   " if rows else ""))
    return '{"settings": %s,\n "cases": [\n%s\n ]}\n' % (
        oneline(data["settings"]), ",\n".join(cases))


# ════════════════════════════════════════════════════════════════════════════
# End to end: the sessions and the payloads.
# ════════════════════════════════════════════════════════════════════════════
#
# Each session is a main transcript with its agents' files beside it, laid
# out as Claude Code lays them, and a payload naming its tasks.  The records
# are the minimum shapes the readers recognise (see status.py), stamped
# seconds before PIN_NOW so every clock on the rows is a chosen figure.

ETA = "⛳ skills/coding-agent-usage-line-report-eta: ETA "


def a_prompt(before, text="do a thing"):
    return {"type": "user", "userType": "external", "isSidechain": True,
            "promptId": "p1", "timestamp": iso(before),
            "message": {"content": text}}


def a_answer(before, rid, fresh=100, cw=2000, cr=30000, out=400, text=None,
             tool=None, end=False, model="claude-opus-5", effort="high",
             **extra):
    """An agent's billed answer: `text` a text block, `tool` (id, name) a
    call, `end` the stop_reason that ends its turn."""
    blocks = [{"type": "text", "text": text}] if text is not None else []
    if tool:
        blocks.append({"type": "tool_use", "id": tool[0], "name": tool[1]})
    msg = {"id": rid, "model": model, "content": blocks, "usage": {
        "input_tokens": fresh, "cache_creation_input_tokens": cw,
        "cache_read_input_tokens": cr, "output_tokens": out}}
    if end:
        msg["stop_reason"] = "end_turn"
    r = {"type": "assistant", "requestId": rid, "isSidechain": True,
         "timestamp": iso(before), "effort": effort, "message": msg}
    r.update(extra)
    return r


def a_result(before, tid, **res):
    """A tool's result, `res` its toolUseResult."""
    r = {"type": "user", "isSidechain": True, "timestamp": iso(before),
         "message": {"content": [{"type": "tool_result",
                                  "tool_use_id": tid}]}}
    if res:
        r["toolUseResult"] = res
    return r


def a_edit(before, tid, added, removed):
    return a_result(before, tid, filePath="/f", structuredPatch=[
        {"oldStart": 1, "oldLines": 1, "newStart": 1, "newLines": 1,
         "lines": [" keep"] + ["-old"] * removed + ["+new"] * added}])


def compact(before):
    return {"type": "system", "subtype": "compact_boundary",
            "timestamp": iso(before)}


def send(before, target):
    """A SendMessage result: the message waits for `target`'s next round."""
    return {"type": "user", "timestamp": iso(before),
            "message": {"content": [{"type": "tool_result",
                                     "tool_use_id": "sm%d%s" % (before, target)}]},
            "toolUseResult": {"success": True, "message":
                              "Message queued for delivery to %s at its "
                              "next tool round." % target}}


def task(tid, name, status="running", before=900, kind="local_agent",
         samples=(), **kw):
    """A payload task as the panel hands it: `before` its start."""
    t = {"id": tid, "name": name, "type": kind, "status": status,
         "description": "Review the %s plan" % name.lower(),
         "label": "", "startTime": int((PIN_NOW - before) * 1000),
         "model": "claude-opus-5", "effort": "high",
         "contextWindowSize": 200000, "tokenCount": 0,
         "tokenSamples": list(samples), "cwd": "${SCRATCH}/repo"}
    t.update(kw)
    return t


def meta(agent_type, parent=None, depth=1):
    m = {"agentType": agent_type, "spawnDepth": depth}
    if parent:
        m["parentAgentId"] = parent
    return m


# name: (main transcript records, {agent id: (records, meta or None, path
# under subagents/ or None)}, payload tasks)
def sessions():
    out = {}

    # Every state a row can be in once: the three running modes, a quiet one,
    # each way to end, an API error, a queued task, a shell with no
    # transcript and a workflow agent one directory further down.
    out["01-mixed"] = ([], {
        "r1": ([a_prompt(700), a_answer(650, "r1a", text=ETA + "10m"),
                a_edit(645, "e1", 9, 4),
                a_answer(640, "r1b", tool=("t1", "Bash"))],
               meta("Explore"), None),
        "r2": ([a_prompt(400), a_answer(380, "r2a", tool=("t2", "Read")),
                a_result(370, "t2"),
                a_answer(20, "r2b", 300, 0, 60000, 900, text="reading",
                         model="claude-sonnet-5", effort="low")],
               meta("general-purpose"), None),
        "r3": ([a_prompt(300), a_answer(280, "r3a",
                                        tool=("t3", "AskUserQuestion"))],
               meta("Plan"), None),
        "r4": ([a_prompt(900), a_answer(800, "r4a", text="thinking")],
               meta("claude"), None),
        "d1": ([a_prompt(3000), a_answer(2900, "d1a", tool=("t4", "Bash")),
                a_result(2700, "t4"),
                a_answer(2500, "d1b", text="done\n" + ETA + "0s", end=True)],
               meta("Explore"), None),
        "f1": ([a_prompt(2000), a_answer(1900, "f1a", text="trying")],
               meta("general-purpose"), None),
        "k1": ([a_prompt(1500), a_answer(1400, "k1a", tool=("t5", "Bash"))],
               meta("general-purpose"), None),
        "e1": ([a_prompt(1200), a_answer(1150, "e1a", text="half"),
                a_answer(1100, "e1b", 0, 0, 0, 0, text="API Error: 529",
                         isApiErrorMessage=True)],
               meta("Explore"), None),
        "w1": ([a_prompt(600), a_answer(500, "w1a", 10, 0, 0, 10,
                                        text="step", model="claude-haiku-4-5",
                                        effort="")],
               meta("workflow-subagent"), "workflows/wf_x"),
    }, [
        task("r1", "Marigold", before=700, label="Running the suite"),
        task("r2", "Bluebell", before=400, model="sonnet", effort="low",
             samples=(1000, 2500, 4000, 6000)),
        task("r3", "Thistle", before=300),
        task("r4", "Clover", before=900),
        task("d1", "Daisy", "completed", before=3000),
        task("f1", "Fern", "failed", before=2000),
        task("k1", "Kale", "killed", before=1500),
        task("e1", "Elm", "completed", before=1200),
        task("q1", "Quince", "pending", before=30),
        task("b1", "", before=120, kind="local_bash",
             description="sleep 300 && make test", model=None, effort=None,
             contextWindowSize=None),
        task("w1", "Willow", before=600, model=None, effort=None),
    ])

    # Completed agents that are only waiting: on a shell, a Monitor, their own
    # ETA and an agent under them; and the ETA cell's other readings, late
    # and amber, signed off and running over in red, inherited from a child.
    out["02-parked"] = ([], {
        "p1": ([a_prompt(1000), a_answer(990, "p1a", tool=("t1", "Bash")),
                a_result(989, "t1", backgroundTaskId="sh1"),
                a_answer(980, "p1b", text="waiting on the build", end=True)],
               meta("general-purpose"), None),
        "p2": ([a_prompt(1000), a_answer(990, "p2a", tool=("t2", "Monitor")),
                a_result(989, "t2", taskId="mon1", timeoutMs=600000),
                a_answer(985, "p2b", tool=("t3", "Bash")),
                a_result(984, "t3", backgroundTaskId="sh2"),
                a_answer(980, "p2c", text="watching", end=True)],
               meta("general-purpose"), None),
        "p3": ([a_prompt(600), a_answer(300, "p3a",
                                        text="parked\n" + ETA + "20m",
                                        end=True)],
               meta("Plan"), None),
        "p4": ([a_prompt(1200), a_answer(1190, "p4a", tool=("t4", "Agent")),
                a_result(1180, "t4"),
                a_answer(1170, "p4b", text="waiting on c4\n" + ETA + "5m",
                         end=True)],
               meta("claude"), None),
        "c4": ([a_prompt(1180), a_answer(60, "c4a", text=ETA + "30m")],
               meta("Explore", "p4", 2), None),
        "s1": ([a_prompt(900), a_answer(600, "s1a", text=ETA + "2m"),
                a_answer(590, "s1b", tool=("t5", "Bash"))],
               meta("Explore"), None),
        "s2": ([a_prompt(900), a_answer(300, "s2a", text=ETA + "0s"),
                a_answer(200, "s2b", tool=("t6", "Bash"))],
               meta("Explore"), None),
        "x1": ([a_prompt(900), a_answer(800, "x1a", text="all done",
                                        end=True)],
               meta("Explore"), None),
    }, [
        task("p1", "Pine", "completed", before=1000),
        task("p2", "Poppy", "completed", before=1000),
        task("p3", "Peony", "completed", before=600),
        task("p4", "Parsley", "completed", before=1200),
        task("c4", "Chive", before=1180),
        task("s1", "Sage", before=900),
        task("s2", "Sorrel", before=900),
        task("x1", "Yarrow", "completed", before=900),
    ])

    # The tree four deep, with siblings and a bar down an open column; an
    # ancestor that finished, stepped over; a parent not on the panel; the
    # counts (👶🏻 🤏 📨) and a worktree's 🌿.
    out["03-tree"] = ([a_prompt(5000, "go"), send(100, "t2"),
                       send(90, "t3"), send(80, "t3")], {
        "t1": ([a_prompt(2000), compact(1900), compact(1500),
                a_answer(1400, "t1a", 500, 8000, 90000, 2000,
                         tool=("u1", "Agent")),
                a_answer(1390, "t1b", tool=("u2", "Agent"))],
               meta("claude"), None),
        "t2": ([a_prompt(1400), a_answer(50, "t2a", tool=("u3", "Bash"))],
               meta("Explore", "t1", 2), None),
        "t3": ([a_prompt(1390), a_answer(1300, "t3a", tool=("u4", "Agent"))],
               meta("general-purpose", "t1", 2), None),
        "t4": ([a_prompt(1300), a_answer(1200, "t4a", tool=("u5", "Agent"))],
               meta("general-purpose", "t3", 3), None),
        "t5": ([a_prompt(1200), a_answer(10, "t5a", text="deep")],
               meta("Explore", "t4", 4), None),
        "g1": ([a_prompt(4000), a_answer(3900, "g1a", text="fin", end=True)],
               meta("claude"), None),
        "g2": ([a_prompt(3950), a_answer(3800, "g2a", text="fin", end=True)],
               meta("Explore", "g1", 2), None),
        "m1": ([a_prompt(500), a_answer(400, "m1a", tool=("u6", "Bash"))],
               meta("Explore", "gone", 2), None),
    }, [
        task("t1", "Trunk", before=2000),
        task("t2", "Twig", before=1400),
        task("t3", "Thorn", before=1390),
        task("t4", "Tendril", before=1300, cwd="${SCRATCH}/repo-dirty"),
        task("t5", "Tip", before=1200),
        task("g1", "Gourd", "completed", before=4000),
        task("g2", "Garlic", "completed", before=3950),
        task("m1", "Moss", before=500),
    ])

    # Nothing but what the payload says: shells, a remote agent, a status
    # never seen, a task with no id and one that is not an object, which are
    # skipped, a name the description stands in for, a label that repeats
    # the description and is dropped.
    out["04-bare"] = ([], {}, [
        task("b1", "", before=60, kind="local_bash",
             description="npm test", samples=(0, 100)),
        task("b2", "", "completed", before=600, kind="local_bash",
             description="sleep 5"),
        task("ra", "Remote", "pending", before=5, kind="remote_agent"),
        task("xx", "Oddity", "paused", before=5),
        task("nn", "", before=5, description="A description for a name",
             label="A description for a name"),
        {"name": "no id", "status": "running"},
        "not a task",
    ])

    # An empty panel: no rows printed.
    out["05-empty"] = ([], {}, [])
    return out


def write_e2e(root):
    """Under ROOT/transcripts/subagent/ and ROOT/payloads/subagent/."""
    made = sessions()
    assert tuple(sorted(made)) == SUBAGENT_PAYLOADS, sorted(made)
    tdir = os.path.join(root, "transcripts", "subagent")
    for name, (main, agents, tasks) in sorted(made.items()):
        tr = os.path.join(tdir, name + ".jsonl")
        write_jsonl(tr, [{"type": "user", "userType": "external",
                          "promptSource": "typed", "timestamp": iso(6000),
                          "message": {"content": "go"}}] + main)
        for aid, (recs, m, sub) in sorted(agents.items()):
            d = os.path.join(tdir, name, "subagents", *(sub.split("/") if sub
                                                        else ()))
            write_jsonl(os.path.join(d, "agent-%s.jsonl" % aid), recs)
            if m is not None:
                with open(os.path.join(d, "agent-%s.meta.json" % aid), "w",
                          encoding="utf-8") as fh:
                    json.dump(m, fh, sort_keys=True)
                    fh.write("\n")
        pay = {"session_id": "subagent-" + name,
               "transcript_path": "${FIXTURES}/transcripts/subagent/%s.jsonl"
                                  % name,
               "cwd": "${SCRATCH}/repo", "columns": 160, "tasks": tasks}
        path = os.path.join(root, "payloads", "subagent", name + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(pay, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")


# ════════════════════════════════════════════════════════════════════════════
# Render: the hand-made inputs.
# ════════════════════════════════════════════════════════════════════════════

# The settings of a group: the terminal's environment (see PROFILE_RULES),
# and the two switches the CLI sets before anything renders.
JEDITERM = {"TERMINAL_EMULATOR": "JetBrains-JediTerm"}
DEFAULT = {"terminal": JEDITERM, "mark_spacing": True,
           "subscript_decimals": False}


def settings(**kw):
    s = dict(DEFAULT)
    s.update(kw)
    return s


# The plan readings: 41٪ and 63٪, as the corpus's app-41-63 source.
LIMITS = {"session_pct": "41", "session_reset": "2026-08-16 04:00",
          "session_share": "", "weekly_pct": "63",
          "weekly_reset": "2026-08-18 01:00", "weekly_share": "",
          "session_turn": "", "weekly_turn": ""}
NO_LIMITS = dict(LIMITS, session_pct="", session_reset="", weekly_pct="",
                 weekly_reset="")

# AgentUsage's fields and NO_AGENT_USAGE's values: what a shell or a remote
# agent, with no transcript, is prepared with.
BARE = {"tok_up": None, "tok_down": 0, "cache_pct": -1, "ctx_tokens": 0,
        "cost": 0.0, "parts": [], "model": "", "effort": "", "calls": 0,
        "last_epoch": None, "lines_added": 0, "lines_removed": 0,
        "tool_s": 0.0, "eta": None, "work": [], "open_at": None,
        "tools": [], "model_s": None, "waiting": [], "pending": [],
        "background": [], "compactions": 0, "last_seen": None,
        "api_error": False, "cwd": "", "blocks": 0, "inbox": 0,
        "ctx_window": 0, "branch": ""}


def usage(**kw):
    """An agent with a transcript: 12 minutes old, working on and off, a
    tool for a minute of it, last heard 30 seconds ago, no ETA yet."""
    u = dict(BARE, tok_up=48210, tok_down=3412, cache_pct=88,
             ctx_tokens=42125, cost=0.4321,
             parts=[[NOW - 600, 0.2], [NOW - 60, 0.2321]],
             model="claude-opus-5", effort="high", calls=4,
             last_epoch=NOW - 60, lines_added=12, lines_removed=3,
             tool_s=60.0, eta=[], work=[[NOW - 720, NOW - 30]],
             open_at=NOW - 30, tools=[[NOW - 400, NOW - 340]],
             model_s=300.0, last_seen=NOW - 30, blocks=7,
             ctx_window=200000)
    u.update(kw)
    return u


def ptask(tid, name="Marigold", status="running", before=720, **kw):
    t = {"id": tid, "name": name, "type": "local_agent", "status": status,
         "description": "Review the plan", "label": "",
         "startTime": int((NOW - before) * 1000), "model": "claude-opus-5",
         "effort": "high", "contextWindowSize": 200000, "tokenCount": 0,
         "tokenSamples": [], "cwd": "/x"}
    t.update(kw)
    return t


SHARES = {"sess": 1.5, "week": 12.25}


def row(t, u, m=None, sh=SHARES):
    return {"task": t, "usage": u, "meta": {} if m is None else m,
            "shares": sh}


class Group:
    """One fixture file: a settings and its cases, gathered then rendered."""

    def __init__(self, name, sets=DEFAULT):
        self.name, self.settings, self.cases = name, sets, []

    def case(self, cid, rows, cols=160, limits=LIMITS, now=NOW, hide=()):
        inp = {"tasks": rows, "limits": limits, "cols": cols, "now": now}
        if hide:
            inp["hide"] = list(hide)
        self.cases.append({"id": cid, "input": inp})


def g_states():
    g = Group("states")
    # Running: who has the floor — the model, a tool, a question or an agent
    # it waits on — and a row with no transcript to say.
    g.case("running-model", [row(ptask("a1"), usage())])
    g.case("running-model-rate", [row(
        ptask("a1", tokenSamples=[1000, 2000, 4000, 7000]), usage())])
    g.case("running-model-quiet", [row(ptask("a1"), usage(
        last_seen=NOW - 90, open_at=NOW - 90))])
    g.case("running-model-silent", [row(
        ptask("a1", tokenSamples=[1000, 9000]), usage(
            last_seen=NOW - 400, open_at=NOW - 400))])
    g.case("running-tool", [row(ptask("a1"), usage(
        pending=[[NOW - 42, "Bash"]], open_at=None))])
    g.case("running-wait-question", [row(ptask("a1"), usage(
        pending=[[NOW - 75, "AskUserQuestion"], [NOW - 10, "Bash"]],
        open_at=None))])
    g.case("running-wait-agent", [row(ptask("a1"), usage(
        pending=[[NOW - 300, "Agent"]], open_at=None))])
    g.case("running-no-transcript", [row(
        ptask("b1", "", type="local_bash", description="make test",
              tokenSamples=[0, 50, 100]), BARE, sh={"sess": None,
                                                    "week": None})])
    # Not started.
    g.case("queued", [row(ptask("q1", status="pending", before=8), BARE)])
    # Paused: on its agents, a shell, a Monitor, its ETA alone; and both
    # background kinds at once, where the shell's mark wins.
    g.case("paused-shell", [row(ptask("p1", status="completed"), usage(
        background=[["sh1", "bash"]], open_at=None, last_seen=NOW - 200))])
    g.case("paused-monitor", [row(ptask("p1", status="completed"), usage(
        background=[["mon1", "monitor"]], open_at=None,
        last_seen=NOW - 200))])
    g.case("paused-both", [row(ptask("p1", status="completed"), usage(
        background=[["mon1", "monitor"], ["sh1", "bash"], ["sh2", "bash"]],
        open_at=None, last_seen=NOW - 200))])
    g.case("paused-eta", [row(ptask("p1", status="completed"), usage(
        eta=[NOW - 120, 900.0], open_at=None, last_seen=NOW - 120))])
    g.case("paused-agents", [
        row(ptask("p1", status="completed", before=900), usage(
            open_at=None, last_seen=NOW - 500)),
        row(ptask("c1", "Chive", before=400), usage(),
            {"parentAgentId": "p1", "spawnDepth": 2})])
    # Ended, each way, with and without a billed transcript.
    for st in ("completed", "failed", "killed"):
        g.case("ended-" + st, [row(ptask("e1", status=st), usage(
            open_at=None, last_seen=NOW - 100, last_epoch=NOW - 100))])
    g.case("ended-killed-unbilled", [row(
        ptask("e1", status="killed"),
        dict(BARE, work=[[NOW - 700, NOW - 695]], model_s=4.0, eta=[]))])
    g.case("ended-shell", [row(
        ptask("b1", "", status="completed", type="local_bash",
              description="sleep 5"), BARE)])
    # An API error: ended, and paused where it still waits on something.
    g.case("api-error-ended", [row(ptask("e1", status="completed"), usage(
        api_error=True, open_at=None, last_seen=NOW - 100))])
    g.case("api-error-failed", [row(ptask("e1", status="failed"), usage(
        api_error=True, open_at=None))])
    g.case("api-error-paused", [row(ptask("e1", status="completed"), usage(
        api_error=True, eta=[NOW - 60, 600.0], open_at=None))])
    g.case("api-error-running", [row(ptask("e1"), usage(api_error=True))])
    # A status never seen, and none at all.
    g.case("status-unknown", [row(ptask("u1", status="paused"), usage())])
    g.case("status-empty", [row(ptask("u1", status=""), usage())])
    # The spinner steps a frame per block it has written.
    for n in (0, 1, 5, 11, 12):
        g.case("spin-%d" % n, [row(ptask("a1"), usage(blocks=n))])
    # The kind marks.
    for kind in ("general-purpose", "claude", "Explore", "Plan", "fork",
                 "workflow-subagent", "statusline-setup"):
        g.case("kind-" + kind, [row(ptask("a1"), usage(),
                                    {"agentType": kind})])
    g.case("kind-from-task-type", [row(
        ptask("a1", type="local_bash"), usage())])
    return g


def g_eta():
    g = Group("eta")
    g.case("none-yet", [row(ptask("a1"), usage(eta=[]))])
    g.case("live", [row(ptask("a1"), usage(eta=[NOW - 60, 600.0]))])
    g.case("live-short", [row(ptask("a1"), usage(eta=[NOW - 5, 45.0]))])
    g.case("live-hours", [row(ptask("a1"), usage(eta=[NOW - 60, 7200.0]))])
    g.case("late", [row(ptask("a1"), usage(eta=[NOW - 600, 120.0]))])
    g.case("late-long", [row(ptask("a1"), usage(eta=[NOW - 9000, 60.0]))])
    g.case("signed-off-over", [row(ptask("a1"), usage(eta=[NOW - 300, 0.0]))])
    g.case("signed-off-now", [row(ptask("a1"), usage(eta=[NOW, 0.0]))])
    g.case("completed-finished", [row(
        ptask("a1", status="completed"), usage(eta=[], open_at=None))])
    g.case("parked-late", [row(
        ptask("a1", status="completed"), usage(eta=[NOW - 900, 300.0],
                                               open_at=None))])
    g.case("no-transcript", [row(ptask("b1", type="local_bash"), BARE)])
    # Inherited: a parent's ⛳ counts to the latest finish under it; its own
    # wins when it runs longer; a killed child counts for nothing; a signed
    # off parent pushed out by a child is not running over.
    kid = {"parentAgentId": "p1", "spawnDepth": 2}
    g.case("inherited-child-longer", [
        row(ptask("p1", before=900), usage(eta=[NOW - 60, 300.0])),
        row(ptask("c1", "Chive", before=600), usage(eta=[NOW - 30, 1800.0]),
            kid)])
    g.case("inherited-own-longer", [
        row(ptask("p1", before=900), usage(eta=[NOW - 60, 3600.0])),
        row(ptask("c1", "Chive", before=600), usage(eta=[NOW - 30, 600.0]),
            kid)])
    g.case("inherited-killed-child", [
        row(ptask("p1", before=900), usage(eta=[NOW - 60, 300.0])),
        row(ptask("c1", "Chive", status="killed", before=600),
            usage(eta=[NOW - 30, 1800.0]), kid)])
    g.case("inherited-signed-off-parent", [
        row(ptask("p1", before=900), usage(eta=[NOW - 60, 0.0])),
        row(ptask("c1", "Chive", before=600), usage(eta=[NOW - 30, 600.0]),
            kid)])
    g.case("inherited-no-own", [
        row(ptask("p1", status="completed", before=900),
            usage(eta=[], open_at=None)),
        row(ptask("c1", "Chive", before=600), usage(eta=[NOW - 30, 600.0]),
            kid),
        row(ptask("c2", "Cress", before=500), usage(eta=[NOW - 30, 900.0]),
            kid)])
    g.case("inherited-grandchild", [
        row(ptask("p1", before=900), usage(eta=[NOW - 60, 60.0])),
        row(ptask("c1", "Chive", before=600), usage(eta=[NOW - 30, 120.0]),
            kid),
        row(ptask("g1", "Garlic", before=500), usage(eta=[NOW - 30, 2400.0]),
            {"parentAgentId": "c1", "spawnDepth": 3})])
    return g


def g_counts():
    g = Group("counts")
    g.case("inbox", [row(ptask("a1"), usage(inbox=1)),
                     row(ptask("a2", "Bluebell"), usage(inbox=12))])
    g.case("compactions", [row(ptask("a1"), usage(compactions=2)),
                           row(ptask("a2", "Bluebell"), usage())])
    g.case("shells-and-monitors-running", [
        row(ptask("a1"), usage(background=[["sh1", "bash"], ["sh2", "bash"],
                                           ["mon1", "monitor"]])),
        row(ptask("a2", "Bluebell"), usage())])
    g.case("background-dropped-when-killed", [
        row(ptask("a1", status="killed"), usage(
            background=[["sh1", "bash"], ["mon1", "monitor"]],
            open_at=None)),
        row(ptask("a2", "Bluebell"), usage(background=[["sh2", "bash"]]))])
    g.case("kids", [
        row(ptask("p1", before=900), usage()),
        row(ptask("c1", "Chive", before=600), usage(),
            {"parentAgentId": "p1", "spawnDepth": 2}),
        row(ptask("c2", "Cress", before=500), usage(),
            {"parentAgentId": "p1", "spawnDepth": 2})])
    g.case("all-counts", [
        row(ptask("p1", before=900), usage(
            inbox=3, compactions=1, background=[["sh1", "bash"]] * 10)),
        row(ptask("c1", "Chive", before=600), usage(
            compactions=11, background=[["mon1", "monitor"]]),
            {"parentAgentId": "p1", "spawnDepth": 2}),
        row(ptask("b1", "", type="local_bash", description="make"), BARE)])
    return g


def g_tree():
    g = Group("tree")

    def kid(parent, depth):
        return {"agentType": "Explore", "parentAgentId": parent,
                "spawnDepth": depth}
    chain = [row(ptask("d1", "One", before=900), usage()),
             row(ptask("d2", "Two", before=800), usage(), kid("d1", 2)),
             row(ptask("d3", "Three", before=700), usage(), kid("d2", 3)),
             row(ptask("d4", "Four", before=600), usage(), kid("d3", 4)),
             row(ptask("d5", "Five", before=500), usage(), kid("d4", 5))]
    for n in (2, 3, 4, 5):
        for c in (200, 160, 120):
            g.case("depth-%d@%d" % (n, c), chain[:n], cols=c)
    # Siblings, and a bar carried down a column while a sibling is to come.
    g.case("siblings", [
        row(ptask("p1", "Root", before=900), usage()),
        row(ptask("c1", "Older", before=800), usage(), kid("p1", 2)),
        row(ptask("g1", "Grandkid", before=700), usage(), kid("c1", 3)),
        row(ptask("c2", "Younger", before=600), usage(), kid("p1", 2))],
           cols=200)
    # Ties in startTime go by the payload's order.
    g.case("siblings-tied", [
        row(ptask("p1", "Root", before=900), usage()),
        row(ptask("c2", "Second", before=600), usage(), kid("p1", 2)),
        row(ptask("c1", "First", before=600), usage(), kid("p1", 2))],
           cols=200)
    # A finished ancestor is stepped over: the panel drops it and its child
    # hangs from the next one up.
    g.case("finished-ancestor", [
        row(ptask("p1", "Root", before=900), usage()),
        row(ptask("m1", "Done", status="completed", before=800),
            usage(open_at=None), kid("p1", 2)),
        row(ptask("c1", "Orphan", status="completed", before=700),
            usage(open_at=None), kid("m1", 3))], cols=200)
    # A parent the payload does not list ends the walk: top level.
    g.case("parent-missing", [
        row(ptask("c1", "Stray", before=700), usage(), kid("gone", 3))],
           cols=200)
    # A loop in the sidecars must not hang the walk.
    g.case("parent-loop", [
        row(ptask("l1", "Loop", before=700), usage(), kid("l2", 2)),
        row(ptask("l2", "Pool", before=600), usage(), kid("l1", 2))],
           cols=200)
    # Deeper than CHROME_DEPTH: the row's label pays for its chrome, and
    # its cells hold the columns the shallower rows' do.
    for c in (220, 150, 120, 92):
        g.case("deep-label@%d" % c, chain, cols=c)
    return g


def g_gauges():
    g = Group("gauges")
    for name, model_s, tool_s, before in (
            ("all-model", 700.0, 0.0, 720),
            ("even", 240.0, 240.0, 720),
            ("mostly-wait", 30.0, 30.0, 720),
            ("tiny-tool", 700.0, 8.0, 720),       # 1.1٪: raised to a dot
            ("noise-tool", 710.0, 5.0, 720),      # under 1٪: blank
            ("overrun", 600.0, 300.0, 720),       # past ⌛: 🚦 empty
            ("dim-short", 20.0, 5.0, 40),
            ("hours", 9000.0, 3000.0, 14400)):
        g.case(name, [row(ptask("a1", before=before), usage(
            model_s=model_s, tool_s=tool_s, work=[[NOW - before, NOW]]))])
    g.case("no-split", [row(ptask("a1"), usage(model_s=None))])
    # A resumed agent: startTime 25 minutes back, its first span two hours.
    g.case("resumed", [row(ptask("a1", before=1500), usage(
        work=[[NOW - 7200, NOW - 6000], [NOW - 1500, NOW]],
        model_s=2000.0, tool_s=600.0))])
    # Finished: the clock stops at its last billed stamp, else its last span.
    g.case("finished-at-last-epoch", [row(
        ptask("a1", status="completed", before=3600), usage(
            last_epoch=NOW - 1800, open_at=None, model_s=1000.0,
            tool_s=200.0))])
    g.case("finished-at-last-span", [row(
        ptask("a1", status="completed", before=3600), usage(
            last_epoch=None, work=[[NOW - 3600, NOW - 2400]], open_at=None,
            model_s=1000.0, tool_s=100.0))])
    return g


def g_figures():
    """The right group's figures: magnitudes, the cache and context cells,
    the shares and the limits."""
    g = Group("figures")
    g.case("small", [row(ptask("a1"), usage(
        tok_up=812, tok_down=40, cost=0.0042, ctx_tokens=900, cache_pct=5,
        lines_added=0, lines_removed=0), sh={"sess": 0.01, "week": 0.2})])
    g.case("large", [row(ptask("a1"), usage(
        tok_up=48_000_000, tok_down=1_200_000, cost=123.4567,
        ctx_tokens=950_000, ctx_window=1_000_000, cache_pct=99,
        lines_added=12000, lines_removed=8000),
        sh={"sess": 45.5, "week": 99.6})])
    g.case("cache-100", [row(ptask("a1"), usage(cache_pct=100))])
    g.case("cache-colours", [row(ptask("a%d" % p), usage(cache_pct=p))
                             for p in (0, 30, 60, 80, 95)])
    g.case("ctx-no-window", [row(ptask("a1"), usage(ctx_window=0))])
    g.case("ctx-full", [row(ptask("a1"), usage(ctx_tokens=200000))])
    g.case("shares-unknown", [row(ptask("a1"), usage(),
                                  sh={"sess": None, "week": None})])
    g.case("shares-light", [row(ptask("a1"), usage(),
                                sh={"sess": 0.3, "week": 0.4})])
    g.case("shares-hundred", [row(ptask("a1"), usage(),
                                  sh={"sess": 99.5, "week": 150.0})])
    g.case("no-limits", [row(ptask("a1"), usage())], limits=NO_LIMITS)
    g.case("limits-float", [row(ptask("a1"), usage())],
           limits=dict(LIMITS, session_pct="0.38", weekly_pct="99.6"))
    g.case("unbilled", [row(ptask("a1"), usage(parts=[], cost=0.0))])
    for m, e in (("claude-sonnet-5", "low"), ("claude-haiku-4-5", ""),
                 ("claude-fable-1", "max"), ("claude-opus-4-1", "medium"),
                 ("claude-opus-5[1m]", "xhigh"), ("gpt-5", "null")):
        g.case("model-%s-%s" % (m, e or "none"), [row(
            ptask("a1", model=m, effort=e), usage(model=m, effort=e))])
    g.case("model-from-usage", [row(ptask("a1", model=None, effort=None),
                                    usage(model="claude-sonnet-5",
                                          effort="medium"))])
    g.case("model-from-meta", [row(ptask("a1", model=None, effort=None),
                                   usage(model="", effort=""),
                                   {"model": "haiku"})])
    return g


def g_who():
    """The name, the branch and the activity, and what each gives up."""
    g = Group("who")
    long = "A rather long name for an agent that keeps going and going"
    for c in (220, 160, 140, 120, 100):
        g.case("name-label-branch@%d" % c, [row(
            ptask("a1", name=long, label="Running the whole suite again"),
            usage(branch="feature/a-long-branch-name-here"))], cols=c)
    g.case("label-equals-description", [row(ptask(
        "a1", label="Review the plan"), usage())])
    g.case("description-for-name", [row(ptask(
        "a1", name="", description="Find  the\n flaky   test"), usage())])
    g.case("id-long", [row(ptask("a1234567890abcdef"), usage())])
    return g


def g_hide():
    """--hide: a column hidden on agent rows alone, which the band's rows
    keep, is left blank; one hidden everywhere is removed and the rest close
    up; label parts leave the label."""
    g = Group("hide")
    for name, hide in (
            ("agent-rate", ["agent.state.rate"]),
            ("all-rate", ["*.state.rate"]),
            ("all-work-and-cache", ["*.work", "*.tokens.cache"]),
            ("agent-time", ["agent.time"]),
            ("all-eta", ["*.time.eta"]),
            ("kind", ["agent.name.kind"]),
            ("name-label", ["agent.name.label"]),
            ("doing", ["agent.chat.doing"]),
            ("branch", ["*.workspace.branch"]),
            ("counts", ["agent.state.kids", "agent.state.inbox"]),
            ("agent", ["agent"]),
            ("other-scopes", ["account", "turn", "main", "session"])):
        for c in (None, 160, 92):
            g.case("%s@%s" % (name, "none" if c is None else c), mixed(),
                   cols=c, hide=hide)
    return g


def g_widths():
    """One mixed panel across the widths, where the cells drop."""
    g = Group("widths")
    for c in (None, 0, 400, 260, 220, 200, 180, 160, 140, 120, 100, 92, 80,
              60, 40, 20):
        g.case("mixed@%s" % ("none" if c is None else c), mixed(), cols=c)
    return g


def mixed():
    kid = {"agentType": "Explore", "parentAgentId": "p1", "spawnDepth": 2}
    return [
        row(ptask("p1", "Parsley", status="completed", before=1800),
            usage(open_at=None, compactions=1, eta=[NOW - 300, 900.0],
                  last_seen=NOW - 300), {"agentType": "claude"}),
        row(ptask("c1", "Chive", before=900, label="Reading the tests",
                  tokenSamples=[100, 900, 2000]),
            usage(inbox=2, background=[["sh1", "bash"]],
                  branch="agent-worktree", eta=[NOW - 60, 300.0]), kid),
        row(ptask("c2", "Cress", status="failed", before=700),
            usage(open_at=None, api_error=True), kid),
        row(ptask("q1", "Quince", status="pending", before=10), BARE),
        row(ptask("b1", "", type="local_bash", before=200,
                  description="sleep 300 && make test"), BARE,
            sh={"sess": None, "week": None}),
    ]


def g_missing():
    """What the renderer does with what it is not given: usage None or
    missing fields, meta and shares None, a task with no id or not a dict,
    no startTime, no model, no width and no clock-free rows."""
    g = Group("missing")
    g.case("usage-none", [row(ptask("a1"), None)])
    g.case("usage-empty", [row(ptask("a1"), {})])
    g.case("usage-partial", [row(ptask("a1"), {
        "tok_up": 10, "tok_down": 2, "cache_pct": 50, "ctx_tokens": 20,
        "cost": 0.01, "parts": [[1.0, 0.01]], "model": "opus",
        "effort": "high", "last_epoch": 2.0})])
    g.case("usage-killed-span-only", [row(
        ptask("a1", status="completed", type="local_agent", before=NOW),
        {"work": [[0.0, 5.0]], "last_epoch": None, "model_s": 4.0,
         "tool_s": 0.0})])
    g.case("meta-and-shares-none", [
        {"task": ptask("a1"), "usage": usage(), "meta": None,
         "shares": None}])
    g.case("task-without-id", [
        {"task": {"name": "no id", "status": "running"}, "usage": usage(),
         "meta": {}, "shares": SHARES},
        row(ptask("a1"), usage())])
    g.case("task-not-a-dict", [
        {"task": "not a task", "usage": None, "meta": {}, "shares": SHARES},
        row(ptask("a1"), usage())])
    g.case("no-start-time", [row(ptask("a1", startTime=None), usage(
        work=[], open_at=None))])
    g.case("start-time-string", [row(ptask("a1", startTime="soon"), BARE)])
    g.case("no-model-anywhere", [row(
        ptask("a1", model=None, effort=None), usage(model="", effort=""))])
    g.case("empty-panel", [])
    return g


# The settings groups: one mixed panel and one row of each kind through each
# switch and profile, at the widths where they move something.
def sweep(name, sets):
    g = Group(name, sets)
    for c in (None, 220, 160, 120, 92, 60):
        g.case("mixed@%s" % ("none" if c is None else c), mixed(), cols=c)
    g.case("figures-large", g_figures().cases[1]["input"]["tasks"])
    g.case("shares-float", [row(ptask("a1"), usage(),
                                sh={"sess": 0.38, "week": 9.95})],
           limits=dict(LIMITS, session_pct="0.38", weekly_pct="9.95"))
    g.case("eta-late", [row(ptask("a1"), usage(eta=[NOW - 600, 120.0]))])
    return g


def handmade():
    return [g_states(), g_eta(), g_counts(), g_tree(), g_gauges(),
            g_figures(), g_who(), g_widths(), g_hide(), g_missing(),
            sweep("tight", settings(mark_spacing=False)),
            sweep("subdec", settings(subscript_decimals=True)),
            sweep("tmux", settings(terminal={"TMUX": "/tmp/tmux-501/default,1,0"})),
            sweep("iterm", settings(terminal={"TERM_PROGRAM": "iTerm.app"})),
            sweep("unknown", settings(terminal={}))]


# ════════════════════════════════════════════════════════════════════════════
# The child processes.
# ════════════════════════════════════════════════════════════════════════════

def child_env(terminal):
    env = {k: v for k, v in os.environ.items()
           if k not in ("TMUX", "TERM_PROGRAM", "TERMINAL_EMULATOR")
           and not k.startswith("CODING_AGENT_USAGE_LINE_")}
    env.update(terminal)
    env.update({"TZ": "UTC", "LC_ALL": "en_US.UTF-8"})
    return env


def render_group(group, python=PYTHON):
    """`group` rendered in a process of its own: {"settings", "cases"}."""
    req = {"settings": group.settings, "cases": group.cases}
    got = subprocess.run(
        [python, os.path.abspath(__file__), "--render"],
        input=json.dumps(req).encode("utf-8"), capture_output=True,
        env=child_env(group.settings["terminal"]), cwd=REPO)
    if got.returncode:
        raise RuntimeError(got.stderr.decode("utf-8", "replace"))
    return json.loads(got.stdout.decode("utf-8"))


def _tuples(v):
    if isinstance(v, list):
        return tuple(_tuples(x) for x in v)
    return v


def span_json(sp):
    """A Span as {"text", "colour", "dim", "bold", "bg"}, less the fields at
    their defaults: a colour or bg left out is null, a dim or bold false.
    Every span is kept as the renderer made it, unmerged, blanks included."""
    out = {"text": sp.text}
    for k in ("colour", "dim", "bold", "bg"):
        if getattr(sp, k):
            out[k] = getattr(sp, k)
    return out


def child_render():
    """--render: the rows for each case on stdin, and the spans they were
    joined from, as the CLI would draw them under these settings."""
    req = json.loads(sys.stdin.read())
    sys.path.insert(0, REPO)
    from types import SimpleNamespace
    from coding_agent_usage_line import claude, formatting as fmt
    from coding_agent_usage_line import claude_subagent_render as sr
    from coding_agent_usage_line.claude_records import Limits
    from coding_agent_usage_line.spans import spans
    s = req["settings"]
    # As claude.main does, before anything renders.
    claude.set_mark_spacing(s["mark_spacing"])
    claude.set_subscript_decimals(s["subscript_decimals"])
    # render_task_rows joins each row as it makes it; the spans are caught
    # on their way into the join.
    caught, join = [], sr.join
    def catching(x, *a, **kw):
        caught.append(spans(x))
        return join(x, *a, **kw)
    sr.join = catching
    out = []
    for case in req["cases"]:
        inp = case["input"]
        prepared = []
        for r in inp["tasks"]:
            u = r["usage"]
            if isinstance(u, dict):
                u = SimpleNamespace(**{k: _tuples(v) for k, v in u.items()})
            prepared.append((r["task"], u, r["meta"], r["shares"]))
        del caught[:]
        rows = sr.render_task_rows(tuple(prepared), Limits(**inp["limits"]),
                                   inp["cols"], inp["now"],
                                   inp.get("hide", []))
        assert len(rows) == len(caught)
        out.append(dict(case, rows=[
            {"id": tid, "row": text, "spans": [span_json(sp) for sp in sp_]}
            for (tid, text), sp_ in zip(rows, caught)]))
    sys.stdout.write(json.dumps({
        "settings": dict(s, profile=fmt.PROFILE), "cases": enc(out)}))


def child_capture():
    """--capture ARGV...: run the program on stdin as the CLI does, and print
    what it printed and the inputs render_task_rows was handed."""
    argv = sys.argv[2:]
    raw = sys.stdin.read()
    sys.path.insert(0, REPO)
    from coding_agent_usage_line import cli
    from coding_agent_usage_line import claude_subagent_render as sr
    caught, render = [], sr.render_task_rows
    def catching(prepared, limits, cols=None, now=None, hide=()):
        inp = {"tasks": [
            {"task": t, "usage": u, "meta": m, "shares": sh}
            for t, u, m, sh in prepared],
            "limits": limits, "cols": cols, "now": now}
        if hide:
            inp["hide"] = list(hide)
        caught.append(inp)
        return render(prepared, limits, cols, now, hide)
    sr.render_task_rows = catching
    real = sys.stdout
    sys.stdin, sys.stdout = io.StringIO(raw), io.StringIO()
    try:
        cli.main(argv)
        printed = sys.stdout.getvalue()
    finally:
        sys.stdout = real
    real.write(json.dumps({"stdout": printed, "inputs": enc(caught)}))


# ════════════════════════════════════════════════════════════════════════════
# The corpus: the end-to-end cases' own inputs.
# ════════════════════════════════════════════════════════════════════════════

def run_cases_module():
    spec = importlib.util.spec_from_file_location(
        "run_cases", os.path.join(TESTS, "run-cases.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def corpus(python=PYTHON):
    """Each subagent case run as run-cases.py runs it, and what reached the
    renderer captured: one group per environment's terminal and flags."""
    import shutil
    import tempfile
    rc = run_cases_module()
    with open(os.path.join(FIXTURES, "cases.json"), encoding="utf-8") as fh:
        cases = [c for c in json.load(fh)["cases"] if c["suite"] == "subagent"]
    groups = {}
    scratch = tempfile.mkdtemp(prefix="panel-corpus.")
    try:
        suite = rc.Suite(scratch)
        for case in cases:
            env, cwd = suite.environ(case["env"])
            with open(os.path.join(FIXTURES, case["input"]),
                      encoding="utf-8") as fh:
                stdin = rc.fill(fh.read(), scratch)
            argv = ["--agent", "claude", "--mode", "subagent",
                    "--cols", str(case["cols"])] + case["flags"]
            got = subprocess.run(
                [python, os.path.abspath(__file__), "--capture"] + argv,
                input=stdin.encode("utf-8"), cwd=cwd, env=env,
                capture_output=True)
            if got.returncode:
                raise RuntimeError(got.stderr.decode("utf-8", "replace"))
            res = json.loads(rc.unfill(got.stdout.decode("utf-8"), scratch))
            terminal = {k: env[k] for k in ("TMUX", "TERM_PROGRAM",
                                            "TERMINAL_EMULATOR") if k in env}
            sets = settings(
                terminal=terminal,
                mark_spacing="--no-mark-spacing" not in case["flags"],
                subscript_decimals="--subscript-decimals" in case["flags"])
            key = json.dumps(sets, sort_keys=True)
            if key not in groups:
                suffix = "-".join(
                    ([case["env"]] if case["env"] != "app-41-63" else [])
                    + [f.lstrip("-") for f in case["flags"]])
                groups[key] = Group("corpus" + ("-" + suffix if suffix
                                                else ""), sets)
            g = groups[key]
            # Nothing reaches the renderer for an empty or unread payload.
            for inp in res["inputs"]:
                g.cases.append({"id": case["id"], "input": inp,
                                "stdout": res["stdout"]})
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return list(groups.values())


def rendered(groups, python=PYTHON):
    """{file name: its content} for every group."""
    from concurrent.futures import ThreadPoolExecutor
    # Each group is a process of its own, so they render side by side.
    with ThreadPoolExecutor(os.cpu_count() or 4) as pool:
        gots = list(pool.map(lambda g: render_group(g, python), groups))
    files = {}
    for g, got in zip(groups, gots):
        for case in got["cases"]:
            # A corpus case's rows are its golden's: the capture and the
            # render must agree before either is written.
            stdout = case.pop("stdout", None)
            if stdout is not None:
                lines = "".join(json.dumps({"id": r["id"], "content": r["row"]},
                                           ensure_ascii=False) + "\n"
                                for r in case["rows"])
                if lines != stdout:
                    raise RuntimeError("%s/%s: the rows drawn from the "
                                       "captured inputs are not the run's"
                                       % (g.name, case["id"]))
        files[g.name + ".json"] = dump(got)
    return files


def all_groups(python=PYTHON):
    return handmade() + corpus(python)


def check(python=PYTHON):
    """The fixtures written again in memory and compared with the committed
    ones: (passed, [failure lines])."""
    files = rendered(all_groups(python), python)
    fails, n = [], 0
    have = sorted(f for f in os.listdir(OUT) if f.endswith(".json"))
    for name in sorted(set(have) | set(files)):
        path = os.path.join(OUT, name)
        kept = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                kept = fh.read()
        want = files.get(name)
        if kept is None or want is None:
            fails.append("%s: %s" % (name, "not committed" if kept is None
                                     else "no longer generated"))
            continue
        a, b = json.loads(want)["cases"], json.loads(kept)["cases"]
        n += len(a)
        if kept != want:
            ids = [x["id"] for x, y in zip(a, b) if x != y]
            fails.append("%s: %s" % (name, ", ".join(ids[:8]) or
                                     "cases added or removed"))
    return n, fails


def main(root=FIXTURES, python=PYTHON):
    """The end-to-end inputs, under ROOT; then, once cases.json lists them,
    the render cases under panel/."""
    write_e2e(root)


def main_panel(python=PYTHON):
    import shutil
    files = rendered(all_groups(python), python)
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    total = 0
    for name, text in sorted(files.items()):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
            fh.write(text)
        n = len(json.loads(text)["cases"])
        total += n
        print("panel/%-24s %4d cases" % (name, n))
    print("panel/%-24s %4d cases" % ("total", total))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--render"]:
        child_render()
    elif sys.argv[1:2] == ["--capture"]:
        child_capture()
    elif sys.argv[1:2] == ["--check"]:
        n, fails = check()
        for f in fails:
            print("  FAIL  " + f)
        print("panel: %d cases, %d files differ" % (n, len(fails)))
        sys.exit(1 if fails else 0)
    else:
        main()
        main_panel()
