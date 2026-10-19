#!/usr/bin/env python3
"""Write the differential cases that pin mod/src/claude_records.ts to
claude_records.py.

    python3 tests/fixtures/gen/records.py

Each call below runs one of claude_records.py's functions and writes its
arguments and its result to tests/fixtures/records/<section>.json, as
{"fn": name, "args": [...], "out": result}.  mod/test/claude_records.test.ts
runs every case through the TypeScript and compares.  Only this side writes
them: a change to the Python shows up as a diff here, and then as a failing
TypeScript case until the port follows it.

The inputs are the committed transcripts under transcripts/status/ and
transcripts/cost/, which the golden cases read, and small hand-made ones for
what that corpus never says: ETA reports, background tasks, inbox sends,
agents finishing, late agent turns.  The hand-made files are written under
records/inputs/ first, by this file, so the TypeScript reads the same bytes.
Paths are relative to the repository root, which both sides run from.

FLOATS.  Python writes a float with repr and JavaScript reads it back with
JSON.parse; both find the shortest digits that round-trip, and both parse
correctly rounded, so the double that arrives is the double that left even
where the two would spell it differently (1e-05 against 0.00001).  What
JSON cannot carry — an infinity, a NaN and the sign of a zero — is written
as {"$float": "inf" | "-inf" | "nan" | "-0"}, and the test reads it back.
A tuple is a list, a NamedTuple is a dict of its fields under their Python
names, and a set is a sorted list.

THE INPUTS ARE ONES THE PYTHON SURVIVES.  Where a malformed field makes the
Python raise — a record that is not an object, a count that is null — the
TypeScript carries on with the field missing, and there is nothing to
compare; see the head of claude_records.ts.
"""
import json
import math
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(FIXTURES))
OUT = os.path.join(FIXTURES, "records")
INPUTS = os.path.join(OUT, "inputs")
sys.path.insert(0, REPO)
os.chdir(REPO)

# A private state directory, so agent_records' cache and the offsets file
# are this run's own and never the user's.
STATE = tempfile.mkdtemp(prefix="records-gen-")
os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = STATE

from coding_agent_usage_line import claude_records as cr  # noqa: E402


def rel(path):
    """A path as the cases spell it: relative to the repository root."""
    return os.path.relpath(path, REPO)


def enc(v):
    """A result as JSON both languages read the same; see FLOATS above."""
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
    if isinstance(v, (set, frozenset)):
        return [enc(x) for x in sorted(v)]
    if isinstance(v, dict):
        return {str(k): enc(x) for k, x in v.items()}
    raise TypeError("cannot write %r" % (v,))


class Section:
    """One fixture file's cases, gathered then written."""

    def __init__(self, name):
        self.name = name
        self.cases = []

    def case(self, fn, *args, **kw):
        """Run `fn` on `args` and record it; `out` overrides the result,
        for a call whose effect is on an argument rather than returned."""
        out = kw.pop("out", None)
        got = getattr(cr, fn)(*args, **kw)
        self.cases.append({"fn": fn, "args": enc(list(args)),
                           "kw": enc(kw), "out": enc(got if out is None
                                                     else out(got))})
        return got

    def raw(self, fn, args, out):
        """Record a case worked out here rather than by one call."""
        self.cases.append({"fn": fn, "args": enc(args), "kw": {},
                           "out": enc(out)})

    def write(self):
        with open(os.path.join(OUT, self.name + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"cases": self.cases}, fh, indent=1, sort_keys=True,
                      ensure_ascii=False, allow_nan=False)
            fh.write("\n")
        return len(self.cases)


# ════════════════════════════════════════════════════════════════════════════
# The inputs.
# ════════════════════════════════════════════════════════════════════════════

def corpus():
    """Every committed transcript the golden cases read, main and agent."""
    out = []
    for suite in ("status", "cost"):
        d = os.path.join(FIXTURES, "transcripts", suite)
        for root, _, files in os.walk(d):
            out += [os.path.join(root, f) for f in files
                    if f.endswith(".jsonl")]
    return sorted(rel(p) for p in out)


