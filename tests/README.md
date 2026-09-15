# Tests for `coding-agent-usage-line.py`

These live beside the program, in its own repository. They did not until
2026-08-28: ten of the thirteen status payloads read a real 8.7 MB session
transcript under `~/.claude/projects/`, which is somebody's actual
conversation and was never going into a repository. Both corpora are now
generated, so there is nothing left in here that belongs to anyone.

```sh
bash tests/golden.sh              # status mode, 135 comparisons — seconds
bash tests/golden-cost.sh         # cost mode, 77 comparisons — seconds
bash tests/py39-floor.sh          # the claimed 3.9 floor, checked — seconds
python3 tests/usage-source.py     # tracker/command/cache migration, 39 cases — seconds
python3 tests/agents.py           # agent spend: reader, fold-in, 👥 row, scan — seconds
python3 tests/subagent.py         # the agent panel rows: file lookup, billing, shares, shape — seconds
python3 tests/rate.py             # the status line's 🛫: the sampler and its cell; the brightness cuts — seconds
python3 tests/formatting.py        # shared formatting and mutable display switches
python3 tests/sources-v1.py        # safe normalized schema and separate quota buckets
python3 tests/source-cache.py      # cache isolation, freshness and refresh backoff
python3 tests/claude-sources.py    # shared account intake projected for Claude
python3 tests/claude-subagent-render.py # prepared panel rows, no transcript/source reads
python3 tests/http-sources.py      # offline admin/private HTTP contracts
python3 tests/app-server.py        # fake app-server framing and bounded cleanup
python3 tests/codex.py             # Codex accounting and origin-aware report state
python3 tests/port-cli.py          # public CLI and concurrent exactly-once late usage
tests/compaction-once.py          # replay real sessions — MINUTES, see below
tests/agents-once.py              # the same for agent spend — MINUTES
./coding-agent-usage-line.py --selftest    # needs a real tty, see below
bash tests/probe-advance.sh       # needs a real tty; measures, does not assert
```

The first seven must end `fail 0   missing 0` — they all print the same
trailer, so a run of all of them reads the same way. Any golden failure
writes the two outputs side by side under `out/` or `out-cost/`, so `diff`
shows the disagreement directly.

The port suites use temporary generated rollouts, SQLite indexes, scripted
collectors and injected transports. They do not inspect installed credentials
or replay your live history. Their success trailers differ from the original
golden suites; each exits nonzero on failure. No golden files should be
regenerated merely to accommodate the port.

**Run them from a directory macOS does not guard.** Under `Documents`,
`Downloads` or `Desktop`, TCC can make Python's import machinery raise
`PermissionError: [Errno 1] Operation not permitted` part-way through a run.
That reads as a fault in the program and is not one — it is the directory. A
checkout under `~/git` or anywhere outside the three protected folders is
fine.

**`compaction-once.py` costs minutes, not seconds.** It is the only test that
reads real sessions, so its runtime scales with the reader's history rather
than with anything in this repository: it walks every transcript under
`~/.claude/projects/`. One recent run read 149 sessions to find the 28 with a
compaction in them, and took **over ten minutes** — a 600-second timeout
killed the run before it, which is how the number is known. Give it no
timeout, or a generous one, and expect to wait. Pass explicit transcripts to
bound it.

**`--selftest` needs a real terminal tab**, and it is the only check that
catches a glyph which measures correctly and paints wrong. Run it in each
terminal you actually read the row in, and LOOK at the drawn rows as well as
the numbers.

Last run 2026-09-08, in Rider/JediTerm and in Ghostty under tmux: every
specimen row delta 0 in both. That closed the four glyphs that had never met a
terminal — 🎤 💯 💳 🎮 — along with the `|` column rule, ▴/▾, 🤏, and, on a
second run after the constant was renamed `E_SUB_DIGITS`, the ten subscript
digits. Nothing the layout draws is inferred from a width table now.

**`probe-advance.sh` asserts nothing** — it measures. It prints this
terminal's real cursor advance for every glyph the program uses, by asking the
terminal with DSR, and it derives the glyph list by parsing the `E_*`
constants and `EAW_WIDE` out of the program beside it. It needs a controlling
tty for the same reason `--selftest` does. Rerun it after a Rider update, and
before changing any glyph or any `EAW_WIDE` entry: a width inferred from a
screenshot has been wrong four separate times.

