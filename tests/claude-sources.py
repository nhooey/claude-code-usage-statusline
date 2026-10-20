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
import hashlib, json, tempfile
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
        claude._calib_swept = True  # which would take a file this old
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
# fetched the reading or took the cache an earlier render left, and whichever
# session it is: the shared scenarios mod/test/sources.test.ts replays too.
# A cached reading lost its account and window, so the panel and the mod
# wrote and read two files; and the scope was the session's, so every
# session of one account scanned for a file of its own.
with open(os.path.join(HERE, "fixtures", "sources", "collect.json")) as fh:
    scenarios = {c["name"]: c["steps"] for c in json.load(fh)}
PROFILE = "profile:" + hashlib.sha256(b"golden").hexdigest()[:24]
SCOPE = "claude-usage-tracker\0" + PROFILE + "\0" "1786838400"
ACCOUNT = "account:" + hashlib.sha256(
    b"11111111-2222-3333-4444-555555555555").hexdigest()[:24]
EXPECT = {
    "tracker: fresh, then cached, one scope": [SCOPE] * 3,
    "tracker: two sessions, one profile, one scope": [SCOPE] * 3,
    "tracker: another profile, another scope": [
        SCOPE, SCOPE.replace(PROFILE, "profile:" + hashlib.sha256(
            b"other").hexdigest()[:24])],
    "tracker: a profile with no id, the session": [
        "claude-usage-tracker\0session:s1\0" "1786838400",
        "claude-usage-tracker\0session:s2\0" "1786838400"],
    "native: two sessions, one signed-in account": [
        "native\0" + ACCOUNT + "\0" "1786838400"] * 3,
}
ENV = ("CODING_AGENT_USAGE_LINE_STATE_DIR",
       "CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST", "CLAUDE_CONFIG_DIR")
for name, scopes in EXPECT.items():
    steps = scenarios[name]
    assert [s["scope"] for s in steps] == scopes, name
    sessions = {s["built_context"]["session"] for s in steps}
    with tempfile.TemporaryDirectory() as tmp:
        saved = {k: os.environ.get(k) for k in ENV}
        os.environ[ENV[0]] = os.path.join(tmp, "s")
        tracker = os.environ[ENV[1]] = os.path.join(tmp, "tracker.plist")
        config = os.environ[ENV[2]] = os.path.join(tmp, "config")
        os.makedirs(config)
        try:
            for s in steps:
                with open(tracker, "w") as fh:
                    fh.write(s["tracker"])
                if s["claude_json"] is not None:
                    with open(os.path.join(config, ".claude.json"),
                              "w") as fh:
                        fh.write(s["claude_json"])
                p = claude_sources.prepare_claude_reading(
                    s["spec"], s["account"], s["period"],
                    s["built_context"], s["now"])
                got = claude.seed_limits_snapshot(p.limits,
                                                  p.reading)["_scope"]
                assert got == s["scope"], (name, s["now"], got)
                # The reading caches stay the session's.
                assert p.reading["account_name"] == (
                    "session:" + s["built_context"]["session"]), p.reading
            files = os.listdir(os.path.join(tmp, "s"))
            assert all("canary" not in open(os.path.join(tmp, "s", f)).read()
                       for f in files if f.endswith(".json"))
        finally:
            for k, v in saved.items():
                if v is None: os.environ.pop(k, None)
                else: os.environ[k] = v
    assert len(sessions) == (1 if "fresh" in name or "another" in name
                             else 2), (name, sessions)

# The tracker's id and the config's uuid are read hashed, and only them.
store = {"activeProfileId": "P1", "profiles_v3": json.dumps([
    {"id": "P1", "claudeUsage": {"sessionPercentage": 1},
     "oauthAccountJSON": "oauth-canary"}]).encode()}
reading = claude.tracker_reading(store)
assert reading["account_id"] == "profile:" + hashlib.sha256(
    b"P1").hexdigest()[:24], reading
assert "canary" not in json.dumps(reading)
assert "account_id" not in claude.tracker_reading(
    {"profiles_v3": json.dumps([{"claudeUsage": {}}])})
# A command cannot name the account: normalise has no such field, and the
# cache takes only the hashed form.
assert "account_id" not in sources.normalise(
    {"schema_version": 1, "account_id": "profile:" + "0" * 24,
     "windows": [{"id": "w", "used_percent": 1}]}, "cmd")
assert "account_id" not in sources._cached_reading(
    {"schema_version": 1, "account_id": "me", "as_of": 1,
     "windows": [{"id": "w", "used_percent": 1}]}, "cmd", 1, 60)

# The sweep: calibration caches untouched for CALIB_MAX_AGE_S, by name, at
# most once a day across processes, and never with an override in force.
with tempfile.TemporaryDirectory() as tmp:
    saved = (os.environ.get("CODING_AGENT_USAGE_LINE_STATE_DIR"),
             claude.CALIB_CACHE_OVERRIDE)
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = tmp
    claude.CALIB_CACHE_OVERRIDE = ""
    now = 2000000000.0
    old_t = now - claude.CALIB_MAX_AGE_S - 60
    def plant(name, t):
        path = os.path.join(tmp, name)
        open(path, "w").close()
        os.utime(path, (t, t))
    c = "claude-calibration-"
    h = "0123456789abcdef" * 4
    try:
        plant(c + h + ".cache", old_t)
        plant(c + h.replace("0", "a") + ".cache", now - 3600)
        plant(c + h + ".cache.tmp", old_t)
        plant(h + ".json", old_t)
        claude._calib_swept = False
        assert claude._sweep_calibrations(now) == 1
        left = sorted(os.listdir(tmp))
        assert left == sorted([c + h.replace("0", "a") + ".cache",
                               c + h + ".cache.tmp", h + ".json",
                               claude.CALIB_SWEPT]), left
        plant(c + h + ".cache", old_t)
        assert claude._sweep_calibrations(now) == 0      # once a process
        claude._calib_swept = False
        assert claude._sweep_calibrations(now) == 0      # once a day
        claude._calib_swept = False
        assert claude._sweep_calibrations(
            now + claude.CALIB_SWEEP_EVERY_S + 1) == 1
        plant(c + h + ".cache", old_t)
        claude._calib_swept = False
        claude.CALIB_CACHE_OVERRIDE = os.path.join(tmp, "calib.json")
        assert claude._sweep_calibrations(now + 9e6) == 0
    finally:
        if saved[0] is None:
            os.environ.pop("CODING_AGENT_USAGE_LINE_STATE_DIR", None)
        else:
            os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = saved[0]
        claude.CALIB_CACHE_OVERRIDE = saved[1]
print("ok Claude source bridge")
