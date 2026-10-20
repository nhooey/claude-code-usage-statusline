#!/usr/bin/env python3
"""Write the differential cases that pin mod/src/formatting.ts and
mod/src/spans.ts to formatting.py and spans.py.

    /usr/bin/python3 tests/fixtures/gen/formatting.py

Run it under /usr/bin/python3, as gen/all.py does, so the cases are 3.9's.

What the files under tests/fixtures/formatting/ hold:

  settings.json  for each terminal environment, mark spacing and subscript
                 setting, what formatting.py's module globals come to (the
                 profile, the width table, the S_* forms, RIGHT_GRID and the
                 widths set_mark_spacing moves), with the constants that do
                 not move and the escape every F_* and B_* name stands for.
  values.json    each function over awkward inputs under each of CFGS:
                 widths and profiles, zero, negative, huge and non-finite
                 figures, the roundings either side of every cut.  One case
                 to a line: {"fn", "cfg", "args", "out"}, and "tz" where
                 the function reads the local zone.
  spans.json     spans.py's helpers over generated span lists, `join` with
                 each of its switches.

formatting.py fixes its profile from os.environ at import and rebinds its
globals through two setters, so each configuration is reached the way a
process reaches it: the environment set, the module reloaded, the setters
called.  The environment, the zone and the module are put back afterwards,
for the generators all.py runs next.

A span is written as {"span": [text, colour, dim, bold, bg]}, a float JSON
cannot carry as {"$float": ...}, and a call that raises as {"raises": true};
the port throws where the Python raises.
"""
import importlib
import json
import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(FIXTURES))
OUT = os.path.join(FIXTURES, "formatting")
sys.path.insert(0, REPO)

from coding_agent_usage_line import formatting as fm  # noqa: E402
from coding_agent_usage_line import spans as sp  # noqa: E402
from coding_agent_usage_line import spec  # noqa: E402

# What an environment here sets in full: the profile's variables and the
# colour level's, so neither comes from the developer's terminal.
PROFILE_VARS = tuple(dict.fromkeys(
    ("TMUX", "TERMINAL_EMULATOR", "TERM_PROGRAM") + sp.COLOUR_VARS))

# The environments a profile is read from: one per profile, and the ones
# that test the rules' order and their values.
ENVS = {
    "unknown": {},
    "jediterm": {"TERMINAL_EMULATOR": "JetBrains-JediTerm"},
    "iterm": {"TERM_PROGRAM": "iTerm.app"},
    "tmux": {"TMUX": "/tmp/tmux-501/default,1,0"},
    "tmux-over-jediterm": {"TMUX": "/tmp/t,1,0",
                           "TERMINAL_EMULATOR": "JetBrains-JediTerm"},
    "jediterm-over-iterm": {"TERMINAL_EMULATOR": "JetBrains-JediTerm",
                            "TERM_PROGRAM": "iTerm.app"},
    "empty-tmux": {"TMUX": "", "TERM_PROGRAM": "iTerm.app"},
    "ghostty": {"TERM_PROGRAM": "ghostty"},
    "other-emulator": {"TERMINAL_EMULATOR": "JetBrains-JediTerm2"},
    "true-colour": {"TERM": "xterm-256color", "COLORTERM": "truecolor"},
}

