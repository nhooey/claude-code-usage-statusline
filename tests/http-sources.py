#!/usr/bin/env python3
"""Offline HTTP fixture contracts for admin and opt-in subscription sources."""
import json, os, sys
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line import sources

class Response:
    def __init__(self, obj): self.data=json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *x): pass
    def read(self, n):
        part, self.data = self.data[:n], self.data[n:]
        return part

def opener_for(pages):
    def open_(request, timeout=0):
        url=request.full_url; key=urlparse(url).path + "?" + parse_qs(urlparse(url).query).get("page", [""])[0]
        value=pages.get(key)
        if value == "bad": raise OSError("fixture failure")
        return Response(value)
    return open_

old_a=os.environ.get("ANTHROPIC_ADMIN_KEY"); old_o=os.environ.get("OPENAI_ADMIN_KEY")
os.environ["ANTHROPIC_ADMIN_KEY"]="x"
pages={
 "/v1/organizations/usage_report/messages?":{"data":[{"results":[{"uncached_input_tokens":2,"cache_read_input_tokens":3,"cache_creation":{"ephemeral_5m_input_tokens":4},"output_tokens":5}]}],"has_more":True,"next_page":"u2"},
 "/v1/organizations/usage_report/messages?u2":{"data":[{"results":[{"uncached_input_tokens":1,"cache_read_input_tokens":0,"output_tokens":2}]}],"has_more":False},
 "/v1/organizations/cost_report?":{"data":[{"results":[{"amount":"150","currency":"USD"}]}],"has_more":True,"next_page":"c2"},
 "/v1/organizations/cost_report?c2":{"data":[{"results":[{"amount":"50","currency":"USD"}]}],"has_more":False},
}
a=sources.anthropic_admin("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", opener_for(pages))
assert a["account"]["cost_usd"] == 2 and a["account"]["input_tokens"] == 10 and a["account"]["cached_input_tokens"] == 3
# A failed second page cannot become a plausible zero/partial period.
pages["/v1/organizations/cost_report?c2"]="bad"
assert sources.anthropic_admin("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", opener_for(pages)) == {}
os.environ["OPENAI_ADMIN_KEY"]="x"
op={
 "/v1/organization/usage/completions?":{"data":[{"results":[{"input_tokens":10,"input_cached_tokens":4,"output_tokens":2}]}],"has_more":False},
 "/v1/organization/costs?":{"data":[{"results":[{"amount":{"value":"1.25","currency":"usd"}}]}],"has_more":False},
}
o=sources.openai_admin(0, 10, opener_for(op)); assert o["account"]["cost_usd"] == 1.25 and o["account"]["input_tokens"] == 10
# Opt-in only and actual nested WHAM layout.
os.environ.pop("CODEX_USAGE_ACCESS_TOKEN", None); os.environ.pop("CODEX_USAGE_ACCOUNT_ID", None)
assert sources.experimental_codex_api(opener_for({})) == {}
os.environ["CODEX_USAGE_ACCESS_TOKEN"]="x"; os.environ["CODEX_USAGE_ACCOUNT_ID"]="a"
w=sources.experimental_codex_api(opener_for({"/backend-api/wham/usage?":{"rate_limit":{"primary_window":{"limit_id":"p","limit_window_seconds":3600,"used_percent":12}},"additional_rate_limits":[{"limit_name":"x","rate_limit":{"primary_window":{"limit_window_seconds":60,"used_percent":4}}}]}}))
assert [x["id"] for b in w["buckets"] for x in b["windows"]] == ["codex:primary", "additional:0:primary"]
features=sources.experimental_codex_api(opener_for({"/backend-api/wham/usage?":{"additional_rate_limits":[
    {"limit_name":"same","metered_feature":"alpha","rate_limit":{"primary_window":{"limit_window_seconds":60,"used_percent":4,"reset_at":1}}},
    {"limit_name":"same","metered_feature":"beta","rate_limit":{"primary_window":{"limit_window_seconds":60,"used_percent":4,"reset_at":1}}}
]}}))
assert [b["id"] for b in features["buckets"]] == ["alpha", "beta"]
# HTTP Retry-After is retained as source failure metadata; the collector never
# exposes the authenticated error body.
def throttled(request, timeout=0):
    raise HTTPError(request.full_url, 429, "throttled", {"Retry-After":"17"}, None)
failure={}; assert sources.experimental_codex_api(throttled, failure) == {} and failure["retry_after"] == 17
assert sources._retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412000) == 480
assert sources.normalise({"schema_version":1,"windows":[{"id":"x","used_percent":"NaN"}]})["buckets"][0]["windows"][0]["used_percent"] is None
assert sources.normalise({"schema_version":2,"windows":[]}) == {}
assert sources.request_pages("https://x", {}, opener=opener_for({"/?":{"data":{},"has_more":False}})) is None
# Missing mandatory Anthropic fields and a non-dict OpenAI result are unavailable.
bad={"/v1/organizations/usage_report/messages?":{"data":[{"results":[{"output_tokens":1}]}],"has_more":False}, "/v1/organizations/cost_report?":{"data":[],"has_more":False}}
assert sources.anthropic_admin(0, 1, opener_for(bad)) == {}
op["/v1/organization/usage/completions?"]={"data":[{"results":[None]}],"has_more":False}
assert sources.openai_admin(0, 1, opener_for(op)) == {}
# Private Claude's stable windows retain their known durations.
os.environ["CLAUDE_OAUTH_ACCESS_TOKEN"]="x"
c=sources.experimental_claude_oauth(opener_for({"/api/oauth/usage?":{"five_hour":{"utilization":1},"seven_day":{"utilization":2}}}))
assert [x["duration_seconds"] for b in c["buckets"] for x in b["windows"]] == [18000.0, 604800.0]
print("ok HTTP sources")
