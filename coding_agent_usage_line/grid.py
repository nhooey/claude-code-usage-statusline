"""The redesigned grid: one scope per row, one column per metric.

agents/plans/_implemented/redesign.md has the design, and mod/src/grid.ts
is the reference this ports, function for function.  Every row of the band, the
receipt and the agent panel draws the columns of GRID_CELLS in one order; a
row with nothing for a column leaves it blank, so the columns hold.  On a
narrow terminal a row's label sheds its ranked parts, then is cut, and past
LABEL_MIN columns whole columns drop from every row at once, in DROP_ORDER.
`--hide` paths remove columns and label parts.

The grid knows nothing about how a cell was drawn.  A row is plain data,
its label's pieces and its cells as spans, so the panel can hand it its
own and tests/grid.py can replay the cases the TypeScript writes under
tests/fixtures/grid/.  The rules' constants are spec's; the widths that
depend on the terminal profile are read from formatting's globals when they
are asked for, not at import, so a reloaded formatting moves them.  Nothing
here joins spans into escape codes: that is the printing's job.
"""
import re
from fnmatch import fnmatchcase
from typing import Dict, List, NamedTuple, Optional, Sequence, Union

from . import formatting as fmt
from . import claude_subagent_render as sub
from .spans import Span, cut, spans, width
from .spec import (CHROME_DEPTH, DROP_ORDER, E_PCT, GRID_CELLS, GRID_SCOPES,
                   LABEL_MIN, PANEL_CHROME, VAL2_W, VAL_W)


class Piece(NamedTuple):
    """A part of a row's label, with the path --hide names it by, under the
    row's scope.  A piece with a `drop` rank leaves the label whole, lowest
    rank first, before the label is cut short; 0 is only ever cut."""
    path: str
    spans: Sequence[Span]
    drop: int


class Row(NamedTuple):
    """One row: its scope (GRID_SCOPES), its label, its cells by GRID_CELLS
    key, and how deep in the agent panel it sits (None for a row outside the
    panel).  A key that is missing is a column the row has nothing for; one
    that is present is drawn, even as no spans."""
    scope: str
    label: Sequence[Piece]
    cells: Dict[str, Sequence[Span]]
    depth: Optional[int] = None


def cell_width(rule: Union[int, str]) -> int:
    """The cell's own width under the current profile, gap aside:
    GRID_CELLS names a fixed number or the rule the width is computed by,
    since the terminal profile widens 🧩, 🧠 and 💰 by a column.  The A_*
    rules that move with the profile are worked out here each time, so
    they follow a reload of formatting."""
    if isinstance(rule, int):
        return rule
    if rule == "A_RATE_W":
        return sub.A_RATE_W
    if rule == "COST_W":
        return fmt.vis_width(fmt.S_COST) + 4
    if rule == "A_CTX_W":
        return fmt.vis_width(fmt.S_CTX) + 4 + 1 + sub.A_CTX_PCT_W
    if rule == "TOK_W":
        return fmt.vis_width(fmt.S_TOK) + VAL_W + VAL2_W
    if rule == "A_CLOCK_W":
        return sub.A_CLOCK_W
    if rule == "A_ETA_W":
        return fmt.vis_width(fmt.E_ETA) + sub.A_ETA_FIG_W
    if rule == "A_SPLIT_W":
        return sub.A_SPLIT_W
    if rule == "A_LIMIT_W":
        return sub.A_LIMIT_W
    if rule == "A_LIMIT_WEEK_W":
        return sub.A_LIMIT_WEEK_W
    if rule == "A_DIFF_W":
        return fmt.vis_width(fmt.S_DIFF) + 11
    raise ValueError("no width rule " + rule)


def hidden(patterns: Sequence[str], path: str) -> bool:
    """Whether a pattern names `path` or a path above it: "turn.time" hides
    "turn.time.eta", and "*" stands for any one part."""
    parts = path.split(".")
    for p in patterns:
        want = p.split(".")
        if len(want) <= len(parts) and all(
                fnmatchcase(parts[i], w) for i, w in enumerate(want)):
            return True
    return False


def chrome(depth: Optional[int]) -> List[Span]:
    """What Claude Code draws before a panel row: PANEL_CHROME columns at
    depth 1, blanks then the pointer, and two more blanks per level below
    it.  A row outside the panel has none."""
    if depth is None:
        return []
    return [Span(" " * (PANEL_CHROME - 2 + 2 * (depth - 1)) + "◯ ",
                 None, True)]


def label_text(row: Row, patterns: Sequence[str], room: int) -> List[Span]:
    """The row's label in `room` columns: the ranked pieces leave first,
    lowest rank first, then what is left is cut, keeping its colours."""
    pieces = [p for p in row.label
              if not hidden(patterns, row.scope + "." + p.path)]
    ranks = sorted({p.drop for p in pieces if p.drop})

    def whole() -> List[Span]:
        return spans([list(p.spans) for p in pieces])

    for rank in ranks:
        if width(whole()) <= room:
            break
        pieces = [p for p in pieces if p.drop != rank]
    out = whole()
    return cut(out, room) if width(out) > room else out