# The environments colour_level is read from: each of Claude Code's rules
# once.
COLOUR_ENVS = {
    "unknown": {},
    "xterm-256": {"TERM": "xterm-256color"},
    "colorterm": {"TERM": "xterm-256color", "COLORTERM": "truecolor"},
    "iterm-3": {"TERM_PROGRAM": "iTerm.app", "TERM_PROGRAM_VERSION": "3.5.10",
                "TERM": "xterm-256color"},
    "ghostty-term": {"TERM": "xterm-ghostty", "TERM_PROGRAM": "ghostty"},
    "foot": {"TERM": "foot"},
    "vscode": {"TERM_PROGRAM": "vscode", "TERM": "xterm-256color"},
    "tmux-true": {"TMUX": "/tmp/t,1,0", "TERM": "tmux-256color",
                  "COLORTERM": "truecolor"},
    "tmux-true-lifted": {"TMUX": "/tmp/t,1,0", "TERM": "tmux-256color",
                         "COLORTERM": "truecolor",
                         "CLAUDE_CODE_TMUX_TRUECOLOR": "1"},
    "no-color": {"COLORTERM": "truecolor", "NO_COLOR": "1"},
    "forced-256": {"FORCE_COLOR": "2", "TERM": "foot"},
    "forced-off": {"FORCE_COLOR": "0", "COLORTERM": "truecolor"},
    "dumb": {"TERM": "dumb", "COLORTERM": "truecolor"},
}

# The configurations every function runs under: each profile's width
# table, both mark spacings and both subscript settings.
CFGS = (
    ("unknown", True, False), ("unknown", False, True),
    ("jediterm", True, False), ("jediterm", False, True),
    ("iterm", True, True), ("tmux", False, False),
)

ZONES = ("UTC", "America/New_York", "Australia/Lord_Howe", "Asia/Kolkata")
NOW = 1786847000


def configure(env_name, spacing, subscript):
    """formatting.py as a process with this environment and these flags
    has it."""
    for var in PROFILE_VARS:
        os.environ.pop(var, None)
    os.environ.update(ENVS[env_name])
    importlib.reload(fm)
    fm.set_mark_spacing(spacing)
    fm.set_subscript_decimals(subscript)


def set_tz(name):
    if name is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = name
    time.tzset()


RAISES = object()


def run(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return RAISES


def enc(v):
    """A value as JSON both languages read the same; see the docstring."""
    if v is RAISES:
        return {"raises": True}
    if isinstance(v, sp.Span):
        return {"span": list(v)}
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        if math.isnan(v):
            return {"$float": "nan"}
        if math.isinf(v):
            return {"$float": "inf" if v > 0 else "-inf"}
        if v == 0 and math.copysign(1.0, v) < 0:
            return {"$float": "-0"}
        return v
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, dict):
        return {k: enc(x) for k, x in v.items()}
    raise TypeError("cannot write %r" % (v,))


def write(name, payload, by_line=None):
    """`payload` as JSON; the list under `by_line` one item to a line."""
    os.makedirs(OUT, exist_ok=True)
    opts = dict(sort_keys=True, ensure_ascii=False, allow_nan=False)
    with open(os.path.join(OUT, name + ".json"), "w",
              encoding="utf-8") as fh:
        if by_line:
            rest = {k: v for k, v in payload.items() if k != by_line}
            head = json.dumps(rest, **opts)[:-1]
            fh.write(head + (", " if rest else "") + json.dumps(by_line) +
                     ": [\n" + ",\n".join(json.dumps(c, **opts)
                                          for c in payload[by_line]) +
                     "\n]}")
        else:
            json.dump(payload, fh, indent=1, **opts)
        fh.write("\n")


# ════════════════════════════════════════════════════════════════════════════
# settings.json
# ════════════════════════════════════════════════════════════════════════════

