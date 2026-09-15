# Implementation checkpoint

Updated 2026-09-14. **Implementation and deterministic verification are complete.**

## Final handoff (supersedes every historical section below)

After implementation, the user explicitly authorized global Codex wiring.
Added `/Users/nhooey/.codex/hooks.json` (0600) with a Stop handler invoking
the checkout launcher through `/usr/bin/python3`, with
`--agent codex --mode cost --usage-source auto`. The existing `config.toml` and footer/model/effort settings
are unchanged. The exact installed command passed an isolated synthetic Stop
smoke (child totals, quota reading and repeated-Stop no-op). Hook trust remains
for the user to review in `/hooks`; no trust record or bypass was installed.
Hot reload in the currently running TUI was not verified; reopening/resuming
the same conversation is the fallback if the new hook is not listed.

The renamed thin launcher and agent-agnostic package are implemented. Claude
status/cost/panel output retains the golden bytes; Codex supplies one-shot
status, grouped history, completed-child reports and origin-aware incremental
Stop output. Agent and usage-source selection are independent. All planned
collectors are implemented and exercised offline, including optional tracker,
managed app-server, admin APIs and explicit experimental subscription APIs.

Quota hierarchy remains intact: a general weekly-only bucket does not inherit
Spark's five-hour window. Codex child request tokens are reportable, but Codex
does not expose documented per-child quota shares or Claude's custom live panel
hook. Claude's existing quota-share calibration is not applied to Codex.

Application state is private and scope-keyed; the legacy global Claude caches,
old app environment names and raw payload debug taps are removed. Native
readings retain identity and can supply a later Stop through normalized cache;
local Claude reset formatting preserves the original epoch outside UTC too.

Root's final independent checks passed:

- Status goldens 135; cost goldens 77; agents 34; subagent 43; rate 38.
- Migrated usage-source suite 39; public CLI acceptance 14.
- Shared formatting, pure panel rendering, normalized source contracts,
  source cache, HTTP, app-server, Claude bridge and Codex suites.
- Actual `/usr/bin/python3` Python 3.9 floor 37, plus Codex and source-cache
  suites under that interpreter.
- Shell syntax and `git diff --check`.

Golden diffs still match the pre-port baseline exactly:
`1b361aebc9704c2ff750a22b1eadcd8531c80d080eadacc3ce5f5048c13da2a0`.
No goldens were regenerated. No commits, pushes, repository/remote rename,
authenticated provider tests, unbounded real-history
replays or real-terminal DSR checks were performed. Local shellcheck was not
available; its existing CI job remains configured.

Application implementation was performed by Terra medium/high workers; root
handled planning, API research, review, independent tests, documentation and CI.
All workers are complete and edit-idle. No implementation blocker remains.
Use README for installation/migration, usage-sources for the collector schema,
and development for the physical module map. Keep launcher and package together;
the checkout and remote retain `claude-code-usage-statusline` for now.

## Historical resume progress (not current status)

- `/root/complete_port` (Terra high) physically extracted shared formatting,
  Claude records, and prepared status/cost/panel rendering. The thin launcher
  lazily selects the Claude adapter; all modes use the shared source pipeline.
  It removed legacy source/cache paths and raw debug dumps and is finishing
  fixture migration and regressions for the new private scoped state. It owns
  Claude modules and legacy tests; coordinate shared cli.py edits.
- `/root/implement_port` (Terra medium) completed source-cache correctness and
  transport work: failed-empty-cache backoff, credential-before-session cache
  identity, stale/current/native cache precedence, grouped map-key identities,
  HTTP-date Retry-After, streaming command/HTTP bounds, and private-source
  failure propagation. Its final fixes scope/cache native/none/off snapshots
  for subsequent Stops without downgrading newer cache entries, and project
  Claude reset epochs to local wall time. Focused tests pass independently.
  It is idle.
- `/root/codex_reports` (fresh Terra high) owns Codex/models/state/render and
  Codex CLI integration. Atomic session-wide claims now preserve origin turns;
  current rows are fresh-only, late-only updates omit unchanged current rows,
  and session totals stay separate. Missing categories, grouped child reports,
  quota duration/expiry rendering, UTF-8 tail handling and cached descendant
  metadata scans are covered. History includes child thread IDs and redacted
  --diagnose without account refresh. Codex/source suites pass independently.
  It is idle.
