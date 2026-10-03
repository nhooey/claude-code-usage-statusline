# Layout and rendering

The reference for everything the program draws: the session status line, the
agent tree and the prompt receipt. Each section opens with a real render, then
says what every cell is. The [legend](../README.md#legend) in the README names
every glyph on all three readouts.

All examples below are the program's own output against the test fixtures
(clock pinned to 2026-08-16 02:23:20 UTC), with colour stripped. Colour and
brightness carry meaning of their own — see
[Colour and brightness](#colour-and-brightness).

- [The session status line](#the-session-status-line)
  - [The grid](#the-grid)
  - [Column by column](#column-by-column)
  - [Fixed widths](#fixed-widths)
  - [Column rules](#column-rules)
  - [Narrow and unknown widths](#narrow-and-unknown-widths)
- [Colour and brightness](#colour-and-brightness)
- [The prompt receipt](#the-prompt-receipt)
- [The agent tree](#the-agent-tree)

## The session status line

At 170 columns:

```
👤💬 Why does the elapsed row report two durations when the …                 🤖O⁵🏃 💰115     🧠   115k    11٪    ⌛ ⛳    ? 🤖 2.8h 🔧  58m 🚦 5.5h    📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you …                 🧩▴2.7M ▾841k    📖 🎤 34٪ 🎮 32٪    🔋 🎤 1.2٪ 🎮 3.8٪ 💳  15٪ 🔜 6.7m    🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                  🛫200/s 🎯98٪    📝 🎤  7٪ 🎮  7٪    🪫 🎤 1.6٪ 🎮 8.4٪ 💳  87٪ 🔜 1.9d    💾 +3.4k - 214
```

### The grid

The readout has a left half that flows and a right half that does not.

**Left:** the last prompt (👤💬) and the last reply (🤖💬), each on one line
with newlines shown as `¶`, then where the session is working: 📦 project,
📁 current directory, 🌿 branch. While the main thread has a background shell
or a Monitor running, `💻 2 📡 1` follows the branch: how many of each it
started and has not heard the end of, read as the [tree reads an
agent's](#state), each drawn only while it has one. Claude Code says the same
in words, and the panel gives a shell a row of its own; the counts are here
so the main thread reads as its agents' rows do. They take their columns from
the directory, and only while something runs. The two chat rows swap while the model is
answering, so the newer message is always on the second row; the metrics
beside them stay put.

**Right:** five fixed-width columns, three rows each, laid out as the
[README's grid](../README.md#session-status-line) shows.

Column 1 is empty unless the session has a non-default output style, an
open PR, messages waiting or a compaction behind it. Row 3 holds the last
two: `📨 2` messages waiting for the main thread's next turn — prompts typed
while it was busy, task notifications, and what agents sent it — and `🤏 1`,
how often this window has been compacted. Each half keeps its columns while
the other is blank. Row 1 and row 2 hold the style and the PR:

```
👤💬 Why does the elapsed row report two durations when the …  🎨 expl        🤖O⁵🏃 💰115     🧠   115k    11٪    ⌛ ⛳    ? 🤖 2.8h 🔧  58m 🚦 5.5h    📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you …  🔀 4211        🧩▴2.7M ▾841k    📖 🎤 34٪ 🎮 32٪    🔋 🎤 1.2٪ 🎮 3.8٪ 💳  15٪ 🔜 6.7m    🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                  🛫200/s 🎯98٪    📝 🎤  7٪ 🎮  7٪    🪫 🎤 1.6٪ 🎮 8.4٪ 💳  87٪ 🔜 1.9d    💾 +3.4k - 214
```

### Column by column

**Column 2 — what the session is and what it has cost.**

- `🤖O⁵🏃`: the model as its family initial and superscript major version
  (`O⁵` Opus 5, `S⁵` Sonnet 5, `H⁴` Haiku 4.5), then the reasoning effort as
  a glyph: 🐢 low, 🚶 medium, 🏃 high, 🚀 xhigh, 🔥 max.
- `💰115`: the session's cost in dollars, as Claude Code reports it.
- `🧩▴2.7M ▾841k`: tokens in and out, including every subagent's. ▴ is
  billable-equivalent input — fresh input, plus cache writes at 2× and cache
  reads at 0.1× — and ▾ is output.
- `🛫200/s`: how fast 🧩's total is climbing, taken over the last 16
  samples, which are at least 5 seconds apart. It jumps by a request's whole prompt
  at each request and rests while a tool runs, so it measures pace, not
  generation speed. `0/s` between turns; blank on a session's first render,
  when there is only one sample.
- `🎯98٪`: prompt-cache hit rate — cache reads as a share of all input.

**Column 3 — how full the context is, and where the money went.**

- `🧠 115k 11٪`: the main thread's context size and its share of the model's
  window. Subagents are excluded: this is the number that decides when *this*
  window needs compacting.
- `📖 🎤 34٪ 🎮 32٪`: the share of the bill spent re-reading the
  conversation (cache reads) — for 🎤 the last turn, for 🎮 the whole
  session. This is the part `/compact` or `/clear` can reclaim.
- `📝 🎤 7٪ 🎮 7٪`: the share spent caching new material (cache writes),
  which compacting does not reclaim.

A high 📖 says compacting would pay; a high 📝 says it would not, however
large 🧠 looks. The session figure sums every turn's dollars before
dividing, so a large turn outweighs a small one. Both are whole percentages
of dollars, not of a plan window.

**Column 4 — time and plan windows**, on a shared four-field grid.

The ⌛ row starts with ⛳, the current answer's ETA (see [ETA](#eta)), then
splits the session's age into 🤖 model time, 🔧 tool time and 🚦 wait time,
which add up exactly.

The three are the main thread's own, read by the same rule as each agent
row's (see [time](accounting.md#time)): an agent's work shows on its row, and
the main thread waiting on it is 🚦. `AskUserQuestion` and `ExitPlanMode`
are tool calls in the transcript but are counted as 🚦, because their
duration is a person reading, and so are `Agent` calls. A permission prompt is not moved: nothing in the transcript marks
one, and a tool that waited for approval did stall the turn.

The 🔋 (5-hour) and 🪫 (weekly) rows each show three widening scopes, 🎤 the
last turn, 🎮 the session and 💳 the account, then 🔜, the time until the
window resets.

🎤 and 🎮 are estimates: the program prices the session's transcript and
divides by a calibrated dollars-per-percent figure (see
[Accounting](accounting.md)). `?` means no calibration exists yet. 💳 is read
from the configured [usage source](usage-sources.md) and can include use from
other machines, the web and the phone. A full window draws `💯٪`. With no
plan reading at all, the rows are blank.

**Column 5 — date, time and diff.** `💾 +3.4k - 214` is the lines added and
removed in the session, as Claude Code reports them.

**Line 3's left side.** A dirty working tree turns 🌿 into 🍂 and adds `✱`:

```
👤💬 Why does the elapsed row report two durations when the …                 🤖O⁵🏃 💰115     🧠   115k    11٪    ⌛ ⛳    ? 🤖 2.8h 🔧  58m 🚦 5.5h    📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you …                 🧩▴2.7M ▾841k    📖 🎤 34٪ 🎮 32٪    🔋 🎤 1.2٪ 🎮 3.8٪ 💳  15٪ 🔜 6.7m    🕐    02:23:20
📦repo-dirty  📁…atusline-fixture/deep/tree  🍂golden-dirty ✱                 🛫200/s 🎯98٪    📝 🎤  7٪ 🎮  7٪    🪫 🎤 1.6٪ 🎮 8.4٪ 💳  87٪ 🔜 1.9d    💾 +3.4k - 214
```

In a linked git worktree 📦 names the main repository, since 🌿 already
names the worktree's branch.

**With no transcript**, every transcript-derived cell blanks rather than
printing zero, and the session scopes print `?`:

```
👤💬 (no prompt yet)                                                          🤖O⁵🏃 💰115                                                              📅  2026-08-16
🤖💬 (no reply yet)                                                                                                🔋 🎤    ? 🎮    ? 💳  15٪ 🔜 6.7m    🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                                                       🪫 🎤    ? 🎮    ? 💳  87٪ 🔜 1.9d    💾 +3.4k - 214
```

### Fixed widths

Every value is formatted to a fixed number of columns and every cell
reserves its width whether or not it has content. The right half is
therefore the same width in every session, and right-aligning it puts each
metric on the same screen column in every terminal tab. Switching tabs never
moves a number.

To stay fixed as values grow, figures carry a unit instead of more digits:
`1.2k`, `4.5M`, `1.5h`, `2.4d`. Money follows the same ladder: `29.8`, `123`,
`1.2k`. Within a column, values are right-aligned so units stack: in column
4, every `٪` sits over the `m`/`h`/`d` of the durations below it.

Percentages use the Arabic percent sign `٪` (U+066A) because it is reliably
one column wide; see [Glyphs and terminals](glyphs-and-terminals.md). Limit
percentages take three characters at every magnitude — `5.4`, `.38`, `12` —
and `--subscript-decimals` draws sub-1 readings with subscript digits
instead (`0₀₁٪`).

`--no-mark-spacing` removes the blank between each mark and its value in
columns 3 and 4, saving six columns:

```
👤💬 Why does the elapsed row report two durations when the sessio…                 🤖O⁵🏃 💰115     🧠  115k   11٪    ⌛ ⛳   ? 🤖2.8h 🔧 58m 🚦5.5h    📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you spent.…                 🧩▴2.7M ▾841k    📖 🎤34٪ 🎮32٪    🔋 🎤1.2٪ 🎮3.8٪ 💳 15٪ 🔜6.7m    🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                        🛫200/s 🎯98٪    📝 🎤 7٪ 🎮 7٪    🪫 🎤1.6٪ 🎮8.4٪ 💳 87٪ 🔜1.9d    💾 +3.4k - 214
```

### Column rules

The faint `|` between columns is drawn inside the four-column gap that
separates them, so it costs no width: a ruled row and an unruled one are the
same width, column for column. At 170 columns, with `--column-rules`:

```
👤💬 Why does the elapsed row report two durations when the …               | 🤖O⁵🏃 💰115   | 🧠   115k    11٪  | ⌛ ⛳    ? 🤖 2.8h 🔧  58m 🚦 5.5h  | 📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you …               | 🧩▴2.7M ▾841k  | 📖 🎤 34٪ 🎮 32٪  | 🔋 🎤 1.2٪ 🎮 3.8٪ 💳  15٪ 🔜 6.7m  | 🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                | 🛫200/s 🎯98٪  | 📝 🎤  7٪ 🎮  7٪  | 🪫 🎤 1.6٪ 🎮 8.4٪ 💳  87٪ 🔜 1.9d  | 💾 +3.4k - 214
```

Rules are off by default, and `--column-rules` asks for them. Even then they
are dropped when any of these holds:

| Condition | Reason |
|---|---|
| `--no-column-rules` | Asked for; it wins over `--column-rules`. |
| `--no-mark-spacing` | That layout is for terminals short on room; it gets no extra chrome. |
| Width under 170 columns | Below that, the project, path and branch are already being cut hard; the row has no room to spare for chrome. |
| Width unknown | The fallback layout (below) already overruns. |

`--column-rules` never overrides a width that cannot hold them. The rule is
ASCII `|` rather than the box-drawing `│`, because `│` is East Asian
Ambiguous width and some terminals draw it two columns wide, which would
shift everything to its right.

### Narrow and unknown widths

The right half never shrinks. As the terminal narrows, the left half gives
way:

1. The chat text is cut first, down to a bare `…`.
2. The project, path and branch share what is left, in proportion. The path
   is cut first and from the left (`…deep/tree`); the branch is cut last.
3. When not even minimal names fit — below about 135 columns — line 3 falls
   back to flowing left to right with a two-column gap, and overruns the
   terminal.

At 140 columns:

```
👤💬 Why does the elapsed row …                 🤖O⁵🏃 💰115     🧠   115k    11٪    ⌛ ⛳    ? 🤖 2.8h 🔧  58m 🚦 5.5h    📅  2026-08-16
🤖💬 Two figures, because one …                 🧩▴2.7M ▾841k    📖 🎤 34٪ 🎮 32٪    🔋 🎤 1.2٪ 🎮 3.8٪ 💳  15٪ 🔜 6.7m    🕐    02:23:20
📦repo  📁…deep/tree  🌿golden…                 🛫200/s 🎯98٪    📝 🎤  7٪ 🎮  7٪    🪫 🎤 1.6٪ 🎮 8.4٪ 💳  87٪ 🔜 1.9d    💾 +3.4k - 214
```

The same fallback applies when the terminal will not report its width
(`--cols 0` forces it); the path is then trimmed to fit an assumed 165-column
row. Four columns are always left empty at the right edge, because Claude
Code draws the status line into a box a few columns narrower than the
terminal.

## Colour and brightness

Hue says *what* a figure is; brightness says *whether it is worth looking
at*.

**Hue is identity and never changes with the value.** Each quantity keeps
its colour on every readout: 🔋 is always green and 🪫 always red, whatever
their figures say. The one exception is 🎯 (below).

**Brightness is magnitude.** A figure with no natural ceiling is dim under a
fixed cut and full strength at or over it:

| Kind | Cut | Where |
|---|---|---|
| tokens | 100k | 🧩 ▴ and ▾ each, 🧠's size — status line and tree rows |
| rate | 1k/s | 🛫 |
| cost | $1 | 💰 |
| duration | 10 min | ⛳ 🤖 🔧 🚦 each on the status line; ⌛ and each gauge's own seconds on the tree rows |
| diff | 100 lines | 💾, each half |

The cuts are fixed rather than relative to the session, so the same
brightness means the same thing on every row and in every frame.

**Shares have cuts of their own.** Plan-window shares are measured against
the week, since 100٪ of a window is not the edge anyone compares a turn to:

| Figure | Dim when |
|---|---|
| 🎤 on 🔋 and 🪫 | the turn is under 1٪ of the week |
| 🎮 on 🔋 and 🪫 | the session is under 5٪ of the week |
| an agent's 🔋 🪫 pair | the agent is under 0.2٪ of the week |
| column 3's 🎤 pair, 🎮 pair | that scope's 📖 is under 67٪ of its bill |

Each pair dims together, so two figures about one scope never disagree. The
67٪ cut for 📖 is set high because re-reading is normally most of a turn's
cost: across 6,002 measured turns the median was 73٪.

**Always dim or always bright, whatever the value:**

- The 5-hour row's 💳 is dim — context for the session's own figures. The
  weekly row's 💳 is bright.
- 🔜 is bright only when the reset is under an hour away.
- Limit percentages and 🧠's percentage are never dimmed by magnitude;
  100٪ is their ceiling and the reader knows it.

**🎯 uses tiers**, because a low hit rate is the problem: red at or under
50٪, amber at or under 80٪, and dim green above. A cache collapse means the
prefix was invalidated and the same work now bills at full price.

## The prompt receipt

The Stop hook prints what the prompt just answered cost, over what the
session has cost so far. Installed as the README suggests
(`--no-usage-text --force-newline`), Claude Code shows the rows right-aligned
under the prompt. Rendered here with `--no-right-align`, and with the text
labels on:

```
📊 👥 Usage: Agents (other)  🧩 ▴7.2k ▾900   🎯 99٪                  💰+  0.1   🔋+ 0.01٪ 📖 56٪  🪫+ 0.01٪ 📝  5٪

📊 🎤 Usage: Prompt (last)   🧩 ▴ 28k ▾7.1k  🎯 95٪  🧠+ 3.4٪ +6.8k  💰+  0.2   🔋+ 0.03٪ 📖 32٪  🪫+ 0.05٪ 📝 18٪  ⌛🤖+  2m  🔧+  3m  📅 2026-08-16
📊 🎮 Usage: Session (total) 🧩 ▴ 68k ▾ 14k  🎯 97٪  🧠 27.1٪   54k  💰   0.6   🔋  0.1٪  💳 41٪  🪫  0.14٪ 💳 63٪  ⌛🤖   5m  🔧   3m  🕐   02:23:20
```

After a compaction:

```
📊 🤏 🧩 ▴ 29k ▾  4k  🎯 99٪                  💰+  0.2   🔋+ 0.05٪ 📖 59٪  🪫+ 0.06٪ 📝  0٪  ⌛🤖+ 41s  🔧+  0s

📊 🎤 🧩 ▴ 12k ▾800   🎯 98٪  🧠-19.5٪ -195k  💰+  0.1   🔋+ 0.01٪ 📖 61٪  🪫+ 0.02٪ 📝 14٪  ⌛🤖+  1m  🔧+  0s  📅 2026-08-16
📊 🎮 🧩 ▴ 76k ▾  6k  🎯 99٪  🧠  9.7٪   97k  💰   0.5   🔋  0.1٪  💳 41٪  🪫  0.13٪ 💳 63٪  ⌛🤖 3.7m  🔧   0s  🕐   02:23:20
```

### Rows

The [legend](../README.md#receipt-rows) names each row. The 🎮 row includes
every row above it. The 👥 row also carries a turn that shared its Stop with a
later one.

🤏 and 👥 rows print above the 🎤 row, separated by a blank line. See
[Accounting](accounting.md) for how turns and agents are attributed.

### Receipt cells

| Cell | 🎤 🤏 👥 rows | 🎮 row |
|---|---|---|
| 🧩 | tokens in and out, as on the status line | the session's |
| 🎯 | cache hit rate | the session's |
| 🧠 | change in context: share of the window, then tokens | context at the end: share, then tokens |
| 💰 | what this row cost | what the session cost |
| 🔋 | share of the 5-hour window, then 📖 re-read share of this row's bill | the session's share, then 💳 the account's |
| 🪫 | share of the weekly window, then 📝 cache-write share | the session's share, then 💳 the account's |
| ⌛🤖 | time with the model: the row's span less its 🔧 and its waiting, plus its agents' | summed over every row |
| 🔧 | time inside tools, as the status line's 🔧 counts it, plus its agents' | summed over every row |
| 📅 / 🕐 | date the row was printed | time it was printed |

The 🧠 cell reads percentage first, the reverse of the status line's.
🧠 and 📅 are blank on 🤏 and 👥 rows: a compaction or a batch of agents has
no context change of its own, and the print time is not when the event
happened. A 👥 row's ⌛🤖 and 🔧 are its agents' own time. A 🤏 row's 🔧 is
always `0s`: the summariser runs no tool.

⌛🤖 and 🔧 split each turn by the status line's rule (see
[Time](accounting.md#time)), and add the time of the agents the row bills, off
each agent's own clock. On the 🎮 row they are the status line's 🤖 and 🔧 for
the same transcript plus every agent's. What the turn spent waiting — on a
question to you, or on an agent it dispatched — is in neither, and the
receipt has no cell for it.

**The sign column.** On the per-row lines, 🧠 💰 🔋 🪫 ⌛🤖 and 🔧 carry a `+`
(or `-` for a context that shrank) in the column after the mark; the 🎮 row
has a blank there. Each upper figure is what one event added to the figure
beneath it, and the blank keeps the two stacking digit under digit.
`--no-mark-spacing` removes the space after 🧩, 🎯 and 💳 but never the sign
column.

**📖 and 📝 on the upper rows** are shares of that row's bill, not of the
window whose mark opens the cell. They sit in the half-cell that 💳 fills on
the 🎮 row, so the two rows stack.

The rows are laid out as one block: the placement is decided once for the
tightest row, so every row's columns line up. When there is not room for the
labels, the labels are cut, never the metrics.

### "Stop says:" and `--force-newline`

Claude Code shows a hook's `systemMessage` in a box that indents each line
five columns and prefixes the first line with `Stop says: `, sixteen columns
in all. Neither figure appears in the hook payload; the program subtracts
them as constants. Two consequences:

- If a row is too wide, Claude Code wraps its tail onto a second line rather
  than truncating it. A wrapped prompt receipt means the chrome figures are wrong.
- All rows go out as a single `systemMessage` joined by newlines. As separate
  messages, each would get the sixteen-column prefix.

`--force-newline` starts the message with a newline, so `Stop says: ` sits
alone on the first line and every row is laid out against the five-column
indent, gaining eleven columns. The program does this unaided when the
window is too narrow for the labels with the prefix but wide enough without
it.

## The agent tree

While agents run, `--mode subagent` replaces each row of Claude Code's agent
panel. At 180 columns, with a running agent, its nested child, a finished
agent and a shell:

```
⏺  ✶🔩🟢🤖 👶🏻1 a1b2c3d4e… Port the renderer Editing …  ⏺   🤖O⁵🏃  💰 0.4   🧠 124k  12٪  🧩 ▴ 66k ▾3.6k  🛫266/s  🎯93٪  ⌛ 14m ⛳   3m 🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀  🔋.08٪  🪫.10٪  💾 +  48 -   9
└ ◯  ✢🔍🟢🔧     c7d8e9f0a… Find every caller of seg…  └ ◯ 🤖S⁵🚶  💰 0.1   🧠  48k  24٪  🧩 ▴ 24k ▾  1k  🛫 80/s  🎯90٪  ⌛8.3m ⛳    ? 🤖⠶⠦ 🔧⠄⠀ 🚦⠀⠀  🔋.03٪  🪫.04٪  💾 +   0 -   0
◯   📐⚫✅     f3e4d5c6b… Plan the docs rewrite        ◯   🤖O⁵🏃  💰 0.2   🧠  42k   4٪  🧩 ▴ 26k ▾2.9k           🎯85٪  ⌛  5m ⛳    ? 🤖⠶⠆ 🔧⠀⠀ 🚦⠆⠀  🔋.04٪  🪫.05٪  💾 + 120 -  30
◯   🐚🟢       b1         npm test npm test --watch    ◯                                                                  ⌛ 13m
```

The leading `◯`, `⏺` and `└` are the panel's own chrome, drawn by Claude Code;
everything after them is this program's, including the copy of that tree
where the figures start (see [Nesting](#nesting)).

### Tree cells

Left to right. 👶🏻, 🤏, 💻, 📡, 📨 and 🔇 are drawn only while some row on the
panel needs them, so they sit together right after the kind and state:
those keep their column however many of the six the panel draws, and one
coming or going moves only the id and the name, never the right group. The
ones that stay once they come, 👶🏻 and 🤏, sit furthest left, then 💻 and 📡,
which last as long as a shell or a Monitor runs, so 📨 and 🔇 coming and going
move the fewest cells. On a panel where no row needs one,
a cell takes no columns at all.

| Cell | Meaning |
|---|---|
| spinner | a running agent's activity, first on the row: Claude Code's own spinner, `· ✢ ✳ ✶ ✻ ✽` and back, in red. It steps one frame for each ⏺ the agent writes, a text or tool-call block, so it moves when the agent does and stands still when it stalls. Blank on any other row, and on a shell, which has no transcript to count in |
| kind | the agent type, as a glyph (table below) |
| state | the phase, 🟢 running, 🟡 paused or ⚫ ended, then what the agent is doing in it. See [State](#state) |
| 👶🏻 | how many rows hang directly under it on the panel, finished or not. The cell is there on every row once any row has children |
| 🤏 | how often its window has been compacted. On every row once any row has one |
| 💻 | how many background shells it started and has not heard the end of, while it runs or is paused; not once it has failed or been killed. Paused, the 💻 after 🟡 says it waits on one; this says how many. On every row once any row has one |
| 📡 | the same for its Monitors |
| 📨 | messages sent to it with SendMessage and not yet delivered: Claude Code's own "N queued". See [Inbox](#inbox). On every row once any row has one |
| 🔇 | how long a running agent has written nothing, from a minute, amber from ten. Blank while it waits on a question or an agent it started, which its 🚦 already says. The cell is there on every row once any row draws one |
| id | the task id, cut to ten columns |
| name | the task's name, or its description; then 🌿 and the branch of a worktree it works in apart from the session's; then what it is doing now |
| tree | the panel's tree, drawn again beside the figures, in a wide window |
| 🤖 | model and effort, as on the status line, right before the 💰 they priced |
| 💰 | cost, from the agent's own transcript, each request priced at its own model |
| 🧠 | the agent's context size (its last request's input), and its share of the window the payload gives for its model |
| 🧩 | tokens in and out |
| 🛫 | token rate, from the panel's own samples; running agents only |
| 🎯 | cache hit rate |
| ⌛ | the agent's age: from its first record, or its `startTime` if that is earlier, to now, or to its last record once it has finished. A completed agent still parked on its children keeps counting. Not the `startTime` alone, which Claude Code restarts when it resumes an agent |
| ⛳ | the time the agent says it has left. `?` until it reports. See [ETA](#eta) |
| 🤖 ⠶⠄ | share of ⌛ spent thinking: the agent's working spans off its transcript, minus its own tool calls |
| 🔧 ⠆⠀ | share of ⌛ spent inside its own tools; its children's are on their rows |
| 🚦 ⠄⠀ | share of ⌛ spent waiting: on a question put to you, on an agent it started, or parked until something woke it |
| 🔋 🪫 | the agent's share of each plan window, right after the time it spent |
| 💾 | lines added and removed by the agent's own edits and writes |

The right-hand group is fixed width and ends on the same column on every
row. The name takes what is left: the activity is cut first, then the name.
A label that only repeats the description is not drawn. The kind glyphs are in
the [README legend](../README.md#agent-kind).

### State

Claude Code gives a task one of five statuses, and `completed` covers two
different things: an agent that has finished, and one that ended its turn to
wait on work it started, which Claude Code keeps alive until that work ends.
The row reads the phase off everything it knows, and puts what the agent is
doing in that phase after the circle.

| Phase | Mark | When |
|---|---|---|
| 🟢 running | 🤖 | the model has the floor: no tool call is waiting on its result |
| | 🔧 | a tool call is waiting on its result |
| | 🚦 | the call it waits on is a question to you or an agent it started |
| | (none) | a task with no transcript to say, such as a shell |
| 🟡 paused | 💤 | completed, with an agent under it still running or not started |
| | 💻 | completed, with a background shell it has not heard the end of |
| | 📡 | completed, with a Monitor it has not heard the end of |
| | ⛳ | completed, with nothing it can name but a live ETA in its last message |
| | 🥚 | Claude Code's `pending`: not started |
| ⚫ ended | ✅ ❌ 🛑 | completed and waiting on nothing, failed, killed |
| 🟡 or ⚫ | 💥 | completed or failed, and its last answer died on an API error: Claude Code writes one only once its retries are spent, and still calls the agent completed |

A paused agent shows the first of its reasons in that order. A background
task opens on the tool result that hands back its id: `backgroundTaskId` for a
Bash, whether run in the background or moved there by its timeout, and
`taskId` with `timeoutMs` for a Monitor. It closes on a `<task-notification>`
for that id that carries a `<status>` (a Monitor's events carry none), on
TaskStop's result, or on a TaskOutput that reads it finished. A status never
seen is two amber letters and no mark.

Some limits are Claude Code's and no setting changes them. The panel shows
five rows at a time and scrolls with the cursor. It hides a finished
background agent that waits on nothing, and removes any other finished task
30 seconds after it ends, unless you have opened it.

### Inbox

A message SendMessage cannot hand over at once waits in the agent's inbox
until its next tool round, and Claude Code's own row says `1 queued`. The
payload carries no such count, so 📨 rebuilds it from the two ends. The
sender's transcript — the main thread's or another agent's — gets a result
reading `Message queued for delivery to <id> at its next tool round.` The
agent's own file gets the delivery, as a `queued_command` attachment or a
`type: user` record, with an `origin` of `coordinator` for the main thread or
`peer` for an agent. The two are matched by time: a send adds one, a
delivery takes one away, and the count never drops below zero. A peer
`handback` is a report home and is not counted, and nor is a message typed
into the agent's pane, which leaves nothing on the sending side, so 📨 can
read lower than Claude Code's count. A killed or failed agent's inbox is
dropped. Files last written before the earliest agent on the panel started
are not read.

### Nesting

An agent spawned by another agent is drawn by the panel under its parent,
with a `├ ` or `└ ` per level of nesting. The program reads each agent's
parent from the `parentAgentId` in its sidecar file and resolves it the way
the panel does:

- An ancestor that has finished and waits on nothing is stepped over. The
  panel drops such an agent and hangs its children from its parent. The
  panel's own test reads state the payload doesn't carry, so the program
  takes "completed and not paused" for it (see [State](#state)). An agent
  paused on a child still running keeps its children.
- An ancestor missing from the payload ends the walk, and the row is top
  level. The payload lists every agent the panel can show.
- A task with no sidecar — a shell, a remote agent — is top level.

The depth is the number of ancestors left. The program shortens the row by
two columns per level below the first, so a child's right-hand group lands
on the same columns as its parent's. The panel's indent also pushes a
child's left-hand cells two columns right of its parent's, so every row
opens with two blank columns per level it sits above the deepest row, and
the kind, state, 👶🏻, 🤏, 💻, 📡, 📨, 🔇, id and name start on one column at every depth.

In a wide window the panel's tree is far from the figures, so the row draws
it again where the figures start: `◯` for an agent, `├ ◯` or `└ ◯` for a child, with
a `│` running down an ancestor's column while its siblings continue. That
shows which rows are parents, whose 🚦 includes the time their children
ran, and which are leaves. The row builds the copy from those resolved parents, and orders siblings
by `startTime`, as the panel does. The panel shows a row's
children only when that row is expanded, and only the selected row is, so a
row with a child showing gets the filled `⏺`, as the panel draws it. The
panel's `❯` sits in the gutter left of its tree, and the copy doesn't draw
it. The copy is padded to the deepest row's width, so the right group
stays aligned. The row draws it only when the name keeps at least 40
columns; in a narrower window the row leaves it out and gives the columns to
the activity.

A parent's figures are its own transcript only: its children's tool time,
cost, tokens and diff are on their rows. Time it spends waiting on a child is
its 🚦.

### ETA

An agent reports how long it has left by writing a line of its own:

```
⛳ skills/coding-agent-usage-line-report-eta: ETA 4m
```

The `coding-agent-usage-line-report-eta` skill, in `skills/` in this
repository, tells it when: once it has a plan, after each milestone, and
whenever the estimate moves by a quarter or more. The row reads the last such
line from the text of the agent's own messages, so a tool result that quotes
one isn't counted. The skill's path is the part matched; the ⛳ is there so
a person scrolling the transcript notices the line, and may be left off. The
🏁 the skill asked for before ⛳ is read as well. The readout draws the time
left under the same ⛳.

A report is an estimate of the whole run: the time already gone when it was
written, plus the time it said was left. The row counts it down between
reports. ⛳'s figure is what is left of that total. Past the estimate it
turns amber, with a `+` for how late the agent is. A report of zero is the
skill's sign-off, an agent saying it ends now: it reads `0s`, and if the
agent keeps going it counts up how late it is at once, in bright red rather
than amber: the agent said it was done and is running over, which is louder
than an estimate that ran short. A child whose later finish the row inherits
takes that back to amber, since the overrun is then the child's. The
cell is `?` only when there is no live estimate: no report yet, or an
answer that ended its turn after its last report. The exception is a
report in the message that ends the turn, which stays live, unless it is
the `0s` sign-off, which finishes the answer. That is an agent parking on background work, and Claude Code
marks it completed while it waits; the row shows it 🟡 paused. A killed or failed agent is read at
its last record and stops there.

**Inherited up the tree.** A parent isn't done until the children it is
waiting on are, so a row counts to the latest finish among its own estimate
and those of its running descendants, recursively. Its own wins when its own
plan runs longer, and a finished child counts for nothing. Each agent
reports its own conceptual ETA for its whole task, including rounds of
subagents it plans to start later, which only it knows about. It doesn't add
up its children's reports; the maximum here keeps its row from finishing
before any of them.

The status line's ⌛ row carries the same cell for the main thread, as the
root of that tree: its last report in the answer to the current prompt,
counted from that prompt, pushed out to the latest finish of any agent still
answering. An agent that has written nothing for half an hour is taken for
dead rather than late. A new prompt clears the main thread's own report, and
so does the answer ending, so an idle session with no agents running reads
`?`. Its late `+` follows the same colour rule as a row's: bright red past
the main thread's own `0s` sign-off, amber past an estimate, and amber
again when a live agent's later finish is the one it ran past. Both
readouts run their times ⛳ 🤖 🔧 🚦: the status line prints
figures for the last three, and the tree rows, which put ⌛ first, print
each one's share of it.

An agent that hasn't reported shows `⛳ ?`, since saying nothing is not the
same as having nothing left. The skill reaches an agent only if it is
loaded: `skills: [coding-agent-usage-line-report-eta]` in an agent type's
frontmatter preloads it, and a line in `CLAUDE.md` reaches the main session
and the general-purpose agents. The built-in Explore agents don't read
`CLAUDE.md`, so they usually stay at `?`.

### Blank cells

A task with no transcript — a shell or a remote agent — shows only its name,
activity and run time; there is nothing else to measure, and a zero would
read as a measurement. 🔧 is blank at zero for the same reason, and ⛳ is
blank there too: a task with no transcript has nowhere to write a report. 💾 is drawn
even at `+ 0 - 0` for any agent with a transcript, since writing nothing is a
fact about it. 🔋 and 🪫 are blank without a plan reading, and `?` without a
calibration.
