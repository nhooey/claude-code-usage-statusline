# Options

Operational modes require `--agent claude|codex`. Help and the terminal
`--selftest` do not require an agent. Select account intake independently with
`--usage-source`; transcript data always supplies the session's own metrics.

| common option | effect |
|---|---|
| `--agent claude\|codex` | choose the transcript and hook adapter |
| `--usage-source SPEC` | choose account intake; see [Usage sources](usage-sources.md) |
| `--transcript PATH` | read an explicit file in status or cost mode without waiting for stdin; do not consume live Stop-report state |
| `--account NAME` | a non-secret account/cache namespace; default `default` |
| `--account-period day\|week\|month` | UTC calendar period for organization reports; weeks start Monday; default `day` |
| `--diagnose` | emit redacted source/freshness/coverage diagnostics on stderr |
| `--all` | with cost mode, report historical turns and completed child rows as plain text |

Codex supports one-shot status and JSON Stop summaries. It groups requests by
root turn, includes descendant usage without adding copied fork prefixes, and
reports late usage once with its original turn attribution. Its live footer is
configured through Codex's own `/statusline`; there is no external footer
command. `--mode subagent` is Claude-only and exits 2 for Codex with an explanation.
The display switches below apply to Claude's presentation.

Claude has three modes and a self-test:

```
--mode status   stdin: the status-line JSON payload
                stdout: three rows
--mode cost     stdin: the Stop-hook JSON payload
                stdout: {"systemMessage": "<two rows>"}
--mode subagent stdin: the agent panel's task list
                stdout: one {"id": ..., "content": ...} line per task
--selftest      draws specimen rows on the tty and asks the terminal where
                the cursor landed; needs a real terminal tab
```

`--mode cost` takes these, most of which only ever REMOVE something or
move it:

| option | effect |
|---|---|
| `--transcript PATH` | read this transcript instead of the payload's; also suppresses the flush wait, so tests do not pay for it |
| `--all` | list every prompt as plain text instead of emitting a hook response |
| `--prefix TEXT` | the icon block at the head of each row (default 📊) |
| `--label TEXT` | the label after it, bolded at print time |
| `--color` | emit colour; the hook needs plain, so plain is the default |
| `--no-totals` | drop the session-totals row |
| `--no-right-align` | print flush left |
| `--no-account-totals` | drop the second half of the 🔋 and 🪫 cells — `💳 99٪` on the totals row (`💳 💯` at a full window), `📖`/`📝` on the per-prompt row — leaving each window's own share alone. The two halves go together because they stack; see *Where one prompt's money went* |
| `--no-datetime` | drop the 📅 date and 🕐 clock cells |
| `--no-usage-text` | drop the `Usage: ...` words from every row label, keeping each row's marker glyph |
| `--force-newline` | always open the message with a blank line |

`--mode subagent` is the `subagentStatusLine` setting. Claude Code runs it
every few seconds while the session has tasks in its agent panel — Agent tool
calls, forks, background shells, workflows — with the task list on stdin, and
replaces each panel row with the `content` printed for its `id`. A task left
out keeps the panel's own row. It takes no options of its own: the row is
fixed, and `--cols` and `--usage-source` below apply to it as they do to the
other two (`--no-mark-spacing` changes nothing here — no cell on this row
carries a mark-spacing blank).

