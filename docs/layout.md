# Layout and rendering

The reference for everything the program draws: the three-row status line,
the Stop-hook cost line, and the agent-panel rows. Each section opens with a
real render, then says what every cell is. The [glyph legend](#glyph-legend)
at the end lists every mark on all three readouts.

All examples below are the program's own output against the test fixtures
(clock pinned to 2026-08-16 02:23:20 UTC), with colour stripped. Colour and
brightness carry meaning of their own — see
[Colour and brightness](#colour-and-brightness).

- [The status line](#the-status-line)
  - [The grid](#the-grid)
  - [Column by column](#column-by-column)
  - [Fixed widths](#fixed-widths)
  - [Column rules](#column-rules)
  - [Narrow and unknown widths](#narrow-and-unknown-widths)
- [Colour and brightness](#colour-and-brightness)
- [The cost line](#the-cost-line)
- [Agent-panel rows](#agent-panel-rows)
- [Glyph legend](#glyph-legend)

## The status line

At 170 columns:

```
👤💬 Why does the elapsed row report two durations when the …               | 🤖O⁵🏃 💰115   | 🧠   115k    11٪  | ⌛ 🔧  58m 🤖   3h 👤  6h Σ  9.3h  | 📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you …               | 🧩▴2.7M ▾841k  | 📖 🎤 34٪ 🎮 32٪  | 🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m  | 🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                | 🛫200/s 🎯98٪  | 📝 🎤  7٪ 🎮  7٪  | 🪫 🎤 1.6٪ 🎮 8.4٪ 💳 87٪ 🔜 1.9d  | 💾 +3.4k - 214
```

### The grid

The readout has a left half that flows and a right half that does not.

**Left:** the last prompt (👤💬) and the last reply (🤖💬), each on one line
with newlines shown as `¶`, then where the session is working: 📦 project,
📁 current directory, 🌿 branch. The two chat rows swap while the model is
answering, so the newer message is always on the second row; the metrics
beside them stay put.

**Right:** five fixed-width columns, three rows each.

| | Column 1 | Column 2 | Column 3 | Column 4 | Column 5 |
|---|---|---|---|---|---|
| **Row 1** | 🎨 output style | 🤖 model · 💰 cost | 🧠 context | ⌛ where the time went | 📅 date |
| **Row 2** | 🔀 PR number | 🧩 tokens | 📖 re-read share | 🔋 5-hour window | 🕐 time |
| **Row 3** | — | 🛫 token rate · 🎯 cache hits | 📝 cache-write share | 🪫 weekly window | 💾 diff |

Column 1 is empty unless the session has a non-default output style or an
open PR:

```
👤💬 Why does the elapsed row report two durations when the …  🎨 expl      | 🤖O⁵🏃 💰115   | 🧠   115k    11٪  | ⌛ 🔧  58m 🤖   3h 👤  6h Σ  9.3h  | 📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you …  🔀 4211      | 🧩▴2.7M ▾841k  | 📖 🎤 34٪ 🎮 32٪  | 🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m  | 🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                | 🛫200/s 🎯98٪  | 📝 🎤  7٪ 🎮  7٪  | 🪫 🎤 1.6٪ 🎮 8.4٪ 💳 87٪ 🔜 1.9d  | 💾 +3.4k - 214
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

The ⌛ row splits the session's age three ways that add up exactly:

| Field | Meaning |
|---|---|
| 🔧 | time inside a tool call, on the main thread or in any agent |
| 🤖 | time waiting on the model, with tool time removed |
| 👤 | time waiting on you — to type, or to answer a question the session asked |
| Σ | the session's age, wall clock since it started |

Tool spans from the main thread and every agent are unioned, so overlapping
work counts once. `AskUserQuestion` and `ExitPlanMode` are tool calls in the
transcript but are counted as 👤, because their duration is a person
reading. A permission prompt is not moved: nothing in the transcript marks
one, and a tool that waited for approval did stall the turn.

The 🔋 (5-hour) and 🪫 (weekly) rows each show three widening scopes, then a
countdown:

| Field | Meaning |
|---|---|
| 🎤 | this window's share spent by the last turn |
| 🎮 | this window's share spent by this session |
| 💳 | the whole account's consumption of the window, as the plan reports it |
| 🔜 | time until the window resets |

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
👤💬 Why does the elapsed row report two durations when the …               | 🤖O⁵🏃 💰115   | 🧠   115k    11٪  | ⌛ 🔧  58m 🤖   3h 👤  6h Σ  9.3h  | 📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you …               | 🧩▴2.7M ▾841k  | 📖 🎤 34٪ 🎮 32٪  | 🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m  | 🕐    02:23:20
📦repo-dirty  📁…atusline-fixture/deep/tree  🍂golden-dirty ✱               | 🛫200/s 🎯98٪  | 📝 🎤  7٪ 🎮  7٪  | 🪫 🎤 1.6٪ 🎮 8.4٪ 💳 87٪ 🔜 1.9d  | 💾 +3.4k - 214
```

In a linked git worktree 📦 names the main repository, since 🌿 already
names the worktree's branch.

**With no transcript**, every transcript-derived cell blanks rather than
printing zero, and the session scopes print `?`:

```
👤💬 (no prompt yet)                                                        | 🤖O⁵🏃 💰115   |                   |                                    | 📅  2026-08-16
🤖💬 (no reply yet)                                                         |                |                   | 🔋 🎤    ? 🎮    ? 💳 15٪ 🔜 6.7m  | 🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                |                |                   | 🪫 🎤    ? 🎮    ? 💳 87٪ 🔜 1.9d  | 💾 +3.4k - 214
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
👤💬 Why does the elapsed row report two durations when the sessio…                 🤖O⁵🏃 💰115     🧠  115k   11٪    ⌛ 🔧 58m 🤖  3h 👤 6h Σ 9.3h    📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you spent.…                 🧩▴2.7M ▾841k    📖 🎤34٪ 🎮32٪    🔋 🎤1.2٪ 🎮3.8٪ 💳15٪ 🔜6.7m    🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                        🛫200/s 🎯98٪    📝 🎤 7٪ 🎮 7٪    🪫 🎤1.6٪ 🎮8.4٪ 💳87٪ 🔜1.9d    💾 +3.4k - 214
```

### Column rules

The faint `|` between columns is drawn inside the four-column gap that
separates them, so it costs no width: a ruled row and an unruled one are the
same width, column for column.

Rules are on by default. They are dropped when any of these holds:

| Condition | Reason |
|---|---|
| `--no-column-rules` | Asked for. |
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
👤💬 Why does the elapsed row …                 🤖O⁵🏃 💰115     🧠   115k    11٪    ⌛ 🔧  58m 🤖   3h 👤  6h Σ  9.3h    📅  2026-08-16
🤖💬 Two figures, because one …                 🧩▴2.7M ▾841k    📖 🎤 34٪ 🎮 32٪    🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m    🕐    02:23:20
📦repo  📁…deep/tree  🌿golden…                 🛫200/s 🎯98٪    📝 🎤  7٪ 🎮  7٪    🪫 🎤 1.6٪ 🎮 8.4٪ 💳 87٪ 🔜 1.9d    💾 +3.4k - 214
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
| tokens | 100k | 🧩 ▴ and ▾ each, 🧠's size — status line and agent rows |
| rate | 1k/s | 🛫 |
| cost | $1 | 💰 |
| duration | 10 min | ⌛ 🔧 🤖 👤 Σ each; an agent's 🔧 and 🤖 |
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

## The cost line

The Stop hook prints what the prompt just answered cost, over what the
session has cost so far. Installed as the README suggests
(`--no-usage-text --force-newline`), Claude Code shows the rows right-aligned
under the prompt. Rendered here with `--no-right-align`, and with the text
labels on:

```
📊 👥 Usage: Agents (other)  🧩 ▴7.2k ▾900   🎯 99٪                  💰+  0.1   🔋+ 0.01٪ 📖 56٪  🪫+ 0.01٪ 📝  5٪

📊 🎤 Usage: Prompt (last)   🧩 ▴ 28k ▾7.1k  🎯 95٪  🧠+ 3.4٪ +6.8k  💰+  0.2   🔋+ 0.03٪ 📖 32٪  🪫+ 0.05٪ 📝 18٪  ⌛🤖+  5m  📅 2026-08-16
📊 🎮 Usage: Session (total) 🧩 ▴ 68k ▾ 14k  🎯 97٪  🧠 27.1٪   54k  💰   0.6   🔋  0.1٪  💳 41٪  🪫  0.14٪ 💳 63٪  ⌛🤖  10m  🕐   02:23:20
```

After a compaction:

```
📊 🤏 🧩 ▴ 29k ▾  4k  🎯 99٪                  💰+  0.2   🔋+ 0.05٪ 📖 59٪  🪫+ 0.06٪ 📝  0٪  ⌛🤖+ 41s

📊 🎤 🧩 ▴ 12k ▾800   🎯 98٪  🧠-19.5٪ -195k  💰+  0.1   🔋+ 0.01٪ 📖 61٪  🪫+ 0.02٪ 📝 14٪  ⌛🤖+  1m  📅 2026-08-16
📊 🎮 🧩 ▴ 76k ▾  6k  🎯 99٪  🧠  9.7٪   97k  💰   0.5   🔋  0.1٪  💳 41٪  🪫  0.13٪ 💳 63٪  ⌛🤖 3.7m  🕐   02:23:20
```

### Rows

| Row | What it reports |
|---|---|
| 🎤 Prompt | the prompt just answered |
| 🎮 Session | the whole session, including every row above it |
| 🤏 Compact | a compaction since the last report — `/compact` fires no Stop hook of its own, so it is reported here, once |
| 👥 Agents | agent spend the 🎤 row cannot carry: a background agent that finished after its turn printed, or a turn that shared its Stop with a later one |

🤏 and 👥 rows print above the 🎤 row, separated by a blank line. See
[Accounting](accounting.md) for how turns and agents are attributed.

### Cost-line cells

| Cell | 🎤 🤏 👥 rows | 🎮 row |
|---|---|---|
| 🧩 | tokens in and out, as on the status line | the session's |
| 🎯 | cache hit rate | the session's |
| 🧠 | change in context: share of the window, then tokens | context at the end: share, then tokens |
| 💰 | what this row cost | what the session cost |
| 🔋 | share of the 5-hour window, then 📖 re-read share of this row's bill | the session's share, then 💳 the account's |
| 🪫 | share of the weekly window, then 📝 cache-write share | the session's share, then 💳 the account's |
| ⌛🤖 | time the model spent answering | summed over every prompt |
| 📅 / 🕐 | date the row was printed | time it was printed |

The 🧠 cell reads percentage first, the reverse of the status line's.
🧠 and 📅 are blank on 🤏 and 👥 rows, and ⌛🤖 is blank on 👥: a
compaction or a batch of agents has no context change of its own, agent time
is already counted on the rows that spawned it, and the print time is not
when the event happened.

**The sign column.** On the per-row lines, 🧠 💰 🔋 🪫 and ⌛🤖 carry a `+`
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
  than truncating it. A wrapped cost line means the chrome figures are wrong.
- All rows go out as a single `systemMessage` joined by newlines. As separate
  messages, each would get the sixteen-column prefix.

`--force-newline` starts the message with a newline, so `Stop says: ` sits
alone on the first line and every row is laid out against the five-column
indent, gaining eleven columns. The program does this unaided when the
window is too narrow for the labels with the prefix but wide enough without
it.

## Agent-panel rows

While agents run, `--mode subagent` replaces each row of Claude Code's agent
panel. At 170 columns, with a running agent, its nested child, a finished
agent and a shell:

```
◯  🔧🟢 a1b2c3d4e… Port the renderer Editing claude_render.py        🤖O⁵🏃  🔧  4m  🤖8.6m  💰0.4   🧠124k  🧩▴ 66k ▾3.6k  🛫266/s  🎯93٪  🔋.08٪  🪫.10٪  💾 +  48 -   9
├ ◯  🔍🟢 c7d8e9f0a… Find every caller of seg() Searching for seg(   🤖S⁵🚶  🔧  1m  🤖7.3m  💰0.1   🧠 48k  🧩▴ 24k ▾  1k  🛫 80/s  🎯90٪  🔋.03٪  🪫.04٪  💾 +   0 -   0
◯  📐🔵 f3e4d5c6b… Plan the docs rewrite                             🤖O⁵🏃          🤖  4m  💰0.2   🧠 42k  🧩▴ 26k ▾2.9k           🎯85٪  🔋.04٪  🪫.05٪  💾 + 120 -  30
◯  🐚🟢 b1         npm test npm test --watch                                         🤖 13m
```

The leading `◯` and `├` are the panel's own chrome, drawn by Claude Code;
everything after them is this program's.

### Agent-row cells

Left to right:

| Cell | Meaning |
|---|---|
| kind | the agent type, as a glyph (table below) |
| state | 🟢 running, 🟡 pending, 🔵 completed, 🔴 failed, ⚫ killed |
| id | the task id, cut to ten columns |
| name | the task's name, or its description; then what it is doing now |
| 🤖 | model and effort, as on the status line |
| 🔧 | time inside tools — this agent's and every agent it spawned, unioned |
| 🤖 | time thinking: the run so far, minus the 🔧 time. Stops at the agent's last record once it finishes |
| 💰 | cost, from the agent's own transcript, each request priced at its own model |
| 🧠 | the agent's context size (its last request's input) |
| 🧩 | tokens in and out |
| 🛫 | token rate, from the panel's own samples; running agents only |
| 🎯 | cache hit rate |
| 🔋 🪫 | the agent's share of each plan window |
| 💾 | lines added and removed by the agent's own edits and writes |

The right-hand group is fixed width and ends on the same column on every
row. The name takes what is left: the activity is cut first, then the name.
A label that only repeats the description is not drawn.

| Kind glyph | Agent type |
|---|---|
| 🔧 | general-purpose |
| 🎩 | claude |
| 🔍 | Explore |
| 📐 | Plan |
| 📚 | claude-code-guide |
| 📟 | statusline-setup |
| 🍴 | fork |
| 🔗 | workflow |
| 🐚 | shell |
| 🌐 | remote agent |
| 🎎 | in-process teammate |
| 👥 | any other type, including custom agents |

### Nesting

An agent spawned by another agent is drawn by the panel under its parent,
with one `├ ` per level of nesting. The program reads each agent's depth
from the `spawnDepth` in its sidecar file and shortens the row by two
columns per level, so a child's right-hand group lands on the same columns
as its parent's. A task with no sidecar — a shell, a remote agent — is
treated as top level.

A parent's 🔧 includes its descendants' tool time; its 💰, 🧩 and 💾 are
its own transcript only. In the example, the parent's `🔧 4m` is its own
three minutes plus its child's one.

### Blank cells

A task with no transcript — a shell or a remote agent — shows only its name,
activity and run time; there is nothing else to measure, and a zero would
read as a measurement. 🔧 is blank at zero for the same reason. 💾 is drawn
even at `+ 0 - 0` for any agent with a transcript, since writing nothing is a
fact about it. 🔋 and 🪫 are blank without a plan reading, and `?` without a
calibration.

## Glyph legend

Every mark, on every readout. Some glyphs appear in more than one place;
their position tells them apart.

| Glyph | Where | Meaning |
|---|---|---|
| 👤💬 | status line | your last prompt |
| 🤖💬 | status line | the model's last reply |
| ¶ | status line | a newline inside a chat row |
| 📦 | status line | project (the main repository, in a worktree) |
| 📁 | status line | current directory |
| 🌿 | status line | branch, clean tree |
| 🍂 ✱ | status line | branch, uncommitted changes |
| 🎨 | status line | output style, when not the default |
| 🔀 | status line | pull request number |
| 🤖 `O⁵` | status line, agent rows | model: family initial and major version |
| 🐢 🚶 🏃 🚀 🔥 | status line, agent rows | effort: low, medium, high, xhigh, max |
| 💰 | all | cost in dollars |
| 🧩 ▴ ▾ | all | tokens: billable-equivalent input, output |
| 🛫 | status line, agent rows | token rate, per second |
| 🎯 | all | prompt-cache hit rate |
| 🧠 | all | context: size and share of the window, or its change |
| 📖 | status line, cost line | share of the bill spent re-reading the conversation |
| 📝 | status line, cost line | share of the bill spent caching new material |
| ⌛ | status line | the time row |
| 🔧 | status line, agent rows | time inside tools |
| 🤖 | status line, agent rows | time waiting on the model |
| 👤 | status line | time waiting on you |
| Σ | status line | the session's age |
| ⌛🤖 | cost line | time the model spent answering |
| 🔋 | all | the 5-hour plan window |
| 🪫 | all | the weekly plan window |
| 🎤 | status line, cost line | scope: the last turn; the prompt row |
| 🎮 | status line, cost line | scope: this session; the session row |
| 💳 | status line, cost line | scope: the whole account |
| 🔜 | status line | time until a window resets |
| 💯 | status line, cost line, agent rows | a full 100٪ |
| `?` | status line, agent rows | a share that cannot be derived yet |
| 📅 🕐 | status line, cost line | date and time |
| 💾 | status line, agent rows | lines added and removed |
| 📊 | cost line | marks a cost-line row |
| 🤏 | cost line | compaction row |
| 👥 | cost line | late agent-spend row |
| 🔧 🎩 🔍 📐 📚 📟 🍴 🔗 🐚 🌐 🎎 👥 | agent rows | agent kind — see [Agent-row cells](#agent-row-cells) |
| 🟢 🟡 🔵 🔴 ⚫ | agent rows | running, pending, completed, failed, killed |