def write_bytes(name, data):
    path = os.path.join(INPUTS, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return rel(path)


# Byte-level oddities the reader has to take the Python's way: universal
# newlines, a BOM, a line that is not UTF-8, a partial last write, and a
# line that is JSON but not an object.
BYTES = {
    "crlf.jsonl": b'{"a": 1}\r\n{"b": 2}\r{"c": 3}\n',
    "bom.jsonl": b'\xef\xbb\xbf{"a": 1}\n{"b": 2}\n',
    "badutf8.jsonl": b'{"a": "x\xff\xfey"}\n{"b": 2}\n',
    "partial.jsonl": b'{"a": 1}\n{"b": 2}\n{"c": ',
    "blank.jsonl": b'\n\n   \n{"a": 1}\n',
    "notdict.jsonl": b'{"a": 1}\n5\n[1, 2]\n"s"\n{"b": 2}\n',
}


# ════════════════════════════════════════════════════════════════════════════
# Section 1: the payload, parsing, stamps, squash and prices.
# ════════════════════════════════════════════════════════════════════════════

def section_basics():
    s = Section("basics")
    for v in (0, 1, -7, 1.0, -0.0, 1.5, 0.1, 1e-05, 0.0001, 1e16, 1.5e16,
              123456789.25, 2.5e-7, 1e300, True, False, None, "x",
              [1, "a", None], {"a": [True, 1.5]}, "it's", 'say "hi"'):
        s.case("_num", v)
    d = {"a": {"b": 0, "c": None, "d": False, "e": "s", "f": 2.0,
               "g": {"h": [1]}}, "z": "last"}
    for paths in (("a.b",), ("a.c", "z"), ("a.d", "z"), ("a.e",), ("a.f",),
                  ("a.g",), ("a.g.h",), ("x.y", "a.x"), ("a.b.c", "z")):
        s.case("_first", d, *paths)
        s.case("_first", d, *paths, default="0")
    pdir = os.path.join(FIXTURES, "payloads", "status")
    for name in sorted(os.listdir(pdir)):
        with open(os.path.join(pdir, name), encoding="utf-8") as fh:
            s.case("read_payload", fh.read())
    for raw in ("", "not json", "[1, 2]", "5", "null",
                '{"model": {"display_name": 5}, "cost": '
                '{"total_cost_usd": 0.1234, "total_lines_added": 0}}',
                '{"cwd": "/c", "workspace": {"current_dir": null}, '
                '"github": {"pr": {"number": 12.0}}}',
                '{"pr": {"number": false}, "pull_request": {"number": 7}}',
                '{"effort": {"level": ["a"]}, "session_id": true}'):
        s.case("read_payload", raw)

    for name, data in sorted(BYTES.items()):
        p = write_bytes(name, data)
        # Only the objects: the Python yields any JSON value, and its
        # readers raise on the first that is not an object.
        s.raw("_records", [p], [r for r in cr._records(p)
                                if isinstance(r, dict)])
    for p in corpus():
        recs = list(cr._records(p))
        kept = {id(r) for r in cr._dedupe_usage(recs)}
        s.raw("_dedupe_usage", [p], [i for i, r in enumerate(recs)
                                     if id(r) in kept])
    s.raw("_dedupe_usage", [write_bytes("dedupe.jsonl", jsonl([
        {"message": {"usage": {}}, "requestId": "a"},
        {"message": {"usage": {"x": 1}}, "requestId": ""},
        {"message": {"usage": {"x": 1}, "id": "m"}},
        {"message": {"usage": {"x": 2}, "id": "m"}, "requestId": 0},
        {"message": {"usage": {"x": 1}}},
        {"message": {"usage": {"x": 1}}},
        {"message": {"usage": {"x": 1}}, "requestId": 7},
        {"message": {"usage": {"x": 1}}, "requestId": "7"},
    ]))], None)
    recs = list(cr._records(s.cases[-1]["args"][0]))
    kept = {id(r) for r in cr._dedupe_usage(recs)}
    s.cases[-1]["out"] = [i for i, r in enumerate(recs) if id(r) in kept]

    for ts in ("", "2026-08-16T01:12:00Z", "2026-08-16T01:12:00.123Z",
               "2026-08-16T01:12:00", "2026-08-16T01:12:00ZZ",
               "2026-1-5t1:2:3", "2026-01- 1T00:00:00", "2026-01-01T00:00:60",
               "2026-02-29T00:00:00", "2024-02-29T23:59:59",
               "0001-01-01T00:00:00", "0000-01-01T00:00:00",
               "9999-12-31T23:59:59", "2026-08-16T01:12:00+00:00",
               "2026-08-16 01:12:00", "2026-08-16T1:12:00 ",
               "２０２６-01-01T00:00:00",
               "2026-13-01T00:00:00", "2026-08-16T24:00:00", "garbage",
               "1970-01-01T00:00:00Z", "1969-12-31T23:59:59.999Z"):
        s.case("ts_epoch", ts)
    for e in (None, 0.0, 1787000000.0, 1787000000.4, 1787000000.9999996,
              -1.0, 86399.0):
        s.case("_stamp_utc", e)

    for text in ("", "plain", "two\nlines\tand  spaces   here",
                 "arrows ← ⟳ ⯿ Ⰰ", "vs16 ❤️",
                 "oil \U0001F6E2 clock \U0001F570 ok \U0001F600",
                 "flag \U0001F1EC\U0001F1E7", "¶ already",
                 "edge \U0001FBFF \U0001F2FF \U0001F300", "  lead\n\ntrail  "):
        s.case("squash", text)
        s.case("squash", text, "|")
    for m in (None, "", "claude-opus-5", "claude-fable-5-1", "Fable-5",
              "claude-sonnet-5-20260101", "claude-sonnet-4-6",
              "claude-haiku-4-5", "<synthetic>", "OPUS"):
        s.case("_price", m)
        s.case("_usd", m, 1234, 56789, 1234567, 8901)
    s.case("_usd", "claude-opus-5", 0, 0, 0, 0)
    s.case("_usd", "claude-sonnet-5", 3, 7, 11, 13)
    return s


def jsonl(records):
    """Records as JSONL bytes, spaced as Claude Code spaces them."""
    return "".join(json.dumps(r) + "\n" for r in records).encode("utf-8")


# ════════════════════════════════════════════════════════════════════════════
# Hand-made transcripts, for what the corpus never says.
# ════════════════════════════════════════════════════════════════════════════

BASE = 1787000000           # 2026-08-17T...Z; every stamp is an offset from it


def stamp(sec):
    """A transcript stamp `sec` seconds after BASE, with milliseconds."""
    whole = int(sec)
    return "%s.%03dZ" % (time.strftime("%Y-%m-%dT%H:%M:%S",
                                       time.gmtime(BASE + whole)),
                         int(round((sec - whole) * 1000)))


def prompt(sec, text, **kw):
    """A typed prompt, the record opens_turn() takes."""
    return dict({"type": "user", "userType": "external",
                 "promptSource": "typed", "timestamp": stamp(sec),
                 "message": {"content": text}}, **kw)


def asst(sec, mid, text=None, tools=(), usage=None, stop=None,
         model="claude-opus-5", rid=None, **kw):
    """An assistant record: a text block, tool calls as (id, name), and
    usage when it bills."""
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    content += [{"type": "tool_use", "id": i, "name": n} for i, n in tools]
    m = {"id": mid, "model": model, "content": content}
    if usage is not None:
        m["usage"] = dict(zip(("input_tokens", "cache_creation_input_tokens",
                               "cache_read_input_tokens", "output_tokens"),
                              usage))
    if stop is not None:
        m["stop_reason"] = stop
    r = {"type": "assistant", "timestamp": stamp(sec), "message": m}
    if usage is not None:
        r["requestId"] = rid or ("req-" + str(mid))
    return dict(r, **kw)


def result(sec, *ids, **kw):
    """A tool result answering the calls `ids`."""
    return dict({"type": "user", "timestamp": stamp(sec),
                 "message": {"content": [{"type": "tool_result",
                                          "tool_use_id": i} for i in ids]}},
                **kw)


def note(sec, body, attach=False, **kw):
    """A <task-notification>, as an agent's attachment or a woken thread's
    user record."""
    if attach:
        return dict({"type": "attachment", "timestamp": stamp(sec),
                     "attachment": {"type": "queued_command",
                                    "prompt": body}}, **kw)
    return dict({"type": "user", "timestamp": stamp(sec),
                 "message": {"content": [{"type": "text", "text": body}]}},
                **kw)


def queue(sec, op, content=None):
    r = {"type": "queue-operation", "operation": op, "timestamp": stamp(sec)}
    if content is not None:
        r["content"] = content
    return r


ETA = "skills/coding-agent-usage-line-report-eta: ETA "
FLAG = "⛳ "


def handmade():
    """Write the hand-made transcripts; their paths, by name."""
    files = {}

    def put(name, records):
        files[name] = write_bytes(name, jsonl(records))

    put("eta.jsonl", [
        prompt(0, "go"),
        asst(10, "m1", "Plan.\n" + FLAG + ETA + "4m"),
        asst(20, "m2", "`\U0001F3C1 " + ETA + "6h30m`"),
        asst(30, "m3", "**" + ETA + "1.5 h — 3 lanes left**"),
        asst(40, "m4", ETA + "<number><s|m|h>"),
        asst(50, "m5", "one\r\n" + FLAG + ETA + "5m\r\nmore"),
        asst(60, "m6", FLAG + ETA + "٤m"),
        asst(70, "m7", FLAG + ETA + "1m\n" + FLAG + ETA + "2m\n"),
        result(75, "x", message={"content": [
            {"type": "tool_result", "tool_use_id": "x",
             "content": FLAG + ETA + "9m"}]}),
        asst(76, "m7b", "⛳" + ETA + "10 s and more"),
        asst(77, "m7c", ETA + "2h 15m"),
        asst(78, "m7d", ETA + "5m - x\n" + ETA + "6m —x"),
        asst(80, "m8", "done " + FLAG + ETA + "0s", stop="end_turn"),
        asst(81, "m8b", FLAG + ETA + "0s", stop="end_turn"),
        prompt(100, "again"),
        asst(110, "m9", FLAG + ETA + "3m", tools=[("t1", "Bash")]),
        asst(111, "m9", None, stop="end_turn"),
        prompt(200, "third"),
        asst(210, "m10", FLAG + ETA + "2m"),
        asst(220, "m11", "bye", stop="end_turn"),
        prompt(300, "fourth"),
        asst(310, "m12", FLAG + ETA + "0s"),
        asst(320, "m13", "more work"),
        {"type": "assistant", "message": {"id": "m14", "content": [
            {"type": "text", "text": FLAG + ETA + "7m"}]}},
        asst(330, "m15", 5),
        {"type": "system", "subtype": "turn_duration",
         "timestamp": stamp(340)},
        queue(350, "remove", "queued prompt"),
        asst(360, "m16", FLAG + ETA + "1m", stop="end_turn"),
    ])
    put("tools.jsonl", [
        prompt(0, "tools"),
        asst(10, "a", None, tools=[("a1", "Bash"), ("a2", "Read"),
                                   ("a3", "AskUserQuestion"),
                                   ("a4", "Agent"), ("", "Bash"),
                                   (7, "Task")]),
        {"type": "assistant", "timestamp": stamp(11), "message": {
            "content": [{"type": "tool_use", "id": "a5"}, "junk", 3]}},
        result(15, "a2"),
        result(12, "a1"),
        result(40, "a3"),
        result(100, "a4"),
        result(10, 7),
        result(20, "zz"),
        result(30, "a5"),
        asst(120, "b", None, tools=[("b1", "Bash"), ("b2", "Task"),
                                    ("b3", "ExitPlanMode")]),
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "c1", "name": "Bash"}]}},
        result(130, "b3"),
        {"type": "user", "timestamp": "bad", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "b1"}]}},
        prompt(200, "next"),
        asst(205, "d", None, tools=[("d1", "Bash"), ("d2", "AskUserQuestion")]),
        result(215, "d1"),
    ])
    put("background.jsonl", [
        prompt(0, "bg"),
        result(1, "x", toolUseResult={"backgroundTaskId": "b1"}),
        result(2, "x", toolUseResult={"backgroundTaskId": 5}),
        result(3, "x", toolUseResult={"taskId": "m1", "timeoutMs": 1000}),
        result(4, "x", toolUseResult={"taskId": "m2"}),
        result(5, "x", toolUseResult={"task_id": "b1", "message": "ok"}),
        result(6, "x", toolUseResult={"task": {"task_id": "m1",
                                               "status": "completed"}}),
        result(7, "x", toolUseResult={"backgroundTaskId": "b2"}),
        result(8, "x", toolUseResult={"backgroundTaskId": "b3"}),
        result(9, "x", toolUseResult={"taskId": "m3", "timeoutMs": None}),
        note(10, "<task-notification><task-id> b2 </task-id>"
                 "<status>completed</status></task-notification>",
             attach=True),
        {"type": "user", "timestamp": stamp(11), "message": {"content": [
            {"type": "text", "text": "<task-notification><task-id>b3"},
            {"type": "text", "text": "</task-id><status>killed</status>"
                                     "</task-notification>"}]}},
        note(12, "<task-notification><task-id>m3</task-id>event"
                 "</task-notification>"),
        result(13, "x", toolUseResult={"agentId": "ag1",
                                       "status": "completed"}),
        result(14, "x", toolUseResult={"agentId": "ag2",
                                       "status": "running"}),
        note(15, "<task-notification><task-id>ag3</task-id>"
                 "<status>failed</status></task-notification>"),
        result(9, "x", toolUseResult={"agentId": "ag1", "status": "killed"}),
        result(20, "x", toolUseResult={"agentId": "ag1",
                                       "status": "stopped"}),
        {"type": "user", "message": {"content":
                                     "<task-notification><task-id>ag4"
                                     "</task-id><status>x</status>"}},
        prompt(30, "<task-notification><task-id>ag5</task-id><status>"
                   "completed</status></task-notification>",
               promptSource="system"),
        result(31, "x", toolUseResult={"task": {"task_id": "m3",
                                                "status": "running"}}),
        result(32, "x", toolUseResult={"backgroundTaskId": ""}),
    ])
    put("queue.jsonl", [
        queue(0, "enqueue", "typed while busy"),
        queue(1, "remove", "typed while busy"),
        queue(2, "enqueue", "<task-notification>x</task-notification>"),
        queue(3, "dequeue", "<task-notification>x</task-notification>"),
        queue(4, "enqueue"),
        queue(5, "popAll", ""),
        queue(6, "clear", "x"),
        queue(7, "remove"),
        queue(8, "popAll", "two\nlines"),
        {"type": "user", "userType": "external", "timestamp": stamp(9),
         "message": {"content": "no source"}},
        prompt(10, "<task-notification>wake</task-notification>",
               promptSource="system", isMeta=True),
        prompt(11, "meta", isMeta=True),
        prompt(12, "queued", promptSource="queued"),
        prompt(13, "summary", isCompactSummary=True),
        prompt(14, ""),
        prompt(15, "internal", userType="internal"),
        prompt(16, "<command-name>/x</command-name>"),
        {"type": "user", "userType": "external", "timestamp": stamp(17),
         "promptSource": None, "message": {"content": "null source"}},
        {"type": "system", "subtype": "compact_boundary",
         "timestamp": stamp(18), "compactMetadata": {"preTokens": 1000}},
        {"type": "system", "subtype": "stop_hook_summary",
         "timestamp": stamp(19)},
        {"type": "progress", "timestamp": stamp(20)},
        asst(21, "q1", "x", stop="end_turn"),
    ])
    return files


