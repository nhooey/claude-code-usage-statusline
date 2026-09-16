# Development

## Reading the code

The executable is a thin checkout launcher. Keep it beside the
`coding_agent_usage_line/` package; no package installation is required.

| module | responsibility |
|---|---|
| `cli.py` | validate agent/source/options, prepare Codex reports, dispatch to the selected adapter |
| `formatting.py` | shared glyphs, measured widths, ANSI palette, number formatting and terminal geometry |
| `models.py` | immutable token/request records, with missing categories distinguished from zero |
| `sources.py` | source selection, grouped quota normalization, command/app-server/HTTP collection and refresh policy |
| `state.py` | private scoped source cache, refresh locks and atomic Codex report claims |
| `codex.py` | rollout records, thread identity, descendant discovery, request deduplication and turn attribution |
| `render.py` | prepared Codex status/history/Stop text and separate account-period rows |
| `claude_records.py` | Claude payload/transcript records, usage parsing, model prices and turn/agent accounting primitives |
| `claude.py` | Claude orchestration: read inputs, prepare accounting/cache snapshots, serialize status/Stop/panel output |
| `claude_sources.py` | shared source reading to Claude's established default-window display bridge |
| `claude_render.py` | prepared Claude status cells and fixed-column grid |
| `claude_cost_render.py` | prepared Claude cost-row placement, palette and layout |
| `claude_subagent_render.py` | prepared Claude task rows, without transcript or source reads |

The accepted portability scope and remaining module-boundary criteria are in
[the agent-agnostic implementation plan](agent-agnostic-plan.md).

The substantial Claude sections retain their original comments and formatting
algorithms. Shared formatters do not select sources or read vendor histories;
rendering receives prepared readings. A named quota bucket is not squeezed
into the legacy default five-hour/weekly pair: its identity and nested windows
remain in the generic account output.

The code comments are deliberately dense, and these documents duplicate the
parts of them that are worth knowing before you open the file rather than
while you are standing at one line of it. Where a comment is the better place
for a detail — a single field's width, one function's failure mode — it stays
there, and docs/ does not repeat it.

## Style

Prefer pure rendering functions over immutable records and prepared snapshots.
Keep file reads, subprocesses, HTTP, cache writes and report claiming in the
adapter/source/state layers. A missing observation is not an observed zero.

The agent files are read once per process and handed to every reader that
needs them — `read_transcript`, `read_turns`, `_with_shares` all take an
`agents` argument — rather than memoised in a module name. Same rule: a
process is one render, and the reading is an input to it.

The display knobs for mark spacing and subscript decimals are set before
rendering. Code outside `formatting.py` reads dependent mutable widths through
the module, not copied imports. Source selection happens before rendering, so
cells and rows cannot independently refresh or disagree about the reading.

Codex account quotas and request tokens are different records. A request ID
deduplicates copied fork history; a thread ID identifies a child; an explicit
root-turn link attributes child usage. Do not substitute the shared session ID
for any of these. Atomic session-wide claims retain origin turns so late child
usage can print once without being charged to the latest turn. Historical
`--all` reports are read-only and do not consume those claims.

Claude's turn/session/child quota shares are calibrated estimates. There is no
Codex conversion from a child's tokens to its share of a subscription bucket,
and no API-price fallback for subscription usage. Preserve unavailable values.


## TODO

Known and deliberate, rather than discovered by a reader. Entries leave this
list when they are done; git history is the record of what was.

**Measured 2026-09-08, and closed.** `--selftest` and
`tests/probe-advance.sh` were run in Rider/JediTerm and in Ghostty under tmux,
twice — the second time after `SUB_DIGITS` was renamed `E_SUB_DIGITS`, which is
what put the subscript digits in front of the probe at all. Every specimen row
came back delta 0 in both terminals, and both probes emitted empty override
tables. 🎤 💯 💳 🎮 📖 📝 advance two, ▴ U+25B4 and ▾ U+25BE advance one, 🤏
U+1F90F advances two, `U+2080`–`U+2089` advance one, and the `|` column rule
draws in a gap the grid already spends.

Nothing in the layout is inferred from a width table any more. What the runs
found instead is recorded where it belongs: a stale claim about U+1FA70 and a
real Ghostty/JediTerm disagreement at U+1F900, both under *Glyphs, terminals,
and the naughty ones*; and a saving that never existed, under
`--subscript-decimals` in *Options*.

**Measured 2026-09-12, and closed.** 👥 `E_ROW_AGENTS`, U+1F465, the label
glyph of the late-agents cost row added 2026-09-11, went through
`tests/probe-advance.sh` in Rider/JediTerm and in Ghostty, both outside tmux:
`advance=2` in each. Its two columns are a reading now, recorded beside 🤏's
under *Glyphs, terminals, and the naughty ones*.

