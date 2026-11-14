# One port: the agent panel drawn by the TypeScript

Approved to build. Its steps are `OP1` … `OP7` in [the schedule](_schedule.md);
its two open decisions are taken at `OP7`.

## Why

Most of the logic is written twice. Nineteen modules of
`coding_agent_usage_line/` have a twin in `mod/src/`, about 17,800 lines
of Python beside about 12,000 of TypeScript, and the two are held together
by fixtures the Python writes and goldens both sides are checked against.
Every change to what a row shows is made in both ports, in
`spec/layout.jsonc`, and in the fixtures and goldens of each: dropping one
glyph from the agent panel's rows touched 81 files.

The band, the footer rows and the receipt are already the mod's alone. The
Python's live job in Claude Code is now the agent panel
(`subagentStatusLine`), and the TypeScript already has every piece the
panel draws with (`claude_subagent_render.ts`, `cells.ts`, `grid.ts`) and
Node readers for the files it reads (`claude_records_node.ts`,
`sources_node.ts`, `claude_calib_node.ts`). What it lacks is the panel's
command: reading the payload on stdin, preparing each task, and printing
one JSON line per task.

## What the Python serves today

| Use                                   | Entry                                                     | Has a TypeScript twin                                 |
| ------------------------------------- | --------------------------------------------------------- | ----------------------------------------------------- |
| The agent panel                       | `coding-agent-usage-line.py --agent claude --mode subagent` | the rendering and readers; not the command           |
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

What it decides for `OP6` and `OP7`:

- **Codex keeps 14 modules, 7,288 lines:** `cli.py`, `codex.py`,
  `render.py`, `sources.py`, `config.py`, `options.py`, `options_spec.py`,
  `usage_report.py`, `models.py`, `state.py`, `state_spec.py`,
  `formatting.py`, `spec.py` and `spans.py`. `formatting.py` and `spec.py`
  are kept whole here but hold the Claude rows' glyphs and cells too, and
  `sources.py` holds the Claude Usage Tracker's adapter; each can shed its
  Claude parts at `OP7`.
- **Claude alone uses 7 modules, 6,410 lines:** `claude.py`,
  `claude_render.py`, `claude_subagent_render.py`, `claude_cost_render.py`,
  `grid.py`, `inbox_fold.py` and `claude_sources.py`. They go at `OP7`.
- **The fold worker also uses 3, 4,059 lines:** `claude_records.py`,
  `main_fold.py` and `agent_fold.py`. They go at `OP7` once `OP6` has
  moved the worker to Node.
- **No entry loads `credits.py`,** 69 lines: the 💳 row is the mod's, and
  only `tests/source-cache.py` imports it. It can go with its test now.
- **The tests:** 32 files load `formatting.py`, so the generators and
  checks that only test the Claude modules go with them at `OP7`, and the
  rest stay as Codex's.

## Target

- `subagentStatusLine` runs `node mod/src/panel.ts --mode subagent` (Node
  runs the TypeScript as it is, with its types stripped, as `npm test`
  already does). It takes the same flags and configuration files, and
  writes the same agent folds and caches under
  `~/.local/state/coding-agent-usage-line`.
- The mod's large folds use the same Node code through `process.run`,
  so the mod needs no Python either.
- The Python keeps what has no twin: Codex. Its Claude modules that only
  the panel, the status line and the cost receipt used are removed, with
  their tests, once nothing reads them.
- The TypeScript becomes the reference: the panel's goldens are kept and
  checked against `panel.ts`; the parity fixtures between the ports go.

## Steps

1. **`OP1` Measure what the move would remove.** Done: see
   [Which entries reach each module](#which-entries-reach-each-module).
   List, per Python module, which entries reach it: the panel, Codex, the
   mod's fold worker, the tests. That decides what the Python keeps after
   `OP6`, and whether Codex shares enough with Claude (`sources.py`,
   `formatting.py`, `config.py`) to keep those modules whole.
2. **`OP2` The panel's command in TypeScript.** `mod/src/panel.ts`: the
   port of `main_subagent`, `prepare_subagent_tasks` and
   `render_subagent`, over the Node readers, with the same options parser
   (`options_spec.ts`) and the same error rows.
3. **`OP3` Its goldens.** Run `tests/run-cases.py --suite subagent`
   against both commands, and add `panel.ts` to `tests/all.sh` as its own
   suite, so the two are seen to agree on every case before the switch.
4. **`OP4` Startup time.** The panel redraws every second per agent. Time
   `node panel.ts` against the Python on the largest fixture and on a live
   session. A first measurement, Node 26 against the system `python3`, on
   a loaded machine, 10 runs each: an empty `node -e 0` took 143 ms and
   importing `claude_subagent_render.ts` 267 ms, against 30 ms for an
   empty `python3` and 165 ms for the whole Python panel on an empty
   payload. So Node starts slower, and the type stripping of a dozen
   modules costs more again. Try a single bundled `.js` file, built by a
   generator step and committed, and Node's compile cache
   (`module.enableCompileCache()`), before the switch; the switch waits
   until `panel.ts` is no slower than the Python.
5. **`OP5` The switch.** `examples/claude/settings.json`, the README's
   install section and `docs/` name `panel.ts`; the README states the Node
   version needed in place of Python 3.9. The user changes
   `~/.claude/settings.json` themselves.
6. **`OP6` The mod's fold worker in TypeScript.** `transcripts.ts` spawns
   `node .../agent_lines.ts` in place of `python3 .../agent_lines.py`.
7. **`OP7` Remove the Python's Claude twins.** Delete the modules `OP1`
   found only the panel, the status line and the cost receipt use, their
   tests and their fixture generators, and move the generators the
   TypeScript's tests still need to Node or keep them as they are.

## What to watch

- **Node on the machine.** The Python needs only the standard library;
  the panel would need Node 23.6 or newer, where type stripping is on by
  default. Claude Code ships its own runtime, but `subagentStatusLine`
  runs a shell command, so the user's own Node is the one that runs.
- **Codex users.** They keep the Python. A Codex-only install must not
  need Node, and a Claude-only one must not need Python.
- **The shared state files.** The Python and the TypeScript both read and
  write the agent folds and the `window-costs` cache (`spec/state.jsonc`).
  During `OP3` to `OP5` both may run; the formats must not move.

## Open decisions

1. **Whether the Python keeps the Claude status line and cost receipt**
   (`--mode status` and `--mode cost`) for people who don't install the
   mod, or whether the mod becomes the only way to see them.
2. **Whether Codex moves too.** Porting `--agent codex` would retire the
   Python entirely, at the cost of a port nobody has asked for yet.
