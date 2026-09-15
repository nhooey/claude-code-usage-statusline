"""Pure Claude status-line renderers.

All data and precomputed state arrive as arguments.  This module deliberately
does not inspect transcripts, source caches, hook stdin/stdout, or rate state.
"""
import os
from typing import Optional

from . import formatting as fmt
from .formatting import *
from .claude_records import Git, Limits, Payload, Transcript

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

    Each half is bright from MAG_TOK up and dim under it, arrow included —
    the arrow is the figure's, not the cell's — and each is reset on its
    own, so a dim ▴ never dims the ▾ after it.
    """
    if up is None:
        return ""
    return "%s%s%s%s%s%s%s" % (
        S_TOK, mag_dim(up, MAG_TOK) + F_TUP,
        pad_val(VAL_W, E_UP + pad_val(4, humanize(up)), True), R,
        mag_dim(down, MAG_TOK) + F_TDN,
        pad_val(VAL2_W, E_DOWN + pad_val(4, humanize(down))), R)


def render_rate_cache(rate: Optional[float], cache_pct: int) -> str:
    """🛫 the token rate and 🎯 the cache hit rate in one cell: "🛫200/s 🎯98٪".

    Two readings of the one stream of requests — how fast it is running and
    how much of each request the cache served — and the column-2 shape: the
    mark, a VAL_W first field, a VAL2_W second, so "200/s" stacks under ▴'s
    figure and the 🎯 with its percentage right-aligns under ▾'s.  The
    cache figure carries its own mark inside the second field the way the
    window carried 📏, because the field is a different quantity from the
    first and a reader should not have to know the layout to tell which.

    The rate is session_rate's and the figure is rate_fig's three characters
    with the "/s" that makes them five: the same cell as the agent rows',
    for the same quantity read on the main thread.  Blank — the mark still
    drawn, the field empty — while there is no slope to report, which is the
    first tick of a session and nothing else; a rate of nothing between
    turns is "  0/s" and is meant to be read.

    Nothing at all when there has been no usage, as the cache cell was on
    its own: no requests is no rate and no hit rate, and a cell of two blank
    fields would be a row saying something where there is nothing to say.

    The rate dims under MAG_RATE — a trickle against full flight — and is
    reset before the 🎯, which keeps its tiers and must not inherit the DIM.
    The tier's colour goes on after the 🎯 rather than around it: the green
    tier carries a DIM of its own (cache_color), and that is for the figure,
    not the mark — the same shape as every magnitude cell.
    """
    if cache_pct is None or cache_pct < 0:
        return ""
    fig = "" if rate is None else rate_fig(rate) + "/s"
    return "%s%s%s%s%s" % (
        S_RATE, mag_dim(rate, MAG_RATE) + F_RATE, pad_val(VAL_W, fig), R,
        pad_val(VAL2_W, E_CACHE + cache_color(cache_pct)
                + pad_val(3, pct2(cache_pct) + E_PCT) + R))


def render_ctx(ctx_pct: Optional[int], ctx_tokens: int) -> str:
    """Live context occupancy, as a size and then a percentage — "🧠 115k   11٪".

    The window itself is deliberately not printed: it is constant for the
    session, so of the three possible numbers it is the one that never says
    anything twice — and it was 🤖's second field until 2026-09-13.

    Size first, percentage second, since the evening of 2026-09-13 and to
    Neil's spec; this cell has now been turned round twice.  The order it
    replaces put the percentage first, on the argument that it is the figure
    the row is read for and the size its qualifier, and turned the prompt-cost
    row round to match on the same day.  This order puts the size under 🧩's
    tokens two rows up — figure under figure, with the 🛫 rate between them
    — and the percentage on the column's right edge, where 🎯's sits on the
    row above.  The cost row was NOT turned back with it: it still reads
    "🧠+ 8.0٪ + 16k", the change in the level before the change in the size,
    and the two readouts now differ in order.  The argument for one order
    across both — a reader moving between them should not have to work out
    which field is which — stands as it did; it is outweighed here by the
    stacking, and the cost line's two rows stack with each other regardless.

    One hue across both fields, and it is the percentage's.  The brightness
    is not: the size dims under MAG_TOK like every other token count on the
    two readouts, and the percentage stays bright at any value, because its
    window is its ceiling and a level with a ceiling needs no cut to say what
    high is — the case MAG_TOK makes for the limit rows.  This docstring
    argued until 2026-09-14 that the two are one quantity said twice, so
    dimming either half would rank a figure against itself; the reply is
    that they are not ranked against each other but each against its own
    kind — the size against the 🧩 figures two rows up that it stacks under,
    the percentage against nothing.  115k of a 1M window reads bright-dim
    and says exactly that: a lot of context, and a small part of the room.

    Always pink rather than tiered, so an approaching window limit reads off
    the number rather than the colour.  It also drops the 99 clamp the other
    percentages keep, which matters here and nowhere else: a context at 99٪ and
    one at 100٪ are different situations, where a plan limit at either is the
    same news.
    """
    if ctx_pct is None:
        return ""
    return "%s%s%s%s%s%s%s" % (
        S_CTX, mag_dim(ctx_tokens, MAG_TOK) + F_PNK,
        pad_val(VAL_W, humanize(ctx_tokens)), R,
        F_PNK, pad_val(VAL2_W, "%d%s" % (ctx_pct, E_PCT)), R)


def render_cost(cost_usd: str) -> str:
    """The session cost, "💰115 ": money_fig's three characters and a unit
    column.  Always yellow — no value tiering — and
    dim under MAG_COST, a dollar; the agent rows borrow the cell, so a heavy
    agent's 💰 is the bright one down the panel."""
    if not cost_usd or cost_usd == "null":
        return ""
    try:
        c = float(cost_usd)
    except ValueError:
        return ""
    return "%s%s%s%s" % (S_COST, mag_dim(c, MAG_COST) + F_YEL,
                         pad_val(4, money_fig(c)), R)


