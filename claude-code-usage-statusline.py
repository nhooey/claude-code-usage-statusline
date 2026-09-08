#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Code status line and prompt-cost line, in one program.

Two readouts, two modes, one set of facts:

    --mode status   stdin: the status-line JSON payload
                    stdout: three rows, redrawn continuously
    --mode cost     stdin: the Stop-hook JSON payload
                    stdout: {"systemMessage": "<two rows>"}, once per turn
    --selftest      draws specimen rows on the tty and asks the terminal
                    where the cursor landed; needs a real terminal tab

They were separate programs in separate languages (statusline.sh and
cost-line.py plus its hook), sharing glyphs, column widths, billing weights
and a whole width-measurement layer by copy.  The copies drifted, and the
drift could only be repaired by hand because nothing could be imported across
the language boundary.  This file exists so those facts are stated once.

── BEFORE YOU EDIT: READ README.md ─────────────────────────────────────────

It carries what is worth knowing BEFORE opening this file, rather than while
standing at one line of it.  Four things in particular, each of which has
cost time to relearn and each of which is short there:

  * "Glyphs, terminals, and the naughty ones" — JediTerm disagrees with every
    published width table AND with itself, so widths are MEASURED, never
    inferred from which row looks wrong.  Also how to tell a layout bug from
    a paint bug, which is the first question to settle, not the last.
  * "Why vis_width is not a correct Unicode implementation" — it counts per
    codepoint with a hand-maintained table.  Both look like bugs and both are
    deliberate.  Swapping in wcwidth or unicodedata.east_asian_width breaks
    the alignment of every row; it is tempting and has been attempted before.
  * "The layout rule" — fixed field widths, fixed segment reservations, one
    right-aligned constant.  Switching tabs must not move the numbers.
  * '"Stop says: ", and the eleven columns' — the chrome the cost line is
    laid out against, and why its rows ship as ONE systemMessage.

