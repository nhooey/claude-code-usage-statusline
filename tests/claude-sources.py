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
print("ok Claude source bridge")
