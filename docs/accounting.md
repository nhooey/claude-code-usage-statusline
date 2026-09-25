# Accounting

Where the figures come from, and which numbers can be attributed to a turn,
session or child agent.

## Codex: request usage is not a quota share

Codex reports aggregate recorded request tokens, including newly billed child
and descendant requests. Response IDs deduplicate copied fork history. An
explicit root-turn link associates a child's requests with a parent turn;
missing links remain separately labeled child/session usage, not guessed
current-turn usage. Completed-child history identifies the child and preserves
its recorded model and reasoning effort.

Cached-input and reasoning-output tokens are subsets of their respective
totals, not extra tokens. Missing categories stay unavailable. Per-request
records take precedence over ambiguous same-turn legacy cumulative records;
`--diagnose` reports that ambiguity rather than inventing request identities.
Missing index/child files can also leave descendant coverage incomplete.

Stop reports distinguish fresh incremental usage from the complete recorded
session total. A session-wide locked journal claims request IDs once, retaining
origin turns for late child usage. Repeated unchanged Stops print `{}`;
`--all` and explicit transcript reports do not consume that journal.

Account quotas retain bucket IDs, headings, model/feature metadata and each
bucket's own windows. A general weekly-only reading does not gain a five-hour
meter from Spark. Separate reset anchors are not interchangeable.

