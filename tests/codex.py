#!/usr/bin/env python3
"""Offline contract checks for Codex per-request and legacy accounting."""
import json, os, sys, tempfile, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line.codex import read_requests, totals
from coding_agent_usage_line.codex import rollout_identity
from coding_agent_usage_line.models import TokenUsage, UsageRequest
from coding_agent_usage_line.render import account_summary, clean_text, codex_report, codex_stop_report, codex_summary
from coding_agent_usage_line.state import claim_reportable_requests

def check(name, got, want):
    if got != want:
        raise AssertionError("%s: %r != %r" % (name, got, want))
    print("ok", name)

fd, path = tempfile.mkstemp(); os.close(fd)
try:
    records = [
      {"type":"token_usage_record", "response_id":"r1", "session_id":"s", "turn_id":"t1", "usage":{"input_tokens":10,"cached_input_tokens":2,"output_tokens":7,"reasoning_output_tokens":4}},
      {"type":"token_usage_record", "response_id":"r1", "session_id":"s", "turn_id":"t1", "usage":{"input_tokens":10,"output_tokens":3}},
      {"type":"event_msg", "token_count":{"input_tokens":999,"output_tokens":999}},
      {"type":"token_usage_record", "response_id":"r2", "session_id":"s", "turn_id":"t2", "usage":{"input_tokens":5,"output_tokens":7}},
    ]
    with open(path, "w") as fh:
        for x in records: fh.write(json.dumps(x) + "\n")
        fh.write('{"type":"token_usage_record"')
    rows=read_requests(path)
    check("dedupe and incomplete tail", len(rows), 2)
    check("per response not cumulative", totals(rows), (15, None, 14, None))
    legacy=[{"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":3,"output_tokens":2}}}},
            {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":8,"output_tokens":4}}}}]
    from coding_agent_usage_line.codex import requests_from_records
    check("nested legacy counter delta", totals(requests_from_records(legacy)), (5, None, 2, None))
    mixed = [
        {"type":"turn_context", "payload":{"turn_id":"upgrade"}},
        {"type":"token_usage_record", "payload":{"turn_id":"upgrade", "response_id":"modern", "usage":{"input_tokens":10,"output_tokens":2}}},
        {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":15,"output_tokens":3}, "last_token_usage":{"input_tokens":5,"output_tokens":1}}}},
    ]
    mixed_diag = {}
    check("mixed same-turn preserves only identified requests", totals(requests_from_records(mixed, diagnostics=mixed_diag)), (10, None, 2, None))
    check("mixed same-turn exposes ambiguity", mixed_diag.get("ambiguous_legacy_records"), 1)
    duplicate_subset = mixed + [
        {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":20,"cached_input_tokens":0,"output_tokens":4}, "last_token_usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":2}}}},
        {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":20,"cached_input_tokens":0,"output_tokens":4}, "last_token_usage":{"input_tokens":10,"cached_input_tokens":0,"output_tokens":2}}}},
    ]
    check("repeated legacy subsets do not duplicate request", totals(requests_from_records(duplicate_subset)), (10, None, 2, None))
    cross_turn = [
        {"type":"turn_context", "payload":{"turn_id":"one"}},
        {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":3,"output_tokens":1}, "last_token_usage":{"input_tokens":3,"output_tokens":1}}}},
        {"type":"turn_context", "payload":{"turn_id":"two"}},
        {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":8,"output_tokens":3}}}},
    ]
    check("legacy counter carries across turns", totals(requests_from_records(cross_turn)), (8, None, 3, None))
    explicit_prefix = [
        {"type":"turn_context", "payload":{"turn_id":"modern-one"}},
        {"type":"token_usage_record", "payload":{"turn_id":"modern-one", "response_id":"one", "usage":{"input_tokens":10,"output_tokens":2}}},
        {"type":"turn_context", "payload":{"turn_id":"legacy-two"}},
        {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":15,"output_tokens":3}, "last_token_usage":{"input_tokens":5,"output_tokens":1}}}},
    ]
    check("different-turn legacy prefix is nonoverlapping", totals(requests_from_records(explicit_prefix)), (15, None, 3, None))
    reset = [
        {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":10,"output_tokens":2}, "last_token_usage":{"input_tokens":10,"output_tokens":2}}}},
        {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":5,"output_tokens":1}}}},
        {"type":"event_msg", "payload":{"type":"token_count", "info":{"total_token_usage":{"input_tokens":8,"output_tokens":3}}}},
    ]
    check("legacy reset establishes baseline", totals(requests_from_records(reset)), (13, None, 4, None))
finally: os.unlink(path)

fd, path = tempfile.mkstemp(); os.close(fd)
try:
    with open(path, "wb") as fh:
        fh.write(b'{"type":"token_usage_record","response_id":"utf8","usage":{"input_tokens":1}}\n')
        fh.write(b'\xf0\x9f')  # an interrupted UTF-8 writer tail
    check("partial UTF8 tail preserves complete records", len(read_requests(path)), 1)
finally: os.unlink(path)

# A known subset is not a complete total when another response omitted the
# category.  The renderer must not turn it into a fabricated session number.
partial = [UsageRequest("known", "s", "t", "t", "", None, "m", "", TokenUsage(4, None, 2, None)),
           UsageRequest("unknown", "s", "t", "t", "", None, "m", "", TokenUsage(None, None, 1, None))]
check("missing category keeps aggregate unknown", totals(partial), (None, None, 3, None))
check("summary marks missing total", "in ?" in codex_summary(partial), True)
check("terminal sanitizer strips C1", clean_text("safe\x1b[2J\x85label"), "safe[2Jlabel")
quota = account_summary({"buckets":[{"id":"general", "label":"general", "windows":[
    {"id":"primary", "duration_seconds":300, "used_percent":42, "resets_at":999999999999999999999, "expired":True}]}]},
    "default", "day", now=0)
check("quota uses duration and expired marker", "primary 5m 42% expired" in quota and "account default day" not in quota, True)
rich_quota = account_summary({"stale": True, "buckets": [
    {"id": "general", "label": "general", "windows": [
        {"id": "short", "duration_seconds": 300, "used_percent": 42, "resets_at": 3600},
        {"id": "weekly", "duration_seconds": 604800}]},
    {"id": "reasoning", "label": "reasoning", "model": "gpt-5", "windows": [
        {"id": "primary", "used_percent": 7, "expired": True}]}],
    "account": {"input_tokens": 12, "output_tokens": 3}}, "team-a", "month", now=0)
check("quota keeps bucket window hierarchy", "🔋 general:" in rich_quota and "🔋 reasoning (gpt-5):" in rich_quota, True)
check("quota keeps absent stale reset and expiry facts", "quota stale" in rich_quota and "weekly 7d unavailable" in rich_quota and "🔜 01:00Z" in rich_quota and "primary 7% expired" in rich_quota, True)
check("organization period is separate from quota", "💳 organization team-a month stale: 🧩 in 12 out 3" in rich_quota and "$" not in rich_quota, True)
check("summary uses shared model and token marks", "🤖" in codex_summary(partial, "gpt-5", "high") and "🧩" in codex_summary(partial, "gpt-5", "high"), True)
check("rollout metadata scopes empty transcript", rollout_identity([
    {"type":"session_meta", "payload":{"id":"thread", "session_id":"real-session"}},
    {"type":"turn_context", "payload":{"turn_id":"stop-turn", "model":"gpt-5.6-terra", "effort":"high"}}], "stop-turn"),
    {"session_id":"real-session", "model":"gpt-5.6-terra", "effort":"high"})
check("empty rollout chooses latest root context", rollout_identity([
    {"type":"session_meta", "payload":{"id":"thread", "session_id":"real-session"}},
    {"type":"turn_context", "payload":{"turn_id":"root-old", "model":"old", "effort":"low"}},
    {"type":"turn_context", "payload":{"turn_id":"child-copy", "root_turn_id":"root-old", "model":"child", "effort":"high"}},
    {"type":"turn_context", "payload":{"turn_id":"root-new", "model":"new", "effort":"medium"}}]),
    {"session_id":"real-session", "model":"new", "effort":"medium"})

# Report state is shared by origins in a session: a late child belonging to a
# previously reported root gets one incremental claim during a different Stop.
with tempfile.TemporaryDirectory() as tmp:
    before = os.environ.get("CODING_AGENT_USAGE_LINE_STATE_DIR")
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = tmp
    try:
        check("claims first root", claim_reportable_requests("session", "root-one", [("r1", "root-one")]), ["r1"])
        check("claims second root", claim_reportable_requests("session", "root-two", [("r2", "root-two")]), ["r2"])
        check("claims late earlier root", claim_reportable_requests("session", "root-two", [("r1", "root-one"), ("r2", "root-two"), ("late", "root-one")]), ["late"])
        check("late child remains exactly once", claim_reportable_requests("session", "root-two", [("late", "root-one")]), [])
        # State contains IDs and origin IDs only; user/assistant text never lands on disk.
        blobs = "".join(open(os.path.join(tmp, name), encoding="utf-8").read() for name in os.listdir(tmp) if name.endswith(".json"))
        check("report state has no prompt text", "sensitive prompt" in blobs, False)
    finally:
        if before is None: os.environ.pop("CODING_AGENT_USAGE_LINE_STATE_DIR", None)
        else: os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = before

# Actual 0.154-shaped metadata keeps thread ID distinct from session ID; a
# copied parent request in the child rollout is globally deduplicated.
with tempfile.TemporaryDirectory() as tmp:
    root=os.path.join(tmp, "root.jsonl"); child=os.path.join(tmp, "child.jsonl"); db=os.path.join(tmp, "state_5.sqlite")
    def put(path, rows):
        with open(path, "w") as fh:
            for row in rows: fh.write(json.dumps(row) + "\n")
    put(root, [
        {"type":"session_meta","payload":{"id":"thread-root","session_id":"session-real"}},
        {"type":"turn_context","payload":{"turn_id":"turn-a","model":"gpt-5.6-terra","effort":"high"}},
        {"type":"token_usage_record","payload":{"thread_id":"thread-root","session_id":"session-real","turn_id":"turn-a","response_id":"root-r","usage":{"input_tokens":10,"output_tokens":2}}},
        {"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":10,"output_tokens":2},"last_token_usage":{"input_tokens":10,"output_tokens":2},"model_context_window":100}}},
    ])
    put(child, [
        {"type":"session_meta","payload":{"id":"thread-child","session_id":"session-real","source":{"subagent":{"thread_spawn":{"parent_thread_id":"thread-root"}}}}},
        {"type":"token_usage_record","payload":{"thread_id":"thread-root","session_id":"session-real","turn_id":"turn-a","response_id":"root-r","usage":{"input_tokens":10,"output_tokens":2}}},
        {"type":"turn_context","payload":{"turn_id":"child-a","root_turn_id":"turn-a","model":"gpt-5.6-luna","effort":"low"}},
        {"type":"response_item","payload":{"type":"message","role":"user","content":[{"text":"child work\u0085summary"}]}},
        {"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"text":"finished"}]}},
        {"type":"token_usage_record","payload":{"thread_id":"thread-child","session_id":"session-real","turn_id":"child-a","root_turn_id":"turn-a","response_id":"child-r","usage":{"input_tokens":4,"output_tokens":1}}},
        {"type":"event_msg","payload":{"type":"task_complete","turn_id":"child-a"}},
    ])
    con=sqlite3.connect(db); con.execute("create table threads (id text primary key, rollout_path text, source text)"); con.execute("create table thread_spawn_edges (parent_thread_id text, child_thread_id text primary key, status text)")
    con.executemany("insert into threads values (?,?,?)", [("thread-root",root,"cli"),("thread-child",child,"subagent")]); con.commit(); con.close()
    from coding_agent_usage_line.codex import read_request_tree, root_context
    coverage = {}
    rows=read_request_tree(root, "session-real", db, coverage)
    check("thread/session child tree fork dedupe", totals(rows), (14, None, 3, None))
    check("child marked separately", [row.child for row in rows], [False, True])
    check("indexed child coverage diagnostic", coverage["child_coverage"], "indexed")
    check("root context only", root_context(__import__('coding_agent_usage_line.codex', fromlist=['parse_jsonl']).parse_jsonl(root))[2], 12)
    check("explicit zero root context survives", root_context([{"type":"event_msg", "payload":{"type":"token_count", "info":{"last_token_usage":{"input_tokens":0,"output_tokens":0,"total_tokens":0}, "model_context_window":100}}}])[2], 0)

    # Completion and bounded message metadata are available to the pure report.
    report = codex_report(rows)
    check("all report has grouped root total", "turn turn-a" in report and "in 14 out 3" in report, True)
    check("all report has completed child", "child child-a" in report and "complete" in report, True)
    check("all report sanitizes child messages", "user child worksummary" in report and "assistant finished" in report, True)

# A child without root_turn_id is retained as separate usage rather than being
# silently filed under its own child turn as though that were a root turn.
unattributed = UsageRequest("orphan", "s", "child-turn", "", "parent", None, "m", "", TokenUsage(3, None, 1, None), child=True)
from coding_agent_usage_line.codex import origin_turn
check("child without root stays unassociated", origin_turn(unattributed), "")
check("unassociated child is separately labelled", "unattributed child/session usage" in codex_report([unattributed]), True)
increment = codex_stop_report("root", [UsageRequest("new", "s", "root", "root", "", None, "m", "", TokenUsage(2, None, 1, None))], partial, {}, "m", "")
check("stop renderer labels incremental distinct from session", "incremental" in increment and "session total" in increment, True)
late_thread = UsageRequest("late", "s", "child", "root", "parent", None, "m", "", TokenUsage(1, None, 1, None),
                           thread_id="late-thread", child=True)
check("late child keeps its thread identity", "thread late-thread" in codex_stop_report("root", [], partial, {"root": [late_thread]}), True)
root_detail = UsageRequest("root", "s", "root", "root", "", None, "m", "", TokenUsage(2, None, 1, None),
                           started_at=1000, completed_at=1065, user_message="asked", assistant_message="answered", completed=True)
check("root lifecycle and excerpts render", "started 1970-01-01" in codex_report([root_detail]) and "elapsed 1.1m" in codex_report([root_detail]) and "assistant answered" in codex_report([root_detail]), True)
from coding_agent_usage_line.codex import _stamp
check("out of range timestamp unavailable", _stamp(1e300), None)
resume = requests_from_records([
    {"type":"session_meta", "payload":{"id":"child", "session_id":"s", "source":{"subagent":{"thread_spawn":{"parent_thread_id":"root"}}}}},
    {"type":"turn_context", "payload":{"turn_id":"old-child", "root_turn_id":"root-one"}},
    {"type":"turn_context", "payload":{"turn_id":"new-child"}},
    {"type":"token_usage_record", "payload":{"thread_id":"child", "turn_id":"new-child", "response_id":"unattributed", "usage":{"input_tokens":1}}},
    {"type":"event_msg", "payload":{"type":"task_complete", "turn_id":"new-child"}},
    {"type":"event_msg", "payload":{"type":"task_started", "turn_id":"new-child"}},
])
check("new context clears leaked root attribution", resume[0].root_turn_id, "")
check("resumed task clears completed lifecycle", resume[0].completed, False)
same_turn_children = [
    UsageRequest("c1", "s", "child", "root", "parent", None, "m", "", TokenUsage(1, None, 1, None),
                 thread_id="thread-one", child=True, completed=True),
    UsageRequest("c2", "s", "child", "root", "parent", None, "m", "", TokenUsage(2, None, 1, None),
                 thread_id="thread-two", child=True, completed=True),
]
same_turn_report = codex_report(same_turn_children)
check("same child turn IDs retain thread identity", "thread thread-one" in same_turn_report and "thread thread-two" in same_turn_report, True)
