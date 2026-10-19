"""Pure layout for Claude's prepared Stop-cost report.

The caller supplies turns plus already-prepared window, accounting and plan
totals: each turn's cost and window shares are worked out before drawing,
and only read here.  This module deliberately does not read transcripts,
caches, account sources, clocks or process state.  The metric-group builders
are arguments, so the groups claude.py draws stay where their notes are.

Labels, tags and groups are all spans (see spans.py), joined into escape
codes once, where render_cost_line hands back the finished rows.
"""
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .formatting import (C_CHROME_CONT, C_CHROME_LEFT, C_MIN_GAP,
                         C_RIGHT_MARGIN, E_TURN_ID, E_TURN_PAST,
                         TURN_ID_HEX, fit_cols, trunc, vis_width)
from .spans import (Span, SpanLike, indent, join, lstrip, rstrip, spans,
                    width)

# A metric group, a label and the chrome its row sits beside.
Row = Tuple[List[Span], str, int]


class CostOpts(NamedTuple):
    prefix: str
    label: str
    totals_label: str
    cols: Optional[int]
    colour: bool
    totals: bool
    right_align: bool
    session_id: str = ""
    compact_label: str = ""
    agents_label: str = ""
    account_totals: bool = True
    stamps: bool = True
    force_newline: bool = False


def ink_colour(colour: bool, name: str) -> Optional[str]:
    """`name`, "F_CRM", where the receipt is in colour (--color), and None,
    the terminal's own, where it is not."""
    return name if colour else None


def painted(prefix: str, value: str) -> List[Span]:
    """The row's prefix, then its label in bold: "P " and a bold "A"."""
    out = spans(prefix)
    if value:
        out += ([Span(" ")] if out else []) + [Span(value, bold=True)]
    return out


def place(group: SpanLike, opts: CostOpts, label: str,
          chrome: int) -> List[Span]:
    """Place one finished cost row without touching terminal/process state."""
    group = spans(group)
    if opts.cols and opts.right_align:
        room = opts.cols - chrome - C_RIGHT_MARGIN - width(group)
        plain = " ".join(part for part in (opts.prefix, label) if part)
        pad = room - vis_width(plain) - C_MIN_GAP
        if pad >= 0:
            return spans([" " * pad, painted(opts.prefix, label),
                          " " * C_MIN_GAP, group])
        keep = trunc(label, max(0, room - vis_width(opts.prefix) - 1 - C_MIN_GAP))
        head = painted(opts.prefix, keep) if keep else spans(opts.prefix)
        return spans([head, " " * C_MIN_GAP, group])
    head = painted(opts.prefix, label)
    return spans([head, " ", group]) if head else group


def stack_metrics(rows: Sequence[Row],
                  opts: CostOpts) -> Tuple[int, int, int]:
    """Return the shared tight/room/base geometry for a cost-row block."""
    tight = max(chrome + width(group) for group, _, chrome in rows)
    room = opts.cols - C_RIGHT_MARGIN - tight
    widest = max(vis_width(" ".join(part for part in (opts.prefix, label) if part))
                 for _, label, _ in rows)
    return tight, room, room - widest - C_MIN_GAP


def place_stacked(rows: Sequence[Row], opts: CostOpts) -> List[List[Span]]:
    """Place several rows as one aligned block."""
    if not (opts.cols and opts.right_align):
        return [rstrip(lstrip([painted(opts.prefix, label), " ", group]))
                if painted(opts.prefix, label) else spans(group)
                for group, label, _ in rows]
    tight, room, base = stack_metrics(rows, opts)
    output = []
    for group, label, chrome in rows:
        shift = tight - chrome - width(group)
        if base >= 0:
            output.append(spans([" " * (base + shift),
                                 painted(opts.prefix, label),
                                 " " * C_MIN_GAP, group]))
            continue
        keep = trunc(label, max(0, room - vis_width(opts.prefix) - 1 - C_MIN_GAP))
        head = painted(opts.prefix, keep) if keep else spans(opts.prefix)
        output.append(spans([" " * shift, head, " " * C_MIN_GAP, group]))
    return output


