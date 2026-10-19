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
| 💳 account | the plan's two windows, and when each resets | the mod, in the band |
| 🎤 and the prompt | the turn | the mod, in the band, while the turn runs |
| 🤖💬 and the reply, or what it is doing | the main thread alone | the mod, in the band |
| 🎮 session, 📦 project, 🌿 branch | the main thread and every agent, summed | the mod, in the band, while the turn runs |
| one per agent | that agent's life | `subagentStatusLine`, in the panel |
| 📊 🎤 and 📊 🎮 | the turn and the session as they stood when it ended | the mod, on the turn's closing line |

A row's label says which scope its figures count; the figures do not carry
the scope's glyph.

The band draws 🎤 and 🎮 only while a turn runs. When it ends, the receipt
on the turn's closing line carries both, frozen, and the band drops to 💳
and 🤖💬; the next prompt brings them back. The columns are laid out over
every row either phase draws, so none moves when the two rows come or go. The band replaces the status line, which is removed from
`settings.json`.

### One column per metric

Every row of the band, the panel and the receipt draws the same columns in
the same order, with the agent panel's cells and widths:

```
model  💰  🧠  🧩 ▴ ▾  🎯  ⌛ ⛳ 🤖 🔧 🚦  🔋  🪫  💾
```

A row with nothing for a column leaves it blank, so the columns hold. Every
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
    └ State             model, what it is doing, 🧠, ⛳, 📨 💻 📡 👶🏻
```

Running totals (💰, 🧩, ⌛, the splits, 🔋 🪫 shares, 💾) add up across both
Agent and Turn. State values describe one thread now and do not add up, so
only agent-shaped rows draw them. Workspace (📦 📁 🌿) and the clock (📅 🕐)
are not usage.

### Narrow terminals

A row's label shrinks first, down to 20 columns. Past that, whole columns
drop, from every row at once, so the grid never breaks. Least important
first:

```
💾  🎯  🤖 🔧 🚦  model  🧩  ⛳  ⌛  🧠  🪫  🔋  💰
```

### Hiding

`--hide scope[.group[.metric]]`, repeatable, with `*` for any one part. One
renderer draws all three readouts, so one path means the same everywhere.

| Part | Values |
|---|---|
| scope | `account`, `turn`, `main`, `session`, `agent` |
| group | `plan` (🔋 🪫 🔜), `cost` (💰), `tokens` (🧩 🎯), `context` (🧠), `time` (⌛ ⛳ 🤖 🔧 🚦), `work` (💾), `state` (model), `chat` (prompt, reply, activity), `workspace` (📦 🌿) |

```
--hide account              the 💳 row
--hide '*.work'             💾 on every row
--hide turn.time.eta        ⛳ on the 🎤 row only
--hide session.workspace    📦 🌿 on the 🎮 row
```

A column hidden on every row it could show on is removed, and the others
close up; hidden on some rows, it is left blank there.

### The receipt

The mod redraws the turn's closing line, `✻ Worked for 4m 2s`, with the
receipt's head after it and its two rows under it:

```
✻ Worked for 4m 2s · 🔺🔖 8f37748e #12  📅 2026-10-19  🕐 13:06:02
📊 🎤 Why is the build slo…          💰 0.2   🧠 +34k  +3٪  🧩 ▴ 28k ▾7.1k  🎯95٪  ⌛  4m ⛳   2m 🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀  🔋.03٪  🪫.050٪  💾 +  12 -   3
📊 🎮 session  📦app 🌿main          💰 115                 🧩 ▴2.7M ▾841k  🎯98٪  ⌛  9h         🤖⠦⠀ 🔧⠦⠀ 🚦⠆⠀  🔋1.2٪  🪫3.80٪  💾 +3.4k - 214
```

The head is 🔺🔖, the head of the turn's promptId and Claude Code's turn
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
- `$.process.run` runs the Python renderer with JSON on its standard input.
- `TurnDuration` is raised on the terminal only; the desktop app would show
  no receipt.

## The whole screen

After the turn, `python3 tools/layout-mockup.py --cols 150 --plain`, made-up
figures; `--phase running` draws it mid-turn:

```
❯ Why is the build slow?

⏺ Bash(npm run build -- --profile)
  ⎿  compile 31s · bundle 18s · test 3m 12s

⏺ The test step takes 80٪ of the build: Jest runs the suites serially
  because maxWorkers is 1 in jest.config.js.

✻ Worked for 4m 2s · 🔺🔖 8f37748e #12  📅 2026-10-19  🕐 13:06:02
📊 🎤 Why is the build slo…          💰 0.2   🧠 +34k  +3٪  🧩 ▴ 28k ▾7.1k  🎯95٪  ⌛  4m ⛳   2m 🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀  🔋.03٪  🪫.050٪  💾 +  12 -   3
📊 🎮 session  📦app 🌿main          💰 115                 🧩 ▴2.7M ▾841k  🎯98٪  ⌛  9h         🤖⠦⠀ 🔧⠦⠀ 🚦⠆⠀  🔋1.2٪  🪫3.80٪  💾 +3.4k - 214
💳 account  🔋 🔜 6.7m  🪫…                                                                                       🔋 15٪  🪫87.0٪                  [-]
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

1. **The plan columns' glyph.** Drawn as 🔋 and 🪫 on every row, the scope
   in the label. The alternative is the scope's glyph, 💳 🎤 🎮, beside the
   figure, as the status line has it now.
2. **Cells left out.** 📅 🕐 on the band, 📁, 🔀, 🎨 and 🛫 are not drawn.
   Whether any comes back as a cell to switch on is open.
3. **Labels in blank columns.** A label stops where the first column starts,
   even on a row whose first columns are blank: the 💳 row cuts its reset
   times while 💰 to ⛳ are empty on it. A label could run on into its own
   row's blank columns.
4. **Where the band's figures come from.** The mod reads
   `$.session.usage()`, whose weekly share can differ from the status line's
   by a point (33 against 34): another source, not rounding. Whether the band
   calls the Python renderer through `$.process.run` or a TypeScript port
   draws the cells is also open.
5. **A tag line under each prompt.** The mod could redraw the prompt's row
   (`UserMessage`) with the receipt's head under it, as the turn starts:
   `🔖 31fe78e5 #35  📅 2026-10-19  🕐 13:43:55`. Tried with a throwaway mod
   on 2026-10-19, and it draws, dim, under the prompt. The mod's own
   `turnId` is not the transcript's `promptId`, but the transcript holds the
   prompt's record by the time `turn.start` reaches the mod, so the id is read
   from there. `$.session.turns()` counts differently from the receipt (39
   against #35), so the number has to come from the receipt's own count. A
   `UserPromptSubmit` hook cannot do it: its payload carries no prompt id, and
   its message would sit behind `UserPromptSubmit says:`.