- Root owns independent `tests/port-cli.py`, documentation and CI. Public CLI
  tests verify grouped history, held-open stdin, historical effort, source
  precedence, concurrent exactly-once late children, and continued-turn fresh
  usage, all Claude mode/source contracts, redacted diagnostics and native
  cache reuse/account isolation. All 12 prior cases plus the new 13th native
  integration regression have independently passed.
- Root updated README (including corrected nested Codex hook shape), options,
  usage-source/development/accounting docs and test/CI lists. Env names now
  use the product prefix: STATE_DIR, USAGE_SOURCE, NOW, CLAUDE_PROJECTS_DIR,
  CLAUDE_CALIB_CACHE and CLAUDE_TRACKER_PLIST. Final full regressions/checkpoint
  still await the worker's stable fixture migration handoff.
- No goldens regenerated; last root hash comparison still matches the exact
  pre-port baseline hash recorded below. No commits/settings/repo rename or
  live authenticated provider tests.

The remainder is the **pre-compaction snapshot**, useful for original acceptance
and fixture reference, not a current statement that workers are stopped.

## User request and execution choices

The user asked for a revised plan, then implementation of an AI-agent-agnostic
usage readout with a Codex port and independent command-line usage-source
selection. Accepted product name: `coding-agent-usage-line`; executable:
`coding-agent-usage-line.py`. Keep the repository, checkout directory and clone
URLs named `claude-code-usage-statusline` for now. No compatibility executable.

The user requested implementation using an appropriate lower model/effort in
a cleared context. Application edits were delegated to fresh-context workers:

- `/root/implement_port`: GPT-5.6 Terra, medium effort. Finished and stopped.
- `/root/complete_port`: GPT-5.6 Terra, high effort. Replaced the medium worker
  after independent review found integration defects. Finished its current
  slice and stopped before beginning the next formatting extraction.

Root did planning, first-party API research, review, independent verification,
plan/checkpoint documents and temporary review fixtures, not the application
implementation. Both workers are stopped; no edit was in progress at pause.

Read [the complete approved plan](agent-agnostic-plan.md) before resuming. It is
the acceptance contract, not a claim that all listed work has been completed.

## Latest user correction: quota bucket hierarchy

Do not parse all 5-hour/weekly rows as belonging to the selected Codex model.
User observations from separate sessions:

- Sol: general 5-hour 31% resetting 20:15; general weekly 89% resetting
  September 21 15:15.
- Astra: general weekly 97% resetting September 21 17:17, with no general
  5-hour meter displayed. Subsequent 5-hour 100% and weekly 100% rows appeared
  under the explicit Spark heading and belong to Spark, not Astra.

Preserve bucket IDs, headings, explicitly supplied model/feature metadata, and
nested windows throughout source parsing, cache, diagnostics and rendering.
Missing windows remain absent. Never borrow another bucket's same-duration
meter, infer association from the active model, or merge buckets on matching
duration/reset/value. Canonical command schema v1 now uses `buckets`; earlier
flat v1 `windows` becomes one unassociated default bucket. The old flat
session_pct/weekly_pct command adapter remains part of the plan.

## Files and baseline safety

Workspace: `/Users/nhooey/git/github/nhooey/claude-code-usage-statusline`.
It was very dirty before this task. Preserve ALL pre-existing changes.

- Original main file and pre-port diff are saved outside the checkout at
  `/private/tmp/coding-agent-usage-line-baseline`.
- New launcher is executable. Original launcher has been removed in the
  working tree as agreed; the backup and git history remain available.
- `coding_agent_usage_line/` contains `cli.py`, `sources.py`, `state.py`,
  `models.py`, `codex.py`, `render.py`, `claude.py`, and `claude_render.py`.
- `claude.py` is still about 7,800 lines: nearly the whole original monolith.
  `claude_render.py` is only a small preparatory pure-cell extraction.
- Docs and CI have been partially updated. Audit their implementation claims;
  do not treat documentation or named helpers as evidence that a feature works.
- No commits, pushes, repository/directory rename, installed agent setting
  changes, or live credential/API tests were performed.
- Do not regenerate goldens. Their current diff is byte-identical to the
  golden sections of the pre-port baseline diff (verified again at pause):
  SHA256 `1b361aebc9704c2ff750a22b1eadcd8531c80d080eadacc3ce5f5048c13da2a0`.

