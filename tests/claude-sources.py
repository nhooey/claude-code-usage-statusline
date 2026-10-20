#!/usr/bin/env python3
"""Claude bridge keeps scoped sources canonical and avoids quota misassignment."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line import claude_sources, sources

seen=[]; old=sources.collect
def fake(agent, spec, account, period, context, now=None):
    seen.append((agent, spec, account, period, context))
    return {"schema_version":1, "source":"cmd", "as_of":1,
            "buckets":[{"id":"default","label":"default","windows":[
                {"id":"five","duration_seconds":18000,"used_percent":12,"resets_at":200},
                {"id":"week","duration_seconds":604800,"used_percent":34,"resets_at":300}]}],
            "account":{"scope":"organization","cost_usd":2}}
sources.collect=fake
try:
    p=claude_sources.prepare_claude_reading("cmd:/fixture", "team", "day",
        {"session":"s", "model":"Claude", "rate_limits":{"secret":"no"}}, now=10)
finally: sources.collect=old
assert seen[0][:4] == ("claude", "cmd:/fixture", "team", "day")
assert p.limits.session_pct == "12" and p.limits.weekly_pct == "34"
old_tz=os.environ.get("TZ")
os.environ["TZ"]="Etc/GMT-7"; time.tzset()
try:
    assert claude_sources.legacy_limits(p.reading).session_reset == "1970-01-01 07:03"
finally:
    if old_tz is None: os.environ.pop("TZ", None)
    else: os.environ["TZ"]=old_tz
    time.tzset()
assert "organization" in p.account_text and "team day" in p.account_text
# Named/associated buckets are kept solely in the generic account row.
assert claude_sources.legacy_limits({"buckets":[{"id":"spark","label":"Spark","model":"Spark","windows":[{"id":"five","duration_seconds":18000,"used_percent":99}]}]}) == claude_sources.NO_LIMITS
# A stale reading is still the reading: age is reported, never enforced.
assert claude_sources.legacy_limits(dict(p.reading, stale=True)) == p.limits

# The seeded snapshot carries NUMBERS, the form calibration compares against
# CALIB_MIN_PCT.  Seeding the renderer's strings raised a TypeError that
# _with_shares swallowed, and every share cell drew "?" on the live readout.
import json, tempfile
from coding_agent_usage_line import claude
snap = claude.seed_limits_snapshot(p.limits, p.reading)
assert snap["session_pct"] == 12.0 and snap["weekly_pct"] == 34.0, snap
# ... and a calibration entry written by the string-carrying version still
# divides, rather than poisoning every render until CALIB_TTL lets it go.
with tempfile.TemporaryDirectory() as tmp:
    cache = os.path.join(tmp, "calib.json")
    ss, ws = claude._window_starts()
    with open(cache, "w") as fh:
        json.dump({"windows": "%s|%s" % (ss, ws), "sess_cost": 6.0, "week_cost": 17.0,
                   "sess_pct": "12", "week_pct": "34"}, fh)
    saved = claude.CALIB_CACHE_OVERRIDE
    claude.CALIB_CACHE_OVERRIDE = cache
    try:
        assert claude.calibration() == {"sess": 0.5, "week": 0.5}, claude.calibration()
    finally:
        claude.CALIB_CACHE_OVERRIDE = saved

# The calibration cache both ports share: its name and its text as the
# shared cases pin them, which mod/test/claude_calib.test.ts checks the
# TypeScript against.
from coding_agent_usage_line import state
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "fixtures", "calib", "values.json")) as fh:
    shared = [c for c in json.load(fh)["cases"]
              if c["fn"] in ("state_name", "calib_cache_text")]
FLOATS = {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf"),
          "-0": -0.0}
def revive(v):
    return FLOATS[v["$float"]] if isinstance(v, dict) and "$float" in v else v
for c in shared:
    args = [revive(a) for a in c["args"]]
    try:
        got = (state.state_name(*args) if c["fn"] == "state_name"
               else claude.calib_cache_text(*args))
    except TypeError:
        got = {"raises": True}
    assert got == c["out"], (c, got)
assert len(shared) == 13, len(shared)

# ... and each port reads the other's: the text the mod writes, under the
# name it gives, read by the panel's scan=False at any age.
with tempfile.TemporaryDirectory() as tmp:
    saved = (os.environ.get("CODING_AGENT_USAGE_LINE_STATE_DIR"),
             claude.CALIB_CACHE_OVERRIDE, claude._SNAPSHOT)
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = tmp
    claude.CALIB_CACHE_OVERRIDE = ""
    try:
        claude._SNAPSHOT = dict(snap, _scope="cmd\0me\0" + "1786800000")
        ss, ws = claude._window_starts()
        windows = "%s|%s" % (ss, ws)
        name = state.state_name("calibration", "cmd\0me\0" + "1786800000")
        assert name == [c["out"] for c in shared
                        if c["args"] == ["calibration",
                                         "cmd\0me\x001786800000"]][0]
        path = os.path.join(tmp, name)
        assert claude.calibration_cache_path() == path
        with open(path, "w") as fh:
            fh.write(claude.calib_cache_text(windows, 6.0, 17.0, 12.0, 34.0))
        os.utime(path, (1, 1))
        assert claude.calibration(scan=False) == {"sess": 0.5, "week": 0.5}
        # The Python writes the same bytes the mod's pyJsonDumps does.
        claude._write_calib_cache(windows, 6, 17.0, 12.0, 34)
        with open(path) as fh:
            assert fh.read() == ('{"windows":"%s","sess_cost":6.0,'
                                 '"week_cost":17.0,"sess_pct":12.0,'
                                 '"week_pct":34.0}' % windows)
    finally:
        if saved[0] is None:
            os.environ.pop("CODING_AGENT_USAGE_LINE_STATE_DIR", None)
        else:
            os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = saved[0]
        claude.CALIB_CACHE_OVERRIDE, claude._SNAPSHOT = saved[1:]

# The old calibration caches go once, by name alone, and nothing else does;
# find_compatible opens only a usage cache's name.
with tempfile.TemporaryDirectory() as tmp:
    saved = os.environ.get("CODING_AGENT_USAGE_LINE_STATE_DIR")
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = tmp
    h = "0123456789abcdef" * 4
    usage = {"agent": "claude", "account_name": "a", "period_start": "0",
             "as_of": 5, "source": "cmd"}
    c = "claude-calibration-"
    old = [c + h + ".json", c + "ts-" + h + ".cache",
           c + h.replace("0", "f") + ".json"]
    kept = [c + h + ".json.123", c + h + ".cache", c + h[:-1] + ".json",
            c + "ts-x.cache", "claude-agent-offsets-%s.json" % h, h + ".json"]
    try:
        for n in old + kept:
            with open(os.path.join(tmp, n), "w") as fh:
                json.dump(usage if n == h + ".json" else dict(usage, as_of=9),
                          fh)
        assert state.find_compatible("claude", "a", "0")["as_of"] == 5
        claude._old_calib_checked = False
        assert claude._remove_old_calibrations() == 3
        assert (sorted(os.listdir(tmp))
                == sorted(kept + [claude.OLD_CALIB_DONE]))
        # Once: the marker stops the listing, in this process and the next.
        with open(os.path.join(tmp, old[0]), "w"):
            pass
        assert claude._remove_old_calibrations() == 0
        claude._old_calib_checked = False
        assert claude._remove_old_calibrations() == 0
        assert os.path.exists(os.path.join(tmp, old[0]))
        # A run out of time leaves the rest, and no marker, for the next.
        os.remove(os.path.join(tmp, claude.OLD_CALIB_DONE))
        budget, claude.OLD_CALIB_BUDGET_S = claude.OLD_CALIB_BUDGET_S, -1
        claude._old_calib_checked = False
        try:
            assert claude._remove_old_calibrations() == 0
        finally:
            claude.OLD_CALIB_BUDGET_S = budget
        assert not os.path.exists(os.path.join(tmp, claude.OLD_CALIB_DONE))
        claude._old_calib_checked = False
        assert claude._remove_old_calibrations() == 1
    finally:
        if saved is None:
            os.environ.pop("CODING_AGENT_USAGE_LINE_STATE_DIR", None)
        else:
            os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = saved

# One account and window name one calibration cache, whether the render
# fetched the reading or took the cache an earlier render left: the shared
# scenario mod/test/sources.test.ts replays too.  A cached reading lost its
# account and window, so the panel and the mod wrote and read two files.
with open(os.path.join(HERE, "fixtures", "sources", "collect.json")) as fh:
    scenario = [c for c in json.load(fh)
                if c["name"] == "tracker: fresh, then cached, one scope"][0]
SCOPE = "claude-usage-tracker\0session:s1\0" "1786838400"
with tempfile.TemporaryDirectory() as tmp:
    saved = {k: os.environ.get(k) for k in (
        "CODING_AGENT_USAGE_LINE_STATE_DIR",
        "CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST")}
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = os.path.join(tmp, "s")
    tracker = os.path.join(tmp, "tracker.plist")
    os.environ["CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST"] = tracker
    try:
        for s in scenario["steps"]:
            with open(tracker, "w") as fh:
                fh.write(s["tracker"])
            p = claude_sources.prepare_claude_reading(
                s["spec"], s["account"], s["period"], s["built_context"],
                s["now"])
            got = claude.seed_limits_snapshot(p.limits, p.reading)["_scope"]
            assert got == s["scope"] == SCOPE, (s["now"], got)
        assert len(scenario["steps"]) == 3
    finally:
        for k, v in saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
print("ok Claude source bridge")