Style: pure functions over frozen NamedTuple records.  Nothing here reads
mutable module state; the module-level names are constants, and the few that
depend on the terminal are computed once at import and passed as default
arguments so a test can substitute them.  Standard library only, and written
to run on Python 3.9 — the macOS Command Line Tools interpreter — so it works
in any project, not only one whose devshell supplies newer packages.
"""

import fcntl
import functools
import glob
import json
import os
import plistlib
import re
import struct
import subprocess
import sys
import termios
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

# ════════════════════════════════════════════════════════════════════════════
# Glyphs.
#
# Single source of truth for the characters.  Referenced everywhere by name,
# never by literal — probe-advance.sh derives what to measure by parsing the
# E_* names out of this file, so a glyph left inline in a renderer is a glyph
# nobody measures.
#
# The invariant, restated because it is the thing that keeps the override
# tables empty: every glyph here is ONE codepoint, none newer than Unicode 9,
# and none carries a variation selector.  README, "Glyphs, terminals, and the
# naughty ones", for the rule and the one-line test for a new glyph.
# ════════════════════════════════════════════════════════════════════════════
E_HUMAN = "👤💬"       # chat row prefix — user.  U+1F464, Unicode 6.0, single
                       # codepoint, two columns — same width as the 👨 it
                       # replaced, so no field moves.
E_BOT = "🤖💬"         # chat row prefix — assistant
E_PROJ = "📦"          # project name
E_DIR = "📁"           # pwd
E_GIT_OK = "🌿"        # branch, clean tree
E_GIT_BAD = "🍂"       # branch, dirty tree
E_DIRTY = "✱"          # dirty marker, after a dirty branch name
E_PR = "🔀"            # PR number
E_MOD = "🤖"           # model
E_TOK = "🧩"           # ▴/▾ tokens
E_UP = "▴"             # input tokens, inside the 🧩 segment.  U+25B4 BLACK
                       # UP-POINTING SMALL TRIANGLE.
E_DOWN = "▾"           # output tokens, likewise.  U+25BE BLACK DOWN-POINTING
                       # SMALL TRIANGLE.
                       #
                       # These were ↑ and ↓ (U+2191/U+2193) until 2026-08-28.
                       # Both of those are East_Asian_Width AMBIGUOUS, the
                       # class that is one column on some terminals and two on
                       # others -- the same property that keeps the em dash out
                       # of this file's prose.  They are absent from EAW_WIDE,
                       # so vis_width called them one and JediTerm agreed;
                       # nothing was ever observed to be wrong.  But they sit
                       # in the token field, which is on EVERY row of both
                       # readouts, so an Ambiguous character resolving the
                       # other way would not have been a small failure.
                       #
                       # U+25B4 and U+25BE are NEUTRAL rather than Ambiguous:
                       # not East Asian at all, and drawn one column by the
                       # terminals that disagree about ↑.  Both are Unicode
                       # 1.1, so font coverage is as good as it gets, and they
                       # are a matched pair from one block.  That last part is
                       # not free either: ⇧/⇩ (U+21E7/U+21E9) and ˄/˅
                       # (U+02C4/U+02C5) look like pairs and are not -- each
                       # splits across Ambiguous and Neutral, so the up mark
                       # and the down mark can resolve to DIFFERENT widths and
                       # break the field against itself.
                       #
                       # Still naughty by README rule 2's literal test, which
                       # calls everything but W naughty.  That test cannot
                       # approve any one-column mark, because W means two
                       # columns, so it does not decide this field.  Neither
                       # pair has been probed; that is a TODO.
E_FOLD = "¶ "          # stands in for a newline when chat text is flattened
E_CACHE = "🎯"         # prompt-cache HIT rate — the glyph names what is
                       # measured rather than the mechanism.  It also keeps
                       # the row free of variation selectors: ♻️ (U+267B+VS16)
                       # held this slot twice and cost more than every other
                       # glyph together — drawn as "♻ ?" where the terminal
                       # would not compose it, ink spilling onto the first
                       # digit, and a different measured width in each of two
                       # terminals.  U+1F3AF is one codepoint, Unicode 6.0,
                       # two columns everywhere, and asks nothing of anybody.
E_CTX = "🧠"           # context-window occupancy / growth
E_COST = "💰"          # cost
E_DIFF = "💾"          # +adds/-removes
E_EFF = "⚡"           # reasoning effort — the fixed part, so the segment is
                       # found by the same icon whatever the level
E_WIN = "📏"           # context-window size, beside the model that has it.
                       # Deliberately from the Unicode 6.0 range: 🪟 (U+1FA9F)
                       # and 🪣 (U+1FAA3) both read better and both come from
                       # the Unicode 13 block this terminal carries loose
                       # metrics for — painting past the two columns they
                       # advance and leaving debris on redraw.
E_RESET = "🔜"         # marks a duration as time UNTIL: the figure beside it
                       # is a deadline, not a cycle.  A rotation glyph (🔄, ⟳
                       # before it) said only "something recurs here"; this one
                       # names the number, which is what earns its two columns.
E_EFF_LOW = "🐢"       # effort ladder, legible as a picture before it is read
E_EFF_MED = "🚶"       # as a word: the pace of the thing doing the work.
E_EFF_HIGH = "🏃"      # All five single-codepoint and EAW-Wide (the 🎚/🎛
E_EFF_XHIGH = "🚀"     # sliders are not, and would shift everything to their
E_EFF_MAX = "🔥"       # right by a column on some terminals).
E_STY = "🎨"           # output style
E_SUM = "\u03a3"       # Greek capital sigma, ONE column — the n-ary summation
                       # U+2211 sits inside the 2190-2BFF range this file
                       # treats as unmeasurable, and the column matters here
E_WAIT = "👤"          # time the session spent waiting for a person
E_WORK = "🤖"          # time it spent answering
E_DATE = "📅"          # calendar date, above the wall clock it belongs to
E_TIME = "🕐"          # wall clock.
                       #
                       # It was 🕰 (U+1F570), which reads better at terminal
                       # size, until the colons of the time beside it stopped
                       # drawing in JediTerm — while the same bytes rendered
                       # correctly in iTerm and a hexdump confirmed the colons
                       # were in the buffer.  The mechanism is font-run
                       # shaping: the renderer picks one face for a run, and
                       # having chosen the emoji face for 🕰 it draws what
                       # follows from that face too.  Apple Color Emoji carries
                       # digits (for keycaps) but no colon, so the digits
                       # survive and the colons come out blank.  Selecting text
                       # across the row went wrong too, which corroborates it.
                       # Neither symptom is a width error, so neither shows up
                       # in the probe: the only detector is the eye.
E_IDLE = "⌛"          # time since either side last wrote.  An hourglass reads
                       # as elapsed time as plainly as the ⏱ it replaced, and
                       # advances two columns where ⏱ advances one — which
                       # retired the last EAW_NARROW entry the layout depended
                       # on.
E_SESS = "🔋"          # 5-hour window consumed — a fixed reserve that drains
                       # with use and refills on a cycle, which is exactly what
                       # a rolling window is.  It also keeps the row from
                       # carrying three timepieces.  🪣 read as well and is out
                       # on mechanics: U+1FAA3 is Unicode 13, later than the
                       # cutoff the rest of this file observes, and it drew as
                       # a .notdef box once.
E_WEEK = "🪫"         # weekly window consumed — a drained battery under
                       # 🔋's charged one, two containers that drain, which is
                       # what these two rows are.  It replaced 📆 to stop the
                       # weekly limit wearing a calendar in a layout where 📅
                       # means the DATE two columns along; two calendars on
                       # one screen meaning different things is a misread
                       # waiting to happen.
                       #
                       # It then replaced 🛢, which said the same thing and
                       # could not be drawn reliably: U+1F6E2 has no default
                       # emoji presentation, so whether it advances one column
                       # or two is decided by whichever font the terminal
                       # happens to reach for, and Rider's kept tearing the
                       # grid to the right of it.  U+1FAAB is
                       # Emoji_Presentation=Yes — two columns everywhere, no
                       # width-table entry on any profile, no compensating
                       # pad.  That property is the reason it was chosen;
                       # a replacement for this slot needs it too.
# The three scopes column 4 reports, widening left to right: what the turn
# just answered consumed, what this session has consumed, what the account
# has.  Each MARKS a figure rather than naming a metric, so each is emitted
# bare and lets its field's padding supply the column of air, exactly as
# 🔜 and Σ do on the same rows.
#
# The first two are the cost line's own row marks rather than new ones:
# E_ROW_PROMPT and E_ROW_TOTAL below ARE these.  One quantity, one glyph,
# wherever it is printed — before this the two readouts had two
# vocabularies for one pair of figures, and the reader had to learn both.
E_TURN = "🎤"          # the turn just answered.  Not 💬, which was already
                       # spoken for: E_HUMAN and E_BOT carry a LITERAL 💬 in
                       # column 1, so one picture meant "a line of chat" on the
                       # left of the row and "the last turn" on the right.
                       # Nothing else here has two meanings, and 💬 keeps the
                       # one it had first.
                       #
                       # A microphone still says what 💬 said — what was just
                       # spoken — so the reading is not lost, only moved to a
                       # glyph that is dark-bodied instead of a bright white
                       # blob.  This field is read BESIDE a figure, not instead
                       # of one, so its mark has no business being the loudest
                       # thing in the cell.
                       #
                       # U+1F3A4, Unicode 6.0, single codepoint,
                       # Emoji_Presentation=Yes, inside EAW_WIDE.
E_SESSION = "🎮"       # this session, summed.  A controller, because a
                       # session is a thing you are AT — it started when you
                       # sat down and it ends when you stop, and the figure
                       # beside it is what this sitting has spent.  🧮 stood
                       # here first and said "summed", which is true of every
                       # figure on the readout and so distinguished nothing.
                       #
                       # It also clears the glyph bar more cleanly than what it
                       # replaces: U+1F3AE is Unicode 6.0, where 🧮 (U+1F9EE)
                       # is Unicode 11 and was the one mark on these rows
                       # relying on a terminal's newer tables.  Single
                       # codepoint, Emoji_Presentation=Yes, EAW W, inside
                       # EAW_WIDE.
                       #
                       # E_ROW_TOTAL is this, so the cost line's total row
                       # moved with it — one quantity, one glyph.
E_ACCT = "💳"          # the whole account.  A card because the figure is
                       # what the SUBSCRIPTION has been drawn down by, and a
                       # subscription is not bounded by this machine:
                       # calibration() can only scan transcripts that sit on it,
                       # while the percentage it divides into counts a phone and
                       # the web app too.  One account, one card — the glyph
                       # states the caveat the docstring makes.
                       #
                       # It does sit two fields from 💰 in column 3, and two
                       # money pictures on one row was the argument for the
                       # globe that stood here first.  Overruled deliberately:
                       # 💰 is dollars this session and 💳 is percent of a
                       # plan window, they are never confusable as figures, and
                       # the reading the card buys — this is the bill — is worth
                       # more than the separation the globe bought.
                       #
                       # U+1F4B3, Unicode 6.0, single codepoint,
                       # Emoji_Presentation=Yes — the bar every icon on
                       # these rows has to clear, and the reason 🟰 (Unicode 14)
                       # and 🧾 lost: the first is later than the blocks this
                       # file trusts, the second puts a second picture of a
                       # tally one row under 🎮, which is the misread that
                       # retired 📆.

E_READ = "📖"          # of ONE prompt's cost, the share that went on
                       # re-reading the conversation so far -- cache_read, at
                       # 0.1x a fresh token.  It is what the transcript
                       # charges simply for still being there, and it is the
                       # only component /compact can remove.  Measured over
                       # this file's own sessions it swings from 8٪ to 57٪ of
                       # a turn, and the two most expensive turns in one
                       # session sat at opposite ends of that spread -- which
                       # is the whole case for the cell.  It says whether
                       # shrinking the context would buy anything BEFORE you
                       # spend a compaction finding out.
                       #
                       # A SHARE OF THE TURN, not of the plan window, even
                       # though the cell it sits in is a window cell.  The
                       # window form was tried first and cannot be drawn: the
                       # largest such turn on record spent $1.46 re-reading,
                       # which is 0.25٪ of a 5-hour window and 0.08٪ of a
                       # weekly one, and this field is the three WHOLE columns
                       # 💳 uses.  Both would render "0٪" -- blank in effect
                       # at every magnitude that matters.  Two decimals would
                       # fit neither: they need eight columns where C_LIM_TOT
                       # has seven, and widening it would unstack the cost
                       # row from the totals row under it.  The share is a
                       # whole number in the same three columns, and it is
                       # the figure the decision turns on anyway -- what you
                       # would reclaim, as a fraction of what you just paid.
                       #
                       # An open book because the quantity is the
                       # conversation being read AGAIN, and because 🔁 means
                       # re-send: one glyph per direction.  U+1F4D6, Unicode
                       # 6.0, single codepoint, Emoji_Presentation=Yes, EAW W,
                       # inside EAW_WIDE.

E_WRITE = "📝"         # same denominator, the other component:
                       # cache_creation, at 2x.  This is the turn's OWN new
                       # material being cached -- tool results, files read,
                       # the prefix the next request will re-read -- which is
                       # why it belongs UNDER 📖 rather than beside it.
                       # /compact does not touch it, so a turn reading 📝 55٪
                       # is one where compacting would save almost nothing
                       # however large the context looks.  What the pair does
                       # not account for is output, which is neither and
                       # cannot be reclaimed at all.
                       #
                       # It takes the 🪫 row because a share of a turn does
                       # not vary by window: the read share printed on both
                       # rows would spend the second slot restating the
                       # first.  The two rows carry the two halves instead,
                       # which is the only arrangement in which both slots
                       # say something.
                       #
                       # U+1F4DD, Unicode 6.0, single codepoint,
                       # Emoji_Presentation=Yes, EAW W, inside EAW_WIDE.

E_COSTLINE = "📊"      # prefix of the prompt-cost row

E_HUNDRED = "💯"       # stands in for the "100" of "100٪" on a limit row.
                       # 100 is the one reading of that field which means the
                       # window is GONE, and a number is a weak way to say it
                       # when every other reading of the same field is also a
                       # number.
                       #
                       # E_PCT FOLLOWS IT, exactly as it follows a spelled
                       # figure.  Until 2026-08-28 it did not: the glyph
                       # already draws "100" with a percent sign inside it, so
                       # the sign was dropped as a doubling.  That reasoning
                       # was about the picture and not about the row.  Read
                       # DOWN the column -- "5.4٪", "44٪", "💯" -- and the one
                       # reading that matters was the only one not wearing the
                       # unit, which makes it look like a different kind of
                       # thing rather than the top of the same scale.
                       #
                       # It costs nothing to fix, which is why there is no
                       # trade to weigh: the glyph is two columns in a field of
                       # three, so it was already being padded with a leading
                       # blank.  "💯٪" spends that blank on the unit and the
                       # field is the same three columns it always was.  Both
                       # render sites do this, and both say so.
                       #
                       # ⚠ was asked for beside it and cannot be had: U+26A0
                       # is East_Asian_Width Neutral and needs U+FE0F to draw as
                       # an emoji at all, which is the two-codepoint,
                       # measures-one-draws-two shape that left 🪟 a phantom
                       # cell.  README rule 2 rules it out, the same rule that
                       # ruled out 🗨.
                       #
                       # It narrows exactly one field, and did not at first.
                       # LIM_FIG_W could not follow it down, because limit_pct
                       # spends three characters at EVERY magnitude -- "5.4"
                       # and ".38" as much as "100" -- so retiring the hundreds
                       # case left the widest percentage where it was.  What
                       # changed is LIM_ACCT_W: the account figure is a whole
                       # number, so with 100 drawn rather than spelled its
                       # widest reading is "99٪", three columns.  The glyph is
                       # what makes that field a column narrower than the two
                       # beside it.
                       #
                       # U+1F4AF, Unicode 6.0, single codepoint,
                       # Emoji_Presentation=Yes, inside EAW_WIDE.

E_PCT = "٪"            # percent sign — U+066A ARABIC PERCENT SIGN, not ASCII
                       # '%'.  One column, same as '%', and Bidi_Class ET
                       # exactly like it, so it neither costs a cell nor
                       # reorders the digits beside it in a left-to-right line.
                       # Chosen over '%' because it reads lighter beside the
                       # figure.  The two marks that look like the obvious
                       # answer are both traps: U+FE6A is *named* SMALL PERCENT
                       # SIGN and U+FF05 is the fullwidth form, and both are
                       # East_Asian_Width Wide — smaller as drawings, twice the
                       # width as cells.

# ════════════════════════════════════════════════════════════════════════════
# ANSI truecolor escapes.
# ════════════════════════════════════════════════════════════════════════════
R = "\033[0m"                              # reset
DIM = "\033[2m"                            # dim attribute
BOLD, UNBOLD = "\033[1m", "\033[22m"       # UNBOLD is 22 (bold off) and not 0
                                           # (all attributes off), so it cannot
                                           # stomp colour set around it.
F_BLU = "\033[38;2;100;170;255m"           # blue        — project name
F_BLU2 = "\033[38;2;70;115;185m"           # dark blue   — pwd
F_GRN = "\033[38;2;120;200;80m"            # green       — healthy / clean
F_AMB = "\033[38;2;255;200;0m"             # amber       — *_WARN thresholds
F_RED = "\033[38;2;255;90;90m"             # red         — *_CRIT thresholds
F_CYN = "\033[38;2;80;200;220m"            # cyan        — PR, output style
F_PUR = "\033[38;2;200;130;255m"           # purple      — model
F_PUR2 = "\033[38;2;140;91;179m"           # dark purple — model's second field
F_TUP = "\033[38;2;120;200;220m"           # teal        — ▴ input tokens
F_TDN = "\033[38;2;220;140;200m"           # pink        — ▾ output tokens
F_YEL = "\033[38;2;255;210;60m"            # yellow      — cost (never tiered)
F_PNK = "\033[38;2;255;120;190m"           # hot pink    — context %
F_PNK2 = "\033[38;2;178;84;133m"           # dark pink   — context size
F_CRM = "\033[38;2;211;215;207m"           # cream       — default text
F_PRW = "\033[38;2;140;150;255m"           # periwinkle  — the ⌛ row.  It was
                                           #  orange, and orange had the same
                                           #  problem F_AMB has: amber means "a
                                           #  threshold was crossed" everywhere
                                           #  else on these rows, and elapsed
                                           #  time is never a warning about
                                           #  anything.  Orange only stood a
                                           #  short way from that reading; blue
                                           #  cannot be given it at all.
                                           #
                                           #  Not F_BLU (📦) or F_BLU2 (📁),
                                           #  the two blues already on row 3.
                                           #  20.7 ΔE from the nearer, which is
                                           #  about the separation those two
                                           #  already keep from each other
                                           #  (21.7) while sitting side by
                                           #  side; these sit at opposite ends
                                           #  of the row.  L* 65 against the
                                           #  orange's 72, so the row keeps
                                           #  roughly the weight it read at.
F_CHAT_U = "\033[38;2;166;170;158m"        # warm grey   — user chat row
F_CHAT_B = "\033[38;2;112;126;140m"        # cool slate  — assistant chat row
B_DRK = "\033[48;2;12;14;18m"              # near-black background, chat rows

# The two limit rows, one colour each.  ROW IDENTITY, not a reading: 🔋 is
# green because it is the battery, 🪫 red because it is the low one, and
# neither hue moves with what the figures say.  Everything a row has to
# distinguish inside itself — this session against the account, a countdown
# against a consumption — is carried by brightness instead, so hue answers
# exactly one question here and answers it the same way every frame.
#
# It replaced two hue ladders on 2026-08-28.  limit_color tiered the 🔋 row
# green/amber/red on the account's consumption, and F_RST_FAR/MID/NEAR ran the
# countdown down three shades of slate by its unit.  Between them a single row
# could carry three unrelated hues, none of which was the row's own, and the
# colour had to be decoded before it could be read.  git has both if the alarm
# is wanted back on a channel of its own.
F_LIM_SESS = F_GRN                         # the 🔋 5-hour row
F_LIM_WEEK = F_RED                         # the 🪫 weekly row

# Σ, and Σ only — the ⌛ row's mark, in the colour the 🔜 above it paints
# itself.  MEASURED, not matched by eye: Apple Color Emoji stores 🔜 as a PNG
# in its sbix table, and the alpha-weighted mean of its ink is rgb(76,76,76) at
# every strike from 20ppem to 160 — a flat neutral grey, no hue at all, which
# is not what an emoji named SOON looks like it should be.  L* 32.3.
#
# It is the mark that takes this and not the figure.  On the two rows above,
# the countdown's figure carries the row's colour and 🔜 paints itself this
# grey; the ⌛ row painted BOTH halves F_PRW and was the one row where the mark
# competed with what it labels.  Now all three read the same way down the
# column — a receding mark, a figure that carries the row — and Σ stacks under
# 🔜 in ink as well as in column.
#
# It is dim on purpose and it is dim in fact: 2.2:1 against the chat rows'
# background, which is under every legibility threshold there is.  That is the
# 🔜's own contrast — this only stops Σ from being the exception.
F_SUM = "\033[38;2;76;76;76m"             # the SOON arrow's ink, sampled

# The rules between the grid's columns, deliberately the same ink as F_SUM.
# One chrome level and not two: a rule and a receding mark are the same kind
# of thing — structure the eye should find only when it looks for it — and
# two greys a few units apart would read as an accident rather than a
# distinction.  They are bound rather than typed out twice so they cannot
# drift; write a literal here if they ever need to differ.
#
# 2.2:1 against the chat rows' background, which is far under any legibility
# threshold — and that is the specification, not a compromise.  A divider that
# has to be read is louder than the readings it divides.  What carries it is
# that it repeats: one faint stroke is nothing, three stacked on one column
# for the height of the readout is a line.
F_RULE = F_SUM

# Erase the whole line before painting it, and again past the end afterwards.
#
# The rows redraw in place and the previous frame's ink survives anywhere the
# new frame does not overwrite — which happens constantly, because a glyph
# whose paint exceeds the cell it advances spills into its neighbour, and
# because a value that shrinks between frames ("1.2h" to "59m") leaves its old
# last character standing.  That is where "1sm" for a value of 1s came from.
#
# Erasing FIRST is what fixes it: clearing afterwards only wipes past the end
# of the new content.  The SGR reset ahead of it matters too — erase fills with
# the current background colour, and the chat rows set a dark one.
LINE_CLEAR = "\033[0m\033[2K"
EOL_CLEAR = "\033[K"

# ════════════════════════════════════════════════════════════════════════════
# Tunables.
# ════════════════════════════════════════════════════════════════════════════
MAX_ROW = 120          # max columns of chat text when the width is unknown
MAX_LINE = 165         # fallback row width when the terminal will not say
MARK_SP = " "          # what sits between a column-4 mark and its value.
                       # A space by default, "" under --no-mark-spacing.
                       #
                       # Everything in column 4 is right-aligned in a field
                       # exactly as wide as its own widest reading, so with
                       # this empty a full-width value TOUCHES the mark that
                       # labels it and the column takes four fewer columns —
                       # one per field.  That is the tighter readout and it is
                       # not the default, because the touching is the part
                       # people disagree about: 🎤.98٪ is one token to some
                       # eyes and a run-on to others, and the four columns it
                       # saves only matter on a narrow terminal.
                       #
                       # A literal space and not a wider field, which is the
                       # other way to open the gap and the worse one: widening
                       # the field would put the slack INSIDE the alignment,
                       # where a short reading would swallow it and the gap
                       # would come and go with the value.  A space is a space
                       # on every reading.
                       #
                       # Read at render time, so set_mark_spacing() can move
                       # it after import — see the four constants it drags
                       # along.
COL4_TIGHT_W = 29      # column 4 with MARK_SP empty; each of its four fields
                       # grows by len(MARK_SP)
LINE3_TIGHT = 105      # LINE3_RESERVED at COL4_TIGHT_W, measured
LINE3_RESERVED = 105   # columns the non-pwd segments of line 3 occupy.  It
                       # was 110 while column 4 was 34 wide and is measured,
                       # not estimated: shrink that column and this follows it
                       # down, or the pwd is held five columns shorter than the
                       # line can afford whenever the width is unknown.
PWD_MAX_FALLBACK = MAX_LINE - LINE3_RESERVED

RIGHT_MARGIN = 4       # columns held empty at the right edge, covering two
                       # things neither the payload nor the tty reports.
                       # First, the status line is drawn into an Ink box with
                       # wrap:"truncate" and that box is narrower than the tty:
                       # at 196 reported columns the cut fell at 193.  Second, a
                       # column of slack for any glyph a terminal draws wider
                       # than it declares.  Erring high is nearly free; erring
                       # low gets the clock chopped to "00:15…".
MIN_GAP = 2            # smallest gap between the left and right groups

# How the left group divides whatever the right group leaves it.  The three
# names compete for one budget, so a fixed cap each would either waste columns
# on a short name or crush a long one beside it.  Weights set the share of a
# contended budget; the same ranking decides who gets the rounding and who
# gives up a column first when a minimum must be met.  The branch is cut least
# — it is the shortest and every character is load-bearing.  The path is cut
# first: longest, most repetitive, and its head is echoed by the project name.
LWT_BRANCH, LMIN_BRANCH = 3, 6
LWT_PROJ, LMIN_PROJ = 2, 6
LWT_PATH, LMIN_PATH = 2, 10

LEFT_GAP = 2           # columns between 📦 project, 📁 path and 🌿 branch
W_STY = 6              # 🎨 + the style name's first 4 characters
VAL_W = 5              # a metric's first value field: "▴4.8M", "Opus5", " 142k"
VAL2_W = 6             # the second field — one wider, because one of them
                       # carries a glyph as well as a figure ("📏200k").  All
                       # three second fields share it, so output tokens,
                       # context size and window size right-align down the
                       # column.
PAIR_GAP = 2           # between two metrics sharing one cell (⌛ and 🕐)
LIM_PCT_W = 4          # the widest a limit percentage draws: three characters
                       # of figure plus the ٪ — see limit_pct for why three is
                       # enough and why the column it saves goes to "100".
LIM_FIG_W = 4          # the field each of the three marks right-aligns its
                       # value in, on all three rows of column 4.  EXACTLY as
                       # wide as the widest thing that can land in one —
                       # LIM_PCT_W above, and dur_fmt's three at digits=2 — so
                       # a full-width value touches its mark and nothing is
                       # spent holding it off.
                       #
                       # It was five until 2026-08-27, one wider than any
                       # reading, which put a blank column between every mark
                       # and every figure on every row.  That column was
                       # bought for the space it left in front of the NEXT
                       # mark, and the single space between fields already
                       # buys that; the mark and the figure it labels were
                       # paying for the gap after them.
                       #
                       # Right-aligned and not left, which is the other way to
                       # close the gap and the wrong one: the values have to
                       # stack.  Right-alignment lands the last character of
                       # every reading on one column, so the ٪ of a
                       # percentage sits under the m/h/d of a duration on the
                       # row below — a units rule down the column, not three
                       # figures that happen to start together.  The cost is a
                       # leading blank on short readings ("💳 44٪"), which is
                       # the alignment, not slack.
LIM_ACCT_W = 3         # field 2 only — 💳 the account, and 🤖 below it.  One
                       # narrower than the fields on either side of it, and it
                       # is the one field that can afford to be.
                       #
                       # A percentage there spends two characters because the
                       # account figure is a WHOLE NUMBER at both sources: the
                       # menu-bar app stores integers and Claude Code's payload
                       # has only ever been observed at whole values (see
                       # limit_pct).  0 to 99 is two characters exactly, and
                       # 100 is not printed at all — E_HUNDRED draws it.  So
                       # the column is given up for nothing, unlike 🎤 and 🎮,
                       # whose figures are ratios this program computes and are
                       # fractional for real.
                       #
                       # 🤖 fits because the ⌛ row's scope figures now ask
                       # dur_fmt for two digits: "12h" is three columns, and a
                       # unit still lands under a ٪.
RST_W = 6              # the countdown/elapsed field — column 4's LAST, shared
                       # by 🔋 📆 ⌛ so the three durations line up down it.
                       # Two columns of mark and four of figure, dur_fmt's
                       # widest at the default three digits ("5.8d").  🔜
                       # measures two; Σ measures one and is padded to two by
                       # S_SUM, so the field is one shape on all three rows and
                       # begins on one column.
                       #
                       # It led the column until 2026-08-28.  The argument for
                       # that was real — a countdown asks the same question as
                       # the ⌛ below it — but it put the one field that is not
                       # a scope in front of the three that are, so the reader
                       # crossed it to reach the sequence and the sequence
                       # started a field in from the column's edge.
SEG_GAP = 4            # columns between adjacent grid cells
SEG_RULE = "|"         # the divider drawn inside that gap, at wide enough
                       # widths.  ASCII, and not U+2502, which is what a box
                       # rule is for and is the better-looking glyph by a
                       # distance: it is east_asian_width AMBIGUOUS, so a
                       # terminal is within its rights to advance two columns
                       # for it, and two columns here does not cost a rule —
                       # it costs every alignment to the right of it on all
                       # three rows.  "|" is width 1 everywhere there is.
                       # --selftest measures glyphs; if it ever measures
                       # U+2502 at 1 on this terminal, this is the one line
                       # to change.
                       #
                       # It sits two columns after the cell on its left and
                       # one before the cell on its right, which is off-centre
                       # in the arithmetic and centred to the eye: a cell here
                       # ends on a digit or a ٪ hard against its edge and
                       # begins with an emoji, and an emoji carries its own
                       # side bearing.  Splitting the four columns evenly is
                       # not possible anyway.
RULE_MIN = 160         # narrowest row that still gets the rules.  Set against
                       # what line 3 owes before a single name is drawn, which
                       # is measured and not estimated: 95 columns of grid,
                       # RIGHT_MARGIN, MIN_GAP and the where-group's own chrome
                       # come to 113.  At this width the project, path and
                       # branch share the 47 that are left, against the 22
                       # allocate_left will cut them to at the floor — a bit
                       # over twice their minimum.  They are already being
                       # trimmed there and the point is not that they are not;
                       # it is that there is still enough room for the trim to
                       # leave something readable.  Below it the row is closing
                       # on that floor, and one closing on its floor has
                       # nothing to spend on chrome.
                       #
                       # Deliberately NOT MAX_LINE, which sits near it and
                       # answers a different question: that is the width to
                       # ASSUME when the terminal will not say, and this is a
                       # width the terminal HAS said.  Binding them would tie
                       # a guess to a measurement.

CTX_DEF = 200000       # context window for ordinary models
CTX_1M = 1000000       # context window for the *-1M-context variants
CACHE_WARN, CACHE_CRIT = 80, 50    # cache hit %: ≤ WARN amber, ≤ CRIT red
LIMIT_TTL = 60                     # seconds to cache a usage source's reading
LIMIT_CACHE = os.environ.get(
    "CLAUDE_LIMIT_CACHE",
    os.path.join(os.environ.get("TMPDIR", "/tmp"), "claude-usage-cache.json"))

# The one stamp format crossing every boundary in this program: the plan cache
# the two modes trade readings through, the reset times a usage source reports,
# and `as_of`, which decides which of two readings is quoted.  LOCAL time and
# minute resolution, because that is what the readout formats in and what the
# menu-bar app's own JSON emitted -- a channel that changed format would be a
# channel silently read wrong, and _window_starts parses with one strptime.
#
# Named once because it was written out five times, in four functions that
# have to agree about it, and nothing said they had to.
STAMP_FMT = "%Y-%m-%d %H:%M"
K, M, G = 1000, 1000000, 1000000000   # humanize boundaries

# The ladder humanize() and money_fmt() both climb, largest first.  One tuple
# rather than one per function because the two are read in the same glance —
# 🧩 and 💰 sit four columns apart on the cost row — and a "k" that meant a
# thousand in one field and nothing in the other would be worse than no unit
# at all.
#
# G is here for the reason the top step of any such ladder is: a figure that
# runs off the end of its units does not degrade, it overruns.  humanize
# without it writes 1.2e9 as "1234M", five columns in a field that reserves
# four, and the cell it pushes into is the one that has to stack.  Neither
# field reaches a billion today; the step costs one tuple entry, and the
# alternative costs a layout.
SI_UNITS = ((G, "G"), (M, "M"), (K, "k"))

# Billing weights relative to a fresh input token.  Raw ▴ traffic is ~99% cache
# reads in a typical session, so an unweighted sum says nothing about either
# cost or context size.  The write weight is TTL-dependent — 1.25x at the
# 5-minute default, 2x at the 1-hour TTL these sessions run on.
W_CACHE_WRITE, W_CACHE_READ = 2.0, 0.1

# Opus 5 list price, USD per token, for the cost line's per-prompt figure.
P_IN, P_OUT, P_CR, P_CW = 5e-6, 25e-6, 0.5e-6, 10e-6

# Per-model prices for the calibration scan, which sees other sessions' turns
# and so cannot assume one model.  $/token: fresh, output, cache-read,
# cache-write at the 2x TTL.
MODEL_PRICE = (
    ("opus", (5e-6, 25e-6, 0.5e-6, 10e-6)),
    ("sonnet", (3e-6, 15e-6, 0.3e-6, 6e-6)),
    ("haiku", (1e-6, 5e-6, 0.1e-6, 2e-6)),
)

# ── Cost-line geometry ──────────────────────────────────────────────────────
# Reserved widths for the prompt-cost row: emoji (2), one separator column,
# then the value field.
#
# That middle column is not the same thing on every cell, and the difference is
# why MARK_SP reaches some of them and not others.  On 🧠 💰 🔋 🪫 and ⌛🤖
# it holds a SIGN -- "+" on the per-prompt row, a blank on the totals row
# directly beneath it -- and that is content, not spacing: close it and the two
# rows stop stacking digit under digit, which is the one alignment this readout
# exists to hold.  On 🧩 and 🎯 there was nothing in it at all, so those
# two follow the status line's MARK_SP and give the column back under
# --no-mark-spacing.
# So does the 💳 that divides the two halves of a totals-row limit cell, which
# is a mark like any other -- see C_LIM_TOT.  📅 and 🕐 carry S_DATE/S_TIME's
# hard space, the status line's own column 5 constant, and were already spaced
# on both readouts.
#
# It read "no separator between them" until 2026-08-27, on the argument that a
# two-cell glyph divides itself from what follows.  Five of the seven cells
# already disproved it -- the sign column has been there as long as the rows
# have stacked -- and the status line spent that day deciding the same question
# the other way.  One readout arguing for the tight form while the other
# defaults to the spaced one is the inconsistency, not either form.
C_ELAPSED = 9  # ⌛🤖 + a duration.  BOTH rows are robot time: this prompt's
               # answering time on top, every prompt's answering time summed
               # beneath it.  The session's AGE used to sit on the bottom row
               # and was the wrong total for the row it was on — everything
               # else here totals what the prompts above it did, and an age
               # totals what the clock did.  The 🤖 says which of the two
               # this is, against the status line's ⌛ Σ 👤 🤖, where all
               # three are on show and only one of them is this one.
C_STAMP = 13   # 📅 + "2026-08-22" above 🕐 + a clock padded to the same ten,
               # so the date and the time it belongs to share a right edge
C_TOK_TIGHT = 13       # 🧩 + "▴627k ▾627k" with MARK_SP empty
C_TOK = C_TOK_TIGHT + len(MARK_SP)
               # 🧩 + MARK_SP + "▴627k ▾627k".  The INNER marks still touch:
               # no space after either arrow, so the two readouts' figures land
               # in the same columns.  MARK_SP sits before ▴ only, and
               # set_mark_spacing moves this constant with it.
C_CTX = 14     # 🧠 + "+142k +14.2٪" — growth in tokens, then that growth as a
               # share of the window it has to fit in
C_CACHE_TIGHT = 5      # 🎯 + "97٪" with MARK_SP empty
C_CACHE = C_CACHE_TIGHT + len(MARK_SP)
               # 🎯 + MARK_SP + "97٪".  pct clamps at 99, so the figure is
               # never four columns.  The clamp is the status line's too -- 💯
               # stands in for a full reading on the LIMIT cells, where 99 and
               # 100 are the same news, and a cache rate is not one of those.
C_COST = 9     # 💰 + a sign column + money_cell: three integer columns, one
               # fractional so the two rows' points land in one column, and
               # one for the unit.  Nine, not the eight it was until
               # 2026-09-03, and the column bought is the unit's: three
               # integer columns used to cap the row at $999, past which the
               # cell overran and — because only ONE of the two rows carries
               # the big figure — the groups came out different widths and the
               # 📊 stopped stacking.  The old note here said to widen this
               # before that day and not to touch the fraction.  Half of that
               # was right.  What the field wanted was not a fourth integer
               # column, which buys one decade and then faces the same cliff
               # at $9999; it wanted the k and M every other magnitude on this
               # row already carries, and a unit costs exactly one column
               # whatever the figure.  The fraction is untouched, as the note
               # asked.  The line is one column wider, which place() takes out
               # of the label, never out of the group.
               # The sign column carries "+" on the per-prompt row and a space
               # on the totals row, as 🧠 🔋 and 📆 do either side of it: every
               # figure on that row is what ONE prompt added to the reading
               # beneath it, and 💰 was the only one not saying so — the field
               # a reader is most likely to mistake for a running total, since
               # a dollar figure beside a session's name reads as the bill
C_LIM_TOT_TIGHT = 6    # " 💳99٪" with MARK_SP empty
C_LIM_TOT = C_LIM_TOT_TIGHT + len(MARK_SP)
               # " 💳 99٪", or " 💳  💯" at a full window — the account
               # half of a totals-row limit cell: the status line's own mark,
               # MARK_SP, and one reading in three columns.  Also the blank
               # the per-prompt row pads with so that its emoji
               # lands in the same column as the one below it.  seg() puts
               # the cost row's slack on the LEFT (it holds a right edge), so
               # a narrower cell does not simply leave a gap at its end: it
               # pushes the whole cell right, off the row it has to stack on.
               #
               # It was " / 99٪" until 2026-08-27, on the stated argument that
               # the slash was "the status line's idiom for exactly this
               # pair".  It never was one: column 4 divides its four fields
               # with MARKS and carries no slash anywhere, so what the two
               # readouts had in common was the pair, not the punctuation.
               # 💳 is what the status line actually prints beside this
               # reading, and it says WHICH of the two figures the second one
               # is — the account, drawn down — where a slash says only that
               # there are two.  Same six columns under --no-mark-spacing;
               # one more with the spacing, which is where the blank went.
C_SESS = 9 + C_LIM_TOT  # 🔋 + a sign column + dec_align(plan_pct, 2, 2, ٪),
               # then the window's own reading after a "/".
               #
               # Get this figure wrong and the symptom points nowhere near it.
               # seg() does not truncate, so a cell whose content outgrows its
               # reservation overruns while an EMPTY cell is exactly the
               # reservation — and the per-prompt row has no 🔋 until a
               # calibration exists where the totals row always does.  The two
               # groups then differ in width, place_stacked shifts each row by
               # its own group width, and what you see is the two 📊 failing to
               # stack.  Check this against what the cell actually renders
               # before believing anything else about that.
C_SEG_GAP = 2  # between adjacent cost-row segments; matches the status line's
               # line-3 spacing so the two read as one family

# Columns the CLI spends before the cost row's first character: the box's
# five-column indent ("  ⎿  ") plus "Stop says: ", which appear nowhere in the
# hook payload and cannot be measured from here.  README, '"Stop says: ", and
# the eleven columns', for what these two figures buy — why the rows ship as
# ONE systemMessage, and why an unsubtracted chrome shows up as a WRAPPED
# second line rather than a trailing ellipsis.
#
# Neither figure can be derived; both were read off a pasted row, by counting
# how far its 📊 sat from the screen's left edge and subtracting the leading pad
# this program had emitted.  They were 14 and 3 first, which is the same
# ELEVEN-column difference and so stacked correctly while quietly spending two
# of RIGHT_MARGIN's four columns.
C_CHROME_LEFT = 16
# The same box on a CONTINUATION line: the indent alone.  "Stop says: " is
# printed against the first line only, so a row below it starts eleven columns
# further left and needs its own figure, or it right-aligns to a different
# column than the row above it.
C_CHROME_CONT = 5
C_RIGHT_MARGIN = 4     # matches the status line's 4 so the right edges agree.
                       # Agreeing takes BOTH constants: the status line ends at
                       # cols-4 because nothing precedes it, while this row is
                       # inset by the chrome first, so it must end at
                       # cols-chrome-4 of its own width to land on the same
                       # screen column.
C_MIN_GAP = 4          # floor between the label and the metrics — the four
                       # spaces asked for after the colon.  When even the floor
                       # will not fit it is the LABEL that gives way, never the
                       # group: a metric that moves when the window narrows is
                       # a metric you have to re-find.
# Padded to a common width rather than written to one.  The invariant is that
# the two labels are the SAME width — the rows are right-aligned as one block,
# so a shorter label starts its row further right and the two 📊 stop stacking.
# Writing both to twenty columns satisfied that by hand and lost it the first
# time one was reworded; computing it cannot be lost.
# All three padded to one width.  place_stacked lays the two rows out as a
# single block and the 📊 prefixes drift the moment the labels differ in
# length, so the compaction label has to be measured with the others rather
# than written to match by eye.
_LABELS = ("Usage: Prompt (last)", "Usage: Session (total)",
           "Usage: Compact (last)")
_LABEL_W = max(len(x) for x in _LABELS)
# One glyph per row type, riding immediately right of the 📊 that marks the
# block.  📊 says "this is the cost line"; these say WHICH cost line, so the
# three rows can be told apart at a glance without reading the words —
# 🎤 a prompt the user typed, 🎮 the running tally, 🤏 the context pinched down.
#
# All three are Emoji_Presentation=Yes, chosen for that and not only for
# meaning: a codepoint that defaults to TEXT presentation is drawn one column
# wide by some terminals and two by others, which is the whole reason the
# width profiles exist.  Anything picked for this slot must clear that bar,
# or it buys a per-terminal alignment bug for a picture.
# The first two are ALIASES, not copies.  The status line's column 4 marks
# the same two scopes with the same two glyphs, and a second literal here
# would be a second place for them to drift apart.
E_ROW_PROMPT = E_TURN         # 🎤  the prompt just answered
E_ROW_TOTAL = E_SESSION       # 🎮  the session tally
E_ROW_COMPACT = "\U0001F90F"  # 🤏  the compaction
# The emoji is padded ahead of the text, never inside it: ljust counts
# CHARACTERS and the glyph is two columns, so padding the joined string would
# make the three labels agree on length and disagree on width.
_lab = lambda e, i: e + " " + _LABELS[i].ljust(_LABEL_W)
C_LABEL = _lab(E_ROW_PROMPT, 0)
C_TOTALS_LABEL = _lab(E_ROW_TOTAL, 1)
# Swapped in when the last thing that happened was a compaction.  The row is
# then reporting an operation the user did not type and cannot see the cost of
# anywhere else, and calling it a prompt would bury exactly that.
C_COMPACT_LABEL = _lab(E_ROW_COMPACT, 2)
# Both labels are twenty columns, deliberately, so the two right-aligned rows
# start and end on the same columns and read as a heading over a heading rather
# than two ragged captions.  Keep them equal if either is reworded.


# Where the status line leaves the plan figures it took from Claude Code's
# payload, so the cost rows can quote the same ones.  /tmp rather than TMPDIR,
# for the reason CALIB_CACHE below is: the two readouts run in different
# processes under different launchers, and the status line has been observed
# writing its caches to /tmp while the Stop hook's TMPDIR pointed inside
# /var/folders.  A path that resolves differently per process cannot be a
# channel between them.
# Overridable because the golden test feeds this program synthetic payloads:
# eleven of the thirteen fixtures carry rate_limits, so a test run would
# otherwise publish 08-limits-critical's figures to the live cost rows and
# leave them on the real cost rows.  A test must not be able to write to the
# thing it is testing around.
#
# No TTL beside it.  There was one, and expiring this cache meant falling
# through to the menu-bar app unconditionally — which assumes the app is
# fresher than an expired file and it need not be.  Both sources now say how
# old their reading is and limits_snapshot takes the newer; see _reading_age.
PLAN_CACHE = os.environ.get("CLAUDE_PLAN_CACHE",
                            "/tmp/claude-plan-limits.json")

# Same reason PLAN_CACHE is overridable, one file along: the calibration scan
# walks every transcript on the machine, so its answer depends on what has been
# run here lately.  A golden test needs it planted.
CALIB_CACHE = os.environ.get("CLAUDE_CALIB_CACHE",
                             "/tmp/claude-calib-cache.json")
CALIB_TTL = 300        # the scan walks transcripts; five minutes is plenty

# The smallest plan reading that can serve as the DIVISOR of a calibration.
#
# used_percentage arrives quantised to whole percent, so a reading of n means
# the truth is somewhere in a band half a point wide either side of it: at
# n=1 that is ±50٪ — a factor of three across the band — and every share
# divided by a unit derived from it inherits the whole of that.  At 2 the band
# is ±25٪, at 5 it is ±10٪.  Two is where a figure stops being wrong by more
# than itself, which is the only threshold this reading can actually support;
# it is not where the figure becomes precise, and nothing here can make it so,
# because the payload does not publish a finer one.
#
# What this costs is the 🔋 shares for the first few minutes of every 5-hour
# window, which then read "?" — see render_limit's fig(), which draws exactly
# that for a figure it does not have.  What it buys is that they never again
# read 18٪ under an account total of 1٪.  The weekly window sits above this
# for all but the first hours of a week, so it pays almost nothing.
CALIB_MIN_PCT = 2.0


def frozen_now() -> Optional[float]:
    """The wall clock, pinned, or None to read the real one.

    Every renderer that needs the time already takes `now` and defaults it to
    time.time(); this is the one place that fills it in, and it fills it in
    from the environment so a test can pin it without touching an argument
    list.  None everywhere else, which is what the live status line passes.

    It exists because the differential test that preceded the golden files
    could not pin the clock at all.  Both programs read it independently, so a
    second ticking between the two runs was a false failure, and the harness
    answered that by running the reference twice and comparing only when the
    two agreed — up to six attempts per comparison, and a SKIP when the clock
    beat all six.  A clean run skipped 15 of 78.  Those 15 were not passes and
    were not failures; they were comparisons that did not happen, and which
    ones varied per run.  Pinning the clock costs one environment variable and
    makes the other 63 reproducible as well as green.

    TZ is the caller's business: the readout formats in local time, so a golden
    file records the zone it was generated in and the harness sets TZ to match.
    """
    v = os.environ.get("CLAUDE_STATUSLINE_NOW", "")
    try:
        return float(v) if v else None
    except ValueError:
        return None

# ════════════════════════════════════════════════════════════════════════════
# Width tables.
#
# Sorted, inclusive [lo, hi] decimal codepoint ranges the terminal draws in two
# cells.  Everything below U+1100 is narrow, so the table starts there.
#
# THIS IS NOT unicodedata, AND MUST NOT BE REPLACED BY IT.  It began as a
# generated East_Asian_Width table and was then corrected against
# probe-advance.sh; the three corrections, and why unicodedata gets each of
# them wrong, are in README under "Why vis_width is not a correct Unicode
# implementation".  Short version: the regional indicators are folded in at
# two columns EACH, U+1F300–U+1FAFF is ONE range rather than a dozen with
# gaps, and U+1FA70–U+1FAF8 is left out so it measures one column.
#
# KEEP IT SORTED: the scan stops at the first range starting above the
# codepoint, so an entry out of order is an entry never read.
#
# Known imprecision, left deliberately: 9962-9995 holds both narrow dingbats
# (✀ measures one) and wide emoji (✅), and no range can be right for both.  It
# costs nothing because chat text — the only place those appear — has the whole
# U+2190-U+2BFF block replaced before measurement.
#
# Second known imprecision, and the one that shows what "corrected against the
# probe" is worth.  U+1F300-U+1FBFF is one range, so this table calls U+1F900
# wide.  MEASURED 2026-09-08, the same codepoint, two terminals:
#
#     Ghostty under tmux    advance 1        (agrees with the standard: the
#     Rider / JediTerm      advance 2         block is Neutral to U+1F90B and
#                                             Wide from U+1F90C)
#
# So there is no table entry that is right for both, and this one is right for
# the terminal the layout is tuned to.  It costs nothing TODAY because no
# glyph here lives in U+1F900-U+1F90B — 🤏 U+1F90F is above the split and
# measured two in both — and it is written down so that the next glyph chosen
# out of that band is chosen knowing it would be a column wrong under Ghostty.
# The band is unremarkable ornaments (⯑-ish crosses and circles), so avoiding
# it costs nothing either.
EAW_WIDE = (
    (4352, 4447), (8986, 8987), (9001, 9002), (9193, 9203), (9725, 9726),
    (9748, 9749), (9800, 9811), (9855, 9855), (9875, 9875), (9889, 9889),
    (9898, 9899), (9917, 9925), (9934, 9940), (9962, 9995), (10024, 10024),
    (10060, 10071), (10133, 10135), (10160, 10160), (10175, 10175),
    (11035, 11036), (11088, 11093), (11904, 12019), (12032, 12245),
    (12272, 12771), (12784, 12871), (12880, 19903), (19968, 42182),
    (43360, 43388), (44032, 55203), (63744, 64255), (65040, 65049),
    (65072, 65131), (65281, 65376), (65504, 65510), (94176, 94180),
    (94192, 94193), (94208, 100343), (100352, 101589), (101632, 101640),
    (110576, 110882), (110898, 110898), (110928, 110933), (110948, 110951),
    (110960, 111355), (126980, 126980), (127183, 127183), (127374, 127386),
    (127462, 127490), (127504, 127569), (127584, 127589), (127744, 130047),
    (131072, 262141),
)


class Widths(NamedTuple):
    """Everything terminal-specific about measuring a string.

    Passed to vis_width as a default argument rather than read from module
    scope, so the function stays pure and a test can substitute a profile.
    """
    narrow: frozenset      # advances ONE where the table says two
    icons: frozenset       # advances TWO where the table says one
    clusters: bool         # True if the terminal folds a grapheme cluster
    wide: Tuple[Tuple[int, int], ...]


def term_profile(env: Optional[Dict[str, str]] = None) -> str:
    """Which terminal is drawing this, as a profile name.

    TMUX is checked first, on the reasoning that when the row renders inside
    tmux it is tmux doing the laying out and the host terminal is beside the
    point.  Two probes support that: tmux 3.5a over iTerm2 measured identically
    to bare iTerm2 on every glyph but a keycap.

    BUT THAT EVIDENCE IS FROM ONE HOST.  tmux over JediTerm has never been
    measured, and JediTerm is the terminal that disagrees with iTerm in the
    opposite direction.  So the tmux branch is measurement over iTerm and
    inference everywhere else — which matters, because a Rider user running
    tmux hits exactly that gap.  Settling it takes one command in a tmux
    session inside Rider:

        ~/.claude/claude-code-usage-statusline.py --selftest

    A non-zero delta on any row means tmux does not insulate the row from its
    painter, and the combination needs a branch of its own.
    """
    e = os.environ if env is None else env
    if e.get("TMUX"):
        return "tmux"
    if e.get("TERMINAL_EMULATOR") == "JetBrains-JediTerm":
        return "jediterm"
    if e.get("TERM_PROGRAM") == "iTerm.app":
        return "iterm"
    return "unknown"


def widths_for(profile: str) -> Widths:
    """The measurement rules for one terminal profile.

    MEASURED 2026-08-16, and again 2026-09-08 in two terminals: every override
    below now corrects nothing.  Both glyphs that needed one have left the
    layout — ⏱ for ⌛, and 🕰 for 🕐 over the font-run fault described at
    E_TIME — so a probe run against the current glyph set emits empty tables in
    all three profiles.  The 2026-09-08 run also measured every specimen row
    in --selftest at delta 0 in both, which is the first time the layout itself
    has been checked against a terminal that is not JediTerm.  Deleting them would
    change no output.

    They stay because they record measured behaviour of the TERMINALS rather
    than a fix for this layout, and the next glyph choice may want exactly
    that.  Do not read them as load-bearing: what the split actually carries
    now is `clusters`, and the grid width beside it.
    """
    if profile == "jediterm":                  # probed 2026-08-16, Rider 2025.x
        return Widths(
            narrow=frozenset({9201}),          # ⏱ U+23F1, though EAW says Wide.
                                               #  U+1F6E2 🛢 was here too, on the
                                               #  reasoning that a codepoint with
                                               #  no default emoji presentation
                                               #  falls back to a text font and
                                               #  draws in ONE cell.  It tore the
                                               #  grid in Rider, and 🕰 below is
                                               #  the same class of codepoint
                                               #  going the OTHER way — which is
                                               #  the lesson: for these, what
                                               #  decides the advance is which
                                               #  font happens to cover the
                                               #  glyph, so it cannot be reasoned
                                               #  out, only measured.  The glyph
                                               #  was swapped for one that needs
                                               #  no entry instead.
            icons=frozenset({128368}),         # 🕰 U+1F570, though the generated
                                               #  table calls it narrow
            clusters=False,                    # measured: skin tone 4, ZWJ 5,
                                               #  flag 4, keycap 3, VS16 +1 —
                                               #  no folding at all
            wide=EAW_WIDE,
        )
    if profile in ("tmux", "iterm"):           # probed 2026-08-16, iTerm2 +
                                               #  tmux; again 2026-09-08,
                                               #  Ghostty + tmux, which agreed
                                               #  on all four sequences and
                                               #  needed no entry of its own.
                                               #  Note term_profile checks TMUX
                                               #  first, so Ghostty reaches
                                               #  this branch only inside tmux;
                                               #  bare Ghostty is "unknown" and
                                               #  unmeasured.
        return Widths(
            narrow=frozenset({128368, 9201}),  # 🕰 and ⏱ both advance one
            icons=frozenset({9851}),           # ♻ U+267B advances two.  Correct
                                               #  only because this file never
                                               #  emits a BARE ♻ — the entry was
                                               #  derived from the VS16 sequence
                                               #  ♻️ measuring two.  If a bare
                                               #  one is ever added, this becomes
                                               #  a one-column error on it.  The
                                               #  same construction once produced
                                               #  49 (ASCII "1", from the keycap
                                               #  1️⃣), which would have made every
                                               #  literal 1 on the row count two.
            clusters=True,                     # measured: skin tone 2, ZWJ 2,
                                               #  flag 2
            wide=EAW_WIDE,
        )
    # Unknown terminal: nothing to correct.  Every glyph this file emits either
    # is Emoji_Presentation=Yes or is covered by the generated table, which is
    # the standing rule for adding one — a glyph needing a per-terminal entry
    # is a glyph that will be wrong on the terminals nobody probed.
    return Widths(frozenset(), frozenset(), False, EAW_WIDE)


PROFILE = term_profile()
WIDTHS = widths_for(PROFILE)

# Paint room, per terminal.  Width and ink are separate questions: a glyph can
# advance the two columns everyone agrees on and still draw past them, and
# where it does, the ink lands on the digit beside it.  iTerm needs a column of
# air after the icons that carry a value directly; JediTerm does not.
#
# ⚡ is padded although it was not in the report, because column 3 holds 🎯 💰 ⚡
# and a cell that skipped the pad would sit a column short of the two beside
# it.  Cheaper than letting the column go ragged.
_PAD = " " if PROFILE in ("iterm", "tmux") else ""

# Status-mode glyph forms.  The ones written with a literal " " carry it in
# EVERY profile, where _PAD is empty on JediTerm: the countdown field and the
# elapsed field have to begin on the same column for column 4's three rows to
# stack, and the grid's outer columns space their icons as a matter of layout
# — see S_STY.
#
# The marks INSIDE column 4 — 🔜, Σ, and the three scope marks — take no S_
# form and no _PAD, and unlike every icon outside the column they are meant to
# TOUCH their figure.  Their fields are right-aligned and exactly as wide as
# the widest reading that can land in one, so a full-width value sits hard
# against its mark and only a short one leaves a gap — and that gap is the
# alignment doing its job, not a separator.  See LIM_FIG_W.
S_TOK = E_TOK + _PAD
S_CTX = E_CTX + _PAD
S_MOD = E_MOD + _PAD
S_CACHE = E_CACHE + _PAD
S_COST = E_COST + _PAD
S_EFF = E_EFF + _PAD
S_HUMAN = E_HUMAN + " "
S_BOT = E_BOT + " "
S_TIME = E_TIME + " "
S_DATE = E_DATE + " "
S_IDLE = E_IDLE + " "
# Columns 1 and 5 — the two edges of the grid, spaced in every profile.  Every
# icon in column 4 already divides itself from its value and these three did
# not, so the edges read tighter than the middle: 🎨expl and 💾+3.4k against
# 🔋 🎤.  A hard space and not _PAD, because the reason is layout, not paint —
# _PAD compensates for ink that spills in iTerm, which is a different question
# from where a value begins.
#
# The two columns pay for it in opposite ways.  Column 1 had the room already,
# its widest cell spending six of the eleven columns it reserves.  Column 5 had
# none — every cell in it filled exactly the thirteen it was given — so the
# column is one wider and 📅 and 🕐 pad their values to match; see RIGHT_GRID.
S_STY = E_STY + " "
S_PR = E_PR + " "
S_DIFF = E_DIFF + " "
# The cost line's elapsed cell.  No space between the two: the 🤖 qualifies
# the ⌛ rather than sitting beside it, and the sign that follows lands where
# 💰, 🔋 and 📆 put theirs — hard against the icon.
S_WORK = E_IDLE + E_WORK
S_SESS = E_SESS + " "
# One space, like every other prefix on these rows.  It carried two while the
# glyph was 🛢, to compensate for a single-cell draw; 🪫 measures two like the
# 🔋 above it and needs no compensation.  If this slot ever takes a glyph that
# does, the pad belongs HERE rather than in the grid, because it is a property
# of the glyph and travels with it.
S_WEEK = E_WEEK + " "
# No separator space, unlike the other S_ forms: 🔜 and Σ mark what the figure
# beside them measures rather than naming a metric, and the field they sit in
# right-aligns its value hard against them, so a separator here would be the
# one thing standing between a mark and the figure it labels.  Dropping it
# also puts the two marks on one rule — Σ never had one — and leaves the
# field the four columns dur_fmt's widest reading needs.
S_RESET = E_RESET
# Σ padded to 🔜's two columns so the last field has one shape on all three
# rows and its figure begins on one column.  Padded on the RIGHT: Σ is one
# column and 🔜 is two, the blank has to sit on one side of it, and putting it
# after leaves the two marks starting on the same column — which is the edge
# that reads, because a mark is found by where it begins, not where it ends.
# The cost is the one blank on this readout that does divide a mark from its
# figure; it buys the only stack the alternative could not.  Painted F_SUM
# rather than the row's F_PRW, so it stacks under 🔜 in ink as well as in
# column — see the constant for where that grey was measured.
S_SUM = E_SUM + " "

# The right-hand column grid, listed left to right.
#
#            col 1       col 2            col 3      col 4             col 5
#   row 1    🎨 style    🧩 tokens        🎯 cache   🔋 5-hour limit   📅 date
#   row 2    🔀 PR       🧠 context       💰 cost    🪫 weekly limit   🕐 time
#   row 3                🤖 model 📏win   ⚡ effort   ⌛ elapsed        💾 diff
#
# Column 2 is the point of the arrangement: three two-value metrics whose
# fields are the same width, so ▴'s figure sits over the context size and over
# the model, and their second values line up down the right of the column.
# Column 1 holds the two segments that can be absent (🎨 off the default style,
# 🔀 off a PR branch) over an empty cell, so their absence leaves a gap at the
# row's left edge rather than a hole between two figures.  Column 5 ends the
# readout with the stamp and the diff.
#
# COLUMN 4 IS A GRID OF ITS OWN, three rows by four fields, and the widest
# thing on the readout at 29 columns.  Fields 0 to 2 are the three scopes,
# widening left to right — 🎤 this turn, 🎮 this session, 💳 the account —
# each a mark and a value right-aligned in LIM_FIG_W, each divided from the
# next by one space.  Field 3 is a duration and its mark says which kind: 🔜
# time until this window resets, Σ time since the session opened.
#
# The duration went last on 2026-08-28, having led the column since it was
# built.  Leading was defensible — a countdown answers the same question as
# the ⌛ row below it, and the three durations stack whichever end they sit
# at — but it cost the arrangement its opening.  Fields 0 to 2 are ONE
# sequence, a scope widening a step at a time, and the reader met it a field
# in from the column's edge with a figure of a different kind in front of it.
# Now the column opens on the narrowest scope, widens twice, and ends on the
# one reading that is not a scope at all — the horizon the three of them are
# being spent against.  The three durations still stack; they stack on the
# other edge.
#
# The value is right-aligned in a field exactly its own widest reading, which
# is what makes the column read as a column: the last character of every
# figure lands on one terminal column, so a percentage's ٪ sits directly above
# the m/h/d of the duration below it, and the mark touches the figure it
# labels whenever that figure is full width.  The ⌛ row buys its share of
# that by asking dur_fmt for two digits rather than three — "6h" and not
# "6.4h" — everywhere except Σ, which keeps three because field 3 is a column
# wider and the session's own age is the one duration here worth a decimal.
#
# The two limit rows fill all three scopes.  The ⌛ row fills 🎤 with the
# turn's own wall-clock time, and its other two scope fields are positional
# rather than scoped: 👤 and 🤖 split the session age that field 3 states,
# and there is no account-wide time to put under 💳.  That is the same
# compromise the row made before this change, one field wider.
#
# The marks are what make the stacking possible, not decoration.  Without
# them the three rows want different field widths — the limit rows carry no
# glyph inside a field and the ⌛ row's halves carried two columns of one —
# so they could not be given one field width and could not stack.
#
# Column 5 is 14: eleven columns of diff after an icon that now takes three.
# 📅 and 🕐 pad their values to the same eleven rather than to the ten the date
# needs, so all three right edges meet — the alignment that makes a date
# sitting above a time read as one stamp instead of two unrelated fields, and
# that puts the diff's figures under both of them.
#
# The four gaps between these five columns carry a rule at wide enough widths —
# added 2026-08-28, see SEG_RULE for the glyph, F_RULE for the ink and
# rules_on for when it is drawn.  It is painted INTO SEG_GAP and takes no
# column of its own, so nothing here moves and a row with the rules stacks
# against one without them.  What it buys is that the grid stops relying on
# white space alone to say where one column ends: four columns of blank is a
# gap on a short row and an expanse next to a cell like column 4, and the eye
# has to re-measure it on every row.  A stroke on a fixed column does not need
# measuring.  Between the chat text and column 1 there is deliberately no rule:
# that boundary is a computed pad rather than a fixed gap, and a rule there
# would have to be paid for in width.
RIGHT_GRID = (11, 14, 7, 29, 14) if _PAD else (11, 13, 6, 29, 14)


def set_mark_spacing(on: bool) -> None:
    """Turn the blank between a column-4 mark and its value on or off.

    Four constants move together and none of them may be left behind.  MARK_SP
    is what the renderers print; column 4 in RIGHT_GRID is four columns wider
    with it, one per field; LINE3_RESERVED is what line 3 spends outside the
    pwd and so follows column 4 exactly; and PWD_MAX_FALLBACK is derived from
    that, which is why it is recomputed here rather than left at the value it
    took at import.

    Called once from main() before anything renders.  Rebinding module globals
    is not how this file usually works — nothing else here is settable — and it
    is done this way because the alternative is threading a layout flag through
    every renderer and grid_row down to seg(), for a switch read in four
    places.
    """
    global MARK_SP, RIGHT_GRID, LINE3_RESERVED, PWD_MAX_FALLBACK
    global C_TOK, C_CACHE, C_LIM_TOT, C_SESS
    MARK_SP = " " if on else ""
    col4 = COL4_TIGHT_W + 4 * len(MARK_SP)
    RIGHT_GRID = (11, 14, 7, col4, 14) if _PAD else (11, 13, 6, col4, 14)
    LINE3_RESERVED = LINE3_TIGHT + 4 * len(MARK_SP)
    PWD_MAX_FALLBACK = MAX_LINE - LINE3_RESERVED
    # The cost row's two unspaced cells.  The other five hold a sign there and
    # do not move; see the cost-line geometry block.  A cost width left behind
    # here does not shift one cell -- seg() never truncates, so the cell
    # overruns its reservation, the two groups come out different widths, and
    # what you see is the two 📊 refusing to stack.
    C_TOK = C_TOK_TIGHT + len(MARK_SP)
    C_CACHE = C_CACHE_TIGHT + len(MARK_SP)
    # 💳 divides the two halves of a totals-row limit cell and takes MARK_SP
    # like any other mark.  C_SESS is derived and must be rebound here too: it
    # is read as a plain global by both cost renderers, so leaving it at its
    # import value is the overrun described above.
    C_LIM_TOT = C_LIM_TOT_TIGHT + len(MARK_SP)
    C_SESS = 9 + C_LIM_TOT


set_mark_spacing(True)

_SGR = re.compile("\033\\[[0-9;]*m")


# ════════════════════════════════════════════════════════════════════════════
# Measurement.
#
# Pure helpers over strings.  Nothing here touches the terminal or the clock.
# ════════════════════════════════════════════════════════════════════════════

def strip_ansi(s: str) -> str:
    """Drop SGR escapes so a rendered segment can be measured as text."""
    return _SGR.sub("", s)


def vis_width(s: str, w: Widths = WIDTHS) -> int:
    """Columns a string occupies, as THIS terminal counts them.

    Not as Unicode defines them, and not as a correct implementation would.

    One rule, and it is the terminal's: every codepoint advances on its own.
    There is no grapheme clustering unless the profile says the terminal does
    it.  Measured with probe-advance.sh, which prints a glyph and asks the
    terminal where the cursor landed:

        👍🏽 base + skin tone   4 columns    (a clustering terminal gives 2)
        👨‍💻 ZWJ sequence       5            (2)
        🇺🇸 flag pair          4            (2)
        1️⃣ keycap             3            (2)
        ♻️ and 🕰️ with VS16   +1 each      (+0)

    So a variation selector, a zero-width joiner and a keycap enclosure each
    take a cell of their own, and the tables are consulted per codepoint with
    no sequence handling whatsoever.  Earlier versions folded clusters the way
    a correct implementation would and were wrong here by four columns on a
    family emoji.  If you "fix" this to handle clusters, you reintroduce that.

    What it predicts is the cursor ADVANCE, not the ink.  The two differ often
    enough that several glyphs carry a trailing space purely so their overspill
    lands somewhere harmless.

    Confirmed 2026-09-08 on both sides of the switch: JediTerm still measures
    4/5/4/3 for those four, and Ghostty under tmux measures 2 for every one of
    them.  The parenthesised column above is no longer an inference about what
    a clustering terminal would do.

    Rerun probe-advance.sh after a Rider update: these numbers describe one
    build of JediTerm, not a standard.
    """
    total = 0
    skip = False
    prev_ri = False
    for ch in strip_ansi(s):
        cp = ord(ch)
        if cp < 128:
            total += 1
            continue
        if w.clusters:
            # Cluster folding, for terminals that do it.  Off for JediTerm.
            if cp == 0x200D:                        # ZWJ
                skip = True
                continue
            if skip:                                # its partner
                skip = False
                continue
            if cp in (0xFE0F, 0xFE0E, 0x20E3):      # VS16 / VS15 / keycap
                continue
            if 0x1F3FB <= cp <= 0x1F3FF:            # skin tone modifiers
                continue
            if 0x1F1E6 <= cp <= 0x1F1FF:
                # A flag is two regional indicators drawn as one glyph: count
                # the pair once.  Without this the table's own entry (two
                # columns each) makes a flag four, where a clustering terminal
                # draws two.
                if prev_ri:
                    prev_ri = False
                    continue
                prev_ri = True
            else:
                prev_ri = False
        if cp in w.narrow:
            total += 1
            continue
        if cp in w.icons:
            total += 2
            continue
        # The table is sorted, so the scan stops at the first range starting
        # above this codepoint.  A hit is two columns; anything else is one.
        for lo, hi in w.wide:
            if cp < lo:
                break
            if cp <= hi:
                total += 1
                break
        total += 1
    return total


def pad_val(want: int, txt: str, left: bool = False) -> str:
    """`txt` padded into a field of `want` COLUMNS, right-aligned by default.

    Never use a plain format width for a value on these rows.  Python's `%-5s`
    and f-string `{v:>5}` pad to a count of characters, and every field here is
    fixed width precisely so the rows stack.  The moment a value contains a
    two-column glyph — 📏 beside the model, 🧩 opening the token cell — a
    character count sees a string already at width and adds nothing.  The
    field comes out short, every later cell on that row shifts, and the row
    stops lining up with the ones above and below.  Invisible in testing with
    ASCII, obvious the moment one of those lands in a padded field.

    The token marks are NOT an example of this.  ▴ and ▾ are one column, so
    "▴4M" measures three either way, and ↑ before them was one column too:
    this comment named the arrow for as long as it existed and the example
    never demonstrated the bug.  📏 and 🧩 are characters that do.

    It never truncates.  A value that outgrows its field pushes the cell's
    later fields right rather than corrupting anything else; only the fit_*
    helpers cut.
    """
    have = vis_width(txt)
    if have >= want:
        return txt
    pad = " " * (want - have)
    return txt + pad if left else pad + txt


def seg(want: int, txt: str = "", left: bool = True) -> str:
    """One grid cell of exactly `want` columns.

    `left=True` (the status line) puts the slack to the RIGHT of the segment,
    never between its emoji and its value: the emoji sits flush at the cell's
    left edge, which is what aligns it with the emoji above and below, and the
    value follows immediately rather than marooned across a gap.

    `left=False` (the cost line) puts the slack on the left, so the segment
    holds its right edge instead.

    An empty segment spends its whole reservation on spaces so its neighbours
    do not move.  It never truncates — erring one column wide is cheaper than
    erring one narrow, because wide only shifts the row and narrow corrupts the
    alignment of everything after it.
    """
    have = vis_width(strip_ansi(txt)) if txt else 0
    pad = " " * max(0, want - have)
    return txt + pad if left else pad + txt


def pair(a: str, b: str, want: int, gap: int = PAIR_GAP) -> str:
    """Join two segments into one cell of `want` columns, `a` flush left and
    `b` flush right, with the slack between them.

    Pairing is what keeps a hole out of the row: in a grid where every cell is
    the same width, an optional segment holding a cell of its own leaves the
    whole cell blank when it renders nothing and the row reads as broken.
    Sharing, its absence merely empties half a cell.

    `want` is why both ends are named.  Collapsing the pair leftwards instead —
    dropping an absent `a` and letting `b` slide into its columns — moves `b`,
    and on column 4 both edges are load-bearing: ⌛ stacks under the countdowns
    of 🔋 and 📆 at the cell's left edge, and 🕐 ends the whole readout at its
    right edge, level with the ٪ of the two rows above.  A fresh session has no
    elapsed time to show, and while this took no width that alone pulled the
    clock twelve columns in and left line 3 ending short of lines 1 and 2.
    Reserving `a`'s columns whether or not `a` is there fixes both glyphs where
    the eye expects them, exactly as an absent countdown leaves RST_W blank
    rather than shuffling the percentages left.

    It never truncates, for seg's reason: a cell one column wide only shifts
    its row, where one column narrow corrupts every alignment after it.
    """
    return seg(want - vis_width(strip_ansi(b)), a + " " * gap if a else "") + b


def rules_on(cols: Optional[int]) -> bool:
    """Whether this row is wide enough to draw the rules between its columns.

    Two ways to be under horizontal pressure, and either one is enough.

    The first is the tight layout.  `--no-mark-spacing` exists for terminals
    that cannot afford the readout at its designed width, and it buys those
    four columns back by closing the blank between every column-4 mark and its
    value.  A layout that has just been asked to give up the space inside its
    own fields is not one to hand chrome to.

    The second is the measured width, against RULE_MIN.  An unknown width
    counts as pressed: the fallback path there flows line 3 leftwards with only
    MIN_GAP before the group and estimates the pwd rather than fitting it,
    which is the shape the readout takes when it has run out of room.  Guessing
    generous costs a rule drawn into a row that is already overrunning.

    The rules never take a column — they are painted INTO SEG_GAP, which the
    grid spends either way — so this is not a fit calculation and dropping them
    buys nothing back.  It is about what the row can carry: a divider earns its
    ink by separating things that have room to be separate, and on a row whose
    names are being cut to stubs it is one more thing between the reader and
    the readings.
    """
    return bool(MARK_SP) and cols is not None and cols >= RULE_MIN


def seg_gap(rule: bool = False) -> str:
    """The SEG_GAP columns between two grid cells, ruled or blank.

    Exactly SEG_GAP columns wide in both forms — the rule is painted into the
    gap the grid already spends, never added to it.  That is what makes the
    switch safe to flip per row: nothing to the right of it moves, so a ruled
    row and a blank one stack to the column.
    """
    if not rule:
        return " " * SEG_GAP
    return "  %s%s%s%s" % (F_RULE, SEG_RULE, R, " " * (SEG_GAP - 3))


def grid_row(cells: Sequence[str], grid: Optional[Sequence[int]] = None,
             rule: bool = False) -> str:
    """Lay segments onto the column grid — one per slot, empty for unused.

    The grid is resolved on the CALL and not bound as a default argument,
    because set_mark_spacing rebinds RIGHT_GRID after import and a default
    would have captured the value it had at def time.

    `rule` draws a divider in each gap.  It is passed in rather than read from
    the width here, because the three rows of one readout must agree — a rule
    on line 1 and none on line 3 is worse than either — and the width they
    agree on is known once, where the readout is assembled.  Off by default so
    that a grid_row built outside that assembly, as --selftest does, gets the
    plain gaps it is measuring.
    """
    if grid is None:
        grid = RIGHT_GRID
    gap = seg_gap(rule)
    out = []
    for i, want in enumerate(grid):
        if i:
            out.append(gap)
        out.append(seg(want, cells[i] if i < len(cells) else ""))
    out.append(R)
    return "".join(out)


def fit_head(t: str, max_chars: int) -> str:
    """Trim to `max_chars` CHARACTERS by dropping them off the end.

    For names read left to right — a project, a branch — where the
    distinguishing part comes first.  Character count rather than columns is
    deliberate and matches allocate_left, which budgets in characters: these
    are ASCII in practice, and the two must agree or the allowances mean
    nothing.
    """
    if max_chars > 1 and len(t) > max_chars:
        return t[:max_chars - 1] + "…"
    return t


def fit_path(p: str, max_chars: int) -> str:
    """Trim the path by dropping characters off the FRONT.

    Keeps the deepest, most specific trailing directories and marks the cut
    with a leading ellipsis.  The path is the only variable-width segment that
    can be shortened without losing information, so it absorbs a narrow
    terminal.
    """
    if max_chars > 1 and len(p) > max_chars:
        return "…" + p[-(max_chars - 1):]
    return p


def fit_cols(txt: str, max_cols: int) -> str:
    """Trim to `max_cols` COLUMNS, ellipsis included.

    This one is for chat text, which is not ASCII: a row carrying an emoji is
    wider in columns than it is long in characters, and cutting it by character
    count overruns the budget, drives the row's padding negative and pushes the
    row past the right margin — one column per emoji.

    Binary search rather than a per-character walk, inherited from the bash
    where vis_width was a subshell and a walk cost a process per character.
    It costs nothing here either way; it stays because it is what was proved
    against the bash, not because a walk would be wrong.
    """
    if vis_width(txt) <= max_cols:
        return txt
    budget = max_cols - 1                     # leave a column for the ellipsis
    lo, hi = 0, len(txt)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if vis_width(txt[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return txt[:lo] + "…"


def trunc(s: str, want: int) -> str:
    """`s` cut to at most `want` columns, counting as vis_width does.

    Cutting by characters would overshoot on any emoji, which is the whole
    reason this exists: the cost row's icon block is two columns before the
    label even starts.
    """
    out, w = [], 0
    for ch in s:
        cw = vis_width(ch)
        if w + cw > want:
            break
        out.append(ch)
        w += cw
    return "".join(out)


# ════════════════════════════════════════════════════════════════════════════
# Formatting.
#
# The rule throughout is SIGNIFICANT DIGITS, not decimal places.  A decimal
# survives only while the mantissa is below ten, which is what caps every
# field's width and lets the rows stack.
# ════════════════════════════════════════════════════════════════════════════

# ── subscript decimals, off by default ──────────────────────────────────────
#
# U+2080..U+2089 in place of the fraction, so "1.2٪" is written "1₂٪" and the
# decimal point costs nothing.  Off unless --subscript-decimals says otherwise.
#
# WHY IT IS A SWITCH AND NOT THE FORMAT.  Two things about it are unproven
# here and only a terminal can settle them.  East Asian Width calls the block
# Neutral, so vis_width already returns 1 and every reservation in this file
# assumes as much -- but the probe had never MEASURED it, and there is a known
# trap of exactly that shape one plane up (see the U+1F900 note beside
# EAW_WIDE), where the standard says Neutral, one terminal agrees and another
# draws two columns.  And the glyphs are small: these are the figures on the
# row a reader acts on, and whether a subscript 6 reads as a 6 at a terminal's
# point size is a question about a font, not about a program.  The second
# answer is the reader's to give after looking at it, which is what the flag
# is for.
#
# THE NAME CARRIES THE E_ PREFIX for the first of those.  probe-advance.sh
# derives what to measure by parsing the E_* assignments out of this file, so
# a glyph named anything else is a glyph nobody measures -- which is what
# these ten were until 2026-09-08, sitting one rename away from the probe that
# was blocking them.
#
# NOTHING IS RECLAIMED YET.  Every field keeps the width it had, so a shorter
# figure gets one more column of leading pad and the grid cannot tear on the
# switch.  That is deliberate: if the terminal turns out to draw these two
# columns wide, the damage shows up as a figure overrunning its own cell
# rather than as a whole row shifted, which is the difference between a
# diagnosis and a mystery.  Narrowing LIM_FIG_W from 4 to 3 is the payoff and
# it comes after the probe, not before.
#
# THE LEADING ZERO STAYS, where limit_pct drops it.  ".38" is unambiguous
# because the point marks the figure as a fraction; "₃₈" is not -- it is the
# same glyph sequence a reader would take for 38 in a smaller font.  So the
# zero comes back for this form, which means a sub-1 reading saves nothing.
# Neil's call, and the right one: a column is worth less than the difference
# between a third of a point and thirty-eight of them.
E_SUB_DIGITS = "₀₁₂₃₄₅₆₇₈₉"
SUB_DEC = False


def set_subscript_decimals(on: bool) -> None:
    """Turn the subscript fraction form on for this process.

    A global, set once in main() before anything renders, for the reason
    set_mark_spacing is one: the alternative is threading a formatting flag
    through every renderer down to the five functions that actually emit a
    decimal.
    """
    global SUB_DEC
    SUB_DEC = on


def sub_dec(v: str) -> str:
    """A formatted number with its fraction in subscript digits, or unchanged.

    Operates on the RENDERED string rather than on a float, so one function
    covers every magnitude rule in this file — humanize's unit ladder,
    limit_pct's dropped zero, dur_fmt's trailing "h" — without knowing any of
    them.  The point and the digits after it are replaced; anything else the
    string carries, a unit or a sign, is left where it was.

    Only the FIRST run of digits after a point is touched, and there is only
    ever one: nothing here formats two decimal groups into one field.
    """
    if not SUB_DEC or "." not in v:
        return v
    # The zero that limit_pct drops comes back — see the block note.  Done
    # before the substitution rather than after, so the head is a real digit
    # by the time anything measures it.
    if v.startswith("."):
        v = "0" + v
    return re.sub(r"\.(\d+)",
                  lambda m: "".join(E_SUB_DIGITS[int(d)] for d in m.group(1)), v)


def _subscriptable(fn):
    """Route a numeric formatter's result through sub_dec.

    Five functions in this file emit a decimal and each has several returns,
    so wrapping the function is one line where wrapping the returns would be
    fourteen.  wraps() is here because the docstrings on those five are the
    documentation for the formats themselves.
    """
    @functools.wraps(fn)
    def inner(*a, **kw):
        return sub_dec(fn(*a, **kw))
    return inner


@_subscriptable
def humanize(n: float) -> str:
    """A token count in at most four columns: 1234 → "1.2k", 632 → "632 ".

    The decimal is kept only while the mantissa is below ten, i.e. where it is
    the difference between 1.2k and 9.9k.  Past that it is noise dressed as
    precision — the ".4" in "627.4k" is a tenth of a percent of the figure, and
    it costs two columns and a moving decimal point to say so.  Three
    significant digits is what caps the result at four characters.
    """
    for lim, unit in SI_UNITS:
        # The cut is where the mantissa below would ROUND UP into a fourth
        # digit, not at the round number under it, and money_fmt makes the
        # same cut for the same reason -- see the note there.  999,600 belongs
        # with "1.0M" because "%.0f" of 999.6 writes "1000": five characters
        # in a field that reserves four, and a figure that has to be read
        # twice to be told a thousand thousands from a million.  Reported from
        # a live readout on 2026-09-08 as "▾1000k", which is what the whole
        # band 999,500 to 999,999 drew.
        if n >= lim - lim / 2000.0:
            v = n / lim
            s = "%.0f" % v if v >= 10 else re.sub(r"\.0$", "", "%.1f" % v)
            return s + unit
    # Under a thousand the unit is a SPACE, not nothing.  The field is
    # right-aligned in four columns, so an absent unit is not a column saved —
    # it is a column of padding moved to the FRONT, which slides the digits
    # right and lands the count's last digit in the column every other row
    # fills with its k or M.  "▾ 632" over "▾ 16k" stacks the 2 under the k,
    # and for as long as it takes to notice the missing unit the figure reads
    # as 632k — three orders of magnitude, from a blank.  Spent on the right
    # instead the same column costs nothing, keeps mantissa under mantissa and
    # unit under unit, and says "no unit" in the place a unit would have been.
    return "%d " % int(n)


def pct2(v: int) -> str:
    """Clamp a percentage to the two characters the row budgets for it.

    100 is the only value that needs a third, and only ever momentarily — a
    cache or limit reading of 99 versus 100 changes nothing anyone does — so it
    saturates rather than widening every percentage field by a column.
    """
    return "99" if v > 99 else "%s" % v


@_subscriptable
def plan_pct(v: float) -> str:
    """A plan-window percentage for the COST row: two decimals at most.

    limit_pct's sibling, and it exists because the two rows want opposite
    things.  On the status line the two limit rows are read against each
    other's ٪, so the figure floats its point and spends every one of its four
    characters on significant digits.  Here the per-prompt row is read against
    the totals row directly beneath it — the same window, before and after —
    and a comparison that close wants the points in one column.

    A fixed point column means a fixed fraction reservation, and every decimal
    reserved is a column charged to EVERY reading, including the ones with no
    fraction to put there.  Two is where that stops paying: it keeps a weekly
    share of a single prompt legible (0.01٪ rather than 0.0٪) and it is one
    column narrower than the three limit_pct would need for ".006".

    The leading zero stays, where limit_pct drops it.  Dropping it buys a
    decimal only in a field that floats its point; here the integer column is
    reserved either way, so dropping the zero would empty a column rather than
    free one.
    """
    if v >= 99.95:
        return "99.9"
    # Trailing zeros stripped for the reason limit_pct strips them: the totals
    # row's figure comes from a source that quantises to whole points, so
    # "91.0٪" was two columns spent asserting a tenth nobody measured.  The
    # per-prompt figure directly above IS continuous and keeps every digit it
    # earns; dec_align still stacks the two on their units column.
    s = "%.1f" % v if v >= 9.995 else "%.2f" % v
    return s.rstrip("0").rstrip(".") or "0"


@_subscriptable
def limit_pct(v: float, digits: int = 3) -> str:
    """A plan-window percentage in the characters its segment budgets.

    Three, not four, and the character bought back goes to the hundreds digit
    so the field can say 100:

        100 and up   "100"
        10 to 100    "62"    "99"
        1 to 10      "5.4"   "9.9"
        under 1      ".38"   ".04"
        exactly 0    "0"

    This field used to spend four characters holding three significant digits
    at every magnitude, and stopped below 100 on the argument that 99.9 and
    100 say the same thing to a reader — you are out — so the third integer
    digit was not worth a column on every other reading.

    What overturned that is where the number comes from.  Both sources quantise
    to whole points before this code sees them: the menu-bar app stores its
    snapshots as integers (27,735 of them on this machine, not one fractional),
    and Claude Code's payload, though it does carry a float, has been observed
    only at whole values — 56.00000000000001 is a ratio times a hundred, not a
    measurement to two decimals.  The two figures on a limit row are that
    number and a difference between two of them, so a decimal on either was
    reserving a column to display a zero.  100 is a reading you can actually
    reach, and the field could not print it.

    The decimals that remain are the ones that still earn their column.  Below
    10 a tenth is a fifth of the figure, so it survives; below 1 the leading
    zero goes, because the point already marks the figure as a fraction and a
    session that has taken a third of a point of the weekly window has taken
    something.  "0٪" there is the one reading of this field that is flatly
    wrong rather than merely coarse.

    Exactly zero stays "0", not ".00".  Nothing consumed and too little to show
    are different statements, and "0" is the one the field can make without
    spending a decimal to say it.

    `digits` is two for the account field alone, which is LIM_ACCT_W wide:

        100 and up   "100"   (never printed — render_limit draws E_HUNDRED)
        1 to 100     "6"     "62"   "99"
        under 1      ".4"    ".0"
        exactly 0    "0"

    That ladder throws away the decimal below ten, and for the account figure
    there is no decimal to throw away: both sources quantise to whole points,
    as the paragraph above says, so "6" and "6.0" are the same reading.  It is
    NOT offered to 🎤 or 🎮, whose figures this program computes as ratios and
    which are fractional for real — a turn share rendered at two characters
    would be ".0" almost always.

    The under-1 branch keeps one decimal rather than rounding to "0", because
    "0٪" for something consumed is the one reading of this field that is
    flatly wrong.  It can still reach ".0" below a twentieth of a point, which
    is a magnitude an account-wide figure does not sit at.

    The point still MOVES between magnitudes rather than pinning to a column —
    significant digits, never decimal places, the rule the rest of the row
    follows.  The rows stack on the thing worth stacking, because the FIELD is
    fixed width and right-aligned: every figure ends on the same column, ٪
    under ٪, which is the edge the eye actually tracks.

    The "100" branch is no longer what render_limit draws — it intercepts at
    100 and puts E_HUNDRED in the field instead.  The branch stays because this
    function is pure and says what a percentage looks like in three characters;
    returning "99" for a full window would make it wrong on its own terms, and
    a second caller would inherit the lie.
    """
    if v <= 0:
        return "0"
    # Each cut is placed where the NEXT format would round up into a fourth
    # character rather than at the round number below it: 9.96 belongs with 10,
    # not with 9.9, because "%.1f" would write it "10.0".
    if digits < 3:
        if v >= 99.5:
            return "100"
        if v >= 0.95:
            return "%.0f" % v
        if v > 0:
            return ("%.1f" % v)[1:]
        return "0"
    if v >= 99.5:
        return "100"
    if v >= 9.95:
        return "%.0f" % v
    if v >= 0.995:
        # ".0" stripped, not merely tolerated.  Both sources quantise to whole
        # points, so at this magnitude the decimal was printing a zero every
        # time — a claim of precision the figure does not have.  The branch
        # stays because the payload's field IS a float and may one day carry
        # 5.4; what goes is the "5.0" that meant nothing.
        return re.sub(r"\.0$", "", "%.1f" % v)
    return ("%.2f" % v)[1:]


@_subscriptable
def money_fmt(c: float) -> str:
    """A dollar figure in four characters: 0.4, 1.9, 12.3, 123, 1.2k, 12k.

    One decimal at most, and none once the figure reaches three digits.  A
    second decimal is a cent on a running total, which changes no decision
    anyone makes from this row, and on the cost row it costs a column TWICE
    over: once for the digit and once more in the fraction reservation that
    holds the two rows' decimal points in the same column.

    Past $999 it climbs SI_UNITS, the same ladder humanize() climbs, and for
    the same reason: a field that stops having units at the top of its range
    does not lose precision there, it loses its WIDTH.  This one used to write
    $1234 as "1234" — four characters where the status line reserves four and
    the cost row reserves three-and-a-point, so on the cost row the cell ran a
    column long, and because only the totals row ever carries the big figure,
    the two groups came out different widths and the 📊 stopped stacking.  The
    old note here said "widen this before that day"; a unit is the cheaper
    answer, and it is the one every other magnitude on the row already uses.

    No "$" — the emoji ahead of it already says what the number is, and the
    sign costs a column the path can use.
    """
    for lim, unit in SI_UNITS:
        # The cut is where the format BELOW would round up into a fifth
        # character, not at the round number under it: $999.5 belongs with
        # "1.0k" because "%.0f" would write it "1000".
        #
        # This note used to end "humanize needs no such adjustment — its
        # sub-unit branch truncates with %d and cannot round up".  That was
        # true of the branch it looked at and false of the function: the
        # BOTTOM step cannot round up, and every step above it can, because
        # they format with %.0f exactly as this one does.  humanize drew
        # 999,600 tokens as "1000k" until 2026-09-08.  The two ladders are
        # climbed the same way after all.
        if c >= lim - lim / 2000.0:
            v = c / lim
            return ("%.0f" % v if v >= 10
                    else re.sub(r"\.0$", "", "%.1f" % v)) + unit
    return "%.0f" % c if c >= 99.95 else "%.1f" % c


# A mean Gregorian month, 365.25/12 days.  Months are the one unit here with
# no fixed length, and averaging is the only answer that does not depend on
# which month you are standing in.  At this field's precision — one decimal,
# and none past ten — the choice is invisible anyway: no calendar month
# differs from the mean by enough to move "1.4M".
MONTH_S = 2629800.0


@_subscriptable
def dur_fmt(d: float, digits: int = 3) -> str:
    """Seconds → "45s" / "1.5m" / "58m" / "2.5h" / "3d" / "1.4M".

    The unit is the largest that leaves a figure of at least one, and a decimal
    survives only while that figure is below ten: "90s" makes you divide,
    "1.5m" does not, while "58.3m" is three characters spent on nothing.

    `digits` is how many characters the caller has for the FIGURE, unit
    excluded.  Three is the default and admits the decimal; two forbids it
    outright, because "1.9h" needs three and a field budgeted for two would
    take the overflow out of the column beside it.  Below ten that costs real
    precision — 1.9h renders "2h" — which is why it is asked for rather than
    inferred: a caller narrow enough to need it knows what it is buying.

    Units are letters rather than the ' and " of arcminutes — those are
    unambiguous only to someone who already knows which is which.

    Months take a CAPITAL M, minutes a small one, and the pair is the reason
    the case is load-bearing rather than incidental: they are the two units in
    this set that share a letter, and they sit four orders of magnitude apart,
    so reading one as the other is not a small error.  Note that M means
    something else again in humanize, where "4.2M" is millions of tokens — the
    two never meet inside one field, but 🧩 and ⌛ do share a row.
    """
    if d < 60:
        return "%ds" % d
    if d < 3600:
        v, u = d / 60.0, "m"
    elif d < 86400:
        v, u = d / 3600.0, "h"
    elif d < MONTH_S:
        v, u = d / 86400.0, "d"
    else:
        v, u = d / MONTH_S, "M"
    if digits < 3 or v >= 10:
        return "%.0f%s" % (v, u)
    return re.sub(r"\.0$", "", "%.1f" % v) + u


def short_dur(target: str, now: Optional[float] = None) -> Optional[str]:
    """Time until `target`, in its most significant unit only.

    `target` is either a bare Unix epoch — the form the status-line payload
    carries, being the rate-limit reset header verbatim — or a local
    "YYYY-MM-DD HH:MM" from a usage source's reading.

    Returns None for empty or unparseable input, which is the NORMAL case for
    the 5-hour window under the fallback source: it is a rolling window the app
    never persists, so that segment renders as a bare percentage.

    "now" is returned rather than a negative duration when the moment has
    passed; reset_dim reads that as imminent, which it is.
    """
    if not target:
        return None
    # WHOLE SECONDS, deliberately.  Every duration here is a ratio formatted to
    # one decimal, so a leftover fraction of a second can push the result
    # across a rounding boundary and print "1.2m" where a whole-second
    # calculation prints "1.1m" — a visible, irreproducible one-tenth of
    # disagreement for no gain in truth, given the input is a timestamp
    # recorded to the second in the first place.
    t = int(time.time()) if now is None else int(now)
    if target.isdigit():
        delta = int(target) - t
        return "now" if delta <= 0 else dur_fmt(delta)
    try:
        target_s = int(datetime.strptime(target, STAMP_FMT).timestamp())
    except ValueError:
        return None
    delta = target_s - t
    return "now" if delta <= 0 else dur_fmt(delta)


def elapsed_short(ts: str, now: Optional[float] = None) -> Optional[str]:
    """How long ago `ts` was — the mirror of short_dur.

    The question this answers is "has it wedged", so seconds matter here in a
    way they never do for a countdown: the difference between 5s and 50s is the
    whole answer.  A timestamp in the future (clock skew) reads "0s" rather
    than erroring or going negative.
    """
    if not ts:
        return None
    try:
        base = ts.split(".")[0].rstrip("Z")
        t0 = int(datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=_UTC).timestamp())
    except ValueError:
        return None
    t = int(time.time()) if now is None else int(now)    # whole seconds — see
    return dur_fmt(t - t0) if t > t0 else "0s"           # short_dur for why


# Transcript timestamps are UTC with a trailing "Z", which 3.9's
# fromisoformat rejects outright — hence strptime on a stripped string, with
# the zone reattached here.
_UTC = timezone.utc


MODEL_FAMILIES = ("Opus", "Sonnet", "Haiku", "Fable", "Mythos")
                       # Longest first is NOT required -- no name here is a
                       # prefix of another -- but the list is: every family in
                       # the CLI's own model catalogue as of 2.1.261.  Mythos
                       # was missing until 2026-09-07 and fell through to the
                       # five-character passthrough below, which drew it as
                       # "Mytho" -- a family name with its last letter eaten,
                       # which reads as a bug in the status line rather than
                       # as a model.


def short_model(m: str, field: int = VAL_W) -> str:
    """Shorten a model display name: "Opus 5" → "Opus5", "Fable 5" → "Fable".

    THE FAMILY IS THE LABEL.  It is what you actually read off the row -- the
    one word that says which model is answering -- and a version only earns
    its columns where it separates two models you might be running.  So the
    order is: family AND version if both fit, family alone if only it fits,
    and a cut family with its version only where the family cannot fit at all.

    That last case is the one this used to do unconditionally, and it is why
    "Fable 5" drew as "Fabl5": a name squeezed for a digit that distinguished
    it from nothing.  "Haiku 4.5" drew as "Ha4.5" for the same reason.  Both
    now give their whole name, and lose a version that was disambiguating
    them against models nobody is running.

    What it costs, stated plainly: a family with several live versions and a
    name too long to carry one -- Opus at 4.x, whose "Opus 4.8" no longer
    fits with its version -- draws as the bare family.  The field is the knob
    for that, not the name: widen VAL_W and the version comes back on its
    own.  Sonnet and Mythos are six characters and cannot fit the field at
    all, so they keep the old squeeze ("So4.6"), which is ugly and unambiguous
    and beats a mangled family that says nothing.

    Anything outside the catalogue is passed through at the field width.
    """
    fam = next((f for f in MODEL_FAMILIES if m.startswith(f)), "")
    if not fam:
        return m[:field]
    ver = m[len(fam):].strip().split(" ", 1)[0]
    if ver and len(fam) + len(ver) <= field:
        return fam + ver                      # "Opus5"
    if len(fam) <= field:
        return fam                            # "Fable", "Haiku"
    return m[:max(0, field - len(ver))] + ver  # "So4.6" -- family too long


def dec_align(v: str, ip: int, fp: int, suffix: str = "") -> str:
    """`v` padded so its decimal point falls in a fixed column.

    Right-aligning a number holds its LAST digit still, which is the wrong end
    when two rows carry different magnitudes: "1.52" over "13.4" stacks the 2
    under the 4, so the units column of one row sits over the tenths of the
    other and the eye reads a comparison that is not there.  Aligning the point
    stacks units over units.

    `suffix` is emitted immediately after the last digit and the padding goes
    after IT, not before.  Padding first would align the suffixes into a column
    of their own and strand each one from the number it qualifies — "0.13  ٪".

    UNDER --subscript-decimals there is no point to align, and the column it
    used to occupy is not reclaimed: the reservation stays `fp + 1`, so the
    cell keeps its width and the fraction sits one column left of where it was
    with a blank behind it.  Every row in a stacked pair moves identically, so
    units still stack over units and tenths over tenths — which is the whole
    job, the point having only ever been the marker for it.

    It arrives here two ways.  Most callers hand over a string a decorated
    formatter has already converted, so the "." is gone before this sees it.
    signed_pct and the cost row's 🧠 cell format their own "%.1f" inline and
    are not routed through one, which is why the conversion is repeated on the
    way in: sub_dec is idempotent on a string that has already had it, and
    both of those always carry a leading digit, so its leading-zero rule
    cannot fire on a head this function is about to right-align separately.
    """
    v = sub_dec(v)
    head, _, tail = v.partition(".")
    if tail:
        frac = ".%s%s" % (tail, suffix)
    else:
        cut = next((i for i, ch in enumerate(v) if ch in E_SUB_DIGITS), None)
        if cut is None:
            head, frac = v, suffix
        else:
            head, frac = v[:cut], v[cut:] + suffix
    return "%*s" % (ip, head) + "%-*s" % (fp + 1 + len(suffix), frac)


def money_cell(c: float) -> str:
    """money_fmt decimal-aligned in the six columns both cost rows reserve.

    The unit is dec_align's SUFFIX rather than a column of its own, so that it
    rides the digits it qualifies: reserved separately it would line every
    unit up in a column of its own and strand each from its number — " 12  k"
    — which is the failure dec_align's own note describes for "0.13  ٪".

    It is one character ALWAYS, a space where there is no unit, and that is
    the whole reason this is a function and not two dec_align calls.  The
    suffix widens the field, so a "k" on the totals row and nothing on the
    per-prompt row above it would make the two cells six and five columns
    wide.  seg() pads the cost row on the LEFT, so the narrower one would not
    end a column short — it would be shoved a column right, off the field it
    has to stack on, and the misalignment would appear the first time a
    session crossed $1000 and nowhere in any test that had not.
    """
    s = money_fmt(c)
    unit = s[-1] if s[-1] in "kMG" else " "
    return dec_align(s[:-1] if unit != " " else s, 3, 1, unit)


def signed(n: int) -> str:
    """A token delta in exactly five columns: "+142k", "- 88k", "+ 855".

    The sign is always printed, including for a rise, because the field's whole
    subject is direction: an unsigned "88k" beside a context figure reads as a
    size, not a change.

    It gets a column of its own, ahead of a magnitude right-aligned in the four
    humanize() can need, rather than riding the digits as one unit — the same
    arrangement as signed_pct beside it and 💰 🔋 📆 further along.  Written
    as a unit the mark drifts: "+142k" sets its sign a column left of where
    "+88k" sets it, so on the 🧠 cell the leading glyph after the emoji is
    sometimes the sign and sometimes a space, and the totals row beneath — a
    magnitude with no sign at all — stacks under one or the other by accident.
    Pinned, the sign holds the column directly after 🧠 exactly as the "+" of
    🔋 and 📆 holds the column directly after theirs, and the totals row's
    blank sign column falls where a sign would have been.
    """
    return ("+" if n >= 0 else "-") + pad_val(4, humanize(abs(n)))


def signed_pct(n: int, whole: int) -> str:
    """A delta as a signed percentage of `whole`: sign, then six columns.

    One decimal always.  These are fractions of a context window, where the
    difference between 0.4٪ and 1.2٪ of a million tokens is the whole signal
    and an integer field would round most turns to "+0٪".

    The sign is printed in a column of its own and the figure decimal-aligned
    after it, rather than glued to the digits and right-aligned with them.
    That is the arrangement 💰, 🔋 and 📆 use further along the row, and
    matching it is the point: a sign carried by its number MOVES, so "+12.1٪"
    puts its mark two columns left of where "+1.4٪" does, and the one glyph on
    the row whose only job is to say which way the figure went is the one
    glyph that will not hold still.  Given its own column it stops moving, and
    the decimal point stacks under the totals row's absolute reading.

    The mark on those other three is a constant and this one is a sign —
    consumption only climbs, a context window can shrink — but that is a
    difference in what the mark MEANS, not in where a reader should have to
    look for it.
    """
    p = 100.0 * n / whole if whole else 0.0
    return "%s%s" % ("+" if p >= 0 else "-",
                     dec_align("%.1f" % min(abs(p), 99.9), 2, 1, E_PCT))


def pct(p: float) -> str:
    """A percentage in at most three columns, clamped so it never needs four."""
    return "%d%s" % (min(int(p), 99), E_PCT)


# ════════════════════════════════════════════════════════════════════════════
# Colour tiers.
# ════════════════════════════════════════════════════════════════════════════

def reset_dim(d: str) -> str:
    """DIM a reset countdown unless it is under an hour away.

    Reading the unit rather than re-deriving the seconds keeps this to one
    branch and keeps dur_fmt the only place that knows the arithmetic.

    Two levels where there were three shades of slate, so one of the old
    ladder's distinctions had to go.  Hours-against-days is the one that went:
    a window that resets tomorrow and one that resets this afternoon are the
    same news — not yet — while one resetting inside the hour is the only
    reading on the field a person acts on.  Bright means that and nothing
    else.  short_dur returns "now" for a moment already passed, which has no
    unit and so lands here as imminent, which it is.
    """
    return DIM if d.endswith(("d", "h")) else ""


def cache_color(p: int) -> str:
    """Colour the cache-hit rate.  INVERTED against the other tiers: a high
    number is the healthy one.  A collapse means something invalidated the
    cached prefix and the same work now bills about ten times over."""
    if p <= CACHE_CRIT:
        return F_RED
    if p <= CACHE_WARN:
        return F_AMB
    return F_GRN


# ════════════════════════════════════════════════════════════════════════════
# Terminal geometry.
#
# Where the row's width comes from, given that neither payload carries it and
# no tty is available to ask.
# ════════════════════════════════════════════════════════════════════════════

def _winsize(path: str) -> Optional[int]:
    """Columns of a tty device, by ioctl.  None if it cannot be read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOCTTY)
    except OSError:
        return None
    try:
        _rows, cols = struct.unpack(
            "hh", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 4))
        return cols if cols > 0 else None
    except OSError:
        return None
    finally:
        os.close(fd)


