# Accounting

Where every figure on the readouts comes from: what is read straight from
Claude Code, what this program computes, and what it has to estimate. The
Claude sections come first; [Codex](#codex) is at the end.

## Where each figure comes from

| Figure | Readout | Source | Counts agents? |
|---|---|---|---|
| 🧩 ▴ ▾ tokens | status, cost | The transcript and every agent file beside it, deduplicated per request. ▴ is weighted input, ▾ is output. See [tokens](#tokens). | yes |
| 🎯 cache rate | status, cost | Cache reads over all input tokens, from the same requests. | yes |
| 🛫 token rate | status | The slope of 🧩's total over samples the status line keeps between renders. | yes |
| 🛫 token rate | panel | The slope of the token samples Claude Code hands the panel, at its 5-second tick. | the agent's own |
| 🧠 context | status | The last main-thread request's whole input over the window size in the payload. | no |
| 🧠 context | cost | How much the context grew or shrank during the turn; the totals row prints the current level. | no |
| 💰 cost | status | Claude Code's own `cost.total_cost_usd` from the payload. Not computed here. | as Claude Code reports it |
| 💰 cost | cost, panel | List price of every request at its own model's rates. See [dollars](#dollars). | yes |
| 📖 📝 cost shares | status, cost | Share of a turn's or session's cost spent re-reading cache (📖) or writing it (📝). | yes |
| 🔋 🪫 🎤 🎮 window shares | status, cost, panel | Estimated: cost spent inside the window, divided by a calibrated dollars-per-percent. See [plan-window shares](#plan-window-shares). | yes |
| 💳 account % | status, cost | The usage source's plan reading. See [usage sources](usage-sources.md). | — |
| 🔜 reset | status | The usage source's reset time for that window. | — |
| ⌛ 🔧 🤖 👤 Σ | status | Timestamps in the transcript and agent files. See [time](#time). | yes |
| ⌛🤖 | cost | The turn's wall-clock answering time, tool calls included. The totals row sums the turns. | no |
| 🔧 🤖 | panel | The agent's time inside tools (its descendants' included), and the rest of its run. | yes, descendants |
| 💾 diff | status | Claude Code's `cost.total_lines_added` / `total_lines_removed`. | as Claude Code reports it |
| 💾 diff | panel | Lines in the agent's own Edit patches and new-file Writes. | the agent's own |

"Counts agents" means subagents, forks, workflow agents, and agents those
agents spawned. 🧠 never counts them because every agent has its own context
window, and 🧠 is there to tell you when *this* one needs a `/compact`.

## Tokens

A request is counted once. Claude Code writes one transcript line per content
block (thinking, text, each tool call) and repeats the request's whole
`usage` object on every one, and a retried request appears again under the
same id. Records are deduplicated on `requestId` (falling back to
`message.id`), first occurrence wins, within the main transcript and across
all of the agent files.

Requests whose usage is all zero are skipped. That is how Claude Code records
an interrupted request and an API error placeholder (`model: "<synthetic>"`),
and neither was billed. An all-zero record also never replaces the last 🧠
reading, which would otherwise blank the cell.

▴ is not the raw input count. Raw input in a long session is almost all cache
reads, so ▴ weights each input class by its price relative to a fresh token:

| Input class | Weight |
|---|---|
| fresh input | 1 |
| cache write (`cache_creation_input_tokens`) | 2 (the 1-hour cache TTL) |
| cache read (`cache_read_input_tokens`) | 0.1 |

▾ is output tokens, unweighted. 🎯 is `cache_read / (fresh + cache_write +
cache_read)`, recomputed over all requests for a total rather than averaged
over turns.

## Dollars

The cost line, the agent panel and the window shares price every request at
**its own model's** list price, so a Sonnet fork inside an Opus turn costs
Sonnet money. Prices per million tokens, from the model catalog built into
Claude Code (`MODEL_PRICE`):

| Model id contains | Input | Output | Cache read | Cache write |
|---|---|---|---|---|
| `opus` | 5 | 25 | 0.50 | 10 |
| `fable-5-1` | 10 | 50 | 0.25 | 20 |
| `fable` | 10 | 50 | 1.00 | 20 |
| `sonnet-5` | 2 | 10 | 0.20 | 4 |
| `sonnet` | 3 | 15 | 0.30 | 6 |
| `haiku` | 1 | 5 | 0.10 | 2 |

The first matching row wins, so specific rows sit above their family. An
unrecognised model is priced as Opus, deliberately the high side.

These are API list prices. On a subscription they are a measure of how much
work was done, not what you paid; the plan-window shares are what map them
onto a subscription.

A compaction issues no usage record. Its cost is estimated from the boundary
record Claude Code writes instead: `preTokens` at the Opus cache-read rate,
plus a summary of `len(summary) / 4` tokens at the Opus output rate.

## Turns

The cost line reports one turn, and the status line's 🎤 figures describe the
same turn. A turn opens on any of these:

* **A typed prompt**: a `type: user` record from `userType: external`, whose
  content is a string that does not start with `<`, is not `isMeta`, and has
  `promptSource` of `typed` or none.
* **A message delivered to an idle session**: `type: user` with
  `promptSource: "system"`. Claude Code writes four kinds this way — a
  `<task-notification>` from a finished background task, a message from
  another session, a cross-session idle notice, and a usage-limit reset. The
  session answers each as it would a prompt and bills the answer the same
  way.
* **A prompt typed while the assistant was busy**: it goes through a queue
  and has no `type: user` record. The turn opens on the `queue-operation`
  record that delivered it (`remove`, `dequeue` or `popAll`), stamped when the
  model received it rather than when it was typed. Queue entries starting with
  `<` are machinery and open nothing.

The summary `/compact` injects (`isCompactSummary`), tool results and system
reminders never open a turn. A prompt recorded both as queued and as typed
opens one turn, not two. Requests that appear before the first turn opener
have no turn and are dropped.

A turn ends at the last record the answer produced: an assistant or system
record, or a tool result. Records the user causes later — the next enqueue, a
slash command's caveat — do not extend it, so time spent reading and typing is
not charged as answering time.

**Which turn is reported** is the last one that made main-thread requests and
is not a compaction or the [👥 turn](#the--row). The cost line's 🎤 row and
the status line's 🎤 figures use the same rule, so they always describe the
same prompt.

**Waiting for the transcript.** Claude Code does not flush the transcript in
step with the Stop hook; a turn's last requests can be missing when the hook
reads the file. If the turn being reported has no requests yet, the hook
re-reads the transcript whenever it grows, for up to 1.5 s, before reporting.

## Agents

Nothing an agent bills is in the session's own transcript. Claude Code writes
it to files beside it:

```
<project>/<session-id>.jsonl                                   the session
<project>/<session-id>/subagents/agent-<id>.jsonl              Agent tool, forks, and agents they spawn
<project>/<session-id>/subagents/agent-<id>.meta.json          sidecar: agentType, parentAgentId, spawnDepth, …
<project>/<session-id>/subagents/workflows/wf_<id>/agent-<id>.jsonl   a workflow's agents
```

A nested agent sits in the same directory as its parent and differs from a
sibling only by `parentAgentId` (and `spawnDepth`) in its sidecar.

**Filing agent spend under a turn.** Each agent request is filed under the
turn whose `promptId` appears on the agent's most recent user record — the
prompt that spawned it, or a later one that resumed it with `SendMessage`.
That id is matched against every user record of the main transcript, tool
results included. Filing by timestamp instead would put a background agent's
spend on whichever prompt happened to be open when it finished. Where no main
record carries the id (workflow agents, which run under ids of their own, and
old transcripts) the request goes to the last non-compaction turn open at its
timestamp.

An agent's requests add to the turn's tokens, dollars and call count. They do
not change the turn's 🧠 reading or its end time, because agents have their
own windows and run in parallel with the answer.

**Agent-panel rows** read one agent's own transcript: its tokens, cost,
context, cache rate and diff are its own and do not include its children. The
exception is 🔧, which follows `parentAgentId` down the tree and includes
every descendant's tool time (unioned, so a child waited on inside its
parent's Task call counts once). The row's 🤖 is the agent's run time minus
that 🔧.

### The 👥 row

A Stop prints one 🎤 row, for the turn described above. Agent spend filed on
any other turn would be counted in the totals and printed on no row. That
happens in two ways:

* The turn was already reported, and the agent finished afterwards (a
  background agent, a fork left running, a workflow).
* The turn never gets its own Stop: a prompt queued during a run opens a turn,
  but the run's single Stop reports only the last of them.

Such a request, if no earlier Stop has seen it, goes into a separate
**agents** turn instead of its own, and prints on the 👥 row above the 🎤 row
at the next Stop. It is not also added to the turn that spawned it, which would
bill it twice.

"Not seen by an earlier Stop" is measured in bytes. After rendering, the Stop
hook records how far into each agent file the requests it reported reached,
in a per-session file in private state (`claude-agent-offsets-<digest>.json`).
A request whose line ends past that offset is new. Agent files are
append-only, so this is exact. For the first Stop of a session, with no offsets
file yet, the fallback is the timestamp of the last `stop_hook_summary`
record; that can miss a request stamped before the Stop but written after it,
so it errs towards reporting a request at most once.

```
📊 👥 Usage: Agents (other)  🧩 ▴7.2k ▾900   🎯 99٪                  💰+  0.1   🔋+ 0.01٪ 📖 56٪  🪫+ 0.01٪ 📝  5٪

📊 🎤 Usage: Prompt (last)   🧩 ▴ 28k ▾7.1k  🎯 95٪  🧠+ 3.4٪ +6.8k  💰+  0.2   🔋+ 0.03٪ 📖 32٪  🪫+ 0.05٪ 📝 18٪  ⌛🤖+  5m  📅 2026-08-16
📊 🎮 Usage: Session (total) 🧩 ▴ 68k ▾ 14k  🎯 97٪  🧠 27.1٪   54k  💰   0.6   🔋  0.1٪  💳 41٪  🪫  0.14٪ 💳 63٪  ⌛🤖  10m  🕐   02:23:20
```

The 👥 row is not a per-agent breakdown (that is the agent panel). It is the
agent spend the 🎤 row cannot carry, so the rows above 🎮 add up to it.

## Time

The status line's ⌛ row splits the session's age, Σ, into three parts that
do not overlap and add up to Σ:

| Mark | Meaning | How it is measured |
|---|---|---|
| 🔧 | inside a tool | Every tool call's span, from the assistant record that asks for it to the `tool_result` with the matching `tool_use_id`. |
| 🤖 | waiting on the model | Busy time minus 🔧. |
| 👤 | waiting on you | Σ minus busy time, plus the time spent in questions put to you. |
| Σ | session age | Now minus the first timestamped record. |

**Busy time** is the union of every turn's span (opener to last answer record)
on the main thread and in every agent file. Spans are unioned, never summed:
five agents working the same ten minutes are ten minutes of the session. An
agent resumed later by `SendMessage` contributes two spans, not one long one.
Folding agent spans in matters because a main thread that dispatches agents
and waits writes nothing to its own file while they work.

**Tool spans** are unioned the same way. An agent's own tool calls already fall
inside its parent's Task span; a background agent's do not, because its Task
call returns at once, so its tools are counted from its own file.

**Questions put to you** are tool calls whose result is your answer:
`AskUserQuestion` and `ExitPlanMode` (`BLOCKING_TOOLS`, matched by name).
Their spans move from 🔧 and 🤖 to 👤. The subtraction is
`union(all tool spans) − union(blocking spans)`, which is exact because the
blocking spans are a subset. Permission prompts are not moved: nothing in the
transcript marks one, and a tool that waited for approval did hold up the turn.

The cost line's ⌛🤖 is simpler: the turn's span from opener to last answer
record, tool calls included, and on the totals row the sum of the turns' spans.
It does not include agent time or subtract tool time, so it does not equal the
status line's 🤖.

## Plan-window shares

Claude's subscription meters report only whole-account percentages. Every 🎤,
🎮 and agent-row share of the 5-hour (🔋) and weekly (🪫) windows is derived:

```
dollars per percent  =  list-price cost of every request on this machine in the window
                        ÷  the window's current account percentage
share                =  cost this turn / session / agent spent in the window
                        ÷  dollars per percent
```

**The window.** Each window's start is its reset time minus its length (5
hours or 7 days). Both come from the [usage source's](usage-sources.md)
reading.

**The machine's cost** is a scan of every transcript under
`~/.claude/projects/` (override with `CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR`)
and every agent file beside them, deduplicated on request id and priced per
model. Agent files are included because the account percentage includes agent
use. Files last modified more than a day before the weekly window opened are
skipped, which bounds the scan by window length rather than history.

**Caching.** The scan takes about a second, too slow for every redraw. Its two
costs are cached together with the two percentages read at the same moment,
keyed by the source, account, period and window boundaries, for 300 seconds.
The division is redone on each render against the cached pair. Dividing a
cached cost by a live percentage is wrong right after a reset, when the cost
is seconds old and the percentage is climbing, and can make a turn's share
larger than the account's.

**Too small to divide by.** Percentages arrive as whole numbers, so a reading
of 1% means anywhere from 0.5% to 1.5%. Below 2% (`CALIB_MIN_PCT`) no rate is
derived and the shares print `?`. This affects the first minutes of each
5-hour window and the first hours of each week.

**Splitting at the boundary.** A turn can straddle a reset. Its cost is summed
per request by timestamp, so only the part billed after the window opened
counts. A request whose timestamp does not parse is counted in. A compaction
has no per-request parts and counts in or out by its own timestamp.

Because the turn, the session and the scan use the same boundary, the same
prices and the same reading, a limit row reads 🎤 ≤ 🎮 ≤ 💳.

**Caveats.**

* It assumes plan consumption is proportional to list-price cost. Anthropic
  does not publish the real weighting.
* The scan sees only this machine. Use from a phone, the web app or another
  computer raises the account percentage without adding to the scanned cost,
  so the rate comes out low and every share comes out **high**.

The share is not computed as "account percentage now minus account percentage
when the session started". That difference includes every other session's use
over the same period, and becomes the whole account total once the window
resets under a running session.

## One reading per render

Each render takes one plan reading from the selected usage source, and
everything that needs it — the 💳 percentages, the window boundaries, and the
calibration's percentages — uses that same reading (`seed_limits_snapshot`).
Mixing readings taken at different times can put a boundary from an expired
window beside a percentage from the current one. An explicitly selected source
that fails leaves the cells blank rather than falling back to another source.
See [usage sources](usage-sources.md) for how the reading is chosen and how
old it may be.

## State shared between the readouts

The status line, the Stop hook and the agent panel run as separate processes,
so what one learns for another is written to files in the program's private
state directory (see [refresh and storage](usage-sources.md#refresh-and-storage)).
Session-scoped files are named by a SHA-256 digest of the session id.

| File | Written by | Read by | Why |
|---|---|---|---|
| context window | status line | Stop hook | The status payload carries `context_window.context_window_size`; the Stop payload does not, and the transcript names both Opus windows `claude-opus-5`. Without it the Stop hook guesses 1M if any turn exceeded 200k, else 200k. |
| rate history | status line | status line | 🛫 needs a history the payload does not give it: up to 16 samples of 🧩's total, at least 5 seconds apart. |
| agent offsets | Stop hook | Stop hook | Which agent requests have been reported; see [the 👥 row](#the--row). |
| calibration | any | any | The window scan and the readings it was taken with; see [caching](#plan-window-shares). |
| source cache | any | any | The last usage-source reading; see [usage sources](usage-sources.md). |

## Compactions

A compaction writes no usage record and gets no Stop of its own (`/compact`
is a local command, and an automatic compaction happens inside another turn).
It is read from the `compact_boundary` record instead: `preTokens` (the
context that was summarised), `durationMs`, and whether it was manual or
automatic. It becomes a turn of its own, or fills the `/compact` prompt's turn
when that prompt made no requests.

Each compaction is reported exactly once, on a 🤏 row at the next Stop. Claude
Code writes a `stop_hook_summary` record each time the Stop hook runs, and
any compaction after the last such record has not been reported yet. A
transcript with no such records falls back to reporting the compactions
between the previous prompt and the current one.

```
📊 🤏 Usage: Compact (last)  🧩 ▴ 29k ▾  4k  🎯 99٪                  💰+  0.2   🔋+ 0.05٪ 📖 59٪  🪫+ 0.06٪ 📝  0٪  ⌛🤖+ 41s

📊 🎤 Usage: Prompt (last)   🧩 ▴ 12k ▾800   🎯 98٪  🧠-19.5٪ -195k  💰+  0.1   🔋+ 0.01٪ 📖 61٪  🪫+ 0.02٪ 📝 14٪  ⌛🤖+  1m  📅 2026-08-16
📊 🎮 Usage: Session (total) 🧩 ▴ 76k ▾  6k  🎯 99٪  🧠  9.7٪   97k  💰   0.5   🔋  0.1٪  💳 41٪  🪫  0.13٪ 💳 63٪  ⌛🤖 3.7m  🕐   02:23:20
```

The prompt after a compaction reports the drop in context across it (`🧠-19.5٪
-195k` above): the context change is measured from the last turn that had a
reading, skipping the compaction turn, which has none.

## Codex

Codex's accounting shares no estimates with Claude's. It reports what Codex
records and leaves the rest blank.

**Requests.** Tokens are summed from Codex's per-response `token_usage`
records, deduplicated on response id, so history copied into a forked child is
not counted again. Cached input and reasoning output are subsets of input and
output, not extra tokens. Where a rollout has only older cumulative records
for a turn, per-response records take precedence; `--diagnose` reports the
ambiguity instead of inventing request ids. Missing categories stay
unavailable rather than zero.

**Children.** Child threads are found through the spawn edges in Codex's
`state_5.sqlite` index (under `$CODEX_HOME`, default `~/.codex`), or through
indexed subagent rollouts that name their parent thread. A child's requests
belong to a parent turn only through an explicit `root_turn_id`; without one
they are reported as separate child usage, never guessed onto the current
turn. `--diagnose` reports incomplete coverage, such as a missing index or
rollout file.

**Stop reports.** A Stop prints the requests it has not printed before. A
locked, session-scoped journal in private state records reported request ids
and turns, so a child that finishes after its root turn was reported appears
at the next Stop under that root. A Stop with nothing new prints `{}`.
`--all` (plain history) and an explicit `--transcript` report without
consuming the journal.

**No dollars, no per-child quota.** Codex reports thread token usage and
account quota separately, with no documented conversion between them, so
subscription tokens are not priced and children get no share of a quota
window. Claude's calibration is not applied. Organization API totals are
separate account-period rows, never added to a session.

**Quota buckets** keep their own ids, labels, model or feature metadata and
windows. A weekly-only bucket stays weekly-only even when another bucket (such
as Spark's) has a 5-hour window, and reset times are never shared between
buckets.
