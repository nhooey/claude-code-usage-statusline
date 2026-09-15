#!/usr/bin/env python3
"""Deterministic source selection, freshness and cache-isolation contracts."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line import sources, state

def reading(pct, as_of):
    return {"schema_version":1, "source":"cmd", "as_of":as_of,
            "buckets":[{"id":"default","label":"default","windows":[{"id":"x","used_percent":pct}]}], "account":{}}

with tempfile.TemporaryDirectory() as tmp:
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = tmp
    calls=[]
    old_command, old_app = sources.command_reading, sources.codex_app_server
    sources.command_reading=lambda path, context: calls.append(path) or {}
    sources.codex_app_server=lambda: (_ for _ in ()).throw(AssertionError("external fallback"))
    try:
        # Failure backoff works even where no reading exists to normalize.
        assert sources.collect("codex", "cmd:/fixture", context={"session":"backoff"}, now=1000) == {}
        assert sources.collect("codex", "cmd:/fixture", context={"session":"backoff"}, now=1001) == {}
        assert calls == ["/fixture"]
        # Credential identity outranks a coincidental session identifier.
        os.environ["OPENAI_ADMIN_KEY"]="one"; a=sources._cache_namespace("openai-admin", "default", {"session":"same"})
        os.environ["OPENAI_ADMIN_KEY"]="two"; b=sources._cache_namespace("openai-admin", "default", {"session":"same"})
        assert a != b
        os.environ["CODEX_USAGE_ACCESS_TOKEN"]="same-token"; os.environ["CODEX_USAGE_ACCOUNT_ID"]="one"
        a=sources._cache_namespace("experimental-codex-api", "default", {"session":"same"})
        os.environ["CODEX_USAGE_ACCOUNT_ID"]="two"
        b=sources._cache_namespace("experimental-codex-api", "default", {"session":"same"})
        assert a != b
        # none classifies a supplied ancient native snapshot as stale.
        old={"rate_limits":{"five_hour":{"used_percent":17}},"as_of":1,"session":"native"}
        assert sources.collect("claude", "none", context=old, now=1000)["stale"] is True
        # Valid native cache wins over stale current data and never starts app-server.
        ns=sources._cache_namespace("auto", "default", {"session":"native"})
        state.save("codex", "native", ns, "0", dict(reading(60, 990), fetched_at=990))
        stale={"session":"native", "rate_limits":{"five_hour":{"used_percent":17}},"as_of":1}
        assert sources.collect("codex", "auto", context=stale, now=1000)["buckets"][0]["windows"][0]["used_percent"] == 60
        # Explicit native falls back to a compatible native cache, never external.
        assert sources.collect("codex", "native", context={"session":"native"}, now=1000)["buckets"][0]["windows"][0]["used_percent"] == 60
        supplied={"rate_limits":{"five_hour":{"used_percent":17}},"as_of":990}
        for spec in ("native", "none", "off"):
            one=sources.collect("claude", spec, account="one", context=supplied, now=1000)
            two=sources.collect("claude", spec, account="two", context=supplied, now=1000)
            assert one["agent"] == two["agent"] == "claude" and one["source"] == two["source"] == "native"
            assert one["account_name"] != two["account_name"] and one["period_start"] == two["period_start"]
        unknown=sources.collect("claude", "native", context=supplied, now=1000)
        assert unknown["account_name"] == "default" and unknown["source"] == "native"
        # A fresh status-like native snapshot is persisted for a later Stop;
        # stale live input still wins only for its current explicit render.
        live={"session":"bridge","rate_limits":{"five_hour":{"used_percent":44}},"as_of":995}
        assert sources.collect("claude", "native", context=live, now=1000)["buckets"][0]["windows"][0]["used_percent"] == 44
        assert sources.collect("claude", "native", context={"session":"bridge"}, now=1001)["buckets"][0]["windows"][0]["used_percent"] == 44
        stale={"session":"bridge","rate_limits":{"five_hour":{"used_percent":1}},"as_of":1}
        assert sources.collect("claude", "native", context=stale, now=1001)["buckets"][0]["windows"][0]["used_percent"] == 1
        assert sources.collect("claude", "native", context={"session":"bridge"}, now=1001)["buckets"][0]["windows"][0]["used_percent"] == 44
    finally:
        sources.command_reading, sources.codex_app_server = old_command, old_app
print("ok source cache selection and freshness")
