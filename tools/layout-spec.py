#!/usr/bin/env python3
"""Write spec/layout.json from coding_agent_usage_line/formatting.py.

    python3 tools/layout-spec.py           # rewrite it
    python3 tools/layout-spec.py --check   # exit 1 if it is out of date

The layout spec is what the TypeScript mod reads in place of formatting.py:
the glyphs, the colours, the numeric widths and cuts, the wide-character
table, and the terminal-profile rules. formatting.py stays the source, with
each value written out beside the comment that explains it, and this file
copies them across, so the two languages cannot disagree about a glyph or a
width without --check failing. tests/formatting.py runs --check.

Literal constants are read with ast, as tests/probe-advance.sh reads them,
so a value computed at import (an S_* form, RIGHT_GRID) is not in the spec:
those are rules, and each language computes them. The profile tables come
from widths_for(), which is pure, called once per profile.
"""
import ast
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(REPO, "coding_agent_usage_line", "formatting.py")
SPEC = os.path.join(REPO, "spec", "layout.json")
sys.path.insert(0, REPO)

# Rebound by set_mark_spacing or set_subscript_decimals: their literal is a
# default, not a constant, and the switch decides the value.
SWITCHED = {"MARK_SP", "LINE3_RESERVED", "SUB_DEC", "PWD_MAX_FALLBACK",
            "C_TOK", "C_CACHE", "C_LIM_TOT", "C_SESS"}
FG = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m$")
BG = re.compile(r"\x1b\[48;2;(\d+);(\d+);(\d+)m$")


def literals(src):
    """Each top-level NAME = <literal or earlier NAME>, in source order."""
    out = {}
    for node in ast.parse(src).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        t = node.targets[0]
        if not isinstance(t, ast.Name):
            continue
        v = node.value
        if isinstance(v, ast.Constant):
            out[t.id] = v.value
        elif isinstance(v, ast.Name) and v.id in out:
            out[t.id] = out[v.id]          # an alias: F_SPIN = F_RED
        elif t.id == "EAW_WIDE":
            out[t.id] = [list(r) for r in ast.literal_eval(v)]
    return out


def build():
    with open(SOURCE, encoding="utf-8") as fh:
        lits = literals(fh.read())
    from coding_agent_usage_line import formatting as f

    spec = {"glyphs": {}, "colors": {}, "backgrounds": {}, "numbers": {}}
    for name, v in lits.items():
        if name.startswith("E_") and isinstance(v, str):
            spec["glyphs"][name] = v
        elif isinstance(v, str) and FG.match(v):
            spec["colors"][name] = [int(x) for x in FG.match(v).groups()]
        elif isinstance(v, str) and BG.match(v):
            spec["backgrounds"][name] = [int(x) for x in BG.match(v).groups()]
        elif (re.fullmatch(r"[A-Z][A-Z0-9_]*", name) and name not in SWITCHED
              and isinstance(v, (int, float)) and not isinstance(v, bool)):
            spec["numbers"][name] = v
    spec["eaw_wide"] = lits["EAW_WIDE"]
    spec["profile_rules"] = [list(r) for r in f.PROFILE_RULES]
    spec["pad_profiles"] = list(f.PAD_PROFILES)
    spec["profiles"] = {}
    for p in ("jediterm", "tmux", "iterm", "unknown"):
        w = f.widths_for(p)
        spec["profiles"][p] = {"narrow": sorted(w.narrow),
                               "icons": sorted(w.icons),
                               "clusters": w.clusters}
    return json.dumps(spec, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def main():
    text = build()
    if sys.argv[1:] == ["--check"]:
        try:
            with open(SPEC, encoding="utf-8") as fh:
                current = fh.read()
        except FileNotFoundError:
            current = None
        if current != text:
            sys.stderr.write("spec/layout.json is out of date: run "
                             "python3 tools/layout-spec.py\n")
            return 1
        return 0
    os.makedirs(os.path.dirname(SPEC), exist_ok=True)
    with open(SPEC, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