## Implemented work, with limits

The new code includes agent selection and a renamed launcher; Codex request
parsing, descendant lookup, token/context summaries and a basic Stop report;
normalized account source records with grouped quotas; command, admin, private
subscription and managed app-server collectors; and scoped private cache/report
state. Several review fixes are in place, including bucket normalization
idempotency, redirect rejection, currency units, pagination failures, thread vs
session identity, copied-request dedupe and an atomic current-turn Stop claim.

These are real code changes, but they are NOT full plan completion. In
particular, do not describe the unchanged Claude monolith plus new Codex code
as a completed agent-agnostic architecture.

## Checks completed

Root's final checkpoint checks all passed AFTER workers stopped:

```sh
PYTHONPYCACHEPREFIX=/private/tmp/calu-checkpoint-pycache /usr/bin/python3 -m compileall -q coding_agent_usage_line coding-agent-usage-line.py tests
python3 tests/sources-v1.py
python3 tests/http-sources.py
python3 tests/app-server.py
python3 tests/codex.py
git diff --check
for f in tests/*.sh; do bash -n "$f" || exit 1; done
```

The worker also reported its last full deterministic run passing: status
goldens 135, cost goldens 77, original usage-source 41, agents 34, subagent 43,
rate 38, and Python 3.9 floor 24. Re-run these after further refactoring.

Root independently verified the public Codex CLI on a separate generated tree:
400 input / 75 output tokens, model `gpt-5.6-terra`, effort medium, root-only
context 230/1000, and native quota rows. Eight concurrent Stops produced exactly
one report; another unchanged Stop returned `{}`. These checks cover only the
tested cases, not every feature in the plan.

No real-terminal DSR/glyph checks, authenticated provider checks, or expensive
full-history replay suites were run. Do not claim them as verified.

## Next bounded implementation milestone

The high-effort worker was explicitly assigned, but DID NOT START, this slice:

1. Physically extract shared display/measurement/formatting/terminal geometry
   into `formatting.py` (or an equivalently clear module), used by BOTH agents.
   Relevant original banners precede Records, approximately lines 68–2610.
   Separate vendor pricing/cache configuration appropriately.
2. Preserve existing function bodies/comments and measured glyph tables with
   a mechanical section/AST move, then update references. Bulk mechanical
   rewrites are permitted; use apply_patch for normal semantic edits/helper
   creation. Do not hand-copy a giant source block unnecessarily.
3. Handle the finite mutable display knobs through qualified module references
   or explicit configuration, not broad globals syncing or a giant string-keyed
   function dictionary. `set_mark_spacing` changes MARK_SP, RIGHT_GRID,
   LINE3_RESERVED, PWD_MAX_FALLBACK, C_TOK, C_CACHE, C_LIM_TOT and C_SESS;
   `set_subscript_decimals` changes SUB_DEC.
4. Remove moved definitions from `claude.py`, migrate tests to owning modules
   where necessary, and actually reuse shared formatting in Codex rendering.
5. Run status/cost goldens, rate/subagent and focused formatting tests after
   the last edit. This physical extraction is not optional.

Then physically separate Claude records/parser/accounting and pure rendering.
Move renderer I/O into orchestration with prepared snapshots:
render_status currently publishes context/rate state; render_cost_line obtains
calibration/plan totals; render_agent_row reads agent files/metadata/usage;
render_subagent loads limits. Shared renderers must not scan vendor files or
call sources. The launcher should become genuinely thin, not globals-reexport
the legacy adapter.

## Other required work / independent review findings

Collect these into subsequent coherent slices instead of interrupting the
physical extraction with one small fix at a time:

- **Claude source integration is not established.** The last reviewed CLI
  still forwards Claude calls to its original main rather than preparing the
  new shared source snapshot. Verify/fix all selected sources for BOTH agents,
  explicit source precedence, status/cost/subagent contracts and separate
  account-period rows. Migrate app-owned env vars and global `/tmp/claude-*`
  caches; remove raw credential-bearing payload debug taps. Native/tracker must
  remain usable without Claude Usage.app. Do not keep legacy runtime behavior
  solely to make old tests pass.
