# Glyphs and terminals

The readout keeps every figure on a fixed column, and that only works if the
program knows how many columns each character advances the cursor. Terminals
disagree about that for emoji, and no published width table matches all of
them. The program uses one width table with small per-terminal overrides,
and has been measured in Ghostty, iTerm2, JediTerm (JetBrains IDEs) and tmux.

## Choosing a glyph

A new mark must be:

1. **One codepoint.** No variation selector (U+FE0F), no ZWJ sequence, no
   skin tone, no flag.
2. **East Asian Width `W`.**

   ```sh
   python3 -c "import unicodedata as u; print(u.east_asian_width('⌛'))"
   ```

   `W` is safe. `N` (Neutral) and `A` (Ambiguous) are the codepoints terminals
   disagree about: many are text-presentation by default and draw one column
   in some terminals and two in others. Ambiguous includes box-drawing
   characters, which is why the column rule is ASCII `|` and not `│`.
3. **Unicode 9 or older**, preferably from U+1F300 up, so an older terminal
   font still has it.
4. **Outside U+1F900–U+1F90B.** The program treats that band as wide; JediTerm
   agrees and Ghostty does not.
5. **Declared as an `E_*` constant** in `coding_agent_usage_line/formatting.py`
   and used by name, never as a literal in a renderer. `tests/probe-advance.sh`
   finds the glyphs to measure by parsing those constants; a literal is a glyph
   nobody measures.

Then measure it. Run `bash tests/probe-advance.sh` in a real terminal tab and
check it advances two columns, and run `./coding-agent-usage-line.py
--selftest` and look at the drawn rows. A glyph can measure correctly and still
paint wrong.

One glyph in use breaks rule 3: 🤏 `E_ROW_COMPACT` (U+1F90F) is Unicode 12. It
measures two columns in both JediTerm and Ghostty, so it stays. If it ever
needs replacing, 📉 U+1F4C9 and 🔽 U+1F53D both satisfy every rule. 🗜 U+1F5DC
does not: it is Neutral, Unicode 7, and text-presentation by default.

## Diagnosing a misaligned row

**Measure, don't infer.** A width deduced from which row looks wrong has been
wrong repeatedly; the probe asks the terminal directly. Run it after a terminal
update, and before changing any glyph or `EAW_WIDE` entry.

**Tell a layout fault from a paint fault** before fixing either. Ask for the
row as pasted text:

- A **layout** fault moves a whole cell and is still there in the paste. The
  program's width arithmetic is wrong.
- A **paint** fault corrupts individual characters (`1sm` where the value is
  `1s`) and is gone in the paste, because the buffer is right and only the
  screen is wrong. The terminal's font fallback is the usual cause; a
  different glyph is the usual fix.

## Why `vis_width` is not a correct Unicode implementation

`vis_width` counts per codepoint, with no grapheme clustering, using the
hand-maintained `EAW_WIDE` table instead of `unicodedata`. Both look like bugs
and both are deliberate: **replacing it with `wcwidth`, `unicodedata`, or any
standards-correct implementation misaligns every row.** The standard answers
what the character *should* do; the table records what the terminal *does*.
Python 3.9's `unicodedata` also ships Unicode 13, older than several glyphs in
conversation text.

`EAW_WIDE` started as a generated East Asian Width table and was corrected
against the probe:

| Range | Correction |
|---|---|
| U+1F1E6–U+1F202 (127462–127490) | Regional indicators are two columns **each**, so a flag measures four. JediTerm does not cluster them. |
| U+1F300–U+1FBFF (127744–130047) | One range instead of a dozen with gaps. Every pictograph probed there advanced two, including ones the standard calls Neutral for defaulting to text presentation (🗑 🛢 🗓 🎟 🌡), which appear in conversation. This includes the Unicode 12+ block U+1FA70 onwards, where 🪫 lives. |

Two known imprecisions are left in on purpose:

- **U+1F900–U+1F90B** is Neutral in the standard. Ghostty advances one;
  JediTerm advances two. The table sides with JediTerm, and no glyph in the
  layout lives in that band.
- **U+26EA–U+270B** (9962–9995) mixes narrow dingbats (✀) and wide emoji (✅).
  No single entry is right for both. It costs nothing because chat text has
  the U+2190–U+2BFF block replaced before it is measured.

**Keep `EAW_WIDE` sorted.** The lookup stops at the first range starting above
the codepoint, so an out-of-order entry is never read.

## Terminal profiles

`term_profile` picks one of four profiles from the environment, in this order:

| Profile | Detected by |
|---|---|
| `tmux` | `TMUX` set |
| `jediterm` | `TERMINAL_EMULATOR=JetBrains-JediTerm` |
| `iterm` | `TERM_PROGRAM=iTerm.app` |
| `unknown` | anything else |

`widths_for` gives each profile its overrides: codepoints that advance one
where the table says two, codepoints that advance two where it says one, and
whether the terminal clusters graphemes. JediTerm does not cluster at all
(measured: skin-tone sequence 4 columns, ZWJ sequence 5, flag 4, keycap 3,
VS16 adds 1).

The override entries that remain are for glyphs that have since left the
layout (⏱ U+23F1, 🕰 U+1F570). Against the current glyph set the probe emits
empty override tables in every profile; the entries are kept as a record of
how those terminals behave.

`tmux` is checked first on the evidence that tmux over iTerm2 measured the
same as bare iTerm2. tmux inside JediTerm has never been measured. If you run
that combination, `--selftest` in it settles whether the `tmux` profile is
right there: a non-zero delta on any row means it needs its own profile.

## Measurements on record

`--selftest` and `probe-advance.sh` have been run in:

| Terminal | Result |
|---|---|
| Rider / JediTerm | every `--selftest` specimen row delta 0; every glyph in the layout advances as the table says |
| Ghostty under tmux | the same; 🤏 advances two; U+1F900 advances one |
| Ghostty, no tmux | 👥 advances two |
| iTerm2 under tmux | the same as bare iTerm2, except one keycap sequence |

That covers every mark on the readout, including 🎤 💯 💳 🎮 👥 🤏, ▴ ▾, the
`|` rule, and the subscript digits `E_SUB_DIGITS`.