Codex exposes [thread token usage and account quota readings separately](https://learn.chatgpt.com/docs/app-server),
without a documented conversion to per-child quota consumption. Reasoning
effort can affect consumption, but it is not a quota conversion formula. The
port does not apply Claude's calibration or API prices to Codex subscription
tokens. Organization API totals are separate account-period rows, never added
to a session's tokens or bill.

The following sections describe the retained **Claude-specific estimated
accounting**, including its calibration and historical fixes.

## What the two modes tell each other

They run in different processes under different launchers, so everything
crossing between them goes through a file, and the paths are overridable so a
test cannot write to the thing it is testing.

| channel | why |
|---|---|
| selected plan snapshot (shared source cache) | the shared source pipeline selects the reading once; the Claude projection and calibration use that same snapshot, without a second source refresh from a renderer |
| calibration scan | the cost of the configured local history inside each plan window, keyed by its window anchors. Scanning transcripts is too slow to redo per turn; dividing by a percentage is free, so the division is NOT cached |
| per-session context-window state | the Stop payload carries no model, and the transcript records both Opus variants as plain `claude-opus-5`, so the cost line cannot tell a 200k window from a 1M one. Guessing from the largest reading seen fails exactly where it matters — it is *compacting* that keeps a 1M session under the 200k line, so a well-kept session never proves its window and every 🧠 figure runs 5× high |

These channels now live in private, scoped application state, described under
[refresh and storage](usage-sources.md#refresh-and-storage), rather than global
`/tmp/claude-*` files. A stable state root lets status and Stop find the same
channel even when their launchers supply different `TMPDIR` values. Source and
account namespaces must not share calibration just because reset times match.

### One snapshot per render

Both readouts print two plan-limit cells, and each cell needs three things
from the same reading: the percentage after the `/`, the window boundary the
session share is summed over, and the dollars-per-point it is divided by.
Those used to be fetched by three functions that each read the source
independently, so one render could mix three provenances — and did.

Measured on 2026-08-25 at 22:30. The plan cache expired during a reading gap,
the fallback to the menu-bar app was unconditional, and the app's snapshot was
three hours old:

```
cost row     🔋 10.2٪ / 66٪    🪫 1.33٪ /  6٪
status row   🔋   38٪ / 38٪    🪫    10٪ / 10٪
```

(The status row's own left figure is a separate defect, below: it came from
the subtraction this release also removes.)

The `66٪` is the PREVIOUS 5-hour window, read just before it reset at 19:40.
The boundary came from that same expired snapshot, so five extra hours of
turns were charged to a window that had not opened when they ran — `10.2٪`
against a true `0.56٪`. The unit, meanwhile, came from a fresh reading another
session's hook had cached moments earlier.

Two rules now:

* **The source pipeline chooses once per render**, and everything downstream
  takes the prepared snapshot. Status cells, cost groups and panel rows do not
  independently refresh account data.
* **"Fresher" is measured, not assumed.** A reading keeps its own `as_of`,
  separate from the time it was fetched. An explicit source selection remains
  authoritative; a failed selection cannot silently switch to native or another
  collector. Stale readings and expired windows must not look current. The
  tracker polls on its own schedule and can be hours behind.

The calibration cache is the third way a unit could disagree with the figure
beside it, so it stores the **scan** rather than the ratio: the two window
costs, keyed by the boundaries they were measured over, and — since
2026-09-03 — the two plan readings they were measured *with*. The division
happens on every call, against that stored pair. The cache is then invalidated
by the only event that invalidates it — a reset, which moves a boundary.

Storing the reading beside the scan is what stops the unit being estimated
across two moments. It used to divide a cached numerator by a live
denominator, which is harmless while nothing moves between them and wrong by
any factor you like at a **reset**, where everything does: the scan is written
seconds into the new window holding seconds of spending, the reading climbs
while it sits there, and the unit comes out far too small. Every share divided
by it is then far too large. Observed on 2026-09-03: `🎤 18٪` under an account
total of `💳 1٪`, a part eighteen times the whole it belongs to. Measured at
one instant this cannot happen — a session's transcripts are *in* the scan, so
its cost is at most the scan's and its share at most the reading's.

Below `CALIB_MIN_PCT` no unit is derived at all and the shares print `?`.
`used_percentage` arrives quantised to whole percent, so a reading of 1 is a
band half a point wide either side — the unit is uncertain by a factor of
three, and so is anything divided by it. Two is where a figure stops being
wrong by more than itself. It costs the 🔋 shares for the first few minutes of
each 5-hour window; the weekly row sits above the floor for all but the first
hours of a week.

### The session's share of a window

Both readouts derive it the same way, through `session_shares`: sum this
session's own turn costs since the window opened, divide by dollars-per-point.

A turn is **split** at the boundary rather than tested against it, through
`turn_cost_since`. A turn is not an instant — it can run dozens of calls over
many minutes — and until 2026-09-03 it went whole to whichever window its
*prompt* was typed in, which after a reset is the window that has closed.
Measured on the turn that exposed it: prompt at 14:57:32, window open at
15:00:00, `$1.02` billed across 13 calls before the reset and `$3.85` across
43 calls after it. All `$4.87` went to the closed window, and the row reported
this session's share of the live one as `0٪` — under a 🎤 cell reporting the
same turn at `18٪`, because that cell had no window bound on it at all. The
machine-wide scan had always split per record; the per-session tally was the
only place a turn was still atomic.

Both figures now go through the split, so the ordering column 4 asserts merely
by existing — 🎤 ≤ 🎮 ≤ 💳, one window read at three scopes — holds by
construction rather than by no window happening to reset mid-answer.

The status line did not, until 2026-08-25. It subtracted the plan-wide reading
this session first saw from the plan-wide reading now, storing the baseline
per session id. A difference of two plan-wide readings contains every other
session's consumption over the interval, and the baseline only ever moved
**down** — rewritten whenever the reading fell, correctly reading a fall as a
window reset.

Which destroys the figure the first time a session outlives a window, and the
5-hour window resets every five hours. At the reset the reading goes to zero,
the baseline follows it to zero, and nothing raises it again, so `now - 0` is
the plan-wide total from then on. Both halves of the cell print the same
number, and the cell stops saying anything:

```
status row   🔋 🔜  23m   62٪ /  62٪      cost row   🔋 16.2٪ / 62٪
             🪫 🔜 6.5d    6٪ /   6٪                 🪫  1.57٪ /  6٪
```

The 4.4 weekly points between `6` and `1.57` were other sessions, charged to
this one. What the subtraction could see and the sum cannot is usage from
another machine — a phone, the web app — which made it a true ceiling. A
ceiling that sits at 100٪ of the window for the rest of the session is not
worth the column.

## A turn is not always something the user typed

Every figure on the `🎤` row, and every window the `🔋`/`🪫` shares are summed
over, rests on one question: which records OPEN a turn. A typed prompt is the
obvious answer and was for a long time the only one. It is not enough.

Four kinds of message are delivered to a session that is sitting idle, and the
session answers each of them exactly as it answers a prompt. Claude Code writes
all four the same way — `type: user`, `promptSource: "system"` — and across the
130 transcripts on this machine that field marks nothing else:

| what arrives | count | opens with |
| --- | --- | --- |
| `<task-notification>` — a background task finished | 253 | `<` |
| a message from another session | 92 | `Another Claude session sent a message:` |
| a cross-session idle notice | 6 | `[Cross-session idle notice]` |
| the usage limit resetting | 4 | `Your claude.ai usage limit has reset.` |

Refusing them was not a labelling error. `read_turns` drops assistant records
that arrive before the first recognised prompt — there is no turn to attribute
them to — and a wake message is very often the FIRST thing in a transcript,
because another session writes to a session its user has not typed into yet.
Measured in one such session: **74 of its 87 requests, 15.7M of cache-read and
112k of output**, reported by no row and counted in no total, with the `Stop`
hook printing `📊 (no prompts recorded yet)` 37 minutes in. That is the whole
of "the cost line doesn't print when the answer came from another session".

Where a typed prompt did come first, nothing was lost but everything was
misfiled: the wake turn's requests went onto the typed prompt's turn, so the
`🎤` row reprinted the previous prompt with the peer turn's figures added — the
same prompt twice, growing. And where the preceding turn was a `/compact`, the
row for the peer work disappeared a second way: `render_cost_line` excludes
compaction turns from the prompt it reports, so 22 requests went onto a turn
the `🎤` row is not allowed to name.

**What still keeps a record out**, and why the obvious tests do not work:

* the `<` prefix cannot be the test — `<task-notification>` opens with it and
  so does every tool result;
* `isMeta` cannot be the test — a peer message carries it and so does a system
  reminder;
* so `promptSource` is the test, and the two branches are checked separately.

A message that arrives while the assistant is WORKING is a different thing and
is still not a turn: it gets no `type: user` record at all, only a queue
`remove` whose content opens with `<`. Of the 355 wake records here, not one is
preceded by an assistant record or a tool result — every one sits at a turn
boundary. A batch delivered together opens one turn each, the earlier ones with
no requests under them, which is the queue-drain case the reporting rule
already steps past.

One quiet consequence: `read_transcript` measures answering time between turn
starts, so a session that sat idle for twenty minutes and was then woken had
those twenty minutes charged to the previous turn as work. It no longer does.

## Agents are counted, and what the 🎤 row cannot carry gets a row of its own

Nothing a subagent, a fork, or a workflow agent bills is in the session's own
transcript. Claude Code writes it to files beside the transcript —
`<sid>/subagents/agent-<id>.jsonl` for the Agent tool and forks (agents
spawned by agents sit in the same directory), and
`<sid>/subagents/workflows/wf_<id>/agent-<id>.jsonl` for a workflow's — and
until 2026-09-11 every reader here opened the one file and called it the
session. Across the 231 transcripts on this machine the main file carries
**zero** `isSidechain` records now; the agent files carry 9,743 billed
requests and $820 of the machine's $9,745 at list price. Eight percent
overall, most of it in the few sessions that use agents at all.

`agent_records` reads them, once per process, and three things take what it
reads:

* **`read_turns`** files each record under a turn. By the `promptId` on the
  agent's **user** records — the one that opened it, and any later one that
  resumed it with `SendMessage` — matched against the id on every user record
  of the main transcript, tool results included. That is the rule rather than
  the stamp because 14% of agent records here are stamped after the *next*
  turn opened; by stamp they would land on the next prompt's row and that row
  would lie by that much. The stamp is the fallback where no main record
  carries the id — a workflow prompts its agents under ids of its own, and
  transcripts before about 2.1.20x carry none — and it picks the last
  non-compaction turn open at that moment, so agent spend never prints on the
  🤏 row. Into the turn go the token sums, the dollar sums, `parts`, and
  `agent_calls`. **Not** `ctx`, which is a reading of *this* window and is
  watched to decide when this session needs a `/compact` — every agent runs a
  window of its own. **Not** the turn's end: agents run in parallel with the
  answer, and a background one finishing an hour later is not an hour of
  answering.
* **`read_transcript`** adds them to the status line's 🧩 and 🎯, and leaves
  🧠 alone for the same reason. Since 2026-09-25 it takes the **clock** off
  them too. The same walk fills a list of each agent's working spans —
  segmented exactly as the main thread's are, an agent's prompt to the last
  record its answer produced, so an agent resumed later by `SendMessage`
  opens a second span rather than one long one — and the busy clock is the
  length of the **union** of those spans with the main thread's. Union and
  never sum: five agents working the same ten minutes is ten minutes of the
  session's clock, and summing would put the busy figure past Σ and 👤 at a
  permanent zero the moment anything ran in parallel. What it fixes is a main thread that dispatches
  agents and waits, which writes nothing to its own file while they work: on
  the eight most recent sessions with agents here the figure roughly doubles,
  and on the most agent-heavy of them the busy figure went from 14% of the
  session's age to 97% of it — which is what the machine was actually doing.

  Since the same day the walk fills a second list, of each agent's **tool**
  spans, and ⌛'s 🔧 is the union of those with the main thread's. A tool's
  clock runs from the assistant record that asks for it to the `tool_result`
  that answers it, matched by `tool_use_id`; a Task's span therefore covers
  its agent's entire run, which is what lets the fold be recursive without a
  special case — the agent's own tools are already inside it, and unioning
  counts them once. A **background** agent is the case that needs the second
  list: its result comes back at once and it keeps working, so its tools run
  outside every span its parent recorded. ⌛'s 🤖 is then the busy clock
  with these seconds taken out, which is what makes 🔧 🤖 👤 a partition
  of Σ rather than three overlapping readings of it.
* **`_window_costs`** scans them for the 💳 unit. This one mattered most: the
  unit is machine spend over the plan reading, the reading is Anthropic's and
  includes every agent, and a numerator without them was short by the agent
  share of the window — so the unit was small and every share divided by it
  was high, by a factor that changed with which sessions had been running
  forks.

**Pricing is per record now, for every turn.** A `Turn` carries four dollar
sums accumulated at each record's own model, and `turn_cost` is their total.
It used to be the token sums at Opus rates, which could not say that a Sonnet
fork inside an Opus turn cost Sonnet money; and `turn_shares` divided Opus
cents by that total, which for a turn dominated by a Haiku fork would have put
📖 five times too high. A compaction's `preTokens` go into the cache-read sum
at the cache-read rate, which is what let `turn_cost` lose the "unless
compact" clause it needed before.

**The 👥 row.** A Stop prints one 🎤 row, for the last turn with main-thread
calls, and an agent record filed on any other turn would print on no row.
Two ways that happens. The turn was already reported — a background agent, a
fork left running, a workflow, each of which can finish after the turn that
spawned it printed. Or the turn shares its Stop with a later one: a queued
prompt delivered inside a run already in flight opens a turn this program
counts, but the one Stop reports the last of them. 43% of billed turns on
this machine are that, and in a session that runs workflows under a stream
of task notifications it is nearly all of them — 766 of 766 agent requests
in one such session were on turns no 🎤 row would ever name. Filing spend
there counts it in the totals and prints it nowhere, which is what happened
to compactions before they got a row of their own.

So a record that is **new** — not seen by any earlier Stop — and whose turn
is not the one the 🎤 row is about goes into a synthetic turn instead:
`agent` set, `calls` 0, so no selection of "the prompt to report" and no
settle wait can pick it. It prints on the 👥 row above the 🎤/🎮 pair at the
next Stop. The spawning turn does not also get it: the totals sum every turn,
and a record in two of them is billed twice.

"New" is the delicate part, and the compaction argument does not carry over:
there, the boundary and the Stop record are ordered in one file; here there
are two files and only clocks. So the boundary is **bytes**. The Stop hook,
after rendering, writes `$TMPDIR/claude-statusline-agents-<sid>.json` — how
far into each agent file the records it folded in reached. A record whose
line ends beyond that offset was not there; one at or below it was on some
earlier row. Append-only files make it exact and the clock does not enter.
Without the file — the first Stop of a session, or a golden fixture, which
renders one transcript at five widths in one `TMPDIR` and must not have the
first width change the second — the fallback is the last Stop record's
stamp, and that is **at most once**: an agent file flushes on its own
schedule, and a record stamped before the Stop but written after it looks
reported and prints nowhere. About 1% of late-eligible records here sit
inside that window. `tests/agents-once.py` replays real sessions against
both and, on this machine's 19 sessions with agents and Stops, finds every
agent request on exactly one of 🎤 or 👥.

What the row is **not**: a per-agent breakdown, or a live "N agents running"
mark. It is the agent spend the 🎤 row cannot carry, so that the two rows
above the 🎮 total account for everything under it.

## Compaction is reported exactly once

A compaction is the one costly thing in a session that nothing else accounts
for. It writes no usage record, so it is absent from this line's own totals and
from any tally built the same way. And it gets no `Stop` of its own — `/compact`
is a local command, so the first opportunity to report it is the next answered
prompt, one turn later, as its own row.

`Turn.reported` — the transcript's own record of where the last `Stop` ran — is
what buys "exactly once" without keeping state between invocations. The
prompt-pairing rule is only the fallback, for a transcript with no such record,
because it can print ZERO times: it assumes every `Stop` sees its own prompt,
and the transcript is not flushed in step with the hook.

That last fact is worth stating on its own, because it looks like a bug in the
reader: **a turn's assistant records can still be missing from the `.jsonl` when
the `Stop` hook reads it** — observed 1.2 s after their own timestamps. Hence
`read_turns_settled`, which polls for up to 1.5 s.