def term_cols() -> Optional[int]:
    """Columns in the terminal Claude Code is drawing into, or None.

    Neither obvious source works.  The payloads carry model, workspace, cost
    and rate-limit fields but no terminal geometry, and our own stdio are
    pipes — so `tput cols` would fall back to the terminfo default of 80
    SUCCESSFULLY, a wrong answer that never announces itself.  /dev/tty is not
    reachable either: the process has no controlling terminal, and opening it
    fails with ENXIO.

    What is true is that some ancestor owns the tty: our parent is the `claude`
    process, which is attached to the terminal.  So walk up until a process
    reports one and ask that device directly.  The walk is bounded — a login
    shell or launchd ancestor with no tty is where it stops anyway — and it is
    re-read every render, so a resize is picked up on the next frame rather
    than needing a restart.

    Returns None under `claude -p`, in cloud sessions, and anywhere else with
    no tty in the ancestry.  Every caller must have a layout for that.
    """
    p = os.getppid()
    for _ in range(6):
        if p <= 1:
            return None
        # One ps per hop, asking for both fields at once.  The shell version
        # this replaces spent two — a second process to fetch a number the
        # first call could have returned — and at roughly 10 ms a spawn that
        # was the single largest avoidable cost in the walk.
        try:
            out = subprocess.run(["ps", "-o", "tty=,ppid=", "-p", str(p)],
                                 capture_output=True, text=True).stdout.split()
        except Exception:
            return None
        if len(out) < 2:
            return None
        tty, parent = out[0], out[1]
        if tty and tty not in ("?", "??"):
            cols = _winsize("/dev/" + tty)
            if cols:
                return cols
        try:
            p = int(parent)
        except ValueError:
            return None
    return None


