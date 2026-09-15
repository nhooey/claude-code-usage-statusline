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
                         C_RIGHT_MARGIN, R, UNBOLD, trunc, vis_width)


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
    if lead_newline:
        spec = [(group, label, C_CHROME_CONT) for group, label, _ in spec]
    rows = [row.rstrip() for row in place_stacked(spec, opts)]
    lead = len(pending) + (1 if getattr(last, "compact", False) else 0)
    if lead and len(rows) > lead:
        rows.insert(lead, "")
    return ("\n" if lead_newline else "") + "\n".join(rows)
