# Layout and rendering

How the grid is built, why every figure has a fixed width, and what each
colour and mark on it means.

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

