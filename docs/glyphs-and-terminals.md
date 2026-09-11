# Glyphs, terminals, and the naughty ones

Most of what is hard here is not the layout. It is that **JediTerm** — the
terminal JetBrains Rider embeds, and the one these rows are tuned for —
disagrees with every published width table about how many columns an emoji
occupies, and disagrees with ITSELF about how many it paints.

Three rules, all learned expensively:

1. **Never infer a width from which row looks wrong. MEASURE it.** Run
   `tests/probe-advance.sh` in a real terminal tab (it needs a controlling
   tty, which Claude Code does not have) and it reports the advance of every
   glyph by asking the terminal directly, with DSR. Four separate conclusions
   drawn from screenshots were later contradicted by that probe.
2. **Prefer single-codepoint pictographs from U+1F300 up**, nothing newer than
   about Unicode 9, and no variation selectors. A codepoint that defaults to
   TEXT presentation is drawn one column wide by some terminals and two by
   others; picking one buys a per-terminal alignment bug for a picture. The
   per-terminal override tables are empty because the glyph set holds to this
   — an invariant, not a coincidence, and the thing to defend when choosing
   the next glyph.

   **One glyph does not hold to it: 🤏 `E_ROW_COMPACT`, U+1F90F, is Unicode
   12.** It is kept, and it has caused no observed trouble, but it is an
   exception rather than the rule; this documentation used to claim there
   were none. It takes its two columns from the broad `0x1F300–0x1FBFF`
   range rather than from anything specific to it. **Measured 2026-09-08:
   two columns in JediTerm and two under Ghostty**, so the range is right about it in both —
   which is a measurement, and no longer the inference this paragraph used to
   ask someone to replace.

   The other row glyph added since, 👥 `E_ROW_AGENTS` U+1F465 (Unicode
   6.0, Emoji_Presentation=Yes), holds to the rule — and is **unmeasured**
   as of 2026-09-11. See the TODO in [Development](development.md).

   Choosing a replacement, if one is ever wanted: single codepoint, `W` under
   the test below, at or under Unicode 9, no variation selector. 📉 U+1F4C9
   (Unicode 6.0) and 🔽 U+1F53D (6.0) both qualify and both read as "it got
   smaller". Note that the obvious candidate does NOT: U+1F5DC 🗜 is named
   literally `COMPRESSION` and is Neutral, Unicode 7, text-presentation by
   default — naughty on every count.
3. **Distinguish a layout bug from a paint bug before fixing either.** A layout
   bug moves a whole cell and survives a copy-paste of the row. A paint bug
   corrupts single characters (`1sm` for a value of `1s`) and vanishes in a
   paste, because the buffer is correct and only the screen is not. Ask for a
   paste; it settles the question instantly.

A glyph that breaks rule 2 is a **naughty** one. The test is cheap:

```sh
python3 -c "import unicodedata as u; print(u.east_asian_width('⌛'))"
```

`W` is safe. `N` and `A` are not — they are the codepoints terminals disagree
about, and `A` (Ambiguous) includes the em dash, which is why prose read in
JediTerm is written without one.

## Why `vis_width` is not a "correct" Unicode implementation

It counts per codepoint with no grapheme clustering, and uses a hand-maintained
width table rather than `unicodedata`. Both look like bugs and both are
deliberate. **Swapping in `wcwidth`, or `unicodedata.east_asian_width`, or any
correct implementation, breaks the alignment of every row.** The fix is
tempting and has been attempted before, so it is documented at each site in the
code as well as here.

`EAW_WIDE` began as a generated East_Asian_Width table and was then corrected
against the probe. The corrections are the point:

* `127462–127490` folds in the regional indicators — two columns EACH here, so
  a flag costs four, where a clustering terminal paints two.
* `127744–130047` is U+1F300 through U+1FAFF as ONE range where the generated
  table had a dozen with gaps. Every pictograph probed there came back two
  columns, including the ones EAW calls Neutral for defaulting to text
  presentation (🗑 🛢 🗓 🎟 🌡). The gaps mattered: those appear in
  conversation, and each one measured as a single column dragged its row out of
  line.
* U+1FA70–U+1FAF8 (Unicode 12 and later) was left OUT of the table for a
  while, so it measured one column, on the reasoning that this terminal's font
  predated the block — that is what made 🪟 leave a phantom character beside
  it. **That exclusion is gone**: the range now runs to U+1FBFF, 🪫 U+1FAAB is
  in the layout on the strength of it, and the 2026-09-08 probe measured
  U+1FA70 U+1FA90 U+1FAA3 U+1FAE0 at two columns each in **both** JediTerm and
  Ghostty. The bullet is kept because the reasoning was sound and the
  conclusion was not, which is the argument for measuring rather than
  reasoning, made against this documentation itself.
* U+1F300–U+1FBFF being one range makes U+1F900 wide, and the standard calls
  that codepoint Neutral. Measured 2026-09-08: **Ghostty advances one, JediTerm
  advances two.** No entry is right for both, this one is right for the
  terminal the layout is tuned to, and it costs nothing because no glyph here
  sits in U+1F900–U+1F90B. It is the reason to keep choosing glyphs from
  outside that band.

`unicodedata` would get all three wrong. It ships UCD 13 on Python 3.9 and
answers what the standard says, which is a different question from what this
terminal does.

**Keep `EAW_WIDE` sorted.** The scan stops at the first range starting above
the codepoint, so an entry out of order is an entry never read.

## The glyph constants are the single source of truth

Characters are referenced everywhere by `E_*` name, never by literal, because
`tests/probe-advance.sh` derives what to measure by parsing those names out of
the program. A glyph left inline in a renderer is a glyph nobody measures —
which is how the probe's list drifted from the layout three times in two hours.