def turn_tag(turn: object, colour: bool) -> List[Span]:
    """🔺🔖 8f37748e #12: the turn the 🎤 row bills, by the head of its
    promptId and Claude Code's turn index.  Each half is drawn only where the
    transcript wrote it, and the tag not at all where it wrote neither."""
    idx = getattr(turn, "turn_index", None)
    pid = getattr(turn, "prompt_id", "")
    parts = ([pid[:TURN_ID_HEX]] if pid else []) + (
        ["#%d" % idx] if idx is not None else [])
    if not parts:
        return []
    return [Span(E_TURN_PAST + E_TURN_ID + " "),
            Span(" ".join(parts), ink_colour(colour, "F_CRM"))]


# The agent id on a 👥 row, cut as the agent panel cuts it, and the fewest
# columns of its name worth drawing after it.
AGENT_ID_W, AGENT_NAME_MIN = 10, 6


def agent_tag(turn: object, colour: bool, room: int) -> List[Span]:
    """The name and id of the agent a 👥 row bills, in at most `room`
    columns: as much of the name as fits, then the id padded to AGENT_ID_W,
    so the ids of a block of 👥 rows stand in one column beside their 📊s.
    The id whole or nothing."""
    aid = getattr(turn, "agent_id", "")
    if not aid or room < AGENT_ID_W:
        return []
    aid = [Span(fit_cols(aid, AGENT_ID_W), ink_colour(colour, "F_CRM"))]
    aid.append(Span(" " * (AGENT_ID_W - width(aid))))
    name = getattr(turn, "agent_name", "")
    left = room - AGENT_ID_W - 1
    name = trunc(name, left) if name and left >= AGENT_NAME_MIN else ""
    return spans([name + " " if name else "", aid])


# One turn's accounting, or the session's: its cost and its shares, as the
# figures document's `accounting` carries them.
Accounting = Dict[str, Optional[float]]