def section_threads(files):
    s = Section("threads")
    paths = corpus() + sorted(files.values())

    for p in paths:
        recs = list(cr._records(p))
        s.raw("classify", [p], [[
            cr.opens_turn(r), cr.queued_text(r), cr.queue_step(r),
            cr.is_compaction(r), cr.turn_start_text(r), cr.is_work(r),
            cr.ends_turn(r), cr.notification_text(r)] for r in recs])

        for now in (None, BASE + 1000.0):
            pending, tools, blocked = {}, [], []
            for r in recs:
                cr.scan_tool_spans(r, pending, tools, blocked)
            if now is not None:
                cr.open_tool_spans(pending, now, tools, blocked)
            s.raw("scan_tool_spans", [p, now], {
                "pending": [[k, t, n] for k, (t, n) in pending.items()],
                "tools": tools, "blocked": blocked})
        blocked = []
        s.raw("tool_spans", [p], [cr.tool_spans(recs, blocked), blocked])

        open_ = {}
        ends = {}
        for r in recs:
            cr.scan_background(r, open_)
            cr.scan_agent_end(r, ends)
        s.raw("scan_background", [p], list(open_.items()))
        s.raw("scan_agent_end", [p], list(ends.items()))

        state = cr.new_eta_state()
        trace = []
        for r in recs:
            cr.live_eta(r, state)
            trace.append(list(state))
        s.raw("live_eta", [p], trace)
        s.raw("eta_report", [p], cr.eta_report(recs))

        state, spans, trace = [None, None], [], []
        for r in recs:
            cr.agent_span(r, state, spans)
            trace.append([list(state), list(spans)])
        cr.close_agent_span(state, spans)
        trace.append([list(state), list(spans)])
        s.raw("agent_span", [p], trace)

        # The clocks over this file's own spans, cut at every billed stamp.
        work = [w for w in trace[-1][1]]
        tools, waiting = cr.tool_spans(recs), []
        cr.tool_spans(recs, waiting)
        s.case("thread_clock", work, tools, waiting)
        cuts = sorted(t for t in (cr.ts_epoch(r.get("timestamp") or "")
                                  for r in cr._dedupe_usage(recs))
                      if t is not None)
        s.case("split_clock", work, tools, waiting, cuts)
        s.case("turn_clock", tools, waiting, BASE + 5.0, BASE + 120.0)

    for e in ((), (BASE + 0.0, 0.0), (BASE + 10.0, 240.0), (1.5, 2.25)):
        s.case("eta_finish", e)
    texts = ["x\n" + FLAG + ETA + "3m", FLAG + ETA + "3m\n\n",
             "  " + ETA + "45s  ", "\t*`" + FLAG + ETA + "2.5m`*",
             ETA + "1h–2 left", ETA + "1h – 2 left",
             ETA + "1h ", "pre " + ETA + "1m", ETA + "1m\r",
             ETA + "1m1s1h", ETA + "3x", ETA + "３m", ETA + "1.m",
             FLAG + FLAG + ETA + "1m", ETA + "1 m"]
    for t in texts:
        s.case("eta_report", [{"type": "assistant", "timestamp": stamp(1),
                               "message": {"content": [{"type": "text",
                                                        "text": t}]}}])
    s.case("eta_report", [5, {"type": "user"}, {"type": "assistant",
                                                "message": {"content": "s"}}])

    spans = [[], [(0, 10)], [(5, 5), (3, 1)], [(0, 10), (5, 20), (30, 40)],
             [(30, 40), (0, 10), (10, 15), (14, 16)],
             [(0.1, 0.3), (0.2, 0.7), (1e9 + 0.1, 1e9 + 0.35)]]
    for sp in spans:
        s.case("union_seconds", sp)
        s.case("net_tool_seconds", sp, sp[:1])
    work = [(0, 100), (150, 200)]
    tools = [(10, 30), (20, 50), (160, 170)]
    waiting = [(40, 60), (165, 168)]
    s.case("thread_clock", work, tools, waiting)
    for cuts in ([], [0], [25, 45, 200], [float("-inf"), 30],
                 [30, 30, 60], [500], [-5, 1000], [float("-inf")]):
        s.case("split_clock", work, tools, waiting, cuts)
    for t0, t1 in ((None, 10), (10, None), (50, 50), (60, 40), (0, 100),
                   (25, 165), (-10, 1000)):
        s.case("turn_clock", tools, waiting, t0, t1)
    return s


SECTIONS = (section_basics, section_threads)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(INPUTS)
    total = 0
    files = handmade()
    try:
        for make in SECTIONS:
            s = make() if make is section_basics else make(files)
            n = s.write()
            total += n
            print("%-12s %5d cases" % (s.name, n))
    finally:
        shutil.rmtree(STATE, ignore_errors=True)
    print("%-12s %5d cases" % ("total", total))


if __name__ == "__main__":
    main()
