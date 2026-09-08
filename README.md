# claude-code-usage-statusline

[![tests](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml/badge.svg)](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml)

Two readouts for [Claude Code](https://claude.com/claude-code), rendered by one
program:

* a **status line** — three rows redrawn continuously under the prompt, and
* a **prompt-cost line** — two rows printed once per turn by the `Stop` hook,
  saying what the prompt just answered cost and what the session has spent.

```
--mode status   stdin: the status-line JSON payload
                stdout: three rows
--mode cost     stdin: the Stop-hook JSON payload
                stdout: {"systemMessage": "<two rows>"}
--selftest      draws specimen rows on the tty and asks the terminal where
                the cursor landed; needs a real terminal tab
```

Standard library only, written to run on Python 3.9 — the macOS Command Line
Tools interpreter — so it works in any project rather than only one whose
devshell supplies newer packages.

## Install

```sh
git clone https://github.com/nhooey/claude-code-usage-statusline.git ~/src/claude-code-usage-statusline
```

Then point `~/.claude/settings.json` at it:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/src/claude-code-usage-statusline/claude-code-usage-statusline.py --mode status --mark-spacing"
  },
  "hooks": {
    "Stop": [
      { "hooks": [ {
          "type": "command",
          "command": "~/src/claude-code-usage-statusline/claude-code-usage-statusline.py --mode cost --no-usage-text --force-newline --mark-spacing",
          "timeout": 20
      } ] }
    ]
  }
}
```

`--mark-spacing` is the default and is named on both invocations anyway, so
the settings file says which layout it wants rather than inheriting one. Add
`--no-column-rules` to the status command for plain gaps between the columns
instead of the faint borders.

## Options

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

`--no-mark-spacing` works in both modes and changes both. On the status line
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
[Rules between the columns](#rules-between-the-columns).

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

**No field is narrowed for it yet, deliberately.** Every reservation keeps the
width it had, so a shorter figure gets one more column of leading pad and the
grid cannot tear on the switch — verified across both modes at six widths: not
one row changes width. The saving is real (`LIM_FIG_W` could go 4 → 3, three
columns back on the 🔋 row) but it is only bankable once a probe has measured
these glyphs on the terminal in use. East Asian Width calls the block Neutral,
so `vis_width` already returns 1 — and there is a known trap one block along
where the standard and the terminal disagree, which is why the standard is not
taken as the answer. Holding the widths still means that if the terminal draws
these two columns wide, the damage shows up as a figure overrunning its own
cell rather than as a whole row shifted: a diagnosis instead of a mystery.

`--cols N` works in both modes and overrides the terminal-width walk; `0` means
"pretend the width is unknown", which is the only way to exercise the fallback
layout deterministically.

The four removing switches all default to ON — i.e. everything is drawn unless
asked otherwise — so a bare invocation is the full readout.

## The layout rule

Every value is formatted to a fixed number of columns (significant digits,
never decimal places — see `humanize`) and every segment occupies a reserved
width whether or not it has content (see `seg`). A group of segments is
therefore a constant width regardless of session, and right-aligning that
constant puts each metric on a fixed screen column.

That is the whole point: **switching tabs must not move the numbers.**

A fixed width only holds if every figure has somewhere to go when it grows, so
each one carries a **unit** rather than more digits: `1.2k`, `4.5M`, `1.5h`,
`1.4M` months. 💰 was the exception until 2026-09-03 — it wrote $1235 as
`1235`, four characters jammed against the emoji on the status line and one
column too many on the cost line, where only the totals row ever carries the
big figure, so the two rows came out different widths and stopped stacking. It
now climbs the same ladder as everything else: `29.8`, `123`, `1.2k`, `12k`,
`1.2M`. The cost line is one column wider for the unit, which `place` takes
out of the label and never out of the numbers.

The cost line's two rows share one grid, and `place_stacked` — not `place` —
is what keeps them sharing it. It takes the layout decision ONCE, against the
tightest row, and shifts every row by its own chrome. Deciding per row is what
broke the stacking before: the rows do not get the same room, so as a window
narrows the first row crosses into the truncation path while the second is
still comfortably right-aligning, and every column below stops matching the one
above it. A row that has to cut its label now takes the others with it. All
short together beats one aligned and one not.

## Rules between the columns

The five right-hand columns are divided by a faint vertical rule at wide
enough widths:

```
👤💬 Why did the "Prompt Usage" line not stack …   | 🧩↑ 23M ↓837k  | 🎯 98٪  | 🔋 🎤 .13٪ 🎮 6.1٪ 💳 15٪ 🔜 6.7m  | 📅  2026-08-16
🤖💬 Two separate things, and the second one is …  | 🧠  11٪  115k  | 💰 115  | 🪫 🎤 .18٪ 🎮  33٪ 💳 87٪ 🔜 1.9d  | 🕐    02:23:20
📦repo  📁~/Workbench/…/marbled-godwit             | 🤖Opus5  📏1M  | ⚡🏃hi  | ⌛ 🎤   3m 👤   5h 🤖  4h Σ  9.3h  | 💾 +3.4k - 214
```

They are **on by default** and off with `--no-column-rules`.

**It costs no width.** `SEG_GAP` is four columns and the grid spends them
either way; the rule is painted into them, two columns after the cell on its
left and one before the cell on its right. So a ruled row and an unruled one
are the same width to the column, which is what makes it safe to switch the
rules off by width without anything moving.

**Why off-centre.** Four columns do not divide in two, and the eye does not
want them to here. A cell on this grid ends on a digit or a `٪` hard against
its right edge — `seg` puts the slack on the far side — and begins with an
emoji, which carries its own side bearing inside its two columns. One column
of air before an emoji looks like two before a digit.

**Why a rule at all**, when the columns already have gaps. Four blanks is a
gap next to `⚡🏃hi` and an expanse next to column 4's thirty-three, and white
space of a width that changes with its neighbours has to be re-measured on
every row before it reads as a division. A stroke on a fixed column does not.
The grid was always five columns; this is the first thing that says so.

**ASCII `|`, not `│` (U+2502).** The box-drawing character is the better glyph
by a distance — it is designed to join vertically, so a stack of three reads as
one line where three `|` read as three ticks — and it is
`east_asian_width` **Ambiguous**, which means a terminal may advance two
columns for it and be correct to. Two columns here does not cost a rule, it
costs every alignment to its right on all three rows. `--selftest` measures
glyphs against the live terminal; if it ever measures U+2502 at one column,
`SEG_RULE` is the one line to change.

**The ink is `F_SUM`'s**, the grey measured out of the SOON arrow's own bitmap
— 2.2:1 against the chat rows' background, far under any legibility threshold,
which is the specification rather than a compromise. A divider that has to be
read is louder than the readings it divides. What carries it is repetition: one
faint stroke is nothing, three stacked on one column for the height of the
readout is a line. Rules and receding marks are bound to one constant on
purpose — they are the same kind of thing, and two greys a few units apart
would read as an accident.

**When they are dropped** — `--no-column-rules` switches them off outright,
and `rules_on` drops them where the row cannot carry them. Any one of these is
enough:

| Condition | Why |
| --- | --- |
| `--no-mark-spacing` | The tight layout exists for terminals that cannot afford the readout at its designed width, and it pays for that by closing the blank inside every column-4 field. A layout just asked to give up space inside its own fields is not one to hand chrome to. |
| width below `RULE_MIN` (160) | Line 3 owes 113 columns before a single name is drawn — 95 of grid, the right margin, the gap, and the where-group's chrome. At 160 the project, path and branch share the 47 left, against the 22 `allocate_left` cuts them to at the floor. They are being trimmed there already; the threshold is not about avoiding the trim but about there being enough left after it. Below, the row closes on that floor. |
| width unknown | The fallback path flows line 3 leftwards with only `MIN_GAP` and estimates the pwd rather than fitting it — the shape the readout takes when it has run out of room. Guessing generous costs a rule drawn into a row that is already overrunning. |
| `--no-column-rules` | Asked for. `--column-rules` is the default and is accepted so a settings file can name what it wants. |

The flag is the ASK and `rules_on` is the ROOM, and they are separate on
purpose: asking never overrides a width that cannot hold them, so
`--column-rules` on a ninety-column terminal is a request that is not granted
rather than a row that overruns. The veto runs one way only. And because the
rules never take a column, the flag is ink and nothing else — `norules-01@196`
and `norules-04@196` pin exactly that, byte-identical to the ruled goldens once
the bars are turned back into spaces.

Dropping them buys no width back, because they never took any. The test is
what the row can carry: a divider earns its ink by separating things that have
room to be separate, and on a row cutting its names to stubs it is one more
thing between the reader and the readings.

The decision is taken once, in `render_status`, and passed to all three
`grid_row` calls. Three rows of one readout must agree — a rule on line 1 and
none on line 3 is worse than either — so the width is read where the readout is
assembled and not inside `grid_row`, which defaults to plain gaps for callers
outside that assembly (`--selftest` builds one).

There is deliberately **no rule between the chat text and column 1**. That
boundary is a computed pad, not a fixed gap, and a rule there would have to be
paid for in width rather than found inside it.

## Column 4 is a grid of its own

The three rows on the right of the status line share a four-field sub-grid,
33 columns wide, and it is the widest thing on the readout:

```
🔋 🎤 .98٪ 🎮 2.5٪ 💳 44٪ 🔜 2.4h
🪫 🎤 .09٪ 🎮 2.6٪ 💳 51٪ 🔜 4.6d
⌛ 🎤   5m 👤   6d 🤖  6h Σ  5.8d
```

`--no-mark-spacing` closes the blank after every mark, which is four columns —
one per field — and leaves the widest reading in each field touching the mark
that labels it:

```
🔋 🎤.98٪ 🎮2.5٪ 💳44٪ 🔜2.4h
🪫 🎤.09٪ 🎮2.6٪ 💳51٪ 🔜4.6d
⌛ 🎤  5m 👤  6d 🤖 6h Σ 5.8d
```

The switch is a literal space and not a wider field, which is the other way to
open the gap and the worse one: a wider field would put the slack inside the
alignment, where a short reading swallows it and the gap comes and goes with
the value. It also drags `LINE3_RESERVED` with it, and so how much of the pwd
survives when the terminal will not report a width — see `set_mark_spacing`.

Fields 0 to 2 are three scopes that widen left to right — 🎤 the turn just
answered, 🎮 this session, 💳 the account — each a mark and a value
right-aligned in `LIM_FIG_W`, divided from the next by a single space. Field 3
is a duration and its mark says which kind: 🔜 time until this window resets,
Σ time since the session opened.

**Why the duration goes last.** It led the column until 2026-08-28, and the
argument for that was a real one: a countdown asks the same question as the ⌛
directly below it, and the two share `RST_W`. They still do, and the three
durations still stack — they stack on the other edge of the column. What
leading cost was the arrangement's opening. Fields 0 to 2 are one sequence, a
scope widening a step at a time, and a reader met it a field in from the
column's edge with a figure of an entirely different kind standing in front of
it. Now the column opens on the narrowest scope, widens twice, and closes on
the one reading that is not a scope at all — the horizon those three are being
spent against.

**Every field is exactly as wide as its own widest reading**, which is what
makes this a grid rather than three rows of labelled numbers. Right-alignment
lands the last character of every value on one terminal column, so a ٪ sits
directly above the `m`/`h`/`d` of the duration below it — a units rule down the
column. Nothing is spent holding a mark off its figure: when a value is full
width it touches the mark that labels it, and a leading blank appears only on a
short reading, where it is the alignment and not a separator. The single space
between fields is the only real gap.

Three widths pay for that. The ⌛ row asks `dur_fmt` for two digits rather than
three — `6h`, not `6.4h` — everywhere except Σ, which keeps three because
field 3 is a column wider and the session's own age is the one duration here
read as a fact rather than as scale for something else. Σ is one column and 🔜
is two, so `S_SUM` pads Σ to two and the two marks stack. And field 2 alone is
`LIM_ACCT_W`, one narrower than the rest: the account percentage is a whole
number at both sources, so 0 to 99 needs two characters and 100 is not printed
at all — 💯 draws it.

**Σ is painted the colour 🔜 already is.** Not matched by eye: Apple Color
Emoji keeps 🔜 as a PNG in its `sbix` table, and the alpha-weighted mean of
its ink is `rgb(76,76,76)` at every strike from 20ppem to 160 — a flat neutral
grey with no hue in it at all, which is not what a glyph named SOON looks like
it should be. `F_SUM` is that value.

The mark takes it and the figure does not. On the two rows above, the
countdown's figure carries the row's colour while 🔜 paints itself this same
grey; the ⌛ row painted both halves periwinkle and was the one row where the
mark competed with the thing it labels. Now all three read the same way down
the column — a receding mark, a figure that carries the row — and Σ stacks
under 🔜 in ink as well as in position. It is dim, and measurably so: 2.2:1
against the chat rows' background. But that is the 🔜's own contrast, and this
only stops Σ from being the exception to it.

## One colour per limit row, and brightness for the rest

Hue on the 🔋 and 🪫 rows answers exactly one question — *which window is
this?* — and answers it the same way in every frame. 🔋 is green because it is
the battery, 🪫 red because it is the low one. Neither moves with what the
figures say.

Everything a row distinguishes inside itself rides on brightness instead:

| | 🎤 turn | 🎮 session | 💳 account | 🔜 reset |
|---|---|---|---|---|
| 🔋 5-hour | bright | bright | dim | bright under an hour, else dim |
| 🪫 weekly | bright | bright | bright | bright under an hour, else dim |

The 5-hour row dims its account figure and leaves the two this session owns at
full strength — those are what a reader can act on, and the account total is
context for them. The weekly row keeps all three bright, because by then the
total *is* the news.

**What this replaced.** Two hue ladders, on 2026-08-28. `limit_color` tiered
the 🔋 row green / amber / red on the account's consumption, and
`F_RST_FAR`/`MID`/`NEAR` ran the countdown down three shades of slate by its
unit. Between them a single row could carry three unrelated hues, none of them
the row's own — and because 🪫 was pinned red regardless, the same colour meant
"this is the weekly window" on one row and "over 90٪" on the other. A colour
that has to be decoded before it can be read is not doing the job colour is
for.

**What it cost.** The alarm. A 5-hour window at 95٪ now looks like one at 5٪,
because `limit_color`'s thresholds were the only thing that said otherwise —
`LIMIT_WARN` and `LIMIT_CRIT` went with the function that used them. The
figures still say it in digits, two fields to the left.

**Why two brightness levels and not three.** The reset ladder had three, so
one of its distinctions had to go. Hours-against-days went: a window that
resets tomorrow and one that resets this afternoon are the same news — not yet
— while one resetting inside the hour is the only reading on that field a
person acts on. Bright means that and nothing else.

**Why the turn figure is there.** Before it the row could say a session had
spent 2.5٪ of a window without saying whether that was one expensive turn or
forty cheap ones. It is the same quantity the cost line's 🎤 row prints, off
the same derivation and — see `_with_shares` — deliberately the same turn:
`prompts[-1]`, the last turn that made calls and was not a compaction, which
is character for character the selection `render_cost_line` makes. Taking
`turns[-1]` instead would let the two rows describe different turns whenever
the last thing that happened was a compaction.

**Why the marks and not a separator.** Two figures divided by `" / "` read as
"mine out of everyone's". Three do not divide that way, and once each figure
carries a mark the slashes are six columns spent repeating what the marks
already say. The marks also do something a separator cannot: they give the ⌛
row somewhere to stack. Without them the three rows want different field
widths — the limit rows carry no glyph inside a field and the ⌛ row's halves
carried two columns of one — so they could not be given one field width and
could not stack at all.

🎤 replaced 💬 here, on two grounds. 💬 was already spoken for: `E_HUMAN`
and `E_BOT` are the literals `👤💬` and `🤖💬`, so one picture meant "a line of
chat" on the left of the row and "the last turn" on the right, and nothing else
on the readout has two meanings. It is also a bright white blob sitting beside
a figure it is only there to label. A microphone still says what 💬 said —
what was just spoken — so the reading survives the move, on a glyph that is
dark-bodied and unclaimed.

🎮 replaced 🧮 for the session. An abacus said "summed", which is true of
every figure on the readout and so distinguished nothing; a controller says a
session is a thing you are *at* — it began when you sat down, and the figure
beside it is what this sitting has spent. It also clears the glyph bar more
cleanly than the mark it replaces: `U+1F3AE` is Unicode 6.0, where 🧮
(`U+1F9EE`) is Unicode 11 and was the one mark on these rows relying on a
terminal's newer tables.

🎤 and 🎮 are `E_ROW_PROMPT` and `E_ROW_TOTAL`, aliased rather than copied so
one quantity keeps one glyph wherever it is printed — which is why swapping
either mark moves the cost line's matching row with it. 💳 is the only addition. It names what
the figure actually is — the subscription, drawn down — and in doing so states
the caveat `calibration()` spells out: the account figure is not bounded by
this machine, because the scan can only see transcripts that sit on it while
the percentage it divides into counts a phone and the web app too.

A globe stood here first, on the argument that 💳 sits two fields from 💰 in
column 3 and two money pictures on one row invite the misread that retired 📆.
Overruled deliberately: 💰 is dollars this session and 💳 is percent of a plan
window, so the two are never confusable as figures, and the reading the card
buys is worth more than the separation the globe bought.

**100 is drawn, not spelled.** A limit figure that reaches 100 renders as 💯
instead of `100٪`. It is the one reading of that field which means the window
is gone, and a number is a weak way to say it when every other reading is also
a number; the glyph carries the percent sign inside it, so `E_PCT` is dropped
rather than doubled and nothing on the row moves.

It narrows exactly one field, and did not at first. `LIM_FIG_W` could not
follow it down, because `limit_pct` spends three characters at every magnitude
-- `5.4` and `.38` as much as `100` -- so retiring the hundreds case left the
widest percentage where it was. What changed is `LIM_ACCT_W`, the account
field alone: that figure is a whole number at both sources, so with 100 drawn
rather than spelled its widest reading is `99٪`, three columns. The glyph is
what makes that one field a column narrower than the two beside it. ⚠ was
considered alongside 💯 and is unusable -- U+26A0 is East_Asian_Width Neutral
and needs U+FE0F to draw as an emoji at all, the two-codepoint shape rule 2
exists to keep out.

**The cost line draws it too, and had to.** The second figure in a totals-row
🔋 or 🪫 cell and the figure beside the status line's 💳 are the
same reading from the same source. Until it did, the two readouts disagreed at
the one moment either of them matters: the status line drew 💯 and the cost
row printed `99٪` — not a rounding, but `pct`'s clamp, which is to say a figure
that was never true. That half of the cell is three columns and cannot hold
`100٪`, so the glyph is what makes the honest reading fit in both places. Both
now test the same threshold, `>= 99.5`, which is `limit_pct`'s own rather than
a round 100: one test, so the glyph and the string can never disagree about
where a window ends.

Nothing in the cost corpus went near 99.5, which is why the clamp sat there
being wrong without a failing case. `plan-full-01` is that case now.

**What it cost.** Column 4 went from 23 columns to 33, so the left half of
line 3 loses 10 — `LINE3_RESERVED` is 109 with the spacing on and 105 with it
off, and it is measured rather than estimated, so it has to be re-measured
whenever the column moves.

The ⌛ row's other two scope fields stay positional rather than scoped. 👤 and
🤖 split the age that Σ states, and there is no account-wide time to put under
💳. That was the compromise before this change too, one field narrower.

## Where one prompt's money went

A per-prompt 🔋 or 🪫 cell reserves the same width as the totals-row cell it
stacks on, so that the two emoji land in one column. The back half of that
reservation — the seven columns the row below spends on `💳 99٪` — was seven
blanks until 2026-09-03. It now carries where the prompt's money actually
went:

```
🔋+ 0.61٪ 📖 61٪          📖  re-reading the conversation so far   (cache_read, 0.1x)
🪫+ 0.04٪ 📝 15٪          📝  caching what this turn added         (cache_creation, 2x)
🔋  1.27٪ 💳 78٪          the totals row underneath, unchanged
🪫  0.18٪ 💳 16٪
```

**These are shares of the turn, not of the window**, even though the glyph
that opens the cell is a window's. That is the only form the field can hold:
the largest re-read on record cost \$1.46, which is 0.25٪ of a 5-hour window
and 0.08٪ of a weekly one, and this field is 💳's three *whole* columns —
both would draw `0٪`. Two decimals need eight columns where `C_LIM_TOT` has
seven, and widening it would unstack the two rows, which is the one alignment
this readout exists to hold.

**What the pair is for.** `/compact` and `/clear` reclaim 📖 and nothing else.
📝 is this turn's own new material — tool results, files read, the prefix the
next request will re-read — and shrinking the context does not touch it; what
neither accounts for is output, which cannot be reclaimed at all. So a turn
reading `📖 61٪` is one where compacting would pay, and `📝 55٪` is one where
it would save almost nothing however large 🧠 looks. Measured across this
program's own sessions the read share swings from 8٪ to 57٪, and the two most
expensive turns of one session sat at opposite ends of that spread — which is
the case for spending the columns.

It does **not** choose between `/compact` and `/clear`. Both shrink the
prefix; the difference is what is left (a summary, or the system prompt and
tool schemas) and what you are willing to lose. Nor does it carry the one-time
price of compacting — but the cost line already prints a compaction on its own
row, so both halves of the break-even are on screen.

A compaction issues no request of its own, so there is no cost to take a share
of and both cells go blank — the full seven columns, not an empty string. See
`share_half` for why that distinction matters: `seg` pads the cost row on the
**left**, so a short cell is not a gap at the end of a row but a whole cell
pushed right, off the column it has to stack on.

## The column after a cost-line mark

Every cell on the cost row is emoji, one column, then the value. What sits in
that one column is not the same thing twice, and the difference is why
`--no-mark-spacing` reaches two of the seven cells and not the rest.

On 🧠 💰 🔋 🪫 and ⌛🤖 it is a **sign**: `+` on the per-prompt row, a blank
on the totals row directly beneath it. Every figure on the upper row is what
one prompt added to the reading below it, and the blank underneath is what
lets the two stack digit under digit. That is content. Close it and the rows
come apart, which is the one alignment this readout exists to hold.

On 🧩 and 🎯 there was nothing in it at all, so those two follow the status
line's `MARK_SP` and give the column back under `--no-mark-spacing`. So does
the 💳 that divides the two halves of a totals-row limit cell, which is a
mark like any other. 📅 and 🕐 carry `S_DATE`/`S_TIME`'s hard space — the
status line's own column 5 constants — and so were already spaced on both
readouts.

**The account half is marked, not slashed.** A totals-row 🔋 or 🪫 carries
two figures about one window: what this session spent, and what the window has
consumed altogether. The second is the reading the status line puts beside 💳,
so it now carries 💳 here:

```
🔋  0.07٪ 💳 41٪          🔋  0.07٪ 💳  💯
```

It was a spaced `/` until 2026-08-27, and the note in the code claimed the
slash as *"the status line's idiom for exactly this pair"*. It never was one:
column 4 divides its four fields with marks and carries no slash anywhere. A
slash is also the one divider that says nothing about which half is which, and
it reads as "out of" — wrong twice over here, since the share is a percentage
of the same window rather than a part of the total beside it. `render_diff`
dropped its own slash on the same argument, that *"the signs already say which
half is which, so the slash was a column spent repeating them"*. The cost here
is one column with the spacing on and none without it: tight, `💳41٪` is the
same six columns `/ 41٪` spent.

The block's note read *"no separator between them: a two-cell glyph divides
itself from what follows better than a space does"* until 2026-08-27. Five of
the seven cells already disproved it; the sign column has been there as long as
the rows have stacked. The status line spent that day deciding the same
question the other way, and one readout arguing for the tight form while the
other defaults to the spaced one is the inconsistency — not either form.

## `"Stop says: "`, and the eleven columns

A `systemMessage` is not printed bare. Claude Code draws it in a bordered box
that indents content five columns (`"  ⎿  "`) and prefixes `"Stop says: "` —
sixteen columns that appear nowhere in the hook payload and cannot be measured
from inside the program. Both figures were read off a pasted row by counting
how far its 📊 sat from the screen's left edge.

Two consequences, and they are the two things most likely to be broken by an
innocent-looking edit:

1. **Without subtracting the chrome the row overruns, and the CLI *wraps* the
   tail onto a second line rather than truncating it.** The symptom to watch
   for is a second line, not a trailing ellipsis.
2. **`"Stop says: "` is printed against the FIRST line only.** Continuation
   lines get the five-column indent alone. So all the rows must ship as ONE
   `systemMessage` joined by `"\n"` — emitted as two messages the second gets
   the full sixteen columns and misaligns by eleven.

`--force-newline` is the eleven columns turned into a feature. Open the message
with a newline and that first line is spent on the prefix alone; every row
printed is then a continuation line, laid out against the smaller chrome, and
the block gets its eleven columns back for one blank line.

The program also does this **on its own, without being asked**, when the window
is too narrow to afford them — precisely when the block would have to cut its
labels with the prefix and would not have to without it. A window too narrow
either way keeps its first line: there the newline buys a slightly longer label
at the price of a whole row, and the label says the same thing every turn.

## Glyphs, terminals, and the naughty ones

Most of what is hard here is not the layout. It is that **JediTerm** — the
terminal JetBrains Rider embeds, and the one these rows are tuned for —
disagrees with every published width table about how many columns an emoji
occupies, and disagrees with ITSELF about how many it paints.

Three rules, all learned expensively:

1. **Never infer a width from which row looks wrong. MEASURE it.** Run
   `tests/probe-advance.sh` in a real terminal tab (it needs a controlling
   tty, which Claude Code does not have) and it reports the advance of every
   glyph by asking the terminal directly, with DSR. Four separate conclusions
   drawn from screenshots were later contradicted by that probe.
2. **Prefer single-codepoint pictographs from U+1F300 up**, nothing newer than
   about Unicode 9, and no variation selectors. A codepoint that defaults to
   TEXT presentation is drawn one column wide by some terminals and two by
   others; picking one buys a per-terminal alignment bug for a picture. The
   per-terminal override tables are empty because the glyph set holds to this
   — an invariant, not a coincidence, and the thing to defend when choosing
   the next glyph.

   **One glyph does not hold to it: 🤏 `E_ROW_COMPACT`, U+1F90F, is Unicode
   12.** It is kept, and it has caused no observed trouble, but it is an
   exception rather than the rule and this file used to claim there were none.
   It matters because the third `EAW_WIDE` correction below rests on this
   terminal's table predating Unicode 12; 🤏 sits just under the U+1FA70 block
   that correction covers, so it takes its two columns from the broad
   `0x1F300–0x1FBFF` range without anything having measured it. Before
   trusting it further, measure it — that is one `tests/probe-advance.sh` run
   in a Rider tab.

   Choosing a replacement, if one is ever wanted: single codepoint, `W` under
   the test below, at or under Unicode 9, no variation selector. 📉 U+1F4C9
   (Unicode 6.0) and 🔽 U+1F53D (6.0) both qualify and both read as "it got
   smaller". Note that the obvious candidate does NOT: U+1F5DC 🗜 is named
   literally `COMPRESSION` and is Neutral, Unicode 7, text-presentation by
   default — naughty on every count.
3. **Distinguish a layout bug from a paint bug before fixing either.** A layout
   bug moves a whole cell and survives a copy-paste of the row. A paint bug
   corrupts single characters (`1sm` for a value of `1s`) and vanishes in a
   paste, because the buffer is correct and only the screen is not. Ask for a
   paste; it settles the question instantly.

A glyph that breaks rule 2 is a **naughty** one. The test is cheap:

```sh
python3 -c "import unicodedata as u; print(u.east_asian_width('⌛'))"
```

`W` is safe. `N` and `A` are not — they are the codepoints terminals disagree
about, and `A` (Ambiguous) includes the em dash, which is why prose read in
JediTerm is written without one.

### Why `vis_width` is not a "correct" Unicode implementation

It counts per codepoint with no grapheme clustering, and uses a hand-maintained
width table rather than `unicodedata`. Both look like bugs and both are
deliberate. **Swapping in `wcwidth`, or `unicodedata.east_asian_width`, or any
correct implementation, breaks the alignment of every row.** The fix is
tempting and has been attempted before, so it is documented at each site in the
code as well as here.

`EAW_WIDE` began as a generated East_Asian_Width table and was then corrected
against the probe. The corrections are the point:

* `127462–127490` folds in the regional indicators — two columns EACH here, so
  a flag costs four, where a clustering terminal paints two.
* `127744–130047` is U+1F300 through U+1FAFF as ONE range where the generated
  table had a dozen with gaps. Every pictograph probed there came back two
  columns, including the ones EAW calls Neutral for defaulting to text
  presentation (🗑 🛢 🗓 🎟 🌡). The gaps mattered: those appear in
  conversation, and each one measured as a single column dragged its row out of
  line.
* U+1FA70–U+1FAF8 (Unicode 12 and later) is treated as one column, against what
  EAW says, because this terminal's table predates the block. That is what made
  🪟 leave a phantom character beside it.

`unicodedata` would get all three wrong. It ships UCD 13 on Python 3.9 and
answers what the standard says, which is a different question from what this
terminal does.

**Keep `EAW_WIDE` sorted.** The scan stops at the first range starting above
the codepoint, so an entry out of order is an entry never read.

### The glyph constants are the single source of truth

Characters are referenced everywhere by `E_*` name, never by literal, because
`tests/probe-advance.sh` derives what to measure by parsing those names out of
this file. A glyph left inline in a renderer is a glyph nobody measures — which is
how the probe's list drifted from the layout three times in two hours.

## What the two modes tell each other

They run in different processes under different launchers, so everything
crossing between them goes through a file, and the paths are overridable so a
test cannot write to the thing it is testing.

| channel | why |
|---|---|
| `PLAN_CACHE` (`/tmp/claude-plan-limits.json`) | the status line publishes the plan figures it took from Claude Code's payload, so the cost rows quote the SAME ones. Two sources exist — the payload's `rate_limits` and the menu-bar app's snapshot — and `load_limits` is all-or-nothing between them |
| `CALIB_CACHE` (`/tmp/claude-calib-cache.json`) | the cost of everything on this machine inside each plan window, keyed by the windows it was measured over. Scanning transcripts is too slow to redo per turn; dividing by a percentage is free, so the division is NOT cached |
| `$TMPDIR/claude-statusline-ctxwin-<session id>` | the Stop payload carries no model, and the transcript records both Opus variants as plain `claude-opus-5`, so the cost line cannot tell a 200k window from a 1M one. Guessing from the largest reading seen fails exactly where it matters — it is *compacting* that keeps a 1M session under the 200k line, so a well-kept session never proves its window and every 🧠 figure runs 5× high |

`/tmp` rather than `TMPDIR` for the first two, deliberately: the status line has
been observed writing its caches to `/tmp` while the Stop hook's `TMPDIR`
pointed inside `/var/folders`. A path that resolves differently per process
cannot be a channel between them.

### One snapshot per render

Both readouts print two plan-limit cells, and each cell needs three things
from the same reading: the percentage after the `/`, the window boundary the
session share is summed over, and the dollars-per-point it is divided by.
Those used to be fetched by three functions that each read the source
independently, so one render could mix three provenances — and did.

Measured on 2026-08-25 at 22:30. The plan cache expired during a reading gap,
the fallback to the menu-bar app was unconditional, and the app's snapshot was
three hours old:

```
cost row     🔋 10.2٪ / 66٪    🪫 1.33٪ /  6٪
status row   🔋   38٪ / 38٪    🪫    10٪ / 10٪
```

(The status row's own left figure is a separate defect, below: it came from
the subtraction this release also removes.)

The `66٪` is the PREVIOUS 5-hour window, read just before it reset at 19:40.
The boundary came from that same expired snapshot, so five extra hours of
turns were charged to a window that had not opened when they ran — `10.2٪`
against a true `0.56٪`. The unit, meanwhile, came from a fresh reading another
session's hook had cached moments earlier.

Two rules now:

* **`limits_snapshot()` chooses once per process**, and everything downstream
  takes what it chose. A render is one process, so there is nothing to keep in
  sync.
* **"Fresher" is measured, not assumed.** Each source says when its reading was
  taken — the app in its own `as_of` field, which the program used to throw
  away, and the plan cache in one written beside the figures — and
  `_reading_age` compares them. An expired cache is not evidence that the
  other source is newer; the menu-bar app polls on its own schedule and can be
  hours behind.

The calibration cache is the third way a unit could disagree with the figure
beside it, so it stores the **scan** rather than the ratio: the two window
costs, keyed by the boundaries they were measured over, and — since
2026-09-03 — the two plan readings they were measured *with*. The division
happens on every call, against that stored pair. The cache is then invalidated
by the only event that invalidates it — a reset, which moves a boundary.

Storing the reading beside the scan is what stops the unit being estimated
across two moments. It used to divide a cached numerator by a live
denominator, which is harmless while nothing moves between them and wrong by
any factor you like at a **reset**, where everything does: the scan is written
seconds into the new window holding seconds of spending, the reading climbs
while it sits there, and the unit comes out far too small. Every share divided
by it is then far too large. Observed on 2026-09-03: `🎤 18٪` under an account
total of `💳 1٪`, a part eighteen times the whole it belongs to. Measured at
one instant this cannot happen — a session's transcripts are *in* the scan, so
its cost is at most the scan's and its share at most the reading's.

Below `CALIB_MIN_PCT` no unit is derived at all and the shares print `?`.
`used_percentage` arrives quantised to whole percent, so a reading of 1 is a
band half a point wide either side — the unit is uncertain by a factor of
three, and so is anything divided by it. Two is where a figure stops being
wrong by more than itself. It costs the 🔋 shares for the first few minutes of
each 5-hour window; the weekly row sits above the floor for all but the first
hours of a week.

### The session's share of a window

Both readouts derive it the same way, through `session_shares`: sum this
session's own turn costs since the window opened, divide by dollars-per-point.

A turn is **split** at the boundary rather than tested against it, through
`turn_cost_since`. A turn is not an instant — it can run dozens of calls over
many minutes — and until 2026-09-03 it went whole to whichever window its
*prompt* was typed in, which after a reset is the window that has closed.
Measured on the turn that exposed it: prompt at 14:57:32, window open at
15:00:00, `$1.02` billed across 13 calls before the reset and `$3.85` across
43 calls after it. All `$4.87` went to the closed window, and the row reported
this session's share of the live one as `0٪` — under a 🎤 cell reporting the
same turn at `18٪`, because that cell had no window bound on it at all. The
machine-wide scan had always split per record; the per-session tally was the
only place a turn was still atomic.

Both figures now go through the split, so the ordering column 4 asserts merely
by existing — 🎤 ≤ 🎮 ≤ 💳, one window read at three scopes — holds by
construction rather than by no window happening to reset mid-answer.

The status line did not, until 2026-08-25. It subtracted the plan-wide reading
this session first saw from the plan-wide reading now, storing the baseline
per session id. A difference of two plan-wide readings contains every other
session's consumption over the interval, and the baseline only ever moved
**down** — rewritten whenever the reading fell, correctly reading a fall as a
window reset.

Which destroys the figure the first time a session outlives a window, and the
5-hour window resets every five hours. At the reset the reading goes to zero,
the baseline follows it to zero, and nothing raises it again, so `now - 0` is
the plan-wide total from then on. Both halves of the cell print the same
number, and the cell stops saying anything:

```
status row   🔋 🔜  23m   62٪ /  62٪      cost row   🔋 16.2٪ / 62٪
             🪫 🔜 6.5d    6٪ /   6٪                 🪫  1.57٪ /  6٪