- **Late child usage is currently lost.** Root reproduced this after reporting
  turn-one and turn-two, then adding a new child request attributed by
  root_turn_id to turn-one: another Stop for turn-two returned `{}` instead of
  a one-time late-child row. Track already-reported requests by origin turn
  across the session, preserving correct attribution and atomic claiming.
- **Reports are still minimal.** `--all` currently emits individual request
  rows, not grouped root-turn totals and separate completed-child summaries.
  Completion/lifecycle, timestamps/user-assistant text/elapsed fields and
  incomplete-child-coverage diagnostics require an acceptance audit. Current
  Stop output lacks a separate session-total scope. Do not claim full Codex
  feature parity merely because a token sum matches.
- Root's turn-one Stop used the latest session effort (medium), although its
  own root request/context was high effort. Use the selected turn's root model
  and effort when attributing a historical/late report; session metadata is a
  distinct scope.
- **Source freshness/refresh behavior needs completion.** Latest code still
  needs a careful audit for Retry-After/backoff, overall collector deadlines,
  bounded command output while reading (not only after communicate()), and
  separate last-attempt/fetch TTL from source as_of. A collector that returns
  old as_of must not be invoked every render just because its data is stale.
  Newly read stale/expired native/external readings need the same freshness
  treatment as cache hits. Native observation timestamps must survive.
- Default cache isolation needs tests for account switches within one session,
  not just different session strings. Prefer explicit provider identity/
  credential fingerprint appropriately; never read unrelated credential stores.
- Model `TokenUsage` no longer fabricates total from cached subsets, but audit
  aggregates where some requests lack a category: summing only known values
  must not silently claim a complete total. Test legacy counter resets, mixed
  formats, forks, resumed turns and missing metadata beyond the small smoke
  suite. Keep missing/zero/measured/estimated distinct.
- Validate malformed timestamps (finite but out-of-range epochs), empty quota
  envelopes, numeric subset validity, and rendering failure isolation. Unknown
  labels must not execute terminal control sequences.
- Root found a native bucket-dedupe key missing bucket identity, legacy
  window_minutes lost, observation timestamps lost and diagnostics counting
  obsolete flat windows. Worker reports these fixed; final tests should cover
  both same-anchor/different-bucket and the user's weekly-only/Spark example.
- Improve human quota window labels using reported duration without assuming
  primary=5h or secondary=weekly. Do not label rolling quotas as though the
  admin `--account-period day` option defined their measurement period.
- Finish accurate CLI help, docs, schema examples, installation/migration and
  CI coverage after implementation. Codex supports native Stop warnings and
  one-shot reports; its live `/statusline` is built-in fields, not an external
  command footer. Hooks require user trust review via `/hooks`; never bypass
  trust or change installed settings on the user's behalf.

## Review fixtures and reference material

- `/private/tmp/calu-review.9bWs8A`: independent root/child/grandchild JSONLs
  and state_5.sqlite. Use it as CODEX_HOME with a separate state directory.
  Expected parent total 400/75; root turn-one including child 140/30; root
  turn-two including grandchild 260/45; root context 230/1000. Root current turn
  deliberately has no task_complete record because Stop can precede it.
- `/private/tmp/calu-late-review.KF0NRF`: same tree plus a late child request
  `request-child-late` (input5/output2) attributed to turn-one. Its `state/`
  contains prior claims for both root turns. Repeating a turn-two Stop currently
  reproduces the missing late-row bug. Expected new session total 405/77.
- `/private/tmp/coding-agent-usage-line-handoff.md`: earlier detailed handoff
  and first-party API/schema evidence. Its status descriptions are older than
  this checkpoint; use it for reference, not current completion status.
- `/private/tmp/codex-schema.R9DcYl`: generated installed Codex 0.154.0 schemas.
  Re-generate if unavailable; runtime code must not depend on this scratch path.

Important first-party observations: session_meta.id is a THREAD ID distinct
from session_meta.session_id. Per-request records have thread_id, session_id,
turn_id, root_turn_id, response_id and usage plus cumulative totals (do not
sum cumulative fields). Actual child metadata is
source.subagent.thread_spawn.parent_thread_id. SQLite spawn_edges can be empty;
indexed source metadata fallback and unknown-coverage diagnostics matter.

Resume only after the user's next explicit instruction. Keep implementation on
the lower-model worker; root should review evidence and run independent checks.