## Golden files, and why they replaced the differential test

Until 2026-08-25 both harnesses were **differential**: they ran the merged
program and `statusline.sh` / `cost-line.py` on the same payload and demanded
byte-identical stdout. That proved the port — while the reference was the
pre-merge original.

It stopped being one. A reference that has to stay green gets maintained, and
on 2026-08-24 `statusline.sh` was hand-edited four times in a single sitting to
track the Python: the weekly-window glyph, `EAW_NARROW`, `EAW_TEXT_PRES`, the
jq `naughty` predicate. What the comparison measured after that was whether two
files edited the same evening said the same thing — at a cost of 3,588 lines of
reference kept alive to say it.

And it demonstrably passed over the errors it was supposed to catch. A clean
run was 63 pass, and it went straight over two defects that sat in **both**
files identically: `term_profile()` trusting a non-empty `$TMUX` without
stat'ing the socket, and the comment claiming U+1FA70–U+1FAF8 is "DELIBERATELY
ABSENT" from `EAW_WIDE` when the blanket `(127744, 130047)` had swallowed it.
A differential test cannot fail on an error both sides make, and once the
reference is maintained by hand, that is the only kind of error left in it.

The three retired programs are in [`../archive/`](../archive/README.md), which
also records what "did the port change behaviour?" can and cannot be answered
with now. Short version: it cannot, there is no preserved pre-merge copy
anywhere, and `~/.claude` is not a git repository.

**`--regen` is the method, not a weakness.** A golden file is a claim about
what the program prints, so a change to the layout is *supposed* to arrive as a
diff somebody reads and accepts. The old harness could not do that: a layout
change failed all 78 comparisons at once, which reports nothing at all, because
a gate that is red whatever you do has stopped being a gate.

```sh
bash tests/golden.sh --regen      # then READ the diff
```

## What is pinned, and why that is the hard part

`pin-env.sh` holds still everything the readout reads that is not the payload.
The differential test needed almost none of it — it compared two programs
reading the same world at the same moment, so whatever the world said, it said
to both and cancelled. A golden file has nothing to cancel against.

| pinned | otherwise |
|---|---|
| the clock (`CODING_AGENT_USAGE_LINE_NOW`) | every duration and both clock cells move |
| `TZ=UTC` | 🕐 and 📅 differ by the offset and it reads as a layout fault |
| `CODING_AGENT_USAGE_LINE_STATE_DIR` and scratch `TMPDIR` | published context, rate samples and source/report state survive between runs, so a case can read a figure a previous case wrote |
| `CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE`, `CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR` | the test writes to live calibration or walks transcripts outside its fixture tree |
| a usage source's reading, planted, **including its `as_of`** | payloads without native limits can read a different cache or external source. The selected fixture source and normalized cache are pinned; a test cannot rely on whichever source the host happens to have |
| the calibration, planted, **in the short shape** | it is now the units the session shares divide by, so its values reach the rows |
| the terminal profile (`jediterm`) | the answer depends on which terminal ran the suite |
| the working directory (a fixture repo) | the goldens encode today's branch name and today's uncommitted work |

The clock is the one worth dwelling on. The old harness could not pin it at
all, so it ran the reference, then the new program, then the reference again,
and compared only when the two reference runs agreed — up to six attempts per
case, and a SKIP when the clock beat all six. A clean run skipped 15 of 78, and
*which* 15 varied per run. Those were not passes and not failures; they were
comparisons that did not happen. `frozen_now()` costs one environment variable
and one line in each `main_`, and the other 63 became reproducible as well as
green.

## What the goldens gained, and what they still cannot see

Pinning the working directory made two cases possible that the differential
test could never have run deliberately: a **clean** fixture repo and a **dirty**
one, so 🌿 against 🍂 and the ✱ marker are covered on purpose rather than
according to whatever state the checkout happened to be in. Same for the cost
rows' two limit sources — the menu-bar fallback and the status line's plan
cache — which are now separate cases rather than whichever one the machine
happened to have.