```

The 4.4 weekly points between `6` and `1.57` were other sessions, charged to
this one. What the subtraction could see and the sum cannot is usage from
another machine — a phone, the web app — which made it a true ceiling. A
ceiling that sits at 100٪ of the window for the rest of the session is not
worth the column.

## A turn is not always something the user typed

Every figure on the `🎤` row, and every window the `🔋`/`🪫` shares are summed
over, rests on one question: which records OPEN a turn. A typed prompt is the
obvious answer and was for a long time the only one. It is not enough.

Four kinds of message are delivered to a session that is sitting idle, and the
session answers each of them exactly as it answers a prompt. Claude Code writes
all four the same way — `type: user`, `promptSource: "system"` — and across the
130 transcripts on this machine that field marks nothing else:

| what arrives | count | opens with |
| --- | --- | --- |
| `<task-notification>` — a background task finished | 253 | `<` |
| a message from another session | 92 | `Another Claude session sent a message:` |
| a cross-session idle notice | 6 | `[Cross-session idle notice]` |
| the usage limit resetting | 4 | `Your claude.ai usage limit has reset.` |

Refusing them was not a labelling error. `read_turns` drops assistant records
that arrive before the first recognised prompt — there is no turn to attribute
them to — and a wake message is very often the FIRST thing in a transcript,
because another session writes to a session its user has not typed into yet.
Measured in one such session: **74 of its 87 requests, 15.7M of cache-read and
112k of output**, reported by no row and counted in no total, with the `Stop`
hook printing `📊 (no prompts recorded yet)` 37 minutes in. That is the whole
of "the cost line doesn't print when the answer came from another session".

Where a typed prompt did come first, nothing was lost but everything was
misfiled: the wake turn's requests went onto the typed prompt's turn, so the
`🎤` row reprinted the previous prompt with the peer turn's figures added — the
same prompt twice, growing. And where the preceding turn was a `/compact`, the
row for the peer work disappeared a second way: `render_cost_line` excludes
compaction turns from the prompt it reports, so 22 requests went onto a turn
the `🎤` row is not allowed to name.

**What still keeps a record out**, and why the obvious tests do not work:

* the `<` prefix cannot be the test — `<task-notification>` opens with it and
  so does every tool result;
* `isMeta` cannot be the test — a peer message carries it and so does a system
  reminder;
* so `promptSource` is the test, and the two branches are checked separately.

A message that arrives while the assistant is WORKING is a different thing and
is still not a turn: it gets no `type: user` record at all, only a queue
`remove` whose content opens with `<`. Of the 355 wake records here, not one is
preceded by an assistant record or a tool result — every one sits at a turn
boundary. A batch delivered together opens one turn each, the earlier ones with
no requests under them, which is the queue-drain case the reporting rule
already steps past.

One quiet consequence: `read_transcript` measures answering time between turn
starts, so a session that sat idle for twenty minutes and was then woken had
those twenty minutes charged to the previous turn as work. It no longer does.

## Compaction is reported exactly once

A compaction is the one costly thing in a session that nothing else accounts
for. It writes no usage record, so it is absent from this line's own totals and
from any tally built the same way. And it gets no `Stop` of its own — `/compact`
is a local command, so the first opportunity to report it is the next answered
prompt, one turn later, as its own row.

`Turn.reported` — the transcript's own record of where the last `Stop` ran — is
what buys "exactly once" without keeping state between invocations. The
prompt-pairing rule is only the fallback, for a transcript with no such record,
because it can print ZERO times: it assumes every `Stop` sees its own prompt,
and the transcript is not flushed in step with the hook.

That last fact is worth stating on its own, because it looks like a bug in the
reader: **a turn's assistant records can still be missing from the `.jsonl` when
the `Stop` hook reads it** — observed 1.2 s after their own timestamps. Hence
`read_turns_settled`, which polls for up to 1.5 s.

## Tests

The tests live in `tests/`, beside the program. They did not until
2026-08-28: ten of the thirteen status payloads read a real 8.7 MB session
transcript under `~/.claude/projects/`, which is somebody's actual
conversation. Both corpora are generated now — `mkcorpus-status.py` and
`mkcorpus-cost.py` write their fixtures into the scratch directory at the top
of every run — so nothing in here belongs to anyone, and a fixture cannot
drift away from the generator that describes it.

```sh
bash tests/golden.sh              # status mode, 112 comparisons — seconds
bash tests/golden-cost.sh         # cost mode, 65 comparisons — seconds
bash tests/py39-floor.sh          # the claimed 3.9 floor, checked — seconds
tests/compaction-once.py          # replay real sessions — MINUTES, see below
./claude-code-usage-statusline.py --selftest    # needs a real tty
bash tests/probe-advance.sh       # needs a real tty; measures, does not assert
```

The first three must end `fail 0   missing 0`. A deliberate layout change is
accepted with `--regen` **after reading the diff** — that is the step where a
regression gets blessed as the new expected output.

The first three are also what CI runs, on every push, over Python 3.9 and
3.13, plus `shellcheck` over `tests/*.sh` — see
`.github/workflows/tests.yml`. The last three are NOT in CI and cannot be: two
of them need a controlling tty and, more than that, the specific terminal
whose widths are in question, and a runner's answers about a JediTerm layout
would be worse than no answer. The third has no real transcripts to replay on
a runner.

**Run the suites from a directory macOS does not guard.** Under `Documents`,
`Downloads` or `Desktop`, TCC can make Python's import machinery raise
`PermissionError: [Errno 1] Operation not permitted` part-way through a run,
which reads as a fault in the program and is not one.

`--selftest` is the only check that catches a glyph which measures correctly and
paints wrong, and it needs a real terminal tab. Run it in each terminal, and
look at the drawn rows as well as the numbers.

`tests/README.md` carries the rest, including what the generated session is
built to reach and why the differential test against the two programs this one
replaced was retired.

`compaction-once.py` is the one test that still reads real sessions: the rule
it checks is about a SEQUENCE of Stop hooks across a whole conversation, so it
replays whatever transcripts this machine has under `~/.claude/projects/`. It
records nothing, so it takes no fixture with it. **It costs minutes, not
seconds** — its runtime scales with the reader's history, and one recent run
read 149 sessions to find the 28 with a compaction in them and took over ten
minutes. Give it no timeout, or a generous one.

## TODO

Known and deliberate, rather than discovered by a reader. Entries leave this
list when they are done; git history is the record of what was.

**Before the repository is public**

1. There is no remote yet — this is a local repository — so nothing about it
   is set. Three things at creation time, the first of which cannot be fixed
   afterwards without dragging the CI badge, every link and anyone's clone
   along with it: the default branch is `master`, not the `main` GitHub will
   offer. Then the description and the topics. The name deliberately does not
   name the `Stop` hook, so the description is where that has to happen.
   Drafted:

   > **Description** — A Claude Code status line and per-turn cost readout in
   > one program: token spend, plan limits, and answering time, drawn as a
   > fixed grid that stays aligned in JediTerm.
   >
   > **Topics** — `claude-code`, `statusline`, `status-line`, `cli`, `python`,
   > `terminal`, `tui`, `unicode`, `east-asian-width`, `jediterm`,
   > `token-usage`, `cost-tracking`, `developer-tools`, `macos`

   The badge and the *Install* line now name
   `github.com/nhooey/claude-code-usage-statusline`, so that owner and that
   name are no longer free choices — both are dead links until the
   repository exists at exactly that path.

**Unverified — each needs a real terminal tab, so no runner and no agent can
close it**

2. `--selftest` has never been run against a real terminal for four of the
   glyphs it now draws — 🎤 💯 💳 🎮 — nor for the `|` column rule at the
   width the grid assumes for it. Everything else in the layout is measured;
   these are inferred from the width tables, which is exactly the situation
   `--selftest` exists to end. The command is in the run block in
   `tests/README.md`.
3. Three width assumptions have never been measured, all the same shape — a
   character taking its width from a range rather than from a probe:
   * 🤏 `E_ROW_COMPACT` is U+1F90F, **Unicode 12**, which breaks the version
     half of rule 2 under *Glyphs, terminals, and the naughty ones*. Kept
     deliberately: it has caused no observed trouble. But the third
     `EAW_WIDE` correction rests on this terminal's table predating Unicode
     12, and 🤏 sits just under the U+1FA70 block that correction covers.
   * ▴ `E_UP` and ▾ `E_DOWN` are U+25B4 and U+25BE, both **East_Asian_Width
     Neutral**, so they pass the naughty test and `vis_width` calls them one.
     Neutral is where the table puts them, not where a probe found them:
     neither has been measured. They replaced ↑ U+2191 and ↓ U+2193, which
     were Ambiguous — one column or two depending on terminal and locale —
     and they sit on every row of the token field, so a wrong inference will
     not be subtle.
   * If either ever has to move at equal width, the other Neutral pair is
     ⌃ U+2303 / ⌄ U+2304. Note ▲ U+25B2 and ▼ U+25BC are Ambiguous while
     their *small* counterparts are not — same shape, different width class.

   `tests/probe-advance.sh` in a Rider tab settles all three at once.

**Cleanup**

4. Column 1 of the status line renders empty on a default-style session with
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
the profiles, the naughty-glyph rules above. That is the part to lift out
first when the filter arrives.

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
| Git, Plan limits | `detect_git`, `load_limits`, `calibration`, `turn_cost_since`, `window_shares`, `session_shares` |
| Status-line segment renderers, Status-line layout | `--mode status` |
| Cost line | `cost_group`, `cost_totals_group`, `stack_metrics`, `place_stacked`, `render_cost_line` |
| Alignment self-test | `--selftest` |
| Entry points | `main_status`, `main_cost`, `USAGE` |

The code comments are deliberately dense, and this README duplicates the parts
of them that are worth knowing before you open the file rather than while you
are standing at one line of it. Where a comment is the better place for a
detail — a single field's width, one function's failure mode — it stays there,
and this file does not repeat it.

## Style

Pure functions over frozen `NamedTuple` records. Nothing reads mutable module
state; the module-level names are constants, and the few that depend on the
terminal are computed once at import and passed as default arguments so a test
can substitute them.

## License

MIT — the full text is in [`LICENSE`](LICENSE). The SPDX identifier is `MIT`
and the canonical text is published at <https://opensource.org/license/mit>.

`LICENSE` held a *reference* to the text rather than the text until
2026-08-28, which was tidier and wrong: automated licence detection, GitHub's
included, reads the text and not a pointer to it, so the repository showed as
unlicensed. The text is pasted in, unmodified.