**Unverified — needs a real terminal tab, so no runner and no agent can close
it**

0. The seventeen glyphs of the subagent row added 2026-09-13: the eleven
   type marks in `_KIND_MARK` — 🔧 🎩 🔍 📐 📚 📟 🍴 🐚 🔗 🌐 🎎 — the five
   state circles in `_STATE_MARK` — 🟢 🟡 🔵 🔴 ⚫ — and 🛫 U+1F6EB, the
   token rate. Each holds to the glyph rules — single codepoint,
   Emoji_Presentation=Yes, inside `EAW_WIDE` — except that 🟢 U+1F7E2 and 🟡 U+1F7E1 are Unicode 12, past the Unicode 9
   line the rules prefer and the first glyphs on either readout to be. None
   has been through `probe-advance.sh` or drawn by `--selftest` in either
   terminal. The probe derives its list from the `E_*` constants and will
   not see these until they are named that way or it is taught to read the
   two tables; do that, run it, and record the result under *Glyphs,
   terminals, and the naughty ones*. 🛫 replaced ✈️ U+2708 U+FE0F within
   the hour: the airplane with the variation selector broke the rules on
   both counts, and in JediTerm a digit was seen painted over the slash of
   its cell. The row's one live glyph bug so far, and it went the way the
   rules predict. The type marks and the circles appear on the panel rows
   only, so a wrong width there shifts one row of the panel and nothing on
   the status line; 🛫 is on the status line too since the evening of the
   same day, in column 2, where a wrong width shifts row 3 to the right of
   it. The row's width is no longer a guess: the panel's `columns` is
   already net of its chrome, measured on screen 2026-09-13.

0a. The superscript digits `E_SUP_DIGITS`, U+2070 U+00B9 U+00B2 U+00B3
   U+2074–2079, added 2026-09-13 for the model's major version — `O⁵`,
   `H⁴` — on the status line's column 2 and the panel rows both. Six are
   East_Asian_Width Neutral and four (¹ ² ³ ⁴) Ambiguous, the split of the
   subscript block, which both terminals advanced one column on 2026-09-08;
   ⁴ is the Ambiguous one in live use, on every Haiku and Sonnet row. Not
   probed. `probe-advance.sh` reads `E_*` constants, so it will see these
   on its next run; record the result beside the subscripts' under *Glyphs,
   terminals, and the naughty ones*. A two-column ⁴ would push 🤖H⁴🔥's
   effort glyph one column into the gap and nothing else, since the cell
   fills its column exactly.

1. Bare Ghostty — outside tmux — falls to the `unknown` profile, and its
   width behaviour is measured only as far as the probe above went: 👥
   advanced two there on 2026-09-12, which is the first bare-Ghostty reading
   of anything. `term_profile` checks `TMUX` first, so the two full Ghostty
   runs of 2026-09-08 measured the `tmux` profile and say nothing about
   Ghostty on its own. The width tables would be empty either way; what is
   untested is the paint room `_PAD` gives the icons under `iterm`/`tmux` and
   withholds under JediTerm, which only `--selftest`'s drawn rows can show.

**Cleanup**

2. Column 1 of the status line renders empty on a default-style session with
   no open PR, which is the common case. It is reserved width showing
   nothing. Left as-is deliberately: reclaiming it is a layout change that
   moves `render_status` and re-blesses both golden suites, and the width is
   not needed by anything else at present.

## Where this is going

Vague on purpose — these are the intentions, not a design:

1. **Additional agent adapters and intake methods**, following the boundaries
   and capability differences in the [portability plan](agent-agnostic-plan.md).
2. **A terminal diagnostic program**, in a repo of its own: drive every
   terminal-and-multiplexer combination, read back screenshots, and work out
   what each one gets wrong with which emoji. `tests/probe-advance.sh` is the
   seed of it.
3. **A terminal output filter**, in the same repo as (2): normalise output
   across terminals from the active combination, so a program does not have to
   carry the per-terminal knowledge itself.

Until (3) exists, the terminal-specific logic stays here — the width tables,
the profiles, and the naughty-glyph rules in [Glyphs, terminals, and the
naughty ones](glyphs-and-terminals.md). That is the part to lift out first
when the filter arrives.

## License

MIT — the full text is in [`LICENSE`](../LICENSE). The SPDX identifier is
`MIT` and the canonical text is published at
<https://opensource.org/license/mit>.

`LICENSE` held a *reference* to the text rather than the text until
2026-08-28, which was tidier and wrong: automated licence detection, GitHub's
included, reads the text and not a pointer to it, so the repository showed as
unlicensed. The text is pasted in, unmodified.
