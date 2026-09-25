"""Shared terminal display, measurement, geometry and formatting.

This module owns glyph tables and mutable display configuration.  Consumers
must reference mutable configuration as ``formatting.NAME``; setters do not
attempt to synchronize copied module globals.
"""
import fcntl
import functools
import os
import re
import struct
import subprocess
import termios
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple


def _pct_num(value):
    """Parse a display percentage without importing a vendor adapter."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

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
# and none carries a variation selector.  docs/glyphs-and-terminals.md for the
# rule and the one-line test for a new glyph.
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
                       # Still naughty by glyph rule 2's literal test, which
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
E_RATE = "\U0001F6EB"  # 🛫  the token RATE — how fast 🧩's total is climbing,
                       # in tokens per second.  On the status line since
                       # 2026-09-13, beside 🎯 in column 2; on the agent
                       # panel's rows a few hours before that, where the
                       # figure is the panel's own samples rather than the
                       # transcript's.  Was Δ, then 🚀 — which is
                       # E_EFF_XHIGH, two cells along — then ✈️ U+2708
                       # U+FE0F for a quarter of an hour, during which a
                       # digit was seen painted over the cell's slash in
                       # JediTerm.  That is the glyph rules' warning made
                       # flesh: a text-presentation character plus a
                       # variation selector, counted two here and advanced
                       # otherwise there.  🛫 is the same picture, single
                       # codepoint, Emoji_Presentation=Yes, Unicode 7, EAW W
                       # — a glyph that can only be drawn one way.
E_COST = "💰"          # cost
E_DIFF = "💾"          # +adds/-removes
# ⚡ U+26A1, the fixed mark of the effort cell — "⚡🏃hi" — left the readout on
# 2026-09-13 with the cell itself: the effort is now the ladder glyph alone,
# against the model spec, "🤖O⁵🏃", as the agent rows had it first.
# 📏 U+1F4CF, the context-window size beside the model, left the readout on
# 2026-09-13 when the model moved to column 3 without it.  The window is a
# constant for the session, and 🧠's percentage is that constant read as a
# level, so it was the one figure on the grid that never said anything twice.
# The reasoning behind the glyph stands for the next one this file needs from
# that region: it was deliberately from the Unicode 6.0 range, because 🪟
# (U+1FA9F) and 🪣 (U+1FAA3) both read better and both come from the Unicode
# 13 block this terminal carries loose metrics for — painting past the two
# columns they advance and leaving debris on redraw.
E_RESET = "🔜"         # marks a duration as time UNTIL: the figure beside it
                       # is a deadline, not a cycle.  A rotation glyph (🔄, ⟳
                       # before it) said only "something recurs here"; this one
                       # names the number, which is what earns its two columns.
E_EFF_LOW = "🐢"       # effort ladder, legible as a picture: the pace of the
E_EFF_MED = "🚶"       # thing doing the work.  Since 2026-09-13 the picture is
E_EFF_HIGH = "🏃"      # the whole cell, against the model spec, on both
E_EFF_XHIGH = "🚀"     # readouts.  All five single-codepoint and EAW-Wide (the
E_EFF_MAX = "🔥"       # 🎚/🎛 sliders are not, and would shift everything to
                       # their right by a column on some terminals).
E_STY = "🎨"           # output style
E_SUM = "\u03a3"       # Greek capital sigma, ONE column — the n-ary summation
                       # U+2211 sits inside the 2190-2BFF range this file
                       # treats as unmeasurable, and the column matters here
E_WAIT = "👤"          # time the session spent waiting for a person
E_WORK = "🤖"          # time it spent answering
E_TOOL = "🔧"          # of that answering, the part spent inside a
                       # tool rather than waiting on a model.  A spanner is
                       # the picture every harness already uses for the
                       # things a model can reach for, and it is the ONE
                       # glyph on the ⌛ row that names a mechanism rather
                       # than a party: 👤 and 🤖 say WHO the seconds
                       # belonged to, 🔧 says what they were spent doing.
                       #
                       # It is read as a subset of the 🤖 beside it, never
                       # as a third slice of Σ — see read_transcript — so
                       # it sits before the pair that does split the age
                       # rather than inside it.
                       #
                       # U+1F527, Unicode 6.0, single codepoint,
                       # Emoji_Presentation=Yes, inside EAW_WIDE — the same
                       # four properties every mark in this grid needs.
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
# 🔜 and Σ do on the same rows.  Column 3 takes the first two of them, since
# 2026-09-16, for the same pair of scopes on a different bill -- see E_READ.
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
                       #
                       # BOTH HEAD A STATUS-LINE ROW AS WELL, since
                       # 2026-09-16: column 3, to the left of the limits,
                       # is the pair read at two scopes -- 🎤 the turn just
                       # answered, 🎮 the session summed -- in the shape of
                       # the column beside it, so the eye that has learned
                       # "🎤 then 🎮, narrow then wide" on column 4 reads
                       # column 3 without being taught.  The cost line
                       # carried the turn's pair alone, in a half-cell it
                       # had spare; the session's had nowhere to go there,
                       # because its totals row spends that half on 💳.
                       # The status line is where the session figure lives,
                       # and it is the one that says whether this SITTING,
                       # not this prompt, is paying to re-read itself.  See
                       # render_cache_share.

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
                       # cell.  Glyph rule 2 rules it out, the same rule that
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
DIM = "\033[2m"                            # dim attribute.  Two jobs, one
                                           # per kind of figure: on the limit
                                           # rows it is scope and urgency (see
                                           # render_limit); on every unbounded
                                           # figure it is MAGNITUDE — dim under
                                           # a fixed cut, bright over it (see
                                           # MAG_TOK).  Never a hue of its own.
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
F_TUP = "\033[38;2;120;200;220m"           # teal        — ▴ input tokens
F_RATE = "\033[38;2;100;225;180m"          # mint        — 🛫 tokens per second.
                                           # Its own hue since 2026-09-13: it
                                           # was F_TUP, the ▴ figure's, and on
                                           # the status line it now sits one
                                           # row under that figure in the same
                                           # field, where one colour said the
                                           # rate WAS the input count.  Mint is
                                           # off every other reading here — a
                                           # green with the blue of the teal
                                           # above it and none of F_GRN's
                                           # yellow, so it does not read as the
                                           # healthy tier of anything, which a
                                           # rate is never in.  F_PUR2, the
                                           # dark purple of the model's second
                                           # field, went with 📏 the same day.
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
# exactly one question here and answers it the same way every frame.  (On
# the rows that carry no percentage, brightness has a second job since
# 2026-09-14 — magnitude against a fixed cut, see MAG_TOK — and the same
# rule holds: the brightness means one thing per figure, every frame.)
#
# It replaced two hue ladders on 2026-08-28.  limit_color tiered the 🔋 row
# green/amber/red on the account's consumption, and F_RST_FAR/MID/NEAR ran the
# countdown down three shades of slate by its unit.  Between them a single row
# could carry three unrelated hues, none of which was the row's own, and the
# colour had to be decoded before it could be read.  git has both if the alarm
# is wanted back on a channel of its own.
F_LIM_SESS = F_GRN                         # the 🔋 5-hour row
F_LIM_WEEK = F_RED                         # the 🪫 weekly row
# Column 3's 📖 and 📝 rows, ONE colour for the pair: the cost line's
# share_half paints these same two figures amber and a quantity keeps its
# ink across the readouts as it keeps its glyph.  Not one hue per row as the
# limits have, because the limit rows' hue answers a question -- which
# window is this? -- that 📖 and 📝 answer by being different pictures; a
# second hue would be a second channel saying what the mark already says.
# What the column distinguishes inside itself rides on brightness, as the
# limit rows' does: see MAG_SHARE_READ.
F_SHARE = F_AMB

# Σ, and Σ only — the ⌛ row's mark, in the colour the 🔜 below it paints
# itself.  MEASURED, not matched by eye: Apple Color Emoji stores 🔜 as a PNG
# in its sbix table, and the alpha-weighted mean of its ink is rgb(76,76,76) at
# every strike from 20ppem to 160 — a flat neutral grey, no hue at all, which
# is not what an emoji named SOON looks like it should be.  L* 32.3.
#
# It is the mark that takes this and not the figure.  On the two limit rows,
# the countdown's figure carries the row's colour and 🔜 paints itself this
# grey; the ⌛ row painted BOTH halves F_PRW and was the one row where the mark
# competed with what it labels.  Now all three read the same way down the
# column — a receding mark, a figure that carries the row — and Σ stacks with
# 🔜 in ink as well as in column.  (The ⌛ row closed the column when this
# was written and has headed it since the evening of 2026-09-16.)
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
COL3_TIGHT_W = 14      # column 3 with MARK_SP empty: a row mark and its
                       # space, then 🎤 and 🎮 each ahead of SHARE_FIG_W,
                       # divided by one space.  Each of its two fields grows
                       # by len(MARK_SP).
COL4_TIGHT_W = 29      # column 4 with MARK_SP empty; each of its four fields
                       # grows by len(MARK_SP).
LINE3_TIGHT = 113      # LINE3_RESERVED at COL3_TIGHT_W + COL4_TIGHT_W, measured
LINE3_RESERVED = 113   # columns the non-pwd segments of line 3 occupy.  It
                       # was 123 until the evening of 2026-09-16, when the
                       # model and the cost went side by side on one row and
                       # their column with them -- seven of cell and a
                       # SEG_GAP gone, one back for the wider row -- 105
                       # until column 3 arrived that morning and took
                       # eighteen -- fourteen of cell and a SEG_GAP -- and 110
                       # before that, while column 4 was 34 wide.  Measured,
                       # not estimated: shrink a column and this follows it
                       # down, or the pwd is held that many columns shorter
                       # than the line can afford whenever the width is
                       # unknown.
PWD_MAX_FALLBACK = MAX_LINE - LINE3_RESERVED

RATE_TICK_S = 5.0      # seconds between two samples of 🧩's total for the
                       # 🛫 rate, and RATE_SAMPLES the samples kept: the
                       # panel's own tick and depth (A_TICK_S, sixteen), so
                       # the status line's 🛫 and an agent row's measure the
                       # same eighty seconds.  See session_rate.
RATE_SAMPLES = 16
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
W_MOD = 4              # the model cell past its icon: the two-character
                       # spec and the effort's glyph, "O⁵🏃".  Held whether
                       # or not the glyph is drawn, so the 💰 beside it does
                       # not move with the effort — see render_model_cost.
VAL_W = 5              # a metric's first value field: "▴4.8M", "200/s",
                       # " 115k"
VAL2_W = 6             # the second field — one wider, because one of them
                       # carries a glyph as well as a figure ("🎯98٪", and
                       # "📏200k" before it).  All three second fields share
                       # it, so output tokens, the cache rate and the context
                       # percentage right-align down the column.
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
                       # FOUR IS SET BY THE SUB-1 READING and by nothing
                       # else: ".01٪" and "100" are the only shapes that
                       # reach it, and the first is three characters of
                       # figure at a magnitude where two would do.  It is the
                       # same four under --subscript-decimals, where the
                       # leading zero comes back and ".01٪" is drawn "0₀₁٪";
                       # the block note there has the sweep.  Three costs a
                       # digit of precision below 1٪, in both forms equally,
                       # and that is the trade — not a glyph, and not a
                       # probe.
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
                       # ⌛ row — a units rule down the column, not three
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
SHARE_FIG_W = 3        # column 3's two fields, 🎤 and 🎮 ahead of a 📖 or 📝
                       # share.  Three, because the figure is a whole percent
                       # of a bill: turn_shares rounds it once and the cost
                       # line's share_half already draws it in three, so this
                       # is the same reading in the same width on both
                       # readouts.  "99٪" is the widest that is spelled; a
                       # share at or over 99.5 is drawn 💯 in the same three,
                       # exactly as LIM_ACCT_W's account figure is.  Not
                       # LIM_FIG_W, though the column is shaped like its
                       # neighbour's: that fourth column exists for ".01٪",
                       # a sub-1 reading these shares never take -- a
                       # fraction of a percent of one prompt's cost is not a
                       # figure anyone acts on, and rounding it to 0 says the
                       # same thing in fewer columns.
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
RULE_MIN = 170         # narrowest row that still gets the rules.  Set against
                       # what line 3 owes before a single name is drawn, which
                       # is measured and not estimated: 105 columns of grid,
                       # RIGHT_MARGIN, MIN_GAP and the where-group's own chrome
                       # come to 123.  At this width the project, path and
                       # branch share the 47 that are left, against the 22
                       # allocate_left will cut them to at the floor — a bit
                       # over twice their minimum.  They are already being
                       # trimmed there and the point is not that they are not;
                       # it is that there is still enough room for the trim to
                       # leave something readable.  Below it the row is closing
                       # on that floor, and one closing on its floor has
                       # nothing to spend on chrome.
                       #
                       # It was 160 until column 3 arrived on 2026-09-16 and
                       # took twenty columns -- sixteen of cell, four of gap
                       # -- and 180 until that evening, when the model and
                       # the cost's column folded into the tokens' and gave
                       # ten back.  The threshold moved by exactly each, so
                       # the 47 it leaves the names is the 47 it left them
                       # before: the argument is about what survives the
                       # trim, and a wider or narrower grid does not change
                       # how much has to.
                       #
                       # Deliberately NOT MAX_LINE, which sits near it and
                       # answers a different question: that is the width to
                       # ASSUME when the terminal will not say, and this is a
                       # width the terminal HAS said.  Binding them would tie
                       # a guess to a measurement.

CTX_DEF = 200000       # context window for ordinary models
CTX_1M = 1000000       # context window for the *-1M-context variants
CACHE_WARN, CACHE_CRIT = 80, 50    # cache hit %: ≤ WARN amber, ≤ CRIT red

# Magnitude, as brightness.  Since 2026-09-14, to Neil's spec: a figure with
# no ceiling of its own is DIM under its cut and full strength at or over it,
# on the status line and the agent rows alike.  A percentage says what high
# is by being a percentage — 100 is the window, and the reader knows it
# without being told — and the hit rate has its tiers; a token count, a rate,
# a cost, a duration and a diff have no such edge, so 841k and 8.4k sat in
# the same ink and the same four columns and a reader had to parse the unit
# to tell one from the other.  Now the ink says it first.
#
# One cut per KIND of quantity, fixed, and the same wherever that quantity is
# drawn — not "high for this session" or "high against the other rows".  A
# relative cut would make the same brightness mean a different thing in every
# frame and on every panel, which is the fault hue was cured of on the limit
# rows (F_LIM_SESS): a signal that has to be decoded is not a signal.  A
# static cut lets an agent row be read against the status line above it and
# against yesterday's, and lets the flip itself be read as an event — ▾ has
# come to a hundred thousand; that agent has run ten minutes.
#
# The cuts are where a reading becomes worth noticing, not unit boundaries:
#   MAG_TOK    a hundred thousand tokens.  Half a standard window, the size at
#              which a context starts to be a compaction question, and the
#              band that divides the light agents from the heavy ones; 🧩's
#              ▴ passes it inside a few turns, ▾ in a long session.
#   MAG_RATE   a thousand a second — the k of "1k/s".  About what the main
#              thread runs at with a full window and a request every ten
#              seconds; between turns it is 0/s.  Full flight against a
#              trickle.
#   MAG_COST   one dollar.  The line a person draws without help; a session
#              crosses it early and an agent that crosses it is a heavy one.
#   MAG_DUR_S  ten minutes, for every duration on the row.  A turn or an
#              agent past ten minutes is the thing a reader looks up for;
#              the session's own age and the split of it pass the cut early
#              and stay bright, which is the right reading of them.
#   MAG_DIFF   a hundred lines, each half of 💾 on its own — the size at
#              which an uncommitted diff is work rather than a tweak.
#
# THE SHARES take a cut of their own kind, since 2026-09-14 and to Neil's
# spec: a share is a percentage, but of a window it will never fill, so 100
# is not the edge a reader holds it against — the question is whether this
# turn, this session, this agent is a real part of the week, and the WEEKLY
# share answers it for both rows at once.  The 5-hour share of the same
# spend is always the larger figure and would put the two rows on different
# sides of the cut for the same turn, so it is not consulted: the 🎤 pair
# dims together and the 🎮 pair dims together, off the week alone.
#   MAG_SHARE_TURN   one percent of the week, for 🎤 on both limit rows.
#   MAG_SHARE_SESS   five percent of the week, for 🎮 on both rows.  A
#                    session under it is one of many; over it, it is the
#                    one the week is going on.
#   MAG_SHARE_AGENT  a fifth of a percent of the week, for an agent's 🔋 🪫
#                    on its panel row.  An agent is a fraction of a turn,
#                    and a turn's cut would dim nearly every row of the
#                    panel; this one leaves the agent that did the turn's
#                    work bright and dims the ones that ran an errand.
#   MAG_SHARE_READ   two thirds of a BILL, for column 3's 🎤 and 🎮 -- each
#                    scope's 📖 and 📝 as a pair, off the 📖 alone, since
#                    2026-09-16.  The one cut here that is a percentage,
#                    and a percentage of a figure the reader can see: it
#                    says whether the transcript, rather than the answer,
#                    is what the money went on.  See cache_dims for the
#                    measurement the number came from.
# A share that could not be derived draws "?" and was dim already.
#
# What it does NOT touch.  The limit percentages themselves (a ceiling of
# their own); 🎯, which is tiered and inverted, and dims its green tier by a
# rule of its own (cache_color); 🧠's percentage
# (its window is its ceiling, and it is the level the row is read for); the
# 🔜 countdown, which reset_dim already dims — the OTHER way, since for a
# time-until it is the small figure that matters; the 5-hour row's 💳, dimmed
# as context and not as a magnitude; and the cost line, which is a different
# readout with a stacking of its own.  See mag_dim.
MAG_TOK = 100000       # 🧩's ▴ and ▾, 🧠's size, both readouts
MAG_RATE = 1000.0      # 🛫 tokens per second
MAG_COST = 1.0         # 💰 dollars
MAG_DUR_S = 600.0      # ⌛ seconds: 🎤 👤 🤖 Σ, and an agent's clock
MAG_DIFF = 100         # 💾 lines, each half on its own
MAG_SHARE_TURN = 1.0   # ٪ of the WEEK: 🎤 on both limit rows
MAG_SHARE_SESS = 5.0   # ٪ of the WEEK: 🎮 on both limit rows
MAG_SHARE_AGENT = 0.2  # ٪ of the WEEK: an agent's 🔋 🪫, as a pair
MAG_SHARE_READ = 67    # ٪ of the BILL that was 📖: column 3's 🎤 and 🎮
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
# hook payload and cannot be measured from here.  docs/layout.md, '"Stop
# says:" and --force-newline', for what these two figures buy — why the rows ship as
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
           "Usage: Compact (last)", "Usage: Agents (other)")
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
E_ROW_AGENTS = "\U0001F465"   # 👥  agent spend the 🎤 row cannot carry.
                              # Emoji_Presentation=Yes and a single code
                              # point, chosen for that.  Measured 2026-09-12
                              # by tests/probe-advance.sh: advance=2 in
                              # JediTerm and in bare Ghostty, neither under
                              # tmux -- a reading, like the other three.
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
# And for agent spend the 🎤 row cannot carry: it landed after the turn that
# spawned it had printed — a background agent, a fork left running, a
# workflow — or on a turn that shares its Stop with a later one and never
# prints a row of its own.  The same late-report case as the compaction,
# from a different direction: see _fold_agents.
C_AGENTS_LABEL = _lab(E_ROW_AGENTS, 3)
# Both labels are twenty columns, deliberately, so the two right-aligned rows
# start and end on the same columns and read as a heading over a heading rather
# than two ragged captions.  Keep them equal if either is reworded.


# ════════════════════════════════════════════════════════════════════════════
# Width tables.
#
# Sorted, inclusive [lo, hi] decimal codepoint ranges the terminal draws in two
# cells.  Everything below U+1100 is narrow, so the table starts there.
#
# THIS IS NOT unicodedata, AND MUST NOT BE REPLACED BY IT.  It began as a
# generated East_Asian_Width table and was then corrected against
# probe-advance.sh; the three corrections, and why unicodedata gets each of
# them wrong, are in docs/glyphs-and-terminals.md under "Why vis_width is not
# a correct Unicode implementation".  Short version: the regional indicators are folded in at
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

        coding-agent-usage-line.py --agent claude --selftest

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
                                               #  unmeasured, bar one glyph:
                                               #  👥 advanced two there,
                                               #  2026-09-12.
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
# 🤖 and 💰 lost the pad for an hour on 2026-09-14 and have it back: the
# value against the icon was asked for and then unasked.  The agent rows'
# 🤖 never had it (render_agent_model), and that row's 💰 borrows this cell
# and follows it.
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
S_RATE = E_RATE + _PAD
S_CACHE = E_CACHE + _PAD
S_COST = E_COST + _PAD
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
# Column 3's two row marks, spaced as 🔋 and 🪫 beside them are: the mark
# names the row and the space is the same one every prefix on these rows
# takes.  Both glyphs measure two like the batteries and need no compensation.
S_READ = E_READ + " "
S_WRITE = E_WRITE + " "
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
#            col 1       col 2            col 3            col 4             col 5
#   row 1    🎨 style    🤖 model 💰 cost  🧠 context       ⌛ elapsed        📅 date
#   row 2    🔀 PR       🧩 tokens        📖 read share    🔋 5-hour limit   🕐 time
#   row 3                🛫 rate 🎯cache  📝 write share   🪫 weekly limit   💾 diff
#
# Column 2 is the session's own figures: what it is running and what it has
# cost on the first row, then two two-value metrics whose fields are the
# same width, so ▴'s figure sits over the token rate and ▾'s over the 🎯.
# The first row is two short cells side by side — 🤖 with the two-character
# model spec and the effort's glyph against it, held to W_MOD whether or
# not the glyph is drawn, then 💰 with three characters of money and a unit
# column — and with a space between them it is one column wider than the
# two-value rows where the icons carry _PAD, and exactly their width where
# they do not; see render_model_cost.  Column 3 is the context over where
# the bill went.  Column 1 holds the two
# segments that can be absent (🎨 off the default style, 🔀 off a PR branch)
# over an empty cell, so their absence leaves a gap at the row's left edge
# rather than a hole between two figures.  Column 5 ends the readout with
# the stamp and the diff.
#
# Rearranged 2026-09-13, to Neil's spec, in steps over one evening.  Until
# then column 2 was the two-value column with the model and its 📏 window on
# its third row, and column 3 read 🎯 💰 ⚡ top to bottom.  The cache rate
# moved in beside the new 🛫 token rate — two readings of the one stream of
# requests, how fast it runs and how much of it the cache served — the cost
# moved up beside the tokens it is the price of, and the model took the
# cost's old cell without the window, which is a constant the 🧠 percentage
# already divides by, and with its name cut to the two characters the agent
# rows use, "O⁵".  The context row went to the bottom, so the rate sits
# directly under the total it is the slope of, and its two fields swapped so
# the size stacks under 🧩's tokens.  The effort cell went, its glyph moving
# against the model spec as on the agent rows, "🤖O⁵🏃".  Then the two
# columns changed places — the short cells first, the two-value column
# against the limits — and last the model and the cost swapped rows, the
# configuration above the spend.
#
# AND AGAIN ON THE EVENING OF 2026-09-16, to Neil's spec, from six columns
# to five.  The model and the cost went side by side on one row, at the top
# of the two-value column, and the tokens and the rate each dropped a row
# under them; their own column, two short cells over a reserved third, went
# with them.  🧠 left the two-value column for the top of the cache-share
# column, over 📖 and 📝, which each dropped a row in turn.  And the ⌛ row
# went to the head of the limits column, over 🔋 and 🪫, which dropped a
# row each as well.  What it costs is the stacking the 2026-09-13
# arrangement bought the context row — its size no longer sits under 🧩's
# tokens — and what it buys is a readout with no reserved cells left: every
# column is three rows deep and every row is full, the first row reads
# what the session is and how long it has run, and the grid is ten columns
# narrower, which RULE_MIN and LINE3_RESERVED follow down.  The rate still
# sits under the total it is the slope of.
#
# COLUMN 3 IS THE CONTEXT OVER THE PAIR THE COST LINE PRINTS IN ITS SPARE
# HALF-CELL.  The pair is read at two scopes -- added 2026-09-16, to Neil's
# spec, to the LEFT of the limits and in their shape.  📖 the share of a
# bill spent re-reading the conversation and 📝 the share spent caching
# what was added, each as 🎤 the turn just answered and 🎮 this session
# summed; see E_READ for what the pair is for and SHARE_FIG_W for the
# field.  Two fields and not column 4's four, because there is no
# account-wide bill to take a share of and no horizon the shares are spent
# against -- the scopes stop where the transcript does.  Over them, since
# that evening, 🧠: the context the re-reading is of, its size first and
# its percentage on the column's right edge, where 🎮's figures end below
# it.  Left of the limits and not right, so the two columns that carry
# 🎤 🎮 sit together and the scope sequence runs once across both -- a
# reader crossing from column 3 to 4 meets the same marks widening the same
# way, with 💳 and 🔜 added, and does not have to learn a second
# arrangement to read the second column.
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
# the ⌛ row, and the three durations stack whichever end they sit
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
RIGHT_GRID = (11, 15, 14, 29, 14) if _PAD else (11, 13, 14, 29, 14)


def set_mark_spacing(on: bool) -> None:
    """Turn the blank between a column-4 mark and its value on or off.

    Four constants move together and none of them may be left behind.  MARK_SP
    is what the renderers print; column 4 in RIGHT_GRID is four columns wider
    with it, one per field, and column 3 two wider, likewise; LINE3_RESERVED
    is what line 3 spends outside the pwd and so follows both columns
    exactly; and PWD_MAX_FALLBACK is derived from that, which is why it is
    recomputed here rather than left at the value it took at import.

    Called once from main() before anything renders.  Rebinding module globals
    is not how this file usually works — nothing else here is settable — and it
    is done this way because the alternative is threading a layout flag through
    every renderer and grid_row down to seg(), for a switch read in four
    places.
    """
    global MARK_SP, RIGHT_GRID, LINE3_RESERVED, PWD_MAX_FALLBACK
    global C_TOK, C_CACHE, C_LIM_TOT, C_SESS
    MARK_SP = " " if on else ""
    col3 = COL3_TIGHT_W + 2 * len(MARK_SP)
    col4 = COL4_TIGHT_W + 4 * len(MARK_SP)
    RIGHT_GRID = ((11, 15, col3, col4, 14) if _PAD
                  else (11, 13, col3, col4, 14))
    LINE3_RESERVED = LINE3_TIGHT + 6 * len(MARK_SP)
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
    two-column glyph — 🎯 inside the rate cell, 🧩 opening the token cell — a
    character count sees a string already at width and adds nothing.  The
    field comes out short, every later cell on that row shifts, and the row
    stops lining up with the ones above and below.  Invisible in testing with
    ASCII, obvious the moment one of those lands in a padded field.

    The token marks are NOT an example of this.  ▴ and ▾ are one column, so
    "▴4M" measures three either way, and ↑ before them was one column too:
    this comment named the arrow for as long as it existed and the example
    never demonstrated the bug.  🎯 and 🧩 are characters that do, and so
    was 📏 while it stood beside the model.

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
# WHY IT IS A SWITCH AND NOT THE FORMAT.  Not the width, which is settled.
# MEASURED 2026-09-08, all ten digits, JediTerm and Ghostty: one column each,
# which is what East Asian Width says of the block and what vis_width has
# always returned.  Worth measuring anyway -- there is a known trap of exactly
# that shape one plane up (see the U+1F900 note beside EAW_WIDE), where the
# standard says Neutral, one terminal agrees and another draws two columns.
#
# What is left is a question no probe can answer: the glyphs are SMALL, these
# are the figures on the row a reader acts on, and whether a subscript 6 still
# reads as a 6 at a terminal's point size is about a font and an eye.  That is
# the reader's to answer by looking, which is what a flag is for.
#
# THE NAME CARRIES THE E_ PREFIX because probe-advance.sh derives what to
# measure by parsing the E_* assignments out of this file, so a glyph named
# anything else is a glyph nobody measures -- which is what these ten were
# until 2026-09-08, sitting one rename away from the probe.
#
# NOTHING IS RECLAIMED, AND NOTHING WAS EVER GOING TO BE.  This block used to
# promise that narrowing LIM_FIG_W from 4 to 3 was "the payoff, and it comes
# after the probe".  The probe came; the payoff was never there.  What sets
# that field is the widest thing that can land in it, and swept across every
# hundredth of a percent the widest is FOUR columns in both forms and for the
# same reason:
#
#     off  ".01٪"      three characters of figure, then the unit
#     on   "0₀₁٪"      the leading zero comes back, so three again
#
# Subscripts narrow the readings at or above 1٪ -- "4.1٪" to "4₁٪" -- and
# those were never the widest.  The sub-1 reading is, in both forms, and the
# leading zero that makes it so is deliberate and stays (below).  So the
# switch buys leading pad on the middle magnitudes and no column anywhere,
# which is exactly what the six widths of golden files already showed and
# what this comment talked past.
#
# EVERY FIELD KEEPS THE WIDTH IT HAD, so a shorter figure gets one more column
# of leading pad and the grid cannot tear on the switch.  That was insurance
# against the terminal drawing these two columns wide -- the damage would show
# as a figure overrunning its own cell rather than as a whole row shifted,
# which is the difference between a diagnosis and a mystery.  The probe says
# one column, so the insurance was never claimed.
#
# THE LEADING ZERO STAYS, where limit_pct drops it.  ".38" is unambiguous
# because the point marks the figure as a fraction; "₃₈" is not -- it is the
# same glyph sequence a reader would take for 38 in a smaller font.  So the
# zero comes back for this form, which means a sub-1 reading saves nothing.
# Neil's call, and the right one: a column is worth less than the difference
# between a third of a point and thirty-eight of them.
E_SUB_DIGITS = "₀₁₂₃₄₅₆₇₈₉"
# The superscript digits, for the model's major version — "O⁵", "H⁴" — on the
# agent rows and the status line both, since 2026-09-13 and to Neil's spec.
# The same shape of risk as the subscripts above, and the same reading to go
# on: six of the ten are East_Asian_Width Neutral and four — ¹ ² ³ ⁴ — are
# Ambiguous, exactly the split of the subscript block, which both terminals
# advanced one column on 2026-09-08.  ¹ ² ³ are Latin-1 rather than
# U+2070-2079 and the four Opus, Sonnet, Haiku and Fable versions in the
# catalogue land on ⁴ and ⁵, so one Ambiguous digit is in live use.  None of
# these has been probed; see "Open issues" in docs/development.md.  vis_width
# calls them one, as it does every codepoint outside its wide tables.
E_SUP_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
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


def rate_fig(rate: float) -> str:
    """The token rate in three characters where three will hold it.

    humanize's blank unit under a thousand is dropped: the unit of this
    field is the "/s", and "849 /s" reads as a typo.  Above a thousand
    humanize keeps a decimal while the mantissa is under ten — "1.2k" — and
    that is four; here the cell is three, so the figure is rounded to the
    unit instead, "1k", "2k", and 9.9k rounds up to "10k".  "150k" is four
    with no decimal to give and stays four: see A_RATE_W, and
    VAL_W on the status line, where the "/s" makes the five.
    """
    s = humanize(rate).rstrip()
    if vis_width(s) > 3:
        for lim, unit in SI_UNITS:
            if rate >= lim:
                s = "%.0f%s" % (rate / lim, unit)
                break
    return s


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


def money_fig(c: float) -> str:
    """A dollar figure as three characters and a unit column — humanize's
    shape, for the status line's 💰: "0.4 ", "12 ", "115 ", "1.2k", "12k ".

    money_fmt above spends its four columns on digits — "12.3", "115" — and
    the cost line keeps it, because there a decimal point has a column
    reserved to stack in.  On the status line the cell sits in a column of
    figures that all end on a unit — ▴2.7M, 841k, 115k two columns over —
    and a money figure that ended on a digit in the unit's column read as a
    thousand times itself for as long as it took to see there was no k.
    Since 2026-09-14, to Neil's spec, the unit column is held: a blank under
    a thousand dollars, as humanize holds it under a thousand tokens and for
    the reason given there, so the digits stack under digits and the k, when
    it comes, lands where every other k on the readout does.

    One decimal while the figure is under ten, none from ten to a thousand,
    then humanize's own ladder: the cuts sit where the format below would
    round into a fourth character, as both ladders' do.
    """
    if c >= K - K / 2000.0:
        return humanize(c)
    return ("%.0f" % c if c >= 9.95 else "%.1f" % c) + " "


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


def mag_dim(v: Optional[float], cut: float) -> str:
    """DIM for a figure under its magnitude cut; nothing at or over it.

    Prefixed to the figure's colour the way render_limit builds `tcol`, and
    reset with the figure, so a dim first field never dims the second: DIM
    reaches a pictograph where a foreground colour does not, and would take
    the 🎯 inside the rate cell's second field with it.  None — no reading —
    is left alone; the caller blanks or omits those itself.  The cuts and
    the reasoning are at MAG_TOK.
    """
    return "" if v is None or v >= cut else DIM


def share_dims(week_turn: str, week_sess: str) -> Tuple[bool, bool]:
    """Whether the 🎤 and 🎮 shares dim, for BOTH limit rows, off the weekly
    figures alone: the turn under MAG_SHARE_TURN of the week, the session
    under MAG_SHARE_SESS.  A share that is missing is not dimmed here — it
    draws "?" and render_limit's fig dims that itself."""
    t, s = _pct_num(week_turn) if week_turn else None, \
        _pct_num(week_sess) if week_sess else None
    return (t is not None and t < MAG_SHARE_TURN,
            s is not None and s < MAG_SHARE_SESS)


