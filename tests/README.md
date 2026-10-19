# Tests for `coding-agent-usage-line.py`

How to run the suites, and what CI runs, is in [docs/tests.md](../docs/tests.md).
This file is for someone changing or adding a test: how the goldens work, what
the pinned environment holds still, what each case is for, and which recorded
behaviours are deliberate.

- [Golden files](#golden-files)
- [The pinned environment](#the-pinned-environment)
- [The generated corpora](#the-generated-corpora)
- [Figures](#figures)
- [Status cases](#status-cases)
- [Cost cases](#cost-cases)
- [Agent panel cases](#agent-panel-cases)
- [Assertion suites](#assertion-suites)
- [Manual checks](#manual-checks)
- [Behaviours that look like bugs](#behaviours-that-look-like-bugs)

## Golden files

`run-cases.py` renders each case in `fixtures/cases.json` and compares stdout,
byte for byte, with a file under `golden/status/` or `golden/cost/`.
`golden.sh` and `golden-cost.sh` run one suite each through it. A golden's name is
`CASE@WIDTH.txt`, where `WIDTH` is the `--cols` it was rendered at and `none`
means `--cols 0`, the program's "terminal width unknown" path. The cost suite
compares the hook's `systemMessage`, not the JSON envelope around it, so a diff
is readable.

The files keep their ANSI escapes. To look at one as the terminal would:

```sh
cat tests/golden/status/01-baseline@196.txt                        # in colour
sed -E 's/\x1b\[[0-9;]*[A-Za-z]//g' tests/golden/status/01-baseline@196.txt
```

A layout change is supposed to show up as a golden diff. Re-record with
`--regen`, read `git diff tests/golden/` line by line, and commit the goldens
with the change. `--regen` rewrites the case's [figures](#figures) as well,
and a layout change leaves them alone. There is no second implementation to agree with: a golden is
a claim about what the program prints, and the reviewed diff is what keeps it
honest.

To add a case, add the payload or transcript to its generator
(`fixtures/gen/status.py` or `fixtures/gen/cost.py`), or the case and any new
environment to `fixtures/gen/cases.py`. Then run
`python3 tests/fixtures/gen/all.py`, then `--regen`, and read both diffs.

## The pinned environment

Each case names an environment in `fixtures/env/`, and `run-cases.py` turns
it into what the program reads. It holds still everything the readout reads
that is not the payload; a golden is only as reproducible as this list.

| Pinned | Without it |
|---|---|
| `CODING_AGENT_USAGE_LINE_NOW=1786847000` (2026-08-16 02:23:20 UTC) | every duration and both clock cells move |
| `TZ=UTC`, `LC_ALL=en_US.UTF-8` | 🕐 and 📅 shift by the local offset |
| `TMPDIR` and `CODING_AGENT_USAGE_LINE_STATE_DIR` in a fresh scratch directory | context, rate samples and source caches written by one case leak into the next, or into your real state |
| `CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE`, planted as `{"sess": 5.50, "week": 4.10}` | the window shares depend on your own history |
| `CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST`, a fixture Claude Usage Tracker store | `auto` could read the tracker app installed on this machine |
| an environment's `source`, served as a `cmd:` usage source with a fixed `as_of`, one command per environment | the plan percentages come from whatever source the host has |
| `TERMINAL_EMULATOR=JetBrains-JediTerm`, `TMUX` and `TERM_PROGRAM` unset | the width profile depends on the terminal that ran the suite |
| a clean fixture repo (branch `golden-clean`) and a dirty one (`golden-dirty`) as the working directory | 🌿, 💾 and the project name record your checkout |

The pinned instant is 6.7 minutes before `01-baseline`'s 5-hour reset and 1.9
days before its weekly one, so both 🔜 countdowns draw real figures, and it is
after every generated record, so every elapsed figure is positive.

The cases of one suite share one state directory, in the order
`cases.json` lists them: a payload with `rate_limits` writes the cache that a
later payload without them reads. Anything else that runs the cases has to
keep that order.

`run-cases.py` runs the program with `/usr/bin/python3`, not the first
`python3` on `PATH`; `--python` picks another.

## The generated corpora

`fixtures/gen/all.py` writes everything under `fixtures/` but `gen/`, and the
output is committed, so a second implementation can read the same inputs.
Only the generators change it: a hand edit is lost on the next run. Payload
paths are `${HOME}` and `${FIXTURES}` placeholders that `run-cases.py` fills
in, and the readout prints the home as `~`, so neither the fixtures nor the
goldens carry a username.

```
fixtures/
  cases.json             every case, in order: id, suite, input, cols, env, flags
  env/<name>.json        clock, zone, locale, terminal, usage source,
                         calibration, tracker store, which repo
  payloads/status/       status-line payloads
  transcripts/status/    the transcripts and agent files they point at
  transcripts/cost/      the Stop hook's transcripts
  payloads/subagent/     the agent panel's payloads, and under
  transcripts/subagent/  the sessions and agent files they point at
  figures/<suite>/       each case's figures, written by run-cases.py; see
                         Figures below
  panel/<group>.json     the agent panel's rows from the renderer's inputs;
                         see Agent panel cases below
  grid/<profiles>.json   the redesigned grid's layouts and rows, written by
                         the TypeScript; see Grid cases below
  rows/<profiles>.json   the band's and the receipt's rows from the figures,
                         written by the TypeScript; see Row cases below
  gen/                   the generators
```

The main status transcript is built to reach branches a recorded session only
reaches by accident:

- a **sidechain** request, which is billed but must not set the context
  reading;
- an **interrupted** request, whose all-zero usage must not overwrite the last
  real reading;
- a repeated `requestId`, which must be counted once;
- a question put to the user (`AskUserQuestion`) inside a turn, whose span
  counts under 🚦 rather than 🔧;
- timestamps chosen so the ⌛ row's 🔧 🤖 🚦 partition reads `58m 3h 6h` over
  a 9.3-hour session.

## Figures

The program runs each readout in two stages, and `run-cases.py` checks each
on its own as well as the two together:

1. **Figures.** The inputs read -- payload, transcript and agent files, usage
   source, calibration cache, repository, the clock -- and every figure the
   rows draw worked out from them: `status_figures` in `claude.py` for the
   status line, and `cost_figures`, after the transcript read in
   `main_cost`, for the cost line. Everything that reads a file or a cache,
   runs a command, reads the clock or writes session state happens here.
2. **Render.** `render_status_figures` and `render_cost_figures` draw a
   figures document at a width, under the flags and the terminal profile,
   and read nothing else. The live path goes through the document too, so a
   figure the rows need and the document lacks fails every golden.

Between them is a figures document, one per case, committed as
`fixtures/figures/<suite>/<id>.json`. A normal run compares the document
each case writes with the committed one, byte for byte, then draws the
committed one alone and compares that with the golden. `--regen` rewrites
the documents with the goldens; `--regen-figures` rewrites only the
documents, for a change to their shape that must not move a row. To draw
one by hand, its placeholders filled in first:

```sh
coding-agent-usage-line.py --agent claude --mode status --cols 120 \
    --from-figures FILE [render flags]
```

The documents are written for a second implementation to produce and
compare, so the text is canonical:

- **Keys sorted**, two-space indent, UTF-8 unescaped, a newline at the end.
- **Numbers exact**: the shortest decimal that reads back as the same double,
  positional (`0.00001`, never `1e-05`), and a whole number as an integer
  (`300`, not `300.0`). That is JavaScript's `Number#toString` for every
  figure here. Nothing is rounded, so a port has to sum in the same order.
- **Missing is null**, never 0 or "": a string field with no value, the
  transcript's `cache_pct` of -1 and its epochs of 0 are written null.
- **Times are epochs**; `clock.tz` is the zone the clock cells are drawn in.
- **Paths are placeholders**: `${HOME}`, `${FIXTURES}`, and `${SCRATCH}` for
  the suite's scratch directory (the fixture repos, the `cmd:` sources).
- **No width and no flags.** A case drawn at five widths has five identical
  documents, except where the cases' shared state makes them differ: the
  first cost case to run a `cmd:` source records what the command printed,
  and the later ones read it back from the source cache, which keeps less.

`schema` is 3 and `mode` is `status` or `cost`. Schema 2 (2026-10-19) added
the figures the redesigned grid draws and today's rows do not: the status
document's `turn` and `accounting`, the accounting's time and 💾 figures, the
`Turn`'s lines and the `Transcript`'s main-thread figures. Schema 3, the same
day, added what the decisions in the plan's
[Where each row's figures come from](../agents/plans/redesign.md#where-each-rows-figures-come-from)
need: the status document's `open_turn` and `accounting.open_turn`,
`accounting.own`, the session's `start_s`, the `Transcript`'s `own_parts` and
`own_est` with the compactions in its own cost, and the `Turn`'s `eta`. No row
moved either time. Both modes carry:

| Key | Holds |
|---|---|
| `clock` | `now`, the epoch every duration and clock cell is drawn from, and `tz` |
| `context_window` | the window the 🧠 percentages divide by, in tokens |
| `usage.reading` | the version-1 reading the usage source gave ([docs/usage-sources.md](../docs/usage-sources.md)), or null |
| `usage.plan` | the plan figures the accounting divided by: `session_pct`, `weekly_pct`, `session_resets_at`, `weekly_resets_at` |
| `usage.account_text` | the account summary row, when one is drawn |

A status document adds the records `render_status` takes, field for field
as `claude_records.py` defines them:

| Key | Record |
|---|---|
| `payload` | `Payload`: the status-line JSON as read, its strings as given |
| `transcript` | `Transcript`: tokens, cache rate, context, the last exchange, the ⌛ durations and their epochs, ETAs, queue and compactions; and the main thread's own, apart from its agents: `own_tok_up`, `own_tok_down` and `own_cache_pct` over its own requests; `own_parts`, an `[epoch, dollars]` pair for each of those requests and each compaction in the order written, a compaction's stamped where its turn is (at a `/compact` prompt with no calls, else at its boundary); `own_usd`, the parts totalled; `own_est`, true when a compaction is in them, whose summary's cost is an estimate; `lines_added` and `lines_removed` off its own tool results; and the `prompt_id` and `turn_index` of the turn opened last |
| `git` | `Git`: branch, dirty, toplevel, worktree |
| `limits` | `Limits`: the window percentages as the source gave them, this session's and this turn's share of each, the resets as epochs |
| `cache_shares` | `CacheShares`: 📖 and 📝 for the turn and the session |
| `rate` | the session's token rate per second, or null |
| `turn` | the `Turn` the 🎤 figures are about, the last one with main-thread calls that is not a compaction (`_with_shares`' pick), or null |
| `open_turn` | the `Turn` opened last, whether or not it has called yet (`open_turn`), which the running 🎤 row draws: a fresh turn reads zeros, and its `text` is its opener, a queued message or a notification included; or null |
| `accounting.turn` | `turn`'s accounting, as the cost document's per turn, or null |
| `accounting.open_turn` | `open_turn`'s, the same way, or null |
| `accounting.session` | the same over every turn of the session, with `start_s`, or null |
| `accounting.own` | the main thread's own: `cost_usd`, its `own_usd`, and its `sess_share` and `week_share` of each window over `own_parts` (`parts_shares`), null for a window with no start; or null with no transcript |

A status document's window shares in `accounting` are null when there is no
plan reading, since no calibration is asked for then; `limits` carries the
same shares rounded into its strings.

A cost document adds:

| Key | Holds |
|---|---|
| `turns` | every `Turn` the transcript folds into, in order, agent turns included; each with its `lines_added` and `lines_removed`, the main thread's tool results in the turn and its agents' filed with the requests that read them, and its `eta`, `[epoch, seconds]` off the last ETA the main thread reported in it, kept after the turn ends, or `[]` |
| `calibration` | dollars per point of each window, `sess` and `week`, or null |
| `accounting.turns` | per turn: `cost_usd`, its `sess_share` and `week_share` of each window, the `read_share` and `write_share` of its cost, `model_s` and `tool_s` (`turn_times`, the main thread's and its agents' agent-seconds), the main thread's `blocked_s`, and `lines_added` and `lines_removed` |
| `accounting.session` | the same over every turn, for the totals row: sums, with the shares worked out over the sums; and `start_s`, the earliest turn's stamp, which the 🎮 rows' ⌛ counts the session's age from, or null |

The cost rows read their shares from `accounting` and work out none
themselves, so the render stage takes only the percentages from
`usage.plan`, for the totals row's 💳 figures, and not the window ends.

## Status cases

The status suite renders each of the 19 payloads at widths 196, 150, 120, 92, 60 and
unknown (114 goldens), then:

| Case | What it checks |
|---|---|
| `01-baseline` | a full session: every cell drawn |
| `02-no-limits` | a payload with no `rate_limits` |
| `03-no-transcript` | a transcript path that does not exist |
| `04-pr-and-style` | an output style and a PR number on the chat rows |
| `05-haiku-max` | Haiku at `max` effort with a 200k window |
| `06-zero-cost` | a cost under a dollar, no duration fields, no lines changed |
| `07-big-numbers` | a cost over $1,000 and 99,999 lines added |
| `08-limits-critical` | plan windows nearly spent |
| `09-no-session-id` | no session id, so no per-session state |
| `10-empty-payload` | `{}` |
| `11-sonnet-200k` | a 200k context window |
| `12-root-cwd` | `/` as the working directory |
| `13-empty-transcript` | a transcript file with no records |
| `14-limits-full` | a window at 100٪, drawn 💯 |
| `15-cache-warn`, `16-cache-crit` | 🎯's amber and red tiers |
| `17-rounding-boundary` | 999,600 output tokens, which must print `1M`, not `1000k` |
| `18-agents` | a session whose agents billed |
| `19-queue-and-compact` | two queued messages and a compaction, the 📨 and 🤏 cells |
| `dirty-01@*` | `01-baseline` inside the dirty repo: 🍂 and `✱` |
| `stale-plan-*@196` | an explicitly selected `cmd:` source replaces the native reading the main loop left in the cache |
| `tight-*@*` | `--no-mark-spacing` |
| `rules-*@196` | `--column-rules`; the same text as the unruled goldens once the `\|` are spaces |
| `straddle-02@196` | a 5-hour window that opened inside the last turn |
| `uncalibrated-02@196` | a reading too coarse to calibrate window shares from |
| `subdec-*@*` | `--subscript-decimals` |
| `model-fable@196`, `model-mythos@196` | model families other than Opus, Sonnet and Haiku in the 🤖 cell |

The column rules are opt-in, and only 196 is wide enough for them (the cut-off
is 170), so the two `rules-*@196` goldens are the only ruled ones.

The main loop runs with `--usage-source auto`. `01-baseline` carries native
`rate_limits`, which are cached for 60 seconds, so later payloads without their
own (`02`, `10`) quote that cached reading — `💳 15٪` and `87٪`.

## Cost cases

`fixtures/gen/cost.py` writes eleven transcripts, one per branch of the turn reader:

| Transcript | Branch |
|---|---|
| `01-plain` | several ordinary turns |
| `02-compaction` | an automatic compaction, reported on its own 🤏 row |
| `03-single-turn` | one turn, nothing earlier to subtract |
| `04-tool-result` | a turn ending on a tool result, whose Bash call is 🔧 and not ⌛🤖 |
| `05-sidechain` | a sidechain that is billed but is not the context reading |
| `06-interrupted` | an interrupted request with all-zero usage |
| `07-empty` | an empty file |
| `08-woken` | turns opened by messages nobody typed (task notifications, peer messages), including a batch where only the second message is answered |
| `09-agents` | agent files beside the transcript, and a 👥 row for spend the 🎤 row cannot carry; an `Agent` call the first turn waits on, which is in neither ⌛🤖 nor 🔧, and a Bash call in the second |
| `10-turn-id` | the turn tag: a real `promptId` and a `turnIndex` past 9, and the first turn's ids kept off the second's row |
| `11-turn-id-late` | an opener with no ids, as a queue operation writes it: the tag prints the hash alone |

Each renders at 196, 150, 120, 92 and unknown (55 goldens), then:

| Case | What it checks |
|---|---|
| `tight-*` | `--no-mark-spacing`; each has an unflagged sibling at the same width, so the pair's diff is the flag |
| `plan-cache-01@*` | a second planted source reading (15٪ / 87٪) instead of the default 41٪ / 63٪ |
| `plan-full-01@*`, `plan-full-tight-01@196` | a window at 99.6٪ and 100٪, drawn 💯 as the status line draws it |
| `no-acct-01`, `no-datetime-01`, `no-usage-01`, `no-usage-02`, `force-nl-01` | each display switch, at a width where what it removes was visible |
| `all-off-01@92`, `all-off-02@92` | all four switches at once, at the tightest width |
| `straddle-01@*` | a window that opened inside the last turn |
| `uncalibrated-01@*` | a reading too coarse to calibrate from |
| `subdec-*` | `--subscript-decimals` |

`force-nl-01` is checked at 196 on purpose: the program adds that newline by
itself when the window is narrow, so a narrow case would pass without the flag.

## Agent panel cases

`--mode subagent` is checked at two levels, both written by
`fixtures/gen/panel.py`.

**End to end**, the `subagent` suite in `cases.json`, after the status and
cost cases. Each case is a `subagentStatusLine` payload on stdin, and the
golden under `golden/subagent/` is the whole of what the program prints, one
`{"id", "content"}` line per row. The payloads' working directories are
`${SCRATCH}` paths, the fixture repositories, so an agent in the dirty one
draws its 🌿 branch. Every case reads the `app-41-63` source; the three
terminal environments, `tmux`, `iterm` and `unknown-term`, read the same one.

| Session | What it holds |
|---|---|
| `01-mixed` | the running modes (🔧 a tool, 🤖 with a 🛫 rate and quiet in amber, 🚦 a question), ✅ ❌ 🛑, 💥 an API error, 🥚 a queued task, a shell with no transcript, a workflow agent one directory down |
| `02-parked` | completed agents only waiting: 💻 a shell, 📡 a Monitor beside one, ⛳ their own ETA, 💤 an agent under them, whose ETA the parent inherits; an ETA gone stale (amber `+`), one signed off at 0s and running over (red `+`) |
| `03-tree` | the tree four deep with a `│` carried down, 👶🏻 🤏 📨 counts, a worktree's 🌿, a finished ancestor stepped over, a parent not on the panel |
| `04-bare` | the payload alone: shells, a remote agent, a status never seen, tasks with no id or not an object, a label that repeats the description |
| `05-empty` | no tasks: nothing printed |

Each of 01 to 04 renders at 220, 160, 120, 92, 60 and unknown, 05 at unknown
only, and 01 and 03 again at 220 and 120 under `--no-mark-spacing`,
`--subscript-decimals` and each other terminal: 45 goldens.

**Render**, `fixtures/panel/<group>.json`: `render_task_rows`' inputs and the
rows it draws, each as the joined string and as its spans. The inputs are
the prepared `(task, usage, meta, shares)` records, the `Limits`, `cols` and
`now`; a group is one terminal profile and one setting of the two switches,
since the program fixes those per process. The shapes are in the generator's
docstring. `corpus*.json` are the end-to-end cases' own inputs, captured on
their way into the renderer, so their rows are the goldens' rows and the
generator refuses to write them otherwise. The rest are made by hand for
what the corpus does not reach: `states`, `eta`, `counts`, `tree`,
`gauges`, `figures`, `who` (the name, branch and activity), `widths` (one
mixed panel from 400 columns down to 20), `missing` (no usage, a partial
one, no meta or shares, tasks that are skipped), and the mixed panel again
under each switch and terminal (`tight`, `subdec`, `tmux`, `iterm`,
`unknown`).

`run-cases.py` runs the render cases as its `panel` suite: the generator run
again in memory, under `--python`, and compared with what is committed. It
is the panel's counterpart of the figures and render stages, which the
subagent suite skips, having no figures document.

## Grid cases

`fixtures/grid/` pins the redesigned grid
([the plan](../agents/plans/redesign.md)), `mod/src/grid.ts`. Unlike the rest
of `fixtures/`, these are written by the TypeScript, with
`node mod/tools/gen-grid-cases.ts`: the grid is built there first, and the
Python cells the agent panel keeps will be checked against them when they are
brought to it. `all.py` does not touch them.

The inputs are plain data: the mockup's sample rows by id, each its scope, its
panel depth, its label's pieces (path, spans, drop rank) and its cells as
spans by column key, so a port lays them out without any renderer. Each
`layout` case is a set of rows, `cols`, the `--hide` patterns and the fixed or
from-the-rows grid, with the column keys `layout` keeps; each `draw` case is
one row on those keys, with and without the label's spill, and what `draw`
makes of it as spans and as the joined line. The matrix is 200 to 40
columns, eight hide sets, both grids, agents to each depth and both phases'
rows, deduplicated. A file is one terminal profile's, and profiles whose
cases come out the same share one: `unknown-jediterm.json` and
`iterm-tmux.json`, since `_PAD` widens 🧩, 🧠 and 💰 on the second pair. The
shapes are in the generator's header.

`mod/test/grid.test.ts` replays every case under each of its file's profiles
and runs the generator again in memory, failing if what it writes differs
from what is committed, so regenerating and reading the diff is the only way
to change them.
`grid.py` replays the same cases against `coding_agent_usage_line/grid.py`,
the Python port: each profile's environment is set and `formatting.py`
reloaded, as a process with it would have it, and the kept keys, the spans
and the joined line must match. It only reads the cases; a disagreement is
the port's to fix.

## Row cases

`fixtures/rows/` pins the row builders, the step between a figures document
and the grid: `mod/src/band.ts` draws a status document as the band above the
prompt (💳 🎤 🤖💬 🎮 while a turn runs, 💳 🤖💬 once it ends) and
`mod/src/receipt.ts` draws a cost document as the receipt (its 🔺🔖 head, 📊 🎤
and 📊 🎮) and a status document as the 🔻🔖 start line, all through the cells
in `mod/src/cells.ts`. The plan's
[Where each row's figures come from](../agents/plans/redesign.md#where-each-rows-figures-come-from)
says which field each cell reads. Like the grid's, these are written by the
TypeScript, with `node mod/tools/gen-row-cases.ts`.

The inputs are the committed [figures documents](#figures), by id
(`status/01-baseline@196`); documents with the same text are one input, under
the first id, with the rest in `same`. Each `band` case is a status document
drawn at `cols` under the `--hide` patterns in a `phase`, with `rate`, the 🛫
the mod works out itself and passes in; each `receipt` case is a cost document
at `cols` under `hide`, with the 📦 🌿 of the status document named by
`workspace`, which stands for the band's last one; each `start` case is a
status document's start line. Out come the spans of each row and the rows
joined into escape codes. The matrix is 200, 155, 120 and 80 columns, both
phases, three hide sets at 155 and a 🛫 at 200; HOME is `${HOME}`, the
placeholder the documents' paths are written under, and each clock is drawn
in the document's own zone. A file is one terminal profile's, profiles whose
cases come out the same sharing one, as the grid's do.

`mod/test/rows.test.ts` replays every case under each of its file's profiles
and runs the generator again in memory, failing if what it writes differs
from what is committed. To look at the rows in a terminal:

```sh
node mod/tools/draw-figures.ts tests/fixtures/figures/status/<id>.json --cols 160
node mod/tools/draw-figures.ts tests/fixtures/figures/cost/<id>.json \
    --workspace tests/fixtures/figures/status/<id>.json
```

## Assertion suites

These pin values rather than rows, so they assert instead of comparing files.

- **`agents.py`** — reading agent files, pricing each request at its own model,
  folding agent spend into the turn that spawned it, the 👥 row for spend that
  lands after its turn printed, and the ⌛ partition of the main thread's own
  time (agents' work stays on their rows; a question, or an Agent call, is
  waiting; a call still running counts to now on a live session), and the
  same partition per turn, which the receipt's ⌛🤖 and 🔧 draw and which sums
  to the status line's.
- **`subagent.py`** — `--mode subagent`: finding an agent's file (directly
  under `subagents/`, or under `subagents/workflows/*/`), deduplicating
  requests, lines written, the agent's own ⌛ 🤖 🔧 🚦 split (a coordinator
  parked on its agents keeps its ⌛ running and reads the wait as 🚦), 5-hour
  and weekly shares, and the row's shape as stripped text. It checks that a nested row
  pays two columns per level for the `├ ` the panel draws, so every depth ends
  on the same column.
- **`rate.py`** — the 🛫 sampler against a stepped clock (tick, history
  depth, a damaged history file) and its cell; column 3's 📖 📝 shares and
  🧠's alignment; the per-kind brightness cuts; and the ⌛ row's 🔧 🤖 🚦
  partition of Σ, with and without a blocking question.
- **`grid.py`** — the Python grid engine against the TypeScript-written
  [grid cases](#grid-cases), under each profile they name.
- **`usage-source.py`** — the Claude Usage Tracker reader, `cmd:` sources,
  normalization, and the scoped cache. Its fixture store is the tracker's
  schema as last observed; a pre-migration store is a separate case, because
  the tracker once moved its data and the old reader silently returned `{}`.
  To check the fixture against an installed tracker after an app update:

  ```sh
  defaults export HamedElfayome.Claude-Usage - > /tmp/store.plist
  CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST=/tmp/store.plist python3 tests/usage-source.py
  ```

- **`sources-v1.py`, `source-cache.py`, `http-sources.py`, `app-server.py`,
  `claude-sources.py`** — the usage-source layer described in
  [docs/usage-sources.md](../docs/usage-sources.md), all against fixtures and
  fake transports.
- **`codex.py`, `port-cli.py`** — Codex rollout accounting, and the public CLI
  run as a subprocess against temporary homes.
- **`formatting.py`, `claude-subagent-render.py`** — pure helpers, no I/O.
- **`py39-floor.sh`** — `py_compile` over every file under 3.9 (catches
  syntax), then one render per mode under 3.9 (catches a name 3.9 lacks). It
  prefers `/usr/bin/python3`, which is 3.9 on macOS, or `PY39` if set.

## Manual checks

### Replaying real sessions

```sh
tests/compaction-once.py [TRANSCRIPT...]   # default: every eligible transcript
tests/agents-once.py [TRANSCRIPT...]
```

Some rules are properties of a whole session, not of one render. A compaction
writes no usage record and gets no Stop of its own, so it has to be reported
by the next Stop, exactly once. `compaction-once.py` rebuilds what each Stop
hook saw from the `stop_hook_summary` and `compact_boundary` records, and
renders each Stop twice: *settled*, with the transcript caught up, and
*racing*, without the trailing assistant records the hook often cannot see
yet. `ok*` marks a transcript whose compaction predates its first Stop record,
meaning the hook was installed mid-session.

`agents-once.py` checks that every agent request lands on a 🎤 or 👥 row at
the first Stop that saw it, and on a 👥 row at no later Stop. A request whose
agent is still running is held back, and is first seen at the Stop after the
agent ends; `held` counts the ones whose agent never ended. It imports the
program rather than running it.

Both walk `~/.claude/projects/`, so their runtime scales with your history:
one run read 149 sessions and took over ten minutes. Pass transcripts to bound
it, and give it no timeout.

### `--selftest`

```sh
./coding-agent-usage-line.py --selftest
```

Draws specimen rows and measures them against the live terminal. It is the
only check that catches a glyph which measures correctly and paints wrong, so
look at the drawn rows as well as the deltas. Run it in each terminal you use,
from a real tab: it needs a tty to query.

### `probe-advance.sh`

```sh
bash tests/probe-advance.sh
```

Prints this terminal's cursor advance for every glyph the program uses, by
drawing each one and asking the terminal for the cursor position (DSR). The
glyph list is parsed from the `E_*` constants and `EAW_WIDE` in
`coding_agent_usage_line/spec.py`, generated from `spec/layout.jsonc`. It asserts nothing. Run it after a
terminal update and before changing any glyph or width-table entry. See
[glyphs and terminals](../docs/glyphs-and-terminals.md).

## Behaviours that look like bugs

Each of these is deliberate and recorded in the goldens.

1. **▴ is a weighted sum and is not truncated per turn.** Flooring each turn
   and summing drifts below the true total; the per-turn rows and the totals
   row would stop agreeing.
2. **Plan percentages come through a source cache.** A reading is fresh for 60
   seconds (300 for admin and experimental sources), so a totals row can lag
   the live figure by up to a minute. The status line and the cost line quoting
   the same reading matters more than either being current.
3. **A limit percentage under 1 drops its leading zero** — `.09٪` — to keep
   two significant digits in four columns. Exactly zero is `0٪`.
4. **A cost block too narrow for its labels cuts every row's label together.**
   `place_stacked` decides once against the tightest row, so the 📊 marks stay
   stacked. The `@92` and `@120` goldens show the whole block cut at once.
5. **`--mode cost` waits up to 1.5 s for the turn it reports.** The transcript
   is not flushed in step with the Stop hook; without the wait, the line
   reports the previous prompt. `--transcript` names a file nothing is
   appending to, so the goldens never wait.
6. **The status line publishes the context window size; the cost line reads
   it.** The Stop payload carries no model, and the transcript names both
   Opus context sizes the same way, so without it 🧠 on the cost line could be
   5× too high on a 1M-window session. The value goes to a per-session file in
   the state directory, which the suites point at scratch.
7. **`13-empty-transcript` shows `🎮 0٪` beside `🎤 ?`.** An empty transcript
   has a session with no spend, but no last turn to take a share of.

Some case names predate the current source layer: the `plan-cache-*` and
`stale-plan-*` cases no longer involve the status line's old plan cache. They
plant `cmd:` source readings, as described in the tables above.