Fixed on the way through: `13-empty-transcript.json` pointed at
`/tmp/empty-transcript.jsonl`, which does not exist, so for as long as the
corpus had existed that case had been a second copy of `03-no-transcript`. It
now points at `empty.jsonl`, and renders a `🧩↑ 0 ↓ 0` cell that case 03 does
not — the empty-file parse path, which had never been exercised.

Still invisible to both harnesses:

* **Whether the widths are right for this terminal.** That is `--selftest`,
  and it needs a real tab. Run it in each terminal — Rider/JediTerm, iTerm,
  iTerm+tmux — and **look at the drawn rows as well as the numbers**: a glyph
  can measure perfectly and still render wrong. 🕰 dropped the colons of the
  clock beside it while every measurement of it was correct.
* **tmux inside Rider, which has never been measured.** The `tmux` profile is
  measurement over iTerm and inference everywhere else. One `--selftest` in
  that combination settles it.
* **The U+1FA70–U+1FAF8 contradiction.** The program asserts in a comment that
  the block advances one column and asserts in `EAW_WIDE` that it advances
  two, and the weekly-row glyph 🪫 U+1FAAB sits inside it. Nothing on disk can
  settle that; `probe-advance.sh` in a bare Rider tab can.
* **The live Stop hook's wait.** `--transcript` deliberately does not poll, so
  every golden takes the non-waiting path. `compaction-once.py` is what covers
  the racing one.

## Both corpora are generated, and neither is kept

`mkcorpus-status.py` and `mkcorpus-cost.py` write their fixtures into the
scratch directory at the top of every run, and the run reads them from there.
Nothing is kept on disk between runs, so a fixture cannot drift away from the
generator that claims to describe it: what a golden records is provably the
output of the file beside it, and a change to a fixture arrives as a golden
diff, which is where a change to a fixture belongs.

The status corpus was not always this. Until 2026-08-28 it was fourteen
payload files kept in `corpus/`, eleven of which pointed at one real 8.7 MB
finished session under `~/.claude/projects/`. Every token figure, every chat
row and the whole elapsed group came out of it. That had two costs. The tests
could not move into the repo with the program, because the fixture was a
conversation. And the fixture could be pruned, truncated or resumed at any
time, at which point eleven goldens failed at once and the diff blamed the
program — so `golden.sh` carried a guard that recorded the file's SIZE in
`golden/fixtures.txt` and refused to run when it moved. Generating the corpus
retires the guard along with the dependency.

**What the generated session is built to reach.** Four turns across 9.3 hours,
of which 3.8 are spent answering, so the two figures the ⌛ row splits are
chosen rather than inherited. 140 requests at a realistic size rather than a
dozen carrying seven million cache reads each, which would sum the same and be
a fixture no session could have written. Then three records in a deliberate
order at the end: the one that should set the context reading, a **sidechain**
that must not, and an **interrupted** request whose all-zero usage must not win
the last write. A reader that takes the last of anything rather than the last
of the right thing fails there. A repeated `requestId` mid-session covers the
dedup.

**What it gained.** `15-cache-warn` and `16-cache-crit` are new. The 🎯 cell
tiers at 80 and 50, and the recorded session sat at 98 for its whole length, so
two of that cell's three colours had never been drawn by the suite at all.

**What the goldens no longer carry.** The payload paths are derived from the
running user's home, and the readout collapses that prefix to `~` before it
prints, so no golden holds a username, a project name or a directory that
exists. Nothing in the corpus has to be on disk: `current_dir` is a display
string, not a directory anyone opens.

## Which source a limit row quotes

`limits_snapshot()` takes whichever plan reading was TAKEN more recently — the
status line's publication of Claude Code's payload, or the menu-bar app's own
snapshot — rather than treating an expired cache as proof that the app is
fresher. Two branches, and the corpus covers both:

* **The plan cache wins.** Every payload from `01` onward publishes one,
  stamped at the pinned minute; the app fixture's `as_of` is 200 seconds
  older. So `02-no-limits` and `10-empty-payload` in the main loop quote
  `15٪ / 87٪` and count down `6.7m`.
* **The app wins.** `stale-plan-*@196` plants a plan cache whose `as_of` is
  well behind the app's, and the same two payloads come back with the app's
  `41٪ / 63٪` and `1.6h`.

