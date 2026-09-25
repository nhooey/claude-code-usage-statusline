# Codex

For Codex, `coding-agent-usage-line.py --agent codex` prints what each turn
used when it finishes, a one-shot status, and a history report for any
saved rollout — tokens in and out, the model and effort, context occupancy,
and your quota buckets.

It has less to show than the Claude readout, because Codex gives an external
program less to work with:

- **No live footer.** Codex has no status-line command hook. Use Codex's own
  `/statusline` to configure its footer.
- **No agent panel.** Codex has no equivalent of Claude Code's
  `subagentStatusLine`; `--mode subagent` exits 2. Child agents appear in the
  Stop report and in `--mode cost --all`.
- **No dollars.** Subscription usage isn't billed per token, so tokens are
  never priced as if they were API calls.
- **No per-agent quota share.** Codex reports quota for the account, not for
  each child agent, so no share is estimated. (The Claude readout's shares
  come from a calibration against Claude's own figures, which doesn't carry
  over to Codex.)

## Install the Stop hook

Add a Stop hook to `~/.codex/hooks.json`, or to a project's
`.codex/hooks.json`:

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ {
          "type": "command",
          "command": "~/src/claude-code-usage-statusline/coding-agent-usage-line.py --agent codex --mode cost",
          "timeout": 30
      } ] }
    ]
  }
}
```

Codex asks you to review new or changed hooks before they run: open `/hooks`
in Codex, check the command, and trust it (for a project hook, trust the
project too). See Codex's [hook guide](https://learn.chatgpt.com/docs/hooks).
This program never edits your Codex configuration.

## What the Stop hook prints

After each turn, Codex shows the hook's `systemMessage` as a message in the
conversation — it doesn't replace the footer:

```
🎤 Codex turn turn-1 incremental 🤖gpt-5.6-terra/high | 🧩 in 40k out 2.1k
🎮 Codex session total | 🧩 in 40k out 2.1k
quota
  🔋 default: primary 5h 31% 🔜 Sep 26 00:39Z, secondary 7d 89% 🔜 Sep 29 22:22Z
```

- 🎤 is what this turn used that hasn't been reported before, including its
  child agents.
- 🎮 is the whole session so far.
- 👥 rows appear when usage arrives late — a child agent that finished after
  its turn was reported. Each late request is reported once, under the turn it
  belongs to.
- The quota lines list each bucket with its windows. See
  [Quota buckets](#quota-buckets).

A second Stop with nothing new prints `{}`, which Codex treats as no message.
The hook reports nothing if the payload has no `turn_id`, or if the rollout is
missing — it never guesses which session is newest.

## Status and history from a saved rollout

Point `--transcript` at a rollout file:

```sh
./coding-agent-usage-line.py --agent codex --transcript /path/to/rollout.jsonl
```
```
Codex 🤖gpt-5.6-terra/high | 🧩 in 40k out 2.1k | context 22500/272000
quota
  🔋 default: primary 5h 31% 🔜 Sep 26 00:39Z, secondary 7d 89% 🔜 Sep 29 22:22Z
```

`context` is the latest request's occupancy of the root thread's context
window.

For a report of every turn, add `--mode cost --all`. `--usage-source none`
leaves out the quota lookup:

```sh
./coding-agent-usage-line.py --agent codex --mode cost --all --usage-source none \
    --transcript /path/to/rollout.jsonl
```
```
Σ turn turn-1 🤖gpt-5.6-terra/high total 🧩 in 40k out 2.1k
  root started 2026-09-25 22:21:20Z | completed 2026-09-25 22:22:31Z | elapsed 1.2m | user Summarise the failing tests | assistant Two failures, both in the cache tests.
```

Each turn's total includes its child agents. A completed child also gets a
👥 row of its own, with its thread, model, lifecycle and tokens.

Reading a rollout with `--transcript` or `--all` never marks anything as
reported, so it can't change what the live hook prints next.

## Quota buckets

Codex can report several quotas at once, each with its own windows — a
general quota and a separate one for a particular model or feature, say. Each
bucket is shown as its own group, with only the windows it actually has:

```
quota
  🔋 General: weekly 7d 97% 🔜 Oct 01 17:17Z
  🔋 Spark: five-hour 5h 100% 🔜 Sep 26 20:15Z, weekly 7d 100% 🔜 Oct 01 15:15Z
```

Here the general quota has only a weekly window. It is not given Spark's
five-hour window, even though a window of that length exists, and Spark's
figures are not attributed to the model in use. Buckets are never merged
because their durations or reset times match, and a bucket is labelled with
a model or feature only when the source says so.

The readings come from the rollout's own quota snapshots under `auto`. When
the latest snapshot is more than a minute old, `auto` asks
`codex app-server` instead (at most once a minute). A window whose reset has
passed is marked `expired`, and a reading past its refresh interval is marked
`stale`. For other sources, including your own program, see
[Usage sources](usage-sources.md).

## How usage is counted

- **Per request.** Recent rollouts record each response's usage. Those are
  summed once per response ID, so a response copied into a forked thread's
  history isn't counted again. Codex's running turn and thread totals are
  cumulative and are never added up.
- **Older rollouts** record only cumulative counters. Their usage is the
  difference between consecutive counters, which survives a counter reset.
  When a turn has both kinds of record, only the per-request records count,
  and `--diagnose` reports the overlap as `ambiguous_legacy`.
- **Subsets aren't extra.** Cached input is part of input, and reasoning
  output part of output.
- **Missing isn't zero.** If any request lacks a count, the total for that
  category is shown as `?` rather than a partial sum.
- **Child agents** are found through Codex's local thread index,
  `$CODEX_HOME/state_5.sqlite` (default `~/.codex`), opened read-only, and
  their rollouts read in turn. A child's usage counts toward the root turn
  it records as its origin; a child that records none is reported as
  unattributed rather than assigned to the newest turn. If the index is
  missing or has a different schema, child usage may be incomplete and
  `--diagnose` says so.
- **Stop races the rollout.** Codex can run the Stop hook before the turn's
  last record is written. The hook uses the `turn_id` it is given rather than
  waiting for an end-of-turn record, and briefly retries an unfinished last
  line. Anything that lands later is reported by a later Stop.
- **Reported once.** Which requests have been reported is kept per session in
  the private state directory — request IDs only, never text.

## Diagnostics

`--diagnose` adds child coverage to the usual source line:

```
diagnose source=cmd reading=unavailable stale=False as_of= retry_at= child_threads=0 child_coverage=indexed ambiguous_legacy=1
```

| Field | Meaning |
|---|---|
| `child_threads` | Child rollouts read. |
| `child_coverage` | `indexed`: the thread index was read. `incomplete-no-index`, `incomplete-schema`, `incomplete-missing-rollout`: some child usage may be missing, and why. |
| `ambiguous_legacy` | Legacy counter records skipped because per-request records cover the same turn. |

## Migrating

Hooks that ran `claude-code-usage-statusline.py` need the new program name and
`--agent`; see
[Migrating](options.md#migrating-from-claude-code-usage-statuslinepy).
