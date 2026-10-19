# Redesign: one grid for all three readouts

A proposal, not built yet. Nothing here changes what the program draws today;
[Layout](../../docs/layout.md) is still the reference for that. This document collects
the design as it is decided, and `mod/tools/layout-mockup.ts` draws it.

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
| 💳 account | 📅 🕐, then the plan's two windows, each its share and when it resets, all on the label | the mod, in the band |
| 🎤 and the prompt | the turn | the mod, in the band, while the turn runs |
| 🤖💬 and the reply, or what it is doing | the main thread alone | the mod, in the band |
| 🎮 session, 📦 project, 🌿 branch, 📁 directory, 🔀 PR, 🎨 output style | the main thread and every agent, summed | the mod, in the band, while the turn runs |
| one per agent | that agent's life | `subagentStatusLine`, in the panel |
| 📊 🎤 and 📊 🎮 | the turn and the session as they stood when it ended | the mod, on the turn's closing line |

A row's label says which scope its figures count; the figures do not carry
the scope's glyph: the plan columns read 🔋 and 🪫 on every row.

The band draws 🎤 and 🎮 only while a turn runs, as its first two rows, so
they sit nearest the receipt they become (decided 2026-10-19). When it
ends, the receipt on the turn's closing line carries both, frozen, and the band drops to 💳
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
figure: the 💳 row has no figures at all, so its label has the whole row.
Labels therefore end at different points on different
rows; the figures never move. Which columns drop on a narrow terminal is
worked out without this extra room, so a label's spill never changes the
grid. Every
row's cells end five columns short of the terminal's right edge, the columns
Claude Code keeps for the band's `[-]` button, so all three readouts share one
right edge.

Two rows read differently:

- **🧠 on the 🎤 row** is how much the context grew in the turn, in tokens and
  points: `🧠 +34k +3٪`.
