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


SECTIONS = (section_basics,)


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(INPUTS)
    total = 0
    try:
        for make in SECTIONS:
            s = make()
            n = s.write()
            total += n
            print("%-12s %5d cases" % (s.name, n))
    finally:
        shutil.rmtree(STATE, ignore_errors=True)
    print("%-12s %5d cases" % ("total", total))


if __name__ == "__main__":
    main()
