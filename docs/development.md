# Development

`coding-agent-usage-line.py` is a thin launcher: it puts its own directory on
`sys.path` and calls `coding_agent_usage_line.cli.main`. Everything else is
the `coding_agent_usage_line/` package beside it. Keep the two together. There
is nothing to install: the package uses only the standard library and runs on
Python 3.9, the interpreter macOS's Command Line Tools ship as
`/usr/bin/python3`.

## How the code is laid out

```
coding-agent-usage-line.py        launcher
└─ cli.py                         parse and validate flags, pick the agent
   ├─ claude.py                   Claude orchestration: read, prepare, print
   │  ├─ claude_records.py        payloads, transcripts, prices, turn/agent accounting
   │  ├─ claude_sources.py        a usage-source reading, projected for the Claude rows
   │  ├─ claude_render.py         status-line cells and grid           (pure)
   │  ├─ claude_cost_render.py    Stop-hook cost rows                  (pure)
   │  └─ claude_subagent_render.py  agent-panel rows                   (pure)
   ├─ codex.py                    Codex rollout parsing and accounting
   ├─ render.py                   Codex status, history and Stop text  (pure)
   ├─ sources.py                  usage-source selection and collectors
   └─ state.py                    private on-disk cache, locks, report claims

shared by all of the above:
   formatting.py                  glyphs, widths, palette, number formats, terminal geometry
   models.py                      immutable, vendor-neutral token/request records
```

Every module above lives in `coding_agent_usage_line/`.

| module | owns |
|---|---|
| `cli.py` | The public flag set and usage text. Validates everything before reading stdin, then runs the Codex path itself or hands Claude to `claude.main`. |
| `claude.py` | Claude's three modes (`status`, `cost`, `subagent`) and `--selftest`: reads the hook payload and transcripts, takes one usage-source snapshot, derives calibration and window shares, keeps the per-session context and rate files, and prints. |
| `claude_records.py` | Claude JSONL interpretation: payload fields, request deduplication, per-model prices, turns, tool spans, agent files. No terminal output. |
| `claude_sources.py` | Turns a normalised usage-source reading into the `Limits` pair (5-hour and weekly) the Claude rows draw. |
| `claude_render.py` | Every status-line cell and the three-row grid. |
| `claude_cost_render.py` | Placement and stacking of the cost rows. |
| `claude_subagent_render.py` | One agent-panel row per task. |
| `codex.py` | Codex rollout records: thread identity, child discovery, request deduplication, turn attribution. Read-only. |
| `render.py` | Codex status, history and Stop reports, and account-period rows. |
| `sources.py` | `--usage-source` selection, the version-1 custom-command contract, the HTTP and app-server collectors, refresh policy. See [Usage sources](usage-sources.md). |
| `state.py` | The private state directory: scoped source cache, refresh locks, atomic claims so a Codex Stop reports each request once. |
| `formatting.py` | Glyph constants (`E_*`, `S_*`), width tables and `vis_width`, the ANSI palette, `humanize` and the other fixed-width formatters, terminal-width detection, and the two display switches. |
| `models.py` | `TokenUsage` and `UsageRequest`. A missing token category is `None`, not `0`. |

The comments in the code are dense on purpose. These documents cover what is
worth knowing before you open a file; a detail that matters only at one line
— a single field's width, one function's failure mode — lives in the comment
at that line and is not repeated here.

## Boundaries

These hold across the package. Most bugs that reach the goldens come from
breaking one of them.

- **Renderers are pure.** The four `*render*` modules take prepared values
  and return strings. They do not read transcripts, call usage sources, touch
  the cache or read the clock on their own. File reads, subprocesses, HTTP,
  cache writes and report claims belong to the orchestration, source and
  state layers.
- **One snapshot per process.** A process is one render. The usage source is
  read once, before rendering, so no two cells can disagree about the
  reading. Agent files are read once and passed down: `read_transcript`,
  `read_turns` and `_with_shares` all take an `agents` argument instead of
  re-reading or memoising in a module global.
- **Missing is not zero.** An absent metric, token category or quota window
  stays absent and renders blank or `?`. It is never printed as `0`.
- **Display switches are set once, then read through the module.**
  `set_mark_spacing` and `set_subscript_decimals` rebind globals in
  `formatting.py` (`MARK_SP`, `RIGHT_GRID`, `LINE3_RESERVED`, the `C_*`
  cost-line widths, `SUB_DEC`) before anything renders. Code elsewhere must
  read those as `fmt.NAME`. A `from .formatting import *` copy is taken at
  import time and never sees the change.
- **Quota buckets keep their shape.** A reading is a set of named buckets,
  each with its own windows. A bucket that is not the default one is not
  squeezed into the 5-hour/weekly pair; it keeps its identity through the
  cache, diagnostics and the generic account output.
- **Estimates stay labelled as estimates.** Claude's turn, session and agent
  shares of a plan window are calibrated estimates (see
  [Accounting](accounting.md)). Nothing converts Codex subscription tokens
  to API dollars or apportions an account percentage to a Codex child thread.

For Codex, a request ID deduplicates history copied into a fork, a thread ID
identifies a child, and an explicit root-turn link attributes a child's usage
to a turn. None of them can stand in for the shared session ID. Stop claims
remember each request's origin turn, so usage from a child that finishes late
prints once and is not charged to the latest turn. `--all` reads history
without consuming claims. See [Codex](codex.md).