Both fixtures carry an explicit `as_of` because the decision is a comparison
of two ages, and ages measured against the wall clock are not pinned. At
minute resolution the two crossed over whenever a real minute ticked during a
run: one case took the plan cache, the next took the app, from the same two
files, and `--regen` immediately followed by a check failed six comparisons.
`_reading_age` now measures against `frozen_now()` like every other duration
on the readout.

## The usage sources, and why they are not goldens

`usage-source.py` covers the one part of the program that reads somebody
else's store: `tracker_reading()` on the Claude Usage Tracker app's
UserDefaults, `normalise_reading()` on whatever any source hands back, the
`cmd:` escape hatch, and the 60-second cache in front of all of it.

It is assertions rather than golden files because these cases pin **values**,
not a layout — `session_pct` is 98, a reset in the past is dropped, a
credential never reaches `/tmp` — and the last of those cannot be expressed as
a rendered row at all. The fixture store is built in-process with `plistlib`,
so the whole file runs on Linux with no app installed and CI runs it.

**The fixture is the schema.** It is the shape of a live store read on
2026-09-08, and it is the only record of that shape anywhere in the
repository. This matters because the previous implementation had no such
record and failed exactly that way: it lived in two shell scripts outside the
repo, the app moved its snapshot history out of UserDefaults into a file, the
`usageHistory_<uuid>` key both scripts keyed off stopped existing, and the
wrapper printed `{}` and exited 0 for days. Nothing on the readout said so —
the limit rows have a legitimate blank state and that is what a reader saw.
One case (`pre-migration store`) pins that old shape now, so the two are told
apart deliberately rather than by accident.

To check the fixture against reality after an app update:

```sh
defaults export HamedElfayome.Claude-Usage - > /tmp/store.plist
CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST=/tmp/store.plist python3 tests/usage-source.py
```

A field that moved fails with its name in the diff.

## Column 4 carries three scopes

Added 2026-08-27, and it moved all 86 status goldens at once, so the diff is
worth knowing before reading a failure. Each limit row went from a countdown
and two percentages to a countdown and three, each behind a mark: 🎤 the turn
just answered, 🎮 this session, 💳 the account. The ⌛ row gained a fourth
field, the turn's own wall-clock time, under the same 🎤.

Two side effects show up in the goldens and neither is a regression:

* **Durations gained a character.** `render_elapsed` no longer asks `dur_fmt`
  for `digits=2`, so `01-baseline` prints `👤 5.2h` where it used to print
  `👤 5h`. Same measurement, one more significant digit.
* **The fallback width rose from about 117 to about 128**, column 4 having
  grown by 11. `01-baseline@120` now renders by the fallback layout where it
  used to lay out properly; `@92` and `@60` already did.

Both of those were undone later the same day, and the goldens moved again.
Column 4 is now 33 columns and not 34: every field is exactly as wide as its
own widest reading, the account field is one narrower still because 💯 retires
its only three-character case, and the ⌛ row's three scope figures went back
to `digits=2` to pay for it — `👤 5h`, not `👤 5.2h`, everywhere except Σ.
`LINE3_RESERVED` is measured against that, so it moved too.

`--no-mark-spacing` closes the blank between every mark and its value, which
takes the column to 29. The six `tight-*` cases cover it at three widths on
two payloads; the default is the spacing, and `settings.json` asks for it by
name.

**The cost suite followed on 2026-08-27, and grew by seven.** The flag reaches
🧩, 🎯 and the 💳 inside a totals-row limit cell — the other five cells hold
a `+` or the blank the totals row stacks under it, and closing those would
unstack the two rows — so the cost row is four columns wider by default. `tight-01` at three widths and `tight-02@150` cover it, and each has a
same-width sibling directly above it in the file, so the diff between the pair
IS the flag. Until the 💳 replaced the `/` in a limit cell later the same day, every one
of them reproduced the pre-change golden byte for byte, which is what said
that part was additive. The 💳 is a deliberate content change and moved them;
what still holds is that the tight cell is the same six columns the slash
spent, so the flag costs exactly what it claims.

