#!/usr/bin/env python3
"""Write the differential cases that pin mod/src/claude_calib.ts to the
calibration in claude.py.

    /usr/bin/python3 tests/fixtures/gen/calib.py

Run it under /usr/bin/python3, as gen/all.py does: 3.9's sum() adds floats
left to right, as the port does, where 3.12's compensates.

What the files under tests/fixtures/calib/ hold:

  values.json  the pure parts over awkward inputs, each case one call:
               _local_naive and _window_starts across time zones (DST gaps
               and folds included), _pct_num, seed_limits_snapshot,
               plan_totals and _priced_record.
  shares.json  the committed transcripts' turns, and hand-made ones, with
               turn_cost, turn_shares and session_cache_shares, then each
               turn's turn_cost_since and window_shares and the session's
               session_shares against plan snapshots, units and zones.
  scan.json    scenarios: a projects directory built from the committed
               corpus and hand-made files, with mtimes, then steps sharing
               one state directory — calibration, _window_costs, appends,
               rewrites, planted caches — each with its result and the
               caches it left.

A naive datetime is written as str() writes it, "2026-08-16 01:31:00".
FLOATS as gen/records.py writes them: repr, and {"$float": ...} for what
JSON cannot carry.  A call that raises is {"raises": true}; the port throws
where the Python raises, so those are pinned too.  Paths under a scenario's
scratch directory are written as ${DIR}, and a step whose scan cache is
as the step before it left it says "same".

A scenario's steps carry the order glob.glob listed its files in, which is
the filesystem's: a request id in two files is billed at the first, so the
test hands the TypeScript that order rather than its own listing's, and
checks the two list the same files.
"""
import base64
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
OUT = os.path.join(FIXTURES, "calib")
CORPUS = os.path.join(FIXTURES, "transcripts")
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from cases import CALIB_UNITS, ENVS, PIN_NOW  # noqa: E402
from coding_agent_usage_line import (  # noqa: E402
    claude, claude_records as cr, claude_sources, sources)

ZONES = ("UTC", "America/New_York", "Europe/London", "Australia/Lord_Howe",
         "Asia/Kolkata", "America/St_Johns")


class Clock:
    """claude.py's `time`, with time() pinned to `now`."""

    def __init__(self):
        self.now = float(PIN_NOW)

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


CLOCK = Clock()


def set_tz(name):
    os.environ["TZ"] = name
    time.tzset()


def enc(v):
    """A value as JSON both languages read the same; see the docstring."""
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
    if hasattr(v, "isoformat"):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    if isinstance(v, dict):
        return {str(k): enc(x) for k, x in v.items()}
    raise TypeError("cannot write %r" % (v,))


def run(fn, *args):
    """fn(*args), or the mark of a call that raised."""
    try:
        return fn(*args)
    except Exception:
        return RAISES


RAISES = object()


def out(v):
    return {"raises": True} if v is RAISES else enc(v)


def write(name, cases):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name + ".json"), "w",
              encoding="utf-8") as fh:
        json.dump({"cases": cases}, fh, indent=1, sort_keys=True,
                  ensure_ascii=False, allow_nan=False)
        fh.write("\n")
    return len(cases)


def bytes_arg(data):
    """Bytes as a case spells them: text when they are UTF-8, else hex."""
    try:
        return {"text": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"hex": data.hex()}


def snapshot(env_name, tz):
    """The snapshot a render in `tz` seeds from one of cases.py's readings."""
    set_tz(tz)
    reading = sources.normalise(ENVS[env_name]["source"], "cmd")
    lim = claude_sources.legacy_limits(reading)
    return claude.seed_limits_snapshot(lim, reading)


# ════════════════════════════════════════════════════════════════════════════
# values.json
# ════════════════════════════════════════════════════════════════════════════

STAMPS = (
    "2026-08-16T01:10:00Z", "2026-08-16T01:10:00.123Z",
    "2026-08-16T01:10:00ZZ", "2026-8-6T1:2:3Z", "2026-08-16t01:10:00Z",
    "٢٠٢٦-08-16T01:10:00Z",
    "2026-03-08T07:30:00Z", "2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z",
    "2026-03-29T01:30:00Z", "2026-10-25T00:30:00Z", "2026-04-04T14:45:00Z",
    "2026-02-30T00:00:00Z", "2026-08-16T24:00:00Z", "2026-08-16 01:10:00Z",
    "bogus", "", "2026-08-16T01:10:00+00:00",
    "9999-12-31T23:59:59Z", "0001-01-01T00:00:00Z",
)

