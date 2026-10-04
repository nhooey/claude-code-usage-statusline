"""Pure layout for Claude's prepared Stop-cost report.

The caller supplies turns plus already-prepared window, calibration and plan
totals.  This module deliberately does not read transcripts, caches, account
sources, clocks or process state.  The metric-group builders are arguments so
the remaining Claude accounting move can retain its exact tested arithmetic
while this layout seam is adopted.
"""
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from . import formatting as fmt
from .formatting import (BOLD, C_CHROME_CONT, C_CHROME_LEFT, C_MIN_GAP,
                         C_RIGHT_MARGIN, E_TURN_ID, E_TURN_PAST, R,
                         TURN_ID_HEX, UNBOLD, fit_cols, trunc, vis_width)


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


class Ink(NamedTuple):
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


COLOUR_INK = Ink(R, fmt.F_GRN, fmt.F_AMB, fmt.F_RED, fmt.F_TUP, fmt.F_TDN,
                 fmt.F_YEL, fmt.F_PNK, fmt.F_PNK2, fmt.F_CRM)
PLAIN_INK = Ink("", "", "", "", "", "", "", "", "", "")


def place(group: str, opts: CostOpts, label: str, chrome: int) -> str:
    """Place one finished cost row without touching terminal/process state."""
    def painted(value: str) -> str:
        parts = [part for part in (opts.prefix,
                                   BOLD + value + UNBOLD if value else "") if part]
        return " ".join(parts)

    if opts.cols and opts.right_align:
        room = opts.cols - chrome - C_RIGHT_MARGIN - vis_width(group)
        plain = " ".join(part for part in (opts.prefix, label) if part)
        pad = room - vis_width(plain) - C_MIN_GAP
        if pad >= 0:
            return " " * pad + painted(label) + " " * C_MIN_GAP + group
        keep = trunc(label, max(0, room - vis_width(opts.prefix) - 1 - C_MIN_GAP))
        head = painted(keep) if keep else opts.prefix
        return head + " " * C_MIN_GAP + group
    head = painted(label)
    return head + " " + group if head else group


def stack_metrics(rows: Sequence[Tuple[str, str, int]],
                  opts: CostOpts) -> Tuple[int, int, int]:
    """Return the shared tight/room/base geometry for a cost-row block."""
    tight = max(chrome + vis_width(group) for group, _, chrome in rows)
    room = opts.cols - C_RIGHT_MARGIN - tight
    widest = max(vis_width(" ".join(part for part in (opts.prefix, label) if part))
                 for _, label, _ in rows)
    return tight, room, room - widest - C_MIN_GAP


def place_stacked(rows: Sequence[Tuple[str, str, int]], opts: CostOpts) -> List[str]:
    """Place several rows as one aligned block."""
    def painted(value: str) -> str:
        parts = [part for part in (opts.prefix,
                                   BOLD + value + UNBOLD if value else "") if part]
        return " ".join(parts)

    if not (opts.cols and opts.right_align):
        return [(painted(label) + " " + group).strip() if painted(label) else group
                for group, label, _ in rows]
    tight, room, base = stack_metrics(rows, opts)
    output = []
    for group, label, chrome in rows:
        shift = tight - chrome - vis_width(group)
        if base >= 0:
            output.append(" " * (base + shift) + painted(label)
                          + " " * C_MIN_GAP + group)
            continue
        keep = trunc(label, max(0, room - vis_width(opts.prefix) - 1 - C_MIN_GAP))
        head = painted(keep) if keep else opts.prefix
        output.append(" " * shift + head + " " * C_MIN_GAP + group)
    return output


def turn_tag(turn: object, ink: Ink) -> str:
    """🔺🔖 8f37748e #12: the turn the 🎤 row bills, by the head of its
    promptId and Claude Code's turn index.  Each half is drawn only where the
    transcript wrote it, and the tag not at all where it wrote neither."""
    idx = getattr(turn, "turn_index", None)
    pid = getattr(turn, "prompt_id", "")
    parts = ([pid[:TURN_ID_HEX]] if pid else []) + (
        ["#%d" % idx] if idx is not None else [])
    if not parts:
        return ""
    return "%s%s %s%s%s" % (E_TURN_PAST, E_TURN_ID, ink.crm, " ".join(parts),
                            ink.r)


# The agent id on a 👥 row, cut as the agent panel cuts it, and the fewest
# columns of its name worth drawing after it.
AGENT_ID_W, AGENT_NAME_MIN = 10, 6


def agent_tag(turn: object, ink: Ink, room: int) -> str:
    """The name and id of the agent a 👥 row bills, in at most `room`
    columns: as much of the name as fits, then the id padded to AGENT_ID_W,
    so the ids of a block of 👥 rows stand in one column beside their 📊s.
    The id whole or nothing."""
    aid = getattr(turn, "agent_id", "")
    if not aid or room < AGENT_ID_W:
        return ""
    aid = "%s%s%s" % (ink.crm, fit_cols(aid, AGENT_ID_W), ink.r)
    aid += " " * (AGENT_ID_W - vis_width(aid))
    name = getattr(turn, "agent_name", "")
    left = room - AGENT_ID_W - 1
    name = trunc(name, left) if name and left >= AGENT_NAME_MIN else ""
    return (name + " " if name else "") + aid