# ════════════════════════════════════════════════════════════════════════════
# Records.
# ════════════════════════════════════════════════════════════════════════════

class Payload(NamedTuple):
    """The status-line JSON, reduced to what is actually read."""
    current_dir: str
    project_dir: str
    model: str
    model_id: str
    ctx_window: str         # context_window.context_window_size, when given
    transcript: str
    cost_usd: str
    lines_added: str
    lines_removed: str
    output_style: str
    effort: str
    session_id: str
    rl_session_pct: str
    rl_session_reset: str
    rl_weekly_pct: str
    rl_weekly_reset: str
    pr_number: str


class Transcript(NamedTuple):
    """What one pass over the transcript yields for the status line.

    `tok_up` is None only when there was no transcript to read at all, which is
    a different state from a transcript that exists and is empty: the first
    suppresses the token segment, the second renders it as zeros.  Two empty
    states, two renderings, and conflating them was how a fresh session grew a
    "▴0 ▾0" that looked like a stall.
    """
    tok_up: Optional[int]
    tok_down: int
    cache_pct: int          # -1 when there is no usage data at all
    ctx_tokens: int
    user_ts: str
    user_text: str
    asst_ts: str
    asst_text: str
    busy_s: float           # seconds spent answering, summed over every turn
    start_s: float          # epoch of the first STAMPED record, 0 if none


EMPTY_TRANSCRIPT = Transcript(None, 0, -1, 0, "", "", "", "", 0.0, 0.0)


class Git(NamedTuple):
    in_git: bool
    branch: str
    dirty: bool
    toplevel: str
    main_root: str
    is_worktree: bool


NO_GIT = Git(False, "", False, "", "", False)


class Limits(NamedTuple):
    """The two plan windows.  Percentages are strings because a missing figure
    is the empty string throughout, which is what makes a blank row blank.

    They carry whatever precision their source gave them — see _pct_str — and
    are not rounded until limit_pct draws them.  A percentage here may be
    "0.38", so read one with _pct_num, never int().
    """
    session_pct: str
    session_reset: str
    session_share: str
    weekly_pct: str
    weekly_reset: str
    weekly_share: str
    # What the ONE turn just answered put into each window.  Defaulted, so
    # every construction that predates the field still builds, and left ""
    # by load_limits: only _with_shares has a transcript to derive it from.
    session_turn: str = ""
    weekly_turn: str = ""


NO_LIMITS = Limits("", "", "", "", "", "")


class Turn(NamedTuple):
    """One prompt the user typed, and everything billed while answering it."""
    ts: str
    text: str
    fresh: int
    cache_write: int
    cache_read: int
    out: int
    ctx: int                # a READING, not a sum — see read_turns
    calls: int
    dur_s: float            # wall-clock seconds this turn took to answer
    dctx: Optional[int]     # growth over the previous turn; None where there
                            # is no previous reading to subtract
    compact: bool = False   # a compaction rather than a prompt.  Its figures
                            # come from the boundary record, not from usage
    reported: bool = False  # a Stop hook has already run at a point AFTER this
                            # turn, so whatever this line owed for it has been
                            # printed once already.  See read_turns.
    parts: Tuple[Tuple[Optional[float], float], ...] = ()
                            # (epoch, dollars) for each billed call, in the
                            # order the transcript wrote them.  The fields
                            # above are SUMS, and a sum cannot be split at a
                            # window boundary that falls inside the turn — see
                            # turn_cost_since, which is the only reader.  The
                            # epoch is None where the stamp would not parse;
                            # the cost is still carried, so these always total
                            # turn_cost() whatever the stamps did.
                            # Empty for a compaction, which bills through no
                            # usage record at all.


# ════════════════════════════════════════════════════════════════════════════
# Reading the payload.
# ════════════════════════════════════════════════════════════════════════════

def _first(d: dict, *paths, **kw) -> str:
    """First present, non-null value among dotted `paths`, else `default`.

    Mirrors jq's `//` chain, including that it short-circuits on null or
    absent but NOT on a present falsy value like 0 or false.
    """
    default = kw.get("default", "")
    for path in paths:
        cur = d
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None and cur is not False:
            return cur if isinstance(cur, str) else _num(cur)
    return default