RESETS = (
    "2026-08-16 07:18", "2026-08-16 06:31", "2026-03-08 07:30",
    "2026-11-01 06:30", "2026-03-29 06:30", "2026-10-25 06:30",
    "2026-04-05 07:00", "2026-1-5 3:4", "2026-01-05  03:04",
    "2026-01-05\t03:04", "2026-01-05　 03:04", "2026-01-05 03:04 ",
    "2026-01-05 03:04:00", "2026-01-05", "2026-02-29 00:00",
    "2024-02-29 00:00", "2026-08-16 24:00", "2026-08-16 23:60",
    "2026-08- 6 07:18",
    "٢٠٢٦-٠٨-١٦ 07:18",
    "", None, 12345, ["2026-08-16 07:18"],
)


def values():
    cases = []
    for tz in ZONES:
        set_tz(tz)
        for ts in STAMPS:
            if ts.startswith("0001") and tz != "UTC":
                continue  # localtime's zone before 1900 is the platform's
            cases.append({"fn": "_local_naive", "tz": tz, "args": [ts],
                          "out": out(run(claude._local_naive, ts))})
        for r in RESETS:
            for key in ("session_resets_at", "weekly_resets_at"):
                snap = {key: r}
                claude._SNAPSHOT = snap
                got = run(claude._window_starts)
                stamps = None if got is RAISES else [
                    None if s is None else out(run(s.timestamp)) for s in got]
                cases.append({"fn": "_window_starts", "tz": tz,
                              "args": [snap],
                              "out": out(got if got is RAISES else
                                         [got[0], got[1], stamps,
                                          "%s|%s" % got])})
    # The first week of year 1 is where a boundary falls off the calendar.
    set_tz("UTC")
    for r in ("0001-01-01 03:00", "0001-01-01 06:00", "0001-01-08 00:00",
              "0001-01-07 23:59"):
        snap = {"session_resets_at": r, "weekly_resets_at": r}
        claude._SNAPSHOT = snap
        got = claude._window_starts()
        cases.append({"fn": "_window_starts", "tz": "UTC", "args": [snap],
                      "out": enc([got[0], got[1],
                                  [None if s is None
                                   else out(run(s.timestamp))
                                   for s in got], "%s|%s" % got])})

    for v in (15, 15.5, -0.0, "15", " 15 ", "1_5", "15.", ".5", "1e2", "inf",
              "-Infinity", "nan", "abc", "", None, True, False, [], {},
              "٣", "٣.٥", " 5 ", float("inf")):
        cases.append({"fn": "_pct_num", "args": [enc(v)],
                      "out": out(run(claude._pct_num, v))})

    lims = [cr.NO_LIMITS,
            cr.NO_LIMITS._replace(session_pct="41",
                                  session_reset="2026-08-16 04:00",
                                  weekly_pct="63",
                                  weekly_reset="2026-08-18 01:00"),
            cr.NO_LIMITS._replace(session_pct="0.38", weekly_pct=""),
            cr.NO_LIMITS._replace(weekly_pct="abc",
                                  weekly_reset="2026-08-18 01:00"),
            cr.NO_LIMITS._replace(session_share="5")]
    readings = [None, "text", {},
                {"source": "cmd", "account_name": "me",
                 "period_start": 1786800000},
                {"source": None, "account_name": 0, "period_start": 1.5},
                {"source": ["a"], "account_name": {"x": 1}}]
    for lim in lims:
        for reading in readings:
            snap = claude.seed_limits_snapshot(lim, reading)
            cases.append({"fn": "seed_limits_snapshot",
                          "args": [enc(lim), enc(reading)],
                          "out": enc(snap)})
            cases.append({"fn": "plan_totals", "args": [enc(snap)],
                          "out": enc(claude.plan_totals())})
    for snap in ({"session_pct": "7", "weekly_pct": True},
                 {"session_pct": float("nan"), "weekly_pct": 0},
                 {"session_pct": 5}, {}):
        claude._SNAPSHOT = snap
        cases.append({"fn": "plan_totals", "args": [enc(snap)],
                      "out": enc(claude.plan_totals())})

    for line in priced_lines():
        cases.append({"fn": "_priced_record", "args": [bytes_arg(line)],
                      "out": out(run(claude._priced_record, line))})
    return write("values", cases)


