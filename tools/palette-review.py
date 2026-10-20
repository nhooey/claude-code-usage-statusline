#!/usr/bin/env python3
"""Draw spec/layout.jsonc's colours beside an earlier revision's, to review
a palette change by eye in a true-colour terminal.

    python3 tools/palette-review.py                      # against HEAD
    python3 tools/palette-review.py --old origin/master --nearest 4
    python3 tools/palette-review.py --old-tree ../old > review.ansi

One row a colour: its name, the old colour, what Claude Code draws the old
one as under tmux's 256 colours, the new colour and its palette index, and
the role its comment gives.  --nearest adds that many palette entries
closest to the old colour.  Then the pairs whose roles must stay apart,
with how far apart they are before and after, and any two names that share
one entry.  --old-tree, a checkout of the old revision, adds real rows
drawn by tools/draw-panel.py and mod/tools/draw-figures.ts in that tree and
in this one.  The palette and the check are tools/gen-spec.py's.
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
PROMPT_BG = ("prompt background", (0, 0, 95))
# Roles a reader compares, so their colours must stay apart.
PAIRS = [("F_LIM_SESS", "F_LIM_WEEK"), ("F_CHAT_U", "F_CHAT_B"),
         ("F_CHAT_U", "F_CRM"), ("F_CHAT_B", "F_SUM"), ("B_DRK", "B_MSG"),
         ("B_MSG", PROMPT_BG), ("F_PRW", "F_ETA"), ("F_PRW", "F_BLU"),
         ("F_BLU", "F_BLU2"), ("F_BLU", "F_PROJ"), ("F_RED", "F_OVER"),
         ("F_AMB", "F_YEL"), ("F_PNK", "F_PNK2"), ("F_PNK", "F_TDN"),
         ("F_TUP", "F_CYN"), ("F_TUP", "F_RATE"), ("F_GRN", "F_RATE"),
         ("F_PUR", "F_ETA"), ("F_PUR", "F_PRW"), ("F_PNK", "F_ETA"),
         ("F_BLU2", "F_CYN"), ("F_PROJ", "F_TDN"), ("F_CRM", "F_TUP"),
         ("F_GRN", "F_AMB")]
# Real rows: (label, command run from the tree's root).
DRAWINGS = [
    ("the agent panel, 01-mixed at 150",
     ["python3", "tools/draw-panel.py", "--ansi", "01-mixed.json", "150"]),
    ("the band, 01-baseline at 196",
     ["node", "mod/tools/draw-figures.ts",
      "tests/fixtures/figures/status/01-baseline@196.json", "--cols", "196"]),
    ("the receipt, 01-plain at 150",
     ["node", "mod/tools/draw-figures.ts",
      "tests/fixtures/figures/cost/01-plain@150.json", "--cols", "150"]),
]
GOLDEN = os.path.join("tests", "golden", "status", "01-baseline@196.txt")


def gen_spec():
    path = os.path.join(REPO, "tools", "gen-spec.py")
    spec = importlib.util.spec_from_file_location("gen_spec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


G = gen_spec()


def colours(text):
    """{name: (rgb, alias or None, role)} for every F_ and B_ name."""
    r = G.Reader(text)
    r.lead()
    out = {}
    for m in r.members().value:
        if m.key[:2] not in ("F_", "B_"):
            continue
        alias = G.same_as(m)
        if alias is not None:
            rgb = out[alias][0]
        else:
            rgb = tuple(int(x) for x in G.RGB.match(m.value).groups())
        role = " ".join(t.strip() for t in m.tail[:1])
        out[m.key] = (rgb, alias, role)
    return out


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
    return "%s %s" % (swatch(rgb, name), tag)


def name_of(item):
    return item if isinstance(item, str) else item[0]


def rgb_of(item, table):
    return table[item][0] if isinstance(item, str) else item[1]


def run(tree, argv):
    p = subprocess.run(argv, cwd=tree, capture_output=True, text=True,
                       env=dict(os.environ, COLORTERM="truecolor"))
    return p.stdout if p.returncode == 0 else p.stdout + p.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old", default="HEAD",
                    help="the revision to compare with (default: HEAD)")
    ap.add_argument("--nearest", type=int, default=0, metavar="N",
                    help="list the N palette entries nearest each old colour")
    ap.add_argument("--old-tree", metavar="DIR",
                    help="a checkout of the old revision, to draw real rows")
    args = ap.parse_args()

    old_text = subprocess.run(
        ["git", "show", "%s:%s" % (args.old, LAYOUT)], cwd=REPO, check=True,
        capture_output=True, text=True).stdout
    with open(os.path.join(REPO, LAYOUT), encoding="utf-8") as fh:
        new_text = fh.read()
    old, new = colours(old_text), colours(new_text)

    out = ["\x1b[1mColours, %s -> this tree\x1b[0m   (old | old as tmux "
           "draws it | new + index; each: block, text, faint text)" % args.old,
           ""]
    for name, (rgb, alias, role) in new.items():
        was = old.get(name, (rgb, None, ""))[0]
        tmux = G.xterm(G.ansi256(was))
        idx = G.ansi256(rgb)
        mark = " " if G.xterm(idx) == rgb else "!"
        line = "%-10s %s | %s | %s%s  %s" % (
            name, cell(was, name), cell(tmux, name), cell(rgb, name, idx),
            mark, ("= " + alias) if alias else role)
        out.append(line)
        if args.nearest:
            out.append("%-10s nearest: %s" % ("", "  ".join(
                "%3d %s ΔE %.1f" % (i, cell(G.xterm(i), name),
                                     G.delta_e(was, G.xterm(i)))
                for i in G.nearest(was, args.nearest))))

    out += ["", "\x1b[1mPairs that must stay apart\x1b[0m   (ΔE old, "
            "old under tmux, new)", ""]
    for a, b in PAIRS:
        ra_old, rb_old = rgb_of(a, old), rgb_of(b, old)
        ra, rb = rgb_of(a, new), rgb_of(b, new)
        d_old = G.delta_e(ra_old, rb_old)
        d_tmux = G.delta_e(G.xterm(G.ansi256(ra_old)),
                           G.xterm(G.ansi256(rb_old)))
        d_new = G.delta_e(ra, rb)
        out.append("%-10s %-17s %5.1f %5.1f %5.1f  %s  %s" % (
            name_of(a), name_of(b), d_old, d_tmux, d_new,
            cell(ra, name_of(a)), cell(rb, name_of(b))))

    shared = {}
    for name, (rgb, alias, _) in new.items():
        if alias is None:
            shared.setdefault(rgb, []).append(name)
    out += ["", "\x1b[1mNames sharing one entry\x1b[0m (same_as aside): " +
            ("; ".join(" ".join(v) for v in shared.values() if len(v) > 1)
             or "none")]

    if args.old_tree:
        for label, argv in DRAWINGS:
            for which, tree in (("before", args.old_tree), ("after", REPO)):
                out += ["", "\x1b[1m%s, %s\x1b[0m" % (label, which), ""]
                out.append(run(tree, argv).rstrip("\n"))
        for which, tree in (("before", args.old_tree), ("after", REPO)):
            out += ["", "\x1b[1mthe status line, %s, %s\x1b[0m" % (
                GOLDEN, which), ""]
            with open(os.path.join(tree, GOLDEN), encoding="utf-8") as fh:
                out.append(fh.read().rstrip("\n"))
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