def render_cost_line(
        turns: Sequence[object], opts: CostOpts, win: int,
        accounting: Dict[str, object],
        plan_totals: Dict[str, Optional[float]],
        now: Optional[float],
        cost_group: Callable[[object, Accounting, int, bool,
                              Optional[float], bool, bool], List[Span]],
        totals_group: Callable[[Sequence[object], Dict[str, Optional[float]],
                                int, bool, Optional[float], Accounting,
                                bool, bool], List[Span]]) -> str:
    """Lay out prepared Claude cost rows; all accounting is supplied by caller.

    ``accounting`` is the figures document's: ``turns``, one per turn in
    order, and ``session``.  ``cost_group`` and ``totals_group`` are pure
    builders that draw a group from a turn and its accounting, so nothing
    here divides by the plan or reaches caches or transcript files.
    """
    if not turns:
        return opts.prefix + " (no prompts recorded yet)"
    colour = opts.colour
    per_turn = accounting["turns"]
    prompts = [index for index, turn in enumerate(turns)
               if getattr(turn, "calls", None) and not getattr(turn, "compact", False)
               and not getattr(turn, "agent", False)]
    last_index = prompts[-1] if prompts else len(turns) - 1
    previous = prompts[-2] if len(prompts) > 1 else -1
    last = turns[last_index]
    # By index, so each row's group reads its own turn's accounting.
    if any(getattr(turn, "reported", False) for turn in turns):
        pending = [index for index, turn in enumerate(turns)
                   if (getattr(turn, "compact", False) and not getattr(turn, "reported", False))
                   or getattr(turn, "agent", False)]
    else:
        pending = [index for index in range(previous + 1, last_index)
                   if getattr(turns[index], "compact", False)] + [
                       index for index, turn in enumerate(turns)
                       if getattr(turn, "agent", False)]
        pending.sort(key=lambda index: getattr(turns[index], "ts", ""))
    acct, stamps = opts.account_totals, opts.stamps
    spec = [(cost_group(turns[at], per_turn[at], win, colour, now, acct,
                        stamps),
             opts.agents_label if getattr(turns[at], "agent", False)
             else opts.compact_label,
             C_CHROME_LEFT if index == 0 else C_CHROME_CONT)
            for index, at in enumerate(pending)]
    spec.append((cost_group(last, per_turn[last_index], win, colour, now,
                            acct, stamps),
                 opts.compact_label if getattr(last, "compact", False) else opts.label,
                 C_CHROME_LEFT if not spec else C_CHROME_CONT))
    if opts.totals:
        spec.append((totals_group(turns, plan_totals, win, colour, now,
                                  accounting["session"], acct, stamps),
                     opts.totals_label, C_CHROME_CONT))
    lead_newline = opts.force_newline
    if not lead_newline and opts.cols and opts.right_align:
        flat = [(group, label, C_CHROME_CONT) for group, label, _ in spec]
        lead_newline = stack_metrics(spec, opts)[2] < 0 <= stack_metrics(flat, opts)[2]
    lead = len(pending) + (1 if getattr(last, "compact", False) else 0)

    def drawn(rows: Sequence[SpanLike], newline: bool = lead_newline) -> str:
        # The one place the receipt's spans become escape codes.
        return (("\n" if newline else "")
                + "\n".join(join(row, runs=True) for row in rows))

    def laid_out(own_line: bool) -> List[List[Span]]:
        flat = spec
        if own_line:
            flat = [(group, label, C_CHROME_CONT) for group, label, _ in spec]
        rows = [rstrip(row) for row in place_stacked(flat, opts)]
        # Each 👥 row bills one agent, and names it in its pad, C_MIN_GAP
        # left of its 📊 the way the turn tag sits on the 🎤 row.
        for index, at in enumerate(pending):
            turn = turns[at]
            if not getattr(turn, "agent", False):
                continue
            row = rows[index]
            if not (opts.cols and opts.right_align):
                # Flush left there is no pad, and no column to keep: the
                # tag leads the row.
                tag = agent_tag(turn, colour, AGENT_ID_W + 1 + 40)
                rows[index] = spans([tag, " ", row]) if tag else row
                continue
            chart = indent(row)
            tag = agent_tag(turn, colour, chart - C_MIN_GAP)
            if tag:
                rows[index] = spans([" " * (chart - C_MIN_GAP - width(tag)),
                                     tag, " " * C_MIN_GAP,
                                     lstrip(row, " ")])
        if lead and len(rows) > lead:
            rows.insert(lead, [])
        return rows

    tag = [] if getattr(last, "compact", False) else turn_tag(last, colour)
    if not tag:
        return drawn(laid_out(lead_newline))
    # The tag names the turn the 🎤 row bills, so it goes on that row and on
    # no other: in its pad, C_MIN_GAP columns left of its 📊, where the pad
    # has room.  The 🎤 row follows the 👥 and compaction rows and the blank
    # line laid_out puts under them, when there are any.  With
    # --force-newline the line beside Claude Code's chrome stays blank.
    rows = laid_out(lead_newline)
    at = lead + 1 if lead and len(rows) > lead else 0
    chart = indent(rows[at])
    room = chart - width(tag) - C_MIN_GAP
    if room >= 0:
        rows[at] = spans([" " * room, tag, " " * C_MIN_GAP,
                          lstrip(rows[at], " ")])
        return drawn(rows)
    # No room: the tag takes a line of its own directly above the 🎤 row,
    # its 🔖 over the row's 📊 with 🔺 just left of it.  Under 👥 or
    # compaction rows that is the blank line between them and the 🎤 row,
    # a continuation line like the row itself.
    if at:
        rows[at - 1] = spans([" " * max(0, chart - vis_width(E_TURN_PAST)),
                              tag])
        return drawn(rows)
    # With the 🎤 row first, it is the first line, the one beside Claude
    # Code's chrome, so the rows below it are all continuation lines.  The
    # first line starts C_CHROME_LEFT - C_CHROME_CONT columns further right
    # than the rows, so that much comes off the pad.  Where the rows flow
    # left there is no pad to take it from, and the tag starts the line.
    rows = laid_out(True)
    chart = indent(rows[0])
    pad = chart - (C_CHROME_LEFT - C_CHROME_CONT) - vis_width(E_TURN_PAST)
    return " " * max(0, pad) + join(tag) + "\n" + drawn(rows, False)