def render_limit(emoji: str, pct_s: str, delta: str, resets: str,
                 turn: str = "", colour: str = F_LIM_SESS,
                 dim_total: bool = False,
                 now: Optional[float] = None,
                 dim_turn: bool = False, dim_session: bool = False) -> str:
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
    column-4 note above fmt.RIGHT_GRID.

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
    scopes this session owns are bright when they are a real part of the
    week and dim when they are not (`dim_turn`, `dim_session` — the caller
    decides, off the WEEKLY shares, so the two rows agree; see
    MAG_SHARE_TURN), the account total dims where it is context rather than
    news, and the countdown dims unless it is inside the hour.  Hue
    therefore answers "which window is this?" and nothing else, which is
    the one question it can answer from across a screen.

    It tiered green/amber/red on the account figure until 2026-08-28, through
    limit_color.  Three hues, none of them the row's own, moving on a
    quantity that already sits in plain digits two fields to the left; and
    the 🪫 row was pinned red regardless, so the same colour meant "weekly"
    on one row and "over 90٪" on the other.  See F_LIM_SESS.
    """
    if not pct_s:
        return ""
    pct_v = fmt._pct_num(pct_s)
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
        rst = "%s%s%s%s%s%s" % (S_RESET, fmt.MARK_SP, reset_dim(d), colour,
                                pad_val(RST_W - vis_width(S_RESET), d), R)
    else:
        rst = " " * (RST_W + len(fmt.MARK_SP))

    def fig(mark: str, v: Optional[float], col: str,
            w: int = LIM_FIG_W, digits: int = 3) -> str:
        # No transcript to sum or no calibration to divide by: say so rather
        # than showing a zero, which would read as "this consumed nothing".
        # See _with_shares.
        if v is None:
            return "%s%s%s%s%s" % (mark, fmt.MARK_SP, DIM + F_CRM,
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
            return "%s%s%s%s%s" % (mark, fmt.MARK_SP, col,
                                   pad_val(w, E_HUNDRED + E_PCT), R)
        return "%s%s%s%s%s" % (mark, fmt.MARK_SP, col,
                               pad_val(w, limit_pct(v, digits) + E_PCT), R)

    # The 5-hour row dims its account figure, leaving the two this session
    # owns at full strength: those are what a reader can act on and the
    # account total is context for them.  The weekly row keeps all three
    # bright, because by then the total IS the news.
    tcol = DIM + colour if dim_total else colour
    # The two shares dim on the caller's word, not on their own figure: the
    # 5-hour row's share is always the larger of the pair and would flip on
    # a different turn than the weekly row's.  See MAG_SHARE_TURN.
    return "%s%s" % (emoji, " ".join((
        fig(E_TURN, fmt._pct_num(turn) if turn else None,
            DIM + colour if dim_turn else colour),
        fig(E_SESSION, fmt._pct_num(delta) if delta else None,
            DIM + colour if dim_session else colour),
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

    Each half dims under MAG_DIFF on its own count, sign included: a hundred
    lines added is work sitting uncommitted, and the brightness says so
    before the figure is read.  An unparseable count draws "?" at full
    strength, as the limit rows' "?" does — the question is not small.
    """
    if not added:
        return ""

    def n(v: str) -> Optional[int]:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    def half(sign: str, v: Optional[int], col: str) -> str:
        # rstrip drops humanize's unit column; see the note above for why
        # this cell is the exception.  "3.4k" is unaffected — it has no
        # trailing blank to lose — so only the sub-1000 case moves, and it
        # moves one column right, onto the margin.
        fig = "?" if v is None else humanize(v).rstrip()
        return "%s%s%s%s" % (mag_dim(v, MAG_DIFF) + col, sign,
                             pad_val(4, fig), R)

    return "%s%s %s" % (S_DIFF, half("+", n(added), F_GRN),
                        half("-", n(removed), F_RED))