def _num(v) -> str:
    """A JSON number the way jq -r prints it: integers without a decimal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return "%d" % v
    return "%s" % v


def read_payload(raw: str) -> Payload:
    """Parse the status-line JSON.  A malformed payload yields empty fields
    rather than an exception: a status line that renders nothing is a worse
    failure than one that renders a row of blanks."""
    try:
        d = json.loads(raw)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    return Payload(
        current_dir=_first(d, "workspace.current_dir", "cwd"),
        project_dir=_first(d, "workspace.project_dir", "cwd"),
        model=_first(d, "model.display_name"),
        model_id=_first(d, "model.id"),
        ctx_window=_first(d, "context_window.context_window_size"),
        transcript=_first(d, "transcript_path"),
        cost_usd=_first(d, "cost.total_cost_usd"),
        lines_added=_first(d, "cost.total_lines_added", default="0"),
        lines_removed=_first(d, "cost.total_lines_removed", default="0"),
        output_style=_first(d, "output_style.name"),
        effort=_first(d, "effort.level"),
        session_id=_first(d, "session_id"),
        rl_session_pct=_first(d, "rate_limits.five_hour.used_percentage"),
        rl_session_reset=_first(d, "rate_limits.five_hour.resets_at"),
        rl_weekly_pct=_first(d, "rate_limits.seven_day.used_percentage"),
        rl_weekly_reset=_first(d, "rate_limits.seven_day.resets_at"),
        # Five alternate locations, first non-null wins.  Claude Code has moved
        # this field before and may again.
        pr_number=_first(d, "pr.number", "github.pr.number",
                         "github.pull_request.number", "github_pr.number",
                         "pull_request.number"),
    )


# ════════════════════════════════════════════════════════════════════════════
# Reading the transcript.
# ════════════════════════════════════════════════════════════════════════════

def _records(path: str):
    """Yield parsed JSONL records, skipping any line that will not parse.

    A transcript is appended to live, so the last line can be a partial write.
    Skipping is the only reasonable response; failing would blank the row for
    whichever frame caught the file mid-append.
    """
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                yield json.loads(line)
            except Exception:
                continue


def _dedupe_usage(records: Sequence[dict]) -> List[dict]:
    """Assistant records carrying usage, deduped FIRST-WINS on request id.

    Two reasons this matters, and the second is the one that gets forgotten:

      1. Claude Code writes one JSONL line per content block — thinking, text,
         each tool call — and repeats the whole usage object on every one.  A
         turn with ten parallel Reads writes twelve lines all claiming the same
         cache reads, so summing lines instead of requests inflates the total
         about fourfold.
      2. A RETRIED request appears again with the same id.  First-wins is what
         stops the retry being billed twice; last-wins or no dedupe both
         double-count it.

    Order-preserving, because callers below take the LAST non-sidechain entry
    and a re-sort would lose track of which request that was.
    """
    seen = set()
    out = []
    for r in records:
        if not (r.get("message") or {}).get("usage"):
            continue
        k = r.get("requestId") or (r.get("message") or {}).get("id") or "?"
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# Pictographs whose DEFAULT PRESENTATION IS TEXT, as sorted ranges.
#
# EAW_WIDE above blankets 1F300-1FBFF as two columns, and that blanket is
# wrong for about 1,600 codepoints in it.  UAX #11 gives Wide to a pictograph
# whose default presentation is emoji and Neutral to the rest, so this table
# is the blanket's exceptions: 🛢 U+1F6E2, 🕰 U+1F570, 🗓, 🗑, 🎟, 🌡 and the
# rest of that family.  With no emoji presentation they are drawn from
# whatever text font the terminal reaches for — one column in some, two in
# others, and 🛢 and 🕰 disagree with each other on the SAME terminal.
#
# It is not used to measure anything.  vis_width still trusts the blanket,
# because everything this file PRINTS is chosen to be emoji-presentation and
# the blanket is right for all of it.  This table is used by squash, to
# escape the ones that turn up in chat text, where nobody vets the glyphs.
#
# 1F1E6-1F1FF, the regional indicators, are in here for a different reason
# and belong: a flag is two of them, four columns where clusters are not
# folded and two where they are — the terminal decides, so it cannot be
# measured either.
#
# Generated from unicodedata (UCD 15.0.0), which is the right authority for this
# one question: what is asked is the codepoint's declared presentation, not
# what some terminal does with it.  KEEP IT SORTED — the scan stops at the
# first range starting above the codepoint.
EAW_TEXT_PRES = (
    (126976, 126979), (126981, 127182), (127184, 127373), (127375,
    127376), (127387, 127487), (127491, 127503), (127548, 127551),
    (127561, 127567), (127570, 127583), (127590, 127743), (127777,
    127788), (127798, 127798), (127869, 127869), (127892, 127903),
    (127947, 127950), (127956, 127967), (127985, 127987), (127989,
    127991), (128063, 128063), (128065, 128065), (128253, 128254),
    (128318, 128330), (128335, 128335), (128360, 128377), (128379,
    128404), (128407, 128419), (128421, 128506), (128592, 128639),
    (128710, 128715), (128717, 128719), (128723, 128724), (128728,
    128731), (128736, 128746), (128749, 128755), (128765, 128991),
    (129004, 129007), (129009, 129291), (129339, 129339), (129350,
    129350), (129536, 129647), (129661, 129663), (129673, 129679),
    (129726, 129726), (129734, 129741), (129756, 129759), (129769,
    129775), (129785, 130047),
)


def _text_pres(cp: int) -> bool:
    """Is this a pictograph the terminal will draw from a TEXT font?

    The table is sorted, so the scan stops at the first range starting above
    the codepoint — the same walk vis_width does.
    """
    for lo, hi in EAW_TEXT_PRES:
        if cp < lo:
            return False
        if cp <= hi:
            return True
    return False


def squash(s: str, fold: str = E_FOLD) -> str:
    """Make chat text safe to measure, and flatten it to one line.

    Chat text is the one part of the row nobody vets: it is whatever was said,
    and a single glyph whose width this file guesses wrong drags the whole
    metric block out of line — or pushes the row past the margin, where Ink
    cuts it off.

    So the glyphs that cannot be trusted are replaced by their codepoint in
    ASCII: <27F3> in place of a reset arrow.  That is wider than the glyph, but
    it is ASCII, so its width is exact and the row can be measured to the
    column.  It also SAYS what was there, which a dot did not — a row reading
    <1FAA3> is a bug report, where a row reading a dot is only a mystery.

    Two families qualify.  U+2190-U+2BFF is arrows, misc technical, misc
    symbols and dingbats, where terminals disagree glyph by glyph and a
    neighbouring codepoint is no guide.  Variation selectors are the other,
    being the construction behind every rendering fault recorded in this file.

    Pictographs used to be left alone wholesale, on the claim that everything
    from U+1F300 up measures two columns in both terminals.  That was wrong,
    and 🛢 U+1F6E2 is how it was found out: a pictograph with no default emoji
    presentation is drawn from whatever text font the terminal reaches for,
    which is one column in some and two in others — the same fault as the
    U+2190 block, in a range this function trusted.

    The test that separates them is already in the file.  UAX #11 gives East
    Asian Width Wide to pictographs whose default presentation is emoji and
    Neutral to the rest, so a pictograph MISSING from EAW_WIDE is exactly one
    whose width cannot be trusted — 🛢, 🕰, 🗓, 🗑, 🎟, 🌡 and about 1,600
    others.  Escaping by the table also means the two stay in step: a glyph
    this file cannot measure is a glyph it will not print.

    Regional indicators fall out of the same test and should.  A flag is two
    of them, drawn as one glyph by a terminal that folds clusters and two by
    one that does not — four columns against two, decided by the terminal.
    """
    out = []
    for ch in s:
        cp = ord(ch)
        if (8592 <= cp <= 11263) or (65024 <= cp <= 65039) \
                or _text_pres(cp):
            out.append("<%X>" % cp)
        else:
            out.append(ch)
    t = "".join(out).replace("\n", fold).replace("\t", " ")
    return re.sub(" +", " ", t)


def ts_epoch(ts: str) -> Optional[float]:
    """A transcript timestamp as a Unix epoch, or None if it is not one.

    Transcript stamps are UTC with a trailing "Z", which 3.9's fromisoformat
    rejects outright — hence strptime on a stripped string with the zone
    reattached, the same dance elapsed_short does.
    """
    if not ts:
        return None
    try:
        return datetime.strptime(ts.split(".")[0].rstrip("Z"),
                                 "%Y-%m-%dT%H:%M:%S").replace(
                                     tzinfo=_UTC).timestamp()
    except ValueError:
        return None


def read_transcript(path: str) -> Transcript:
    """One pass for the status line: totals, cache rate, context, last texts.

    Context size comes from the last NON-SIDECHAIN request only.  A subagent
    runs its own context, and letting its usage land here would make the main
    thread's occupancy jump around as subagents come and go.  The filter
    applies to that one field: a subagent's tokens still count toward the
    totals and the cost, because they were still billed.
    """
    records = list(_records(path))
    reqs = _dedupe_usage(records)
    fresh = cwrite = cread = down = 0
    for r in reqs:
        u = r["message"]["usage"]
        fresh += u.get("input_tokens") or 0
        cwrite += u.get("cache_creation_input_tokens") or 0
        cread += u.get("cache_read_input_tokens") or 0
        down += u.get("output_tokens") or 0
    in_all = fresh + cwrite + cread

    ctx = 0
    for r in reqs:
        if r.get("isSidechain") is not True:
            u = r["message"]["usage"]
            # Skip a request whose usage is all zero.  That is how an
            # interrupted request is recorded, and letting it win the
            # last-write would blank the whole 🧠 cell on the status line for
            # the rest of the session.  See read_turns for the count.
            _c = ((u.get("input_tokens") or 0)
                  + (u.get("cache_creation_input_tokens") or 0)
                  + (u.get("cache_read_input_tokens") or 0))
            if _c:
                ctx = _c

    user_ts = user_text = asst_ts = asst_text = ""
    for r in records:
        c = (r.get("message") or {}).get("content")
        if (r.get("type") == "user" and r.get("userType") == "external"
                and isinstance(c, str) and len(c) > 0
                and not c.startswith("<")):
            user_ts, user_text = r.get("timestamp") or "", c
        if r.get("type") == "assistant":
            blocks = (r.get("message") or {}).get("content") or []
            if isinstance(blocks, list):
                texts = [b for b in blocks
                         if isinstance(b, dict) and b.get("type") == "text"]
                if texts:
                    asst_text = texts[-1].get("text") or ""
                    asst_ts = r.get("timestamp") or ""

    # Time spent ANSWERING, which is not the time the session has existed.  A
    # turn runs from the prompt that opens it to the last record before the
    # next prompt, so summing those spans counts the working time and skips
    # every gap where the session sat waiting for someone to type.  The two
    # figures together are the point of the pair: 1.9h of work inside an 18h
    # session says something neither number says alone.
    busy = 0.0
    first = open_at = prev = None
    for r in records:
        t = ts_epoch(r.get("timestamp") or "")
        if t is None:
            continue
        if first is None:
            first = t
        if turn_start_text(r) is not None:
            if open_at is not None and prev > open_at:
                busy += prev - open_at
            open_at = prev = t
        elif open_at is not None and is_work(r):
            prev = t
    if open_at is not None and prev > open_at:
        busy += prev - open_at

    return Transcript(
        busy_s=busy,
        # The first STAMPED record, not records[0]: a transcript can open with
        # an unstamped one, and taking its empty timestamp blanked the field
        # outright rather than degrading it.
        start_s=first or 0.0,
        tok_up=int(fresh + W_CACHE_WRITE * cwrite + W_CACHE_READ * cread),
        tok_down=down,
        # -1 is a sentinel meaning "no usage data at all", which is a different
        # state from a legitimate 0% and renders as no segment rather than as
        # a zero.
        cache_pct=int(100 * cread / in_all) if in_all > 0 else -1,
        ctx_tokens=ctx,
        user_ts=user_ts,
        user_text=squash(user_text),
        asst_ts=asst_ts,
        asst_text=squash(asst_text),
    )


def opens_turn(r: dict) -> bool:
    """True for a record that OPENS a turn — the unit the cost line reports.

    Two kinds do, and the second was missing for as long as this file has
    existed.  A prompt the user typed is one.  The other is a message
    DELIVERED to an idle session, which Claude Code writes as `type: user`
    with `promptSource: "system"`.  There are four of them, and across 130
    transcripts on this machine they are the only things that field ever
    marks: a `<task-notification>` from a background task finishing (253), a
    message from another session (92), a cross-session idle notice (6), and
    the usage limit resetting (4).  The session answers each of them exactly
    as it answers a typed prompt, and the answer is billed exactly the same
    way, so each is a turn.

    Left out, they were not merely mislabelled.  A wake message is often the
    FIRST thing in a transcript — another session writes to a session the user
    has not typed into yet — and `read_turns` drops assistant records that
    precede the first recognised prompt, because there is no turn to attribute
    them to.  Measured in one such session: 74 of its 87 requests, 15.7M of
    cache-read and 112k of output, reported by no row and counted in no total,
    and the Stop hook printing "(no prompts recorded yet)" 37 minutes in.
    Where a typed prompt did precede them, their work went onto ITS turn
    instead, so the 🎤 row reprinted the previous prompt with the peer turn's
    figures added to it.

    What is still excluded, and why each one has to be:

      * isCompactSummary — the summary /compact injects.  Prose, and it does
        not begin with '<', so the shape checks alone let it through.
      * strings opening with '<' — tool results and system reminders.  This
        does NOT apply to the wake branch: `<task-notification>` opens with
        the character, and `promptSource` is what tells the two apart.
      * isMeta on a TYPED record.  A wake message is usually marked isMeta as
        well, so the flag cannot be the test on that branch.
      * promptSource "queued" — a typed prompt handed over from the queue.
        Its turn boundary is the queue's own removal record, which carries the
        text and a timestamp of when the model actually got it; see
        `queued_text`.  Reading both would open the turn twice.

    The exclusion this replaces was written against a mid-turn injection —
    "four in a row landed inside one turn" — and that shape does not exist in
    any transcript here: of the 355 wake records, not one is preceded by an
    assistant record or a tool result.  Every one sits at a turn boundary,
    after a queue dequeue, a turn_duration, or another wake record delivered
    in the same batch.  A peer message that genuinely arrives mid-turn gets no
    `type: user` record at all — only a queue `remove`, whose content opens
    with '<' and is refused by `queued_text`.  A batch delivered together
    opens one turn each, the earlier ones with no requests under them, which
    is the queue-drain case `render_cost_line` already skips past.

    promptSource is checked permissively on the typed branch (absent counts as
    typed) so that transcripts written before the field existed still segment
    correctly.
    """
    c = (r.get("message") or {}).get("content")
    if (r.get("type") != "user" or r.get("userType") != "external"
            or r.get("isCompactSummary")
            or not isinstance(c, str) or len(c) == 0):
        return False
    if r.get("promptSource") == "system":
        return True
    return (not r.get("isMeta")
            and r.get("promptSource", "typed") == "typed"
            and not c.startswith("<"))


# Every enqueue is matched by exactly one of these — 1886 of each across 112
# transcripts — so a removal is a delivery, not a cancellation.  The three
# spellings are the queue draining one item, draining all of them, and the
# item being taken off the front; none of them means the message was dropped.
QUEUE_DELIVERED = ("remove", "dequeue", "popAll")


def queued_text(r: dict) -> Optional[str]:
    """The prompt a `queue-operation` record delivered, or None.

    A message typed while the assistant is working does NOT get a `type: user`
    record.  It goes into a queue, and the only trace in the transcript is a
    pair of `queue-operation` records — an enqueue when it was typed and a
    removal when it was handed to the model.  Nothing else is written: the
    text reaches the model inside the turn already in flight.

    Left unread, every queued prompt is invisible as a turn boundary and its
    work is filed under whichever message the user last typed while the
    assistant was IDLE.  Measured over 80 transcripts: 859 queued prompts
    against 991 typed ones, so in a session that uses the queue at all this
    was mis-segmenting close to half of them.  That is the whole of the
    "Prompt (last) is the prompt before last" complaint, and most of the
    "elapsed time is far too long" one — a merged turn spans every gap the
    user spent reading and typing between the messages it swallowed.

    The removal is the boundary, not the enqueue: the enqueue is stamped when
    the message was TYPED, which can be minutes before the assistant was free
    to read it, and that waiting is the user's, not the machine's.

    Unlike `opens_turn`, this one is TYPED-ONLY, and deliberately so.  A turn
    can also be opened by a message nobody typed — that is why `opens_turn` is
    not called `is_prompt` — but those arrive as `type: user` records with
    `promptSource: "system"`, never through this queue.  What DOES ride this
    queue alongside typed prompts is machinery, and the shape rule below
    refuses it.  So "prompt" is accurate here in a way it is not one function
    up.
    """
    if r.get("type") != "queue-operation":
        return None
    if r.get("operation") not in QUEUE_DELIVERED:
        return None
    c = r.get("content")
    # The same shape rule as opens_turn's TYPED branch — not as opens_turn as a
    # whole, which lets a `promptSource: "system"` record through regardless of
    # what it opens with.  Task notifications and other machinery ride this
    # queue too, and every one of them opens with '<'.
    return c if isinstance(c, str) and len(c) > 0 and not c.startswith("<") \
        else None


def turn_start_text(r: dict) -> Optional[str]:
    """The text of the prompt this record opens, or None if it opens none."""
    if opens_turn(r):
        return (r.get("message") or {}).get("content")
    return queued_text(r)


def is_work(r: dict) -> bool:
    """True for a record written while the assistant was answering.

    What this excludes is the point.  A turn ends at the last record the
    ANSWER produced, and the transcript keeps appending long after that: the
    caveat and command records a slash command writes, the enqueue stamped
    when the user typed their next message, the compact summary.  Those carry
    the timestamp of whenever the user got round to it, so counting them as
    part of the turn charges the assistant for the user's reading time — an
    idle overnight gap turned one turn into 1.3h of "answering".

    Tool results are the case that has to stay IN: they arrive as `type: user`
    with a LIST of blocks, and a turn that finishes with one took until that
    result.  A person's message is always a plain string, so the shape of the
    content is what separates the two.
    """
    t = r.get("type")
    if t in ("assistant", "system"):
        return True
    if t == "user":
        return isinstance((r.get("message") or {}).get("content"), list)
    return False


# Characters per token for the compaction summary, calibrated against the
# metadata rather than assumed: the two compactions in this session summarised
# to 16,201 and 23,659 characters against postTokens of 6,597 and 8,737, and
# postTokens is the summary PLUS the handful of preserved messages.  At 4 the
# estimate leaves 700 and 2,800 tokens for those, which is the right order.
# Three would leave none, five would leave more than the messages can hold.
SUMMARY_CPT = 4.0


def read_turns(path: str) -> Tuple[Turn, ...]:
    """Segment the transcript into prompts, with each turn's billed usage.

    `ctx` is LAST-WRITE-WINS within a turn and skips sidechains — it is an
    instantaneous reading of how big the window is, not a sum of anything.  A
    port that accumulates it produces a figure that looks like cumulative
    tokens and is not a context size at all.

    Assistant records appearing before the first recognised prompt are dropped:
    there is no turn to attribute them to.
    """
    turns = []      # built mutably here, frozen into NamedTuples on the way out
    settled = 0     # turns that a Stop hook has already run past
    cur = None
    seen = set()
    for r in _records(path):
        text = turn_start_text(r)
        if text is not None:
            # A queued message can be recorded BOTH ways — once typed, once
            # delivered — in the one case in 859 where the queue drained
            # while the assistant was already idle.  The earlier of the two
            # has no records under it yet, so replacing it in place keeps one
            # turn rather than two, and keeps the later timestamp, which is
            # when the answering actually started.
            if (cur is not None and cur["n"] == 0 and cur["t1"] is None
                    and cur["text"] == text):
                cur["ts"] = r.get("timestamp") or cur["ts"]
                cur["t0"] = ts_epoch(r.get("timestamp") or "")
                continue
            cur = {"ts": r.get("timestamp") or "", "text": text,
                   "fresh": 0, "cw": 0, "cr": 0, "out": 0, "ctx": 0, "n": 0,
                   "t0": ts_epoch(r.get("timestamp") or ""), "t1": None,
                   "parts": []}
            turns.append(cur)
        elif r.get("subtype") == "compact_boundary":
            # A compaction is the one expensive operation that leaves NO usage
            # record anywhere — the request that summarises the conversation
            # is never written to the transcript.  What IS written is this
            # boundary record, and between them its fields say almost
            # everything the row needs:
            #
            #   preTokens   what was fed to the summariser.  Measured against
            #               our own last reading before the boundary — 292,645
            #               against 289,457 — so it is the same quantity this
            #               file calls ctx, to within a percent.
            #   durationMs  how long it took, which is otherwise unknowable:
            #               the turn has no records to bound it with.
            #   postTokens  NOT comparable to our readings, and deliberately
            #               unused: it counts the compacted conversation
            #               alone, where every reading here also carries the
            #               system prompt and the tool definitions.  8,737
            #               against the 95,691 the next request measured.  The
            #               drop across the boundary is reported by that next
            #               turn, in units that can be checked.
            #
            # The input is charged at the cache-read rate.  The summariser is
            # handed the conversation that was live seconds earlier, so it
            # reads the prefix the session has been paying to keep warm; the
            # alternative — full rate on 300k tokens — would put the figure
            # ten times too high.
            # An AUTO compaction has no /compact prompt in front of it: the
            # boundary lands inside whatever turn was running, and filling
            # that turn in would overwrite a real prompt's figures with the
            # compaction's.  So the compaction gets a turn of its own unless
            # the one open is the /compact that asked for it.
            md = r.get("compactMetadata") or {}
            if cur is None or cur["n"] or cur["text"].strip() != "/compact":
                cur = {"ts": r.get("timestamp") or "",
                       "text": "/compact (%s)" % (md.get("trigger") or "auto"),
                       "fresh": 0, "cw": 0, "cr": 0, "out": 0, "ctx": 0,
                       "n": 0, "t0": ts_epoch(r.get("timestamp") or ""),
                       "t1": None, "parts": []}
                turns.append(cur)
            cur["cr"] = md.get("preTokens") or 0
            cur["n"] = 1
            cur["dur"] = (md.get("durationMs") or 0) / 1000.0
            cur["compact"] = True
        elif (r.get("subtype") == "stop_hook_summary"
              and not r.get("isSidechain")):
            # The transcript's own record that a Stop hook RAN, written after
            # the hook returns.  It is the only mark in the file of where a
            # previous cost line drew its window, and it is what makes
            # "report each compaction exactly once" true rather than nearly
            # true.
            #
            # The pairing it replaces inferred that boundary from the prompts:
            # a compaction falls between two consecutive answered prompts, and
            # the second of them reports it.  That holds only while every Stop
            # sees its own prompt.  When one does not — the transcript is not
            # flushed in step with the hook, see read_turns_settled — two
            # consecutive Stops share a window, the pair that straddles the
            # compaction never gets a Stop of its own, and the row is not
            # late: it is gone.  Measured, in this file's own transcript: 18k
            # of cache-read and 1.2m of wall clock reported nowhere.
            settled = len(turns)
        elif r.get("isCompactSummary") and cur is not None and cur.get("compact"):
            # The one figure the metadata does not carry is what the
            # summariser WROTE, and this is it — arriving one record after the
            # boundary, and with an earlier timestamp than it.  Estimated from
            # the text, and the only estimate on either row: everything else
            # here is read or measured.
            _c = (r.get("message") or {}).get("content")
            if isinstance(_c, str):
                cur["out"] = int(len(_c) / SUMMARY_CPT)
        elif r.get("type") == "assistant" and (r.get("message") or {}).get("usage"):
            k = r.get("requestId") or (r.get("message") or {}).get("id")
            if k in seen or cur is None:
                continue
            seen.add(k)
            u = r["message"]["usage"]
            cur["fresh"] += u.get("input_tokens", 0)
            cur["cw"] += u.get("cache_creation_input_tokens", 0)
            cur["cr"] += u.get("cache_read_input_tokens", 0)
            cur["out"] += u.get("output_tokens", 0)
            cur["n"] += 1
            # The same four products turn_cost takes over the sums, taken here
            # over the one record, so the parts total the whole EXACTLY and a
            # window-bounded share and an unbounded one stay on one scale.
            # Sidechain records are included for that reason and no other:
            # they are in the sums four lines up, so leaving them out here
            # would make the parts total something turn_cost never says.
            cur["parts"].append((
                ts_epoch(r.get("timestamp") or ""),
                u.get("input_tokens", 0) * P_IN
                + u.get("output_tokens", 0) * P_OUT
                + u.get("cache_read_input_tokens", 0) * P_CR
                + u.get("cache_creation_input_tokens", 0) * P_CW))
            if not r.get("isSidechain"):
                # LAST-WRITE-WINS, but only over readings that exist.  An
                # interrupted request is written with every usage field zero,
                # and taking that as the reading WIPES the real one captured
                # seconds earlier — the turn then reports no context at all
                # and its 🧠 cell goes blank.  20 such records in 25,782, and
                # they cluster exactly where they hurt: a request is
                # interrupted when the user types over it, which is the same
                # moment they are watching the line for an answer.
                _ctx = (u.get("input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0))
                if _ctx:
                    cur["ctx"] = _ctx
        # Every stamped record of the ANSWER moves the turn's end, not just
        # the billed ones: a turn that finishes with a tool result took until
        # that result, and counting only usage records would stop the clock
        # early.  is_work is what keeps the user's own time out of it.
        if cur is not None and is_work(r):
            _t = ts_epoch(r.get("timestamp") or "")
            if _t is not None:
                cur["t1"] = _t

    # Context growth per turn: how much bigger the window got while this prompt
    # was answered.  The first turn of a transcript gets None rather than its
    # own absolute size — there is no previous reading to subtract, and
    # reporting the absolute figure as though it were growth would be a lie in
    # the one place nobody could check it.  A RESUMED session is the same case:
    # its first turn continues a window this transcript never saw, so a delta
    # across that boundary would be fiction.
    #
    # A compaction shows as a large negative, which is left signed rather than
    # clamped: it is the most useful thing this field can ever report.
    #
    # For it to show at all, prev has to SKIP a turn that carries no reading.
    # A /compact turn records ctx=0 — the compaction issues no request whose
    # usage could be counted — and advancing prev onto that zero blanked the
    # cell TWICE: once for the compact turn, and again for the prompt after
    # it, whose delta against nothing is unknowable.  Two rows lost, and the
    # one figure worth having lost with them.  Holding prev at the last real
    # reading spans the gap instead, so the next prompt reports the drop
    # across the compaction and this comment stops being a promise.
    out = []
    prev = None
    for t in turns:
        dctx = (t["ctx"] - prev["ctx"]
                if prev is not None and t["ctx"] else None)
        out.append(Turn(ts=t["ts"], text=t["text"], fresh=t["fresh"],
                        cache_write=t["cw"], cache_read=t["cr"], out=t["out"],
                        ctx=t["ctx"], calls=t["n"], dctx=dctx,
                        compact=bool(t.get("compact")),
                        reported=len(out) < settled,
                        parts=tuple(t["parts"]),
                        dur_s=(t["dur"] if t.get("dur") else
                               (t["t1"] - t["t0"]
                                if t["t0"] and t["t1"] and t["t1"] > t["t0"]
                                else 0.0))))
        if t["ctx"]:
            prev = t
    return tuple(out)


# How long the Stop hook waits for the turn it is about to report to appear in
# the transcript, and how often it looks.  1.5s against a hook timeout of 20s
# and a typical run of 120ms: room for the write to land, nowhere near the
# budget that would make the hook itself the thing keeping the turn waiting.
SETTLE_S = 1.5
SETTLE_POLL_S = 0.025


def read_turns_settled(path: str, budget: float = SETTLE_S,
                       poll: float = SETTLE_POLL_S) -> Tuple[Turn, ...]:
    """`read_turns`, having waited for the turn being reported to be written.

    The transcript is NOT flushed in step with the Stop hook.  The records the
    turn just produced carry timestamps from before the hook fires and are
    still not in the file when it reads:

        record 383  assistant +usage   12:06:59.976   ┐ both absent from the
        record 384  assistant +usage   12:07:00.296   ┘ file at 12:07:01.4
        record 387  system/stop_hook_summary  12:07:01.516

    A turn with no usage record looks like a prompt that was never answered,
    and `render_cost_line` deliberately falls back to the last prompt that WAS
    — printing a row of zeros for a prompt the user just watched being
    answered is the worse failure.  So the line silently reported the PREVIOUS
    prompt: the same figures twice, one record apart, `▴561k` and then `▴580k`
    for a single 28-minute turn.  Every `🎤` row was short of its own turn by
    whatever the last request billed; on a turn that made no tool calls it was
    short by the whole turn.

    Waiting is the only stateless fix, because nothing in the payload says
    which turn the hook was called for.  It costs nothing in the case that
    does not need it — the check is one `read_turns` that was going to happen
    anyway — and it is bounded in the case that never settles: a turn
    interrupted before it billed anything gets `budget` of dead time once and
    then reports exactly what it reports today.

    `st_size` gates the re-read so a wait that spans the whole budget parses
    the transcript once, not sixty times.
    """
    turns = read_turns(path)
    if not budget or (turns and turns[-1].calls):
        return turns
    deadline = time.monotonic() + budget
    try:
        size = os.stat(path).st_size
    except OSError:
        return turns
    while time.monotonic() < deadline:
        time.sleep(poll)
        try:
            grown = os.stat(path).st_size
        except OSError:
            break
        if grown == size:
            continue
        size = grown
        turns = read_turns(path)
        if turns and turns[-1].calls:
            break
    return turns


# ════════════════════════════════════════════════════════════════════════════
# Git.
# ════════════════════════════════════════════════════════════════════════════

def _git(*args: str) -> Optional[str]:
    """Run git with locking disabled, or None if it fails."""
    try:
        p = subprocess.run(("git", "--no-optional-locks") + args,
                           capture_output=True, text=True)
    except Exception:
        return None
    return p.stdout.rstrip("\n") if p.returncode == 0 else None


def _main_root(common: str, toplevel: str) -> Tuple[str, bool]:
    """Resolve --git-common-dir to the MAIN repo root, and say if we are in a
    linked worktree.

    --show-toplevel returns the CURRENT worktree's root, which for a linked
    worktree is the worktree directory and not the main repo.  --git-common-dir
    always points at the main repo's .git, shared across all worktrees, so
    dirname of it is the main repo root wherever we are.  That is what makes a
    worktree at ~/repo/.claude/worktrees/foo show the project as "repo" rather
    than "foo" — the worktree's branch is already conveyed by the 🌿 segment.
    """
    if not common.startswith("/"):
        common = toplevel + "/" + common
    root = common[:-5] if common.endswith("/.git") else common.rsplit("/", 1)[0]
    return root, bool(toplevel and toplevel != root)


def detect_git() -> Git:
    """Read the git context in three invocations.

    --abbrev-ref and --short cannot both be asked for in one rev-parse: flag
    modes apply globally to every rev in the call, so mixing them clobbers one.
    Hence the separate symbolic-ref.
    """
    out = _git("rev-parse", "--show-toplevel", "--git-common-dir", "--short",
               "HEAD")
    if out is None:
        # Either not a repo, or a repo with no commits yet.  Distinguish them
        # cheaply so the empty-repo case still gets a project name.
        if _git("rev-parse", "--is-inside-work-tree") is None:
            return NO_GIT
        toplevel = _git("rev-parse", "--show-toplevel") or ""
        common = _git("rev-parse", "--git-common-dir") or ""
        root, wt = _main_root(common, toplevel) if common else ("", False)
        return Git(True, "", False, toplevel, root, wt)

    lines = out.split("\n")
    toplevel = lines[0] if len(lines) > 0 else ""
    common = lines[1] if len(lines) > 1 else ""
    sha = lines[2] if len(lines) > 2 else ""
    root, wt = _main_root(common, toplevel)
    branch = _git("symbolic-ref", "--short", "HEAD")
    if branch is None:
        branch = sha                       # detached HEAD
    dirty = _git("diff", "--quiet", "HEAD") is None    # staged + unstaged
    return Git(True, branch, dirty, toplevel, root, wt)


def project_name(git: Git, project_dir: str) -> str:
    """The project name: basename of the MAIN repo root inside a repo, and the
    literal "[none]" outside one — deliberately not the cwd's basename, which
    would imply a project that is not there."""
    if not git.in_git:
        return "[none]"
    n = (git.main_root or git.toplevel).rstrip("/").rsplit("/", 1)[-1]
    if not n:
        n = project_dir.rstrip("/").rsplit("/", 1)[-1]
    return n or "?"


def ctx_window_for(size: str, name: str) -> int:
    """The context window: Claude Code's own figure, or a guess from the name.

    The payload carries context_window.context_window_size, which is the
    number the thing enforcing the window is actually using.  Prefer it
    absolutely.  Reading the model's NAME for a "1m" was always inference
    dressed as fact, and it is wrong in both directions: a model whose window
    is not written into its id reads as 200k whatever it really is, which is
    why switching to Fable dropped the ruler to 200k, and why coming back to
    an Opus selected without the [1m] suffix left it there.

    The name remains the fallback, for a payload that predates the field or
    omits it.  Kept deliberately: a ruler that guesses is better than a row
    with a hole in it, and the guess is right for the id it was written for.
    """
    if size.isdigit() and int(size) > 0:
        return int(size)
    low = name.lower()
    return CTX_1M if ("1m" in low or "1000000" in low) else CTX_DEF


# ════════════════════════════════════════════════════════════════════════════
# Plan limits.
# ════════════════════════════════════════════════════════════════════════════

def _pct_num(v) -> Optional[float]:
    """A carried percentage back as a number, or None if it is not one.

    None rather than 0.0 for the unparseable case, because a missing figure and
    a window at zero are the two things this section spends most of its care
    keeping apart.
    """
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct_str(v: Optional[float]) -> str:
    """A percentage as the limit rows carry it, or "" for a missing figure.

    Nothing is rounded here, which is the point: the payload's used_percentage
    is a float and this used to meet it with "%.0f", so a window at 0.38٪
    reached the renderer as "0" and no later code could tell that from a window
    at nothing.  Precision is now thrown away once, in limit_pct, where the
    column budget is actually known.

    "%g" rather than "%s" for two reasons.  It writes a whole percentage as
    "15", not "15.0" — the baseline file this string goes into was read by
    statusline.sh with a digits-only test that "15.0" fails.  That reader is
    retired (archive/), so only the second reason still binds: "%g" holds the
    figure to six significant digits, so subtracting two readings cannot write
    "0.19999999999999996" into a file the next render has to parse.
    """
    return "" if v is None else "%g" % v


# ════════════════════════════════════════════════════════════════════════════
# Usage sources: where a plan reading comes from when the payload has none.
#
# Claude Code's own payload is always preferred and never comes through here.
# Its `rate_limits` block is the API's own accounting, arriving with the render
# — see load_limits, which is all-or-nothing about it.  But two of the sixteen
# payload shapes in the corpus carry no such block, and the Stop hook's payload
# never does, so there has to be a second channel, and something has to fill
# it.
#
# WHAT THIS REPLACES.  The channel used to be a shell script outside this
# repository: ~/.claude/usage-limits.sh, wrapping ~/.claude/usage-now.sh,
# wrapping `defaults export`, wrapping a python3 of its own.  Three processes
# and two files that were never installed with the program and were named
# nowhere in its README, so a clone of this repository could not read a plan
# figure at all and nothing on the readout said why.
#
# It also broke without saying so.  The menu-bar app moved its snapshot
# history out of UserDefaults into a file at some point before 2026-09-05 —
# the store still carries the `usageHistoryMigratedToFiles_v1` marker of it —
# and the `usageHistory_<uuid>` key both scripts keyed off simply stopped
# existing.  The wrapper caught the failure, printed "{}", exited 0, and the
# fallback answered "no reading" for days.  That is the shape of failure a
# three-layer shell-out has: every layer swallows, and the last one is not
# even in the repository whose tests would have caught it.
#
# THE INTERFACE.  A source is an object with a name, an `available()` and a
# `read()`; `read()` returns a plain dict and may return {}.  Everything else
# — coercion, the future guard on a reset time, dropping fields nobody asked
# for — happens once in normalise_reading, so a new source is a class with one
# method that returns whatever shape it has and no obligation to know how the
# readout uses it.
#
# Three ways to plug one in, in increasing order of effort:
#
#   1. --usage-source cmd:/path/to/script — any executable that prints a
#      reading as JSON on stdout.  This is the old usage-limits.sh contract
#      exactly, so anybody with a working script keeps it, and anybody on a
#      platform this file has no built-in for can write twenty lines of
#      anything and be done.
#   2. A subclass of UsageSource added to USAGE_SOURCES, for a source worth
#      shipping.  `auto` walks that tuple in order and takes the first that
#      says it is available.
#   3. --usage-source none, which is not a plug-in but belongs on the list:
#      it is what a test wants, and what a machine with no such app wants.
#
# The reading is a flat dict of at most seven keys, and the same seven the
# plan cache has always carried, so limits_snapshot can weigh one against the
# other and load_limits can read either without knowing which it got:
#
#   session_pct           whole-plan 5-hour utilisation, a number
#   session_resets_at     when that window resets, STAMP_FMT, local
#   weekly_pct            whole-plan 7-day utilisation
#   weekly_opus_pct       the Opus sub-limit, carried but not yet drawn
#   weekly_resets_at      when the 7-day window resets, STAMP_FMT, local
#   as_of                 when the SOURCE took the reading, STAMP_FMT, local.
#                         Not when this program read it: _reading_age spends a
#                         docstring on that distinction and limits_snapshot
#                         picks a source with it.
#   session_reset_source  "app" | "unknown" — provenance of the 5-hour reset,
#                         for a human reading the cache file by hand
# ════════════════════════════════════════════════════════════════════════════

# Seconds a reset time must be ahead of now before it is believed.
#
# Inherited from usage-limits.sh, and earned there: the app used to store the
# 5-hour reset as a copy of its own snapshot timestamp, so the field was
# present, parseable, and meant "now" — which renders as a countdown of zero
# rather than as the blank that says "not known".  The current schema reports
# it properly (measured 2026-09-08: 77 minutes ahead of the reading that
# carried it), so this guard fires on nothing today.  It stays because the
# failure it catches is a stale reading rendered as a live one, which is the
# failure this whole section is careful about, and five minutes of resolution
# is nothing to a five-hour window.
RESET_MIN_AHEAD = 300

APPLE_EPOCH = 978307200         # 2001-01-01 UTC, in Unix seconds.  Every
                                # timestamp in a macOS app's own store is in
                                # this epoch; every one in this program is in
                                # Unix.  Converted at the boundary, once.


def _stamp(t: float) -> str:
    """A Unix epoch as the stamp every channel here carries."""
    return time.strftime(STAMP_FMT, time.localtime(t))


def _as_epoch(v) -> Optional[float]:
    """A carried time back as a Unix epoch, whichever way it was carried.

    Sources differ and are allowed to: the menu-bar app stores Apple-epoch
    floats, Claude Code's payload sends Unix epochs, a hand-written script is
    likeliest to print the stamp it already had.  All three arrive here and
    only one shape leaves.

    An epoch is distinguished from a stamp by being a number, not by its
    magnitude — no threshold, because a threshold is a rule that works until
    the day it does not and then fails silently in the direction of a
    plausible wrong answer.
    """
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            pass
        try:
            return time.mktime(time.strptime(s, STAMP_FMT))
        except (ValueError, OverflowError):
            return None
    return None


def normalise_reading(d: dict, now: Optional[float] = None) -> dict:
    """A source's answer, coerced into the one shape everything downstream reads.

    Every source goes through this, including the built-in one, so there is a
    single place where "what a reading is" is decided and a single place to
    read to find out.

    Three things happen, and the third is the one worth naming:

      * times become STAMP_FMT strings, from epochs or stamps either way;
      * percentages become numbers, or vanish;
      * ANY OTHER KEY IS DROPPED.  Not tidiness: this dict is written to a
        world-readable file under /tmp, and a source is an arbitrary program
        reading an arbitrary store.  The built-in one reads a record that also
        holds an OAuth account blob and an API session key, three keys along
        from the figures it wants.  A pass-through would put whatever a source
        happened to hand back into that file forever; a whitelist puts seven
        fields there and cannot be talked into an eighth.

    A reset time that is not meaningfully in the future is dropped rather than
    carried — see RESET_MIN_AHEAD.  `as_of` is exempt, obviously: it is a
    reading's age, and an age is behind you.
    """
    if not isinstance(d, dict):
        return {}
    now = now if now is not None else (frozen_now() or time.time())
    out = {}                    # type: Dict[str, object]

    for k in ("session_pct", "weekly_pct", "weekly_opus_pct"):
        v = _pct_num(d.get(k))
        if v is not None:
            out[k] = v

    for k in ("session_resets_at", "weekly_resets_at"):
        t = _as_epoch(d.get(k))
        if t is not None and t - now > RESET_MIN_AHEAD:
            out[k] = _stamp(t)

    t = _as_epoch(d.get("as_of"))
    out["as_of"] = _stamp(t if t is not None else now)

    src = d.get("session_reset_source")
    out["session_reset_source"] = (src if src in ("app", "derived", "unknown")
                                   else ("app" if out.get("session_resets_at")
                                         else "unknown"))
    # A reading with neither percentage is not a reading.  Both windows or
    # neither is load_limits' rule about SOURCES; this is the weaker one about
    # a single source having said anything at all, and it exists so that a
    # source which returns a bare timestamp cannot overwrite a good cache with
    # a dict that renders as two empty rows.
    if "session_pct" not in out and "weekly_pct" not in out:
        return {}
    return out


class UsageSource:
    """One place a plan reading can come from.

    Subclass, set `name`, answer `available()` honestly and return whatever
    `read()` can find.  Neither method may raise: a source that cannot answer
    returns {} and the readout draws the row it draws when nobody knows.
    """

    name = "?"

    def available(self) -> bool:
        """Whether this machine has the thing this source reads.

        Cheap, and it is allowed to be approximate — `auto` uses it to pick,
        and a source that says yes and then returns {} costs one render's
        worth of nothing.  What it must not do is be expensive, because it is
        asked before every refresh.
        """
        return True

    def read(self) -> dict:
        """A raw reading, in whatever shape the source has.  {} if none."""
        return {}


class ClaudeUsageTrackerSource(UsageSource):
    """Claude Usage Tracker, the macOS menu-bar app.

        https://github.com/hamed-elfayome/Claude-Usage-Tracker

    It polls Anthropic on its own schedule and keeps the answer in its
    UserDefaults store, which is why this is worth reading at all: no OAuth
    handling here, no network call, no token to keep — the figures are already
    on disk and somebody else's program is responsible for refreshing them.

    Read through `defaults export` rather than by opening the .plist, because
    a running app's preferences live in cfprefsd and reach the file when
    cfprefsd feels like it.  The app writes a reading every 30 seconds and the
    file lagged it by minutes in testing.  One subprocess, and it replaces the
    three the shell wrapper spawned.

    CLAUDE_USAGE_TRACKER_PLIST overrides that with a path to an exported plist
    file.  It is the seam tests/usage-source.sh drives — a fixture store, on
    any platform, with no app installed — and it doubles as the escape hatch
    for reading a store copied off another machine.
    """

    name = "claude-usage-tracker"
    DOMAIN = "HamedElfayome.Claude-Usage"
    PLIST = "~/Library/Preferences/HamedElfayome.Claude-Usage.plist"
    ENV = "CLAUDE_USAGE_TRACKER_PLIST"

    def available(self) -> bool:
        if os.environ.get(self.ENV):
            return True
        # The file is the CHEAP test — `defaults export` on an unknown domain
        # succeeds and prints an empty dict, so asking it costs a process to
        # learn nothing.  The file lags the live store, which makes it a bad
        # source and a perfectly good existence check.
        return (sys.platform == "darwin"
                and os.path.isfile(os.path.expanduser(self.PLIST)))

    def _store(self) -> dict:
        path = os.environ.get(self.ENV)
        if path:
            with open(os.path.expanduser(path), "rb") as fh:
                return plistlib.load(fh)
        p = subprocess.run(["defaults", "export", self.DOMAIN, "-"],
                           capture_output=True, timeout=15)
        return plistlib.loads(p.stdout) if p.stdout else {}

    def read(self) -> dict:
        try:
            return tracker_reading(self._store())
        except Exception:
            return {}


def tracker_reading(store: dict) -> dict:
    """The tracker's UserDefaults, read down to the figures this program uses.

    Separated from the source that fetches the store so it can be tested
    without a Mac, an app, or a subprocess: hand it a dict and read the answer.
    Every part of this that is worth getting wrong is in here.

    WHERE THE FIGURES LIVE.  `profiles_v3` is a JSON array stored as bytes —
    one record per configured account — and each record carries a
    `claudeUsage` object with the current reading in it:

        sessionPercentage       5-hour window, whole plan
        sessionResetTime        Apple epoch
        weeklyPercentage        7-day window
        weeklyResetTime         Apple epoch
        opusWeeklyPercentage    the Opus sub-limit
        lastUpdated             when the app took this reading

    `activeProfileId` at the top level of the store names the record to read;
    `isSelectedForDisplay` is the fallback, and the first record is the
    fallback's fallback, because a store with one account has nothing to
    choose between and should not need to be configured to say so.

    NOTHING ELSE IS TOUCHED, and the reason is two keys along from the one
    that is: the same profile record holds `oauthAccountJSON` and an API
    session key.  This function names the six fields it wants and
    normalise_reading drops anything else that arrives anyway.  A reading is
    written to a file under /tmp; a credential must not be able to get into
    it by accident.

    THE OLD SHAPE IS GONE.  Until 2026-09 the store held `usageHistory_<uuid>`
    — a rolling array of {sessionReset, weeklyReset} snapshots — and the 5-hour
    reset was NOT in it: on a sessionReset snapshot `triggeringResetTime` was
    a copy of the snapshot's own timestamp, so the wrapper script derived the
    window instead, from the most recent 0٪ → non-zero transition in the
    history.  That history now lives in a file
    (~/Library/Application Support/Claude Usage/history/) and the reset is
    published directly and correctly, so the derivation is not ported.  It is
    written down here rather than carried as code because carrying it means
    parsing nine megabytes of JSON on the off-chance, and because the thing it
    worked around is fixed: reviving it is a matter of reading that file, not
    of remembering what it did.
    """
    profs = store.get("profiles_v3")
    if isinstance(profs, (bytes, bytearray)):
        profs = profs.decode("utf-8", "replace")
    if isinstance(profs, str):
        try:
            profs = json.loads(profs)
        except ValueError:
            return {}
    if not isinstance(profs, list) or not profs:
        return {}

    want = store.get("activeProfileId")
    prof = (next((p for p in profs
                  if isinstance(p, dict) and p.get("id") == want), None)
            or next((p for p in profs
                     if isinstance(p, dict) and p.get("isSelectedForDisplay")),
                    None)
            or (profs[0] if isinstance(profs[0], dict) else None))
    if not prof:
        return {}
    u = prof.get("claudeUsage")
    if not isinstance(u, dict):
        return {}

    def unix(v):
        t = _as_epoch(v)
        return None if t is None else t + APPLE_EPOCH

    return {
        "session_pct": u.get("sessionPercentage"),
        "session_resets_at": unix(u.get("sessionResetTime")),
        "weekly_pct": u.get("weeklyPercentage"),
        "weekly_opus_pct": u.get("opusWeeklyPercentage"),
        "weekly_resets_at": unix(u.get("weeklyResetTime")),
        "as_of": unix(u.get("lastUpdated")),
    }


class CommandSource(UsageSource):
    """An external program that prints a reading as JSON on stdout.

    The extension point for everything this file has no built-in for: another
    tracker, another platform, a company's own quota endpoint, or the
    usage-limits.sh somebody already has working.  The contract is the whole
    of the interface — print a JSON object, exit 0 — and normalise_reading
    takes it from there, so epochs or stamps and any subset of the fields are
    all acceptable.

    Run directly if it is executable and through bash if it is not, which is
    the difference between `cmd:~/bin/usage` and `cmd:~/.claude/usage.sh`
    after a checkout has dropped the execute bit.
    """

    name = "command"

    def __init__(self, path: str):
        self.path = os.path.expanduser(path)
        self.name = "cmd:" + path

    def available(self) -> bool:
        return os.path.isfile(self.path)

    def read(self) -> dict:
        try:
            argv = ([self.path] if os.access(self.path, os.X_OK)
                    else ["bash", self.path])
            p = subprocess.run(argv, capture_output=True, text=True,
                               timeout=20)
            if p.returncode != 0 or not p.stdout.strip():
                return {}
            d = json.loads(p.stdout)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}


# The built-in sources, in the order `auto` tries them.  One today; the tuple
# is the registry rather than an if-statement so that adding a second is an
# entry here and a class above, and so that --usage-source can name one
# without this file growing a table of names beside the classes that have
# them.
USAGE_SOURCES = (ClaudeUsageTrackerSource,)

# Which source to use, as a spec string.  Set from --usage-source, defaulting
# to the environment, defaulting to "auto".
#
# Module state, which this file otherwise does not have, for the reason
# set_mark_spacing is: the flag is parsed in main and consumed four calls deep
# inside a cache refresh that has no argv and should not grow one.  Read once
# per process, and a process is one render.
_USAGE_SPEC = os.environ.get("CLAUDE_USAGE_SOURCE", "auto")


def set_usage_source(spec: str) -> None:
    global _USAGE_SPEC
    _USAGE_SPEC = (spec or "auto").strip()


def usage_source(spec: Optional[str] = None) -> Optional[UsageSource]:
    """The source named by a spec, or None for "do not ask anybody".

        auto              first built-in that says it is available (default)
        none | off        no source; the cache file is still read
        <name>            a built-in by name, e.g. claude-usage-tracker
        cmd:PATH          an external program, see CommandSource

    A NAMED source is returned whether or not it is available, deliberately:
    naming one is an instruction, and an instruction that silently degrades to
    a different source is how a readout comes to be quoting something nobody
    chose.  It will return {} and the rows will be blank, which is a question
    with an answer.  `auto` is the mode that is allowed to shrug.
    """
    spec = (spec if spec is not None else _USAGE_SPEC) or "auto"
    spec = spec.strip()
    if spec in ("none", "off", ""):
        return None
    if spec.startswith("cmd:") or spec.startswith("command:"):
        return CommandSource(spec.split(":", 1)[1])
    if spec == "auto":
        for cls in USAGE_SOURCES:
            src = cls()
            if src.available():
                return src
        return None
    for cls in USAGE_SOURCES:
        if cls.name == spec:
            return cls()
    return None


def _read_limit_cache() -> dict:
    """The selected usage source's reading, refreshed at most once per LIMIT_TTL.

    A source costs a subprocess at least — the built-in one runs `defaults
    export`, an external one is a whole program — which is far too slow to pay
    on every keystroke of a status line.  Nor would it buy anything: the app
    polls Anthropic every thirty seconds, so a read per render would return
    the same figures many times over.

    Written via a temp file and os.replace so a concurrent render never reads
    a half-written cache and a failed refresh leaves the previous good copy in
    place.

    NO SOURCE SUPPRESSES THE REFRESH AND NOTHING ELSE.  It used to return {}
    outright when the shell script was missing, which conflated two questions
    — can this machine take a new reading, and is there a reading already on
    disk — and answered the second with the first.  On the machine that had
    the script the two coincided, since the only writer of this file is the
    branch below, so the conflation was invisible; anywhere else it discards a
    perfectly good cache unread.  The golden suite is the "anywhere else": it
    plants this file as a fixture, pins --usage-source to none, and has no
    ~/.claude at all under CI.

    An EMPTY reading is not written.  normalise_reading returns {} for a
    source that answered nothing intelligible, and overwriting a cache with
    that would turn a momentary failure — the app quit, the store locked, a
    schema changed — into a blank readout that outlives it.  The old cache
    ages instead, and _reading_age lets limits_snapshot prefer the other
    channel while it does.
    """
    age = 999999
    try:
        age = time.time() - os.path.getmtime(LIMIT_CACHE)
    except OSError:
        pass
    if age > LIMIT_TTL:
        src = usage_source()
        d = normalise_reading(src.read()) if src else {}
        if d:
            try:
                tmp = "%s.%d" % (LIMIT_CACHE, os.getpid())
                with open(tmp, "w") as fh:
                    json.dump(d, fh)
                os.replace(tmp, LIMIT_CACHE)
            except Exception:
                pass
    try:
        with open(LIMIT_CACHE) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _reading_age(d: dict, path: str) -> float:
    """How many seconds ago a plan snapshot was TAKEN, not written.

    The distinction is the whole point.  Both sources are files on disk, and
    the mtime of either says when a process last copied a reading into it —
    which for a usage source is when LIMIT_TTL last expired, not when the
    source last heard from Claude.  `as_of` is the source's own answer to "how
    old is this reading" — the tracker app takes it from the `lastUpdated`
    beside the figures — and it was being thrown away; the program never
    mentioned the field.  Prefer it, and fall back to mtime only where it is
    absent.

    Against frozen_now where one is pinned, like every other duration on the
    readout.  Freshness IS a duration, and measuring it on a different clock
    from the one the countdowns use makes a golden run depend on the wall
    clock: at minute resolution the two ages crossed over whenever a real
    minute ticked mid-suite, so one case picked the plan cache and the next
    picked the app, from the same two files.

    Clamped at zero because a pinned clock sits in the past while every
    fixture file is written in the present, which would otherwise make every
    age negative and the comparison meaningless.  Ties go to the caller, which
    resolves them in favour of Claude Code's own figures.
    """
    now = frozen_now() or time.time()
    v = d.get("as_of")
    if v:
        try:
            return max(0.0, now
                       - time.mktime(time.strptime(v, STAMP_FMT)))
        except (ValueError, OverflowError):
            pass
    try:
        return max(0.0, now - os.path.getmtime(path))
    except OSError:
        pass
    return float("inf")


_SNAPSHOT = None            # the one plan reading this PROCESS uses; see below


def limits_snapshot(seed: Optional[dict] = None) -> dict:
    """The plan reading every consumer in this process shares.

    ALL OR NOTHING ACROSS THE READOUT, which is the sibling of load_limits'
    all-or-nothing across a pair of rows and was the missing half of it.
    Three consumers used to read the source independently — plan_totals for
    the figure after the "/", _window_starts for the boundary the share is
    summed over, and calibration for the dollars the share is divided by — so
    one render could mix three provenances.  It did: on 2026-08-25 the totals
    came from a three-hour-old app snapshot, the 5-hour boundary came from
    that snapshot's expired reset time (14:40 rather than 19:40, so five
    extra hours of turns were charged to a window that never saw them), and
    the unit came from a fresh reading another session had just cached.  The
    row was internally inconsistent in three directions at once.

    Memoised for the life of the process, which is one render.  Nothing here
    is long-lived: the status line is a process per draw and the Stop hook is
    a process per turn.

    `seed` is how the status line hands in Claude Code's own figures, which
    beat both caches — they are the API's own accounting, arriving with the
    payload rather than through a file.  Everything downstream then divides
    and bounds by the same reading the row above it prints.
    """
    global _SNAPSHOT
    if seed:
        # Truthy, not "is not None": _write_plan_cache returns {} when it had
        # only half a pair to write, and seeding that would block the caches
        # instead of falling back to them.
        _SNAPSHOT = seed
    elif _SNAPSHOT is None:
        plan, app = _read_plan_cache(), _read_limit_cache()
        pa = _reading_age(plan, PLAN_CACHE) if plan else float("inf")
        aa = _reading_age(app, LIMIT_CACHE) if app else float("inf")
        _SNAPSHOT = plan if pa <= aa else app
    return _SNAPSHOT


def _read_plan_cache() -> dict:
    """The plan figures the STATUS line last took from Claude Code's payload.

    Same shape as _read_limit_cache's — session_pct, weekly_pct and the two
    resets_at — so every caller can prefer one over the other by swapping the
    source and changing nothing else.

    No TTL gate here any more.  It used to return {} past PLAN_TTL, which put
    the caller on the menu-bar app UNCONDITIONALLY — on the assumption that
    anything is fresher than an expired cache.  The app is polled on its own
    schedule and can be hours behind, so that assumption is wrong in exactly
    the case the gate fires in.  Observed 2026-08-25: an idle gap longer than
    PLAN_TTL expired this cache, the Stop hook fell through to an app snapshot
    taken three hours earlier, and the cost row printed the PREVIOUS 5-hour
    window's 66٪ under a status row reading 38٪ — while a second session's
    hook, rendering from the live figures, wrote the calibration both of them
    then divided by.

    So the age is reported rather than enforced, and limits_snapshot picks
    whichever source was actually read more recently.  A stale figure quoted
    as current is still the failure this channel exists to avoid; comparing
    two ages is how it is avoided now.
    """
    try:
        with open(PLAN_CACHE) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_plan_cache(spct: str, sreset: str,
                      wpct: str, wreset: str) -> dict:
    """Leave the payload's figures where the cost rows can find them.

    Both windows or neither, matching load_limits' own all-or-nothing rule: a
    half-filled cache would let the cost rows mix the payload's session figure
    with the app's weekly one, which is the exact mixing that rule forbids.

    The reset times are written in the app's local "%Y-%m-%d %H:%M" rather than
    the payload's epoch, so calibration() can parse either source with the one
    strptime it already has.  `as_of` goes in the same format and for the same
    reason: _reading_age reads it out of either source with one strptime, and
    a channel that says how old it is can be compared against one that does
    not have to be believed.

    Returns what it wrote, so the caller can seed limits_snapshot with the
    same dict rather than reading its own write back off the disk.  Empty when
    there was nothing to write, which is a falsy seed and therefore no seed.
    """
    sp, wp = _pct_num(spct), _pct_num(wpct)
    if sp is None or wp is None:
        return {}

    def local(v: str) -> str:
        try:
            return time.strftime(STAMP_FMT, time.localtime(float(v)))
        except (TypeError, ValueError):
            return ""

    d = {"session_pct": sp, "session_resets_at": local(sreset),
         "weekly_pct": wp, "weekly_resets_at": local(wreset),
         "as_of": time.strftime(STAMP_FMT,
                                time.localtime(frozen_now()))}
    try:
        tmp = "%s.%d" % (PLAN_CACHE, os.getpid())
        with open(tmp, "w") as fh:
            json.dump(d, fh)
        os.replace(tmp, PLAN_CACHE)
    except OSError:
        pass
    return d


def load_limits(pay: Payload) -> Limits:
    """The two plan windows, from the payload if it has them and the menu-bar
    app if it does not.

    ALL OR NOTHING, deliberately.  If the payload supplies either figure, both
    rows come from the payload and the app is not consulted — even for a row
    the payload left empty.  Claude Code's figures are the ones to trust:
    resets_at is the anthropic-ratelimit-unified-*-reset response header as a
    Unix epoch and used_percentage the matching utilisation, both straight from
    the API that enforces the limit.  The app reads a snapshot it polls on its
    own schedule, so its reset time can be minutes stale and its clock is local
    where the payload's is absolute.

    Mixing the two inside one pair of rows would put figures minutes apart
    beside each other with nothing on the row to say why.  A blank row states
    its ignorance; a mixed pair hides it.
    """
    if pay.rl_session_pct or pay.rl_weekly_pct:
        sp = _pct_str(_pct_num(pay.rl_session_pct))
        wp = _pct_str(_pct_num(pay.rl_weekly_pct))
        # Hand them on to the cost rows, which have no payload of their own —
        # the Stop hook is given a transcript path and little else.  Without
        # this they fall back to the app and the two readouts disagree on
        # screen, which is the failure plan_totals' docstring says it exists
        # to prevent: 43٪ on the cost row under 56٪ on the status row.
        # And seed the snapshot with the same dict, so the boundary the
        # session share is summed over and the unit it is divided by come
        # from these figures too rather than from a file written by whoever
        # rendered last.  See limits_snapshot.
        limits_snapshot(seed=_write_plan_cache(
            sp, pay.rl_session_reset, wp, pay.rl_weekly_reset))
        return Limits(sp, pay.rl_session_reset, "",
                      wp, pay.rl_weekly_reset, "")
    # No rate_limits on this payload.  The fallback is no longer the app
    # unconditionally: limits_snapshot weighs it against the plan cache, which
    # another session's payload may have written seconds ago and which is the
    # better source whenever it is the fresher one.
    d = limits_snapshot()
    if not d:
        return NO_LIMITS
    return Limits(
        # The app rounds to whole points before it ever stores a snapshot, so
        # this source can only ever offer "0" below 1٪.  It still goes through
        # the same pair, so the two sources reach the renderer in one form.
        _pct_str(_pct_num(d.get("session_pct"))),
        _num(d.get("session_resets_at")) if d.get("session_resets_at") else "",
        "",
        _pct_str(_pct_num(d.get("weekly_pct"))),
        _num(d.get("weekly_resets_at")) if d.get("weekly_resets_at") else "",
        "",
    )


def _ctxwin_path(session_id: str) -> str:
    return os.path.join(os.environ.get("TMPDIR", "/tmp"),
                        "claude-statusline-ctxwin-%s" % session_id)


def publish_ctx_window(session_id: str, win: int) -> None:
    """Leave the status line's window reading where the Stop hook can find it.

    The two readouts do not get the same facts.  The status-line payload
    carries context_window.context_window_size and a display name that says
    "(1M context)"; the Stop payload carries neither, and the transcript
    records the model as plain "claude-opus-5" for both variants.  So the one
    that knows writes it down for the one that cannot — the same shape as the
    plan cache, and for the same reason.

    Keyed by SESSION id, which is what makes it safe to leave in TMPDIR with
    no isolation: a test fixture's synthetic id can never be read by a live
    session, so unlike the plan cache this store cannot leak into the real
    readout.  It also means a machine running two sessions on two models
    keeps two answers rather than one racing pair.

    Re-read before writing so an unchanged value costs no write.  This runs on
    every status render, which is to say constantly.
    """
    if not session_id or win <= 0:
        return
    p = _ctxwin_path(session_id)
    try:
        with open(p) as fh:
            if fh.read().strip() == str(win):
                return
    except OSError:
        pass
    try:
        tmp = "%s.%d" % (p, os.getpid())
        with open(tmp, "w") as fh:
            fh.write("%d\n" % win)
        os.replace(tmp, p)
    except OSError:
        pass


def stored_ctx_window(session_id: str) -> int:
    """What the status line last published for this session, or 0."""
    if not session_id:
        return 0
    try:
        with open(_ctxwin_path(session_id)) as fh:
            v = int(fh.read().strip())
        return v if v > 0 else 0
    except (OSError, ValueError):
        return 0


def _with_shares(lim: Limits, transcript: str) -> Tuple[Limits, float]:
    """Attach how much of each window this session, and its last turn, used.

    Returns the turn's wall-clock seconds alongside, because ⌛'s new 🎤
    field needs exactly the turn this picked and reading the transcript a
    second time to find it again would be both slower and free to disagree.

    The same derivation the cost line's totals row uses — session_shares over
    this transcript's turns, bounded by the window and divided by
    calibration's dollars-per-point — so the two readouts now report one
    quantity rather than two things with one name.

    WHAT THIS REPLACES, because the old figure looked plausible for months.
    There was no transcript here at all: the share was the plan-wide reading
    now minus the plan-wide reading this session first saw, stored per session
    id under TMPDIR.  A subtraction of two plan-wide readings contains every
    other session's consumption over the interval as well as this one's, and
    the baseline only ever moved DOWN — it was rewritten whenever the reading
    fell, on the correct theory that a fall means the window rolled over.

    Which makes it worthless the moment a session outlives a window, and the
    5-hour window rolls over every five hours.  At the rollover the reading
    goes to zero, the baseline follows it to zero, and nothing raises it
    again, so from then on `now - 0` IS the plan-wide total: both halves of
    the cell print the same number, and a session that has ever crossed a
    reset never reports a share again.  Measured 2026-08-25 on a four-day-old
    session: the status row said `62٪ / 62٪` and `6٪ / 6٪` while the cost row,
    counting the same session's own turns, said 16.2٪ and 1.57٪.  The 4.4
    weekly points between them were other sessions, charged here.

    What the subtraction alone could see and this cannot is usage from another
    machine — a phone, the web app — because the scan reads transcripts. That
    made it a true ceiling.  A ceiling that sits at 100٪ of the window for the
    rest of the session is not worth the column.

    Left as "" when there is no transcript to sum or no calibration to divide
    by, which render_limit draws as "?" rather than as a zero.

    BOUNDED BY THE WINDOW, both figures.  The 🎤 cell was `turn_cost(last)`
    over the unit, with no boundary on it at all, while 🎮 beside it was
    bounded — so a turn that straddled a reset was charged in full to a cell
    whose two neighbours had already dropped it, and column 4 printed
    `🎤 18٪  🎮 0٪  💳 1٪`: a part larger than the whole it belongs to, twice
    over.  Both now go through the split; see turn_cost_since.  What the
    reader gets is the one thing the column claims — turn ≤ session ≤ account
    — as an identity rather than as a coincidence that holds while no window
    happens to reset mid-answer.

    WHICH TURN the 🎤 figure is about is not turns[-1].  It is the last turn
    that made calls and was not a compaction — `prompts[-1]`, character for
    character the selection render_cost_line makes — so the 🎤 on this row and
    the 🎤 row of the cost line under it always describe the same turn.  Take
    turns[-1] instead and the two disagree whenever the last thing that
    happened was a compaction or a batch drained without billing.
    """
    if not transcript or not os.path.isfile(transcript):
        return lim, 0.0
    if not lim.session_pct and not lim.weekly_pct:
        return lim, 0.0
    try:
        turns = read_turns(transcript)
        calib = calibration()
        sh = session_shares(turns, calib)
        prompts = [t for t in turns if t.calls and not t.compact]
        last = prompts[-1] if prompts else None
        tn = {"sess": None, "week": None}
        if last is not None:
            tn = window_shares(last, calib)
    except Exception:
        return lim, 0.0
    return (lim._replace(session_share=_pct_str(sh["sess"]),
                         weekly_share=_pct_str(sh["week"]),
                         session_turn=_pct_str(tn["sess"]),
                         weekly_turn=_pct_str(tn["week"])),
            last.dur_s if last is not None else 0.0)


# ════════════════════════════════════════════════════════════════════════════
# Status-line segment renderers.
#
# One per metric.  Each takes its values as ARGUMENTS — never reads them from
# module scope — pads its own value to a fixed width, and knows nothing about
# where on the row it will land.  That is the layout's business, below.
#
# This is the one structural change the port exists to make.  In the bash these
# read globals, so their inputs were invisible in their signatures and the
# function that set those globals grew every time a renderer wanted something.
# ════════════════════════════════════════════════════════════════════════════

def render_tokens(up: Optional[int], down: int) -> str:
    """The ▴/▾ billable-equivalent token totals.

    Each figure gets four columns of its own — three characters and a unit, the
    widest humanize can produce — with the arrow fixed ahead of it.  Padding
    "▴13M" as one string would right-align the mark along with the number, so
    a short figure would carry its arrow inward and the two would stop stacking
    with each other and with the context row below.
    """
    if up is None:
        return ""
    return "%s%s%s%s%s%s" % (
        S_TOK, F_TUP, pad_val(VAL_W, E_UP + pad_val(4, humanize(up)), True),
        F_TDN, pad_val(VAL2_W, E_DOWN + pad_val(4, humanize(down))), R)


def render_cache(cache_pct: int) -> str:
    """The prompt-cache hit rate.  Nothing when there was no usage at all."""
    if cache_pct is None or cache_pct < 0:
        return ""
    return "%s%s%s%s" % (S_CACHE, cache_color(cache_pct),
                         pad_val(4, pct2(cache_pct) + E_PCT), R)


def render_ctx(ctx_pct: Optional[int], ctx_tokens: int) -> str:
    """Live context occupancy, as a percentage and then a size.

    The window itself is deliberately not printed: it is constant for the
    session, so of the three possible numbers it is the one that never says
    anything twice — and 🤖 already carries it.

    Percentage first, size second, and the prompt-cost row was turned round to
    match on the same day.  The two readouts describe the same window — this
    one as a level, that one as the change in it over a turn — so a reader
    moving between them should not have to work out which field is which each
    time; that argument survives the reversal intact, because what it asks for
    is one order, not a particular one.  Neil's call on which.

    What the reversal costs is the tokens sitting under 🧩's tokens directly
    above, figure under figure.  What it buys is the percentage in the leading
    field, which is the figure this row is read for: how full the window is.
    The size is the qualifier, and qualifiers go second here.

    One colour across both fields, and it is the percentage's.  The other two
    metrics in this column pair a light value with a dark one because their two
    figures are different quantities — tokens up against tokens down, a model
    against its window.  These two are one quantity said twice, so dimming
    either half would rank a figure against itself.

    Always pink rather than tiered, so an approaching window limit reads off
    the number rather than the colour.  It also drops the 99 clamp the other
    percentages keep, which matters here and nowhere else: a context at 99٪ and
    one at 100٪ are different situations, where a plan limit at either is the
    same news.
    """
    if ctx_pct is None:
        return ""
    return "%s%s%s%s%s" % (
        S_CTX, F_PNK, pad_val(VAL_W, "%d%s" % (ctx_pct, E_PCT)),
        pad_val(VAL2_W, humanize(ctx_tokens)), R)


def render_cost(cost_usd: str) -> str:
    """The session cost.  Always yellow — no value tiering."""
    if not cost_usd or cost_usd == "null":
        return ""
    try:
        c = float(cost_usd)
    except ValueError:
        return ""
    return "%s%s%s%s" % (S_COST, F_YEL, pad_val(4, money_fmt(c)), R)


def render_limit(emoji: str, pct_s: str, delta: str, resets: str,
                 turn: str = "", colour: str = F_LIM_SESS,
                 dim_total: bool = False,
                 now: Optional[float] = None) -> str:
    """One plan-limit segment: three widening scopes, then a countdown.

    The percentages come in widening order: 🎤 what the turn just answered
    cost, 🎮 what this session has cost, 💳 what the account has consumed.
    Narrowest first, because that is the one a reader can still do something
    about; widest last, because it is what it is whichever session you look
    from.  Then the countdown, which is the same question as ⌛ directly
    below it — how long until this changes — and shares RST_W with it so the
    two line up in the column.

    The countdown led until 2026-08-28, on that shared question.  It still
    shares it, and the durations still stack, but leading put a reading of a
    different kind in front of a sequence that is only worth arranging
    because it is a sequence: the three scopes now start at the column's edge
    and the horizon they are measured against closes it.  See the
    column-4 note above RIGHT_GRID.

    The 🎤 figure is the same quantity the cost line's 🎤 row prints, off
    the same derivation and — see _with_shares — the same turn.  Before it
    the status line could say a session had spent 1.2٪ of a window without
    saying whether that was one expensive turn or forty cheap ones.

    A separator was tried and dropped.  Two figures divided by " / " read as
    "mine out of everyone's"; three do not divide that way, and once each
    figure carries a mark the slashes are six columns spent repeating what
    the marks already say.

    Every field is fixed width and each may be absent without moving the ones
    after it: either share needs a transcript to sum and a calibration to
    divide by, and the rolling 5-hour window has no persisted reset time to
    count down to.

    The countdown's marker is fixed and only its figure moves.  Padding
    "🔜 31m" as one string would right-align the marker too, so a
    three-character duration would put 🔜 a column right of where a
    four-character one puts it and the two limit rows would stop lining up.
    The three scope marks are fixed for the same reason, one row further.

    ONE COLOUR PER ROW, and brightness carries everything else.  `colour` is
    the row's identity — F_LIM_SESS for 🔋, F_LIM_WEEK for 🪫 — and it does
    not move with any figure on the row.  What varies is emphasis: the two
    scopes this session owns stay bright, the account total dims where it is
    context rather than news, and the countdown dims unless it is inside the
    hour.  Hue therefore answers "which window is this?" and nothing else,
    which is the one question it can answer from across a screen.

    It tiered green/amber/red on the account figure until 2026-08-28, through
    limit_color.  Three hues, none of them the row's own, moving on a
    quantity that already sits in plain digits two fields to the left; and
    the 🪫 row was pinned red regardless, so the same colour meant "weekly"
    on one row and "over 90٪" on the other.  See F_LIM_SESS.
    """
    if not pct_s:
        return ""
    pct_v = _pct_num(pct_s)
    if pct_v is None:
        return ""
    d = short_dur(resets, now)
    if d:
        # Blank rather than absent when there is no reset time to count down
        # to.  The field is the last one now, so its blank falls at the
        # column's right edge and reads as slack; it is not.  Holding it keeps
        # the account figure of a row without a countdown under the account
        # figure of one with it, which is the whole reason the field is fixed.
        # Shaped like fig() below: the mark stands outside the colour and
        # only the figure is painted.  It used to wrap both, which was
        # harmless while the wrapper was a plain foreground — 🔜 paints
        # itself and ignores one — and would not be now, because DIM reaches
        # a pictograph where a foreground colour does not, and would have
        # dimmed the mark on every countdown an hour or more out.
        rst = "%s%s%s%s%s%s" % (S_RESET, MARK_SP, reset_dim(d), colour,
                                pad_val(RST_W - vis_width(S_RESET), d), R)
    else:
        rst = " " * (RST_W + len(MARK_SP))

    def fig(mark: str, v: Optional[float], col: str,
            w: int = LIM_FIG_W, digits: int = 3) -> str:
        # No transcript to sum or no calibration to divide by: say so rather
        # than showing a zero, which would read as "this consumed nothing".
        # See _with_shares.
        if v is None:
            return "%s%s%s%s%s" % (mark, MARK_SP, DIM + F_CRM,
                                   pad_val(w, "?"), R)
        # 100 is drawn, not spelled.  See E_HUNDRED.  E_PCT follows it just
        # as it follows a spelled figure below, so the column reads as one
        # scale all the way down; the glyph is two columns in a field of at
        # least three, so the unit lands in padding that was already blank.
        # The colour wrapper stays because DIM still reaches a pictograph even
        # where the foreground colour does not.
        # The threshold is limit_pct's own, not a round 100: it renders
        # 99.6 as "100", and in LIM_ACCT_W that is one column more than the
        # field holds.  One test, so the glyph and the string can never
        # disagree about where the window ends.
        if v >= 99.5:
            return "%s%s%s%s%s" % (mark, MARK_SP, col,
                                   pad_val(w, E_HUNDRED + E_PCT), R)
        return "%s%s%s%s%s" % (mark, MARK_SP, col,
                               pad_val(w, limit_pct(v, digits) + E_PCT), R)

    # The 5-hour row dims its account figure, leaving the two this session
    # owns at full strength: those are what a reader can act on and the
    # account total is context for them.  The weekly row keeps all three
    # bright, because by then the total IS the news.
    tcol = DIM + colour if dim_total else colour
    return "%s%s" % (emoji, " ".join((
        fig(E_TURN, _pct_num(turn) if turn else None, colour),
        fig(E_SESSION, _pct_num(delta) if delta else None, colour),
        fig(E_ACCT, pct_v, tcol, LIM_ACCT_W, 2),
        rst)))


def render_diff(added: str, removed: str) -> str:
    """The +adds/-removes segment, in eleven columns after its emoji.

    One for the space that divides the halves, two for the signs, and four for
    each figure, so a four-digit diff reads "3.4k" rather than overflowing.
    Neil's budget, and it is the same shape the cost row's signed() uses: the
    sign gets a column of its own so it never drifts with the width of the
    number behind it, and the figures right-align under each other.

    The one place humanize's trailing unit column is thrown away.  Everywhere
    else it is load-bearing — it stacks mantissa under mantissa and unit under
    unit down a grid — but nothing sits above or below this cell to stack
    with, so under a thousand the blank only holds the last digit one column
    short of the right edge, which is what it looks like: a cell that misses
    the margin by one.

    A space divides them rather than the "/" this carried before.  The signs
    already say which half is which, so the slash was a column spent repeating
    them — and the column buys the fourth digit that lets 3443 stay legible.

    Renders even at zero, unlike the other optional segments: nothing shares
    its cell, and "+0 -0" is a fact worth stating — this session has changed
    nothing yet.
    """
    if not added:
        return ""

    def n(v: str) -> str:
        try:
            # rstrip drops humanize's unit column; see the note above for why
            # this cell is the exception.  "3.4k" is unaffected — it has no
            # trailing blank to lose — so only the sub-1000 case moves, and it
            # moves one column right, onto the margin.
            return humanize(int(float(v))).rstrip()
        except (TypeError, ValueError):
            return "?"

    return "%s%s+%s%s %s-%s%s" % (
        S_DIFF, F_GRN, pad_val(4, n(added)), R,
        F_RED, pad_val(4, n(removed)), R)


def render_pr(pr: str) -> str:
    if not pr or pr == "null":
        return ""
    return "%s%s%s%s" % (S_PR, F_CYN, pad_val(4, pr), R)


def render_model(model: str, ctx_window: int) -> str:
    if not model:
        return ""
    return "%s%s%s%s%s%s" % (
        S_MOD, F_PUR, pad_val(VAL_W, short_model(model), True),
        F_PUR2, pad_val(VAL2_W, E_WIN + humanize(ctx_window)), R)


def render_effort(effort: str) -> str:
    """⚡, then a glyph for the level, then the level itself — "⚡🏃hi".

    Three cues, each doing a different job.  ⚡ is fixed, so the segment is
    found by icon like every other one on the row.  The level glyph is read
    without reading, as a picture of pace.  The word removes any doubt about
    which of five it is — the distinction that matters most, between "medium"
    and "max", is the one an abbreviation blurs worst.

    Colour climbs alongside, tiering by intensity rather than by health:
    nothing here is unhealthy, it just runs hotter and costs more.
    """
    if not effort or effort == "null":
        return ""
    table = {
        "low": (E_EFF_LOW, "lo", DIM + F_CRM),
        "medium": (E_EFF_MED, "md", F_CRM),
        "high": (E_EFF_HIGH, "hi", F_CYN),
        "xhigh": (E_EFF_XHIGH, "xh", F_AMB),
        "max": (E_EFF_MAX, "mx", F_RED),
    }
    glyph, label, colour = table.get(
        effort, (E_EFF_MED, effort[:2], F_CRM))
    return "%s%s%s%s%s" % (S_EFF, glyph, colour, pad_val(2, label), R)


def render_style(style: str) -> str:
    """The output style, when it is not the default one."""
    if not style or style in ("default", "null"):
        return ""
    return "%s%s%s%s" % (S_STY, F_CYN, style[:W_STY - 2], R)


def render_time(now: Optional[float] = None) -> str:
    """The wall clock, right-aligned on column 5's edge.

    Eleven columns for eight characters of clock.  Ten would hold the date
    above it and stop there; the eleventh is column 5's, which the diff two
    rows down needs for its own icon's space, and taking it here is what keeps
    all three of the column's right edges on one line.  Padding the clock
    rather than trimming the date is the only way round it that keeps both
    figures whole.
    """
    t = time.localtime(now) if now is not None else time.localtime()
    return "%s%s%s%s" % (S_TIME, F_CRM,
                         pad_val(11, time.strftime("%H:%M:%S", t)), R)


def render_date(now: Optional[float] = None) -> str:
    """Today, above the clock it belongs to.

    A status line that has been open across a date boundary — and at 18h and
    counting, this one routinely has — cannot say when "17:14" was.  The date
    is the cheapest possible answer and it changes once a day.

    Eleven columns for ten characters of date, so the one column column 5
    holds over it falls to the LEFT of the figure and the stamp keeps the
    column's right edge — see render_time.
    """
    t = time.localtime(now) if now is not None else time.localtime()
    return "%s%s%s%s" % (S_DATE, F_CRM,
                         pad_val(11, time.strftime("%Y-%m-%d", t)), R)


def render_elapsed(busy_s: float, start_s: float, turn_s: float = 0.0,
                   now: Optional[float] = None) -> str:
    """The session's clock, in the four fields the rows above it use.

    Three scope fields, then the whole.  🎤 is scoped: how long the turn those
    rows are reporting the cost of actually took, which is the one figure that
    lets "🎤 .82٪" be read as expensive or merely long.  👤 and 🤖 are
    positional — they split the age that Σ states, and there is no
    account-wide time to put under 💳.  Σ closes the row in the column 🔜
    takes on the two rows above — the same kind of mark, one that says what
    the figure after it measures rather than naming a metric.

    That split stays exhaustive and stays worth its columns: 👤 is the part
    spent waiting for someone to type, 🤖 the part spent answering, and they
    sum to Σ.  "1.9h of work inside 19h" is a fact about how a day went that
    neither figure states alone.

    THE THREE SCOPE FIGURES SPEND TWO DIGITS, Σ SPENDS THREE.  dur_fmt's
    digits=2 forbids the decimal outright, so 1.9h renders "2h" and 5.5d
    renders "6d" — a real loss of precision below ten, and the reason the
    argument is passed explicitly rather than inferred.  It is paid for
    twice over.  The field it buys is LIM_FIG_W, shared with the two limit
    rows above, and those cannot go below four columns because a percentage
    spends three characters and a ٪; two digits and a unit fit that field
    with the unit landing under the ٪, which is the whole point of the
    column.  And these three are context for the figures above them — "was
    that turn long?", "how much of the day was waiting?" — questions a
    rounded answer settles.

    Σ keeps three digits because the last field is one column wider than a
    scope field and can hold them, and because the session's own age is the one
    duration on the row that gets read as a fact in its own right rather than
    as scale for something else.  Its mark is padded to two columns by S_SUM
    so it stacks on the 🔜 above it, and painted F_SUM — the grey that emoji
    paints itself — rather than the row's own colour, so the mark recedes and
    the figure carries the row, which is what the two rows above already do.

    An absent turn blanks its whole field, mark included, rather than drawing
    a "0s" that reads as a turn which took no time.  👤 and 🤖 do draw their
    zeros, because for those a zero IS the measurement.
    """
    if not start_s:
        return ""
    t = time.time() if now is None else now
    age = t - start_s if t > start_s else 0.0
    idle = age - busy_s if age > busy_s else 0.0

    def fig(mark: str, v: float, w: int = LIM_FIG_W) -> str:
        return "%s%s%s%s%s" % (mark, MARK_SP, F_PRW, pad_val(w, dur_fmt(v, 2)),
                               R)

    turn = (fig(E_TURN, turn_s) if turn_s
            else " " * (vis_width(E_TURN) + len(MARK_SP) + LIM_FIG_W))
    return "%s%s %s %s %s%s%s%s%s%s%s" % (
        S_IDLE, turn, fig(E_WAIT, idle), fig(E_WORK, busy_s, LIM_ACCT_W),
        F_SUM, S_SUM, R, MARK_SP,
        F_PRW, pad_val(RST_W - vis_width(S_SUM), dur_fmt(age)), R)


# ════════════════════════════════════════════════════════════════════════════
# Status-line layout.
# ════════════════════════════════════════════════════════════════════════════

def allocate_left(budget: int, nat_branch: int, nat_proj: int,
                  nat_path: int) -> Tuple[int, int, int]:
    """Split `budget` columns between branch, project and path — in that order
    of priority — by weighted max-min fair sharing.

    Each round offers every still-unsatisfied field its weighted share of what
    is left, and any field whose natural length fits inside its share takes
    only what it needs and hands the remainder back.  So a one-word branch
    subsidises a deep path instead of sitting on columns it cannot use, and
    only genuinely contended budget gets split by weight.  Three fields
    converge in at most three rounds.

    The minimums are applied afterwards, taking from the LOWEST-priority field
    that is still above its own — a field is never cut to nothing merely
    because two longer ones outweighed it.  Both the recipient order (branch,
    project, path) and the donor scan order (path, project, branch) are
    significant; reversing either changes the output under contention.
    """
    nat = [nat_branch, nat_proj, nat_path]
    wt = [LWT_BRANCH, LWT_PROJ, LWT_PATH]
    mn = [LMIN_BRANCH, LMIN_PROJ, LMIN_PATH]
    got = [0, 0, 0]
    pool = budget
    still = [0, 1, 2]

    for _ in range(3):
        sumw = sum(wt[i] for i in still)
        if sumw <= 0:
            break
        settled = False
        nxt = []
        for i in still:
            share = pool * wt[i] // sumw
            if nat[i] <= share:
                got[i] = nat[i]
                pool -= nat[i]
                settled = True
            else:
                nxt.append(i)
        still = nxt
        if not still:
            break
        if not settled:
            # Everyone left wants more than its share: split what remains by
            # weight and give the rounding remainder to the highest-priority
            # claimant.
            sumw = sum(wt[i] for i in still)
            spent = 0
            for i in still:
                got[i] = pool * wt[i] // sumw
                spent += got[i]
            got[still[0]] += pool - spent
            break

    for i in (0, 1, 2):
        need = min(mn[i], nat[i])
        while got[i] < need:
            donor = -1
            for j in (2, 1, 0):
                if j != i and got[j] > mn[j]:
                    donor = j
                    break
            if donor < 0:
                break
            got[i] += 1
            got[donor] -= 1
    return got[0], got[1], got[2]


def render_where_group(proj: str, path: str, branch: str, git: Git) -> str:
    """The project / pwd / branch group — the flush-left half of line 3.

    All three names arrive PRE-FITTED rather than being read from state,
    because the caller has to size them against whatever the right half leaves
    and therefore calls this twice: once with all three empty, to measure the
    fixed chrome (emoji, separators, the gap before the branch, the dirty
    marker), and once with the fitted names.

    Whether the branch segment exists at all is a property of the SESSION —
    git.branch — not of the text passed in, which is empty on the measuring
    call.  Keying it off the session is what makes that call return the true
    chrome width.
    """
    out = ["%s%s%s%s" % (E_PROJ, F_BLU, proj, R),
           "%s%s%s%s%s" % (" " * LEFT_GAP, E_DIR, F_BLU2, path, R)]
    if git.branch:
        out.append(" " * LEFT_GAP)
        if git.dirty:
            out.append("%s%s%s %s%s" % (E_GIT_BAD, F_AMB, branch, E_DIRTY, R))
        else:
            out.append("%s%s%s%s" % (E_GIT_OK, F_GRN, branch, R))
    return "".join(out)


def chat_row(prefix: str, text: str, placeholder: str, fg: str, tail: str,
             cols: Optional[int]) -> str:
    """One chat row: truncated text on a dark background, with a tail riding
    the right edge.

    The tail is the metrics group parked there, so the text is capped short of
    it as well as at MAX_ROW — a long prompt must not run into the segments.

    When the width is unknown the cap stays at MAX_ROW and the tail is still
    appended with only MIN_GAP before it.  That is inherited behaviour, and
    deliberately kept: the alternative is dropping the tail entirely, which
    loses two thirds of the readout in exactly the sessions (`claude -p`,
    cloud) where there is least else to look at.
    """
    body = text
    dim = ""
    if not body:
        body, dim = placeholder, DIM
    cap = MAX_ROW
    tail_w = 0
    if tail and cols:
        tail_w = vis_width(strip_ansi(tail))
        # Everything the row owes: the margin, the table, the gap before it and
        # the prefix.  Whatever is left is the text's, and MAX_ROW does not
        # apply — that is the cap for when there is no width to measure
        # against, and holding to it here would stop the text well short of the
        # table.
        cap = cols - RIGHT_MARGIN - tail_w - MIN_GAP - vis_width(prefix)
    if cap < 1:
        cap = 1
    body = fit_cols(body, cap)

    out = ["%s%s%s%s%s%s" % (LINE_CLEAR, fg, prefix, B_DRK + dim + fg, body, R)]
    if tail:
        # tail_w is deliberately left at 0 when the width is unknown, matching
        # the arithmetic this was ported from: the pad goes negative either
        # way and clamps to MIN_GAP, so the result is identical.  Kept as the
        # port left it — the reasoning is checkable by reading it, which is
        # just as well, since the test that used to check it is retired.
        pad = (cols or 0) - RIGHT_MARGIN - tail_w - vis_width(prefix + body)
        if pad < MIN_GAP:
            pad = MIN_GAP
        out.append(" " * pad + tail)
    out.append(EOL_CLEAR)
    return "".join(out)


def render_chat_rows(tr: Transcript, tail1: str, tail2: str,
                     cols: Optional[int]) -> Tuple[str, str]:
    """Lines 1 and 2, swapping order when the model is thinking.

    ISO-8601 timestamps sort lexicographically the same as chronologically, and
    an empty one sorts lowest — which is what we want for a fresh session: no
    assistant reply yet puts the bot row on top with a dim placeholder.

    The tails belong to display POSITIONS, not to speakers.  The rows swap; the
    tails stay put, so the eye keeps finding each group where it left it.
    """
    if tr.user_ts > tr.asst_ts:
        return (chat_row(S_BOT, tr.asst_text, "(no reply yet)", F_CHAT_B,
                         tail1, cols),
                chat_row(S_HUMAN, tr.user_text, "(no prompt yet)", F_CHAT_U,
                         tail2, cols))
    return (chat_row(S_HUMAN, tr.user_text, "(no prompt yet)", F_CHAT_U,
                     tail1, cols),
            chat_row(S_BOT, tr.asst_text, "(no reply yet)", F_CHAT_B,
                     tail2, cols))


def render_status(pay: Payload, tr: Transcript, git: Git, lim: Limits,
                  cols: Optional[int], now: Optional[float] = None,
                  turn_s: float = 0.0, rules: bool = True) -> str:
    """The whole three-row readout, as one string ending in a newline.

    Line 3 reads as two halves.  Flush left: where the work is happening.
    Flush right, in the order they were already in: what has changed, how the
    session is configured, what it is consuming, and the clock.

    Every right-hand segment is wrapped at a reserved width, so the group's
    total width is a constant: it does not depend on whether this session has a
    PR, a dirty tree or a usage app to read, nor on how large its numbers have
    grown.  Right-align a constant-width group and each metric occupies the
    same column in EVERY session — which is the point, since the eye learns
    where 🧠 lives and switching tabs should not move it.
    """
    ctx_window = ctx_window_for(pay.ctx_window, pay.model + pay.model_id)
    publish_ctx_window(pay.session_id, ctx_window)
    ctx_pct = None
    if tr.ctx_tokens > 0 and ctx_window > 0:
        ctx_pct = int(tr.ctx_tokens * 100 / ctx_window)

    # One decision for all three rows.  See rules_on for why the width is read
    # here and not inside grid_row.
    #
    # `rules` is the ASK and rules_on is the ROOM, and they are separate on
    # purpose: asking for the rules never overrides a width that cannot hold
    # them, so --column-rules on a 90-column terminal is a request that is
    # simply not granted rather than a row that overruns.  The veto only runs
    # one way.
    rule = rules and rules_on(cols)

    usage = grid_row((
        render_style(pay.output_style),
        render_tokens(tr.tok_up, tr.tok_down),
        render_cache(tr.cache_pct),
        render_limit(S_SESS, lim.session_pct, lim.session_share,
                     lim.session_reset, lim.session_turn, F_LIM_SESS, True,
                     now),
        render_date(now),
    ), rule=rule)
    limits_row = grid_row((
        render_pr(pay.pr_number),
        render_ctx(ctx_pct, tr.ctx_tokens),
        render_cost(pay.cost_usd),
        render_limit(S_WEEK, lim.weekly_pct, lim.weekly_share,
                     lim.weekly_reset, lim.weekly_turn, F_LIM_WEEK, False,
                     now),
        render_time(now),
    ), rule=rule)
    right = grid_row((
        "",
        render_model(pay.model, ctx_window),
        render_effort(pay.effort),
        render_elapsed(tr.busy_s, tr.start_s, turn_s, now),
        render_diff(pay.lines_added, pay.lines_removed),
    ), rule=rule)

    row1, row2 = render_chat_rows(tr, usage, limits_row, cols)

    pwd_display = pay.current_dir
    home = os.path.expanduser("~")
    if pwd_display == home:
        pwd_display = "~"
    elif pwd_display.startswith(home + "/"):
        pwd_display = "~" + pwd_display[len(home):]
    proj_display = project_name(git, pay.project_dir)
    branch_display = git.branch

    right_w = vis_width(strip_ansi(right))
    if cols:
        # What the three left-hand names have to share: the row, less the
        # margin, less the constant-width right group, less the gap between the
        # halves, less the left group's own chrome.  That last figure comes
        # from rendering the group with all three names empty, so the emoji,
        # the separators and the dirty marker are measured rather than
        # estimated — and it stays correct if the punctuation ever changes.
        chrome_w = vis_width(strip_ansi(render_where_group("", "", "", git)))
        budget = cols - RIGHT_MARGIN - right_w - MIN_GAP - chrome_w
        if budget < LMIN_PROJ + LMIN_PATH:
            cols = None                # too narrow to lay out at all
        else:
            a_branch, a_proj, a_path = allocate_left(
                budget, len(branch_display), len(proj_display),
                len(pwd_display))
            branch_display = fit_head(branch_display, a_branch)
            proj_display = fit_head(proj_display, a_proj)
            pwd_display = fit_path(pwd_display, a_path)

    if cols:
        left = render_where_group(proj_display, pwd_display, branch_display,
                                  git)
        pad = cols - RIGHT_MARGIN - right_w - vis_width(strip_ansi(left))
        if pad < MIN_GAP:
            pad = MIN_GAP
        line3 = left + " " * pad + right
    else:
        # No usable width, or too little of it to divide: fall back to the
        # left-flowing row, with only the path trimmed and only by estimate.
        line3 = render_where_group(
            proj_display, fit_path(pwd_display, PWD_MAX_FALLBACK),
            branch_display, git) + " " * MIN_GAP + right

    return "%s\n%s\n%s%s%s\n" % (row1, row2, LINE_CLEAR, line3, EOL_CLEAR)


# ════════════════════════════════════════════════════════════════════════════
# Cost line.
#
# The per-prompt analogue of line 3, emitted once per turn by the Stop hook.
# Same glyphs, same gaps, same humanize, same billing weights, same cache
# tiering.  The session-cumulative segments are re-scoped to the last prompt,
# and 🧠 is re-scoped further: the status line reads context as a level, this
# reads it as the CHANGE in that level over one turn, which a cumulative row
# cannot show.
# ════════════════════════════════════════════════════════════════════════════

class CostOpts(NamedTuple):
    prefix: str
    label: str
    totals_label: str
    cols: Optional[int]
    colour: bool
    totals: bool
    right_align: bool
    session_id: str = ""    # for stored_ctx_window; see main_cost
    # The third label, kept here rather than read off the module constant, so
    # that --no-usage-text can strip all three from one place.  See main_cost.
    compact_label: str = C_COMPACT_LABEL
    # Draw the "💳 99٪" half of the two limit cells: what the whole plan
    # consumed, beside what this session did.  Off narrows both cells by
    # C_LIM_TOT on BOTH rows, which is what keeps them stacked.
    account_totals: bool = True
    # Draw the 📅 date and 🕐 clock cells.
    stamps: bool = True
    # Start the message with a newline unconditionally.  See render_cost_line
    # for the eleven columns this is really about, and for when it is taken
    # without being asked for.
    force_newline: bool = False


def turn_cost(t: Turn) -> float:
    """List-price cost of one turn, at Opus 5 rates."""
    return (t.fresh * P_IN + t.out * P_OUT
            + t.cache_read * P_CR + t.cache_write * P_CW)


def turn_cost_since(t: Turn, start: Optional[datetime]) -> float:
    """The part of one turn's cost that was billed at or after `start`.

    A turn is not an instant.  This one ran 56 calls over five minutes and a
    plan window opened in the middle of it, and until 2026-09-03 every reader
    here charged the whole turn to whichever window its PROMPT was typed in —
    `Turn.ts`, which is when the user pressed return and not when any of the
    money was spent.  Measured on the turn that exposed it: prompt at
    14:57:32, window open at 15:00:00, $1.02 billed across 13 calls before the
    reset and $3.85 across 43 calls after it.  All $4.87 went to the window
    that had closed, and the status row reported this session's share of the
    live one as 0٪ — under a 🎤 cell reporting the same turn at 18٪, because
    that cell had no window bound on it at all.  A column whose three fields
    are the same window read at three scopes printed turn > session > account,
    which is not a rounding error but an ordering that cannot happen.

    The machine-wide scan had it right the whole time and is worth reading
    beside this: _window_costs filters INDIVIDUAL assistant records by their
    own stamps.  The per-session tally was the only place a turn was still
    atomic, so calibration's denominator was split at the boundary and the
    numerator divided into it was not.

    A stamp that will not parse counts IN, which is _window_costs' rule and
    session_shares' before it: both windows end at now, so the likelier of the
    two errors is to drop a call that belongs.

    Falls back to the old whole-turn test when there are no parts to split.
    That is a COMPACTION and only a compaction — it bills through no usage
    record, so its cost comes off the boundary metadata and there is nothing
    stamped to divide.  `t.compact` is tested rather than `not t.parts` alone
    because a /compact prompt can carry both its own calls and the boundary,
    and splitting on the calls would then charge the window a fraction of a
    figure the calls never accounted for.
    """
    if start is None:
        return turn_cost(t)
    edge = start.timestamp()
    if t.compact or not t.parts:
        ts = _local_naive(t.ts)
        return turn_cost(t) if ts is None or ts >= start else 0.0
    return sum(c for e, c in t.parts if e is None or e >= edge)


def window_shares(t: Turn, calib: Dict[str, Optional[float]]
                  ) -> Dict[str, Optional[float]]:
    """One turn's share of each live window, counting only what it billed in.

    The per-prompt half of what session_shares does for the whole session, on
    the same boundaries and the same split, so the 🎤 figure is a part of the
    🎮 figure beneath it by construction rather than by coincidence.  Both
    read _window_starts, which reads limits_snapshot, which is memoised for
    the life of the render — so the two cells cannot end up bounded by
    different moments, which is the failure limits_snapshot exists to stop.
    """
    starts = dict(zip(("sess", "week"), _window_starts()))
    out = {"sess": None, "week": None}
    for key, start in starts.items():
        unit = calib.get(key)
        if unit:
            out[key] = turn_cost_since(t, start) / unit
    return out


def turn_shares(t: Turn) -> Tuple[Optional[int], Optional[int]]:
    """What fraction of one prompt's cost went on re-reading, and on caching.

    The two components of a turn's bill that are ABOUT THE CONTEXT rather than
    about the answer: cache_read, which is the conversation so far being sent
    again, and cache_creation, which is this turn's own new material being
    put where the next request can read it.  Output is the remainder and is
    deliberately not reported -- it is the one part of the bill no amount of
    /compact or /clear can reclaim, so a reading of it would not inform the
    decision these two are here for.

    WHOLE PERCENT, because the field is 💳's three columns and because these
    are ratios to act on rather than figures to add up.  Rounded, not floored:
    nothing sums to them, so the truncation cost_totals_group's note argues
    against has no equivalent here, and half a point of bias in a number read
    as "roughly a third" is worse than the rounding.

    (None, None) for a turn with no cost to take a share OF.  That is a
    compaction, which issues no request of its own -- the same case ctx
    handles by walking back to the last turn that HAS a reading.  Here there
    is nothing to walk back to that would be true of this turn, so the cell
    goes blank rather than borrowing its neighbour's answer.
    """
    c = turn_cost(t)
    if c <= 0:
        return None, None
    return (int(round(100 * t.cache_read * P_CR / c)),
            int(round(100 * t.cache_write * P_CW / c)))
def window_for(turns: Sequence[Turn], session_id: str = "") -> int:
    """The context window in force: what the status line published, else a guess.

    The published figure is Claude Code's own context_window_size, taken from
    the status-line payload — the number the thing enforcing the window is
    using.  It wins outright rather than being reconciled against the guess
    below.  It is refreshed on every status render, so it is at worst seconds
    old, where the guess can be wrong for the whole session.

    THE GUESS, for a session no status line has rendered: the largest reading
    seen.  Not the model name, which the transcript records as plain
    "claude-opus-5" whether or not this is the 1M variant.  A reading above
    200k is proof of the larger window, since the smaller could not have held
    it.

    Its failure mode was called self-correcting, and the correction never came
    in the session that exposed it: a 1M session that has not yet passed 200k
    reads as 200k, so every 🧠 figure runs 5x high — and COMPACTING is what
    keeps it under the line.  This session compacted twice, at 176k and 157k,
    and read 51.3٪ where the truth was 10.3٪.  The habit that keeps a session
    healthy is the one that stops the window ever being proved.  Hence the
    published figure: the guess erring toward a SMALL window is the better of
    two wrong answers, not an acceptable one.
    """
    published = stored_ctx_window(session_id)
    if published:
        return published
    biggest = max((t.ctx for t in turns), default=0)
    return CTX_1M if biggest > CTX_DEF else CTX_DEF


def _price(model: Optional[str]) -> Tuple[float, float, float, float]:
    m = (model or "").lower()
    for key, prices in MODEL_PRICE:
        if key in m:
            return prices
    return MODEL_PRICE[0][1]


def _local_naive(ts: str) -> Optional[datetime]:
    """A transcript's UTC "…Z" stamp as a naive LOCAL datetime.

    The window boundaries arrive from the plan cache as naive local times, so
    both sides of every comparison have to be in that one frame.  Shared by
    the machine-wide scan and by the per-session tally, which have to agree
    about which turns fall inside a window or the two halves of a limit cell
    are measuring different spans.
    """
    try:
        base = ts.split(".")[0].rstrip("Z")
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=_UTC).astimezone().replace(tzinfo=None)
    except Exception:
        return None


def _window_starts() -> Tuple[Optional[datetime], Optional[datetime]]:
    """When the 5-hour and the weekly window opened, or None for either.

    Derived by subtracting each window's length from the reset time the plan
    cache publishes, which is the only end of it that is stated.

    Off limits_snapshot, not off its own read of the source.  A boundary taken
    from one snapshot while the percentage after the "/" comes from another is
    how five hours of turns were once charged to a window that had not opened
    when they ran.
    """
    lim = limits_snapshot()

    def start(key, delta):
        v = lim.get(key)
        if not v:
            return None
        try:
            return datetime.strptime(v, STAMP_FMT) - delta
        except Exception:
            return None

    return (start("session_resets_at", timedelta(hours=5)),
            start("weekly_resets_at", timedelta(days=7)))


def _window_costs(sess_start: Optional[datetime],
                  week_start: Optional[datetime]) -> Tuple[float, float]:
    """Total spend on this machine since each window opened.

    Bounded by FILE MTIME, which the bash and the old Python were not.  The
    scan reads every assistant record in every project's every transcript, and
    json.loads dominates: at roughly ten times the current corpus it crosses
    the Stop hook's timeout and the row simply vanishes with no diagnosis.
    Nothing older than the weekly window can contribute to either figure, so
    skipping those files bounds the work by WINDOW LENGTH instead of by
    history, which does not grow.

    A slack day is allowed either side of the boundary because mtime is when
    the file was last appended to, not when its earliest qualifying record was
    written.
    """
    sess = week = 0.0
    seen = set()
    cutoff = None
    if week_start is not None:
        cutoff = (week_start - timedelta(days=1)).timestamp()
    for fp in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        if cutoff is not None:
            try:
                if os.path.getmtime(fp) < cutoff:
                    continue
            except OSError:
                continue
        for r in _records(fp):
            if r.get("type") != "assistant":
                continue
            u = (r.get("message") or {}).get("usage")
            ts = r.get("timestamp")
            if not u or not ts:
                continue
            k = r.get("requestId") or (r.get("message") or {}).get("id")
            if k in seen:
                continue
            seen.add(k)
            t = _local_naive(ts)
            if t is None:
                continue
            if week_start and t < week_start:
                continue
            pi, po, pr, pw = _price((r.get("message") or {}).get("model"))
            c = (u.get("input_tokens", 0) * pi + u.get("output_tokens", 0) * po
                 + u.get("cache_read_input_tokens", 0) * pr
                 + u.get("cache_creation_input_tokens", 0) * pw)
            week += c
            if sess_start and t >= sess_start:
                sess += c
    return sess, week


def calibration() -> Dict[str, Optional[float]]:
    """Dollars per one percent of each plan window.

    The plist exposes only aggregate percentages, never a per-prompt or
    per-token-class breakdown, so this is DERIVED:

        $/1%          = (cost of everything in the window) / (percent consumed)
        prompt share  = prompt cost / $/1%

    The percentage is the one limits_snapshot publishes — the same reading
    plan_totals prints after the "/" and _window_starts bounds the sum with,
    so all three describe one moment.  Letting them differ would put the two
    🔋 cells of one readout on different scales, which is the same
    disagreement as plan_totals', one row apart — and it happened, by way of
    the DISK cache below: the ratio was stored, so a unit another session had
    derived from a live reading was divided into a share bounded by a stale
    one.

    WHAT IS CACHED IS THE SCAN, NOT THE RATIO, and since 2026-09-03 the
    READING THE SCAN WAS TAKEN WITH goes to disk beside it.  The expensive
    half is _window_costs, which walks transcripts — 1.3 s here, far too slow
    for a status line that redraws as you type; the percentages are free.  So
    the costs go to disk keyed by the WINDOWS they were measured over, the
    reading of that same instant goes with them, and the division happens
    fresh on every call — against that pair, not against a live reading.  A
    rate cannot be estimated from a numerator and a denominator taken minutes
    apart, and at a reset the minutes between them are the whole window: see
    the note at the cache read below for what that printed.

    The unit still cannot disagree with the figure beside it, the scan is
    still paid for at most once per CALIB_TTL, and the cache is still
    invalidated by the only event that actually invalidates it — a reset,
    which moves a boundary.

    NOT DERIVED AT ALL below CALIB_MIN_PCT.  A percentage quantised to whole
    numbers is not a divisor at 1; the shares that would come out of it are
    uncertain by half of themselves, and "?" is what the row has always
    printed for a figure it does not have.

    Self-calibrating — it re-derives from live data each time rather than
    carrying a constant that silently goes stale.  Two honest caveats: it
    assumes limit consumption is proportional to list-price cost (unverified —
    the real weighting is unpublished), and it can only see transcripts on this
    machine.  The second one used to be written down backwards.  Usage from
    elsewhere raises the PERCENTAGE without raising the cost this scan can
    see, so it DEFLATES $/1% and therefore OVERSTATES every share divided by
    it: $14 spent here against a 1٪ reading gives $14 a point, but if a phone
    consumed as much again the reading is 2٪, the unit falls to $7, and the
    same $14 session reads 2٪ when its true share is 1٪.

    Written via a temp file and os.replace: the path is shared by every
    session on the machine, and two hooks finishing together were previously
    able to interleave a write.
    """
    snap = limits_snapshot()
    ss, ws = _window_starts()
    out = {"sess": None, "week": None}
    sp, wp = snap.get("session_pct"), snap.get("weekly_pct")
    cached = _read_calib_cache("%s|%s" % (ss, ws))
    if cached is not None and "windows" not in cached:
        # A planted fixture, which states the two UNITS directly and holds
        # them still.  The goldens need that: the real form is keyed by
        # window boundaries the payloads move on every case, so a fixture in
        # the real form would miss on all thirteen and send the suite off to
        # scan this machine's transcripts.  See tests/pin-env.sh.
        return {"sess": cached.get("sess"), "week": cached.get("week")}
    if cached is not None:
        # BOTH HALVES OFF THE CACHE, which is the 2026-09-03 change and the
        # whole of it.  The scan was cached and the reading was taken live, so
        # a numerator measured five minutes ago was divided by a denominator
        # measured now — and a rate estimated across two moments is only as
        # good as the assumption that nothing moved between them.  At a
        # RESET everything moves: the scan is written seconds into the new
        # window holding seconds of spending, the reading climbs while it
        # sits there, and the unit comes out far too small.  Every share
        # divided by it is then far too large, which is how 🎤 came to print
        # 18٪ of a window whose own account total read 1٪ — a part three
        # times the whole it belongs to.  Same instant on both sides and that
        # cannot happen: this session's transcripts are IN the scan, so its
        # cost is at most sc, so its share is at most sp.
        #
        # This does not contradict the note above about caching the scan and
        # not the ratio.  What must not be cached is the ratio's ANSWER,
        # because a share bounded by one window divided by a unit derived
        # under another is the failure the window key exists to stop.  The
        # two measurements that go INTO it have to be simultaneous, and the
        # window key still holds them to this window.
        sc, wc = cached.get("sess_cost"), cached.get("week_cost")
        sp, wp = cached.get("sess_pct"), cached.get("week_pct")
    elif ss is None and ws is None:
        return out
    else:
        sc, wc = _window_costs(ss, ws)
        _write_calib_cache("%s|%s" % (ss, ws), sc, wc, sp, wp)
    # See CALIB_MIN_PCT: below it the reading's own quantisation is worth
    # more than the figure, and "?" is the honest reading of a scale that
    # cannot be drawn yet.
    if sp and sp >= CALIB_MIN_PCT and sc is not None:
        out["sess"] = sc / sp
    if wp and wp >= CALIB_MIN_PCT and wc is not None:
        out["week"] = wc / wp
    return out


def _read_calib_cache(windows: str) -> Optional[dict]:
    """The cached scan, if it is fresh AND measured over these windows.

    A dict with no "windows" key is a planted fixture and is returned as-is
    for the caller to read as units; anything else has to match, because a
    scan bounded by yesterday's boundary is not an answer about today's.
    """
    try:
        if os.path.getmtime(CALIB_CACHE) <= time.time() - CALIB_TTL:
            return None
        with open(CALIB_CACHE) as fh:
            d = json.load(fh)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    if "windows" not in d:
        return d
    if d.get("windows") != windows:
        return None
    # An entry written before 2026-09-03 carries no reading to pair the scan
    # with, and pairing it with a live one is the bug this key was added to
    # fix.  Treated as a miss, which costs one rescan on the first render
    # after an upgrade and nothing after that.
    return d if "sess_pct" in d else None


def _write_calib_cache(windows: str, sc: float, wc: float,
                       sp: Optional[float], wp: Optional[float]) -> None:
    """The scan, and the two readings it was SIMULTANEOUS with.

    The readings are stored because the division happens later — possibly in
    another process, up to CALIB_TTL after this — and a rate is only estimable
    from a cost and a percentage measured at one moment.  See calibration.
    """
    try:
        tmp = "%s.%d" % (CALIB_CACHE, os.getpid())
        with open(tmp, "w") as fh:
            json.dump({"windows": windows, "sess_cost": sc, "week_cost": wc,
                       "sess_pct": sp, "week_pct": wp}, fh)
        os.replace(tmp, CALIB_CACHE)
    except Exception:
        pass


def plan_totals() -> Dict[str, Optional[float]]:
    """The windows' consumed percentages, or {} — never a mixed pair.

    A row that shows one window's total beside a blank looks authoritative
    about the pair; stating ignorance plainly is the cheaper mistake.

    NOTE, and it is a deliberate change from the program this replaces: the
    figures come from the SAME source the status line used, rather than from a
    fresh reading of a usage source per turn.  Three reasons, in order:

      * The two readouts now agree.  Previously the cost row could print 18٪
        while the status row directly above it printed 17٪, because they asked
        two different times.  Adjacent rows disagreeing about the same number
        is worse than either being a minute stale.

        "The same source" has to be read as the status line's CHOICE of
        source, not as one fixed file, and that is what _read_plan_cache is
        for.  Reading the app's cache unconditionally was enough while the
        status line read it too — but load_limits prefers Claude Code's
        payload whenever it carries rate_limits, and it does.  The two then
        diverged by thirteen points on one screen (cost 43٪, status 56٪),
        which is precisely the failure this bullet claims to have fixed, in
        the code that claims to have fixed it.

        And then it happened a third time, by the remaining path: the plan
        cache expired during a reading gap and the fallback to the app was
        unconditional, so the cost row quoted a three-hour-old snapshot (66٪)
        under a status row reading the live one (38٪).  "Fresher" is now
        measured rather than assumed — see _reading_age — and the choice is
        made once per process in limits_snapshot rather than three times by
        three callers.
      * It removes a ~210ms shell-out from every turn's Stop hook.
      * The staleness is bounded by a TTL chosen for exactly this reason.  The
        menu-bar app polls on its own schedule, so — as the status line's own
        comment puts it — a fresher read would not be a truer one.

    The visible cost is that the totals row can lag the live figure by up to a
    minute.  Revert by calling a non-caching read here if that is ever wrong.
    """
    lim = limits_snapshot()
    sp, wp = lim.get("session_pct"), lim.get("weekly_pct")
    if sp is None or wp is None:
        return {}
    return {"sess": sp, "week": wp}


class Ink(NamedTuple):
    """The cost row's palette, blanked under --plain.

    BOLD and UNBOLD are deliberately NOT blanked.  The Stop hook asks for plain
    because a systemMessage was found not to carry colour, but the label is
    still meant to be bold — so the two are separate decisions and always have
    been.  This is written down because it looks like an oversight and is not.
    """
    r: str
    grn: str
    amb: str
    red: str
    tup: str
    tdn: str
    yel: str
    pnk: str
    pnk2: str
    crm: str


COLOUR_INK = Ink(R, F_GRN, F_AMB, F_RED, F_TUP, F_TDN, F_YEL, F_PNK, F_PNK2,
                 F_CRM)
PLAIN_INK = Ink("", "", "", "", "", "", "", "", "", "")


def share_half(emoji: str, share: Optional[int], ink: Ink) -> str:
    """The C_LIM_TOT half of a PER-PROMPT limit cell, under limit_cell's.

    Same shape as the half it stacks on -- a leading blank, the mark, MARK_SP,
    and one whole-percent reading in three columns -- so the two figures land
    in one column and the row can be read downward.  It is the blank the
    per-prompt row used to pad with, now spent on a reading; the width is
    unchanged, which is the point.  MARK_SP is read HERE and not captured,
    because --no-mark-spacing rebinds it after import and this cell has to
    close with the rest of them.

    A missing share still returns the full seven columns.  seg() pads the cost
    row on the LEFT, so a short cell does not leave a gap at its end: it
    shoves the whole cell right, off the column it has to stack on.  That is
    the same miscount C_LIM_TOT's note warns about, one row up.
    """
    if share is None:
        return " " * C_LIM_TOT
    return " %s%s%s%s%s" % (emoji, MARK_SP, ink.amb, pad_val(3, pct(share)),
                            ink.r)


def cost_group(t: Turn, calib: Dict[str, Optional[float]], win: int, ink: Ink,
               now: Optional[float] = None, acct: bool = True,
               stamps: bool = True) -> str:
    """The constant-width segment group for one prompt.

    Every value is padded to its field width HERE rather than by seg(), so the
    emoji column is fixed too.  Padding the segment as a whole would hold each
    value's right edge but let its icon drift left and right as the value grew
    — which reads as a font problem rather than a layout one, and sends you
    looking in the wrong place.
    """
    # NOT floored.  See cost_totals_group for why the truncation that used to
    # live here is gone from both paths rather than from one of them.
    up = t.fresh + W_CACHE_WRITE * t.cache_write + W_CACHE_READ * t.cache_read
    in_all = t.fresh + t.cache_write + t.cache_read
    cpct = int(100 * t.cache_read / in_all) if in_all else -1
    c = turn_cost(t)
    rd, wr = turn_shares(t)
    # 🔋 and 🪫 below report this prompt's share of each PLAN WINDOW, so what
    # they divide is the part of it billed inside that window — not `c`, which
    # is the whole turn and is what 💰 to their left is for.  The two differ
    # only for a turn that straddles a reset, and for that turn the difference
    # is the whole figure: see turn_cost_since.  The totals row underneath
    # sums the same split over every turn, which is what lets these deltas
    # total the figure beneath them across a reset as well as within one.
    tsh = window_shares(t, calib)
    stamp = time.localtime(now) if now is not None else time.localtime()
    lim_w = C_SESS if acct else C_SESS - C_LIM_TOT
    cells = [
        seg(C_TOK, "%s%s%s%s%s%s" % (
            E_TOK + MARK_SP, ink.tup, E_UP + pad_val(4, humanize(up)),
            ink.tdn, " " + E_DOWN + pad_val(4, humanize(t.out)), ink.r),
            left=False),
        seg(C_CACHE, "%s%s%s%s" % (E_CACHE + MARK_SP, _cache_ink(cpct, ink),
                                   pad_val(3, pct(cpct)), ink.r)
            if cpct >= 0 else "", left=False),
        # Percentage then size, matching render_ctx — and the totals row
        # below repeats the order, because these two rows stack field under
        # field and a swap in one alone would tear that apart.
        seg(C_CTX, "%s%s%s %s%s%s" % (
            E_CTX, ink.pnk2, signed_pct(t.dctx, win),
            ink.pnk, signed(t.dctx), ink.r)
            if t.dctx is not None else "", left=False),
        # "+", not a sign: a prompt cannot cost less than nothing, so there
        # is no negative case to distinguish and the mark is free to mean
        # "added" — the same constant, in the same column, as the two limit
        # cells after it.  Every figure on this row is what ONE prompt put on
        # the reading directly beneath it.
        seg(C_COST, "%s%s+%s%s" % (E_COST, ink.yel,
                                   money_cell(c), ink.r),
            left=False),
        # The second half of each cell is the C_LIM_TOT the row below spends
        # on 💳 and the window's own reading.  It was seven blanks until
        # 2026-09-03 — reserved so the emoji above lands over the emoji below,
        # and otherwise wasted.  It now carries where THIS prompt's money
        # went: 📖 the part spent re-reading the conversation, 📝 the part
        # spent caching what this turn added.  See turn_shares for why those
        # two and not a third, and E_READ for why they are shares of the turn
        # rather than of the window whose glyph opens the cell.
        #
        # The reservation is unchanged either way, and it must be: seg() pads
        # the cost row on the LEFT, so a cell narrower than the one below it
        # is not a gap at the end of a row but a whole cell pushed right, off
        # the column it has to stack on.  With --no-account-totals there is no
        # 💳 half below to stack ON, so the halves go together — which is why
        # share_half is reached through the same `acct` test the blank was.
        seg(lim_w, "%s%s+%s%s%s" % (
            E_SESS, ink.amb,
            dec_align(plan_pct(tsh["sess"]), 2, 2, E_PCT), ink.r,
            share_half(E_READ, rd, ink) if acct else "")
            if tsh.get("sess") is not None else "", left=False),
        seg(lim_w, "%s%s+%s%s%s" % (
            E_WEEK, ink.amb,
            dec_align(plan_pct(tsh["week"]), 2, 2, E_PCT), ink.r,
            share_half(E_WRITE, wr, ink) if acct else "")
            if tsh.get("week") is not None else "", left=False),
        # "+" as on 💰, 🔋 and 📆 beside it: every figure on this row is what
        # ONE prompt added to the reading directly beneath it, and this one is
        # the time it took.  The totals row prints a space in the column.
        seg(C_ELAPSED, "%s%s+%s%s" % (S_WORK, ink.crm,
                                      pad_val(4, dur_fmt(t.dur_s)), ink.r),
            left=False),
        # Blank on a compaction, and the CELL is kept so the columns to its
        # left still stack.  The stamp is `now` — when this line is being
        # drawn — which is honest for the prompt just answered and a lie for
        # a compaction, which happened at some earlier point in the session
        # and is only being reported now because `/compact` fires no Stop of
        # its own.  Printing the moment of the REPORT beside the cost of the
        # EVENT invites reading one as the other.
        seg(C_STAMP, "%s%s%s%s" % (
            S_DATE, ink.crm,
            pad_val(10, time.strftime("%Y-%m-%d", stamp)), ink.r)
            if not t.compact else "", left=False),
    ]
    # Dropped, not blanked.  An empty seg() is still exactly its reservation,
    # so blanking would leave thirteen columns of nothing at the right edge
    # and buy the narrow window none of the room the option is asked for.
    if not stamps:
        cells.pop()
    return (" " * C_SEG_GAP).join(cells)


def _cache_ink(p: int, ink: Ink) -> str:
    if p <= CACHE_CRIT:
        return ink.red
    if p <= CACHE_WARN:
        return ink.amb
    return ink.grn


def session_shares(turns: Sequence[Turn],
                   calib: Dict[str, Optional[float]]
                   ) -> Dict[str, Optional[float]]:
    """What THIS session put into each plan window, as a percentage of it.

    Both readouts, since 2026-08-25.  The status line derived its own version
    by subtracting plan-wide readings, which counted every other session's
    consumption as this one's and collapsed onto the plan-wide total the
    moment a window reset under a live session — see _with_shares for what
    that looked like on screen.  One derivation, two rows.

    The totals row's 🔋 and 🪫 were the plan-wide readings — every session on
    this machine, plus anything run off it — printed under a label that says
    "Session".  They were the only two cells on the row that did not total
    the column above them, and nothing in the row said so.  Now they do total
    it, and the plan-wide figure moves to the far side of a "/", which is the
    arrangement the status line already uses for this same pair.

    Bounded by the WINDOW, not by the session.  A session outliving its
    5-hour window still holds turns that reset with it, and charging those to
    the current window would report a share the window never saw.  That is
    the ordinary case rather than the corner: the session this was written in
    was nine hours old against a five-hour window.

    Same derivation as the per-prompt cell directly above — cost over dollars
    per one percent — so the deltas on that row now sum to the figure beneath
    them, which is what the column claims and could not previously deliver.

    Each turn is SPLIT at the boundary rather than tested against it.  It used
    to be tested — `_local_naive(t.ts) >= start`, on the stamp of the prompt —
    and a turn that straddles a reset then went wholly to the window it was
    typed in, which by then was the window that had closed.  See
    turn_cost_since for the measurement; the short version is that a five
    minute turn put $3.85 into the live 5-hour window and this function
    reported 0.  A turn whose stamp will not parse is still counted IN, for
    the reason it always was: both windows end at now, so the likelier of the
    two errors is to drop spending that belongs.
    """
    out = {"sess": None, "week": None}
    if not calib:
        return out
    starts = dict(zip(("sess", "week"), _window_starts()))
    for key, start in starts.items():
        unit = calib.get(key)
        if not unit or start is None:
            continue
        out[key] = sum(turn_cost_since(t, start) for t in turns) / unit
    return out


def limit_cell(emoji: str, share: Optional[float], total: Optional[float],
               ink: Ink, acct: bool = True) -> str:
    """A totals-row limit cell: this session's share, then 💳, the window's.

    Two figures about one window — before the mark, what this session spent;
    after it, what the window has consumed altogether — and the mark between
    them is the status line's, because the figure it introduces is the status
    line's.  💳 sits beside that same reading in column 4, so a reader moving
    between the readouts meets one glyph for one quantity.

    It was a spaced slash until 2026-08-27, and the note here claimed the
    slash as "the status line's idiom for exactly this pair".  That was never
    true: column 4 divides its four fields with marks and has no slash on it
    anywhere.  What the two readouts genuinely shared was the PAIR, and a
    slash is the one divider that says nothing about which half is which — it
    reads as "out of", which is wrong twice over here, since the share is a
    percentage of the same window and not a part of the total beside it.
    💳 names the second figure instead of merely separating it.

    render_diff dropped its own slash on the same argument and is worth
    reading beside this: "the signs already say which half is which, so the
    slash was a column spent repeating them".  Here the mark does not merely
    avoid repeating something — it says the one thing the cell could not
    otherwise say, which of the two windows-worth of spending is the account's.

    The two halves are formatted differently on purpose.  The share keeps
    plan_pct's decimals because it has to stack under the per-prompt delta
    above it, and dec_align holds its point in a fixed column; the total is
    whole percent, because it is context for the share rather than a figure
    to act on, and because its source quantises to whole points anyway.

    The mark takes MARK_SP after it, exactly as the three scope marks do on
    the status line, so --no-mark-spacing closes this blank with those and the
    cell comes back to the six columns the slash form spent.

    The cost of holding that decimal column is that the gap BEFORE the mark
    floats: a share with no fraction leaves up to three further blanks there.
    Worth it — the point column is the one this row is read down, and the
    total after 💳 still lands in a fixed column either way.

    💯 stands in for a full window here exactly as it does on the status
    line's 💳 field, and that is not decoration.  This total and that field
    are THE SAME READING from the same source, so before it the two readouts
    disagreed at the one moment either of them matters: the status line drew
    💯 and this row printed "99٪" — not a rounding but pct's clamp, which is
    to say a figure that was never true.  A three-column field cannot hold
    "100٪", so the glyph is what makes the honest reading fit, in both places,
    in the same three columns.  With 💳 ahead of it the pair now renders as
    the status line's own 💳 💯٪ -- the unit included, because the glyph
    replaces the FIGURE and not the unit after it, and a column read downward
    should not lose its unit at the one reading that matters.  "💯٪" is three
    columns, which is what " 💯" was.
    """
    if share is None and (total is None or not acct):
        return ""
    left = (dec_align(plan_pct(share), 2, 2, E_PCT) if share is not None
            else pad_val(C_SESS - C_LIM_TOT - 3, "?"))
    if not acct:
        return "%s%s %s%s" % (emoji, ink.amb, left, ink.r)
    # The threshold is render_limit's, so the two readouts can never draw
    # different things for one window: 99.5 up is full, and 💯 says so.
    if total is None:
        right = "?"
    elif total >= 99.5:
        right = E_HUNDRED + E_PCT
    else:
        right = pct(round(total))
    return "%s%s %s%s %s%s%s%s%s" % (emoji, ink.amb, left, ink.r,
                                     E_ACCT, MARK_SP,
                                     ink.amb, pad_val(3, right), ink.r)


def cost_totals_group(turns: Sequence[Turn], totals: Dict[str, Optional[float]],
                      win: int, ink: Ink, now: Optional[float] = None,
                      calib: Optional[Dict[str, Optional[float]]] = None,
                      acct: bool = True, stamps: bool = True) -> str:
    """The session-to-date row that sits under the per-prompt one.

    Same segment order and the same widths, so each total lands directly
    beneath the figure it totals.  Two of the seven have no meaningful total:

      🧠  not a delta but the absolute reading the deltas have summed to.
      🕐  blank.  A clock has no total, and an elapsed figure would be a
          different metric wearing the same icon.

    🔋📆 carry two figures each and are the reason this note changed.  They
    used to carry only the windows' plan-wide consumption, which is a total
    of every session on the machine rather than of the column above it — the
    one place this row printed something other than what its label promised.
    The session's own share now leads the cell and the plan-wide reading
    follows a "/", so the column sums and the wider context survives.  See
    session_shares and limit_cell.

    The cache rate is recomputed over every request rather than averaged over
    the per-prompt rates, which would weight a hundred-token turn like a
    hundred-thousand-token one.

    The weighted ▴ figure is never truncated, here or in the per-prompt row.
    The implementation this replaces floored it once per turn and then summed,
    so the total drifted below a true tally by up to a token per turn without
    bound — 7 tokens over a 14-turn transcript, measured.  That is invisible at
    humanize()'s three significant digits, which is how it survived.

    Flooring only the total would have been worse than leaving it: the
    per-prompt rows would then no longer sum to the row beneath them, which is
    a more confusing kind of wrong than being seven tokens light.  So the
    truncation is gone from BOTH paths rather than fixed in one.  It bought
    nothing in the first place — the value is weighted by 2.0 and 0.1, so it is
    fractional by construction, and humanize() formats it to three significant
    digits whether or not it arrives whole.
    """
    up = sum(t.fresh + W_CACHE_WRITE * t.cache_write
             + W_CACHE_READ * t.cache_read for t in turns)
    out_tok = sum(t.out for t in turns)
    cr = sum(t.cache_read for t in turns)
    in_all = sum(t.fresh + t.cache_write + t.cache_read for t in turns)
    cpct = int(100 * cr / in_all) if in_all else -1
    # The last turn that HAS a reading, not simply the last turn.  A
    # compaction has none — it issues no request whose usage could be counted
    # — and reading straight off the end blanked this cell for the one row
    # printed immediately after a compaction, which is where the absolute
    # figure is most worth having.
    ctx = next((t.ctx for t in reversed(turns) if t.ctx), 0)
    c = sum(turn_cost(t) for t in turns)
    mine = session_shares(turns, calibration() if calib is None else calib)
    stamp = time.localtime(now) if now is not None else time.localtime()
    # Every turn's answering time, summed — the total of the figure directly
    # above it, which is what every other cell on this row is.  It is NOT the
    # session's age: an age counts the hours the session sat waiting for
    # someone to type, and no per-prompt row can add up to that.  The status
    # line is where the age belongs, and it has it, next to this same total
    # and to the difference between them.
    work_s = sum(t.dur_s for t in turns)
    lim_w = C_SESS if acct else C_SESS - C_LIM_TOT
    cells = [
        seg(C_TOK, "%s%s%s%s%s%s" % (
            E_TOK + MARK_SP, ink.tup, E_UP + pad_val(4, humanize(up)),
            ink.tdn, " " + E_DOWN + pad_val(4, humanize(out_tok)), ink.r),
            left=False),
        seg(C_CACHE, "%s%s%s%s" % (E_CACHE + MARK_SP, _cache_ink(cpct, ink),
                                   pad_val(3, pct(cpct)), ink.r)
            if cpct >= 0 else "", left=False),
        # A space where the per-prompt row prints its sign, then the same
        # dec_align — so the two readings stack digit under digit and the
        # column reads as one figure changing rather than two figures.  This
        # is what 💰, 🔋 and 📆 do further along the row.
        seg(C_CTX, "%s%s %s %s %s%s" % (
            E_CTX, ink.pnk2,
            dec_align("%.1f" % (100.0 * ctx / win), 2, 1, E_PCT),
            ink.pnk, pad_val(4, humanize(ctx)), ink.r)
            if ctx else "", left=False),
        seg(C_COST, "%s%s %s%s" % (E_COST, ink.yel,
                                   money_cell(c), ink.r),
            left=False),
        seg(lim_w, limit_cell(E_SESS, mine.get("sess"),
                              totals.get("sess") if totals else None, ink,
                              acct),
            left=False),
        seg(lim_w, limit_cell(E_WEEK, mine.get("week"),
                              totals.get("week") if totals else None, ink,
                              acct),
            left=False),
        # The pair the status line's column 4 makes, split across the two
        # rows this readout already has: what the last prompt took, over how
        # long the session has been alive.  And the stamp beside it splits the
        # same way — the date on the row above the clock it belongs to, which
        # is what a line printed at 00:03 needs and a bare clock cannot give.
        seg(C_ELAPSED, "%s%s %s%s" % (S_WORK, ink.crm,
                                      pad_val(4, dur_fmt(work_s)), ink.r),
            left=False),
        seg(C_STAMP, "%s%s%s%s" % (
            S_TIME, ink.crm,
            pad_val(10, time.strftime("%H:%M:%S", stamp)), ink.r), left=False),
    ]
    if not stamps:            # dropped rather than blanked; see cost_group
        cells.pop()
    return (" " * C_SEG_GAP).join(cells)


def place(group: str, opts: CostOpts, label: str, chrome: int) -> str:
    """One finished line: label and group together at the right edge.

    The whole row is one right-aligned block — leading spaces, then the icon,
    the label, the gap, and the metrics, ending at
    cols - chrome - RIGHT_MARGIN.  The label rides at the group's left rather
    than sitting at the left margin with a lake of padding between them, so the
    row reads as one object and the eye travels a short distance from the words
    to the numbers they describe.

    Three cases, in the order they are tried:

      1. Width known and everything fits — emit the leading pad.
      2. Width known but too narrow for the label — the label is truncated to
         what is left after the group and the gap, with NO leading pad.  The
         group is never moved and never cut: it is the reason the line exists,
         while the label says the same thing every turn.
      3. No width, or right-alignment off — `claude -p`, cloud sessions, or a
         pipe.  Left-aligned after a single space; the fields keep their fixed
         widths, so only the placement of the block is lost, not the stacking
         within it.

    Bold is applied HERE and nowhere earlier, so no escape sequence is ever
    present while a width is being computed.  Measuring a painted label would
    over-count it by about eight columns and drift the group left — which
    presents as a padding bug and sends you hunting in the padding.
    """
    def painted(lbl):
        parts = [p for p in (opts.prefix,
                             BOLD + lbl + UNBOLD if lbl else "") if p]
        return " ".join(parts)

    if opts.cols and opts.right_align:
        room = opts.cols - chrome - C_RIGHT_MARGIN - vis_width(group)
        plain = " ".join(p for p in (opts.prefix, label) if p)
        pad = room - vis_width(plain) - C_MIN_GAP
        if pad >= 0:
            return " " * pad + painted(label) + " " * C_MIN_GAP + group
        keep = trunc(label, max(0, room - vis_width(opts.prefix) - 1
                                - C_MIN_GAP))
        head = painted(keep) if keep else opts.prefix
        return head + " " * C_MIN_GAP + group
    head = painted(label)
    return head + " " + group if head else group


def stack_metrics(rows: Sequence[Tuple[str, str, int]],
                  opts: CostOpts) -> Tuple[int, int, int]:
    """(tight, room, base) for a block of rows — the whole layout decision.

    Extracted so that render_cost_line can ASK whether a block fits before
    place_stacked commits to it, which is what the leading newline turns on.
    Answering that by laying the block out twice and comparing the strings
    would work and would also mean the answer could drift from the layout.

      tight  the widest row once each is charged its own chrome
      room   what is left for the label after the widest row and the margin
      base   the leading pad; NEGATIVE means the labels have to be cut
    """
    tight = max(c + vis_width(g) for g, _, c in rows)
    room = opts.cols - C_RIGHT_MARGIN - tight
    widest = max(vis_width(" ".join(p for p in (opts.prefix, lb) if p))
                 for _, lb, _ in rows)
    return tight, room, room - widest - C_MIN_GAP


def place_stacked(rows: Sequence[Tuple[str, str, int]],
                  opts: CostOpts) -> List[str]:
    """Several rows placed as ONE block, so they cannot drift apart.

    `rows` is (group, label, chrome) in emission order.  The decision is taken
    once, against the tightest row (most chrome, widest group), and every row
    is then shifted by its own chrome relative to that; rows share a cell grid,
    so equal left edges give equal columns throughout.

    Placing each row with place() independently is what broke the stacking, and
    README's "The layout rule" says why in full: the rows do not get the same
    room, so as a window narrows the FIRST row crosses into place()'s
    truncation path while the second is still comfortably right-aligning.  A
    row that has to truncate now takes the others with it — all short together
    beats one aligned and one not.
    """
    def painted(lbl: str) -> str:
        parts = [p for p in (opts.prefix,
                             BOLD + lbl + UNBOLD if lbl else "") if p]
        return " ".join(parts)

    if not (opts.cols and opts.right_align):
        return [(painted(lb) + " " + g).strip() if painted(lb) else g
                for g, lb, _ in rows]

    tight, room, base = stack_metrics(rows, opts)
    out = []
    for group, label, chrome in rows:
        shift = tight - chrome - vis_width(group)
        if base >= 0:
            out.append(" " * (base + shift) + painted(label)
                       + " " * C_MIN_GAP + group)
            continue
        keep = trunc(label, max(0, room - vis_width(opts.prefix) - 1
                                - C_MIN_GAP))
        head = painted(keep) if keep else opts.prefix
        out.append(" " * shift + head + " " * C_MIN_GAP + group)
    return out


def render_cost_line(turns: Sequence[Turn], opts: CostOpts,
                     now: Optional[float] = None) -> str:
    """Every cost row as ONE string joined by newlines.

    They must ship together in a single systemMessage: the box prints
    "Stop says: " against the first line only, so a second message would get
    the full C_CHROME_LEFT columns of chrome and misalign by eleven.

    Two rows normally, three in the one line that follows a compaction, and
    optionally a leading blank one — see the note beside `lead_nl` below.
    """
    if not turns:
        return opts.prefix + " (no prompts recorded yet)"
    ink = COLOUR_INK if opts.colour else PLAIN_INK
    win = window_for(turns, opts.session_id)
    calib = calibration()
    # The last turn that was actually ANSWERED.  A queue that drains two
    # messages at once opens a turn for each, and only the last of them
    # carries the requests — the other is a real prompt with no answer of its
    # own, and reporting it would print a row of zeros for a prompt the user
    # just watched being answered.  Falls back to the true last turn, so a
    # transcript with no usage at all still renders rather than vanishing.
    # EXACTLY ONCE per compaction is the requirement here; README's
    # "Compaction is reported exactly once" says why it falls to this line at
    # all and why Turn.reported, not the pairing below, is what buys it.
    #
    # The pairing is the FALLBACK.  This line fires once per ANSWERED PROMPT,
    # so number the answered prompts and every compaction falls between
    # exactly one consecutive pair of them; let the second of the pair report
    # it and it is reported once.  Hence `prompts` excludes compaction turns
    # on BOTH ends: were `last` allowed to be a compaction, that compaction
    # would print here AND fall inside the next prompt's window, which is the
    # one way that rule can print twice.
    #
    # It can also print ZERO times, which is what retired it as the primary.
    # The argument assumes every Stop sees its own prompt, and the transcript
    # is not flushed in step with the hook (read_turns_settled).  A Stop that
    # cannot see its prompt reports the previous one instead, two consecutive
    # Stops share a window, and the pair straddling the compaction never gets
    # a Stop of its own.
    #
    # Every compaction in the window prints, not just the newest, because the
    # window belongs to no other line — whatever is dropped here is never
    # reported anywhere.
    prompts = [i for i, t in enumerate(turns) if t.calls and not t.compact]
    li = prompts[-1] if prompts else len(turns) - 1
    prev = prompts[-2] if len(prompts) > 1 else -1
    last = turns[li]
    # Where a previous Stop actually drew its line, when the transcript says
    # so: every compaction no Stop has run past yet, which is exactly once
    # each however the prompts fall.  It also catches a compaction AFTER
    # `last`, which the pairing cannot see at all and which is precisely the
    # case that loses one.  The pairing stays as the fallback for a transcript
    # with no such record — every corpus payload, and any session whose first
    # Stop has not run — where "no Stop has run past this" is true of every
    # turn and would reprint the same compaction on every line.
    if any(t.reported for t in turns):
        pending = [t for t in turns if t.compact and not t.reported]
    else:
        pending = [t for t in turns[prev + 1:li] if t.compact]
    acct, stamps = opts.account_totals, opts.stamps
    spec = [(cost_group(t, calib, win, ink, now, acct, stamps),
             opts.compact_label,
             C_CHROME_LEFT if i == 0 else C_CHROME_CONT)
            for i, t in enumerate(pending)]
    spec.append((cost_group(last, calib, win, ink, now, acct, stamps),
                 opts.compact_label if last.compact else opts.label,
                 C_CHROME_LEFT if not spec else C_CHROME_CONT))
    if opts.totals:
        spec.append((cost_totals_group(turns, plan_totals(), win, ink, now,
                                       calib, acct, stamps),
                     opts.totals_label, C_CHROME_CONT))
    # One blank line buys eleven columns: "Stop says: " is printed against the
    # FIRST line only, so opening the message with a newline spends that line
    # on the prefix alone and lays every row out against C_CHROME_CONT.  See
    # README, '"Stop says: ", and the eleven columns'.
    #
    # Taken automatically only where it decides something — the block has to
    # cut its labels with the prefix and does not have to without it.  A window
    # too narrow either way keeps its first line, because there the newline
    # buys a slightly longer label at the price of a whole row, and the label
    # says the same thing every turn.
    lead_nl = opts.force_newline
    if not lead_nl and opts.cols and opts.right_align:
        flat = [(g, lb, C_CHROME_CONT) for g, lb, _ in spec]
        lead_nl = (stack_metrics(spec, opts)[2] < 0
                   <= stack_metrics(flat, opts)[2])
    if lead_nl:
        spec = [(g, lb, C_CHROME_CONT) for g, lb, _ in spec]
    rows = [r.rstrip() for r in place_stacked(spec, opts)]
    # A blank line under the compaction rows, when there are rows after them.
    # The compaction is not part of the prompt/totals pair below it: those two
    # stack field under field and are read as a column, and a compaction row
    # butted against them reads as a third member of that stack rather than as
    # the separate event it is.  Inserted after layout, never as a spec entry —
    # place_stacked measures every row it is given to decide the block's one
    # left edge, and an empty group would be measured with the rest.
    lead = len(pending) + (1 if last.compact else 0)
    if lead and len(rows) > lead:
        rows.insert(lead, "")
    return ("\n" if lead_nl else "") + "\n".join(rows)


# ════════════════════════════════════════════════════════════════════════════
# Alignment self-test.
#
# Answers "are the width tables right for this terminal?" in one glance,
# without a live session and without counting columns by eye.
#
# It renders representative rows from synthetic data, draws each on the tty,
# then asks the terminal where the cursor actually landed (DSR) and reports the
# difference from what vis_width predicted.  That difference IS the correction.
#
#   delta 0    the tables are right for this row
#   delta > 0  the terminal advanced further than predicted — a glyph on this
#              row belongs in `icons`; on a live line this shows up as the row
#              being cut off with an ellipsis
#   delta < 0  the terminal advanced less — a glyph belongs in `narrow`; on a
#              live line the row sits short of the right margin
#
# Rows are chosen to exercise the glyphs that have actually caused trouble,
# including one carrying several at once: errors accumulate along a row, so a
# single-glyph row can be wrong without being visibly wrong.
# ════════════════════════════════════════════════════════════════════════════

def selftest() -> int:
    try:
        tty = open("/dev/tty", "r+b", buffering=0)
    except OSError:
        print("needs a real terminal tab (DSR has no tty here)")
        return 1

    import tty as ttymod
    fd = tty.fileno()
    old = termios.tcgetattr(fd)
    cols = term_cols() or 80

    # Report to stdout so it can be redirected; rows are drawn on the tty and
    # LEFT there.  Both halves are needed and they are not the same thing: the
    # numbers say whether the width tables are right, and the drawn rows are
    # the only way to catch a fault that measures correctly and renders wrong —
    # 🕰 dropped the colons of the time beside it while every measurement of it
    # was perfect.  Redirecting the report must not cost that.
    print("--- claude-code-usage-statusline --selftest ---")
    print("profile:           %s" % PROFILE)
    print("TERMINAL_EMULATOR: %s" % os.environ.get("TERMINAL_EMULATOR", "unset"))
    print("TERM_PROGRAM:      %s" % os.environ.get("TERM_PROGRAM", "unset"))
    print("TERM:              %s" % os.environ.get("TERM", "unset"))
    print("TMUX:              %s" % ("set" if os.environ.get("TMUX") else "unset"))
    print("python:            %s" % sys.version.split()[0])
    print("terminal width:    %s (rows should reach %s)"
          % (cols, cols - RIGHT_MARGIN))
    print("narrow=%s  icons=%s  clusters=%s\n"
          % (sorted(WIDTHS.narrow), sorted(WIDTHS.icons), WIDTHS.clusters))

    rows = [
        ("cache", render_cache(98)),
        ("limit-session", render_limit(S_SESS, "38", "5", "", "0.4")),
        ("limit-weekly", render_limit(S_WEEK, "84", "2", "", "0.05",
                                      F_LIM_WEEK)),
        # Both fields in their fraction form.  Every limit_pct branch fills
        # its four characters, so this one is not wider than the whole
        # percentages above — it is the one whose glyphs are all punctuation
        # and digits with no leading pad to hide a miscount.
        ("limit-fractional",
         render_limit(S_WEEK, "0.384", "0.04", "", "0.004", F_LIM_WEEK)),
        ("elapsed-clock", pair(S_IDLE + pad_val(RST_W, "45s", True),
                               render_time(), RIGHT_GRID[-1])),
        # The same cell with nothing elapsed to report, which is how every
        # session starts and the state in which the clock used to wander.
        ("clock-alone", pair("", render_time(), RIGHT_GRID[-1])),
        ("model-effort", render_model("Opus 5 (1M context)", CTX_1M)
         + "   " + render_effort("high")),
        ("diff", render_diff("302", "70")),
        ("tokens", render_tokens(9900000, 460000)),
        ("mixed", grid_row((render_style("explanatory"),
                            render_tokens(9900000, 460000),
                            render_cache(98),
                            render_limit(S_SESS, "38", "5", "", "0.4")))),
        ("cost-row", cost_group(
            # dctx explicitly: the specimen is built positionally, so a new
            # field with no default silently turns this row into a TypeError
            # that only fires in a real terminal — the tty guard returns
            # first everywhere else.  It did, for as long as dctx existed.
            Turn("", "", 40000, 8000, 900000, 3000, 640000, 3, 142000, None),
            {"sess": 0.5, "week": 2.0}, CTX_1M, COLOUR_INK)),
        # The TOTALS row, which the per-prompt specimen above cannot stand in
        # for.  It used to be the WIDER of the two — 🔋 and 🪫 carried a
        # second figure each where the row above them carried blanks — and
        # since 2026-09-03 it is not: 📖 and 📝 fill that half on the
        # per-prompt row, so both rows now spend C_SESS on content.  Which is
        # why this specimen still has to be measured separately rather than
        # dropped as the narrower case: what differs now is the CONTENT of
        # those seven columns, not their width, and it is content with its own
        # ways to miscount — dec_align's fixed point, the "?" fallback, and 💯
        # standing in for a full window.  C_SESS is still the width whose
        # failure shows up as the two 📊 refusing to stack rather than as
        # anything near this cell.
        #
        # Whether session_shares finds a live plan cache does not matter to
        # what is being measured — dec_align returns exactly six columns for
        # every value, and the "?" it falls back to is padded to the same six
        # — so the row is this width either way.
        ("cost-totals", cost_totals_group(
            (Turn("2026-08-24T12:00:00.000Z", "", 40000, 8000, 900000, 3000,
                  640000, 3, 142000, None),),
            {"sess": 26.0, "week": 80.0}, CTX_1M, COLOUR_INK,
            calib={"sess": 0.5, "week": 2.0})),
    ]

    try:
        ttymod.setcbreak(fd)
        for name, row in rows:
            expect = vis_width(strip_ansi(row))
            tty.write(("\r\033[K%s\033[6n" % row).encode("utf-8"))
            resp = b""
            while not resp.endswith(b"R"):
                ch = tty.read(1)
                if not ch:
                    break
                resp += ch
            tty.write(b"\n")
            try:
                actual = int(resp.decode("ascii", "replace")
                             .rstrip("R").split(";")[-1]) - 1
            except ValueError:
                actual = 0
            delta = actual - expect
            hint = ""
            if delta > 0:
                hint = "  -> a glyph here belongs in `icons`"
            elif delta < 0:
                hint = "  -> a glyph here belongs in `narrow`"
            print("%-14s predicted %-3s actual %-3s delta %+d%s"
                  % (name, expect, actual, delta, hint))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        tty.close()

    print("\nall deltas 0 means the tables are right for this terminal.")
    print("the rows above are drawn on the terminal even when this report is")
    print("redirected: look at them too, since a glyph can measure correctly")
    print("and still render wrong, and no number will tell you that.")
    return 0


# ════════════════════════════════════════════════════════════════════════════
# Entry points.
#
# The mode dispatch is the outermost thing in the program, deliberately.  The
# two modes have OPPOSITE failure policies and neither may leak into the other:
#
#   status  fails visibly.  A blank status line is its own error message, and
#           swallowing a traceback there would hide a broken render forever.
#   cost    fails SILENT.  It runs as a Stop hook under a timeout, and a
#           traceback attaches noise to every turn.  Every failure path prints
#           "{}" — a valid no-op hook response — and exits 0.
# ════════════════════════════════════════════════════════════════════════════

def _flag(argv: Sequence[str], name: str, default: str = "") -> str:
    """Value of a `--name value` argument.

    Matched by MEMBERSHIP, not position: reading argv positionally once meant
    `--last` alone silently turned colour on.
    """
    try:
        return argv[argv.index(name) + 1]
    except (ValueError, IndexError):
        return default


def main_status(argv: Sequence[str], raw: str) -> int:
    pay = read_payload(raw)

    # Debug tap: with ~/.claude/.statusline-debug present, each render drops
    # its payload where it can be read.  For questions of the form "where did
    # that figure come from", which are otherwise unanswerable — the payload
    # arrives on a pipe and vanishes.  Remove the marker file to switch off.
    if os.path.isfile(os.path.expanduser("~/.claude/.statusline-debug")):
        try:
            with open(os.path.join(os.environ.get("TMPDIR", "/tmp"),
                                   "statusline-payload.json"), "w") as fh:
                fh.write(raw)
        except OSError:
            pass

    current = pay.current_dir or pay.project_dir
    pay = pay._replace(current_dir=current,
                       project_dir=pay.project_dir or current)

    tr = (read_transcript(pay.transcript)
          if pay.transcript and os.path.isfile(pay.transcript)
          else EMPTY_TRANSCRIPT)
    git = detect_git()
    # load_limits fills the plan-wide halves and seeds the snapshot; the
    # session halves need the transcript, which only this function has.
    lim, turn_s = _with_shares(load_limits(pay), pay.transcript)
    cols_s = _flag(argv, "--cols")
    # "--cols 0" means "pretend the width is unknown", which is the only way to
    # exercise the fallback layout deterministically from a test.
    cols = (int(cols_s) or None) if cols_s.isdigit() else term_cols()
    sys.stdout.write(
        render_status(pay, tr, git, lim, cols, frozen_now(), turn_s,
                      "--no-column-rules" not in argv))
    return 0


def main_cost(argv: Sequence[str], raw: str) -> int:
    """The Stop hook.  Everything here is inside one catch-all.

    It replaces both cost-line.py and hooks/cost-line.sh: the hook used to
    parse the payload in bash, walk the ancestry for the width, then spawn a
    second Python to do the work.  One process now does all three.
    """
    try:
        transcript = _flag(argv, "--transcript")
        if not transcript:
            transcript = (json.loads(raw) or {}).get("transcript_path", "")
        if not transcript or not os.path.isfile(transcript):
            print("{}")
            return 0
        cols_s = _flag(argv, "--cols")
        # "--cols 0" means "pretend the width is unknown", which is the only
        # way to exercise the fallback layout deterministically from a test.
        cols = (int(cols_s) or None) if cols_s.isdigit() else term_cols()
        # --no-usage-text keeps each row's marker glyph and drops the words.
        # The glyph is what tells the three rows apart at a glance; the words
        # are the part that reads identically every turn, which is what makes
        # them the half worth being able to switch off.
        words = "--no-usage-text" not in argv
        opts = CostOpts(
            prefix=_flag(argv, "--prefix", E_COSTLINE),
            label=_flag(argv, "--label", C_LABEL if words else E_ROW_PROMPT),
            totals_label=C_TOTALS_LABEL if words else E_ROW_TOTAL,
            compact_label=C_COMPACT_LABEL if words else E_ROW_COMPACT,
            account_totals="--no-account-totals" not in argv,
            stamps="--no-datetime" not in argv,
            force_newline="--force-newline" in argv,
            cols=cols,
            colour="--color" in argv,
            totals="--no-totals" not in argv,
            right_align="--no-right-align" not in argv,
            # The transcript's BASENAME, not the payload's session_id, so the
            # live hook and --transcript take the same path — they are the
            # same string, and a lookup that only runs in production is a
            # lookup no harness can check.
            session_id=os.path.basename(transcript)[:-len(".jsonl")]
                       if transcript.endswith(".jsonl") else "",
        )
        # The wait belongs to the LIVE hook alone.  `--transcript` names a
        # file nobody is appending to, so there is nothing to wait for and
        # every golden case would pay the budget for a turn that is never
        # coming.
        turns = (read_turns(transcript) if _flag(argv, "--transcript")
                 else read_turns_settled(transcript))

        # --all is the by-hand mode: every prompt in the transcript, listed,
        # as plain text rather than a hook response.  It is not what the hook
        # asks for and never emits JSON, so it cannot be mistaken for one.
        if "--all" in argv:
            ink = COLOUR_INK if opts.colour else PLAIN_INK
            win = window_for(turns, opts.session_id)
            calib = calibration()
            for i, t in enumerate(turns, 1):
                print("--- prompt #%d  %s  “%s…”  (%d calls)"
                      % (i, t.ts, t.text[:58], t.calls))
                print("    " + cost_group(t, calib, win, ink, None,
                                          opts.account_totals, opts.stamps))
            if turns and opts.totals:
                print("\n" + place(
                    cost_totals_group(turns, plan_totals(), win, ink,
                                      calib=calib, acct=opts.account_totals,
                                      stamps=opts.stamps),
                    opts, opts.totals_label, C_CHROME_CONT).rstrip())
            return 0

        line = render_cost_line(turns, opts, frozen_now())
        if not line.strip():
            print("{}")
            return 0
        print(json.dumps({"systemMessage": line}))
        return 0
    except Exception:
        # Fail silent, by contract.  "{}" is a valid no-op hook response, so
        # nothing appears in the terminal and the turn is not disturbed.
        print("{}")
        return 0


USAGE = """\
usage: claude-code-usage-statusline.py --mode {status|cost} [options]
       claude-code-usage-statusline.py --selftest