def _shows(row: Row, key: str, path: str, patterns: Sequence[str]) -> bool:
    """Whether the row draws column `key`: it has a figure for it, and no
    pattern hides it on the row's scope."""
    return key in row.cells and not hidden(patterns, row.scope + "." + path)


def _share_gone(patterns: Sequence[str]) -> bool:
    """Whether the patterns hide 🧠's ٪ share of the window on every scope,
    so its column can give the share's room back."""
    return all(hidden(patterns, s + ".context.share") for s in GRID_SCOPES)


# The columns 🧠's size takes without its share: the mark, then a sign
# column, three for the digits and one for the unit, "🧠+316k", "🧠 1.2M",
# so the relative and absolute sizes stack from the band down to the
# subagents (asked 2026-10-20).
CTX_SIZE_W = 5


def _col_width(c: dict, patterns: Sequence[str]) -> int:
    """A column's width under `patterns`: 🧠's, where every scope hides its
    share, only its mark and CTX_SIZE_W."""
    if c["key"] == "ctx" and _share_gone(patterns):
        return fmt.vis_width(fmt.S_CTX.rstrip()) + CTX_SIZE_W
    return cell_width(c["width"])


def _stacked(text: str) -> str:
    """🧠's size in CTX_SIZE_W columns: its sign, "+", "-" or an estimate's
    "~", or a blank without one, then its digits flush right in three
    columns, then its unit, or a blank without one, " 800 ".  A figure in
    no such shape is set flush right as it is."""
    m = re.match(r"^([-+~]?)(\d+(?:\.\d)?)(\D?)$", text)
    if not m:
        return fmt.pad_val(CTX_SIZE_W, text)
    return (m.group(1) or " ") + m.group(2).rjust(3) + (m.group(3) or " ")


def _figure(row: Row, key: str, w: int, patterns: Sequence[str]) -> List[Span]:
    """The row's figure for column `key`, `w` wide: 🧠's without the ٪ share
    of the window that ends it, where a pattern hides `context.share` on the
    row's scope: the mark, no blank, and the size stacked, so the signs,
    digits and units of the rows stack."""
    f = spans(list(row.cells[key]))
    if (key != "ctx" or not f
            or not hidden(patterns, row.scope + ".context.share")):
        return f
    if f[-1].text.rstrip().endswith(E_PCT):
        f = f[:-1]
    mark, rest = f[0], f[1:]
    head = mark.text.rstrip()
    room = w - fmt.vis_width(head)
    text = _stacked("".join(s.text for s in rest).strip())
    style = next((s for s in rest if s.text.strip()), mark)
    return [mark._replace(text=head),
            style._replace(text=fmt.pad_val(room, text))]


def layout(rows: Sequence[Row], cols: int, patterns: Sequence[str],
           fixed: bool = True) -> List[str]:
    """The columns every row draws, after --hide and the narrow-window drop,
    as GRID_CELLS keys in order.

    With `fixed`, `rows` is every row the design can draw, and the chrome is
    kept for CHROME_DEPTH levels of nesting whether any agent runs or not:
    the columns then follow from the width and --hide alone, so the mod and
    each panel row's process reach them apart.  Without it they follow from
    the rows drawn, and move when a nested agent appears."""
    keys = [c["key"] for c in GRID_CELLS
            if any(_shows(r, c["key"], c["hide"], patterns) for r in rows)]
    room = {c["key"]: _col_width(c, patterns) + c["gap"] for c in GRID_CELLS}
    lead = (width(chrome(CHROME_DEPTH)) if fixed
            else max([0] + [width(chrome(r.depth)) for r in rows]))
    for k in DROP_ORDER:
        used = sum(room[c] for c in keys)
        if cols - fmt.RIGHT_EDGE_COLS - lead - used >= LABEL_MIN:
            break
        if k in keys:
            keys.remove(k)
    return keys


def draw(row: Row, keys: Sequence[str], cols: int, patterns: Sequence[str],
         spill: bool = True) -> List[Span]:
    """One row on the columns `keys`.  With `spill`, the label runs on over
    the row's own leading blank columns, up to its first figure, instead of
    stopping where the first column starts.  Every row ends
    fmt.RIGHT_EDGE_COLS columns short of the terminal's edge (RIGHT_EDGE
    unless --right-edge says), and never runs past that: a label with no
    room draws nothing, not even a `…`, and a row whose chrome and cells are
    wider than the terminal leaves, at a width too narrow for the drop to
    help, is cut there like a label."""
    cells = []
    for c in GRID_CELLS:
        if c["key"] not in keys:
            continue
        w = _col_width(c, patterns)
        cells.append([c["gap"] + w,
                      [Span(" " * c["gap"])]
                      + fmt.seg(w, _figure(row, c["key"], w, patterns))
                      if _shows(row, c["key"], c["hide"], patterns)
                      else None])
    head = chrome(row.depth)
    end = cols - fmt.RIGHT_EDGE_COLS
    room = end - width(head) - sum(w for w, _ in cells)
    while spill and cells and cells[0][1] is None:
        room += cells.pop(0)[0]
    right = []
    for w, c in cells:
        right.extend(c if c is not None else [Span(" " * w)])
    out = head + fmt.seg(room, label_text(row, patterns, room)) + right
    return cut(out, end) if width(out) > end else out