def render_pr(pr: str) -> str:
    if not pr or pr == "null":
        return ""
    return "%s%s%s%s" % (S_PR, F_CYN, pad_val(4, pr), R)


def model_label(model_id: str) -> str:
    """A display name from a model id or alias, for short_model.

    The panel hands over what the Agent tool was given — "haiku", "sonnet",
    or a full id like "claude-opus-5[1m]" — and the transcript has the id the
    API answered with, "claude-haiku-4-5-20251001".  The status line's
    payload carries a display name ("Opus 5") and short_model is written for
    that shape, so this makes one: family from the id, version from the
    dotted digits after it, never the 8-digit date.
    """
    low = (model_id or "").lower()
    fam = next((f for f in MODEL_FAMILIES if f.lower() in low), "")
    if not fam:
        return model_id[:VAL_W]
    tail = low.split(fam.lower(), 1)[1]
    # Up to two short runs of digits right after the family — "5", "4-5" —
    # and nothing that runs on into more digits, which is the date stamp.
    m = re.match(r"[-_. ]*(\d{1,3})(?:[-_.](\d{1,3}))?(?!\d)", tail)
    if not m:
        return fam
    return fam + " " + ".".join(g for g in m.groups() if g)


def model_spec(model_id: str) -> str:
    """Two terminal cells: family initial and superscript major version."""
    label = model_label(model_id)
    if not label:
        return ""
    fam, _, ver = label.partition(" ")
    if ver:
        d = ver[:1]
        return fam[:1] + (E_SUP_DIGITS[int(d)] if d.isdigit() else d)
    return fam[:2]


def render_model(model: str, effort: str = "") -> str:
    """🤖, the two-character model spec and the effort's glyph — "🤖O⁵🏃".

    Three changes on 2026-09-13, all to Neil's spec.  The context window went:
    "📏1M" stood in a second field beside the name for as long as the model
    had column 2's width, and the window is a constant for the session that
    🧠's percentage already reads as a level, so of the three numbers this
    row could print about it this was the one that never said anything
    twice.  It is still read — ctx_window_for, for the percentage and for
    the Stop hook via publish_ctx_window — and simply not drawn.  And the
    name went from short_model's spelled family, "Opus5", to model_spec's
    initial and superscript major version, "O⁵", the form the agent rows had
    taken that morning: one readout, one way of naming a model, and a cell
    that fits the column 💰 set.  The payload's display name goes in as it
    is; model_label reads either that or an id.  And the effort joined it:
    "⚡🏃hi" had a cell of its own in this column — the fixed mark so the
    segment is found by icon, the glyph as a picture of pace, the word to
    tell "medium" from "max" — and now the glyph alone stands against the
    spec, as render_agent_model had it since the morning.  What that costs
    is the word: 🚶 and 🔥 are the two levels it told apart, and a reader
    who cannot tell them has the glyph ladder at E_EFF_LOW.  What it buys is
    a cell of the column's exact width, six, and a row of it back.
    """
    if not model:
        return ""
    cell = "%s%s%s%s" % (S_MOD, F_PUR, pad_val(2, model_spec(model)), R)
    if effort and effort != "null":
        cell += effort_glyph(effort)
    return cell


