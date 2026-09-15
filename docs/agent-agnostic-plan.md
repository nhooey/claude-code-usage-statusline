# coding-agent-usage-line implementation plan

Implemented and deterministically verified on 2026-09-14. See the
[final checkpoint](implementation-checkpoint.md) for results and manual checks.
The design and acceptance decisions below remain the implementation contract.

Revised 2026-09-14 after a higher-capability model review. This is the execution
brief for a fresh-context implementation agent using GPT-5.6 Terra, high
reasoning effort. Initial implementation used medium effort; independent
integration review justified the increase. Implementation is authorized; no further product decisions
are needed. Preserve the existing uncommitted working tree as the baseline.

## Accepted product decisions

- Product and launcher: `coding-agent-usage-line` and
  `coding-agent-usage-line.py`. Keep the repository, remote URLs and checkout
  directory named `claude-code-usage-statusline` for now. Delete the former
  launcher after moving its implementation; no compatibility executable.
- Require `--agent claude|codex` for operational modes. Preserve current display
  flags and Claude's status, Stop-hook and subagent-panel output, including all
  working-tree golden bytes. The clean break concerns the name and CLI, not a
  gratuitous redesign of Claude's output.
- Use a small Python package with a thin launcher, Python 3.9+, standard library
  only. No package installation should be necessary to execute the checkout.
- Agent integration and account-usage intake are independent options. Support
  native data, tracker app, custom commands, official organization APIs and
  explicitly experimental subscription APIs.
- Codex gets a native Stop-hook summary, one-shot status and historical reports,
  plus child-thread aggregation and separate completed-child report rows.
  Document Codex's own `/statusline` for its live footer. Its configured footer
  identifiers do not constitute an external command hook. No replacement TUI.
- Hide unavailable Codex metrics. Do not convert subscription tokens into API
  dollars or infer session quota shares from whole-account percentage changes.
  Preserve Claude's existing explicitly documented estimated accounting.

## Review corrections to the earlier plan

1. Separate request usage from cumulative usage. New Codex `token_usage_record`
   rows have per-response `usage`, plus turn and thread totals. Sum deduplicated
   response usage; never sum the cumulative fields or also add legacy
   `event_msg/token_count` snapshots. Legacy-only recordings require differences
   of cumulative counters, including duplicate and reset handling.
2. Missing, zero, estimated and measured are different states. Optional token,
   context and cost fields preserve missing data. Cached-input tokens are part
   of input; reasoning-output tokens are part of output. Never count either
   subset twice or apply Claude model/context/pricing defaults to Codex.
3. Cache identity must include agent, provider/source, account namespace and
   applicable reporting period. Session state must include the real session ID
   and agent. A path basename is insufficient for a Codex rollout.
4. Official admin reports describe organization activity and cannot supply a
   personal subscription quota or a particular turn's bill. Render them as
   separate, labeled account-period rows. Never add their usage to session sums.
5. Include BOTH requested private subscription collectors:
   `experimental-claude-oauth` and `experimental-codex-api`. Their wire formats
   are versioned fixture contracts, not promised vendor interfaces.
6. Codex Stop runs before the end-of-turn record may be written. Select its
   supplied `turn_id`; do not wait for an event that can only follow the hook.
   Poll only for an incomplete appended record within a small bounded budget.
7. Preserve quota bucket/heading hierarchy, not one global 5-hour/weekly pair.
   A bucket's identity, label and explicitly supplied model association belong
   to the bucket; its windows, durations, percentages and reset anchors belong
   beneath it. The selected session model does not own every displayed window.
   Missing windows stay absent, even when another bucket has the same duration.

### Quota-bucket correction from observed Codex output

The user reported these observations from separate sessions. They are regression
examples, not universal quota values or inferred backend allocation rules:

- GPT-5.6 Sol: general 5-hour 31% resetting at 20:15, general weekly 89%
  resetting September 21 at 15:15.
- GPT-6 Astra: general weekly 97% resetting September 21 at 17:17, with no
  general/Astra 5-hour meter displayed. Following rows under the explicit Spark
  heading were Spark's 5-hour 100% and weekly 100%, not Astra's.

Keep the general bucket's weekly-only shape and the separate Spark bucket's two
windows. Do not borrow Spark's 5-hour value, relabel Spark as the active model,
or merge windows merely because their durations match. Different reset anchors
are evidence against collapsing buckets; reasoning effort may affect consumption
but does not establish bucket identity. Preserve the provider's explicit bucket
identity/heading and model metadata where available; otherwise leave the model
association unknown rather than guessing it from the selected session model.

## Architecture and CLI

Create `coding_agent_usage_line` with explicit modules for CLI/orchestration,
immutable records, formatting/terminal geometry, rendering, state/cache,
Claude parsing/accounting, Codex parsing/accounting and usage sources. Split the
existing file at real boundaries rather than leaving a legacy monolith behind a
facade. Renderer functions must not read vendor transcripts, call usage sources
or scan agent histories. Orchestration prepares one snapshot and passes it in.
Preserve tested glyph widths, colors, fixed-width reservations and Claude hook
chrome; separate Codex's plain warning/report presentation from Claude chrome.

