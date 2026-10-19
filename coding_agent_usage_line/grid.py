"""The redesigned grid: one scope per row, one column per metric.

agents/plans/redesign.md has the design, and mod/src/grid.ts is the
reference this ports, function for function.  Every row of the band, the
receipt and the agent panel draws the columns of GRID_CELLS in one order; a
row with nothing for a column leaves it blank, so the columns hold.  On a
narrow terminal a row's label sheds its ranked parts, then is cut, and past
LABEL_MIN columns whole columns drop from every row at once, in DROP_ORDER.
On a wide one the grid stops after LABEL_MAX columns of label, and the rest
of the width stays empty.  `--hide` paths remove columns and label parts.

The grid knows nothing about how a cell was drawn.  A row is plain data,
its label's pieces and its cells as spans, so the panel can hand it its
own and tests/grid.py can replay the cases the TypeScript writes under
tests/fixtures/grid/.  The rules' constants are spec's; the widths that
depend on the terminal profile are read from formatting's globals when they
are asked for, not at import, so a reloaded formatting moves them.  Nothing
here joins spans into escape codes: that is the printing's job.
"""
from fnmatch import fnmatchcase
from typing import Dict, List, NamedTuple, Optional, Sequence, Union

from . import formatting as fmt
from . import claude_subagent_render as sub
from .spans import Span, cut, spans, width
from .spec import (CHROME_DEPTH, DROP_ORDER, GRID_CELLS, LABEL_MAX,
                   LABEL_MIN, PANEL_CHROME, RIGHT_EDGE, VAL2_W, VAL_W)


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
    room = {c["key"]: cell_width(c["width"]) + c["gap"] for c in GRID_CELLS}
    lead = (width(chrome(CHROME_DEPTH)) if fixed
            else max([0] + [width(chrome(r.depth)) for r in rows]))
    for k in DROP_ORDER:
        used = sum(room[c] for c in keys)
        if cols - RIGHT_EDGE - lead - used >= LABEL_MIN:
            break
        if k in keys:
            keys.remove(k)
    return keys


def edge(keys: Sequence[str], cols: int) -> int:
    """Where every row on the columns `keys` ends, at `cols`: RIGHT_EDGE
    columns short of the terminal's edge, or, where that would leave more
    than LABEL_MAX columns of label after the chrome at CHROME_DEPTH, where
    LABEL_MAX ends.  It follows from the columns and the width alone, as
    layout's do, so the mod and each panel row's process reach it apart."""
    used = sum(cell_width(c["width"]) + c["gap"] for c in GRID_CELLS
               if c["key"] in keys)
    return min(cols - RIGHT_EDGE,
               width(chrome(CHROME_DEPTH)) + LABEL_MAX + used)


def draw(row: Row, keys: Sequence[str], cols: int, patterns: Sequence[str],
         spill: bool = True) -> List[Span]:
    """One row on the columns `keys`.  With `spill`, the label runs on over
    the row's own leading blank columns, up to its first figure, instead of
    stopping where the first column starts.  Every row ends at `edge`, and
    never runs past it: a label with no room draws nothing, not even a `…`,
    and a row whose chrome and cells are wider than the terminal leaves, at
    a width too narrow for the drop to help, is cut there like a label."""
    cells = []
    for c in GRID_CELLS:
        if c["key"] not in keys:
            continue
        w = cell_width(c["width"])
        cells.append([c["gap"] + w,
                      [Span(" " * c["gap"])]
                      + fmt.seg(w, spans(list(row.cells[c["key"]])))
                      if _shows(row, c["key"], c["hide"], patterns)
                      else None])
    head = chrome(row.depth)
    end = edge(keys, cols)
    room = end - width(head) - sum(w for w, _ in cells)
    while spill and cells and cells[0][1] is None:
        room += cells.pop(0)[0]
    right = []
    for w, c in cells:
        right.extend(c if c is not None else [Span(" " * w)])
    out = head + fmt.seg(room, label_text(row, patterns, room)) + right
    return cut(out, end) if width(out) > end else out