- **The 💳 row is all label** (decided 2026-10-19): the clock, then 💳, then
  each window's share and when it resets, `📅 2026-10-19  🕐 13:06:02  💳 🔋
  15٪ 🔜 6.7m  🪫 87٪ 🔜 1.8d`. It draws nothing in the plan columns, and
  both shares take three digits, so 🪫 reads `87٪` as 🔋 does.

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
| group | `plan` (🔋 🪫 🔜), `cost` (💰), `tokens` (🧩 🎯), `context` (🧠), `time` (⌛ ⛳ 🤖 🔧 🚦), `work` (💾), `state` (model, 🛫; on agent rows also `kids`, `compact`, `shells`, `monitors`, `inbox`: 👶🏻 🤏 💻 📡 📨), `chat` (`prompt`, `reply`, `doing`), `workspace` (📦 🌿 📁 🔀 🎨), `clock` (📅 🕐), `name` (`label`, `kind`, `receipt`: the row's name, an agent's kind, the receipt's 📊) |

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
  no receipt. Decided 2026-10-19: the desktop app is out of scope. The band
  and the start line use render sites it supports, but nothing is designed
  or checked for it.

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
`spec/layout.jsonc` beside 🔺 after a run of `tests/probe-advance.sh`.

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
- **One spec, generated into both languages.** The glyphs, the palette,
  the widths and cuts, and the terminal-profile rules are written once, in
  `spec/layout.jsonc`, and `tools/gen-spec.py` writes them out as
  `coding_agent_usage_line/spec.py` and `mod/src/spec.ts`, comments and all;
  `tests/formatting.py` fails when either is out of date. The
  cells' keys, `--hide` paths, drop order and label ranks join it when the
  new grid is built. The TypeScript side hardcodes none of them.
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

Decided 2026-10-19: the columns follow from the terminal's width and the
`--hide` setting alone.
The chrome is kept for two levels of nesting whether any agent runs or not,
and a deeper agent row cuts its own label instead. The mod and each panel
row's process then reach the same columns without talking to each other, and
no column moves when an agent starts. `--grid rows` in the mockup draws the
alternative, columns from the rows drawn: at 125 columns, a nested agent
appearing there drops 🤖 🔧 🚦 from every row and moves every label.

### Where the plan figures come from

Decided 2026-10-19: the band's 🔋 and 🪫 read the usage source the status
line is configured with (`--usage-source`, `claude-usage-tracker` here), not
`$.session.usage()`, which gave a weekly share a point off (34 against 33).
The band and the status line run side by side until they agree, and they can
only agree reading one source. The TypeScript side gets its own reader, a
port of the parts of `sources.py` the configured sources need, with the
same version-1 reading as its output and shared cases pinning it.

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
   shared cases before the next, and the usage-source reader with it.
   Status 2026-10-19: `claude_records.ts` and `models.ts` (1,417 cases),
   `sources.ts` and `claude_sources.ts` (392) and `claude_calib.ts`, the
   calibration, window shares and the figures' `turn_accounting` and
   `cost_accounting` from `claude.py` (1,179), pass; `py.ts` holds the
   Python semantics they share. Left: the glue in `claude.py` that strings
   them together per render (`_with_shares`, `cost_figures`, `window_for`
   and the published context window), which the mod's handlers take on in
   step 5. `agent_window_shares` stays Python's, with the agent panel.
4. **The cells and the layout in TypeScript,** against the shared cases.
   Decided 2026-10-19: today's cells are ported as they are first, against
   the 228 goldens and the agent panel's own cases, so the port is checked
   byte for byte. The redesigned grid is then built in TypeScript, and the
   Python cells, which the agent panel keeps, are brought to it after.
   Status 2026-10-19: today's cells are ported. `formatting.ts` and
   `spans.ts` (35,956 cases), `claude_render.ts` and `figures.ts` (the 141
   status goldens and 3,958 cell cases), `claude_cost_render.ts` and
   `claude_cost.ts` (the 87 cost goldens and 256 receipt cases), and
   `claude_subagent_render.ts` (the panel's 242 render cases) match the
   Python byte for byte. The redesigned grid is built too: `grid.ts` lays
   out rows given as plain data, a label's pieces and the cells as spans,
   and `mod/tools/layout-mockup.ts` draws the mockup with it, the Python
   mockup's output byte for byte before that was deleted. Its cases,
   `tests/fixtures/grid/`, are written by the TypeScript
   (`mod/tools/gen-grid-cases.ts`), the first fixtures that are, and
   `grid.test.ts` fails when they are not what the generator writes. The
   Python grid engine, `coding_agent_usage_line/grid.py`, is a port of
   `grid.ts` function for function and passes every one of those cases under
   each profile (`tests/grid.py`, 15,519 checks). The row builders are
   built on it: `band.ts` draws a status document as the band's rows and
   `receipt.ts` a cost document as the receipt and a status document as
   the 🔻 line, through the cells the mockup now shares, `cells.ts`; their
   cases, `tests/fixtures/rows/`, are written by `mod/tools/gen-row-cases.ts`
   from every committed figures document, and `node
   mod/tools/draw-figures.ts` draws one in a terminal. The agent panel's
   rows are on it too, in both languages: each is a grid row of scope
   `agent`, laid out over templates of every scope's row for the terminal's width
   (the payload's `columns` plus `PANEL_COLUMNS_SHORT`), with the chrome
   counted and not printed, no copy of the panel's tree and no task id; its
   45 goldens and 275 render cases moved with it, and `--hide` reaches it.
5. **The mod,** from the `usage-band` scaffold: refreshes, receipts kept in
   `$.store` so a resumed transcript still shows them, and the 🔻 line.
   Status 2026-10-19: built and tested in the harness, not yet run in a
   live session. `mod/` is the plugin; its hooks import `src/`, whose
   file reads moved to `src/*_node.ts` so the rest loads in the mod's
   runtime. `src/claude.ts` ports the glue (`status_figures`,
   `cost_figures`, `_with_shares`, `window_for`, `ctx_window_for`,
   `detect_git`'s reading, `session_rate` in memory), and every committed
   status and cost document is built again from its inputs, field for
   field (`test/claude.test.ts`, with `tests/fixtures/gen/claude.py`'s
   cases for the small parts). `mod/hooks/edges.ts` reads through `$`:
   the transcript and the agent files through `$.fs`, a file over 4 MiB
   in pieces through the shell; the tracker and git through
   `$.process.run`; the clock through `$.clock`. The calibration's scan
   runs behind the render, so the shares are blank until the first one
   lands. The published context window is the band's last document's,
   and the agent offsets are read from the Python Stop hook's file and
   not written. `mod/mod-tests/` checks each drawn place against the
   `src/` functions over the same fixture bytes (`npm run test:plugin`;
   CI has no `claude` to run it).
6. **The switch.** The band runs beside the status line until the two agree;
   then the status line leaves `settings.json` and
   [Layout](../../docs/layout.md) is rewritten.

### What the accounting port has to mirror

`claude_records.py` (about 2,500 lines) and the calibration in `claude.py`:
payload fields, request deduplication, prices, turn classification and
folding, tool spans and clocks, agent files and the inbox, and the window
shares with their calibration cache. The I/O in them, file reads that seek
to byte offsets, recursive globs, atomic cache writes, the clock and the
poll in `read_turns_settled`, moves to the mod's edges; the rest ports as
pure functions.

What does not carry over by itself, so each needs a decision written once
and a shared case that pins it:

- **Rounding.** Python's `round` rounds half to even; `Math.round` rounds
  half up. The share percentages use it.
- **Time.** The Python side uses naive local datetimes and `strptime`;
  TypeScript has neither, so the port works in epochs throughout.
- **Records.** `NamedTuple`s compare by value (`lim == NO_LIMITS`); the port
  uses readonly records and an explicit equality.
- **Keys.** Tuple keys in sets and dicts deduplicate in Python; a JavaScript
  `Set` of arrays does not, so the port joins keys into strings.
- **Numbers.** `_num` prints the way `jq -r` does, which leans on Python's
  int/float split.
- **Bytes.** Marks are found by byte substring and agent files are read from
  byte offsets; the port reads `Uint8Array`s, not decoded strings.
- **Cache keys.** `sha256` digests of the package's own source key the
  caches; the TypeScript caches are keyed apart, by the mod's version.

### What the layout spec holds

Decided 2026-10-19: `spec/layout.jsonc` holds 172 constants, each beside
the comment that explains it: the glyphs, the colours as `rgb(…)`, the
widths and cuts, the wide-character table, `term_profile`'s rules, the
profiles `_PAD` pads, each profile's width overrides, and the defaults the
two switches rebind. `tools/gen-spec.py` writes them out as Python literals
in `spec.py`, which `formatting.py` star-imports, and as TypeScript
constants in `mod/src/spec.ts`, colours as hex. The JSONC has comments, so
the explanations moved with the values, and both languages still read a
literal beside its name. Values computed at import (the `S_*` forms,
`RIGHT_GRID`) are rules, and each language computes them.

Done 2026-10-19: the grid's rules joined it, 182 constants now. The grid's
constants (`RIGHT_EDGE`, `LABEL_MIN`, `PANEL_CHROME`,
`PANEL_COLUMNS_SHORT`, `CHROME_DEPTH`), 🔻 as `E_TURN_AHEAD` beside 🔺, the
scopes (`GRID_SCOPES`), the `--hide` groups and their metrics
(`HIDE_GROUPS`, with `name` for the label's own parts), each column's key,
`--hide` path, width and gap (`GRID_CELLS`) and the order columns drop in
(`DROP_ORDER`). A column's
width is a number where it is fixed and otherwise names its rule (`A_CTX_W`,
`COST_W`, …), since `_PAD` and the marks' spacing move it; each language
computes the rules. The label pieces' drop ranks stay with the rows that
carry them: a rank belongs to a row's own label, not to a column.

Still to come: each glyph by code
point; each colour as its RGB triple and the cut-offs that dim it (`mag_dim`,
`cache_color`). Three things vary at run time and go in the spec as rules,
not numbers:

- **The terminal profile.** `_PAD` widens 🧩, 🧠 and 💰 by one column on
  iTerm and tmux, so three cells are one column wider there. The mod reads
  the profile from the environment it runs in, as `term_profile` does.
- **Subscript decimals.** `set_subscript_decimals` changes the digits in six
  cells but, by design, never their widths.
- **Colours by value.** Dim under a magnitude cut, the cache tiers, a late
  ⛳ in amber or red.

Glyphs on these rows not yet measured by `tests/probe-advance.sh`: ▴ and ▾,
the superscript digits in the model cell (¹ ² ³ ⁴ are East Asian Ambiguous,
so a terminal may draw them two wide), and 🔻.

### What the cells port has to change

The cells the band, receipt and panel draw live in `claude_render.py`,
`claude_subagent_render.py`, `claude_cost_render.py` and the number formats
in `formatting.py`. Moving them to spans touches:

- **About 60 places that build escape codes inline** (22 in the panel's
  renderer, 33 in the status line's, and `mag_dim`, `reset_dim` and
  `cache_color`, which return colour prefixes), and about 8 that measure a
  drawn string through `strip_ansi`. With spans, a width is the sum of the
  spans' text widths, and the `F_*` constants become a colour map.
  Done 2026-10-19: `spans.py` holds the `Span` record (text, a colour
  key naming an `F_*` constant, dim, bold and a `B_*` background), `width`
  and `join`. Every cell in `claude_render.py` and
  `claude_subagent_render.py`, the receipt's labels and tags in
  `claude_cost_render.py`, and `pad_val`, `seg`, `pair`, `grid_row`,
  `seg_gap`, `mag_dim` (now a bool), `reset_dim` (a bool) and `cache_color`
  (a style span) work in spans, and the strip_ansi measurements are span
  widths. `join` writes escapes only where a line is printed:
  `render_status`, `render_task_rows` and the receipt's `render_cost_line`.
  Three habits of the old output are kept by `join` itself: a chat row's
  prefix runs unreset into its body on the dark band, a grid row's closing
  reset, and, asked for with `runs`, the receipt's runs of bare colours
  (▴ then ▾) under one reset. The goldens did not move, and every renderer
  call the panel and rate suites make returns the bytes it did before.
  The receipt's metric groups (`cost_group` and `cost_totals_group` in
  `claude.py`) return spans too, so `Ink` is gone, and `place` and
  `render_cost_line` take and return spans. Only the Codex renderer in
  `render.py` still draws strings.
- **State read at import.** `term_profile` reads `TMUX`,
  `TERMINAL_EMULATOR` and `TERM_PROGRAM` when the module loads, and the
  width table and every `S_*` mark are fixed from it then.
  `set_mark_spacing` and `set_subscript_decimals` rebind module globals
  afterwards. In both languages these become one settings value passed to
  the renderers, not globals.
- **The clock.** Seven helpers fall back to `time.time()` or
  `time.localtime()` when no `now` is passed, and many callers pass none.
  Every renderer takes `now`; only the edge reads the clock.

### The shared test cases

The golden inputs are committed data now, the first part of build step 2:
`tests/fixtures/gen/` writes the payloads, transcripts, environments and
`cases.json`, and `tests/run-cases.py` replays all 228 cases against the
unchanged goldens. `golden.sh` and `golden-cost.sh` are wrappers around it,
and `pin-env.sh` is gone.

Each case is split in two now as well, so the accounting and the cells can be
checked apart. `claude.py` runs each readout in two stages:
`status_figures` and `cost_figures` read the inputs and return a figures
document, and `render_status_figures` and `render_cost_figures` draw one and
read nothing else; the live path goes through the document too.
`run-cases.py` checks every case three ways: the whole run against the
golden, the document it wrote against `figures/<suite>/<id>.json`, and that
committed document alone, drawn with `--from-figures`, against the golden
again. The schema is in [tests/README.md](../../tests/README.md#figures).

```
tests/fixtures/
  cases.json                    each case: id, suite, input, cols, env, flags  (done)
  env/<name>.json               clock, zone, locale, terminal, usage source,
                                calibration, tracker store, repo               (done)
  transcripts/<suite>/…         session JSONL, agent files and sidecars        (done)
  payloads/status/<name>.json   with ${HOME} and ${FIXTURES} placeholders      (done)
  figures/<suite>/<id>.json     inputs in, figures out; and figures in for
                                tests/golden/<suite>/<id>.txt                  (done)
  gen/*.py                      the generators, writing the above              (done)
```

The figures stage of the cost line is whole too: the document carries each
turn's and the session's cost and shares as `accounting`, and the cost cells
read them instead of working them out while drawing. The render stage puts
back only the clock's zone; it no longer restores the plan reading into
`limits_snapshot`, and the totals row takes its 💳 percentages from the
document's `usage.plan`. With that, build step 2 is done.

The cases of one suite share one state directory in the order listed, as
the shell suites did: a payload with `rate_limits` writes the cache a later
payload without them reads. The TypeScript runner has to keep the order, or
the cases have to stop depending on it.

- **Figures are canonical JSON:** sorted keys, numbers exact (the shortest
  decimal that reads back as the same double, positional, a whole one as an
  integer), null for missing, times as epochs. That is the contract between
  the two languages. Nothing is rounded, so the port sums in Python's order.
- **The drawn rows stay `.txt` with escape codes,** so the 141 status and 87
  cost goldens in `tests/golden/` move rather than being recorded again; the
  TypeScript runner joins its spans into escape codes to compare.
- **Only Python regenerates** at first (`--regen`, then reading the diff);
  the TypeScript runner only compares.
- **The existing figures-to-rows test,** `claude-subagent-render.py`, is
  already the second stage's shape.

### Where each row's figures come from

Audited 2026-10-19, for the grid to be drawn from the figures documents and
not from today's cells. **S** is the status document (`status_figures`), what
the band's rows read while a turn runs; **C** is the cost document
(`cost_figures`), what the receipt reads when it ends. *Added* marks what
schemas 2 and 3 brought in, and **D***n* the decision below that settled the
cell. **Mod** is a figure the mod works out or keeps itself, in step 5, from
the documents it has been given; nothing in a document stands for it. A figure
"at render" is worked out from the document's own fields by today's cells, as
`cost_group` weighs the 🧩 tokens; nothing there reads outside the document.

| Column | 🎤 (S) | 🤖💬 (S) | 🎮 (S) | 📊 🎤 (C) | 📊 🎮 (C) |
|---|---|---|---|---|---|
| model | | `payload.model`, `model_id`, `effort` | | | |
| 🛫 | | **Mod**: the rise in `transcript.own_tok_up + own_tok_down` between successive documents, over their `clock.now` (D1) | | | |
| 💰 | `accounting.open_turn.cost_usd` *added* (D8) | `accounting.own.cost_usd` *added*, which is `transcript.own_usd`, compactions included and marked by `own_est` (D2) | `accounting.session.cost_usd` *added* (D4) | `accounting.turns[i].cost_usd` | `accounting.session.cost_usd` |
| 🧠 | `open_turn.dctx` *added*, points over `context_window` at render (D8) | `transcript.ctx_tokens`, `ctx_est`, `context_window` | | `turns[i].dctx` over `context_window` | |
| 🧩 ▴ ▾ | `open_turn` fresh, cache write, cache read, out *added*, weighed at render (D8) | `transcript.own_tok_up`, `own_tok_down` *added* | `transcript.tok_up`, `tok_down` | `turns[i]`, weighed at render | the turns summed at render |
| 🎯 | `open_turn`'s tokens at render *added* (D8) | `transcript.own_cache_pct` *added* | `transcript.cache_pct` | `turns[i]` at render | the turns at render |
| ⌛ | `open_turn.dur_s` *added* (D8) | `transcript.busy_s`, `start_s`, `clock.now` | `clock.now` less `accounting.session.start_s` *added* (D5) | `turns[i].dur_s` | `clock.now` less `accounting.session.start_s` *added* (D5) |
| ⛳ | `transcript.eta`, `agent_etas` (the open turn's, `inherit_eta`) | the same | | `turns[i].eta` *added*, the last the turn reported (D6) | |
| 🤖 🔧 🚦 | `accounting.open_turn.model_s`, `tool_s`, `blocked_s` *added* (D8) | `transcript.busy_s`, `tool_s`, `blocked_s`, `start_s` | `accounting.session.*` *added*, drawn as proportions (D5) | `accounting.turns[i].*` *added* (today `turn_times` at render) | `accounting.session.*` *added*, as proportions (D5) |
| 🔋 🪫 | `accounting.open_turn.sess_share`, `week_share` *added* (D8); `limits.session_turn`, `weekly_turn` round `accounting.turn`'s | `accounting.own.sess_share`, `week_share` *added*, over `transcript.own_parts` (D2, D3) | `accounting.session.*_share` *added*; `limits.session_share`, `weekly_share` round them | `accounting.turns[i].*_share` | `accounting.session.*_share` |
| 💾 | `accounting.open_turn.lines_added`, `lines_removed` *added* (D8) | `transcript.lines_added`, `lines_removed` *added* | `accounting.session.lines_*` *added* (D4) | `accounting.turns[i].lines_*` *added* | `accounting.session.lines_*` *added* (D4) |

The 💳 row's 🔋 and 🪫 are `limits.session_pct` and `weekly_pct` in S and
`usage.plan.session_pct` and `weekly_pct` in C, and the 📅 🕐 on every row
that draws them are `clock.now` in `clock.tz`. The labels and heads:

| Part | Source |
|---|---|
| 💳 🔜 resets | `limits.session_reset`, `weekly_reset` (S); `usage.plan.*_resets_at` (C) |
| 🎤 prompt | `open_turn.text` *added*, the turn's opener, a queued message or a notification included (D8); `transcript.user_text` is the last prompt typed |
| 🤖💬 reply, activity | `transcript.asst_text`; `main_doing` off `tool_at`, `wait_at`, `idle_at`, `last_seen`, `shells`, `monitors`, `queued` |
| 🎮 📦 🌿 📁 🔀 🎨 | `git.main_root` or `toplevel` and `payload.project_dir`; `git.branch`; `payload.current_dir`; `payload.pr_number`; `payload.output_style` |
| 📊 🎤 prompt | `turns[i].text` |
| 📊 🎮 📦 🌿 | **Mod**: the band's last status document's `git` and `payload`, kept until the receipt is drawn (D7) |
| receipt head 🔖 # 📅 🕐 | `turns[i].prompt_id` and `turn_index`; `clock.now`, when the Stop ran |
| start line 🔖 # 📅 🕐 | `transcript.prompt_id` and `turn_index` *added*, the turn opened last even before it calls; `transcript.turn_s`, its prompt's stamp |

`open_turn` is the turn opened last, calls or not (`open_turn` in
`claude_records.py`): not a compaction and not a late agent turn. `turn`, the
last turn with main-thread calls that is not a compaction, `_with_shares'`
pick and the receipt's, stays in S beside it, with its accounting, and
`limits` still rounds that turn's shares for today's status line. An auto
compaction in the middle of a turn opens a turn of its own in `read_turns`,
and the requests after it are filed there, so either pick shows the prompt's
figures only up to the compaction.

The agent rows stay Python's and are in no figures document: the panel's
`AgentUsage` gives 🧩, 🎯, 🧠 with the payload's window, 💰 and its `parts` for
🔋 🪫 (`agent_window_shares`), model and effort, 💾 over the agent's whole
life (`agent_diff`), 🤖 🔧 off `agent_clock` and 🚦 off its waiting spans, ⛳
off its ETA; 🛫 is `token_rate` over the payload's samples. Their shared
cases are `tests/fixtures/panel/`.

What schemas 2 and 3 count, and how:

- **💾 per turn** is `diff_lines` over the turn's tool results: the main
  thread's in the turn, and each agent's filed with the billed request that
  read the result, the way `split_clock` files its seconds; a request dropped
  as a duplicate hands its lines on to the next one kept. Lines written after
  an agent's last request are in no turn, as its time is not.
- **🤖💬's own** figures are the main transcript's requests and tool results
  alone, before the agents' are added. Its tokens leave out the compactions,
  which bill through no request; its dollars charge them to it (D2).
- **The own parts** (`transcript.own_parts`) are `(epoch, dollars)` for each
  own request and each compaction, gathered in the pass that finds the
  requests. A compaction is priced as `read_turns` prices its turn, preTokens
  at the cache-read rate and the summary's estimated output, and stamped
  where that turn is: at a `/compact` prompt that has made no call, else at
  the boundary, so it falls in the same window on both rows. `parts_shares`
  splits them at each window's start as `session_shares` splits the turns,
  and leaves a window with no start null.
- **The 🎮 split** in `accounting.session` is each turn's `turn_times` summed:
  agent-seconds, which can outrun the wall clock, and only the main thread's
  🚦.
- **A turn's ⛳** (`Turn.eta`) is the last ETA the main thread reported in
  it, `(epoch, seconds)`, read off the assistant records as `live_eta` reads
  them, before the request dedupe so a report on a later record of one
  message counts. The answer ending does not clear it, and a 0s sign-off is a
  report like any other.

#### Decided 2026-10-19

1. **🛫 on the 🤖💬 row** is the main thread's own rate, which the mod works
   out in memory from successive status documents' `transcript.own_tok_up +
   own_tok_down` against their `clock.now`, with no state file. Every
   document carries the counts already; the rate is step 5's.
   `session_rate` and its state file stay with today's status line.
2. **The main thread's own 💰, 🔋 and 🪫 include its compactions,** which
   compact its window. `own_usd` counts them, and `own_est` marks it an
   estimate, as `ctx_est` marks 🧠: a summary's output is estimated from its
   length. The tokens leave them out, as they leave out every compaction.
3. **The own 🔋 🪫 split at a window boundary off `own_parts`,** a new
   `Transcript` field, and the accounting works out the shares as it does
   the turn's and the session's: `accounting.own` in S, by `own_accounting`
   and `parts_shares`.
4. **🎮 💰 and 💾 are the accounting's** in the band and on the receipt, so
   🎮 is the column's sum and the two readouts agree. Claude Code's
   `payload.cost_usd` and lines are shown by `--diagnose` on the status
   line beside ours (`cost_usd`, `lines`, `claude_cost_usd`,
   `claude_lines`), as a check; [Options](../../docs/options.md) has the
   line. Whether Claude Code's lines count its agents' is still not known,
   and the check is where to find out.
5. **🎮 ⌛ is the session's age** on the wall clock, as today's ⌛, from
   `accounting.session.start_s`, the earliest turn's stamp, to `clock.now`;
   the band and the receipt read the same start, so the two agree.
   `transcript.start_s`, the first stamped record of any kind, stays the
   🤖💬 row's. The 🤖 🔧 🚦 split is `accounting.session`'s agent-seconds,
   with 🚦 the main thread's alone. It is drawn as proportions of itself,
   the bars of today's split, and need not add up to ⌛: agents running side
   by side put more seconds in it than the session has been open.
6. **⛳ on the receipt** is the last ETA the turn reported, `Turn.eta`, kept
   after the turn ends. Comparing it with the turn's end, how far off it
   was, is left to the cell.
7. **The receipt's 📦 🌿** come from the band's last status document, which
   the mod keeps; `cost_figures` runs no git. Step 5's.
8. **The running 🎤 row is the turn opened last,** calls or not, so a fresh
   turn reads zeros, and its prompt is that turn's opener, `turn.text`,
   queued messages and notifications included. S carries it as `open_turn`
   with `accounting.open_turn`; `turn` and its accounting stay for the
   receipt's pick and today's status line, whose rows did not move.

## The whole screen

After the turn, `node mod/tools/layout-mockup.ts --cols 150 --plain`, made-up
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
  -- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle)

  ⏺ main
  ◯ 🔩🟢 Port renderer  Ed…  🤖O⁵🏃  💰 0.4   🧠 124k  12٪  🧩 ▴ 66k ▾3.6k  🎯93٪  ⌛ 14m ⛳   3m 🤖⠦⠀ 🔧⠄⠀ 🚦⠶⠀  🔋.08٪  🪫.100٪  💾 +  48 -   9
    ◯ 🔍🟢 Find callers of…  🤖S⁵🚶  💰 0.1   🧠  48k  24٪  🧩 ▴ 24k ▾  1k  🎯90٪  ⌛8.3m ⛳ 2.5m 🤖⠆⠀ 🔧⠀⠀ 🚦⠶⠆  🔋.03٪  🪫.040٪  💾 +   0 -   0
```

The panel's `⏺ main` row and the `  ◯ ` before each agent row are Claude
Code's own; no hook reaches the main row. Measured with a throwaway mod on
2026-10-19 in a 160-column terminal:

- **The band** is given 155 columns, and `[-]` takes the other 5 on its first
  row.
- **The panel** sits under the mode line, after a blank line. Its chrome is
  `  ◯ `, four columns, and its payload's `columns` is the terminal's width
  less 6 (154). A panel row's figures line up with the band's only when they
  are laid out for the terminal's width, not the payload's.
- **The columns line up on screen.** With the panel laid out for the
  terminal's width, the band's, the receipt's and the panel's 💰, 🧠, 🧩 and
  💾 fell in the same screen columns, checked by eye in tmux inside Ghostty
  (the `tmux` profile), in bare Ghostty (the `unknown` profile, no `_PAD`)
  and in tmux inside JediTerm (the `tmux` profile again). In all three the
  band ended before `[-]`. Bare JediTerm (the `jediterm` profile) looked
  right too. The panel there showed only in a tall pane, so a short pane
  can hide it. The ruler, the mockup's band, the receipt and the panel were
  all on screen together. Every row
  carries the same glyphs before each of those columns, so a width the
  profile gets wrong shifts all rows alike; only the band's right edge
  against `[-]` shows it.
- **A nested row's chrome** was not seen; two more blanks per level is a
  guess.
- **The closing line** is a full-width row: text set beside Claude Code's own
  lands at the right edge, so the mod draws the whole line, `✻ Baked for 1m
  17s · 🔺🔖 …`, and loses Claude Code's `done` time unless it keeps its own.

### Rerunning the alignment test

The probe is in `tools/align-probe/`:

- **`mod/`** is a throwaway mod. Its `AbovePrompt` hook draws a ruler and the
  mockup's band rows. Its `TurnDuration` hook draws the whole closing line
  with the receipt rows under it. Its `UserMessage` hook adds a dim 🔻 line
  under the prompt. It runs `mod/tools/layout-mockup.ts` from the usual checkout
  path.
- **`align-panel.py`** is a `subagentStatusLine` command. While
  `align-probe.on` (git-ignored) sits beside it, each task's row is the
  mockup's first agent row, laid out for the payload's `columns` plus 6.
  Without that file it runs the real subagent mode.

To run it:

1. Copy `mod/` into `~/.claude/dev-mods/<session id>/align-probe/`.
2. Point `subagentStatusLine.command` in `~/.claude/settings.json` at
   `/usr/bin/python3 <repo>/tools/align-probe/align-panel.py`.
3. `touch tools/align-probe/align-probe.on`.
4. Start Claude Code in the terminal under test, `/reload-plugins`, send a
   prompt, then ask for panel agents that each run a 100-second background
   `sleep`.
5. Check by eye that 💰, 🧠, 🧩 and 💾 fall in the same screen columns in the
   band, the receipt and the panel, and that the band ends before `[-]`.

To clean up, set `subagentStatusLine.command` back to
`<repo>/coding-agent-usage-line.py --agent claude --mode subagent
--mark-spacing --usage-source claude-usage-tracker`, delete
`align-probe.on`, and delete the dev mod.

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