Normalized records carry agent/session/turn identity, model and effort, root
context occupancy and capacity, token categories, request identity/time,
optional money and its provenance, user/assistant text and time, child relations,
and quota/account snapshots. Quota snapshots contain named buckets with nested
windows, not a flattened session/weekly pair. A bucket carries a stable source
ID, heading and optional explicitly reported model/feature association. Window
identity includes its owning bucket plus its slot/ID. Preserve this structure
through collection, normalization, caching, diagnostics and rendering.
Extend existing immutable records where practical;
do not force a wholesale schema rewrite merely to change names.

CLI contract:

- `--mode status|cost|subagent` (default status); `--agent` required except for
  help and terminal self-test. Validate flags before reading stdin.
- `--transcript PATH` applies to status and cost and overrides a hook path.
  Explicit files do not require stdin. Without a file, consume the vendor's
  JSON payload. Missing Codex transcript is a missing-data result, not a scan
  for whichever session happens to be newest.
- `--all` with cost prints all turns and completed child rows as plain text.
  Normal cost output is one `{"systemMessage": "..."}` object. Operational
  hook failures return `{}` and exit 0 without influencing agent execution.
- Codex subagent mode exits 2 with an explanation and the supported report
  alternative. Retain Claude's subagent JSONL contract.
- `--usage-source SPEC` defaults to auto. Recognize auto, native, none/off,
  claude-usage-tracker, codex-app-server, anthropic-admin, openai-admin,
  experimental-claude-oauth, experimental-codex-api and cmd:PATH.
- Auto: current native reading, then valid native cache, then an available
  tracker for Claude or app-server for Codex. Never auto-select private/admin
  endpoints just because a credential exists. Native excludes external refresh.
  None/off preserves the existing offline semantics: do not refresh external
  sources, but native data and compatible cached readings remain readable.
- Explicit external selection controls account intake; do not silently replace
  it with another source or override it with native data. Reject a source that
  is for the other provider. Transcripts still supply session metrics.
- `--account-period day|week|month` defaults to day; calendar boundaries are UTC,
  week starts Monday, and period end is now. Label account scope and period.
- `--account NAME` supplies a non-secret cache namespace (default default).
  Honor CODEX_HOME as an input for Codex data. All application-owned env vars
  become CODING_AGENT_USAGE_LINE_*; vendor credentials retain vendor names.
- An explicit `--diagnose` emits redacted source/capability/freshness diagnostics
  separately from normal hook output, making missing sources inspectable.

## Usage-source contract and collection

Use a documented version-1 JSON reading for custom commands: schema_version,
as_of, buckets, optional account. Each bucket has id, label, optional explicit
model/feature association and windows. Each window has id, duration_seconds,
used_percent and optional resets_at. Accept the earlier flat version-1 windows
shape as one unassociated default bucket; never assign it to the active model
implicitly. Account has period_start/period_end,
optional token categories and cost_usd. Timestamps are Unix seconds or RFC3339
at the boundary and normalized to UTC epochs internally. Retain an adapter for
the old flat command reading so an unrelated script rewrite is unnecessary.
Commands receive a small JSON context on stdin (agent/session/model/account and
period, no conversation text or credentials). Execute a single path, never a
shell string; retain bash fallback for existing non-executable scripts.

Implement all collectors, with transport calls injectable for offline tests:

- Claude native rate_limits and tracker plist: retain known schemas and
  tracker profile selection. Keep the plist override for fixtures under the new
  application env prefix. No tracker is required for native Claude usage.
- Codex native: read quota snapshots from its rollout. Keep reported duration
  and limit identity; do not assume every window is 5 hours or every secondary
  window weekly. Preserve all bucket IDs/headings and each bucket's own window
  set. Render additional buckets as separate labeled groups, including a bucket
  with only a weekly meter. Never fill a missing window from another bucket.
- Codex app-server: initialize JSON-RPC over `codex app-server --stdio`, send
  initialized, call account/rateLimits/read, normalize and close cleanly within
  a deadline. Use Codex's managed authentication. Never call login/logout,
  resume/start a thread, consume a reset or send a message.
  Preserve rateLimitsByLimitId snapshot identities and labels. The legacy
  rateLimits snapshot may duplicate a map entry; deduplicate only when its
  bucket identity is established, not by duration, value or display order.
  The same hierarchy rule applies to private additional_rate_limits entries.
- Anthropic admin: documented messages usage and cost report GET endpoints,
  using ANTHROPIC_ADMIN_KEY. OpenAI admin: organization usage/completions and
  costs GET endpoints, using OPENAI_ADMIN_KEY. Follow pagination; distinguish
  input/cache categories, normalize currency units from documented schemas,
  and keep billing periods faithful to the API's bucket granularity. Partial
  or lagged cost data must not masquerade as complete current-turn spending.