def settings():
    configs = []
    for name in ENVS:
        for spacing in (True, False):
            for subscript in (True, False):
                configure(name, spacing, subscript)
                w = fm.WIDTHS
                configs.append({
                    "env": name, "spacing": spacing, "subscript": subscript,
                    "profile": fm.PROFILE, "pad": fm._PAD,
                    "widths": {"narrow": enc(w.narrow),
                               "icons": enc(w.icons),
                               "clusters": w.clusters,
                               "wide": enc(w.wide)},
                    "markSp": fm.MARK_SP, "subDec": fm.SUB_DEC,
                    "rightGrid": list(fm.RIGHT_GRID),
                    "line3Reserved": fm.LINE3_RESERVED,
                    "pwdMaxFallback": fm.PWD_MAX_FALLBACK,
                    "cTok": fm.C_TOK, "cCache": fm.C_CACHE,
                    "cLimTot": fm.C_LIM_TOT, "cSess": fm.C_SESS,
                    "sTok": fm.S_TOK, "sCtx": fm.S_CTX, "sMod": fm.S_MOD,
                    "sRate": fm.S_RATE, "sCache": fm.S_CACHE,
                    "sCost": fm.S_COST, "doingPad": fm.DOING_PAD,
                    "col2Val2W": fm.COL2_VAL2_W,
                    "rightEdge": fm.RIGHT_EDGE_COLS,
                    "truecolor": sp.colour_level() >= 3,
                })
    constants = {k: enc(getattr(fm, k)) for k in (
        "LINE_CLEAR", "EOL_CLEAR", "SI_UNITS", "C_LABEL", "C_TOTALS_LABEL",
        "C_COMPACT_LABEL", "C_AGENTS_LABEL", "S_HUMAN", "S_BOT", "S_TIME",
        "S_DATE", "S_IDLE", "S_STY", "S_PR", "S_DIFF", "S_WORK", "S_SESS",
        "S_WEEK", "S_READ", "S_WRITE", "S_RESET", "S_SUM")}
    constants.update({k: getattr(sp, k)
                      for k in ("R", "DIM", "BOLD", "UNBOLD")})
    escapes = {k: getattr(spec, k) for k in dir(spec)
               if k[:2] in ("F_", "B_") and isinstance(getattr(spec, k), str)}
    write("settings", {"envs": ENVS, "configs": configs,
                       "constants": constants, "escapes": escapes,
                       "trueEscapes": spec.TRUE_COLOURS})
    return len(configs) + len(constants) + 2 * len(escapes)


# ════════════════════════════════════════════════════════════════════════════
# values.json
# ════════════════════════════════════════════════════════════════════════════

INF, NAN = float("inf"), float("nan")

# Every cut in the file, either side of it, and the magnitudes past them.
NUMS = [
    0, -0.0, 1, -1, 0.04, 0.0449, 0.045, 0.05, 0.004, 0.0045, 0.005, 0.0095,
    0.0499, 0.095, 0.5, 0.94, 0.949, 0.95, 0.951, 0.99, 0.994, 0.995,
    0.9949, 0.9994, 0.9995, 0.996, 1.25, 1.5, 2.5, 3.0, 5.45, 9.94, 9.949,
    9.95, 9.951, 9.96, 9.994, 9.995, 9.9951, 10, 10.05, 12.25, 12.35,
    0.125, 0.375, 0.625, 59, 59.9, 60, 61, 89.5, 90, 99, 99.49, 99.5,
    99.94, 99.949, 99.95, 99.96, 99.995, 100, 100.5, 101, 149.5, 150.5,
    999, 999.4, 999.49, 999.5, 999.6, 1000, 1049, 1050, 1234, 1500, 2500,
    9499, 9500, 9949, 9950, 9951, 9999, 10000, 10500, 99499, 99500,
    149999, 999499, 999500, 999501, 999999, 1000000, 1250000, 9.95e6,
    999.4e6, 999.5e6, 1e9, 1.05e9, 1.5e12, 1e15, 2 ** 53, 1e21, 1e22,
    1e300, INF, -INF, NAN, -5.5, -0.5, -999.6, -1e6, 3569, 3569.9, 3570,
    3600, 5399, 5400, 35999, 36000, 84599, 84600, 86400, 863999, 864000,
    spec.MONTH_S - 1, spec.MONTH_S, 10 * spec.MONTH_S, 1e8, 0.1 + 0.2,
    1 / 3, 200 / 3, 5e-324, 1e-10, 2.675, 1.005, 0.015, 0.025,
]


def _random_nums():
    """Figures across every magnitude the rows draw, seeded."""
    rng = random.Random(20261019)
    out = []
    for _ in range(80):
        out.append(round(10 ** rng.uniform(-3, 10), rng.choice((0, 1, 2, 3,
                                                                 6))))
    return out


