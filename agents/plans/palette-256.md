# Colours: every default on the 256-colour palette

A proposal, not built yet (asked 2026-10-20: "ensure that the default
colours snap to the 256-colour Tmux palette, since other users will likely
default to this").

## Why

Claude Code draws in 256 colours whenever `TMUX` is set, unless
`CLAUDE_CODE_TMUX_TRUECOLOR` is (the 2.1.304 binary: `if (a.TMUX &&
level > 2) level = 2`). Each channel is then rounded to the colour cube's
0, 95, 135, 175, 215, 255 (`16 + 36r + 6g + b`, each `round(v / 255 *
5)`). A colour between those steps draws differently in tmux and outside
it, and two near colours can land on one entry: the user's dark blue
prompt and the dark green message bar both drew as `#005f5f` teal (seen
live 2026-10-20). Every one of the 23 `rgb(...)` colours in
`spec/layout.jsonc` is off the palette today, by up to 55 in a channel
(`F_GRN` 120,200,80 draws as 135,215,135).

The panel, a status line Claude Code runs as a command, writes its own
escapes, so it draws in true colour wherever the terminal does; the mod's
rows go through Claude Code's renderer and are rounded. One palette-exact
set looks the same in both.

## The design

- **Every default colour is a palette entry:** one of the 216 cube colours
  (channels from 0, 95, 135, 175, 215, 255) or one of the 24 greys
  (`8 + 10k`, k 0–23). It draws the same in true colour and in 256.
- **Snapped by eye, not by formula alone:** each colour moves to its
  nearest entry, then the set is drawn side by side (`tools/draw-panel.py`
  and `mod/tools/draw-figures.ts` on the fixtures) and adjusted where two
  roles land on one entry or a hue reads wrong. The roles that must stay
  apart are the ones the eye compares: 🔋 and 🪫, the ⌛ split's 🤖 🔧 🚦, the
  magnitude dims, the chat rows' greys, and `B_MSG` against the theme's
  user-message background.
- **A check:** `tools/gen-spec.py` refuses an `F_*` or `B_*` colour that is
  not a palette entry, naming the nearest, so a new colour cannot drift
  off it.
- **The theme:** `docs/` notes that a custom theme's `userMessageBackground`
  should be a palette entry for the same reason, with the dark blue
  `#00005f` as the example, and that `CLAUDE_CODE_TMUX_TRUECOLOR=1` lifts
  the rounding where tmux passes RGB (`Tc` or `RGB` in `tmux info`).

## The build order

1. **Snap and check.** Every colour moved to a palette entry and reviewed
   in the side-by-side drawing; the gen-spec check; the fixtures and
   goldens regenerated (colour bytes only). The user looks at the drawing
   before the commit.
2. **The doc note** on themes and `CLAUDE_CODE_TMUX_TRUECOLOR`.

## Files

`spec/layout.jsonc`, `tools/gen-spec.py`, the generated `spec.py` and
`spec.ts`, every fixture and golden carrying colour escapes, `docs/`.
Step 1 regenerates fixtures broadly, so it runs when no other node is
regenerating them; see [the schedule](_schedule.md).