def priced_lines():
    """Every line of two corpus files, then the records it never holds."""
    lines = []
    for name in ("cost/01-plain.jsonl",
                 "cost/09-agents/subagents/agent-fork1.jsonl"):
        with open(os.path.join(CORPUS, name), "rb") as fh:
            lines += list(fh)

    def rec(**kw):
        r = {"type": "assistant", "timestamp": "2026-08-16T01:11:00Z",
             "requestId": "req-x",
             "message": {"id": "msg-x", "model": "claude-opus-5",
                         "usage": {"input_tokens": 10, "output_tokens": 20,
                                   "cache_read_input_tokens": 30,
                                   "cache_creation_input_tokens": 40}}}
        for k, v in kw.items():
            if k.startswith("m_"):
                r["message"][k[2:]] = v
            elif k.startswith("u_"):
                r["message"]["usage"][k[2:]] = v
            else:
                r[k] = v
        return json.dumps(r).encode() + b"\n"

    lines += [
        rec(), rec(type="user"), rec(type=None), rec(m_usage={}),
        rec(m_usage=None), rec(timestamp=""), rec(timestamp=None),
        rec(timestamp="bogus"), rec(timestamp="2026-08-16T01:11:00.5Z"),
        rec(requestId=None), rec(requestId="", m_id=None), rec(requestId=0),
        rec(requestId=0, m_id=7), rec(requestId=1.0), rec(requestId=True),
        rec(requestId=False, m_id=False), rec(requestId=[1]),
        rec(m_model="claude-sonnet-5"), rec(m_model="Claude-HAIKU-4"),
        rec(m_model="fable-5-1"), rec(m_model=None), rec(m_model=""),
        rec(m_model="unknown-model"),
        rec(u_input_tokens=True), rec(u_output_tokens=1.5),
        rec(u_cache_read_input_tokens=-5), rec(u_input_tokens=1e300),
        rec(u_output_tokens=2 ** 60),
        rec(m_usage={"output_tokens": 7}), rec(m_usage={"other": 1}),
        rec(m_usage=[1]), rec(m_usage="yes"), rec(u_input_tokens="10"),
        rec(u_input_tokens=None), rec(u_input_tokens=[1]),
        rec(m_model=5), rec(m_model=["opus"]), rec(timestamp=5),
        rec(timestamp=True), rec(timestamp=["x"]), rec(message=[1]),
        rec(message="text"), rec(message=""), rec(message=None),
        rec(message=0),
        b'{"type": "assistant", "timestamp": "2026-08-16T01:11:00Z", '
        b'"requestId": NaN, "message": {"usage": {"input_tokens": NaN}}}\n',
        b'{"type": "assistant", "timestamp": "2026-08-16T01:11:00Z", '
        b'"requestId": "r", "message": {"usage": {"input_tokens": '
        b'Infinity, "output_tokens": -Infinity}}}\n',
        b'{"type": "assistant", "timestamp": "2026-08-16T01:11:00Z", '
        b'"requestId": "r\xff\xfe", "message": {"usage": {"input_tokens": '
        b'1}}}\n',
        b'\xef\xbb\xbf' + rec(),
        rec().rstrip(b"\n") + b"\r\n", rec().rstrip(b"\n"),
        b"  " + rec(), b"", b"\n", b"not json\n", b"[1, 2]\n", b"null\n",
        rec()[:40], rec().rstrip(b"\n") + b" x\n",
        b'{"type": "assistant", "type": "user", "timestamp": "2026", '
        b'"message": {"usage": {"a": 1}}}\n',
    ]
    return lines


# ════════════════════════════════════════════════════════════════════════════
# shares.json
# ════════════════════════════════════════════════════════════════════════════

def corpus_turns():
    out = {}
    for suite in ("status", "cost"):
        for name in sorted(os.listdir(os.path.join(CORPUS, suite))):
            if name.endswith(".jsonl"):
                out["%s/%s" % (suite, name)] = cr.read_turns(
                    os.path.join(CORPUS, suite, name))
    return out