NUMS += _random_nums()
INTS = [0, 1, -1, 5, 9, 10, 50, 51, 79, 80, 81, 98, 99, 100, 101, 250,
        -7, 999, 1000, 99999, 2 ** 40]

STRINGS = [
    "", "a", "abc", "hello world", "  padded  ", "▴4.8M", "🎯97٪", "🧩▴1k",
    "👍🏽", "👨‍💻", "🇺🇸", "🇺🇸🇬🇧", "🇺", "1️⃣", "♻️", "♻", "🕰️", "🕰", "⏱",
    "⌛🤖", "漢字かな", "٪", "Σ", "‍", "a‍b", "️",
    "\x1b[38;2;1;2;3mab\x1b[0m", "\x1b[2m🔋\x1b[0m 5", "\x1b[m", "\x1b[1",
    "x\tz", "Opus5 🏃 💰12.3", "₁₂₃", "👥👥👥👥",
    "a" * 30, "🧩" * 12, "mixed 🧠 text with 🎨 and 漢 and 🇯🇵 flags",
]

MODELS = ["Opus 5", "Fable 5", "Haiku 4.5", "Sonnet 4.6", "Mythos 1",
          "Opus 4.8", "Opus", "Opus  5 beta", "Opus 5 (1M context)",
          "GPT-5", "", "🤖Opus 5", "Opusx", "Sonnet", " Opus 5", "Fable"]

STAMPS = ["2026-08-16T01:31:00Z", "2026-08-16T01:31:00.123Z",
          "2026-08-16T01:31:00ZZ", "2026-8-6T1:2:3Z", "2026-08-16T01:31:60Z",
          "2026-02-30T00:00:00Z", "٢٠٢٦-08-16T01:31:00Z", "bogus", "",
          "2026-08-16 01:31:00Z", "0001-01-01T00:00:00Z",
          "9999-12-31T23:59:59Z", "2026-08-16T05:13:19Z",
          "2026-08-16T05:13:21Z", "2026-08-16t05:13:20z"]

TARGETS = ["", "0", str(NOW), str(NOW + 1), str(NOW + 59), str(NOW + 3599),
           str(NOW + 90000), str(NOW - 5), "١٧٨٦٨٥٠٠٠٠", "²", "①", "12a",
           "-5", "2026-08-16 07:18", "2026-08-16 05:13", "2026-08-16 05:14",
           "2026-03-08 02:30", "2026-11-01 01:30", "2026-04-05 01:45",
           "2026-10-04 02:15", "2026-1-5 3:4", "2026-01-05  03:04",
           "2026-01-05 03:04 ", "2026-02-30 00:00", "2026-08-16 24:00",
           "garbage", "9999-12-31 23:59", "1970-01-01 00:00",
           "٢٠٢٦-٠٨-١٦ 07:18"]

SPAN_IN = [
    "", "x", "▴4.8M", "🎯", [], [""], sp.Span(""), sp.Span("97٪", "F_GRN",
                                                         True),
    ["🧩 ", sp.Span("▴1k", "F_TUP"), " ", sp.Span("▾2k", "F_TDN")],
    [sp.Span("🔋", None, False, True), ["5", [sp.Span("٪", "F_PNK")]]],
    "a long value that outgrows its field",
]


