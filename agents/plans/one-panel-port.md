# One port: Claude's figures drawn by the mod alone

Approved to build. Its steps are `OP1` … `OP7` in [the schedule](_schedule.md).
Its decisions are taken (see [Decided](#decided)).

## Why

Most of the logic is written twice. Nineteen modules of
`coding_agent_usage_line/` have a twin in `mod/src/`, about 17,800 lines
of Python beside about 12,000 of TypeScript, and the two are held together
by fixtures the Python writes and goldens both sides are checked against.
Every change to what a row shows is made in both ports, in
`spec/layout.jsonc`, and in the fixtures and goldens of each: dropping one
glyph from the agent panel's rows touched 81 files.

The band, the footer rows and the receipt are already the mod's alone.
Claude Code 2.1.323 removed `subagentStatusLine`: the agent panel always
draws its own rows, runs no command, and no `ui.render` component draws
it. So the Python's Claude modes serve nothing in Claude Code but the mod's
fold worker, and each subagent's figures need a new place: the band above
the prompt, one row per running subagent, drawn by the mod with the
renderer it already has (`claude_subagent_render.ts`, `cells.ts`,
`grid.ts`).

## What the Python serves today

| Use                                   | Entry                                                     | Has a TypeScript twin                                 |
| ------------------------------------- | --------------------------------------------------------- | ----------------------------------------------------- |
| The mod's large transcript folds      | `mod/scripts/agent_lines.py`, spawned by `transcripts.ts`       | yes: the mod folds 8 MiB at a time without it, slower |
| The status line and the cost receipt  | `--mode status`, `--mode cost`                            | yes: the band and the mod's receipt replace both      |
| Codex receipts and its status         | `--agent codex`, from a Codex `Stop` hook                 | no                                                    |
| The reference the ports are tested on | the fixture generators and goldens under `tests/`         | the TypeScript is what is tested against it           |

## Which entries reach each module

`OP1`'s measure, by `tools/python-module-reach.py`, which follows each
module's imports from each entry without running anything. Codex is the
launcher with `--agent codex`; Claude is the same launcher with
`--agent claude`, the agent panel among its modes; the fold worker is
`mod/scripts/agent_lines.py`. The last column counts the Python files
under `tests/` and `tools/` that load the module.

| Module | Lines | Codex | Claude | Fold worker | Test files |
| --- | ---: | :---: | :---: | :---: | ---: |
| `claude.py` | 3649 | — | ✅ | — | 20 |
| `claude_render.py` | 1192 | — | ✅ | — | 23 |
| `claude_subagent_render.py` | 720 | — | ✅ | — | 22 |
| `claude_cost_render.py` | 267 | — | ✅ | — | 20 |
| `grid.py` | 260 | — | ✅ | — | 22 |
| `inbox_fold.py` | 245 | — | ✅ | — | 21 |
| `claude_sources.py` | 77 | — | ✅ | — | 20 |
| `credits.py` | 69 | — | — | — | 1 |
| `claude_records.py` | 3204 | — | ✅ | ✅ | 26 |
| `main_fold.py` | 662 | — | ✅ | ✅ | 26 |
| `agent_fold.py` | 193 | — | ✅ | ✅ | 26 |
| `sources.py` | 1006 | ✅ | ✅ | — | 20 |
| `config.py` | 637 | ✅ | ✅ | — | 21 |
| `codex.py` | 540 | ✅ | ✅ | — | 20 |
| `options_spec.py` | 463 | ✅ | ✅ | — | 21 |
| `cli.py` | 454 | ✅ | ✅ | — | 3 |
| `options.py` | 255 | ✅ | ✅ | — | 21 |
| `render.py` | 200 | ✅ | ✅ | — | 20 |
| `usage_report.py` | 113 | ✅ | ✅ | — | 3 |
| `models.py` | 40 | ✅ | ✅ | — | 20 |
| `formatting.py` | 1539 | ✅ | ✅ | ✅ | 32 |
| `spec.py` | 1402 | ✅ | ✅ | ✅ | 32 |
| `spans.py` | 280 | ✅ | ✅ | ✅ | 32 |
| `state.py` | 268 | ✅ | ✅ | ✅ | 26 |
| `state_spec.py` | 91 | ✅ | ✅ | ✅ | 26 |

What it decides for `OP4` and `OP5`:

- **Codex keeps 14 modules, 7,288 lines:** `cli.py`, `codex.py`,
  `render.py`, `sources.py`, `config.py`, `options.py`, `options_spec.py`,
  `usage_report.py`, `models.py`, `state.py`, `state_spec.py`,
  `formatting.py`, `spec.py` and `spans.py`. `formatting.py` and `spec.py`
  are kept whole here but hold the Claude rows' glyphs and cells too, and
  `sources.py` holds the Claude Usage Tracker's adapter; each can shed its
  Claude parts at `OP5`.
- **Claude alone uses 7 modules, 6,410 lines:** `claude.py`,
  `claude_render.py`, `claude_subagent_render.py`, `claude_cost_render.py`,
  `grid.py`, `inbox_fold.py` and `claude_sources.py`. They go at `OP5`.
- **The fold worker also uses 3, 4,059 lines:** `claude_records.py`,
  `main_fold.py` and `agent_fold.py`. They go at `OP5` once `OP4` has
  moved the worker to Node.
- **No entry loads `credits.py`,** 69 lines: the 💳 row is the mod's, and
  only `tests/source-cache.py` imports it. It can go with its test now.
- **The tests:** 32 files load `formatting.py`, so the generators and
  checks that only test the Claude modules go with them at `OP5`, and the
  rest stay as Codex's.

## Target

- **No agent panel command.** `--mode subagent`, its `subagent` suite and
  goldens, `examples/claude/settings.json`'s `subagentStatusLine`, and
  every doc that names it are gone. The renderer's own cases
  (`tests/fixtures/panel/`) stay, as the inputs and rows the TypeScript
  renderer is checked against.
- **The session's threads as a tree in the band.** Above the prompt, the
  mod draws 🎮 the session as the root, 🎤 the turn and 🧵 the main thread
  as its children, and each subagent under the thread that started it,
  from the agent folds it already keeps, with the figures the panel's
  rows had: model, cost, tokens, cache, context, plan-window shares,
  🤖 🔧 🚦 clocks, the inbox and the worktree branch. See
  [The band's tree](#the-bands-tree).
- **The mod's large folds in Node,** through `process.run`, so the mod
  needs no Python.
- **The Python keeps Codex alone.** Its Claude modules, their tests and
  their fixture generators go, with `--mode status` and `--mode cost`
  for Claude: the mod is the one way to see them in Claude Code. The
  TypeScript becomes the reference for what stays.

## The band's tree

Every thread, the main one included, is a row of the same grid: small
multiples, one row design repeated, with the hierarchy in the label
alone, as a tree table draws it, so every figure keeps its column on
every row.

- **The tree.** 🎮 the session is the root; 🎤 the turn and then 🧵 main
  are its children; each subagent sits under the thread that started it, in
  the order they started. The lines are `├─` `╰─` `│`, branching at the
  middle of the cell, three columns a depth.
- **The label.** Its kind glyph and state circle (🟢 🟡 ⚫, ✅ once
  finished), its counts, its name, then its latest progress update, the
  line a thread writes between tool calls, dimmed, while it works or
  waits; an idle or finished thread shows its name alone. The label takes
  the columns the figures leave and is cut with `…`, so on a narrow
  terminal the update shrinks first and no figure moves. The path
  `chat.progress` hides the update.
- **The root's label** is the workspace: 📦 the project, 🌿 the branch and
  🔀 the pull request, each a link to it on GitHub. The 💳 row keeps the
  account alone.
- **Folding.** Every row with children folds and opens on a click: its
  mark takes the place of the `─` in its tree line, `├⊟` opened and `├⊞`
  folded, and the root's mark stands before it. A folded agent keeps its
  own figures, with 👶🏻 before its name counting every agent hidden under
  it; 👶🏻 is drawn on folded rows alone. An agent that starts under a
  folded row stays hidden and adds to its 👶🏻, and a row stays as it was
  left for the rest of the session.
- **`✅ N done`,** under 🧵 main, sums the subagents that finished this
  turn, which Claude Code's own panel drops after 30 seconds; it starts
  folded, and opened lists them.
- **The cap.** At most 6 running subagent rows by default. Past it, the
  later siblings under one parent fold into that parent's `… N more`,
  which sums them and starts folded; every shown row's parents stay.
- **The glyphs.** 🧵 marks the main thread, in the kind slot 🔍 🔩 📐 fill
  for agents; 🤖 keeps one job, the model having the floor, in the 🛫
  column and the first time gauge.
- **A click on a thread's label** switches the transcript to it, as
  Claude Code's tasks list does (`$.ui.view`); 🧵 main's goes back to the
  main conversation. There are no hotkeys: the numbers would move as
  threads come and go.

Drawn at 236 columns, with Marigold opened, then folded:

```text
Marigold opened
⊟ 🎮 📦 claude-code-usage-statusline 🌿 master 🔀 #38                                                                         💰 35                🧩▴2.7M ▾841k  🎯98٪  ⌛9.3h         🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀  🔋 3.8٪   🪫 8.45٪
├─ 🎤🟢 turn                                                                                                 🧬O⁵🏃  🛫 200   💰6.4   🧠-42k  -4٪  🧩▴525k ▾151k  🎯98٪  ⌛  5m         🤖⠶⠆ 🔧⠆⠀ 🚦⠀⠀  🔋 1.2٪   🪫 1.56٪
╰⊟ 🧵🟢 main  Checking the binary for subagentStatusLine, then the changelog for a hook that replaces it     🧬O⁵🏃  🤖   3m  💰 35   🧠115k  11٪  🧩▴2.7M ▾841k  🎯98٪  ⌛9.3h         🤖⠆⠀ 🔧⠄⠀ 🚦⠶⠄  🔋 3.8٪   🪫 8.45٪
   ├⊟ 🔍🟢 Marigold  Running the plugin tests after the wrapper Box fix, then the 29 suites                  🧬O⁵🏃  🔧  11m  💰0.1   🧠 32k  16٪  🧩▴ 14k ▾800   🎯93٪  ⌛ 12m ⛳ +50s 🤖⠄⠀ 🔧⠶⠦ 🚦⠀⠀  🔋  .02٪  🪫  .022٪  💾 +  9  -  4
   │  ├─ 🔩🟢 Fern  Reading spec/layout.jsonc for the rows table and the cells each row draws                🧬S⁵🐢  🤖 333   💰0.1   🧠 60k  30٪  🧩▴ 13k ▾1.3k  🎯97٪  ⌛6.7m         🤖⠶⠦ 🔧⠄⠀ 🚦⠀⠀  🔋  .01٪  🪫  .016٪  💾 + 41  - 12
   │  ├─ 🔩🟢 Rowan  Reading mod/src/grid.ts to see how a label runs over the blank columns                  🧬H⁵🐇  🔧  50s  💰0.0   🧠  9k   4٪  🧩▴1.1k ▾120   🎯89٪  ⌛ 1m          🤖⠄⠀ 🔧⠶⠀ 🚦⠀⠀  🔋  .00٪  🪫  .003٪
   │  ╰⊞ … 2 more                                                                                                    🏃   2   💰0.0                🧩▴2.4k ▾210   🎯88٪  ⌛20s          🤖⠄⠀ 🔧⠶⠀ 🚦⠀⠀  🔋  .00٪  🪫  .004٪
   ├─ 📐🟡 Thistle  Asking you which layout to build                                                         🧬O⁵🏃  🚦 4.7m  💰0.0   🧠 32k  16٪  🧩▴7.1k ▾400   🎯93٪  ⌛  5m         🤖⠄⠀ 🔧⠀⠀ 🚦⠶⠦  🔋  .01٪  🪫  .011٪
   ╰⊞ ✅ 3 done                                                                                                      ✅  42m  💰0.4                🧩▴ 61k ▾4.2k  🎯95٪  ⌛ 31m         🤖⠶⠆ 🔧⠶⠄ 🚦⠀⠀  🔋  .07٪  🪫  .081٪  💾 + 88  - 30

Marigold folded
⊟ 🎮 📦 claude-code-usage-statusline 🌿 master 🔀 #38                                                                         💰 35                🧩▴2.7M ▾841k  🎯98٪  ⌛9.3h         🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀  🔋 3.8٪   🪫 8.45٪
├─ 🎤🟢 turn                                                                                                 🧬O⁵🏃  🛫 200   💰6.4   🧠-42k  -4٪  🧩▴525k ▾151k  🎯98٪  ⌛  5m         🤖⠶⠆ 🔧⠆⠀ 🚦⠀⠀  🔋 1.2٪   🪫 1.56٪
╰⊟ 🧵🟢 main  Checking the binary for subagentStatusLine, then the changelog for a hook that replaces it     🧬O⁵🏃  🤖   3m  💰 35   🧠115k  11٪  🧩▴2.7M ▾841k  🎯98٪  ⌛9.3h         🤖⠆⠀ 🔧⠄⠀ 🚦⠶⠄  🔋 3.8٪   🪫 8.45٪
   ├⊞ 🔍🟢 👶🏻4 Marigold  Running the plugin tests after the wrapper Box fix, then the 29 suites            🧬O⁵🏃  🔧  11m  💰0.1   🧠 32k  16٪  🧩▴ 14k ▾800   🎯93٪  ⌛ 12m ⛳ +50s 🤖⠄⠀ 🔧⠶⠦ 🚦⠀⠀  🔋  .02٪  🪫  .022٪  💾 +  9  -  4
   ├─ 📐🟡 Thistle  Asking you which layout to build                                                         🧬O⁵🏃  🚦 4.7m  💰0.0   🧠 32k  16٪  🧩▴7.1k ▾400   🎯93٪  ⌛  5m         🤖⠄⠀ 🔧⠀⠀ 🚦⠶⠦  🔋  .01٪  🪫  .011٪
   ╰⊞ ✅ 3 done                                                                                                      ✅  42m  💰0.4                🧩▴ 61k ▾4.2k  🎯95٪  ⌛ 31m         🤖⠶⠆ 🔧⠶⠄ 🚦⠀⠀  🔋  .07٪  🪫  .081٪  💾 + 88  - 30
```

## Steps

1. **`OP1` Measure what the move would remove.** Done: see
   [Which entries reach each module](#which-entries-reach-each-module).
2. **`OP2` Remove the agent panel command.** Done: the Python has no
   `--mode subagent`, no `subagent` suite or goldens, no end-to-end
   payloads, no tools that drew or timed the command, no example
   `settings.json`, and no docs that name it. `prepare_subagent_tasks`,
   the sessions under `tests/fixtures/transcripts/subagent/` (the fold
   and calibration fixtures read them) and the render-level corpus in
   `tests/fixtures/panel/` stay until `OP5`, since the TypeScript
   renderer and folds are checked against them. The corpus is committed
   data: its inputs are read as they are and its rows drawn again.
3. **`OP3` The band's tree.** Done: [The band's tree](#the-bands-tree)
   above the prompt, the 🎮 root with the workspace, 🎤 the turn, 🧵
   main moved up from under the footer line, and the subagents under the
   thread that started each (`mod/src/band_tree.ts`); a
   `rows.subagents` row, live while a turn runs, and `subagent-rows`, the
   cap, in `spec/options.jsonc` and `mod/defaults/config.jsonc`. The mod
   prepares each agent's task from `$.agent.list()` and its agent fold
   as `prepare_subagent_tasks` does (`mod/src/subagent_tasks.ts`,
   `mod/hooks/subagents.ts`), its usage checked against `agent_usage_of`,
   and draws its cells with the renderer's. Each thread's progress update
   is the first line of the last text block in its transcript's tail.
   The agents' 📨 counts are 0 in the mod: the inbox fold reads with
   Node alone. Tests in `mod/test/band_tree.test.ts`, the rows' cases and
   `docs/layout.md`.
4. **`OP4` The mod's fold worker in TypeScript.** `transcripts.ts` folds
   large transcripts in Node in place of `python3 .../agent_lines.py`.
5. **`OP5` Remove the Python's Claude twins.** Delete the modules `OP1`
   found only Claude and the fold worker use, `--mode status` and
   `--mode cost` for Claude, their tests and their fixture generators,
   and move what the TypeScript's tests still need to Node or keep it as
   committed data.
6. **`OP6` 🧬 for the model cell.** `🤖O⁵🏃` becomes `🧬O⁵🏃` on every
   row and the receipt (`E_MOD` in `spec/layout.jsonc`), so 🤖 keeps one
   job. After `OP5` it touches the TypeScript and its cases alone.
7. **`OP7` The band's clicks.** A label's click switches the transcript
   to its thread; a row with children folds and opens, its fold kept in
   `$.state` by agent id; 📦 🌿 🔀 are links. Tests in `mod/mod-tests/`.

## What to watch

- **Codex users.** They keep the Python. A Codex-only install must not
  need Node, and a Claude-only one must not need Python.
- **The shared state files.** Until `OP5`, the Python's Codex side and
  the mod both read the `window-costs` cache (`spec/state.jsonc`); its
  format must not move.
- **The band's height.** Each running subagent adds a row above the
  prompt, up to the cap; `rows.subagents` can be hidden like any other
  row.

## Decided

1. **The subagents' figures go in the band above the prompt,** one row
   per running subagent, not in a pane, as
   [The band's tree](#the-bands-tree) draws them.
2. **The Python drops its Claude status line and cost receipt** with its
   other Claude modules at `OP5`; the mod is the way to see them.
3. **Codex stays in Python.** Porting `--agent codex` waits until someone
   asks for it.
