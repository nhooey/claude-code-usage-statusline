#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The status line's 🛫: the sampler behind it and the cell it fills.

The goldens cannot show this figure.  They pin the clock, so every render of
a case sees the same second and the sampler takes one reading and reports no
slope — which is the correct blank for a session's first tick, and it is
what every golden records.  The slope itself, the tick, the depth of the
history and what a damaged file costs are pinned here, against a scratch
TMPDIR, with the clock stepped by hand.  The brightness-as-magnitude rule
(MAG_TOK and mag_dim) is pinned here too, as a rule rather than as escapes.

Run:  python3 tests/rate.py
"""

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(DIR, "..", "coding-agent-usage-line.py")

pass_n = fail_n = 0


def ok(name):
    global pass_n
    pass_n += 1
    print("  ok    %s" % name)


def bad(name, detail=""):
    global fail_n
    fail_n += 1
    print("  FAIL  %s" % name)
    if detail:
        for line in str(detail).splitlines():
            print("          " + line)


def check(name, got, want):
    if got == want:
        ok(name)
    else:
        bad(name, "got  %r\nwant %r" % (got, want))


def near(name, got, want, tol=1e-6):
    if got is not None and want is not None and abs(got - want) <= tol:
        ok(name)
    else:
        bad(name, "got  %r\nwant %r" % (got, want))


ANSI = re.compile(r"\x1b\[[0-9;]*m")
NOW = 1786847000.0      # pin-env.sh's PIN_NOW, for no reason but habit



def main():
    scratch = tempfile.mkdtemp(prefix="statusline-rate.")
    os.environ["TMPDIR"] = scratch
    os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = os.path.join(scratch, "state")
    # The profile the goldens pin, so _PAD is empty and the cell widths
    # below are the ones in the golden files.
    os.environ.pop("TMUX", None)
    os.environ.pop("TERM_PROGRAM", None)
    os.environ["TERMINAL_EMULATOR"] = "JetBrains-JediTerm"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from coding_agent_usage_line import claude as sl
    from coding_agent_usage_line import claude_subagent_render as sr
    sl.set_mark_spacing(True)
    try:
        run(sl, sr, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("\npass %d   fail %d" % (pass_n, fail_n))
    return 1 if fail_n else 0


def run(sl, sr, scratch):
    tick = sl.RATE_TICK_S
    path = sl._rate_path("s1")

    print("the sampler")
    check("one sample has no slope: the first tick is None",
          sl.session_rate("s1", 1000, NOW), None)
    check("and it was written, so the second tick has something to lean on",
          json.load(open(path)), [[NOW, 1000.0]])
    check("a render inside the tick takes no sample and still has no slope",
          (sl.session_rate("s1", 1500, NOW + 2), json.load(open(path))),
          (None, [[NOW, 1000.0]]))
    near("one tick on, the slope is rise over the RECORDED span",
         sl.session_rate("s1", 2000, NOW + tick), 1000.0 / tick)
    near("a late render divides by the time that actually passed, not the tick",
         sl.session_rate("s1", 2000 + 300 * 20, NOW + tick + 20),
         (300 * 20 + 1000) / (tick + 20))
    check("a total that fell — a transcript re-read shorter — reads zero, not negative",
          sl.session_rate("s1", 10, NOW + 2 * tick + 20), 0.0)
    # Fill the history past its depth: the oldest reading falls off, so the
    # slope is over the last RATE_SAMPLES readings and not the session.
    t = NOW + 2 * tick + 20
    for i in range(sl.RATE_SAMPLES + 4):
        t += tick
        r = sl.session_rate("s1", 100000 + i * 500, t)
    kept = json.load(open(path))
    check("the history is cut to RATE_SAMPLES readings",
          len(kept), sl.RATE_SAMPLES)
    near("and the slope is over those alone: a steady 500 a tick reads 100/s",
         r, 500.0 / tick)
    check("no session id: nothing sampled, nothing said",
          (sl.session_rate("", 5, NOW), os.path.exists(sl._rate_path(""))),
          (None, False))
    check("no total — no transcript — the same",
          sl.session_rate("s2", None, NOW), None)
    with open(sl._rate_path("s3"), "w") as fh:
        fh.write("{not json")
    check("a damaged file starts the history over rather than raising",
          (sl.session_rate("s3", 7, NOW), json.load(open(sl._rate_path("s3")))),
          (None, [[NOW, 7.0]]))
    with open(sl._rate_path("s4"), "w") as fh:
        json.dump({"a": 1}, fh)
    check("a file of the wrong shape, likewise",
          sl.session_rate("s4", 7, NOW), None)

    print("the cell")
    cell = lambda rate, pct: ANSI.sub("", sl.render_rate_cache(rate, pct))
    check("🛫 the rate, /s, then 🎯 and the hit rate: column 2's shape, 13 wide",
          (cell(200.0, 98), sl.vis_width(cell(200.0, 98))),
          ("\U0001F6EB200/s \U0001F3AF98٪", 13))
    check("a short rate right-aligns under ▴'s figure; a short percentage under ▾'s",
          cell(7.0, 5), "\U0001F6EB  7/s \U0001F3AF 5٪")
    check("past a thousand the figure rounds to the unit and keeps the width",
          cell(1700.0, 50), "\U0001F6EB 2k/s \U0001F3AF50٪")
    check("no slope yet: the mark, a blank field, the cache — still 13",
          (cell(None, 98), sl.vis_width(cell(None, 98))),
          ("\U0001F6EB      \U0001F3AF98٪", 13))
    check("a rate of nothing is a figure, not a blank",
          cell(0.0, 98), "\U0001F6EB  0/s \U0001F3AF98٪")
    check("a full cache clamps at 99 like the cell it replaced",
          cell(0.0, 100), "\U0001F6EB  0/s \U0001F3AF99٪")
    check("no usage at all: no cell", cell(50.0, -1), "")
    check("the model: 🤖, the two-character spec with its superscript "
          "version, and the effort's glyph against it",
          [ANSI.sub("", sl.render_model(m, e)) for m, e in
           (("Opus 5 (1M context)", "high"), ("Haiku 4.5", "max"),
            ("Sonnet 4.6", ""), ("Fable 5", "null"), ("Opus 5", "odd"),
            ("", "high"))],
          ["\U0001F916O⁵\U0001F3C3", "\U0001F916H⁴\U0001F525",
           "\U0001F916S⁴", "\U0001F916F⁵", "\U0001F916O⁵\U0001F6B6", ""])
    mc = lambda m, e, c: ANSI.sub("", sl.render_model_cost(m, e, c))
    check("and beside the 💰 on column 2's first row since 2026-09-16: the "
          "model held at its full width, one space, the cost — the column",
          (mc("Opus 5", "high", "115.2"), mc("Opus 5", "", "1234.5"),
           mc("", "", "115.2"), mc("Opus 5", "high", ""), mc("", "", ""),
           sl.vis_width(mc("Opus 5", "high", "115.2")),
           sl.vis_width(mc("Opus 5", "", "115.2"))),
          ("🤖O⁵🏃 💰115 ", "🤖O⁵   💰1.2k",
           "       💰115 ", "🤖O⁵🏃 ", "",
           sl.RIGHT_GRID[1], sl.RIGHT_GRID[1]))
    check("the tokens and the 🛫 cell under it fill the same column",
          (sl.vis_width(cell(200.0, 98)),
           sl.vis_width(ANSI.sub("", sl.render_tokens(2700000, 841000)))),
          (sl.RIGHT_GRID[1], sl.RIGHT_GRID[1]))
    ctx = lambda: ANSI.sub("", sl.render_ctx(11, 115000))
    share = lambda mark, t, s_: ANSI.sub("", sl.render_cache_share(mark, t, s_))
    # Where a figure ENDS: the columns up to and including its last glyph.
    end = lambda s_, last: sl.vis_width(s_.split(last)[0]) + 1
    check("🧠 heads column 3, its unit under the 🎤 figures' ٪ and its "
          "percentage on the column's edge, where 🎮's figures end",
          (ctx(), sl.vis_width(ctx()), sl.RIGHT_GRID[2],
           end(ctx(), "k"), end(share(sl.S_READ, 34, 32), "٪")),
          ("🧠   115k    11٪", 16, 16, 9, 9))

    print("column 3: where the bill went, at two scopes")

    def turn(usd_in, usd_out, usd_cr, usd_cw):
        # A Turn with only its four dollar sums set: all column 3 reads.
        return sl.Turn("", "", 0, 0, 0, 0, 0, 1, 0.0, None,
                       usd_in, usd_out, usd_cr, usd_cw)
    # Two turns whose per-turn shares average to (30, 52) and whose dollars,
    # summed first, give (14, 74): the second is nine times the first, so
    # the session's figure has to be nearly the second's, not halfway.
    TURNS = [turn(0.25, 0.0, 0.5, 0.25), turn(0.9, 0.0, 0.9, 7.2)]
    check("📖 then 🎤 and 🎮 ahead of a whole percent each: 16 wide, the column",
          (share(sl.S_READ, 34, 32), sl.vis_width(share(sl.S_READ, 34, 32)),
           sl.RIGHT_GRID[2]),
          ("📖 🎤 34٪ 🎮 32٪", 16, 16))
    check("a short share right-aligns in its three, so the ٪ stays put",
          share(sl.S_WRITE, 7, 0), "📝 🎤  7٪ 🎮  0٪")
    check("a full share is drawn 💯, in the same three columns",
          (share(sl.S_READ, 100, 99), sl.vis_width(share(sl.S_READ, 100, 99))),
          ("📖 🎤 💯٪ 🎮 99٪", 16))
    check("a scope with no figure draws ?; both missing draws nothing",
          (share(sl.S_READ, None, 7), share(sl.S_READ, None, None)),
          ("📖 🎤   ? 🎮  7٪", ""))
    check("the figure is the cost line's: turn_shares, then the session summed "
          "before dividing — not the per-turn shares averaged",
          [sl.turn_shares(t) for t in TURNS] + [sl.session_cache_shares(TURNS)],
          [(50, 25), (10, 80), (14, 74)])
    check("no cost, no share: a compaction alone, and an empty session",
          (sl.turn_shares(TURNS[0]._replace(usd_in=0, usd_out=0, usd_cr=0,
                                             usd_cw=0)),
           sl.session_cache_shares([])),
          ((None, None), (None, None)))
    sl.set_mark_spacing(False)
    # fmt's binding, not sl's: set_mark_spacing rebinds the grid in
    # formatting, and the star-import above captured the value at load.
    check("--no-mark-spacing closes both fields and the column follows, to 14",
          (share(sl.S_READ, 34, 32), sl.vis_width(share(sl.S_READ, 34, 32)),
           sl.fmt.RIGHT_GRID[2]),
          ("📖 🎤34٪ 🎮32٪", 14, 14))
    check("and 🧠's two edges follow the share row's in",
          (ctx(), sl.vis_width(ctx()), end(ctx(), "k"),
           end(share(sl.S_READ, 34, 32), "٪")),
          ("🧠  115k   11٪", 14, 8, 8))
    sl.set_mark_spacing(True)

    print("brightness as magnitude")
    # The goldens pin every escape on the status line; what is pinned here is
    # the RULE — one fixed cut per kind, dim under it, nothing at or over it,
    # and a dim first field reset before the second — so a re-bless cannot
    # quietly bless a rate that dims the 🎯 beside it.
    D = sl.DIM
    check("mag_dim: DIM under the cut, nothing at it, nothing over it, "
          "nothing for no reading",
          [sl.mag_dim(v, 100.0) for v in (99.9, 100.0, 1e9, None)],
          [D, "", "", ""])
    def dims(s):
        # which fields carry DIM, reading the escapes as a list of
        # (dim?, text) runs, stripped of colour
        # (dim?, text) runs, stripped of colour; a mark drawn ahead of the
        # colour, outside it, is not part of the run
        runs, cur, dim = [], "", False
        for tok in re.split(r"(\x1b\[[0-9;]*m)", s):
            if tok == D:
                dim = True
            elif tok == sl.R:
                if cur.strip():
                    runs.append((dim, cur.strip()))
                cur, dim = "", False
            elif tok.startswith("\x1b"):
                cur = ""
            else:
                cur += tok
        return runs
    check("🧩: each half against MAG_TOK on its own, arrow included",
          dims(sl.render_tokens(sl.MAG_TOK, sl.MAG_TOK - 1000)),
          [(False, "▴100k"), (True, "▾ 99k")])
    check("🛫: a trickle dims and the 🎯 beside it does not inherit the DIM",
          dims(sl.render_rate_cache(999.0, 70)),
          [(True, "999/s"), (False, "70٪")])
    # 🎯's own rule, inverted like its tiers: the green tier is the one
    # nothing has to be done about, so it is the dim one; amber and red are
    # events and stay bright.  The DIM is for the figure, not the mark — the
    # 🎯 is drawn ahead of the colour, on both readouts.
    # The shares: 🎤 and 🎮 dim off the WEEKLY figures, on both rows alike,
    # so the 5-hour row — always the larger share — never flips on a
    # different turn than the weekly row.  An agent's pair takes a cut of
    # its own, a fifth of the turn's, both cells together.  Missing shares
    # are not dimmed here: they draw "?" and that was dim already.
    check("share_dims: the turn at 1٪ of the week, the session at 5٪",
          [sl.share_dims("0.99", "4.9"), sl.share_dims("1", "5"),
           sl.share_dims("", "")],
          [(True, True), (False, False), (False, False)])
    check("the agent's cut is a fifth of the turn's",
          (sl.MAG_SHARE_AGENT, sl.MAG_SHARE_AGENT < sl.MAG_SHARE_TURN),
          (0.2, True))
    check("🔋 row: 🎤 and 🎮 dim on the caller's word, 💳 as before",
          [d for d, _ in dims(sl.render_limit(
              sl.S_SESS, "38", "5", "", "0.4", sl.F_LIM_SESS, True, NOW,
              True, True))],
          [True, True, True])
    check("🪫 row: bright when told nothing, whatever the figures",
          [d for d, _ in dims(sl.render_limit(
              sl.S_WEEK, "84", "0.01", "", "0.001", sl.F_LIM_WEEK, False,
              NOW))],
          [False, False, False])
    check("agent 🔋 🪫: dim as a pair, the mark outside the DIM",
          [(sl.DIM in sr.render_agent_limit(sl.E_SESS, "38", 3.0,
                                             sl.F_LIM_SESS, True, dim),
            sr.render_agent_limit(sl.E_SESS, "38", 3.0, sl.F_LIM_SESS,
                                  True, dim).startswith(sl.E_SESS))
           for dim in (True, False)],
          [(True, True), (False, True)])
    check("🎯: green is dim, amber and red are not, on the status line",
          [dims(sl.render_rate_cache(None, p))[0][0] for p in (81, 80, 50)],
          [True, False, False])
    check("🎯: the same on the agent row, and the mark stays bright",
          [(sl.DIM in sr.render_agent_cache(p),
            sr.render_agent_cache(p).startswith(sl.E_CACHE))
           for p in (81, 80)],
          [(True, True), (False, True)])
    check("🛫: 1k/s is full flight; no slope is no DIM either",
          [dims(sl.render_rate_cache(1000.0, 70))[0][0],
           D in sl.render_rate_cache(None, 70)],
          [False, False])
    check("🧠: the size takes the token cut, the percentage stays bright",
          dims(sl.render_ctx(45, sl.MAG_TOK - 1000)),
          [(True, "99k"), (False, "45٪")])
    check("💰: a dollar is the line, on the status line and the agent rows",
          [dims(sl.render_cost(v))[0][0] for v in ("0.99", "1.0", "115")],
          [True, False, False])
    check("⌛ row: ten minutes, each figure on its own, Σ included",
          [d for d, _ in dims(sl.render_elapsed(
              5 * 3600, NOW - 9 * 3600, 599.0, NOW)) if _ != "Σ"],
          [True, False, False, False])
    check("💾: a hundred lines, each half on its own count",
          dims(sl.render_diff("100", "99")),
          [(False, "+ 100"), (True, "-  99")])
    check("column 3: each scope's pair dims off its own 📖, under two thirds",
          [sl.cache_dims(t, s_) for t, s_ in
           ((66, 67), (67, 66), (None, 10), (90, None))],
          [(True, False), (False, True), (False, True), (False, False)])
    check("and both rows take the caller's word, so 📝 flips with 📖",
          [dims(sl.render_cache_share(sl.S_READ, 34, 80, sl.F_SHARE, True, False)),
           dims(sl.render_cache_share(sl.S_WRITE, 7, 20, sl.F_SHARE, True, False))],
          [[(True, "34٪"), (False, "80٪")], [(True, "7٪"), (False, "20٪")]])
    check("a ? is dim whatever the caller says; 💯 is bright",
          dims(sl.render_cache_share(sl.S_READ, None, 100, sl.F_SHARE, False, False)),
          [(True, "?"), (False, "💯٪")])
    check("the agent row's ⌛ 🛫 🧠 take the same cuts",
          [dims(sr.render_agent_clock(1000 * (NOW - 599), NOW))[0][0],
           dims(sr.render_agent_clock(1000 * (NOW - 600), NOW))[0][0],
           dims(sr.render_agent_rate(999.0))[0][0],
           dims(sr.render_agent_rate(1000.0))[0][0],
           dims(sr.render_agent_ctx(sl.MAG_TOK - 1))[0][0],
           dims(sr.render_agent_ctx(sl.MAG_TOK))[0][0]],
          [True, False, True, False, True, False])


if __name__ == "__main__":
    sys.exit(main())