def values():
    cases = []

    def add(fn, cfg, args, f, tz=None):
        c = {"fn": fn, "cfg": list(cfg) if cfg else None,
             "args": [enc(a) for a in args], "out": enc(run(f, *args))}
        if tz:
            c["tz"] = tz
        cases.append(c)

    # Pure of the settings, run once.
    for d in ["", "now", "5s", "1.5m", "58m", "2h", "3d", "1.4M", "h", "d "]:
        add("reset_dim", None, [d], fm.reset_dim)
    for v in [None, 0, 99999, 100000, 100001, -1, NAN, INF, 0.5]:
        for cut in (100000, 1.0, 0):
            add("mag_dim", None, [v, cut], fm.mag_dim)
    shares = ["", None, "0.5", "0.99", "1", "1.0", "4.9", "5", "6", "abc",
              " 4.9 ", "nan", "inf", "-inf", "1_0", "٣", 0.5, 7, 0]
    for t in shares:
        for s in ("", "4.99", "5.0", "x", None, 3, "0.2"):
            add("share_dims", None, [t, s], fm.share_dims)
    for t in (None, 0, 66, 67, 68, 100, -1, 66.9):
        for s in (None, 66, 67):
            add("cache_dims", None, [t, s], fm.cache_dims)
    for p in INTS + [49.5, 50.5, 80.1, -INF, INF, NAN]:
        add("cache_color", None, [p], fm.cache_color)
    for v in INTS:
        add("pct2", None, [v], fm.pct2)
    for p in NUMS:
        add("pct", None, [p], fm.pct)
    for m in MODELS:
        for field in (spec.VAL_W, 0, 1, 3, 4, 6, 8, -2):
            add("short_model", None, [m, field], fm.short_model)
    for s in STRINGS:
        add("strip_ansi", None, [s], fm.strip_ansi)
        for n in (-1, 0, 1, 2, 3, 5, 10):
            add("fit_head", None, [s, n], fm.fit_head)
            add("fit_path", None, [s, n], fm.fit_path)
    for rule in (False, True):
        add("seg_gap", None, [rule], fm.seg_gap)
    for env in ENVS:
        add("term_profile", None, [ENVS[env]], fm.term_profile)
    for env in COLOUR_ENVS:
        add("colour_level", None, [COLOUR_ENVS[env]], sp.colour_level)
    for prof in ("unknown", "jediterm", "iterm", "tmux", "ghostty", ""):
        w = fm.widths_for(prof)
        cases.append({"fn": "widths_for", "cfg": None, "args": [prof],
                      "out": [enc(w.narrow), enc(w.icons), w.clusters,
                              enc(w.wide)]})

    for cfg in CFGS:
        configure(*cfg)
        for s in STRINGS:
            add("vis_width", cfg, [s], fm.vis_width)
            for n in (-1, 0, 1, 2, 3, 5, 8, 20):
                add("fit_cols", cfg, [s, n], fm.fit_cols)
                add("trunc", cfg, [s, n], fm.trunc)
        for txt in STRINGS[:12] + SPAN_IN:
            for want in (-1, 0, 3, 5, 8):
                for left in (False, True):
                    add("pad_val", cfg, [want, txt, left], fm.pad_val)
                    add("seg", cfg, [want, txt, left], fm.seg)
        for a in ("", "⌛ 5m", [], sp.Span(""), [sp.Span("🔜", "F_SUM")],
                  "much too wide a thing"):
            for b in ("", "🕐 12:04", [sp.Span("99", "F_RED"), "٪"]):
                for want in (0, 6, 14):
                    for gap in (0, 2, -1):
                        add("pair", cfg, [a, b, want, gap], fm.pair)
        for cols in (None, 0, 169, 170, 171, 300):
            add("rules_on", cfg, [cols], fm.rules_on)
        rows = [[], ["🎨 expl"], ["🎨 expl", [sp.Span("🤖", "F_PUR"), "O⁵"]],
                ["a", "b", "c", "d", "e", "f"],
                ["", "", sp.Span("x", "F_RED")],
                ["way too wide for its cell to hold"]]
        for cells in rows:
            for grid in (None, [3, 0, 5]):
                for rule in (False, True):
                    add("grid_row", cfg, [cells, grid, rule], fm.grid_row)
        for v in ["1.25k", ".38", "5", "", "1.2.3", "a.b", ".", "x.5y.7",
                  "1.٣", "-0.5", "12.", "0.000"]:
            add("sub_dec", cfg, [v], fm.sub_dec)
        for v in ["1.25", ".38", "5", "", "12.", "1₂", "0.13", "100", "abc",
                  "9.9", "-1.5"]:
            for ip in (-2, 0, 2, 3):
                for fp in (0, 1, 2):
                    for suf in ("", "٪", "k"):
                        add("dec_align", cfg, [v, ip, fp, suf], fm.dec_align)
        for n in NUMS:
            add("humanize", cfg, [n], fm.humanize)
            add("rate_fig", cfg, [n], fm.rate_fig)
            add("money_fmt", cfg, [n], fm.money_fmt)
            add("money_fig", cfg, [n], fm.money_fig)
            add("money_cell", cfg, [n], fm.money_cell)
            add("signed", cfg, [n], fm.signed)
            for places in (0, 1, 2, 3):
                add("plan_pct", cfg, [n, places], fm.plan_pct)
            for digits in (2, 3, 4):
                add("limit_pct", cfg, [n, digits], fm.limit_pct)
            for digits in (2, 3):
                add("dur_fmt", cfg, [n, digits], fm.dur_fmt)
        for n in INTS + [0.5, -3.25]:
            for whole in (0, 1, 3, 200000, 1000000, -400, NAN):
                add("signed_pct", cfg, [n, whole], fm.signed_pct)
        for now in (NOW, NOW + 0.7, NOW - 0.5, INF):
            for ts in STAMPS:
                add("elapsed_short", cfg, [ts, now], fm.elapsed_short)
        for tz in ZONES:
            set_tz(tz)
            for now in (NOW, NOW + 0.9):
                for target in TARGETS:
                    add("short_dur", cfg, [target, now], fm.short_dur, tz)
    return cases


