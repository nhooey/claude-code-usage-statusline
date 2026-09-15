# Usage sources

The public command is `coding-agent-usage-line.py --agent claude|codex`.
`--usage-source` independently selects account intake: `auto`, `native`,
`none`/`off`, `claude-usage-tracker`, `codex-app-server`, `anthropic-admin`,
`openai-admin`, the explicitly opt-in experimental subscription sources, or
`cmd:PATH`. Admin readings are organization-period rows, never personal quota
or turn costs. `--account` and `--account-period day|week|month` scope cached
readings; cache identity includes agent, source, account and period.

The normalized v1 command contract is `schema_version`, `as_of`, `buckets`
and optional `account`. A bucket has stable `id`, `label`, optional explicit
`model` or `feature`, and `windows`; every window has `id`,
`duration_seconds`, `used_percent`, and optional `resets_at`. Buckets are
preserved through cache and rendering: a weekly-only General bucket is not
filled from a separate Spark bucket with a 5-hour meter. The earlier flat
`windows` v1 shape and legacy `session_pct`/`weekly_pct` commands remain
accepted as one unassociated default bucket.

`auto` reads current native data first, then a fresh native cache, then only
the local tracker (Claude) or managed app-server (Codex). It never chooses
admin or experimental endpoints merely because credentials exist. `off` does
not refresh, but can show a compatible cached reading marked stale. Source
caches are atomic, mode-private, and scoped by provider/account namespace and
UTC calendar period; unknown managed identities fall back to the real session
rather than another account's reading.

Admin sources use `ANTHROPIC_ADMIN_KEY` or `OPENAI_ADMIN_KEY` and render as
labeled organization-period totals, never as session cost or subscription
quota. Experimental subscription sources require explicit
`CLAUDE_OAUTH_ACCESS_TOKEN`, or both `CODEX_USAGE_ACCESS_TOKEN` and
`CODEX_USAGE_ACCOUNT_ID`; they are versioned fixture contracts, not stable
vendor API promises. `--diagnose` emits only source/freshness capability
information, never raw responses or credentials.

## Choosing a source

| source | agent | authentication/input |
|---|---|---|
| `native` | both | the active payload/rollout and compatible native cache; no external refresh |
| `cmd:PATH` | both | your program, run as one path without shell-string evaluation |
| `claude-usage-tracker` | Claude | optional local tracker preference store |
| `codex-app-server` | Codex | Codex's managed authentication; `codex` must be on PATH |
| `anthropic-admin` | Claude | `ANTHROPIC_ADMIN_KEY` |
| `openai-admin` | Codex | `OPENAI_ADMIN_KEY` |
| `experimental-claude-oauth` | Claude | explicit `CLAUDE_OAUTH_ACCESS_TOKEN` |
| `experimental-codex-api` | Codex | explicit `CODEX_USAGE_ACCESS_TOKEN` and `CODEX_USAGE_ACCOUNT_ID` |

An explicit external choice controls account intake even when native data is
available. Failure leaves that source unavailable or stale; it does not switch
providers. The account period affects organization reports, not the durations
of rolling quota windows. Organization input/output/cost totals stay separate
from transcript turn/session totals.

