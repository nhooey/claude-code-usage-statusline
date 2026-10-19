"""Spans: the text a cell draws, each run with its own colour and attributes.

A cell returns spans, not a string with escape codes in it, so that what it
draws can be measured, compared and carried to a mod, whose `Text` refuses
control characters, without parsing escapes back out.  The colour is the
NAME of a spec constant, "F_PNK" and not its escape, so the TypeScript port
reads the same span and looks the name up in spec.ts.  Escape codes are
written by `join`, once, where the text is printed.

A plain string stands in for one uncoloured span wherever spans are taken,
so a mark or a pad need not be wrapped.
"""
from typing import List, NamedTuple, Optional, Sequence, Union

from . import spec

# The attribute escapes.  The colours are spec's; these are not colours.
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


class Span(NamedTuple):
    """One run of text drawn one way.

    `colour` and `bg` name an F_* and a B_* constant of spec, or are None
    for the terminal's own.  A span with none of the four drawn attributes
    is plain text and writes no escape at all.
    """
    text: str
    colour: Optional[str] = None
    dim: bool = False
    bold: bool = False
    bg: Optional[str] = None

    def styled(self) -> bool:
        return bool(self.colour or self.bg or self.dim or self.bold)


SpanLike = Union[str, Span, Sequence[Span]]


def spans(x: SpanLike) -> List[Span]:
    """`x` as a flat list of spans: a string is one plain span and "" none,
    and a list may hold strings, spans and lists of either, so a cell can
    be written as its pieces in order."""
    if isinstance(x, str):
        return [Span(x)] if x else []
    if isinstance(x, Span):
        return [x]
    out = []
    for s in x:
        out.extend(spans(s))
    return out


def ink(colour: Optional[str], dim: bool = False) -> Span:
    """A style with no text yet: `paint` puts text in it.  What a renderer
    passes where the escape-code version passed a colour prefix such as
    DIM + F_AMB."""
    return Span("", colour, dim)


def paint(style: Span, text: str) -> Span:
    """`text` in `style`'s colour and attributes."""
    return style._replace(text=text)


def text(x: SpanLike) -> str:
    """The spans' text alone, as the terminal's cells hold it."""
    return "".join(s.text for s in spans(x))


def width(x: SpanLike) -> int:
    """Columns the spans occupy, as vis_width counts them."""
    from .formatting import vis_width
    return sum(vis_width(s.text) for s in spans(x))


def cut(x: SpanLike, cols: int) -> List[Span]:
    """The spans in `cols` columns, ellipsis included: cut where fit_cols
    cuts their text, the longest start that leaves a column for the `…`,
    with each span kept as it was drawn.  The `…` takes the style of the
    span it cuts into.  At no room, `cols` 0 or under, nothing is left,
    since even the `…` would run a column past it."""
    from .formatting import fit_cols, vis_width
    out = spans(x)
    if vis_width(text(out)) <= cols:
        return out
    if cols <= 0:
        return []
    n = len(fit_cols(text(out), cols)) - 1    # the characters kept
    kept = []
    for s in out:
        if n >= len(s.text):
            kept.append(s)
            n -= len(s.text)
            continue
        kept.append(s._replace(text=s.text[:n] + "…"))
        break
    return kept


def rstrip(x: SpanLike) -> List[Span]:
    """The spans less trailing blanks, as str.rstrip took them off a drawn
    string: only off plain spans, since a coloured span's text ends at the
    reset after it, which no rstrip reached."""
    out = spans(x)
    while out and not out[-1].styled():
        t = out[-1].text.rstrip()
        if t:
            out[-1] = out[-1]._replace(text=t)
            break
        out.pop()
    return out


def lstrip(x: SpanLike, chars: Optional[str] = None) -> List[Span]:
    """The spans less leading `chars` (blanks by default), as str.lstrip
    took them off a drawn string: only off plain spans, since a coloured
    span's text starts after the escape that opens it."""
    out = spans(x)
    while out and not out[0].styled():
        t = out[0].text.lstrip(chars)
        if t:
            out[0] = out[0]._replace(text=t)
            break
        out.pop(0)
    return out


def indent(x: SpanLike) -> int:
    """Columns of blanks the spans open with: what lstrip(" ") takes off."""
    return len(text(x)) - len(text(lstrip(x, " ")))


def _runs_on(s: Span, nxt: Optional[Span]) -> bool:
    """Whether `s` and `nxt` are both a colour alone, so the escape that
    opens `nxt` replaces `s`'s colour with no reset between them."""
    def bare(t: Span) -> bool:
        return bool(t.colour) and not (t.bg or t.dim or t.bold)
    return nxt is not None and bare(s) and bare(nxt)


def _sgr(s: Span) -> str:
    """The escapes that open `s`: background, dim, bold, then colour, the
    order the renderers wrote them in (B_DRK + DIM + F_CHAT_U)."""
    return "".join((getattr(spec, s.bg) if s.bg else "",
                    DIM if s.dim else "",
                    BOLD if s.bold else "",
                    getattr(spec, s.colour) if s.colour else ""))


def join(x: SpanLike, close: bool = False, runs: bool = False) -> str:
    """The spans as the terminal draws them, with their escape codes.

    Each styled span is opened with its escapes and closed with a reset of
    its own, so no attribute leaks into the next: R, or UNBOLD for a span
    that is only bold, which turns bold off without stomping the colour
    around it.  Two exceptions keep the bytes the renderers wrote before
    spans, which the goldens pin:

    - A span is not reset before one that only lays a background under the
      same colour: a chat row's prefix runs straight into its body on the
      dark band, "fg 👤 B_DRK fg text R".
    - `close` writes one more reset at the end, which the status line's
      grid rows always carried after their last cell.  It changes nothing
      on screen, since every cell already reset itself.

    `runs` keeps the receipt's bytes: its metric groups wrote a run of
    bare colours, F_TUP ▴ then F_TDN ▾, with one reset after the run, so
    with it a span that is a colour alone is not reset before another.
    The status line's cells reset each half, which is why it is asked for.
    """
    out = []
    items = spans(x)
    for i, s in enumerate(items):
        if not s.styled():
            out.append(s.text)
            continue
        out.append(_sgr(s) + s.text)
        nxt = items[i + 1] if i + 1 < len(items) else None
        if (nxt is not None and s.colour and nxt.colour == s.colour
                and nxt.bg and not s.bg and not s.bold):
            continue
        if runs and _runs_on(s, nxt):
            continue
        if s.bold and not (s.colour or s.bg or s.dim):
            out.append(UNBOLD)
        else:
            out.append(R)
    if close:
        out.append(R)
    return "".join(out)
