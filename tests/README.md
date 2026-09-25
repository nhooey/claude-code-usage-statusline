# Tests for `coding-agent-usage-line.py`

How to run the suites, and what CI runs, is in [docs/tests.md](../docs/tests.md).
This file is for someone changing or adding a test: how the goldens work, what
the pinned environment holds still, what each case is for, and which recorded
behaviours are deliberate.

- [Golden files](#golden-files)
- [The pinned environment](#the-pinned-environment)
- [The generated corpora](#the-generated-corpora)
- [Status cases](#status-cases)
- [Cost cases](#cost-cases)
- [Assertion suites](#assertion-suites)
- [Manual checks](#manual-checks)
- [Behaviours that look like bugs](#behaviours-that-look-like-bugs)

## Golden files

`golden.sh` and `golden-cost.sh` render a payload and compare stdout, byte for
byte, with a file under `golden/status/` or `golden/cost/`. A golden's name is
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
with the change. There is no second implementation to agree with: a golden is
a claim about what the program prints, and the reviewed diff is what keeps it
honest.

To add a case, add the payload or transcript to the generator
(`mkcorpus-status.py` or `mkcorpus-cost.py`), or a `check` line to the suite
for a flag or a planted source, then run `--regen` and read what it wrote.

## The pinned environment

`pin-env.sh` is sourced by both golden suites. It holds still everything the
readout reads that is not the payload; a golden is only as reproducible as
this list.

| Pinned | Without it |
|---|---|
| `CODING_AGENT_USAGE_LINE_NOW=1786847000` (2026-08-16 02:23:20 UTC) | every duration and both clock cells move |
| `TZ=UTC`, `LC_ALL=en_US.UTF-8` | 🕐 and 📅 shift by the local offset |
| `TMPDIR` and `CODING_AGENT_USAGE_LINE_STATE_DIR` in a fresh scratch directory | context, rate samples and source caches written by one case leak into the next, or into your real state |
| `CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE`, planted as `{"sess": 5.50, "week": 4.10}` | the window shares depend on your own history |
| `CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST`, a fixture Claude Usage Tracker store | `auto` could read the tracker app installed on this machine |
| `set_claude_fixture`, which plants a `cmd:` usage source with a fixed `as_of` | the plan percentages come from whatever source the host has |
| `TERMINAL_EMULATOR=JetBrains-JediTerm`, `TMUX` and `TERM_PROGRAM` unset | the width profile depends on the terminal that ran the suite |
| a clean fixture repo (branch `golden-clean`) and a dirty one (`golden-dirty`) as the working directory | 🌿, 💾 and the project name record your checkout |

The pinned instant is 6.7 minutes before `01-baseline`'s 5-hour reset and 1.9
days before its weekly one, so both 🔜 countdowns draw real figures, and it is
after every generated record, so every elapsed figure is positive.

The golden suites run the program with `/usr/bin/python3`, not the first
`python3` on `PATH`.

## The generated corpora

`mkcorpus-status.py` and `mkcorpus-cost.py` write their fixtures into the
scratch directory at the start of every run. Nothing is kept between runs, so
a fixture cannot drift from its generator, and a change to a fixture arrives
as a golden diff. Payload paths are built from the running user's home and
printed as `~`, so no golden carries a username.

The main status transcript is built to reach branches a recorded session only
reaches by accident:

- a **sidechain** request, which is billed but must not set the context
  reading;
- an **interrupted** request, whose all-zero usage must not overwrite the last
  real reading;
- a repeated `requestId`, which must be counted once;
- a question put to the user (`AskUserQuestion`) inside a turn, whose span
  counts under 👤 rather than 🔧;
- timestamps chosen so the ⌛ row's 🔧 🤖 👤 partition reads `58m 3h 6h` over
  a 9.3-hour session.

## Status cases

`golden.sh` renders each of the 18 payloads at widths 196, 150, 120, 92, 60 and
unknown (108 goldens), then:

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
| `dirty-01@*` | `01-baseline` inside the dirty repo: 🍂 and `✱` |
| `stale-plan-*@196` | an explicitly selected `cmd:` source replaces the native reading the main loop left in the cache |
| `tight-*@*` | `--no-mark-spacing` |
| `norules-*@196` | `--no-column-rules`; byte-identical to the ruled goldens once the `\|` are spaces |
| `straddle-02@196` | a 5-hour window that opened inside the last turn |
| `uncalibrated-02@196` | a reading too coarse to calibrate window shares from |
| `subdec-*@*` | `--subscript-decimals` |
| `model-fable@196`, `model-mythos@196` | model families other than Opus, Sonnet and Haiku in the 🤖 cell |

Only 196 is wide enough for the column rules (the cut-off is 170), so every
ruled golden is an `@196`.

The main loop runs with `--usage-source auto`. `01-baseline` carries native
`rate_limits`, which are cached for 60 seconds, so later payloads without their
own (`02`, `10`) quote that cached reading — `💳 15٪` and `87٪`.

## Cost cases

`mkcorpus-cost.py` writes nine transcripts, one per branch of the turn reader:

| Transcript | Branch |
|---|---|
| `01-plain` | several ordinary turns |
| `02-compaction` | an automatic compaction, reported on its own 🤏 row |
| `03-single-turn` | one turn, nothing earlier to subtract |
| `04-tool-result` | a turn ending on a tool result |
| `05-sidechain` | a sidechain that is billed but is not the context reading |
| `06-interrupted` | an interrupted request with all-zero usage |
| `07-empty` | an empty file |
| `08-woken` | turns opened by messages nobody typed (task notifications, peer messages), including a batch where only the second message is answered |
| `09-agents` | agent files beside the transcript, and a 👥 row for spend the 🎤 row cannot carry |

Each renders at 196, 150, 120, 92 and unknown (45 goldens), then:

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

## Assertion suites

These pin values rather than rows, so they assert instead of comparing files.

- **`agents.py`** — reading agent files, pricing each request at its own model,
  folding agent spend into the turn that spawned it, the 👥 row for spend that
  lands after its turn printed, and the ⌛ partition across main thread and
  agents (a question asked on the main thread that overlaps an agent's tool
  call counts once).
- **`subagent.py`** — `--mode subagent`: finding an agent's file (directly
  under `subagents/`, or under `subagents/workflows/*/`), deduplicating
  requests, lines written, tool time including descendants, 5-hour and weekly
  shares, and the row's shape as stripped text. It checks that a nested row
  pays two columns per level for the `├ ` the panel draws, so every depth ends
  on the same column.
- **`rate.py`** — the 🛫 sampler against a stepped clock (tick, history
  depth, a damaged history file) and its cell; column 3's 📖 📝 shares and
  🧠's alignment; the per-kind brightness cuts; and the ⌛ row's 🔧 🤖 👤
  partition of Σ, with and without a blocking question.
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
the first Stop that saw it, and on a 👥 row at no later Stop. It imports the
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
`coding_agent_usage_line/formatting.py`. It asserts nothing. Run it after a
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