- Experimental Claude: OAuth usage GET with explicit CLAUDE_OAUTH_ACCESS_TOKEN.
  Experimental Codex: subscription usage GET with explicit
  CODEX_USAGE_ACCESS_TOKEN and CODEX_USAGE_ACCOUNT_ID. Verify exact endpoint,
  headers and response schema from available vendor code or first-party
  evidence; keep the supported app-server source preferred. Never scrape
  browser cookies or copy tokens from credential stores. No refresh-token flow.

HTTP uses TLS verification, fixed provider endpoints, bounded response sizes,
timeouts and bounded pagination. Reject redirects carrying authorization to a
different host. Native/tracker refresh defaults to 60 seconds; direct API
refresh defaults to 300 seconds. Honor Retry-After and bound exponential
backoff; concurrent processes must not each refresh the same cache. Preserve
the source's as_of rather than changing stale data into a new reading. Mark
stale account output visibly; expired quota windows cannot look live.

Persist only whitelisted normalized fields. Validate finite, nonnegative values
and token subset relationships; malformed data becomes unavailable. Cache and
state directory mode 0700, files 0600, unique temporary files plus atomic replace
and a scoped lock. Never reuse another source/account's cache. Session-only
fallback when identity cannot be established is preferable to cross-account
reuse. No raw credential-bearing responses or raw payload debug dumps.

## Codex accounting

Target installed codex-cli 0.154.0 plus fixtures for legacy token_count rollouts.
Read session_meta, turn_context, response_item messages, task lifecycle events,
token_usage_record and quota snapshots. Parse JSONL incrementally/tolerantly;
unknown record types are harmless and an incomplete tail is ignored. Deduplicate
response IDs, including copied fork prefixes. Prefer per-request rows when
present, and only use non-overlapping legacy cumulative deltas as fallback.

Resolve children using explicit parent/root/session IDs and known parent-child
metadata. Read-only SQLite lookup is allowed for the versioned local index
when rollout metadata is insufficient; absence/schema changes must degrade
cleanly. Traverse descendants with a visited set. A child owns its context and
elapsed clock; only its actual new requests belong in parent usage sums. Never
assign a copied parent history as new child spend. Use root_turn_id where
available; unresolved turn attribution remains session/child usage rather than
guessing the newest turn. Report incomplete child coverage in diagnostics.

For repeated Stops, use per-session locked report state keyed by turn ID and
already-reported request IDs. Repeated unchanged Stop is a no-op; continued
usage or late child requests gets an incremental row exactly once. Explicit
--transcript and --all do not consume live reporting state. No inferred
compaction bill. Unsupported format or missing file yields a useful partial
status and a no-op cost hook rather than fabricated zeros.

## Execution sequence and acceptance

1. Save a working-tree baseline outside the checkout; run existing deterministic
   tests before edits. Record pre-existing failures. Do not regenerate goldens
   to hide failures, reset the worktree, commit, push, rename the repository or
   edit the user's installed agent settings.
2. Extract shared modules and the Claude adapter; rename launcher, migrate tests
   and environment variables and require --agent. Restore all baseline golden
   passes before relying on the refactor.
3. Add scoped cache/source orchestration, normalized source contract and all
   selected collectors. Test source selection, cache isolation and transport
   failure handling with local fixtures; live credentials are not required.
4. Add Codex adapter, rendering and child/exactly-once accounting. Keep Codex
   model/effort readable; do not shorten distinct GPT variants to one ambiguous
   glyph. Reuse the common formatting/width implementation.
5. Update documentation and CI for the package, configuration, source options,
   auth env variables, experimental limitations and real-terminal manual checks.
   Link this plan from development docs. Current remote links stay unchanged.
6. Verify status/cost goldens, usage-source, agents, subagent, rate and Python 3.9
   floor suites. Include all package modules in the floor check. Add meaningful
   offline tests for Codex per-request/cumulative duplicates, counter reset,
   mixed formats, fork history, nested/late children, interrupted/resumed turns,
   partial tails and repeated Stops; account/source isolation; partial windows;
   a general weekly-only bucket alongside a Spark 5-hour/weekly bucket; distinct
   same-duration bucket reset anchors; unknown model associations;
   invalid numeric data; admin pagination/currency; failed/slow collectors;
   private endpoint opt-in; bounded app-server process cleanup; and secrets not
   reaching disk/stdout/stderr. Run shell parse checks and shellcheck if present.

A complete delivery includes implementation, passing deterministic regression
and new tests, updated user docs and a truthful list of any real-terminal or
credential-dependent checks not performed. The tests must exercise public CLI
integration as well as source/parser functions; a registry of unimplemented
sources or a hidden legacy renderer is not completion.

## Reference points

- https://learn.chatgpt.com/docs/hooks (Stop input/output and transcript caveat)
- https://learn.chatgpt.com/docs/app-server (account and token interfaces)
- https://learn.chatgpt.com/docs/developer-commands?surface=cli (footer fields)
- https://developers.openai.com/api/docs/models/gpt-5.6-terra (worker choice)
- Installed schema bundle generated during planning:
  /private/tmp/codex-schema.R9DcYl (re-generate if absent; never depend on it at runtime).
