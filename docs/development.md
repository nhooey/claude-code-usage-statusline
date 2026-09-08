# Development

## Reading the code

One file, sectioned by banner comment, in dependency order:

| section | what |
|---|---|
| Glyphs | every character, by name |
| ANSI truecolor escapes | the palette |
| Tunables | widths, thresholds, billing weights, prices, cost-line geometry |
| Width tables | `EAW_WIDE` and the per-terminal overrides |
| Measurement | `vis_width`, `trunc`, `term_profile` |
| Formatting | `humanize`, `dec_align`, `pad_val`, `pct`, `money_fmt`, `money_cell`, `short_model`, `SI_UNITS`, `sub_dec` |
| Colour tiers, Terminal geometry, Records | small |
| Reading the payload / the transcript | `Turn`, `read_turns`, `read_turns_settled` |
| Usage sources | `UsageSource`, `ClaudeUsageTrackerSource`, `tracker_reading`, `CommandSource`, `normalise_reading`, `usage_source` |
| Git, Plan limits | `detect_git`, `load_limits`, `calibration`, `turn_cost_since`, `window_shares`, `session_shares` |
| Status-line segment renderers, Status-line layout | `--mode status` |
| Cost line | `cost_group`, `cost_totals_group`, `stack_metrics`, `place_stacked`, `render_cost_line` |
| Alignment self-test | `--selftest` |
| Entry points | `main_status`, `main_cost`, `USAGE` |

The code comments are deliberately dense, and these documents duplicate the
parts of them that are worth knowing before you open the file rather than
while you are standing at one line of it. Where a comment is the better place
for a detail — a single field's width, one function's failure mode — it stays
there, and docs/ does not repeat it.

## Style

Pure functions over frozen `NamedTuple` records. Module-level names are
constants, and the few that depend on the terminal are computed once at import
and passed as default arguments so a test can substitute them.

Three names are mutable and all three are set once, in `main()`, before
anything renders: mark spacing, subscript decimals, and the selected usage
source. Each is a command-line flag consumed several calls deep — inside a
formatter, or inside a cache refresh — and threading a display switch through
every renderer that does not care about it buys nothing. They are set before
the first render and never again, and a process is one render.


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

**Unverified — needs a real terminal tab, so no runner and no agent can close
it**

1. Bare Ghostty — outside tmux — is unmeasured and falls to the `unknown`
   profile. `term_profile` checks `TMUX` first, so both Ghostty runs measured
   the `tmux` profile and say nothing about Ghostty on its own. The width
   tables would be empty either way; what is untested is the paint room `_PAD`
   gives the icons under `iterm`/`tmux` and withholds under JediTerm.

**Cleanup**

2. Column 1 of the status line renders empty on a default-style session with
   no open PR, which is the common case. It is reserved width showing
   nothing. Left as-is deliberately: reclaiming it is a layout change that
   moves `render_status` and re-blesses both golden suites, and the width is
   not needed by anything else at present.

## Where this is going

Vague on purpose — these are the intentions, not a design:

1. **This program, made agnostic** between harnesses and agents, rather than
   knowing about Claude Code specifically.
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