Renders the Claude Code status line and the per-prompt cost line from one set
of glyphs, widths and formatters.  README.md, beside this file, carries the
design notes: the layout rule, the terminal width tables, and the chrome the
cost rows are laid out against.

modes:
  --mode status      read the status-line JSON on stdin, print three rows
  --mode cost        read the Stop-hook JSON on stdin, print a systemMessage
  --selftest         draw specimen rows and measure them against the terminal

options (both modes):
  --subscript-decimals
                     write a fraction in U+2080..U+2089 instead of after a
                     point: 🎤 1.2٪ becomes 🎤 1₂٪, 💰 29.8 becomes 💰 29₈.
                     Off by default.  The leading zero the status line drops
                     comes back — "₃₈" would read as 38 where ".38" cannot —
                     so a reading under 1٪ is the same width either way.
                     No field is narrowed yet: the saving is real but it is
                     only banked once a probe has measured these glyphs on
                     the terminal in use.
  --no-mark-spacing  close the blank between a mark and its value (🎤 .98٪
                     becomes 🎤.98٪).  Status: all four column-4 fields, so
                     the column narrows from 33 to 29.  Cost: 🧩, 🎯 and the
                     💳 inside a totals-row limit cell -- the marks with
                     nothing in that column.  The other five hold a "+" or the
                     blank the totals row stacks under it, and closing those
                     would unstack the two rows.
                     --mark-spacing is the default and is accepted so a
                     settings file can say which it wants
  --cols N           terminal width, overriding the ancestry walk.  Chiefly
                     for the golden test, which must be deterministic.  "0"
                     means "pretend the width is unknown".
  --usage-source SPEC
                     where to read the plan figures when Claude Code's own
                     payload carries none.  Claude Code's figures are always
                     preferred and this is never consulted while they are
                     there.  Default "auto"; also settable as
                     CLAUDE_USAGE_SOURCE.
                       auto      the first built-in source that is available
                       none      ask nobody; the cached reading is still read
                       claude-usage-tracker
                                 the Claude Usage Tracker menu-bar app
                                 (macOS), read from its UserDefaults store
                       cmd:PATH  any program that prints a reading as JSON on
                                 stdout -- see CommandSource for the contract

