#!/usr/bin/env python3
"""Offline v1 coverage for Claude tracker, command, and scoped cache intake."""
import json, os, plistlib, sys, tempfile, time

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from coding_agent_usage_line import claude, sources, state

NOW=1788860278.0; APPLE=978307200.0; CANARY="oauth-canary-must-never-be-copied"
passed=0
def check(name, got, want):
    global passed
    assert got == want, "%s: %r != %r" % (name, got, want)
    passed += 1; print("  ok   ", name)

def store(path, usage=None, active="P1", selected=False, extra=None):
    usage=usage or {"sessionPercentage":98,"sessionResetTime":1788864600.363-APPLE,
        "weeklyPercentage":10,"opusWeeklyPercentage":3,"weeklyResetTime":1789434000.363-APPLE,
        "lastUpdated":NOW-60-APPLE}
    profiles=[{"id":"P0","claudeUsage":{"sessionPercentage":1,"weeklyPercentage":1},"isSelectedForDisplay":selected},
              {"id":"P1","claudeUsage":usage,"oauthAccountJSON":CANARY}]
    value={"activeProfileId":active,"profiles_v3":json.dumps(profiles).encode()}; value.update(extra or {})
    with open(path,"wb") as fh: plistlib.dump(value,fh)

with tempfile.TemporaryDirectory(prefix="usage-source.") as tmp:
    primary=os.path.join(tmp,"primary.plist"); store(primary)
    with open(primary,"rb") as fh: raw=claude.tracker_reading(plistlib.load(fh))
    check("tracker session",raw.get("session_pct"),98); check("tracker weekly",raw.get("weekly_pct"),10)
    check("tracker opus",raw.get("weekly_opus_pct"),3); check("CFDate reset",raw.get("session_resets_at"),1788864600.363)
    check("weekly CFDate reset",raw.get("weekly_resets_at"),1789434000.363)
    check("CFDate as_of",raw.get("as_of"),NOW-60)
    # Tracker adapter normalizes to grouped v1 and persists only safe fields.
    old=os.environ.get("CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST"); os.environ["CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST"]=primary
    try: reading=sources.claude_usage_tracker()
    finally:
        if old is None: os.environ.pop("CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST",None)
        else: os.environ["CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST"]=old
    wins=reading["buckets"][0]["windows"]
    check("v1 tracker session",wins[0]["used_percent"],98.0); check("v1 tracker reset",wins[0]["resets_at"],1788864600.363)
    check("v1 tracker as_of",reading["as_of"],NOW-60)
    check("v1 strict envelope keys",sorted(reading),["account","as_of","buckets","schema_version","source"])
    assert CANARY not in repr(reading); passed+=1; print("  ok    tracker canary whitelist")
    # Active, selected-display, first-profile fallback and bad old schemas.
    other=os.path.join(tmp,"other.plist"); store(other,active="P0")
    with open(other,"rb") as fh: check("active profile",claude.tracker_reading(plistlib.load(fh))["session_pct"],1)
    selected=os.path.join(tmp,"selected.plist"); store(selected,active="gone",selected=True)
    with open(selected,"rb") as fh: check("selected fallback",claude.tracker_reading(plistlib.load(fh))["session_pct"],1)
    first=os.path.join(tmp,"first.plist"); store(first,active="gone")
    with open(first,"rb") as fh: check("first fallback",claude.tracker_reading(plistlib.load(fh))["session_pct"],1)
    check("pre-migration rejected",claude.tracker_reading({"usageHistory_ABC":"{}"}),{})
    check("empty rejected",claude.tracker_reading({}),{})
    check("malformed profiles rejected",claude.tracker_reading({"profiles_v3":b"{"}),{})
    check("missing usage rejected",claude.tracker_reading({"profiles_v3":json.dumps([{"id":"P1"}])}),{})
    # V1 validation preserves missing data, marks expired windows later, and
    # does not manufacture an envelope from flat unknown JSON.
    v1=sources.normalise({"schema_version":1,"as_of":NOW,"windows":[{"id":"x","used_percent":"42","resets_at":NOW-1}]},"cmd")
    check("v1 percent numeric",v1["buckets"][0]["windows"][0]["used_percent"],42.0)
    check("v1 past reset retained",v1["buckets"][0]["windows"][0]["resets_at"],NOW-1)
    expired=sources._cached_reading(v1,"cmd",NOW,60)
    check("past reset marked expired",expired["buckets"][0]["windows"][0]["expired"],True)
    check("unknown flat rejected",sources.normalise({},"cmd"),{})
    check("non-dict rejected",sources.normalise([],"cmd"),{})
    check("no-metrics envelope",sources.has_reading(sources.normalise({"schema_version":1,"windows":[{"id":"x"}],"account":{"scope":"organization"}},"cmd")),False)
    check("source none",sources.validate_source("claude","none"),"none")
    check("source off",sources.validate_source("claude","off"),"off")
    check("source command",sources.validate_source("claude","cmd:/bin/echo"),"cmd:/bin/echo")
    try: sources.validate_source("claude","codex-app-server")
    except ValueError: passed+=1; print("  ok    cross-provider rejected")
    else: raise AssertionError("cross-provider source accepted")
    try: sources.validate_source("claude","unknown-source")
    except ValueError: passed+=1; print("  ok    unknown source rejected")
    else: raise AssertionError("unknown source accepted")
    # Executable and bash fallback commands, nonzero, missing, and safe stdin.
    script=os.path.join(tmp,"flat.sh")
    with open(script,"w") as fh: fh.write("#!/bin/sh\nprintf '{\"session_pct\":7,\"weekly_pct\":8,\"session_resets_at\":%d}'\n" % int(NOW+7200))
    got=sources.command_reading(script,{"agent":"claude","session":"s","account":"a","period":"day"})
    check("bash flat adapter",got["buckets"][0]["windows"][0]["used_percent"],7.0)
    broken=os.path.join(tmp,"broken.sh"); open(broken,"w").write("#!/bin/sh\necho nope\nexit 3\n")
    check("nonzero command",sources.command_reading(broken,{}),{}); check("missing command",sources.command_reading(os.path.join(tmp,"none"),{}),{})
    # Scoped cache fill, disk whitelist, failed refresh retention and off read.
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"]=os.path.join(tmp,"state")
    live=os.path.join(tmp,"live.py"); open(live,"w").write("#!/usr/bin/env python3\nprint(%r)\n" % json.dumps({"schema_version":1,"as_of":1,"windows":[{"id":"x","used_percent":9}],"account":{"access_token":CANARY,"cost_usd":1}})); os.chmod(live,0o700)
    filled=sources.collect("claude","cmd:"+live,"account-a","day",{"session":"s"},now=1000)
    check("scoped cache fill",filled["buckets"][0]["windows"][0]["used_percent"],9.0)
    cached=state.find_compatible("claude","account-a","0")
    assert CANARY not in json.dumps(cached); passed+=1; print("  ok    cache whitelist")
    os.unlink(live)
    check("failed refresh keeps cache",sources.collect("claude","cmd:"+live,"account-a","day",{"session":"s"},now=1100)["buckets"][0]["windows"][0]["used_percent"],9.0)
    check("off reads compatible cache",sources.collect("claude","off","account-a","day",{"session":"s"},now=1101)["buckets"][0]["windows"][0]["used_percent"],9.0)
    check("none separate account",sources.collect("claude","none","account-b","day",{"session":"s"},now=1101),{})
    # Collector-level auto uses only the fixture tracker; none in a fresh
    # state never consults it or another account's cache.
    os.environ["CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST"] = primary
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = os.path.join(tmp,"auto-state")
    check("auto tracker fixture",sources.collect("claude","auto","auto-a","day",{"session":"auto"},now=NOW)["buckets"][0]["windows"][0]["used_percent"],98.0)
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = os.path.join(tmp,"none-state")
    check("none asks no source",sources.collect("claude","none","auto-a","day",{"session":"auto"},now=NOW),{})

print("\npass %d   fail 0   missing 0" % passed)