def made_turns():
    """What the corpus never holds: compactions either side of a boundary,
    unstamped parts, a turn with no cost and one whose cost is no number."""
    def t(ts, usd=(1.0, 2.0, 0.5, 0.25), **kw):
        return cr.Turn(ts=ts, text="", fresh=0, cache_write=0, cache_read=0,
                       out=0, ctx=0, calls=1, dur_s=0.0, dctx=None,
                       usd_in=usd[0], usd_out=usd[1], usd_cr=usd[2],
                       usd_cw=usd[3], **kw)
    edge = 1786842000.0  # 2026-08-16T02:20:00Z
    return {
        "made/compactions": [
            t("2026-08-16T00:30:00Z", compact=True),
            t("2026-08-16T02:30:00Z", compact=True),
            t("2026-08-16T02:30:00Z", compact=True,
              parts=((edge, 1.0), (edge + 60, 2.0))),
            t("bogus", compact=True),
            t("2026-08-16T02:30:00Z"),
            t("2026-08-16T00:30:00Z")],
        "made/parts": [
            t("2026-08-16T00:30:00Z",
              parts=((edge - 7200, 0.75), (None, 0.5), (edge + 7200, 2.5))),
            t("2026-08-16T00:30:00Z", parts=((None, 3.0),)),
            t("2026-08-16T00:30:00Z", parts=((edge - 9e5, 1.0),)),
            t("2026-08-16T00:30:00Z", parts=((edge + 9e5, -0.0),))],
        "made/costs": [
            t("2026-08-16T01:00:00Z", usd=(0.0, 0.0, 0.0, 0.0)),
            t("2026-08-16T01:00:00Z", usd=(0.0, 0.0, 0.125, 0.375)),
            t("2026-08-16T01:00:00Z", usd=(0.5, 0.5, 0.5, 0.5)),
            t("2026-08-16T01:00:00Z", usd=(1.0, -3.0, 0.5, 0.5)),
            t("2026-08-16T01:00:00Z", usd=(0.0, 0.0, 0.025, 0.0))],
        "made/nan": [
            t("2026-08-16T01:00:00Z", usd=(float("nan"), 0.0, 1.0, 1.0))],
        "made/inf": [
            t("2026-08-16T01:00:00Z", usd=(float("inf"), 0.0, 1.0, 1.0))],
        "made/empty": [],
    }


UNITS = (CALIB_UNITS, {"sess": None, "week": 4.1}, {"sess": 0.5},
         {}, {"sess": True, "week": 0}, {"sess": "5", "week": 4.1},
         {"sess": float("nan"), "week": float("inf")},
         {"sess": 2, "week": [1]})


def snapshots(tz):
    out = [snapshot(name, tz) for name in
           ("app-41-63", "straddle", "straddle-cost", "plan-cache")]
    out += [{"session_resets_at": "2026-08-16 06:20"},
            {"weekly_resets_at": "2026-08-22 21:20"},
            {"session_resets_at": "bogus", "weekly_resets_at": ""}, {}]
    return out


def shares():
    cases = []
    turns = dict(corpus_turns(), **made_turns())
    for name, ts in sorted(turns.items()):
        cases.append({"fn": "turn_costs", "turns": enc(ts),
                      "args": [name],
                      "out": {"turn_cost": [enc(claude.turn_cost(t))
                                            for t in ts],
                              "turn_shares": [out(run(claude.turn_shares, t))
                                              for t in ts],
                              "session_cache_shares": out(run(
                                  claude.session_cache_shares, ts))}})
    for tz in ("UTC", "America/New_York", "Australia/Lord_Howe"):
        for snap in snapshots(tz):
            set_tz(tz)
            claude._SNAPSHOT = snap
            starts = claude._window_starts()
            for name, ts in sorted(turns.items()):
                since = [[out(run(claude.turn_cost_since, t, s))
                          for s in starts] for t in ts]
                cases.append({
                    "fn": "shares", "tz": tz, "args": [name],
                    "snap": enc(snap), "calibs": enc(UNITS),
                    "out": {
                        "turn_cost_since": since,
                        "by_calib": [{
                            "window_shares": [
                                out(run(claude.window_shares, t, units))
                                for t in ts],
                            "session_shares": out(run(
                                claude.session_shares, ts, units))}
                            for units in UNITS]}})
    # The turns go in once each, not once per case.
    by_name = {}
    for c in cases:
        if "turns" in c:
            by_name[c["args"][0]] = c.pop("turns")
    cases.insert(0, {"fn": "turns", "args": [], "out": by_name})
    return write("shares", cases)