def effort_glyph(effort: str) -> str:
    """The level's glyph on the ladder; the middle of it for a level not on
    it.  The two-letter label and the tiered colour that stood beside the
    glyph in the old ⚡ cell went with that cell on 2026-09-13 — an emoji
    takes no colour, so the ladder's intensity is the picture alone."""
    return {
        "low": E_EFF_LOW,
        "medium": E_EFF_MED,
        "high": E_EFF_HIGH,
        "xhigh": E_EFF_XHIGH,
        "max": E_EFF_MAX,
    }.get(effort, E_EFF_MED)


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

    Every figure on the row dims under MAG_DUR_S, ten minutes, and each on
    its own: the turn is the field that flips in practice — a long turn is
    the thing this row is looked at for — while Σ and its split pass the cut
    in the session's first minutes and stay bright.  The 🔜 directly above
    dims the other way, and deliberately: for a time-until it is the SMALL
    figure that matters (reset_dim).  The two rows agree on what bright
    means — the figure worth looking up for — and differ on which end of
    the scale that is, because the scales run opposite ways.
    """
    if not start_s:
        return ""
    t = time.time() if now is None else now
    age = t - start_s if t > start_s else 0.0
    idle = age - busy_s if age > busy_s else 0.0

    def fig(mark: str, v: float, w: int = LIM_FIG_W) -> str:
        return "%s%s%s%s%s" % (mark, fmt.MARK_SP, mag_dim(v, MAG_DUR_S) + F_PRW,
                               pad_val(w, dur_fmt(v, 2)), R)

    turn = (fig(E_TURN, turn_s) if turn_s
            else " " * (vis_width(E_TURN) + len(fmt.MARK_SP) + LIM_FIG_W))
    return "%s%s %s %s %s%s%s%s%s%s%s" % (
        S_IDLE, turn, fig(E_WAIT, idle), fig(E_WORK, busy_s, LIM_ACCT_W),
        F_SUM, S_SUM, R, fmt.MARK_SP,
        mag_dim(age, MAG_DUR_S) + F_PRW,
        pad_val(RST_W - vis_width(S_SUM), dur_fmt(age)), R)


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
                  turn_s: float = 0.0, rules: bool = True,
                  ctx_window: int = 0, rate: Optional[float] = None) -> str:
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

    # Both rows' 🎤 and 🎮 dim off the WEEKLY shares, so the pair flips
    # together.  See MAG_SHARE_TURN.
    dim_turn, dim_sess = share_dims(lim.weekly_turn, lim.weekly_share)
    usage = grid_row((
        render_style(pay.output_style),
        render_model(pay.model, pay.effort),
        render_tokens(tr.tok_up, tr.tok_down),
        render_limit(S_SESS, lim.session_pct, lim.session_share,
                     lim.session_reset, lim.session_turn, F_LIM_SESS, True,
                     now, dim_turn, dim_sess),
        render_date(now),
    ), rule=rule)
    limits_row = grid_row((
        render_pr(pay.pr_number),
        render_cost(pay.cost_usd),
        render_rate_cache(rate, tr.cache_pct),
        render_limit(S_WEEK, lim.weekly_pct, lim.weekly_share,
                     lim.weekly_reset, lim.weekly_turn, F_LIM_WEEK, False,
                     now, dim_turn, dim_sess),
        render_time(now),
    ), rule=rule)
    right = grid_row((
        "",
        "",
        render_ctx(ctx_pct, tr.ctx_tokens),
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
            proj_display, fit_path(pwd_display, fmt.PWD_MAX_FALLBACK),
            branch_display, git) + " " * MIN_GAP + right

    return "%s\n%s\n%s%s%s\n" % (row1, row2, LINE_CLEAR, line3, EOL_CLEAR)