options (--mode status):
  --no-column-rules  drop the faint "|" borders between the five right-hand
                     columns, leaving the plain gaps they are painted into.
                     They take no width either way, so this changes nothing
                     but the ink.  --column-rules is the default and is
                     accepted so a settings file can say which it wants.
                     Note the rules are ALREADY off below 160 columns, at an
                     unknown width, and under --no-mark-spacing; this switches
                     them off at the widths that would otherwise carry them.

options (--mode cost):
  --transcript PATH  read this transcript instead of the payload's
  --all              list every prompt as plain text instead of emitting a
                     hook response.  For reading a transcript by hand.
  --prefix TEXT      icon block at the head of the row
  --label TEXT       label after it, bolded at print time
  --color            emit colour (default: plain, which the hook needs)
  --no-totals        suppress the session-totals row
  --no-right-align   print flush left
  --no-account-totals
                     drop the "💳 99٪" half of the 🔋 and 🪫 cells (💳 💯 at
                     a full window), leaving this session's own share of each
  --no-datetime      drop the 📅 date and 🕐 clock cells
  --no-usage-text    drop the "Usage: ..." words from every row label, keeping
                     each row's marker glyph
  --force-newline    always open the message with a blank line.  Taken without
                     asking when the window is too narrow for the eleven
                     columns "Stop says: " costs the first row; this asks for
                     it at every width, because it reads better.