def term_cols():
    """term_cols over scripted process tables: each scenario's `ps` maps a
    pid to its output, or to null for a run that raised, and `winsize` a
    device to its columns."""
    scenarios = [
        {"ppid": 500, "ps": {"500": "ttys003   1\n"},
         "winsize": {"/dev/ttys003": 211}},
        {"ppid": 500, "ps": {"500": "??  400", "400": " ttys001 1 "},
         "winsize": {"/dev/ttys001": 80}},
        {"ppid": 500, "ps": {"500": "?  400", "400": "pts/3 1"},
         "winsize": {"/dev/pts/3": None}},
        {"ppid": 1, "ps": {}, "winsize": {}},
        {"ppid": 0, "ps": {}, "winsize": {}},
        {"ppid": 500, "ps": {"500": ""}, "winsize": {}},
        {"ppid": 500, "ps": {"500": "ttys003"}, "winsize": {}},
        {"ppid": 500, "ps": {"500": None}, "winsize": {}},
        {"ppid": 500, "ps": {"500": "??  x4"}, "winsize": {}},
        {"ppid": 500, "ps": {"500": "??  +400", "400": "ttys9 1"},
         "winsize": {"/dev/ttys9": 120}},
        {"ppid": 7, "ps": {str(p): "?? %d" % (p + 1) for p in range(7, 20)},
         "winsize": {}},
        {"ppid": 7, "ps": {str(p): "?? %d" % (p + 1) for p in range(7, 12)},
         "winsize": {}},
        {"ppid": 500, "ps": {"500": "ttys003 400", "400": "ttys004 1"},
         "winsize": {"/dev/ttys003": 0, "/dev/ttys004": 99}},
        {"ppid": 500, "ps": {"500": "ttys003 ٤٠٠", "400": "ttys004 1"},
         "winsize": {"/dev/ttys004": 64}},
    ]

    class Done:
        def __init__(self, stdout):
            self.stdout = stdout

    class FakeSubprocess:
        def __init__(self, table):
            self.table = table

        def run(self, argv, **_kw):
            out = self.table.get(argv[-1])
            if out is None:
                raise OSError("no such process")
            return Done(out)

    real_getppid, real_sub, real_winsize = os.getppid, fm.subprocess, \
        fm._winsize
    try:
        for s in scenarios:
            os.getppid = lambda s=s: s["ppid"]
            fm.subprocess = FakeSubprocess(s["ps"])
            fm._winsize = lambda path, s=s: s["winsize"].get(path)
            s["out"] = enc(run(fm.term_cols))
    finally:
        os.getppid = real_getppid
        fm.subprocess = real_sub
        fm._winsize = real_winsize
    return scenarios


