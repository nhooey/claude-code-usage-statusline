# Accounting

Where the figures come from, what the two modes tell each other, and the
rules that keep a share of a window honest.

## What the two modes tell each other

They run in different processes under different launchers, so everything
crossing between them goes through a file, and the paths are overridable so a
test cannot write to the thing it is testing.

| channel | why |
|---|---|
| `PLAN_CACHE` (`/tmp/claude-plan-limits.json`) | the status line publishes the plan figures it took from Claude Code's payload, so the cost rows quote the SAME ones. Two sources exist — the payload's `rate_limits` and whatever [usage source](usage-sources.md) is configured — and `load_limits` is all-or-nothing between them |
| `CALIB_CACHE` (`/tmp/claude-calib-cache.json`) | the cost of everything on this machine inside each plan window, keyed by the windows it was measured over. Scanning transcripts is too slow to redo per turn; dividing by a percentage is free, so the division is NOT cached |
| `$TMPDIR/claude-statusline-ctxwin-<session id>` | the Stop payload carries no model, and the transcript records both Opus variants as plain `claude-opus-5`, so the cost line cannot tell a 200k window from a 1M one. Guessing from the largest reading seen fails exactly where it matters — it is *compacting* that keeps a 1M session under the 200k line, so a well-kept session never proves its window and every 🧠 figure runs 5× high |

`/tmp` rather than `TMPDIR` for the first two, deliberately: the status line has
been observed writing its caches to `/tmp` while the Stop hook's `TMPDIR`
pointed inside `/var/folders`. A path that resolves differently per process
cannot be a channel between them.

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

* **`limits_snapshot()` chooses once per process**, and everything downstream
  takes what it chose. A render is one process, so there is nothing to keep in
  sync.
* **"Fresher" is measured, not assumed.** Each source says when its reading was
  taken — a usage source in its own `as_of` field, which the program used to
  throw away, and the plan cache in one written beside the figures — and
  `_reading_age` compares them. An expired cache is not evidence that the
  other source is newer; the tracker app polls on its own schedule and can be
  hours behind.

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

