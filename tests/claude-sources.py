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
assert claude_sources.legacy_limits(dict(p.reading, stale=True)) == claude_sources.NO_LIMITS
print("ok Claude source bridge")