"""


def main(argv: Sequence[str]) -> int:
    # --selftest must be checked BEFORE reading stdin: a live invocation
    # supplies a payload and a self-test does not, so reading first would block
    # forever.
    if "--selftest" in argv:
        return selftest()
    if "-h" in argv or "--help" in argv:
        sys.stdout.write(USAGE)
        return 0
    # Before anything renders: it moves the grid every renderer lays onto.
    set_mark_spacing("--no-mark-spacing" not in argv)
    # Same reason, one layer in: it changes what the five numeric formatters
    # emit, and every field on both readouts is measured from that.
    set_subscript_decimals("--subscript-decimals" in argv)
    # Where a plan reading comes from when the payload carries none.  Set
    # before either mode runs, because the first thing that asks for one is
    # four calls inside a render.
    set_usage_source(_flag(argv, "--usage-source",
                           os.environ.get("CLAUDE_USAGE_SOURCE", "auto")))
    mode = _flag(argv, "--mode", "status")
    if mode == "cost":
        try:
            raw = sys.stdin.read()
        except Exception:
            print("{}")
            return 0
        return main_cost(argv, raw)
    if mode != "status":
        sys.stderr.write("unknown --mode %r\n" % mode)
        sys.stdout.write(USAGE)
        return 2
    return main_status(argv, sys.stdin.read())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