`plan-full-01` is the other three. The second figure in a totals-row 🔋 or
🪫 cell is the same reading the status line puts beside 💳 — and now carries
that same mark — but it was clamped to `99٪` where the status line drew 💯. Nothing in the corpus went
near 99.5, so no case failed while the two readouts disagreed about a full
window. The planted cache for these three carries 99.6 and 100.0 for exactly
that reason; 💯 now draws on both.

`limit-fractional` in `--selftest` grew a third specimen figure, `0.004`, to
keep the sub-1٪ path covered in the new field.

## The session's share is summed, not subtracted

The left figure on each limit row used to be the plan-wide reading now minus
the reading the session first saw, kept per session id under `TMPDIR`. It is
now `session_shares` — this session's own turn costs since the window opened,
over dollars-per-point — which is what the cost line always used.

Two things in this directory moved because of it.

**The planted calibration reaches the rows now.** It used to be read only by
the cost line. `pin-env.sh` carries the note on why the figures are 5.50 and
4.10 rather than the original 1.85: under the pinned corpus every payload with
`rate_limits` sums to $33.37 in the 5-hour window, and 1.85 put the session's
share at 18٪ of a window standing at 15٪. Possible from a bad calibration;
not something to leave in a golden file for somebody to find.

**Two cases stopped being contaminated by their neighbours.** The baseline
file was keyed by session id and outlived a case, so a payload that shared an
id with an earlier one measured its delta against that one's percentage —
`13-empty-transcript` recorded `24٪` for a transcript with no turns in it at
all. It records `0٪` now.

## Turns nobody typed

`08-woken` is the corpus case for a turn opened by a message DELIVERED to an
idle session rather than typed into it: a task notification, a message from
another session, a cross-session idle notice, the usage limit resetting. Claude
Code writes all four as `type: user` with `promptSource: "system"`, and until
2026-08-26 the reader refused every one of them.

The case is built so that it fails in three separate ways against the old
reader, because the defect showed itself in three:

* its **first** record is a peer message with no typed prompt anywhere before
  it, and `read_turns` drops assistant records that precede the first
  recognised prompt. That turn's request was not misfiled, it was gone — and
  in a session with no typed prompt at all the hook printed
  `📊 (no prompts recorded yet)` over a session that had been working for
  half an hour;
* two later wake messages sit **after** a typed prompt, so their requests were
  filed under it and the `🎤` row reprinted that prompt with somebody else's
  figures added to it;
* the last is a **task notification**, which opens with `<` like a tool result
  and is admitted only by `promptSource`, not by the shape checks.

Before the fix the fixture segmented as ONE turn of 3 requests; after it, five
turns of 4 requests, one of them deliberately empty — a batch of two messages
delivered together, where only the second is answered and the first must not be
what the `🎤` row reports.

Not covered here, and worth knowing: the same change moves the status line's
⌛ 🤖 figure, because `read_transcript` measures answering time between turn
starts. A session idle for twenty minutes and then woken was charged those
twenty minutes as work. On the pinned corpus transcript it is 4.27h before and
4.04h after, and `dur_fmt` renders both as `4h`, so no status golden moved. The
cost corpus is what holds this behaviour down.

## The display switches

`--no-account-totals`, `--no-datetime`, `--no-usage-text` and
`--force-newline` all REMOVE something, so each is checked at a width where
what it removes was visible. The one worth understanding is `--force-newline`
at 196 columns: the program takes that newline by itself when the window is
too narrow to afford the eleven columns `"Stop says: "` costs the first row,
so a case that passes only because the window was narrow would prove nothing
about the flag. 92 columns is the other end of the same question - there the
newline cannot help, and the auto rule declines to spend a blank line on it.

`all-off-01@92` and `all-off-02@92` turn all four on at once, at the width
where the block is tightest. The stacking has to survive four simultaneous
width changes, which no single-flag case covers.

`mkcorpus-cost.py` writes eight synthetic transcripts into the scratch
directory on every run, one per branch of the reader — a plain multi-turn session, an automatic compaction, a single
turn with no previous reading to subtract, a turn ending on a tool result, a
sidechain that must be billed but must not be read as context, an interrupted
request whose all-zero usage must not wipe the real reading, an empty file,
and a session woken by messages nobody typed.

## Replaying a session

