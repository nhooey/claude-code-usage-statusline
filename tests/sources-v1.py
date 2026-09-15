#!/usr/bin/env python3
"""Boundary/safety regression cases for source contract v1."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line.sources import epoch, normalise, collect, native_reading, command_reading, has_reading

assert epoch("2026-09-14T12:00:00+07:00") == epoch("2026-09-14T05:00:00Z")
reading=normalise({"schema_version":1, "account":{"access_token":"fixture-canary", "cost_usd":3}})
assert "access_token" not in repr(reading)
assert reading["account"] == {"cost_usd":3}
assert not has_reading(normalise({"schema_version":1,"buckets":[{"id":"x","label":"x","windows":[{"id":"quota"}]}],"account":{"scope":"organization"}}))
assert normalise({"schema_version":1, "buckets":[{"id":"\x9bunsafe", "windows":[]} ]})["buckets"] == []
# Canonical grouped quotas survive normalization/cache round trips without
# merging Astra's weekly-only general bucket into a separate Spark bucket.
bucketed={"schema_version":1,"buckets":[
    {"id":"general","label":"general","windows":[{"id":"weekly","duration_seconds":604800,"used_percent":97,"resets_at":1000}]},
    {"id":"spark","label":"Spark","windows":[{"id":"five-hour","duration_seconds":18000,"used_percent":100,"resets_at":2000},{"id":"weekly","duration_seconds":604800,"used_percent":100,"resets_at":3000}]}]}
one=normalise(bucketed, "fixture"); two=normalise(one, "fixture")
assert one == two and [len(x["windows"]) for x in two["buckets"]] == [1, 2]
assert "model" not in two["buckets"][0] and two["buckets"][1]["label"] == "Spark"
# Equal duration/reset does not permit cross-bucket deduplication.
native=normalise({"schema_version":1,"windows":[{"id":"weekly","bucket_id":"general","heading":"general","duration_seconds":604800,"used_percent":97,"resets_at":5},{"id":"weekly","bucket_id":"spark","heading":"Spark","duration_seconds":604800,"used_percent":100,"resets_at":5}]})
assert [b["id"] for b in native["buckets"]] == ["general", "spark"]
raw_native={"rateLimitsByLimitId":{"general":{"limitId":"general","limitName":"general","secondary":{"usedPercent":97,"windowDurationMins":10080,"resetsAt":5}},"spark":{"limitId":"spark","limitName":"Spark","primary":{"usedPercent":100,"windowDurationMins":300,"resetsAt":5},"secondary":{"usedPercent":100,"windowDurationMins":10080,"resetsAt":5}}}}
assert [len(b["windows"]) for b in native_reading("codex", {"rate_limits": raw_native})["buckets"]] == [1, 2]
# A keyed provider map is canonical over a stale standalone snapshot with the
# same bucket ID; matching duration/reset never authorizes cross-bucket merge.
duplicate={"limitId":"general","primary":{"usedPercent":1,"windowDurationMins":300},"rateLimitsByLimitId":{"general":{"secondary":{"usedPercent":60,"windowDurationMins":10080},"limitName":"General"},"spark":{"primary":{"usedPercent":100,"windowDurationMins":300},"limitName":"Spark"}}}
got=native_reading("codex", {"rate_limits":duplicate})
assert [(b["id"], [w["id"] for w in b["windows"]]) for b in got["buckets"]] == [("general", ["secondary"]), ("spark", ["primary"])]
# Explicit native always consumes the current supplied snapshot, even when a
# prior cached observation exists within its fetch TTL.
native_context={"rate_limits":{"five_hour":{"used_percent":7,"resets_at":2000}}, "as_of":999}
assert collect("claude", "native", context=native_context, now=1000)["buckets"][0]["windows"][0]["used_percent"] == 7
with tempfile.TemporaryDirectory() as tmp:
    script=os.path.join(tmp, "source.py")
    count=os.path.join(tmp, "count")
    with open(script, "w") as fh: fh.write("#!/bin/sh\necho x >> %s\nprintf '{\\\"schema_version\\\":1,\\\"as_of\\\":1,\\\"windows\\\":[{\\\"id\\\":\\\"x\\\",\\\"used_percent\\\":12}]}'\n" % count)
    os.chmod(script, 0o700)
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"]=os.path.join(tmp, "state")
    got=collect("codex", "cmd:" + script, "a/b", "day", now=1000)
    assert got["buckets"][0]["windows"][0]["used_percent"] == 12
    # The old observation is visibly stale but its recent fetch does not
    # cause command execution on every render.
    assert collect("codex", "cmd:" + script, "a/b", "day", now=1001)["stale"] is True
    assert len(open(count).read().splitlines()) == 1
    # no source selected: compatible scoped cache is still readable
    assert collect("codex", "none", "a/b", "day", now=1001)["buckets"][0]["windows"][0]["id"] == "x"
    flood=os.path.join(tmp, "flood.py")
    with open(flood, "w") as fh: fh.write("#!/usr/bin/env python3\nimport sys,time\nsys.stdout.write('x'*1100000); sys.stdout.flush(); time.sleep(10)\n")
    os.chmod(flood, 0o700)
    assert command_reading(flood, {"agent":"codex", "rate_limits":{"secret":"no"}}, timeout=1) == {}
    invalid=os.path.join(tmp, "invalid.py")
    with open(invalid, "w") as fh: fh.write("#!/usr/bin/env python3\nprint('not-json')\n")
    os.chmod(invalid, 0o700)
    assert command_reading(invalid, {"agent":"codex"}, timeout=1) == {}
    close_soon=os.path.join(tmp, "close-soon.py")
    with open(close_soon, "w") as fh: fh.write("#!/usr/bin/env python3\nimport sys,time\nprint('{\\\"schema_version\\\":1,\\\"windows\\\":[{\\\"id\\\":\\\"x\\\",\\\"used_percent\\\":1}]}'); sys.stdout.flush(); sys.stdout.close(); time.sleep(.03)\n")
    os.chmod(close_soon, 0o700)
    assert command_reading(close_soon, {"agent":"codex"}, timeout=1)["buckets"][0]["windows"][0]["used_percent"] == 1
    child=os.path.join(tmp, "child.py"); pidfile=os.path.join(tmp, "child.pid")
    with open(child, "w") as fh: fh.write("#!/usr/bin/env python3\nimport subprocess,time\np=subprocess.Popen(['sleep','10']); open(%r,'w').write(str(p.pid)); time.sleep(10)\n" % pidfile)
    os.chmod(child, 0o700)
    assert command_reading(child, {"agent":"codex"}, timeout=1) == {}
    pid=int(open(pidfile).read())
    time.sleep(.1)  # allow init to reap the killed process-group child
    try:
        os.kill(pid, 0)
        raise AssertionError("command child survived cleanup")
    except ProcessLookupError:
        pass
print("ok source timestamp and whitelist")