Codex app-server collection performs only initialization and
`account/rateLimits/read`, then closes the process. It does not start a thread,
send a prompt, log in/out or reset quota. The
[official app-server contract](https://learn.chatgpt.com/docs/app-server)
defines the multi-bucket map separately from its legacy single-bucket view.

## Custom-command contract

`--usage-source cmd:/absolute/path/to/reader` runs the executable directly, or
uses `bash` for a non-executable script. It sends a small JSON context on stdin:
agent, session, model, account, period, period_start and period_end. Conversation
text, raw native payloads and credentials are not included. The command inherits
the invoking environment, so only run readers you trust. It must exit 0 and
print one JSON object, with at most 1 MiB of output within five seconds.

Example reading (illustrative, not a live account):

```json
{
  "schema_version": 1,
  "as_of": "2026-09-14T12:00:00Z",
  "buckets": [
    {"id": "general", "label": "General", "windows": [
      {"id": "weekly", "duration_seconds": 604800, "used_percent": 97,
       "resets_at": "2026-09-21T17:17:00Z"}
    ]},
    {"id": "spark", "label": "Spark", "windows": [
      {"id": "five-hour", "duration_seconds": 18000, "used_percent": 100,
       "resets_at": "2026-09-14T20:15:00Z"},
      {"id": "weekly", "duration_seconds": 604800, "used_percent": 100,
       "resets_at": "2026-09-21T15:15:00Z"}
    ]}
  ]
}
```

Percentages are **used**, not remaining. Missing windows and model associations
stay missing. Supply `model` or `feature` on a bucket only when your source
explicitly identifies it; do not assign every bucket to the selected model.
The general bucket above has no five-hour meter. Matching durations or reset
anchors never license merging it with Spark.

Optional `account` fields are `period_start`, `period_end`, `input_tokens`,
`cached_input_tokens`, `output_tokens`, `reasoning_output_tokens`, `cost_usd`
and `scope`. Cached input and reasoning output are subsets, not extra tokens.
Boundary timestamps accept Unix seconds or RFC3339 and normalize to UTC.
Invalid/nonfinite numbers and terminal-control labels are unavailable; unknown
keys are dropped before persistence. Legacy flat commands may still return
`session_pct`, `weekly_pct`, `session_resets_at` and `weekly_resets_at`.

## Refresh and storage

Local/native/command refreshes default to 60 seconds; direct API sources use
300 seconds. Fetch time is separate from source `as_of`, so an old reading is
visibly stale without causing a collector invocation on every render. Failed
refreshes back off, including bounded HTTP Retry-After delays. Expired quota
windows are historical, not current availability.

State lives under `$XDG_STATE_HOME/coding-agent-usage-line`, defaulting to
`~/.local/state/coding-agent-usage-line`. Use
`CODING_AGENT_USAGE_LINE_STATE_DIR` to override it. Directories are 0700 and files
0600, with scoped locks and atomic replacement. Only normalized whitelisted
fields and report IDs are stored, not raw API replies or transcript text.

`CODING_AGENT_USAGE_LINE_USAGE_SOURCE` sets the source default; a CLI option wins.
Claude history defaults to `~/.claude/projects`; override it with
`CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR`. Claude calibration and per-session
context/rate/report state also use the private state root, with hashed scope
identities rather than global temporary filenames. Tests can supply a prepared
calibration at `CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE` and freeze the Claude
display clock with `CODING_AGENT_USAGE_LINE_NOW`. The old application-owned
`CLAUDE_*` environment variables are no longer supported; vendor credential
names are unchanged.

Use a distinct non-secret `--account NAME` for managed accounts whose identity
is otherwise unavailable. Do not put access tokens in `--account`, source paths
or command-line arguments. Experimental sources do not read credential stores,
scrape browser cookies or refresh tokens. Fixed HTTPS endpoints reject redirects;
admin pagination and all collector processes have bounded budgets.

## Optional Claude tracker

[**Claude Usage Tracker**](https://github.com/hamed-elfayome/Claude-Usage-Tracker),
a macOS menu-bar app, is one optional source. It polls Anthropic on its own
schedule and keeps the answer in its UserDefaults store, which is the whole
appeal: no OAuth handling here, no network call, no token to keep. The figures
are already on disk and somebody else's program is responsible for them.

It is read through `defaults export` rather than by opening the `.plist`,
because a running app's preferences live in `cfprefsd` and may reach the file
later. `CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST` overrides that with a
path to an exported store, which is how the tests drive it on a machine with
no app, and how a store copied off another machine can be read.

`activeProfileId` names the account record to read; `isSelectedForDisplay` is
the fallback and the first record is the fallback's fallback. Six fields are
taken from the `claudeUsage` object inside it and nothing else is touched.

## What this replaced, and how it failed

Until 2026-09-08 this channel was a shell script **outside this repository**:
`~/.claude/usage-limits.sh`, wrapping `~/.claude/usage-now.sh`, wrapping
`defaults export`, wrapping a `python3` of its own. Three processes and two
files that were never installed with the program and were named nowhere in
this documentation, so a clone of this repository could not read a plan
figure at all and nothing on the readout said why.

It also broke without saying so. The app moved its snapshot history out of
UserDefaults into a file — the store still carries the
`usageHistoryMigratedToFiles_v1` marker of it — and the `usageHistory_<uuid>`
key both scripts keyed off stopped existing. The wrapper caught the failure,
printed `{}`, exited 0, and the fallback answered "no reading" for days. The
limit rows have a legitimate blank state, so what a reader saw was a plausible
readout.

That is the failure mode of a three-layer shell-out: every layer swallows, and
the last layer is not in the repository whose tests would have caught it. The
reading is now taken in-process, the schema it expects is a fixture in
`tests/usage-source.py`, and CI runs it.

One thing was lost with the scripts and is not coming back. The old store did
not publish the 5-hour reset at all — on a `sessionReset` snapshot,
`triggeringResetTime` was a copy of the snapshot's own timestamp — so the
wrapper derived the window from the most recent 0٪ → non-zero transition in
the snapshot history. The current schema publishes that reset directly and
correctly (measured 2026-09-08: 77 minutes ahead of the reading carrying it),
so the derivation is documented in `tracker_reading()` rather than ported.
Reviving it means reading the history file the app now keeps under
`~/Library/Application Support/Claude Usage/history/`; it does not mean
remembering what it did.