```sh
tests/compaction-once.py [TRANSCRIPT...]     # default: every one
```

A golden test renders ONE payload. Some rules are not about one payload:
"every compaction is reported on exactly one cost line" is a property of a
whole session, because a compaction writes no usage record, gets no Stop of its
own, and is reported by the next Stop. Both programs held the same wrong rule
for it and agreed with each other perfectly while losing the row — which is the
same lesson the differential test was retired for, found earlier and in one
rule.

So this one replays real transcripts. Each records where every Stop hook ran
and where every compaction happened, which is enough to rebuild what each Stop
saw. Every Stop is rendered twice: once with the transcript caught up, and once
**racing** — without the trailing assistant records of the turn being reported,
which is the view the hook demonstrably gets when it is not.

`ok*` marks a transcript with a compaction older than its first Stop record.
That is the session the hook was installed during, not a miss.

## Behaviours the goldens record that read like bugs

These were the "deliberate differences from the reference". There is no
reference now, so they are simply what the program does — but each is still
the thing somebody will read as a fault, so each is still written down.

1. **The token field is `↑627k`, no space, width 13** — the status line's
   convention in both readouts, so the two sets of figures share a column.
2. **The weighted ↑ figure is not truncated**, in either the per-prompt row or
   the totals row. Flooring once per turn and then summing drifts below a true
   tally without bound: 58 tokens over a 133-turn transcript. Fixing only the
   total would have been worse — the rows would stop summing to it.
3. **The 🔋/📆 figures come from a 60-second cache**, so the totals row can lag
   the live figure by up to a minute. The two readouts agreeing with each other
   is worth more than either being current, and the Stop hook loses a ~210 ms
   subprocess.
4. **A plan-limit percentage below 1 renders as a fraction** — `.384٪`,
   `.040٪`, the leading zero dropped to buy a third decimal. All four fields on
   the 🔋 and 📆 rows do it. Exactly zero still renders `0٪`; nothing at or
   above 1 is affected. No corpus payload carries a fractional
   `used_percentage`, so the coverage is `limit_pct`'s docstring and the
   `limit-fractional` specimen in `--selftest`.
5. **A cost row too narrow for its label takes the other rows with it.**
   `place_stacked` decides once, against the tightest row, and shifts every row
   by its own chrome. Cutting labels per row moves each 📊 by a different
   amount, which unstacks the readout — measured on the old reference at 150
   columns: a compaction label cut by seven characters, the other two whole,
   and that row's 📊 standing eleven columns left of the pair below it. The
   goldens at 92 and 120 columns record the whole block being cut or dropped
   together.
6. **`--mode cost` waits for the turn it is reporting.** The transcript is not
   flushed in step with the Stop hook: a turn's assistant records were still
   absent 1.2 s after their own timestamps, and the line consequently reported
   the PREVIOUS prompt — `↑561k` then `↑580k` for one 28-minute turn. It now
   polls for up to 1.5 s. `--transcript` names a file nobody is appending to,
   so it does not wait, which is why no golden pays for it.
7. **`--mode status` publishes the context window; `--mode cost` reads it.**
   The Stop payload carries no model, and the transcript records both Opus
   variants as plain `claude-opus-5`, so the cost line cannot tell a 200k
   window from a 1M one. Guessing from the largest reading seen fails exactly
   where it matters: it is *compacting* that keeps a 1M session under the 200k
   line, so a well-kept session never proves its window and every 🧠 figure
   runs 5× high — 51.3٪ against a true 10.3٪, in the session this was found in.
   So the status mode writes Claude Code's own `context_window_size` to
   a hashed per-session file in the private application state directory.
   Tests override `CODING_AGENT_USAGE_LINE_STATE_DIR` with fresh scratch state
   rather than relying only on a synthetic session ID for isolation.

## Changing what the rows draw

Edit the program. Run `--regen`. **Read the diff**, row by row, and accept it
only if every line that moved is a line you meant to move. Then commit the
goldens alongside the change.

There is no second implementation to mirror the edit into any more, which is
the largest thing this retirement bought: a field's width, a figure's format or
a glyph's position used to be two edits in two languages that a hand had to
keep identical, with the acknowledged weakness that the same mistake made twice
passes. Now it is one edit and a diff.