def render_cost_line(
        turns: Sequence[object], opts: CostOpts, win: int,
        calib: Dict[str, Optional[float]], plan_totals: Dict[str, Optional[float]],
        now: Optional[float],
        cost_group: Callable[[object, Dict[str, Optional[float]], int, Ink,
                              Optional[float], bool, bool], str],
        totals_group: Callable[[Sequence[object], Dict[str, Optional[float]], int,
                                Ink, Optional[float], Dict[str, Optional[float]],
                                bool, bool], str]) -> str:
    """Lay out prepared Claude cost rows; all accounting is supplied by caller.

    ``cost_group`` and ``totals_group`` are pure prepared-data builders.  They
    make the temporary seam explicit while the legacy Claude arithmetic moves
    here, and prevent this renderer from reaching caches or transcript files.
    """
    if not turns:
        return opts.prefix + " (no prompts recorded yet)"
    ink = COLOUR_INK if opts.colour else PLAIN_INK
    prompts = [index for index, turn in enumerate(turns)
               if getattr(turn, "calls", None) and not getattr(turn, "compact", False)
               and not getattr(turn, "agent", False)]
    last_index = prompts[-1] if prompts else len(turns) - 1
    previous = prompts[-2] if len(prompts) > 1 else -1
    last = turns[last_index]
    if any(getattr(turn, "reported", False) for turn in turns):
        pending = [turn for turn in turns
                   if (getattr(turn, "compact", False) and not getattr(turn, "reported", False))
                   or getattr(turn, "agent", False)]
    else:
        pending = [turn for turn in turns[previous + 1:last_index]
                   if getattr(turn, "compact", False)] + [turn for turn in turns if getattr(turn, "agent", False)]
        pending.sort(key=lambda turn: getattr(turn, "ts", ""))
    acct, stamps = opts.account_totals, opts.stamps
    spec = [(cost_group(turn, calib, win, ink, now, acct, stamps),
             opts.agents_label if getattr(turn, "agent", False) else opts.compact_label,
             C_CHROME_LEFT if index == 0 else C_CHROME_CONT)
            for index, turn in enumerate(pending)]
    spec.append((cost_group(last, calib, win, ink, now, acct, stamps),
                 opts.compact_label if getattr(last, "compact", False) else opts.label,
                 C_CHROME_LEFT if not spec else C_CHROME_CONT))
    if opts.totals:
        spec.append((totals_group(turns, plan_totals, win, ink, now, calib, acct, stamps),
                     opts.totals_label, C_CHROME_CONT))
    lead_newline = opts.force_newline
    if not lead_newline and opts.cols and opts.right_align:
        flat = [(group, label, C_CHROME_CONT) for group, label, _ in spec]
        lead_newline = stack_metrics(spec, opts)[2] < 0 <= stack_metrics(flat, opts)[2]
    lead = len(pending) + (1 if getattr(last, "compact", False) else 0)

    def laid_out(own_line: bool) -> List[str]:
        flat = spec
        if own_line:
            flat = [(group, label, C_CHROME_CONT) for group, label, _ in spec]
        rows = [row.rstrip() for row in place_stacked(flat, opts)]
        # Each 👥 row bills one agent, and names it in its pad, C_MIN_GAP
        # left of its 📊 the way the turn tag sits on the 🎤 row.
        for index, turn in enumerate(pending):
            if not getattr(turn, "agent", False):
                continue
            row = rows[index]
            if not (opts.cols and opts.right_align):
                # Flush left there is no pad, and no column to keep: the
                # tag leads the row.
                tag = agent_tag(turn, ink, AGENT_ID_W + 1 + 40)
                rows[index] = tag + " " + row if tag else row
                continue
            chart = len(row) - len(row.lstrip(" "))
            tag = agent_tag(turn, ink, chart - C_MIN_GAP)
            if tag:
                rows[index] = (" " * (chart - C_MIN_GAP - vis_width(tag)) + tag
                               + " " * C_MIN_GAP + row.lstrip(" "))
        if lead and len(rows) > lead:
            rows.insert(lead, "")
        return rows

    tag = "" if getattr(last, "compact", False) else turn_tag(last, ink)
    if not tag:
        rows = laid_out(lead_newline)
        return ("\n" if lead_newline else "") + "\n".join(rows)
    # The tag names the turn the 🎤 row bills, so it goes on that row and on
    # no other: in its pad, C_MIN_GAP columns left of its 📊, where the pad
    # has room.  The 🎤 row follows the 👥 and compaction rows and the blank
    # line laid_out puts under them, when there are any.  With
    # --force-newline the line beside Claude Code's chrome stays blank.
    rows = laid_out(lead_newline)
    at = lead + 1 if lead and len(rows) > lead else 0
    chart = len(rows[at]) - len(rows[at].lstrip(" "))
    room = chart - vis_width(tag) - C_MIN_GAP
    if room >= 0:
        rows[at] = (" " * room + tag + " " * C_MIN_GAP
                    + rows[at].lstrip(" "))
        return ("\n" if lead_newline else "") + "\n".join(rows)
    # No room: the tag takes a line of its own directly above the 🎤 row,
    # its 🔖 over the row's 📊 with 🔺 just left of it.  Under 👥 or
    # compaction rows that is the blank line between them and the 🎤 row,
    # a continuation line like the row itself.
    if at:
        rows[at - 1] = " " * max(0, chart - vis_width(E_TURN_PAST)) + tag
        return ("\n" if lead_newline else "") + "\n".join(rows)
    # With the 🎤 row first, it is the first line, the one beside Claude
    # Code's chrome, so the rows below it are all continuation lines.  The
    # first line starts C_CHROME_LEFT - C_CHROME_CONT columns further right
    # than the rows, so that much comes off the pad.  Where the rows flow
    # left there is no pad to take it from, and the tag starts the line.
    rows = laid_out(True)
    chart = len(rows[0]) - len(rows[0].lstrip(" "))
    pad = chart - (C_CHROME_LEFT - C_CHROME_CONT) - vis_width(E_TURN_PAST)
    return " " * max(0, pad) + tag + "\n" + "\n".join(rows)