The row is two groups, like line 3 of the status line. Flush left, *which*
agent, its cells one blank apart: the type glyph (🔍 Explore, 📐 Plan, 🔧
general-purpose, 🐚 a shell, 👥 anything else) with the run state as a
coloured circle against it — 🟢 running, 🟡 pending, 🔵 done, 🔴 failed, ⚫
killed — the task id, then the name, bright, and after it, dimmer, what the
agent is doing right now — the panel's progress summary — the two together
taking whatever the right group leaves, the activity giving way first. The
name is the registry's where the panel has one and the Agent tool's
`description` where it has not, which is most spawns. Flush right at fixed
widths, *what it is doing*: 🤖 a two-character model spec with the effort's
glyph against it (`O⁵🏃`, `H⁴🔥`; the ladder is 🐢 🚶 🏃 🚀 🔥, and the
status line's cell is the same since the same day), ⌛ elapsed, 🧩 tokens, 🛫 the token rate in tokens per
second, 🎯 🧠 💰, and 🔋 🪫 the agent's own share of each window. Right-aligning a
constant-width group puts each metric on one column in every row, ending on
the status line's own right edge, and the name is the field that gives. The
row is exactly the payload's `columns` wide: the panel states that width
already net of its own chrome — the `◯ ` pointer before the row and two
columns of padding after — so a row that fills it ends where the status line
does. The panel's ◯ itself is drawn before anything the command returns and
cannot be replaced from here.

The payload carries a name, a type, a status, a start time, a model, an
effort and the panel's own running token count. Everything else on the row —
🧩 🎯 🧠 💰 and the two shares — is read from the agent's own transcript,
`<session>/subagents/agent-<id>.jsonl`, the same way the status line reads the
session's, and the plan windows are the snapshot the status line last
published. A task with no transcript (a shell, a remote agent) shows the
fields the payload gives and nothing where the others would be. Brightness
on the row follows the status line's cuts (see *Brightness as magnitude* in
`layout.md`): 🧩 🧠 🛫 💰 ⌛ dim under theirs, 🎯 dims its green tier, and
the 🔋 🪫 pair dims together when the agent's weekly share is under 0.2٪ — a
light agent, whichever window you read it in. 🛫 is the
slope of the panel's last sixteen token readings at its five-second tick, and
is the one figure on the row that comes from the panel rather than the file.
That reading is the last request's input plus every output, so it climbs by
a whole context at each request and rests while a tool runs: a sign of life
and of pace, not a generation rate. The status line's own 🛫, in column 3
beside 🎯, is the same figure for the main thread, sampled by the program
itself — see [Columns 2 and 3](layout.md#columns-2-and-3). ⌛ 🧩 🛫 🧠 💰
dim under the status line's own magnitude cuts — ten minutes, 100k tokens,
1k/s, a dollar — so the heavy agents are the bright rows of the panel; see
[Brightness as magnitude](layout.md#brightness-as-magnitude-everywhere-else).

`--no-mark-spacing` works in every mode. On the status line
it closes the blank between each column-4 mark and its value, narrowing that
column from 33 to 29. On the cost line it reaches 🧩 and 🎯 only, for two
columns: those are the two cells with nothing in the column after the mark,
where 🧠 💰 🔋 🪫 and ⌛🤖 hold a `+` on the per-prompt row and the blank
the totals row stacks under it. That column is content, not spacing, and
closing it would unstack the two rows. `--mark-spacing` is the default and is
accepted so a settings file can say which one it means.

`--no-column-rules` is `--mode status` only, and drops the faint `|` borders
between the five right-hand columns. They are painted into the gaps the grid
already spends, so this changes the ink and nothing else — no column moves
either way. `--column-rules` is the default and is accepted so a settings file
can name what it wants. Note that the rules are ALREADY off below 160 columns,
at an unknown width, and under `--no-mark-spacing`; the flag turns them off at
the widths that would otherwise carry them. See
[Rules between the columns](layout.md#rules-between-the-columns).

`--subscript-decimals` works in both modes and is **off by default**. It writes
a fraction in `U+2080`–`U+2089` instead of after a point, so the point costs
nothing:

```
off   🧩 ▴6.6M ▾389k  🎯 96٪  🔋 🎤 .79٪ 🎮 4.1٪ 💳 11٪ 🔜 4.5h   💰 35.5
on    🧩 ▴ 6₆M ▾389k  🎯 96٪  🔋 🎤 0₇₉٪ 🎮  4₁٪ 💳 11٪ 🔜  4₅h   💰  35₅
```

The leading zero the status line normally drops **comes back**: `.38` is
unambiguous because the point marks the figure as a fraction, and `₃₈` is not
— it is the glyph sequence a reader takes for 38, one point size down. So a
reading under 1٪ is the same width either way and the switch buys nothing
there. That branch has a golden of its own, because it is the one somebody
tidies away later on the grounds that the zero is redundant.

**No field is narrowed for it, and none ever will be by this switch.** Every
reservation keeps the width it had, so a shorter figure gets one more column of
leading pad and no row changes width — verified across both modes at six
widths.

This note used to call that a deferral: the saving was "real (`LIM_FIG_W`
could go 4 → 3, three columns back on the 🔋 row)" and merely waiting on a
probe. **The probe ran on 2026-09-08 and the saving was never there.** What
sets that field is the widest thing that can land in it, and swept across every
hundredth of a percent the widest is four columns in both forms, for the same
reason:

```
off   .01٪        three characters of figure, then the unit
on    0₀₁٪        the leading zero comes back, so three again
```

Subscripts narrow the readings at or above 1٪ — `4.1٪` to `4₁٪` — and those
were never the widest. The sub-1 reading is, in both forms, and the leading
zero that makes it so is a deliberate choice explained above. `LIM_FIG_W` 4 → 3
is still available; it costs a digit of precision below 1٪, equally in both
forms, and it has nothing to do with subscripts.

The width question the probe was actually needed for is settled: all ten digits
advance **one column** in JediTerm and in Ghostty, which is what East Asian
Width says of the block and what `vis_width` has always returned. It was worth
asking — U+1F900 one plane up is a Neutral codepoint that Ghostty advances one
and JediTerm advances two. Holding the widths still means that if the terminal draws
these two columns wide, the damage shows up as a figure overrunning its own
cell rather than as a whole row shifted: a diagnosis instead of a mystery.

`--cols N` works in both modes and overrides the terminal-width walk; `0` means
"pretend the width is unknown", which is the only way to exercise the fallback
layout deterministically.

`--usage-source SPEC` applies to all supported modes. Explicit external
selection overrides native account readings and never silently selects a
different source. `auto` prefers current native data, a valid native cache,
then the optional tracker for Claude or managed app-server for Codex. `native`
excludes external refreshes; `none`/`off` also allow compatible cached readings.
`CODING_AGENT_USAGE_LINE_USAGE_SOURCE` sets the default; the CLI takes precedence.
Provider-specific sources are rejected for the other agent. The complete
source and credential list is in [Usage sources](usage-sources.md).

The four removing switches all default to ON — i.e. everything is drawn unless
asked otherwise — so a bare invocation is the full readout.
