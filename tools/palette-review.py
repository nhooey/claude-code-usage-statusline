#!/usr/bin/env python3
"""Draw spec/layout.jsonc's two colour sets side by side, to review them by
eye in a true-colour terminal.

    python3 tools/palette-review.py > review.ansi       # this tree's sets
    python3 tools/palette-review.py --old origin/master  # beside a revision's
    python3 tools/palette-review.py --nearest 4

One row a colour: its name, its true value, its 256 value with its palette
index, what Claude Code would draw the true value as at 256 colours if it
were handed that and left to round it (chalk's rgbToAnsi256 on the xterm
palette), and the role its comment gives.  Each cell is a block, the text
"841k" and the text "98٪" faint, as a figure under its magnitude cut is
drawn, with the faint text's contrast on black; a colour a dim figure takes
is marked * and must clear the floor in tools/gen-spec.py.  --nearest adds
that many palette entries closest to each true value.  --old adds a column
for a revision's 256 value.  Then the pairs whose roles must stay apart,
how far apart they are in each set, any two names that share one 256
entry, and real rows drawn at each level: the agent panel, the band and the
receipt, true colour then 256.  The palette and the checks are gen-spec's.
"""
import argparse
import importlib.util
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT = os.path.join("spec", "layout.jsonc")
RESET = "\x1b[0m"
# Claude Code's default dark theme's user-message background, which B_MSG
# sits against in the transcript.
PROMPT_BG = ("prompt background", (0, 0, 95), (0, 0, 95))
# Roles a reader compares, so their colours must stay apart.
PAIRS = [("F_LIM_SESS", "F_LIM_WEEK"), ("F_CHAT_U", "F_CHAT_B"),
         ("F_CHAT_U", "F_CRM"), ("F_CHAT_B", "F_SUM"), ("B_DRK", "B_MSG"),
         ("B_MSG", PROMPT_BG), ("F_PRW", "F_ETA"), ("F_PRW", "F_BLU"),
         ("F_BLU", "F_BLU2"), ("F_BLU", "F_PROJ"), ("F_RED", "F_OVER"),
         ("F_AMB", "F_YEL"), ("F_PNK", "F_PNK2"), ("F_PNK", "F_TDN"),
         ("F_TUP", "F_CYN"), ("F_TUP", "F_RATE"), ("F_GRN", "F_RATE"),
         ("F_PUR", "F_ETA"), ("F_PUR", "F_PRW"), ("F_PNK", "F_ETA"),
         ("F_BLU2", "F_CYN"), ("F_PROJ", "F_TDN"), ("F_CRM", "F_TUP"),
         ("F_GRN", "F_AMB"), ("F_RED", "F_PROJ")]
# The environments the rows are drawn under: Claude Code at true colour,
# then at 256 colours.
LEVELS = [("true colour", {"TERM": "xterm-256color", "COLORTERM": "truecolor"},
           "true-colour-panel"),
          ("256 colours", {"TERM": "xterm-256color"}, "app-41-63")]
# Real rows: (label, command run from the tree's root, given the level's
# fixture environment for the panel).
DRAWINGS = [
    ("the agent panel, 01-mixed at 150",
     lambda env: ["python3", "tools/draw-panel.py", "--ansi", "--env", env,
                  "01-mixed.json", "150"]),
    ("the band, 01-baseline at 196",
     lambda env: ["node", "mod/tools/draw-figures.ts",
                  "tests/fixtures/figures/status/01-baseline@196.json",
                  "--cols", "196"]),
    ("the receipt, 01-plain at 150",
     lambda env: ["node", "mod/tools/draw-figures.ts",
                  "tests/fixtures/figures/cost/01-plain@150.json",
                  "--cols", "150"]),
]
GOLDENS = [("true colour", "status/true-colour-01@196.txt"),
           ("256 colours", "status/01-baseline@196.txt")]