# ════════════════════════════════════════════════════════════════════════════
# scan.json
# ════════════════════════════════════════════════════════════════════════════

RECENT = PIN_NOW              # every corpus stamp is inside the windows
OLD = PIN_NOW - 30 * 86400    # a month before: past every scan's cutoff
LATER = 1798761600            # 2027-01-01, after every window of the year


def corpus_files(*suites):
    out = []
    for suite in suites:
        root = os.path.join(CORPUS, suite)
        for dirpath, _, names in os.walk(root):
            for n in names:
                if n.endswith(".jsonl"):
                    p = os.path.join(dirpath, n)
                    out.append({"path": os.path.relpath(p, CORPUS),
                                "from": os.path.relpath(p, REPO),
                                "mtime": RECENT})
    return sorted(out, key=lambda f: f["path"])


def line(rid, ts="2026-08-16T01:11:00Z", tokens=1000, **kw):
    r = {"type": "assistant", "timestamp": ts, "requestId": rid,
         "message": {"model": "claude-opus-5",
                     "usage": {"input_tokens": tokens, "output_tokens": 0}}}
    r.update(kw)
    return json.dumps(r) + "\n"


class Scenario:
    """One scratch directory and the steps run in it."""

    def __init__(self, name, tz, files):
        self.case = {"name": name, "tz": tz, "files": files, "steps": []}
        self.dir = tempfile.mkdtemp(prefix="calib-gen-")
        self.projects = os.path.join(self.dir, "projects")
        self.state = os.path.join(self.dir, "state")
        os.makedirs(self.projects)
        set_tz(tz)
        os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = self.state
        claude.PROJECTS_DIR = self.projects
        claude.CALIB_CACHE_OVERRIDE = ""
        claude._SNAPSHOT = {}
        # Every file gets a stamped mtime: left to the clock, the scan's
        # cutoff would keep or drop it by the day the generator ran.
        for f in files:
            f.setdefault("mtime", RECENT)
            self.put(f)

    def put(self, f, mode="wb"):
        p = os.path.join(self.projects, f["path"])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if "from" in f:
            with open(os.path.join(REPO, f["from"]), "rb") as fh:
                data = fh.read()
        elif "hex" in f:
            data = bytes.fromhex(f["hex"])
        elif "text" in f:
            data = f["text"].encode("utf-8")
        else:
            data = None
        if data is not None:
            with open(p, mode) as fh:
                fh.write(data)
        if "mtime" in f:
            os.utime(p, (f["mtime"], f["mtime"]))

    def scrub(self, v):
        if isinstance(v, str):
            return v.replace(self.dir, "${DIR}")
        if isinstance(v, list):
            return [self.scrub(x) for x in v]
        if isinstance(v, dict):
            return {self.scrub(k): self.scrub(x) for k, x in v.items()}
        return v

    def glob(self):
        return [os.path.relpath(p, self.projects) for p in
                claude.glob.glob(os.path.join(claude.PROJECTS_DIR, "*",
                                              "*.jsonl"))
                + claude.glob.glob(os.path.join(claude.PROJECTS_DIR, "*",
                                                "*", "subagents", "**",
                                                "agent-*.jsonl"),
                                   recursive=True)]

    def costs_cache(self):
        """The scan cache's files, or "same" when no different from the
        last step that wrote them out, which keeps the corpus's small."""
        try:
            with open(os.path.join(self.state,
                                   "claude-window-costs.cache")) as fh:
                got = self.scrub(enc(json.load(fh)["files"]))
        except OSError:
            got = None
        if got == getattr(self, "last", None):
            return "same"
        self.last = got
        return got

    def calib_cache(self, windows):
        try:
            with open(claude.calibration_cache_path(windows)) as fh:
                return enc(json.load(fh))
        except (OSError, ValueError):
            return None

    def step(self, op, **kw):
        s = dict(kw, op=op)
        snap = kw.get("snap", {})
        claude._SNAPSHOT = snap
        CLOCK.now = kw.get("now", float(PIN_NOW))
        if op in ("append", "replace"):
            self.put(kw, "ab" if op == "append" else "wb")
        elif op == "override":
            claude.CALIB_CACHE_OVERRIDE = (
                os.path.join(self.dir, kw["path"]) if kw["path"] else "")
        elif op == "plant":
            path = claude.calibration_cache_path(kw["windows"])
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(kw["content"])
            if kw.get("age") is not None:
                at = CLOCK.now - kw["age"]
                os.utime(path, (at, at))
        elif op == "age":
            path = claude.calibration_cache_path(kw["windows"])
            at = CLOCK.now - kw["age"]
            os.utime(path, (at, at))
        elif op == "calibration":
            s["glob"] = self.glob()
            got = run(claude.calibration, kw.get("scan", True))
            s["out"] = out(got)
            starts = claude._window_starts()
            s["calib_cache"] = self.calib_cache("%s|%s" % starts)
            s["costs_cache"] = self.costs_cache()
        elif op == "window_costs":
            s["glob"] = self.glob()
            ss, ws = (None if v is None else
                      claude.datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
                      for v in (kw["ss"], kw["ws"]))
            s["out"] = out(run(claude._window_costs, ss, ws))
            s["costs_cache"] = self.costs_cache()
        else:
            raise ValueError(op)
        self.case["steps"].append(s)
        return s

    def done(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        return self.case


def scan():
    cases = []

    # The whole corpus as two projects, in two zones: a scan, the same
    # windows again off the cache, and the scan bounded every other way.
    for tz in ("UTC", "America/New_York"):
        sc = Scenario("corpus-" + tz, tz, corpus_files("status", "cost"))
        for env in ("app-41-63", "straddle", "straddle-cost", "coarse"):
            snap = snapshot(env, tz)
            sc.step("calibration", snap=snap)
            sc.step("calibration", snap=snap, scan=False)
        for ss, ws in (("2026-08-16 01:31:00", "2026-08-11 01:00:00"),
                       ("2026-08-16 01:31:00", None),
                       (None, "2026-08-16 01:20:00"), (None, None),
                       ("2026-08-15 21:20:00", "2026-08-15 21:31:00"),
                       ("2026-08-16 01:33:20", "2026-08-16 01:33:20")):
            sc.step("window_costs", ss=ss, ws=ws)
        cases.append(sc.done())

    # One project's files, read again only past where the last scan
    # stopped: appends, a half-written last line, a rewrite that shrinks
    # the file, one that keeps its length, and a file aging out.
    base = "".join(line("a%d" % i, "2026-08-16T01:%02d:00Z" % i)
                   for i in range(5))
    sc = Scenario("incremental", "UTC", [
        {"path": "p/s1.jsonl", "text": base, "mtime": RECENT},
        {"path": "p/s2.jsonl", "text": line("b1"), "mtime": RECENT}])
    snap = snapshot("app-41-63", "UTC")
    w = ("2026-08-15 23:00:00", "2026-08-11 01:00:00")
    sc.step("window_costs", ss=w[0], ws=w[1])
    sc.step("window_costs", ss=w[0], ws=w[1])
    sc.step("append", path="p/s1.jsonl",
            text=line("a5", "2026-08-16T01:30:00Z") + line("a1")
            + line("a6", tokens=7)[:-1])
    sc.step("window_costs", ss=w[0], ws=w[1])
    sc.step("append", path="p/s1.jsonl", text="\n" + line("a6", tokens=9))
    sc.step("window_costs", ss=w[0], ws=w[1])
    sc.step("replace", path="p/s1.jsonl", text=line("c1"))
    sc.step("window_costs", ss=w[0], ws=w[1])
    sc.step("replace", path="p/s1.jsonl",
            text=line("c2").replace("c2", "c3"))
    sc.step("window_costs", ss=w[0], ws=w[1])
    sc.step("replace", path="p/s2.jsonl", mtime=OLD)
    sc.step("window_costs", ss=w[0], ws=w[1])
    sc.step("window_costs", ss=None, ws=None)
    sc.step("calibration", snap=snap)
    cases.append(sc.done())

    # Request ids as a Python set keys them, across one file and two.
    keys = [line(1), line(1.0, tokens=2), line(True, tokens=3),
            line("1", tokens=4), line(None, tokens=5), line(None, tokens=6),
            line(0, tokens=7, message={"id": "m0", "usage":
                                       {"input_tokens": 8}}),
            line("m0", tokens=9), line(-0.0, tokens=10),
            line(False, tokens=11), line("late", "bogus", 12),
            line("late", tokens=13), line(1e300, tokens=14),
            line(float("inf"), tokens=15)]
    nan = ('{"type": "assistant", "timestamp": "2026-08-16T01:11:00Z", '
           '"requestId": NaN, "message": {"usage": {"input_tokens": %d}}}\n')
    sc = Scenario("keys", "UTC", [
        {"path": "p/a.jsonl", "text": "".join(keys) + nan % 16 + nan % 17,
         "mtime": RECENT},
        {"path": "p/b.jsonl", "text": line(2, tokens=18) + nan % 19
         + line("late", tokens=20), "mtime": RECENT}])
    sc.step("window_costs", ss="2026-08-16 00:00:00",
            ws="2026-08-11 01:00:00")
    sc.step("window_costs", ss="2026-08-16 00:00:00",
            ws="2026-08-11 01:00:00")
    cases.append(sc.done())

    # Where glob looks and where it does not.
    agent = line("ag", tokens=50)
    sc = Scenario("layout", "UTC", [
        {"path": "p/s.jsonl", "text": line("s")},
        {"path": "p/s/subagents/agent-1.jsonl", "text": agent},
        {"path": "p/s/subagents/wf/deep/agent-2.jsonl",
         "text": line("d", tokens=60)},
        {"path": "p/s/subagents/.hidden/agent-3.jsonl",
         "text": line("h", tokens=70)},
        {"path": "p/s/subagents/agent-4.json", "text": line("j")},
        {"path": "p/s/subagents/.agent-5.jsonl", "text": line("k")},
        {"path": "p/s/agent-6.jsonl", "text": line("l")},
        {"path": "p/x.jsonl/inner.jsonl", "text": line("x")},
        {"path": "p/.dot.jsonl", "text": line("dot")},
        {"path": ".hidden/s.jsonl", "text": line("hp")},
        {"path": "top.jsonl", "text": line("top")},
        {"path": "q/deep/s.jsonl", "text": line("qd")},
        {"path": "q/s/subagents", "text": line("file")}])
    sc.step("window_costs", ss=None, ws="2026-08-11 01:00:00")
    sc.step("window_costs", ss=None, ws=None)
    cases.append(sc.done())

    # A record the scan cannot price raises, and takes the calibration
    # with it; nothing is cached.
    sc = Scenario("raises", "UTC", [
        {"path": "p/a.jsonl", "text": line("ok"), "mtime": RECENT},
        {"path": "p/b.jsonl", "text": line("bad", message=[1]),
         "mtime": RECENT}])
    snap = snapshot("app-41-63", "UTC")
    sc.step("calibration", snap=snap)
    sc.step("window_costs", ss=None, ws=None)
    sc.step("replace", path="p/b.jsonl", text=line([1]))
    sc.step("window_costs", ss=None, ws=None)
    sc.step("replace", path="p/b.jsonl", text=line([1])[:-1])
    sc.step("window_costs", ss=None, ws=None)
    sc.step("replace", path="p/b.jsonl", text=line("ok2"))
    sc.step("calibration", snap=snap)
    cases.append(sc.done())

    # The calibration cache: planted, live, stale, foreign, and none.
    sc = Scenario("cache", "UTC", corpus_files("cost"))
    app = snapshot("app-41-63", "UTC")
    coarse = snapshot("coarse", "UTC")
    key = "%s|%s" % windows_of(app)
    sc.step("calibration", snap={})
    sc.step("calibration", snap={}, scan=False)
    sc.step("calibration", snap=app, scan=False)
    sc.step("plant", snap=app, windows=key, content=json.dumps(
        {"windows": key, "sess_cost": 8.0, "week_cost": 60.0,
         "sess_pct": 4.0, "week_pct": 30.0}))
    sc.step("calibration", snap=app)
    sc.step("age", snap=app, windows=key, age=400)
    sc.step("calibration", snap=app, scan=False)
    sc.step("calibration", snap=app)
    sc.step("plant", snap=app, windows=key, content=json.dumps(
        {"windows": key, "sess_cost": 8.0, "week_cost": 60.0}))
    sc.step("calibration", snap=app)
    sc.step("plant", snap=app, windows=key, content=json.dumps(
        {"windows": key, "sess_cost": 8.0, "week_cost": None,
         "sess_pct": "1.5", "week_pct": "30"}))
    sc.step("calibration", snap=app)
    sc.step("plant", snap=app, windows=key, content=json.dumps(
        {"windows": key, "sess_cost": True, "week_cost": "60",
         "sess_pct": 2, "week_pct": 30}))
    sc.step("calibration", snap=app)
    sc.step("plant", snap=app, windows=key, content=json.dumps(
        {"windows": key, "sess_cost": float("nan"), "week_cost": 1e308,
         "sess_pct": float("nan"), "week_pct": 1e-300}))
    sc.step("calibration", snap=app)
    for bad in ("[1, 2]", "not json", '"text"', "﻿{}",
                json.dumps({"windows": "other", "sess_pct": 1})):
        sc.step("plant", snap=app, windows=key, content=bad)
        sc.step("calibration", snap=app, scan=False)
    sc.step("override", path="planted.json")
    sc.step("plant", snap=app, windows=key,
            content=json.dumps(CALIB_UNITS))
    sc.step("calibration", snap=app)
    sc.step("calibration", snap={})
    sc.step("plant", snap=app, windows=key,
            content=json.dumps({"sess": "x", "other": 1}))
    sc.step("calibration", snap=app)
    sc.step("plant", snap=app, windows=key,
            content=json.dumps(ENVS["coarse"]["calib"]))
    sc.step("calibration", snap=coarse)
    sc.step("calibration", snap=app)
    sc.step("calibration", snap=app, scan=False)
    sc.step("override", path="")
    sc.step("calibration", snap=coarse)
    cases.append(sc.done())

    # The weekly reset falls inside the 5-hour window, which bounds each
    # by its own start; and a boundary in a DST gap and in a fold.
    for tz, sess, week in (
            ("UTC", "2026-08-16 05:20", "2026-08-23 01:20"),
            ("America/New_York", "2026-03-08 07:30", "2026-03-14 02:30"),
            ("America/New_York", "2026-11-01 06:30", "2026-11-07 01:30"),
            ("Australia/Lord_Howe", "2026-04-05 06:45", "2026-04-11 01:45")):
        stamps = ["2026-03-08T06:59:00Z", "2026-03-08T07:00:00Z",
                  "2026-03-08T07:31:00Z", "2026-11-01T05:29:00Z",
                  "2026-11-01T05:31:00Z", "2026-11-01T06:31:00Z",
                  "2026-04-04T14:44:00Z", "2026-04-04T15:16:00Z",
                  "2026-08-16T00:19:00Z", "2026-08-16T00:21:00Z",
                  "2026-08-16T01:19:00Z", "2026-08-16T01:21:00Z"]
        text = "".join(line("r%d" % i, ts, tokens=1000 + i)
                       for i, ts in enumerate(stamps))
        sc = Scenario("bounds-%s-%s" % (tz, sess[:10]), tz,
                      [{"path": "p/s.jsonl", "text": text,
                        "mtime": LATER}])
        snap = {"session_pct": 20.0, "session_resets_at": sess,
                "weekly_pct": 10.0, "weekly_resets_at": week,
                "_scope": "x"}
        sc.step("calibration", snap=snap)
        cases.append(sc.done())
    return write("scan", cases)


def windows_of(snap):
    claude._SNAPSHOT = snap
    return claude._window_starts()


def main():
    # gen/all.py runs the other generators in this process after this one,
    # so the zone, the state directory and claude.py's globals go back as
    # they were found.
    saved = {k: os.environ.get(k) for k in
             ("TZ", "CODING_AGENT_USAGE_LINE_STATE_DIR")}
    globs = {k: getattr(claude, k) for k in
             ("time", "PROJECTS_DIR", "CALIB_CACHE_OVERRIDE", "_SNAPSHOT")}
    claude.time = CLOCK
    try:
        n = values() + shares() + scan()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        time.tzset()
        for k, v in globs.items():
            setattr(claude, k, v)
    print("calib: %d cases" % n)


if __name__ == "__main__":
    main()