def cache_dims(turn_read: Optional[int], sess_read: Optional[int]
               ) -> Tuple[bool, bool]:
    """Whether column 3's 🎤 and 🎮 dim, each scope's 📖 📝 as a pair, off the
    📖 share alone: dim under MAG_SHARE_READ, full strength at or over it.

    Off 📖 and not 📝, because 📖 is the figure the column exists for -- the
    part of the bill /compact can reclaim -- and 📝 is its complement's
    context.  A pair rather than each figure on its own for the reason the
    limit rows' 🎤 🎮 flip together off the week (share_dims): two figures
    about one scope on different sides of a cut would read as two events
    where there is one.  A share that is missing is not dimmed here -- it
    draws "?" and render_cache_share's fig dims that itself.

    TWO THIRDS, and measured rather than argued for.  On 2026-09-16, over
    the 275 most recent sessions on the machine this was written on (6,002
    turns, read through read_turns and priced by turn_shares): the median
    turn spends 73٪ of its bill re-reading and the median session 56٪ --
    far above the "8٪ to 57٪" E_READ's note recorded when the cost line's
    cell was built, and enough that re-reading is normally the MAJORITY of
    what a prompt costs.  So a cut at the half lights three quarters of
    everything (78٪ of turns, 60٪ of sessions) and brightness stops being a
    signal.  At 67٪ it lights 60٪ of turns and 26٪ of sessions -- a bright
    🎤 and a dim one are both ordinary, and a bright 🎮 is news -- and it
    divides by the thing that matters: turns at or over it sat on a median
    context of 311k, turns under it on 137k.  75٪ was the other candidate
    and lights 11٪ of sessions, which makes the 🎮 pair a figure that is
    dim whatever it says.  Two thirds also has a reading a person can say
    aloud: two dollars in three went on the transcript, not the answer.

    One number for both scopes, deliberately.  The scopes are the same
    quantity at two ranges, and the limit rows' two cuts (MAG_SHARE_TURN,
    MAG_SHARE_SESS) differ because a turn and a session are different
    fractions of a WEEK; here the denominator is each scope's own bill, so
    the same share means the same thing at either.
    """
    return (turn_read is not None and turn_read < MAG_SHARE_READ,
            sess_read is not None and sess_read < MAG_SHARE_READ)


def cache_color(p: int) -> str:
    """Colour the cache-hit rate.  INVERTED against the other tiers: a high
    number is the healthy one.  A collapse means something invalidated the
    cached prefix and the same work now bills about ten times over.

    The green tier is DIM as well as green, at Neil's call of 2026-09-14: a
    high hit rate is the state nothing has to be done about, and the figure
    that asks for nothing should not be the one the eye lands on.  Amber and
    red are the tiers that mean something happened, and stay full strength.
    The same reading as the magnitude cuts (MAG_TOK) from the other side:
    there the small figure is the quiet one, here the large one is.  Callers
    put the 🎯 ahead of this, outside it, so the DIM reaches the figure and
    not the mark — as mag_dim's callers do."""
    if p <= CACHE_CRIT:
        return F_RED
    if p <= CACHE_WARN:
        return F_AMB
    return DIM + F_GRN


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
