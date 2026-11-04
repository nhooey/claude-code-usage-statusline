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
    # A corrupt report journal (non-list IDs) reads as empty, not a crash.
    import hashlib, json
    digest=hashlib.sha256(b"s\0t").hexdigest()
    with open(os.path.join(tmp, "reported-" + digest + ".json"), "w") as fh: json.dump({"request_ids":5}, fh)
    assert state.unreported_requests("s", "t", ["a"]) == ["a"]
    with open(state._report_path("s2"), "w") as fh: json.dump({"request_ids":None, "turn_ids":1}, fh)
    assert state.claim_reportable_requests("s2", "t", [("a", "t")]) == ["a"]
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
with tempfile.TemporaryDirectory() as tmp:
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = tmp
    # A window's use only rises until it resets, so each window reads at the
    # highest the account has given for it: sessions on 20, the account's
    # OAuth reading on 21 (its reset a fraction of a second later), and an
    # idle session's stale 16 all read 21.  Another account, a reading with
    # no account and the next window keep their own figures.
    acct, other, now, reset = ("account:aec47d42ff6857fec81c29d6",
                               "account:0123456789abcdef01234567", 1793786000, 1794272400)
    def weekly(pct, at=reset, **ident):
        value={"schema_version":1, "as_of":now, "buckets":[{"id":"default","label":"default",
               "windows":[{"id":"seven_day","duration_seconds":604800,"resets_at":at,"used_percent":pct}]}]}
        value.update(ident); return value
    pct=lambda value: value["buckets"][0]["windows"][0]["used_percent"]
    assert pct(sources.account_high("claude", weekly(20, account_id=acct), now)) == 20
    assert pct(sources.account_high("claude", weekly(21, reset + 0.435, account_name=acct), now)) == 21
    stale = weekly(16, account_id=acct)
    assert pct(sources.account_high("claude", stale, now)) == 21
    assert pct(stale) == 16, "the reading given is not changed"
    assert pct(sources.account_high("claude", weekly(20, account_id=acct), now)) == 21
    assert pct(sources.account_high("claude", weekly(16, account_id=other), now)) == 16
    assert pct(sources.account_high("claude", weekly(16), now)) == 16
    assert pct(sources.account_high("claude", weekly(5, reset + 604800, account_id=acct), now)) == 5
    # Past its reset a window's high is dropped, so the new window starts low.
    assert pct(sources.account_high("claude", weekly(2, reset + 604800, account_id=acct), reset + 1)) == 5
    assert pct(sources.account_high("claude", weekly(1, reset, account_id=acct), reset + 1)) == 1
    # A corrupt highs file reads as none.
    state.save("claude", sources.HIGHS_SOURCE, other, sources.HIGHS_PERIOD, {"windows": [1]})
    assert pct(sources.account_high("claude", weekly(3, account_id=other), now)) == 3
print("ok source cache selection and freshness")
