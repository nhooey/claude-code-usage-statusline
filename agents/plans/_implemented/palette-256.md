# Colours: every default on the 256-colour palette

Asked 2026-10-20: "ensure that the default colours snap to the 256-colour
Tmux palette, since other users will likely default to this". Both steps
are built (2026-10-20).

## Why

Claude Code draws in 256 colours whenever `TMUX` is set, unless
`CLAUDE_CODE_TMUX_TRUECOLOR` is (the 2.1.304 binary: `if (a.TMUX &&
level > 2) level = 2`). Its renderer then turns each colour into an index
the way chalk's `rgbToAnsi256` does: a grey (r = g = b) onto the ramp by
`round((v - 8) / 247 * 24) + 232`, anything else onto the cube by `16 +
36r + 6g + b`, each `round(v / 255 * 5)`. The terminal draws that index
from the xterm palette, whose cube steps are 0, 95, 135, 175, 215, 255 and
not the even fifths the rounding assumes, so 95 comes back as 135 and 135
as 175, and the ramp's greys from 188 up come back a step darker. A colour
that is not one of the entries that survive this draws differently in
tmux and outside it, and two near colours can land on one entry: the
user's dark blue prompt and the dark green message bar both drew as
`#005f5f` teal (seen live 2026-10-20). Every one of the 23 `rgb(...)` colours in
`spec/layout.jsonc` is off the palette today, by up to 55 in a channel
(`F_GRN` 120,200,80 draws as 135,215,135).

The panel, a status line Claude Code runs as a command, writes its own
escapes, so it draws in true colour wherever the terminal does; the mod's
rows go through Claude Code's renderer and are rounded. One palette-exact
set looks the same in both.

## The design

- **Every default colour is a palette entry the rounding gives back:** one
  of 80. A cube colour whose channels are all 0, 175, 215 or 255 (60),
  black, white, or a ramp grey from 8 to 178 (`8 + 10k`, k 0–17). It
  draws the same in true colour and in 256. There is no dark colour but a
  grey: the darkest purple is `#af00af`.
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
  should be one of these entries for the same reason, with the dark blue
  `#0000af` as the example (`#00005f`, the user's, draws as `#000087`
  under tmux), and that `CLAUDE_CODE_TMUX_TRUECOLOR=1` lifts
  the rounding where tmux passes RGB (`Tc` or `RGB` in `tmux info`).

## The build order

1. **Snap and check.** Done 2026-10-20. Every colour moved to a palette
   entry and reviewed in the side-by-side drawing
   (`tools/palette-review.py`); the gen-spec check; the fixtures and
   goldens regenerated (colour bytes only).
2. **The doc note** on themes and `CLAUDE_CODE_TMUX_TRUECOLOR`. Status
   2026-10-20: done. [Under tmux](../../../docs/layout.md#under-tmux), in
   `docs/layout.md`, with a pointer from `docs/development.md`.

## Files

`spec/layout.jsonc`, `tools/gen-spec.py`, the generated `spec.py` and
`spec.ts`, every fixture and golden carrying colour escapes, `docs/`.
Step 1 regenerates fixtures broadly, so it runs when no other node is
regenerating them; see [the schedule](../_schedule.md).