# ════════════════════════════════════════════════════════════════════════════
# spans.json
# ════════════════════════════════════════════════════════════════════════════

def span_lists():
    """Hand-made lists for each of join's special cases, then seeded random
    ones over the colours, attributes and blanks that meet them."""
    S = sp.Span
    hand = [
        [S("👤", "F_CHAT_U"), S("hi there", "F_CHAT_U", False, False,
                                "B_DRK")],
        [S("👤", "F_CHAT_U", False, True), S("x", "F_CHAT_U", False, False,
                                             "B_DRK")],
        [S("▴", "F_TUP"), S("1k", "F_TUP"), S("▾", "F_TDN"), "2k"],
        [S("b", None, False, True), S("c", "F_RED", False, True)],
        [S("", "F_RED"), S("", None, True)],
        ["  a  ", S(" ", "F_RED"), "  "],
        ["   ", ""],
        [S("x", "", False, False, "")],
        [S("x", "F_NOPE")],
        [S("x", None, False, False, "B_NOPE")],
        [S("x", "F_RULE"), S("y", "F_SPIN", True), S("z", "F_LIM_WEEK")],
    ]
    rng = random.Random(4242)
    colours = [None, "F_PNK", "F_TUP", "F_TDN", "F_RED", ""]
    texts = ["", " ", "  ", "a", "▴", "🎯", "99٪ ", " x ", "\t"]
    for _ in range(200):
        items = []
        for _ in range(rng.randint(0, 5)):
            if rng.random() < 0.2:
                items.append(rng.choice(texts))
            else:
                items.append(S(rng.choice(texts), rng.choice(colours),
                               rng.random() < 0.3, rng.random() < 0.2,
                               "B_DRK" if rng.random() < 0.2 else None))
        cases_nested = items if rng.random() < 0.7 else [items[:2],
                                                          items[2:]]
        hand.append(cases_nested)
    return hand


def spans_cases():
    cases = []
    configure("unknown", True, False)
    for x in span_lists():
        c = {"in": enc(x)}
        c["spans"] = enc(sp.spans(x))
        c["text"] = sp.text(x)
        c["rstrip"] = enc(sp.rstrip(x))
        c["lstrip"] = enc(sp.lstrip(x))
        c["lstrip_sp"] = enc(sp.lstrip(x, " "))
        c["indent"] = sp.indent(x)
        c["join"] = [enc(run(sp.join, x, close, runs))
                     for close in (False, True) for runs in (False, True)]
        c["width"] = {}
        for prof in ("unknown", "jediterm", "tmux"):
            configure(prof, True, False)
            c["width"][prof] = sp.width(x)
        cases.append(c)
    ink = [enc(sp.ink(c, d)) for c in (None, "F_RED") for d in (False, True)]
    paint = [enc(sp.paint(sp.ink("F_AMB", True), "97٪")),
             enc(sp.paint(sp.Span("old", "F_RED", False, True, "B_DRK"),
                          "new"))]
    write("spans", {"cases": cases, "ink": ink, "paint": paint},
          by_line="cases")
    return len(cases) * 11 + len(ink) + len(paint)


def main():
    saved = {k: os.environ.get(k) for k in PROFILE_VARS + ("TZ",)}
    try:
        n = settings()
        cases = values()
        write("values", {"cases": cases, "term_cols": term_cols()},
              by_line="cases")
        n += spans_cases()
        n += len(cases)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        time.tzset()
        importlib.reload(fm)
    print("formatting: %d cases" % n)


if __name__ == "__main__":
    main()
