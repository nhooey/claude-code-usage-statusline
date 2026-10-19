# Redesign: one grid for all three readouts

A proposal, not built yet. Nothing here changes what the program draws today;
[Layout](../../docs/layout.md) is still the reference for that. This document collects
the design as it is decided, and `tools/layout-mockup.py` draws it.

## Why

The status line mixes three scopes on one grid: figures for the turn just
answered, for the session, and for the whole account sit side by side, each
cell shaped its own way. The agent panel's rows, by contrast, are each one
scope, an agent's life, in one fixed set of columns. The prompt receipt is a
third shape again.

Claude Code 2.1.296 added mods: plugins with a TypeScript hooks module that
can draw into parts of Claude Code's own screen. A mod can draw the band
above the prompt (`AbovePrompt`) and redraw the line that closes a turn
(`TurnDuration`). It cannot draw the status line or the agent panel, and
nothing hides the agent panel; see [Claude Code's limits](#claude-codes-limits).

## The design

### One scope per row

| Row | Scope | Drawn by |
|---|---|---|
| 💳 account | the plan's two windows, when each resets, 📅 🕐 | the mod, in the band |
| 🎤 and the prompt | the turn | the mod, in the band, while the turn runs |
| 🤖💬 and the reply, or what it is doing | the main thread alone | the mod, in the band |
| 🎮 session, 📦 project, 🌿 branch, 📁 directory, 🔀 PR, 🎨 output style | the main thread and every agent, summed | the mod, in the band, while the turn runs |
| one per agent | that agent's life | `subagentStatusLine`, in the panel |
| 📊 🎤 and 📊 🎮 | the turn and the session as they stood when it ended | the mod, on the turn's closing line |

A row's label says which scope its figures count; the figures do not carry
the scope's glyph: the plan columns read 🔋 and 🪫 on every row.

The band draws 🎤 and 🎮 only while a turn runs. When it ends, the receipt
on the turn's closing line carries both, frozen, and the band drops to 💳
and 🤖💬; the next prompt brings them back. The columns are laid out over
every row either phase draws, so none moves when the two rows come or go.
The band shrinks from four rows to two when the turn ends, and the prompt
moves up with it; it grows back when the next turn starts. The band replaces
the status line, which is removed from `settings.json`.

### One column per metric

Every row of the band, the panel and the receipt draws the same columns in
the same order, with the agent panel's cells and widths:

```
model  🛫  💰  🧠  🧩 ▴ ▾  🎯  ⌛ ⛳ 🤖 🔧 🚦  🔋  🪫  💾
```

🛫, the token rate, is a state value, so only the 🤖💬 row and the agent
rows fill it.

A row with nothing for a column leaves it blank, so the columns hold. A
label runs on over its own row's leading blank columns, up to its first
figure: the 💳 row has no figures before 🔋, so its label has room for both
resets and the clock. Labels therefore end at different points on different
rows; the figures never move. Which columns drop on a narrow terminal is
worked out without this extra room, so a label's spill never changes the
grid. Every
row's cells end five columns short of the terminal's right edge, the columns
Claude Code keeps for the band's `[-]` button, so all three readouts share one
right edge.

Two cells read differently on one row:

- **🧠 on the 🎤 row** is how much the context grew in the turn, in tokens and
  points: `🧠 +34k +3٪`.
- **The 🔋 and 🪫 resets** are on the 💳 row's label, after 🔜; the figures
  are in the plan columns.

### The metrics hierarchy

```
Account                 🔋 🪫 and their 🔜 resets
└ Session               the main thread and every agent
  ├ Turn                the session cut by time
  └ Agent               the session cut by thread: the main thread, each agent
    └ State             model, 🛫, what it is doing, 🧠, ⛳, 📨 💻 📡 👶🏻
```

Running totals (💰, 🧩, ⌛, the splits, 🔋 🪫 shares, 💾) add up across both
Agent and Turn. State values describe one thread now and do not add up, so
only agent-shaped rows draw them. Workspace (📦 📁 🌿 🔀 🎨) and the clock
(📅 🕐) are not usage; they are parts of a label, not columns.

### Narrow terminals

A row's label shrinks first, down to 20 columns. It sheds its ranked parts
whole before anything is cut, least important first: 🎨, then 🔀, then 📁
on the 🎮 row; 📅, then 🕐 on the 💳 row. A part leaves whole rather than
showing as `📁~/sr…`. What is left is cut with `…`.

Past 20 columns, whole columns drop, from every row at once, so the grid
never breaks. Least important first:

```
🛫  💾  🎯  🤖 🔧 🚦  model  🧩  ⛳  ⌛  🧠  🪫  🔋  💰
```

With the sample figures, 🛫 shows from about 185 columns.

### Hiding

`--hide scope[.group[.metric]]`, repeatable, with `*` for any one part. One
renderer draws all three readouts, so one path means the same everywhere.

| Part | Values |
|---|---|
| scope | `account`, `turn`, `main`, `session`, `agent` |
| group | `plan` (🔋 🪫 🔜), `cost` (💰), `tokens` (🧩 🎯), `context` (🧠), `time` (⌛ ⛳ 🤖 🔧 🚦), `work` (💾), `state` (model, 🛫), `chat` (prompt, reply, activity), `workspace` (📦 🌿 📁 🔀 🎨), `clock` (📅 🕐) |

```
--hide account              the 💳 row
--hide '*.work'             💾 on every row
--hide turn.time.eta        ⛳ on the 🎤 row only
--hide session.workspace    📦 🌿 📁 🔀 🎨 on the 🎮 row
--hide '*.state.rate'       🛫 everywhere
```

A column hidden on every row it could show on is removed, and the others
close up; hidden on some rows, it is left blank there.

### The receipt

The mod redraws the turn's closing line, `✻ Worked for 4m 2s`, with the
receipt's head after it and its two rows under it:

```
✻ Worked for 4m 2s · 🔺🔖 8f37748e #12  📅 2026-10-19  🕐 13:06:02
📊 🎤 Why is the build slow?         💰 0.2   🧠 +34k  +3٪  🧩 ▴ 28k ▾7.1k  🎯95٪  ⌛  4m ⛳   2m 🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀  🔋.03٪  🪫.050٪  💾 +  12 -   3
📊 🎮 session  📦app 🌿main          💰 115                 🧩 ▴2.7M ▾841k  🎯98٪  ⌛  9h         🤖⠦⠀ 🔧⠦⠀ 🚦⠆⠀  🔋1.2٪  🪫3.80٪  💾 +3.4k - 214
```

The head is 🔺🔖, 🔺 pointing up at the turn that ended, the head of the turn's promptId and Claude Code's turn
index, then 📅 and 🕐 when it ended. The Stop hook prints nothing: Claude
Code draws a hook's `systemMessage` behind a fixed `Stop says: `, and no
setting or mod changes that label.

How the mod would do it, from the mod API in 2.1.296:

- `turn.complete` gives the turn's id, its duration in milliseconds, and an
  `agentId` on a subagent's turn, which is skipped.
- `TurnDuration`, the closing line, is given only the word (`Worked`) and the
  same duration. The mod files each receipt under its duration and finds it
  there when the line is drawn.
- The line is redrawn whenever it scrolls into view, so the mod keeps every
  turn's receipt, not only the last.
- `TurnDuration` is raised on the terminal only; the desktop app would show
  no receipt.

### The start line

As the turn starts, the mod redraws the prompt's row (`UserMessage`) with the
receipt's head under it, dim, 🔻 pointing down at the turn it opens, and
when it started:

```
❯ Why is the build slow?
  🔻🔖 8f37748e #12  📅 2026-10-19  🕐 13:02:00
```

So every turn carries its tag at both ends, even one that is interrupted or
still running. Tried with a throwaway mod on 2026-10-19: it draws under the
prompt and costs no tokens. The mod's own `turnId` is not the transcript's
`promptId`, but the transcript holds the prompt's record by the time
`turn.start` reaches the mod, so the id is read from there.
`$.session.turns()` counts differently from the receipt (39 against #35), so
the number has to come from the receipt's own count. A `UserPromptSubmit`
hook cannot do it: its payload carries no prompt id, and its message would
sit behind `UserPromptSubmit says:`. 🔻 is not yet a glyph constant; it joins
`formatting.py` beside 🔺 after a run of `tests/probe-advance.sh`.

### The mod's code

The mod works out its figures and draws them in TypeScript: a port of the
Claude accounting (transcripts, request deduplication, prices, turns,
agents, calibration) and of the cells. Both are pure functions, figures from
records and spans from figures, with no side effects of their own and no
workarounds. Reading the transcript, the usage source and the clock stays at
the edges, in the mod's event handlers.

Python keeps the agent panel, which `subagentStatusLine` draws, and Codex,
which has no mods. So the accounting and the cells exist twice, and the code
is laid out so the two copies are easy to keep in step:

- **One module per module.** Each Python module that is ported has one
  TypeScript module of the same name and split (`claude_records.py` and
  `claude_records.ts`), and each function keeps its name, in the language's
  case (`render_agent_ctx` and `renderAgentCtx`). A change to one names the
  place to change in the other.
- **One spec, read by both.** The cells' keys, `--hide` paths, widths and
  gaps, the glyphs, the drop order, the label ranks and the palette are in
  one JSON file that both load. Neither hardcodes them.
- **One set of cases, run by both.** Shared fixtures, sample transcripts
  with the figures they make and figures with the spans they draw, are
  written by the Python side with `--regen`. Both test suites run every case,
  so CI fails when either copy drifts.
- **The same boundaries.** Pure renderers, one snapshot per render, missing
  is not zero, estimates labelled ([Development](../../docs/development.md#boundaries)) hold in both.

A cell returns spans, not a string: a mod's `Text` refuses control
characters, so the escape codes the Python renderers colour with cannot
reach the screen. Each span is drawn as a nested `<Text>` with its own
`color`, a theme key or a raw colour such as hex, and `dimColor`. The Python
cells return the same spans and join them into escape codes at the edge, so
the shared cases compare spans, colours included.

### Where the columns go

The columns follow from the terminal's width and the `--hide` setting alone.
The chrome is kept for two levels of nesting whether any agent runs or not,
and a deeper agent row cuts its own label instead. The mod and each panel
row's process then reach the same columns without talking to each other, and
no column moves when an agent starts. `--grid rows` in the mockup draws the
alternative, columns from the rows drawn: at 125 columns, a nested agent
appearing there drops 🤖 🔧 🚦 from every row and moves every label.

### The build order

1. **An alignment test.** A throwaway mod draws the mockup's rows, as fixed
   strings, in the band, on the closing line and under the prompt, and a
   stub `subagentStatusLine` draws the mockup's agent rows. Looked at in
   Ghostty, tmux and JediTerm, it shows whether Ink and the terminal agree on
   each glyph's width, what width the band is given, where `[-]` sits and
   how wide the panel's chrome is.
2. **The spec and the shared cases, from Python.** The layout spec as JSON,
   the Python cells returning spans, and the fixtures written from the
   current renderers. The goldens show that nothing moved.
3. **The accounting in TypeScript,** module by module, each passing the
   shared cases before the next.
4. **The cells and the layout in TypeScript,** against the shared cases.
5. **The mod,** from the `usage-band` scaffold: refreshes, receipts kept in
   `$.store` so a resumed transcript still shows them, and the 🔻 line.
6. **The switch.** The band runs beside the status line until the two agree;
   then the status line leaves `settings.json` and
   [Layout](../../docs/layout.md) is rewritten.

## The whole screen

After the turn, `python3 tools/layout-mockup.py --cols 150 --plain`, made-up
figures; `--phase running` draws it mid-turn:

```
❯ Why is the build slow?
  🔻🔖 8f37748e #12  📅 2026-10-19  🕐 13:02:00

⏺ Bash(npm run build -- --profile)
  ⎿  compile 31s · bundle 18s · test 3m 12s

⏺ The test step takes 80٪ of the build: Jest runs the suites serially
  because maxWorkers is 1 in jest.config.js.

✻ Worked for 4m 2s · 🔺🔖 8f37748e #12  📅 2026-10-19  🕐 13:06:02
📊 🎤 Why is the build slow?         💰 0.2   🧠 +34k  +3٪  🧩 ▴ 28k ▾7.1k  🎯95٪  ⌛  4m ⛳   2m 🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀  🔋.03٪  🪫.050٪  💾 +  12 -   3
📊 🎮 session  📦app 🌿main          💰 115                 🧩 ▴2.7M ▾841k  🎯98٪  ⌛  9h         🤖⠦⠀ 🔧⠦⠀ 🚦⠆⠀  🔋1.2٪  🪫3.80٪  💾 +3.4k - 214
💳 account  🔋 🔜 6.7m  🪫 🔜 1.8d  📅 2026-10-19  🕐 13:06:02                                                    🔋 15٪  🪫87.0٪                  [-]
🤖💬 The test step takes 8…  🤖O⁵🏃  💰  92   🧠 115k  11٪  🧩 ▴2.1M ▾640k  🎯98٪  ⌛  9h ⛳   2m 🤖⠦⠀ 🔧⠦⠀ 🚦⠆⠀  🔋.90٪  🪫2.10٪  💾 +3.1k - 180
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
❯
──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
◯  main
◯  🔩🟢 Port renderer  Edi…  🤖O⁵🏃  💰 0.4   🧠 124k  12٪  🧩 ▴ 66k ▾3.6k  🎯93٪  ⌛ 14m ⛳   3m 🤖⠦⠀ 🔧⠄⠀ 🚦⠶⠀  🔋.08٪  🪫.100٪  💾 +  48 -   9
  └ ◯  🔍🟢 Find callers o…  🤖S⁵🚶  💰 0.1   🧠  48k  24٪  🧩 ▴ 24k ▾  1k  🎯90٪  ⌛8.3m ⛳ 2.5m 🤖⠆⠀ 🔧⠀⠀ 🚦⠶⠆  🔋.03٪  🪫.040٪  💾 +   0 -   0
  -- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle)
```

The `◯  main` row and the `└ ◯` before a nested row are the panel's own,
drawn by Claude Code; no hook reaches the main row. Their exact look here is
a guess.

## Claude Code's limits

Read from the 2.1.302 binary:

- **The agent panel cannot be hidden.** It is mounted under the prompt
  unconditionally. `CLAUDE_CODE_DISABLE_AGENT_VIEW` and `disableAgentView`
  cover `claude agents`, `--bg` and the daemon, not this panel.
- **The panel's main row cannot be changed.** `subagentStatusLine` replaces
  task rows by id, and the main row has none.
- **The band's `[-]` is Claude Code's.** It takes the five rightmost columns
  of the band's first row, and ctrl+x ctrl+a collapses the band.
- **A mod cannot draw the status line or the panel.** Its drawable parts are
  `AskUserQuestion`, `UserMessage`, `AssistantMessage`, `ToolUse`,
  `ToolResult`, `ToolGroup`, `ToolProgress`, `CommandOutput`, `Spinner`,
  `TurnDuration`, `InfoNotice`, `SessionMode`, `PromptHint`, `AbovePrompt` and
  `Pane`.

## Open

1. **The usage source.** `$.session.usage()` gives a weekly share a point
   off the status line's (33 against 34). The status line here runs with
   `--usage-source claude-usage-tracker`, and the mod reads Claude Code's
   own figures. Which one the band reads is open.
