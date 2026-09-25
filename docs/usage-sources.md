# Usage sources

A **usage source** supplies account-level readings: how much of each plan or
quota window is used and when it resets — the 🔋 and 🪫 rows, and 💳 — or, for
organization sources, an account's token and dollar totals for a period.
Everything else on the readout — tokens, cost, context, time — comes from the
session's own transcript, whatever source you pick.

Most people need no configuration. Claude Code includes the plan windows in
the status-line payload, and Codex records them in its rollout. The default,
`auto`, reads those.

```sh
--usage-source auto                         # the default
--usage-source cmd:/path/to/your-reader     # your own program
CODING_AGENT_USAGE_LINE_USAGE_SOURCE=native # as an environment default; the flag wins
```

## Sources

| Source | Agent | Needs | Gives |
|---|---|---|---|
| `auto` | both | — | native data, then a local fallback (below) |
| `native` | both | — | only what the agent itself supplied; never runs anything |
| `none`, `off` | both | — | native data or an existing cached reading; never refreshes |
| `cmd:PATH` | both | your program | whatever it prints, in the [format below](#writing-a-custom-command) |
| `claude-usage-tracker` | Claude | the [Claude Usage Tracker](#claude-usage-tracker) app (macOS) | plan windows |
| `codex-app-server` | Codex | `codex` on `PATH`, signed in | quota buckets |
| `anthropic-admin` | Claude | `ANTHROPIC_ADMIN_KEY` | organization totals for the period |
| `openai-admin` | Codex | `OPENAI_ADMIN_KEY` | organization totals for the period |
| `experimental-claude-oauth` | Claude | `CLAUDE_OAUTH_ACCESS_TOKEN` | plan windows, from an undocumented endpoint |
| `experimental-codex-api` | Codex | `CODEX_USAGE_ACCESS_TOKEN` and `CODEX_USAGE_ACCOUNT_ID` | quota buckets, from an undocumented endpoint |

A source for the other agent is rejected with exit 2 — `--agent claude
--usage-source codex-app-server` is an error, not a silent fallback.

### What `auto` does

1. Use native data if this invocation has fresh native data.
2. Otherwise use a native reading cached by an earlier invocation in the last
   60 seconds.
3. Otherwise ask the local fallback: the Claude Usage Tracker for Claude, the
   Codex app-server for Codex.

`auto` never picks an admin or experimental source just because its
credential is set; you have to name those.

For Claude, only the status line receives plan windows from Claude Code. The
Stop hook and the agent panel get none, so they use the reading the status
line cached — which is why step 2 exists. Close to a render the status line
has always just drawn one; if it hasn't redrawn for more than a minute, `auto`
goes to the tracker, and without the tracker the plan cells are blank.

### An explicit source is final

Naming a source other than `auto`, `native`, `none` or `off` replaces native
data for account readings. If that source fails, the readings are unavailable
(or the last good reading is shown, marked stale); the program never falls
back to a different source. The session's own figures are unaffected.

`none`/`off` never run a collector, but still use native data and any
compatible cached reading, marked stale once it is more than five minutes old.

## Writing a custom command

`--usage-source cmd:PATH` runs your program and reads one JSON object from its
stdout. This is the way to plug in anything the built-in sources don't cover.

**How it is run.** `PATH` is run directly, with no shell, or through `bash` if
the file isn't executable. It inherits the environment, so only use programs
you trust. It must exit 0, print at most 1 MiB, and finish within five
seconds, or the reading is unavailable. It is run at most once a minute per
account scope; renders in between use the cached result.

**Input.** A small JSON object on stdin, which you are free to ignore:

```json
{"agent": "codex", "session": "…", "model": "gpt-5.6-terra",
 "account": "default", "period": "day",
 "period_start": 1790380800.0, "period_end": 1790419360.0}
```

`session` and `model` are present when known. `period_start` and
`period_end` are Unix seconds for the UTC period chosen by `--account-period`.
No conversation text, raw payloads or credentials are ever sent.

**Output.** Version 1 of the reading format:

```json
{
  "schema_version": 1,
  "as_of": "2026-09-26T08:00:00Z",
  "buckets": [
    {"id": "general", "label": "General", "windows": [
      {"id": "weekly", "duration_seconds": 604800, "used_percent": 97,
       "resets_at": "2026-10-01T17:17:00Z"}
    ]},
    {"id": "spark", "label": "Spark", "windows": [
      {"id": "five-hour", "duration_seconds": 18000, "used_percent": 100,
       "resets_at": "2026-09-26T20:15:00Z"},
      {"id": "weekly", "duration_seconds": 604800, "used_percent": 100,
       "resets_at": "2026-10-01T15:15:00Z"}
    ]}
  ]
}
```

With that reading, `--agent codex` prints:

```
quota
  🔋 General: weekly 7d 97% 🔜 Oct 01 17:17Z
  🔋 Spark: five-hour 5h 100% 🔜 Sep 26 20:15Z, weekly 7d 100% 🔜 Oct 01 15:15Z
```

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | Must be `1`. |
| `as_of` | no | When the reading was taken: Unix seconds or RFC 3339. Used to mark it stale. If omitted, the time of the fetch. |
| `buckets[].id` | yes | A stable identifier for the quota. |
| `buckets[].label` | no | Its heading on the readout. |
| `buckets[].model`, `buckets[].feature` | no | What the bucket applies to. Set these only when your source says so explicitly. |
| `windows[].id` | yes | The window's name within its bucket. |
| `windows[].duration_seconds` | no | The window's length: 18000 for five hours, 604800 for a week. |
| `windows[].used_percent` | no | Percent **used**, not remaining, 0–100. Missing means unknown, not zero. |
| `windows[].resets_at` | no | Unix seconds or RFC 3339. A window whose reset has passed is shown as expired. |
| `account` | no | Organization totals; see below. |

Buckets stay separate all the way to the readout. The General bucket above has
no five-hour window, and nothing will fill one in from Spark's, even though a
window of that length exists there: two meters with the same duration are not
the same meter. Don't give a bucket a `model` just because it is the model in
use.

The optional `account` object carries period totals: `period_start`,
`period_end`, `input_tokens`, `cached_input_tokens`, `output_tokens`,
`reasoning_output_tokens`, `cost_usd` and `scope`. Cached input is part of
input, and reasoning output part of output — they are subsets, not extra
tokens.

**Validation.** Unknown keys are dropped. A number that is negative,
non-finite or out of range, and a label containing control characters, are
treated as missing. A subset larger than its total (cached input above input)
discards the token counts. Nothing but the whitelisted fields is ever
written to disk.

**Older shapes** are still accepted: a top-level `windows` list in place of
`buckets`, read as one unlabelled bucket, and a flat object with
`session_pct`, `weekly_pct`, `session_resets_at` and `weekly_resets_at` and
no `schema_version`.

## Organization reports

`anthropic-admin` and `openai-admin` read your organization's usage and cost
reports with an admin key: tokens in and out, cached input and dollars, for
the UTC day, week (from Monday) or month to date chosen by `--account-period`.
They cover the whole organization, not your session or your subscription, so
they are printed on a separate labelled line and never added to session
totals or turned into plan-window percentages.

## Experimental subscription sources

`experimental-claude-oauth` and `experimental-codex-api` call the
undocumented endpoints the vendors' own apps use to show subscription usage.
They may break without notice, and are used only when named. The token must be
supplied in the environment. The program doesn't read credential stores or
browser cookies, and doesn't refresh tokens.

`experimental-claude-oauth` reads the five-hour and seven-day windows, plus
the Opus and Sonnet weekly sub-limits when present.

## Claude Usage Tracker

[Claude Usage Tracker](https://github.com/hamed-elfayome/Claude-Usage-Tracker)
is a macOS menu-bar app that polls Anthropic for your plan usage and keeps the
result in its preferences. Reading those needs no network call and no token.
It is `auto`'s fallback for Claude, and only matters when Claude Code hasn't
supplied the figures — in the Stop hook and the agent panel once the status
line's reading is more than a minute old.

The store is read with `defaults export` rather than by opening the `.plist`
file, because a running app's latest preferences may not have reached the file
yet. The account named by `activeProfileId` is read, falling back to the one
marked `isSelectedForDisplay`, then to the first. Only the usage figures are
taken: the five-hour, weekly and Opus-weekly percentages, their reset times,
and when the app last updated them. The same record holds an OAuth account and
a session key, and neither is read.

Set `CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST` to read an exported store
from a file instead, for example one copied from another machine.

## Codex app-server

`codex-app-server` starts `codex app-server --stdio`, sends `initialize` and
`account/rateLimits/read`, and closes it. It never starts a thread, sends a
prompt, signs in or out, or resets anything. It uses Codex's own sign-in. The
response's per-limit map is used as the source of bucket identities and
labels; see the
[app-server documentation](https://learn.chatgpt.com/docs/app-server).

## Refresh and storage

| Source | Refreshed at most every |
|---|---|
| native, `cmd:`, tracker, app-server | 60 seconds |
| admin and experimental sources | 300 seconds |

Between refreshes the cached reading is used. A failed refresh keeps the last
good reading and backs off exponentially, up to five minutes, and longer if
the server sent `Retry-After` (also capped at five minutes). A reading older
than its refresh interval is marked **stale** — freshness comes from the
source's `as_of`, not from when it was fetched.

Concurrent renders don't refresh the same cache twice: each refresh takes a
lock scoped to the agent, source, account and period.

Caches live under `$XDG_STATE_HOME/coding-agent-usage-line`
(`~/.local/state/coding-agent-usage-line` by default), or
`CODING_AGENT_USAGE_LINE_STATE_DIR`. The directory is mode 0700 and files
0600, written atomically. Each cache is keyed by agent, source, account and
the start of the `--account-period`, so readings never leak between them.
With `--account default`, the account scope is the credential in use (hashed)
for a source that has one, and otherwise the session — so two sessions never
share a reading that might belong to different accounts. Name the account
with `--account` to share a reading across sessions.

HTTP sources use fixed HTTPS endpoints, refuse redirects, cap response size
and pagination, and share one time budget per refresh.

## Diagnostics

`--diagnose` writes one line to stderr:

```
diagnose source=native reading=available stale=False as_of=1790375136.064312 retry_at=
```

`reading=unavailable` with a `retry_at` means the source failed and is backing
off. Codex adds `child_threads`, `child_coverage` and `ambiguous_legacy`; see
[Codex](codex.md#diagnostics). A `cmd:` source is reported as `cmd`, without
its path.
