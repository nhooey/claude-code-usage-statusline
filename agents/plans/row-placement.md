# Row placement: each row where it reads best

Approved to build, its nine decisions taken (see [Decided](#decided)).
Its steps are `RP1` … `RP8` in [the schedule](_schedule.md).

## Why

Today one setting, `live-place`, puts every live row of the mod in one
place: all under Claude Code's footer line (`"footer"`, the default) or
all above the prompt (`"above"`). The user wants each row where it reads
best:

- 🎤, the turn, above the prompt, as the first row of the band Claude Code
  can collapse with its `[-]`. When the turn ends it becomes the receipt,
  stamped as the turn's closing line, in nearly the same place on screen.
- 🎮, the session, above the prompt too, under 🎤, kept between turns.
- 💳, the account, as a row of its own under the footer line, holding
  everything about where the session works: 📦 🌿 📁 🔀 🎨.
- 🤖, the main thread, as the lowest row the mod can draw, just over
  Claude Code's agent panel, whose rows it is compared with.

It also removes the prompt's text from 🎤 and the reply's text from 🤖,
the code that draws them included, and leaves 🤖 and 🎮 out of the
receipt by default, since both are live on screen.

## The layout

### Today

With the user's file (`rows` with 🤖 and 🎮 kept and all three stamped,
`account-place` `"tail"`, the workspace's 📦 🌿 hidden on 💳):

```
  transcript … reply
                                                              (blank row)
  🎤 Why does the elapsed row…   cells …                      ← the receipt,
  🤖 Two figures, because one…   cells …                        dim, once the
  🎮 📦repo 🌿main               cells …                        turn has ended
                                                              (blank row)
🔺🔖 8f37748e #12  📅 2026-08-16  🕐 02:23:20
╭───────────────────────────────────────────────────────────────────────────╮
│ > prompt input                                                            │
╰───────────────────────────────────────────────────────────────────────────╯
  -- INSERT -- ⏵⏵ auto mode on · ⠀⠀⠀📁~/git/📦/mod ⠀💳 🪫 87٪ 🔜 1.9d ⠀📅 … 🕐 …
                                                              (blank row)
  🎤 Why does the elapsed row…   cells …   ← while a turn runs
  🤖 Two figures, because one…   cells …   ← kept
  🎮 📦repo 🌿main  📁~/git/📦…  cells …   ← kept
                                                              (blank row)
⏺ main
  ◯ ✳🔍🟢 Marigold  Running t…   cells …   ← the agent panel, the Python's
```

Every row ends 2 columns short of the edge (`right-edge`, derived from
`live-place`), and the rows under the footer line start 2 columns in
(`hint-inset`).

### New

```
  transcript … reply
                                                              (blank row)
  🎤                             cells …   ← the receipt: 🎤 alone, dim,
                                                              (blank row)
🔺🔖 8f37748e #12  📅 2026-08-16  🕐 02:23:20     and its tag line
  🎤                             cells …     [-]  ← AbovePrompt, while a turn runs
  🎮                             cells …          ← AbovePrompt, kept
╭───────────────────────────────────────────────────────────────────────────╮
│ > prompt input                                                            │
╰───────────────────────────────────────────────────────────────────────────╯
  -- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle)
                                                              (blank row)
  💳 🪫 87٪ 🔜 1.9d  📦repo 🌿main  📁~/git/📦/mod  🔀#12  🎨Explanatory   📅 … 🕐 …
  🤖 📨2                         cells …          ← PromptHint, kept
                                                              (blank row)
⏺ main
  ◯ ✳🔍🟢 Marigold  Running t…   cells …          ← the agent panel
```

- While a turn runs the band above the prompt is 🎤 then 🎮, and Claude
  Code's `[-]` stands on 🎤's row. Once the receipt is stamped (and
  `receiptHoldMs` has passed), 🎤 leaves the band and its frozen copy is
  the receipt just above; the band is 🎮 alone, `[-]` on its row.
- Every row, above and below the prompt, and the receipt, starts at one
  column and ends at one column, so a figure on 🎮 stands over the same
  figure on 🤖 and on the panel's rows (see [One grid](#one-grid-above-and-below)).
- 🎤's, 🤖's and 🎮's labels are their marks alone (🤖 keeps its 📨
  count), drawn flush right against the first column, and no row takes a
  press; the receipt's 🔖 tag line ties it to its prompt's 🔻🔖.

## The configuration

### The shape

A third field in each row of the `rows` table, `place`, and `live-place`
retired ([Decided](#decided), 1). The defaults, in
`mod/defaults/config.jsonc`:

```jsonc
  // Each row the mod draws.  place: "above", in the band above the
  // prompt, or "footer", under Claude Code's footer line; live: "never",
  // "running" (while a turn runs) or "always"; transcript: whether a
  // turn's end stamps it into the transcript.  A file may set any one
  // field; the rest stay.
  "rows": {
    // 🎤 drawn above the prompt while a turn runs, then left to the
    // receipt stamped in the transcript just above it.
    "turn":    {"place": "above",  "live": "running", "transcript": true},
    // 🤖 under the footer line, just over the agent panel, kept.
    "agent":   {"place": "footer", "live": "always",  "transcript": false},
    // 🎮 above the prompt, under 🎤, kept.
    "session": {"place": "above",  "live": "always",  "transcript": false},
    // The 🔻🔖 line under the prompt and the receipt's 🔺🔖 line; its
    // place is always "footer" (it has no live row).
    "tag":     {"place": "footer", "live": "never",   "transcript": true},
    // The 💳 account; its transcript is always false.
    "account": {"place": "footer", "live": "always",  "transcript": false}
  },
  // Where the 💳 account is drawn under the footer line: "row", a row of
  // its own, or "tail", at the footer line's right end, plain and dim.
  "account-place": "row",
  // Columns each agent-panel row leaves blank at the right edge.  null
  // follows rows.*.place: 5 when any row drawn live is "above", where
  // Claude Code's [-] stands, else 2.
  "right-edge": null,
```

- **`place`** is an enum, `"above"` or `"footer"`, on every row; the spec
  carries `"fixed": ["tag"]` for it, as `transcript` carries
  `["account"]`, so a file that sets `rows.tag.place` is warned about.
- **The order** in each place is one order, whatever the places:
  💳 `account`, 🎤 `turn`, 🤖 `agent`, 🎮 `session`. Under the footer line
  that gives 💳 then 🤖; above the prompt 🎤 then 🎮.
- **`live-place`** leaves the spec and the defaults file. A user or project
  file that still sets it gets the unknown-key warning, as any unknown key
  does.
- **`account-place`** keeps both values; its default becomes `"row"`
  ([Decided](#decided), 4). `"tail"` ignores `rows.account.place`.
- **`right-edge`** is derived from the rows, not from one option: `"above"`
  when any row whose `live` is not `"never"` has `place` `"above"`, else
  `"footer"`, through the same map, `{"footer": 2, "above": 5}`. The spec's
  `derived` gains a form for this: `{"from": "rows", "field": "place",
  "any": "above", "map": {…}}`, held by `gen-spec.py` as the one-option
  form is.
- **The receipt switch** is the one that exists: `rows.agent.transcript`
  and `rows.session.transcript`, `false` by default, put 🤖 and 🎮 back in
  the receipt. Nothing new is needed.

### What the user's file does after it

`~/.config/coding-agent-usage-line/config.jsonc` (read, not written by
this plan) sets `rows.agent.transcript` and `rows.session.transcript` to
`true`, and hides `account.workspace.project` and
`account.workspace.branch` because 🎮 drew them. Left as it is, after the
build:

- 🤖 and 🎮 are still stamped in each receipt (the file turns them back on).
- 📦 and 🌿 are shown nowhere: 🎮 no longer draws them, and the file hides
  them on 💳.

Step `RP7` gives the file that draws the new layout.

## One grid above and below

The user's first note: 🎮 above the prompt and 🤖 under the footer line
compare only if both use one column grid and one left indent.

**The width.** `AbovePrompt`'s `bodyColumns` is the band's column (the
terminal, or the transcript's beside a docked `Pane`) less the engine's
five at the right end, where `[-]` stands on the first row
(`mod/.claude-plugin/types/claude-code/index.d.ts`, `AbovePrompt`). The
mod already lays every row out at `bandCols = bodyColumns + 5`, taken from
that hook whether or not it draws there; the footer's rows and the receipt
use the same `bandCols`. So the width is shared today.

**The right edge.** The grid is laid out from the right, at
`cols - right-edge`. A row above the prompt cannot run into the five
columns of `[-]`, so it needs `right-edge` 5; under the footer line it is 2
today. With 🎮 at 5 and 🤖 at 2 every figure would stand three columns
apart. So once any row is above, every row, the receipt and the agent
panel take 5 (the derivation above). The cost is three blank columns at
the right of the footer's rows and the panel ([Decided](#decided), 2).

**The left indent.** Claude Code draws the footer line's container
`hint-inset` (2) columns in, and the mod draws its rows there that much
narrower; the band above the prompt starts at column 0. Since the grid is
laid out from the right, the cells already land on one column either way;
only the labels start 2 columns apart. The rows above the prompt take
`indent: hint-inset` (`BandOpts.indent`, blanks before the label), and the
receipt always takes `hint-inset` (today it takes none under `"above"`),
so 🎤, 🎮, 💳, 🤖 and the receipt's 🎤 start at one column
([Decided](#decided), 3). `RP1` checks live that the band's left edge is
column 0.

## The labels without their text

The user's second note: dropping the prompt and the reply frees the label
column.

- **What the rows lose.** 🎤's label is `🎤 `; 🤖's is `🤖 ` and its 📨
  count; 🎮's is `🎮 `, its workspace moving to 💳. The receipt's 🎤 loses
  its prompt too, and its 🎮, when `rows.session.transcript` stamps it,
  is as bare as the live one ([Decided](#decided), 6).
- **The code goes with it** ([Decided](#decided), 9). `turnLabel` and
  `mainLabel` in `mod/src/cells.ts` lose their `chat.prompt` and
  `chat.reply` pieces and the text they took; `band.ts` and `receipt.ts`
  stop reading the prompt and the reply for them; `chat` in
  `HIDE_GROUPS` keeps only `doing`. 🎮's live label is its mark alone;
  the workspace's pieces become `workspacePieces` in `cells.ts`, which
  only 💳 draws, so the receipt no longer takes a workspace. The Python
  draws none of these labels. What the retired status line draws (its
  👤💬 and 🤖 chat rows, from `user_text` and `asst_text`) stays, as do
  the transcript's prompt and reply in the folds, which it reads.
- **What the grid keeps.** Which columns drop on a narrow terminal is
  worked out once for every row the band, the receipt and the panel can
  draw (`fixedKeys`, `LABEL_MIN` in `spec/layout.jsonc`): a column drops
  while the label would keep fewer than `LABEL_MIN` columns. It goes from
  20 to 12 for every row ([Decided](#decided), 8): an agent row's head on
  the panel, its spinner, kind and state marks and a blank, is 7
  columns, and 5 more show the first letters of its name, enough to tell
  two agents apart; the band's widest label, 🤖 with a 📨 count, is about
  7. So one more column, 💰 or 🔋, stays on screen at widths where it
  dropped, and the panel's names and tasks are cut harder there. The
  band's labels leave the rest of their room blank, on the left: each row
  is as wide as before, its mark flush right against the first column
  (`FLUSH_RIGHT` in `grid.ts` and `grid.py`) and its figures where they
  were.
- **No row is pressable.** The rows are plain Text, above the prompt,
  under the footer line and in the receipt.

## The 💳 row

Today 💳 is, by default, a tail on Claude Code's footer line
(`PromptHint`'s `tail`): plain text, dim only, after Claude Code's ` · `,
cut a column short of the row's end, and padded with U+2800 to a guessed
width. With the workspace's 📦 🌿 📁 🔀 🎨 joining the windows and 📅 🕐,
it no longer fits after the footer's pills on most widths, so it becomes a
row of its own under the footer line (`account-place` `"row"`, which
`accountLine` draws today), in its colours ([Decided](#decided), 4).

- **What it holds** (`workspacePieces`, `mod/src/cells.ts`, after `RP4`):
  📦 project, 🌿 branch (🍂 and ✱ when dirty), 📁 directory, 🔀 PR and 🎨
  output style. `accountPieces` (`mod/src/band.ts`) already takes 📦 🌿
  📁; it gains 🔀 and 🎨, each hidden by its own `account.workspace.*`
  path.
- **The order** the user wrote, a new layout in `accountLine`: 💳 and its
  windows from the label column, then 📦 🌿 📁 🔀 🎨, then 📅 🕐 flush
  right ([Decided](#decided), 5).
- **Fitting.** Today the row is not cut and Claude Code cuts it at the
  edge. As a row with more in it, it sheds by the ranks the pieces already
  carry: 🎨, then 🔀, then 📁, then 📅, then 🕐, and then the windows' 🔜,
  before anything is cut with `…`.

## While a survey holds the band

The user's third note. `AbovePrompt` raises `hasSurvey` while a survey (a
question picker, `AskUserQuestion`) holds the band, and a hook yields to it
(`register.tsx` returns `next(e)`). With 🎤 and 🎮 above the prompt, both
are gone while the picker is open, and come back when it is answered:

- the turn is still running, so 🎤 returns as it was;
- 💳 and 🤖, under the footer line, stay if Claude Code still draws the
  footer line under a survey (`RP1` checks);
- the receipt is not touched: it is stamped at the turn's end, and a
  survey is answered before that.

The plan takes that as it is, with no code for it
([Decided](#decided), 7).

## What changes, file by file

| File | Change | Step |
|---|---|---|
| `spec/options.jsonc` | `rows.fields.place` (enum, `fixed: ["tag"]`); `live-place` removed; `right-edge`'s `derived` from `rows.*.place`; `account-place`'s doc | `RP2` |
| `mod/defaults/config.jsonc` | `place` on each row, `live-place` gone, `account-place` `"row"`, `right-edge`'s comment | `RP2`, `RP5` |
| `tools/gen-spec.py` | the table form of `derived`, checked: the table and field exist, `any` is among the field's items, the map is keyed by every item | `RP2` |
| `coding_agent_usage_line/options_spec.py`, `mod/src/options_spec.ts`, `docs/options.md` tables | generated | `RP2` |
| `coding_agent_usage_line/options.py` | `_merged_value` and the derivation read `rows` (a mod-only option, as `live-place` was) to give `right-edge` | `RP2` |
| `coding_agent_usage_line/config.py` | nothing beyond the spec: table fields and `fixed` are already generic | `RP2` |
| `mod/src/config.ts` | the same derivation, `optionsOf` without `livePlace` | `RP2` |
| `mod/hooks/register.tsx` | `AbovePrompt` draws the rows whose `place` is `"above"`,; `PromptHint` the ones whose `place` is `"footer"`; `insetOf` gone (one inset); the above rows indented `hint-inset` | `RP1`, `RP2`, `RP3` |
| `mod/src/band.ts` | `bandScoped` takes the place to draw (rows filtered by `place`) and the order with 💳; `sessionRow`'s label bare; `turnRow`, `mainRow` without text; `accountPieces` on `workspacePieces`, then with 🔀 🎨, the user's order, shedding | `RP2`, `RP4`, `RP5` |
| `mod/src/receipt.ts` | `turnRow` without its prompt; `sessionRow`'s label bare; no workspace taken | `RP4` |
| `mod/src/cells.ts` | `turnLabel` and `mainLabel` without their text pieces; `sessionLabel` the mark alone; `workspacePieces` for 💳 | `RP4` |
| `spec/layout.jsonc`, `spec.{py,ts}` | `HIDE_GROUPS.chat` without `prompt` and `reply`; `LABEL_MIN` 12 | `RP4` |
| `mod/hooks/register.tsx`, `mod/tools/*.ts`, `mod/mod-tests/` | the receipt's callers without a workspace | `RP4` |
| `mod/tools/draw-figures.ts` | `--part above` and `--part footer` draw by place; `--sticky` becomes `--rows` reading a rows table | `RP2` |
| `mod/README.md`, `docs/layout.md`, `docs/options.md` prose | see [Docs](#docs) | `RP6` |

### The Python port

What the Python draws, and what it must change:

- **The agent panel** (`--mode subagent`) draws Claude Code's panel rows,
  none of the mod's. It must change one thing: its `right-edge`, derived
  from `rows.*.place` (5 under the new defaults) in step with the mod, as
  it is derived from `live-place` today. The user's `subagentStatusLine`
  command gives no `--right-edge`, so it follows.
- **The defaults file** is read strictly by both ports, so `place` must be
  in the spec the Python's checker is generated from, and `live-place`
  gone from both at once (`RP2`, one commit).
- **The status line** (`--mode status`) and **the Stop hook's receipt**
  (`--mode cost`) draw grids of their own, retired with the mod loaded
  ([docs/layout.md](../../docs/layout.md#the-status-line-and-the-stop-hook)).
  They draw none of these rows and do not change; their goldens hold.

## Tests and fixtures

Each step leaves `bash tests/all.sh` and `npm test` (in `mod/`) passing.

| What | How | Step |
|---|---|---|
| The spec's generated files | `python3 tools/gen-spec.py`, then `--check` | `RP2` |
| The shared config cases | `tests/fixtures/gen/config.py` (in `gen/all.py`): `right-edge-derived` becomes one case per place mix (all footer 2, any above 5, an above row `"never"` not counted), `live-place` as an unknown key, `rows.tag.place` warned | `RP2` |
| The defaults cases | `tests/fixtures/config/defaults-cases.json`: a defaults file still holding `live-place`, or lacking `place`, is a `DefaultsError` | `RP2` |
| The mod's fixtures module | `node mod/tools/gen-mod-fixtures.ts` (it carries the defaults file's text) | `RP2`, `RP5` |
| The row cases | `node mod/tools/gen-row-cases.ts`: band cases by place, labels without text, the 💳 row with 🔀 🎨 and its shedding | `RP2`, `RP4`, `RP5` |
| The grid cases and the panel goldens | regenerated in both ports for `LABEL_MIN` 12 | `RP4` |
| The mod harness | `mod/mod-tests/band.test.ts`: 🎤 and 🎮 in `AbovePrompt`, 💳 and 🤖 in `PromptHint`; 🎤 gone and 🎮 kept after the stamp; nothing above under `hasSurvey`; no row a Button; 🎮's and 🤖's cells on the same columns (`RP3`); the receipt without 🤖 🎮 by default and with them under `transcript` `true` | `RP1` … `RP5` |
| `mod/mod-tests/config.test.ts` | the options with no file match the defaults file, `place` included | `RP2` |
| The panel goldens' edge | unchanged by `RP2`: `tests/run-cases.py` writes `"right-edge": 5` in its scratch user file | — |

## Docs

- **`docs/layout.md`:** the opening render becomes the new layout, both
  places drawn; "The rows" table gets a Place column; "Pressing a row"
  drops "Nor are the rows above the prompt"; "Labels" says 🎤, 🤖 and 🎮
  carry their marks and 💳 the workspace; "Between turns" draws the band
  with 🎮 alone; "The receipt" draws 🎤 alone by default; "Hiding" loses
  the shipped `account.workspace.*` example; "Other placements" becomes
  how to put all rows in one place (every `place` the same) and keeps the
  footer's tail. A line on surveys.
- **`docs/options.md`:** the generated tables, and the prose that names
  `live-place` (`right-edge` follows the rows' places).
- **`mod/README.md`:** where the rows go, and the options list.
- **`README.md`:** the legend if it names where a row is drawn.

## Migration of the user's file

The user's own, by hand, as `CM7` was; the plan only reads it. After
`RP5`, the file that draws the new layout with the user's hiding:

```jsonc
// coding-agent-usage-line: the band's and the agent panel's settings.
// The options are in docs/options.md; `coding-agent-usage-line.py
// --show-config` shows what each layer gives.
{
  // The menu-bar app's store.
  "usage-source": "claude-usage-tracker",
  // 🔋 the 5-hour limit, 🧠's ٪ of the window and 🎯 the cache hit rate in
  // every row.
  "hide": ["*.plan.five_hour", "*.context.share", "*.tokens.cache"]
}
```

- `rows` goes: the defaults are the new layout, with only 🎤 stamped.
- `account.workspace.project` and `account.workspace.branch` leave
  `hide`: 💳 is now the only row that draws 📦 and 🌿.
- To keep 🤖 and 🎮 in each receipt, the file keeps
  `"rows": {"agent": {"transcript": true}, "session": {"transcript": true}}`.
- `coding-agent-usage-line.py --show-config` run here shows no warning and
  `right-edge` 5, derived.

## Risks

- **The band's left edge and a docked pane.** That the band starts at
  column 0 is read from the docs' render, not the types. Beside a docked
  `Pane` (fullscreen, 110 columns and wider) `bodyColumns` is the
  transcript's column; if the footer line is the terminal's width there,
  rows above and below are laid out at one `bandCols` but drawn in
  containers of different widths. `RP1` logs both widths live.
- **The survey's gap.** 🎤 and 🎮 vanish while a question picker is open.
- **The `[-]` collapse.** Collapsed, the band hides 🎤 and 🎮 until it is
  opened again; Claude Code keeps that state, not the mod.
- **Three columns lost** under the footer line and on the panel at
  `right-edge` 5.
- **The receipt and the band at once.** For `receiptHoldMs` (1 s) after the
  stamp, 🎤 is both the receipt and the band's first row, as it is under
  the footer line today.
- **Other users' files** that set `live-place` get a warning and fall to
  the new defaults, which split the rows.

## The build order

Each step is one commit and leaves both ports' tests passing; the first is
a trial, the last two are the user's.

1. **`RP1`, the trial above the prompt.** With `live-place` `"above"` (set
   by the user in their own file for the trial, and taken out after it),
   the `AbovePrompt` and `PromptHint` hooks log,
   once per change, `bodyColumns`, `viewport.columns`,
   `viewport.isFullscreen` and `hasSurvey`. Under `live-place` `"footer"`
   nothing drawn changes; only the log lines are new. The user opens a
   question picker and a docked pane, and reports what moved and what the
   log said. Settles: the band's left column; whether the footer line and its rows still draw
   under a survey; the widths beside a docked pane.
2. **`RP2`, placement per row.** `rows.*.place` in the spec, the defaults
   file and both ports; `live-place` gone; `right-edge` derived from the
   places in both ports; `AbovePrompt` and `PromptHint` each draw the rows
   of their place, in the one order; `draw-figures.ts` by place; config
   cases, defaults cases, fixtures module and row cases regenerated.
3. **`RP3`, one grid.** The rows above the prompt indented `hint-inset`;
   the receipt always at `hint-inset`; a harness test that 🎮 above and 🤖
   below put each cell on the same terminal column at 80, 120 and 160
   columns.
4. **`RP4`, the labels without text.** The code that draws 🎤's prompt
   and 🤖's reply removed, in the band and the receipt; 🎮 without its
   workspace, live and in the receipt, which no longer takes one;
   `HIDE_GROUPS.chat` down to `doing`; `LABEL_MIN` 12 for every row, its
   grid cases and panel goldens regenerated in both ports; row cases and
   fixtures regenerated; the docs that describe the removed text.
5. **`RP5`, the 💳 row.** `account-place` `"row"` by default; 🔀 and 🎨
   on it; its order and shedding; fixtures module and row cases
   regenerated.
6. **`RP6`, docs.** As in [Docs](#docs), with each render drawn by
   `draw-figures.ts` from the fixtures.
7. **`RP7`, the user's file.** By hand, as in
   [Migration](#migration-of-the-users-file).
8. **`RP8`, the acceptance check**, live, below.

## Acceptance

In a session started in this repository, with the user's file as in `RP7`
and no `config.local.jsonc` setting `rows`:

1. `coding-agent-usage-line.py --show-config` shows `rows` from the
   defaults, `right-edge` 5 derived, and no warning; the mod's log says
   the same.
2. While a turn runs: 🎤 then 🎮 above the prompt, `[-]` on 🎤's row; 💳
   then 🤖 under the footer line, then Claude Code's panel. Neither 🎤 nor
   🤖 shows the prompt's or the reply's text.
3. 🎮's 💰, ⌛ and 🪫 stand on the same columns as 🤖's and as an agent
   row's on the panel; all four marks start at one column.
4. 💳 holds 💳 🪫 🔜, 📦 🌿 📁 (and 🔀 on a branch with a PR, 🎨 under an
   output style), and 📅 🕐; at 100 columns it sheds 🎨 and 🔀 first.
5. The turn ends: the receipt appears as the closing line just above the
   band, 🎤 alone and its 🔺🔖 line; the band is 🎮 alone, `[-]` on its
   row; 💳 and 🤖 stay.
6. A click on 🎤 above the prompt, on 🤖 under the footer line and on
   the receipt's 🎤 each scrolls to its prompt or reply, and the log shows
   each `$.ui.scroll`.
7. A question picker opens: 🎤 and 🎮 go while it is open and come back
   when it is answered.
8. `[-]` collapses the band; 🎤 and 🎮 are hidden; reopening it shows
   them.
9. `"rows": {"agent": {"transcript": true}, "session": {"transcript": true}}`
   in this repository's `config.local.jsonc` puts 🤖 and 🎮 back in the
   next receipt, within one tick and no `/reload-plugins`.

## Decided

The user's answers to the plan's nine questions; the steps above follow
them.

1. **The configuration's shape: a `place` field in each row of `rows`;
   `live-place` retired.** Any arrangement can be written, and a project
   sets one row's place alone, since tables merge per field. It costs the
   table form of `derived` in `gen-spec.py` and both ports, and a warning
   in any file that still sets `live-place`. Not taken: a third
   `live-place` value fixed to this layout, or a `places` option apart
   from `rows`.
2. **The right edge: 5 everywhere once any row is above,** the footer's
   rows and the agent panel included. One grid; three blank columns at
   the right of the rows under the footer line and of the panel. Not
   taken: 5 above and 2 below, which would set 🎮's figures and 🤖's
   three columns apart.
3. **The left indent above the prompt: `hint-inset` (2) columns,** so
   every mark and the receipt's start at one column, at the cost of two
   columns of label room, now blank.
4. **💳: a row of its own under the footer line** (`account-place`
   `"row"` by default): its colours, its own width and shedding by rank,
   for one more row of height; the footer line goes back to Claude
   Code's own. The dim tail stays as the other value.
5. **The 💳 row's order: 💳 and its windows from the label column, then
   📦 🌿 📁 🔀 🎨, then 📅 🕐 flush right,** mark first as on the other
   rows; a new layout in `accountLine`.
6. **The receipt's 🎮, when `rows.session.transcript` stamps it: bare,
   like the live 🎮.** One look for the row; a receipt no longer says
   the branch it ran on.
7. **While a survey holds the band, 🎤 and 🎮 go until it is answered.**
   No code; the turn's and the session's figures are off screen while the
   user answers.
8. **`LABEL_MIN` lowered for every row, to 12.** An agent row's head on
   the panel (spinner, kind and state marks, and a blank) is 7 columns;
   5 more keep the first letters of its name, enough to tell two agents
   apart, while the band's widest label, 🤖 with a 📨 count, is about 7.
   Below 12 a panel row could show its marks and no name at all. One more
   column stays at a given width; the panel's names and tasks are cut
   harder; the grid cases, the panel goldens and the row cases are
   regenerated in both ports. Not taken: a smaller minimum for the band's
   rows alone, which would break the shared column layout.
9. **The prompt and the reply text: the code is removed,** not only left
   uncalled: `turnLabel`'s and `mainLabel`'s text pieces, the callers'
   reading of the text for them, `HIDE_GROUPS`' `chat.prompt` and
   `chat.reply`, and their tests and fixtures, in each port that has them
   (only the mod does). The receipt's 🔖 tag line stays.
10. **No row is pressable,** and the press code is removed: a press on 🎤
    or 🤖 did nothing live. The three rows' labels are drawn flush right,
    their marks and 📨 beside the model, two columns from it.

## Files

`spec/options.jsonc`, `mod/defaults/config.jsonc`, `tools/gen-spec.py`,
`coding_agent_usage_line/options.py`, `mod/src/config.ts`,
`mod/hooks/register.tsx`, `mod/src/band.ts`, `mod/src/receipt.ts`,
`mod/tools/draw-figures.ts`, `mod/mod-tests/band.test.ts`,
`tests/fixtures/gen/config.py`, `docs/layout.md`, `docs/options.md`,
`mod/README.md`. `register.tsx` and `band.ts` are changed by several
steps; see [the schedule](_schedule.md) for their order.