## Where to make a change

| change | where | then |
|---|---|---|
| A status-line cell | `claude_render.py`; its width in `RIGHT_GRID` / `LINE3_RESERVED` / `RULE_MIN` in `formatting.py` | Regenerate the status goldens and read the diff; update [Layout](layout.md). |
| A cost-line cell | `claude_cost_render.py`, and the group builders in `claude.py` | Regenerate the cost goldens; update [Layout](layout.md). |
| An agent-panel cell | `claude_subagent_render.py` | Update the row shape asserted in `tests/subagent.py`. |
| A glyph | An `E_*` constant in `formatting.py` | Follow [Glyphs and terminals](glyphs-and-terminals.md); run `tests/probe-advance.sh` in a real terminal. |
| A flag | `_CLAUDE_FLAGS` / `_COMMON_FLAGS` and `USAGE` in `cli.py`; read it in `claude.main` or `codex_main` | Update [Options](options.md); add a case to `tests/port-cli.py`, the public-CLI suite. |
| Claude accounting (prices, turns, agents) | `claude_records.py`; window shares and calibration in `claude.py` | `tests/agents.py`, the cost goldens; update [Accounting](accounting.md). |
| A usage source | `sources.py`, and `validate_source` for its spec | `tests/sources-v1.py` and friends; update [Usage sources](usage-sources.md). |
| Codex accounting | `codex.py`, rendering in `render.py` | `tests/codex.py`. |

## Verifying a change

[Tests](tests.md) lists every suite and what it covers. The short version:

```sh
bash tests/golden.sh           # status line, byte for byte
bash tests/golden-cost.sh      # Stop-hook cost line
python3 tests/agents.py        # agent spend and tool time
python3 tests/subagent.py      # agent-panel rows
python3 tests/rate.py          # 🛫 and the brightness cuts
```

CI runs these plus the source, Codex, CLI and Python 3.9 floor suites.

A layout change is supposed to fail the goldens. Rerun the suite with
`--regen`, read the diff of `tests/golden/`, and commit the new files only if
every changed byte is one you meant to change.

Glyph widths cannot be checked in CI: they depend on the terminal drawing
them. `--selftest` and `tests/probe-advance.sh` need a real terminal tab.

## Style

- Prefer pure functions over immutable records and prepared snapshots.
- Name glyphs as `E_*` constants in `formatting.py` and use the constant.
  The probe finds glyphs by that prefix; a literal elsewhere is invisible to
  it.
- A fixed-width field carries a unit (`1.2k`, `4.5M`, `1.5h`), never more
  digits. See [Layout](layout.md).
- Explain a non-obvious choice in a comment at the line that makes it, with
  the evidence (a measurement, a failing case). Keep history in commit
  messages, not in comments or docs.

## Open issues

**Glyph widths not yet measured in a real terminal.** Each needs a run of
`tests/probe-advance.sh` in JediTerm and in Ghostty, with the result recorded
in [Glyphs and terminals](glyphs-and-terminals.md).

- The agent-panel type marks and state circles in `KIND_MARK` and
  `STATE_MARK` (`claude_subagent_render.py`): 🎩 🔍 📐 📚 📟 🍴 🐚 🔗 🌐 🎎 and
  🟢 🟡 🔵 🔴 ⚫. Unlike 🔧 and 👥, which are also `E_*` constants, they are
  literals in those tables, so the probe does not see them until it is taught
  to read the tables. 🟢 and 🟡 are Unicode 12, newer
  than any other glyph on either readout. A wrong width here shifts one panel
  row.
- 🛫 `E_RATE` and the superscript digits `E_SUP_DIGITS` (the `⁵` in `O⁵`).
  Both are `E_*` constants, so the next probe run covers them. ¹ ² ³ ⁴ are
  East Asian Width Ambiguous; ⁴ appears on every Haiku 4.x row. A two-column
  ⁴ would push the effort glyph one column into the gap after it.

**Terminal profiles not measured.**

- Bare Ghostty (outside tmux) gets the `unknown` profile. Whether it wants
  the icon padding `_PAD` gives `iterm` and `tmux` is untested; only
  `--selftest`'s drawn rows can show it.
- tmux over JediTerm has never been measured. `term_profile` checks `TMUX`
  first, on evidence from tmux over iTerm2 only. Running
  `coding-agent-usage-line.py --agent claude --selftest` in tmux inside Rider
  settles it: a non-zero delta on any row means the combination needs its
  own branch.

**Column 1 is usually empty.** It shows the output style or the PR number,
and on a default-style session with no open PR it is eleven columns of
nothing. Reclaiming it moves `render_status` and every status golden, and
nothing else needs the width yet, so it stays.

## Direction

Intentions, not designs:

1. More agent adapters and usage sources, behind the same boundaries.
2. A terminal diagnostic tool, in its own repository: drive each terminal and
   multiplexer combination and record which glyphs each one draws at which
   width. `tests/probe-advance.sh` is its seed.
3. A terminal output filter in the same repository, so a program need not
   carry per-terminal width knowledge itself.

Until (3) exists, the width tables, terminal profiles and glyph rules stay in
`formatting.py`. They are the first thing to move out when it does.

## License

MIT. The full text is in [`LICENSE`](../LICENSE), pasted in whole so that
licence detection (GitHub's included) recognises it.