def gen_spec():
    path = os.path.join(REPO, "tools", "gen-spec.py")
    spec = importlib.util.spec_from_file_location("gen_spec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


G = gen_spec()


def colours(text):
    """{name: (rgb 256, rgb true, alias or None, role)} for every F_ and
    B_ name.  A revision whose colours have one value has it in both."""
    r = G.Reader(text)
    r.lead()
    out = {}
    for m in r.members().value:
        if m.key[:2] not in ("F_", "B_"):
            continue
        alias = G.same_as(m)
        if alias is not None:
            c256, ctrue = out[alias][:2]
        else:
            both = G.two_values(m) if hasattr(G, "two_values") else None
            c256 = G.rgb_of(m.key, both[0] if both else m)
            ctrue = G.rgb_of(m.key, both[1]) if both else c256
        role = " ".join(t.strip() for t in m.tail[:1])
        out[m.key] = (c256, ctrue, alias, role)
    return out


def faint_ratio(rgb):
    return G.contrast(G.faint(rgb), (0, 0, 0))


def swatch(rgb, name):
    fg = "38;2;%d;%d;%d" % rgb
    if name.startswith("B_"):
        return "\x1b[48;2;%d;%d;%dm\x1b[38;2;255;255;255m 841k 98٪ %s" % (
            *rgb, RESET)
    return "\x1b[%sm██ 841k\x1b[0m \x1b[2;%sm98٪%s" % (fg, fg, RESET)


def cell(rgb, name, index=None):
    tag = "%3d,%3d,%3d" % rgb
    if index is not None:
        tag += " %3d" % index
    if name.startswith("F_"):
        tag += " %4.2f" % faint_ratio(rgb)
    return "%s %s" % (swatch(rgb, name), tag)


def name_of(item):
    return item if isinstance(item, str) else item[0]


def run(argv, env):
    full = {k: v for k, v in os.environ.items()
            if k not in ("TMUX", "TERM_PROGRAM", "TERMINAL_EMULATOR",
                         "FORCE_COLOR", "NO_COLOR", "COLORTERM",
                         "TERM_PROGRAM_VERSION",
                         "CLAUDE_CODE_TMUX_TRUECOLOR")}
    full.update(env)
    p = subprocess.run(argv, cwd=REPO, capture_output=True, text=True,
                       env=full)
    return p.stdout if p.returncode == 0 else p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old", metavar="REV",
                    help="also show a revision's 256 value")
    ap.add_argument("--nearest", type=int, default=0, metavar="N",
                    help="list the N palette entries nearest each true value")
    ap.add_argument("--no-drawings", action="store_true",
                    help="leave out the real rows")
    args = ap.parse_args()

    with open(os.path.join(REPO, LAYOUT), encoding="utf-8") as fh:
        new = colours(fh.read())
    old = None
    if args.old:
        old = colours(subprocess.run(
            ["git", "show", "%s:%s" % (args.old, LAYOUT)], cwd=REPO,
            check=True, capture_output=True, text=True).stdout)

    out = ["\x1b[1mThe two colour sets\x1b[0m   (true | 256 + index | the "
           "true value as chalk rounds it at 256%s; each: block, text, faint "
           "text, faint contrast on black; * a dim figure takes it, floor "
           "%.1f)" % (" | " + args.old + "'s 256" if old else "",
                      G.FAINT_FLOOR), ""]
    for name, (c256, ctrue, alias, role) in new.items():
        idx = G.ansi256(c256)
        rounded = G.xterm(G.ansi256(ctrue))
        mark = "*" if name in G.DIMMED else " "
        line = "%-10s%s %s | %s | %s" % (
            name, mark, cell(ctrue, name), cell(c256, name, idx),
            cell(rounded, name))
        if old:
            line += " | " + cell(old.get(name, new[name])[0], name)
        out.append(line + "  " + (("= " + alias) if alias else role))
        if args.nearest:
            out.append("%-11s nearest: %s" % ("", "  ".join(
                "%3d %s ΔE %.1f" % (i, cell(G.xterm(i), name),
                                     G.delta_e(ctrue, G.xterm(i)))
                for i in G.nearest(ctrue, args.nearest))))

    out += ["", "\x1b[1mPairs that must stay apart\x1b[0m   (ΔE true, 256)",
            ""]
    for a, b in PAIRS:
        pa = new[a] if isinstance(a, str) else (a[1], a[2])
        pb = new[b] if isinstance(b, str) else (b[1], b[2])
        out.append("%-10s %-17s %5.1f %5.1f  %s  %s  |  %s  %s" % (
            name_of(a), name_of(b), G.delta_e(pa[1], pb[1]),
            G.delta_e(pa[0], pb[0]),
            cell(pa[1], name_of(a)), cell(pb[1], name_of(b)),
            cell(pa[0], name_of(a)), cell(pb[0], name_of(b))))

    shared = {}
    for name, (c256, _, alias, _) in new.items():
        if alias is None:
            shared.setdefault(c256, []).append(name)
    out += ["", "\x1b[1mNames sharing one 256 entry\x1b[0m (same_as aside): "
            + ("; ".join(" ".join(v) for v in shared.values() if len(v) > 1)
               or "none")]

    if not args.no_drawings:
        for label, argv in DRAWINGS:
            for level, env, fixture_env in LEVELS:
                out += ["", "\x1b[1m%s, at %s\x1b[0m" % (label, level), ""]
                out.append(run(argv(fixture_env), env).rstrip("\n"))
        for level, golden in GOLDENS:
            out += ["", "\x1b[1mthe status line golden %s, at %s\x1b[0m" % (
                golden, level), ""]
            with open(os.path.join(REPO, "tests", "golden", golden),
                      encoding="utf-8") as fh:
                out.append(fh.read().rstrip("\n"))
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
