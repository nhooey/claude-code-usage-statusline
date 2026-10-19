#!/usr/bin/env python3
"""Write the differential cases that pin mod/src/claude_render.ts to
claude_render.py.

    /usr/bin/python3 tests/fixtures/gen/render.py

The 141 status goldens draw every cell, but all of them under one terminal
profile, one zone and a handful of transcripts, so they never reach the
other profiles' padded icons, a clock off UTC, a background shell, an ETA
an agent pushed out, or most of the Doing field's states.  These reach
them, one call at a time:

  render/cells.json   each cell renderer over awkward inputs under each of
                      CFGS, one case to a line: {"fn", "cfg", "args",
                      "out"}, and "tz" where the cell reads the local zone.
  render/status.json  render_status over hand-made records at several
                      widths, under STATUS_CFGS: each variant's records
                      once under "records", each case naming its variant,
                      and "home" the HOME it shortens the working
                      directory by.

The encoding is gen/formatting.py's: a Span is {"span": [text, colour, dim,
bold, bg]}, a float JSON cannot carry is {"$float": ...}, and a call that
raises is {"raises": true}.  A NamedTuple record is {"rec": its fields},
under their Python names.

claude_render.py star-imports formatting.py, so each configuration reloads
both, the way a process with that environment and those flags has them.
The environment, the zone and both modules are put back afterwards.
"""
import importlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(FIXTURES))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import formatting as gen  # noqa: E402  gen/formatting.py, for its codec
from coding_agent_usage_line import claude_render as cr  # noqa: E402
from coding_agent_usage_line import claude_records as rec  # noqa: E402
from coding_agent_usage_line import formatting as fm  # noqa: E402

OUT = os.path.join(FIXTURES, "render")

CFGS = (
    ("unknown", True, False), ("unknown", False, True),
    ("jediterm", True, False), ("jediterm", False, False),
    ("iterm", True, True), ("tmux", False, False),
)
ZONES = ("UTC", "America/New_York", "Asia/Kolkata")
NOW = 1786847000
HOME = "/home/fixture"


def configure(env_name, spacing, subscript):
    for var in gen.PROFILE_VARS:
        os.environ.pop(var, None)
    os.environ.update(gen.ENVS[env_name])
    importlib.reload(fm)
    importlib.reload(cr)
    fm.set_mark_spacing(spacing)
    fm.set_subscript_decimals(subscript)


def enc(v):
    if isinstance(v, gen.sp.Span):
        return gen.enc(v)
    if isinstance(v, tuple) and hasattr(v, "_fields"):
        return {"rec": {k: enc(x) for k, x in zip(v._fields, v)}}
    if isinstance(v, (list, tuple)):
        return [enc(x) for x in v]
    return gen.enc(v)


# ════════════════════════════════════════════════════════════════════════════
# Records.
# ════════════════════════════════════════════════════════════════════════════

TR = rec.Transcript(
    tok_up=2722123, tok_down=841300, cache_pct=98, ctx_tokens=114902,
    user_ts="2026-08-16T02:15:20Z", user_text="Why two durations?",
    asst_ts="2026-08-16T02:20:00Z", asst_text="Because one is idle.",
    busy_s=13800.0, start_s=NOW - 33480.0, tool_s=3450.0, blocked_s=300.0,
    turn_s=NOW - 480.0, last_seen=NOW - 180.0)
PAY = rec.Payload(
    current_dir=HOME + "/src/statusline-fixture/deep/tree",
    project_dir=HOME + "/src/statusline-fixture/deep/tree",
    model="Opus 5 (1M context)", model_id="claude-opus-5[1m]",
    ctx_window="1000000", transcript="/x.jsonl", cost_usd="114.63",
    lines_added="3443", lines_removed="214", output_style="default",
    effort="high", session_id="s", rl_session_pct="15",
    rl_session_reset="", rl_weekly_pct="87", rl_weekly_reset="",
    pr_number="")
GIT = rec.Git(in_git=True, branch="golden-clean", dirty=False,
              toplevel="/scratch/repo", main_root="/scratch/repo",
              is_worktree=False)
LIM = rec.Limits(
    session_pct="15", session_reset="2026-08-16 08:30",
    session_share="3.8436", weekly_pct="87",
    weekly_reset="2026-08-18 07:00", weekly_share="8.44954",
    session_turn="1.16525", weekly_turn="1.56314")
CACHE = rec.CacheShares(turn_read=34, turn_write=7, sess_read=32,
                        sess_write=7)


def status_variants():
    """(name, payload, transcript, git, limits, cache, ctx_window, rate)."""
    base = (PAY, TR, GIT, LIM, CACHE, 1000000, 210.5)
    out = [("base",) + base]

    def add(name, pay=None, tr=None, git=None, lim=None, cache=None,
            win=None, rate=False):
        out.append((name, pay or PAY, tr or TR, git or GIT, lim or LIM,
                    cache or CACHE, 1000000 if win is None else win,
                    210.5 if rate is False else rate))

    add("background", tr=TR._replace(shells=2, monitors=1))
    add("monitor-only", tr=TR._replace(monitors=3))
    add("dirty-long", git=GIT._replace(
        dirty=True, branch="feature/a-very-long-branch-name-for-fitting"),
        pay=PAY._replace(current_dir=HOME + "/a/b/c/d/e/f/g/h/i/j/k/l/m"))
    add("no-git", git=rec.NO_GIT, pay=PAY._replace(current_dir="/opt/x"))
    add("home", pay=PAY._replace(current_dir=HOME, pr_number="1234",
                                 output_style="Explanatory"))
    add("home-prefix", pay=PAY._replace(current_dir=HOME + "x/y"))
    add("tool", tr=TR._replace(tool_at=NOW - 42.0, queued=3,
                               compactions=120))
    add("wait", tr=TR._replace(wait_at=NOW - 700.0, user_ts="2026-09",
                               asst_text=""))
    add("idle", tr=TR._replace(idle_at=NOW - 30.0, user_text=""))
    add("quiet", tr=TR._replace(last_seen=NOW - 900.0), rate=None)
    add("quiet-short", tr=TR._replace(last_seen=NOW - 90.0))
    add("eta", tr=TR._replace(eta=(NOW - 60.0, 300.0)))
    add("eta-over", tr=TR._replace(eta=(NOW - 600.0, 120.0)))
    add("eta-zero", tr=TR._replace(eta=(NOW - 100.0, 0.0)))
    add("eta-agents", tr=TR._replace(
        eta=(NOW - 60.0, 30.0),
        agent_etas=((NOW + 900.0, NOW - 10.0), (NOW + 9000.0, NOW - 4000.0),
                    (None, NOW - 5.0), (NOW + 50.0, None))))
    add("eta-agent-only", tr=TR._replace(
        turn_s=0.0, agent_etas=((NOW + 400.0, NOW - 10.0),)))
    add("est-ctx", tr=TR._replace(ctx_est=True, ctx_tokens=76000,
                                  cache_pct=40), win=200000)
    add("no-transcript", tr=rec.EMPTY_TRANSCRIPT, lim=rec.NO_LIMITS,
        cache=rec.NO_CACHE_SHARES, rate=None)
    add("limits-full", lim=LIM._replace(
        session_pct="99.7", weekly_pct="100", session_share="",
        weekly_turn="", session_reset="2026-08-16 07:05",
        weekly_reset="garbage"), cache=rec.CacheShares(100, None, 3, 99))
    add("odd-payload", pay=PAY._replace(
        model="claude-haiku-4-5-20251001", effort="weird",
        cost_usd="nan", lines_added="1e400", lines_removed="x",
        output_style="null"))
    return out


# ════════════════════════════════════════════════════════════════════════════
# The cases.
# ════════════════════════════════════════════════════════════════════════════

def cells(cfg):
    out = []

    def add(fn, *args, tz=None):
        if tz:
            gen.set_tz(tz)
        f = getattr(cr, fn)
        out.append({"fn": fn, "cfg": list(cfg), "args": enc(list(args)),
                    "out": enc(gen.run(f, *args)), **({"tz": tz} if tz
                                                      else {})})

    for up, down in ((None, 0), (0, 0), (99999, 100000), (999600, 5),
                     (2722123, 841300), (12345678901, 1)):
        add("render_tokens", up, down)
        add("render_tokens", up, down, fm.COL2_VAL2_W)
    for t in (TR, TR._replace(tool_at=5.0), TR._replace(wait_at=6.0),
              TR._replace(idle_at=7.0), TR._replace(last_seen=0.0)):
        add("main_doing", t)
    for rate in (None, 0.0, 12.5, 999.4, 1000.0, 123456.0):
        for cp in (None, -1, 0, 15, 50, 98, 100):
            add("render_rate_cache", rate, cp)
        for mark in (fm.E_WORK, fm.E_TOOL, fm.E_WAIT):
            for secs in (None, 0.0, 59.9, 60.0, 599.0, 600.0, 7200.0):
                add("render_rate_cache", rate, 97, mark, secs)
    for pct, tok, est in ((None, 5, False), (0, 0, False), (11, 114902, False),
                          (100, 1000000, True), (7, 76000, True),
                          (250, 2500000, False)):
        add("render_ctx", pct, tok, est)
    for c in ("", "null", "0", "0.4", "9.96", "114.63", "999.5", "1234",
              "nan", "inf", "1e400", "x", " 5 ", "-3"):
        add("render_cost", c, fm.E_COST)
        add("render_model_cost", "Opus 5", "high", c)
        add("render_model_cost", "", "", c)
    for pct, delta, resets, turn in (
            ("", "1", "", ""), ("x", "1", "", ""), ("15", "", "", ""),
            ("15", "3.8436", "1786847400", "1.16525"),
            ("99.5", "0.004", "1786847000", "100"),
            ("87", "8.44954", "2026-08-18 07:00", "0"),
            ("0.3", "x", "2026-08-16 08:30", "y"),
            ("62.4", "45", "1786850000", "9.96"),
            ("100", "100", "garbage", "99.4")):
        for tz in ZONES[:2]:
            add("render_limit", "🔋 ", pct, delta, resets, turn,
                "F_LIM_SESS", True, NOW, False, True, tz=tz)
        add("render_limit", "🪫 ", pct, delta, resets, turn,
            "F_LIM_WEEK", False, NOW, True, False, tz="UTC")
    for turn, sess in ((None, None), (61, None), (None, 45), (0, 100),
                       (99, 3), (100, 100)):
        add("render_cache_share", "📖 ", turn, sess, "F_SHARE", True, False)
        add("render_cache_share", "📝 ", turn, sess, "F_SHARE", False, True)
    for a, r in (("", "1"), ("0", "0"), ("3443", "214"), ("99", "100"),
                 ("99999", "1e3"), ("inf", "nan"), ("x", ""), ("-5", "2.9")):
        add("render_diff", a, r)
    for pr in ("", "null", "7", "12345"):
        add("render_pr", pr)
    for m in ("", "Opus 5", "Opus 5 (1M context)", "claude-opus-5[1m]",
              "claude-haiku-4-5-20251001", "sonnet", "Sonnet 4.5",
              "claude-fable-1", "mythos-12-3", "gpt-5 thing", "x",
              "claude-opus-20251001", "Opus ٥", "HAIKU 3"):
        add("model_label", m)
        add("model_spec", m)
        for e in ("", "null", "low", "medium", "high", "xhigh", "max", "?"):
            add("render_model", m, e)
    for e in ("low", "medium", "high", "xhigh", "max", "", "turbo"):
        add("effort_glyph", e)
    for q, c in ((0, 0), (2, 0), (0, 1), (2, 1), (150, 3)):
        add("render_queue", q, c)
    for s in ("", "default", "null", "Explanatory", "ab", "Ünïcödé🎨x"):
        add("render_style", s)
    for now in (NOW, NOW + 0.999, 0.0, 1798761599.5):
        for tz in ZONES:
            add("render_time", now, tz=tz)
            add("render_date", now, tz=tz)
    for eta, start, status, end in (
            (None, None, "running", None), ((), None, "running", None),
            ((NOW - 60.0, 300.0), (NOW - 600.0) * 1000, "running", None),
            ((NOW - 60.0, 300.0), None, "running", None),
            ((NOW - 60.0, 0.0), (NOW - 600.0) * 1000, "running", None),
            ((NOW - 60.0, 10.0), (NOW + 600.0) * 1000, "running", None),
            ((NOW - 60.0, 10.0), "x", "killed", NOW - 30.0),
            ((NOW - 60.0, 3000.0), (NOW - 60.0) * 1000, "failed", NOW - 30.0),
            ((NOW, 0.0), NOW * 1000, "running", None)):
        add("eta_reading", eta, start, NOW, status, end)
    for own, fin, start in (((), [], None), ((), [NOW + 5.0], NOW - 10.0),
                            ((NOW, 30.0), [], None),
                            ((NOW, 30.0), [NOW + 90.0, None], NOW - 10.0),
                            ((NOW, 300.0), [NOW + 90.0], 0.0),
                            ((), [NOW + 90.0, NOW + 9.0], 0.0)):
        add("inherit_eta", own, fin, start)
    for reading in (None, (), (0.5, 120.0), (1.0, -45.0), (1.0, -40000.0),
                    (0.1, 9000.0), (0.9, 0.0)):
        for w, digits in ((4, 3), (4, 2), (6, 3)):
            add("eta_fig", reading, w, digits, False)
            add("eta_fig", reading, w, digits, True)
    for busy, start, tool, blocked, eta, turn, agents in (
            (0.0, 0.0, 0.0, 0.0, (), 0.0, ()),
            (13800.0, NOW - 33480.0, 3450.0, 300.0, (), NOW - 480.0, ()),
            (100.0, NOW + 50.0, 200.0, 500.0, (), 0.0, ()),
            (50.0, NOW - 40.0, 0.0, 0.0, (NOW - 10.0, 0.0), NOW - 20.0, ()),
            (50.0, NOW - 4000.0, 10.0, 0.0, (NOW - 10.0, 0.0), NOW - 20.0,
             ((NOW + 100.0, NOW - 3.0),)),
            (50.0, NOW - 4000.0, 10.0, 0.0, (NOW - 900.0, 60.0), NOW - 1000.0,
             ((NOW + 100.0, NOW - 3000.0), (None, NOW))),
            (9e5, NOW - 2e6, 4e5, 1e6, (), 0.0, ((NOW + 50.0, NOW),))):
        add("render_elapsed", busy, start, tool, NOW, blocked, eta, turn,
            agents)
    for budget, b, p, w in ((40, 10, 10, 10), (40, 30, 30, 30),
                            (16, 30, 30, 30), (16, 2, 30, 30),
                            (100, 3, 4, 200), (25, 40, 3, 50),
                            (0, 5, 5, 5), (17, 9, 9, 9)):
        add("allocate_left", budget, b, p, w)
    for s, m in ((0, 0), (2, 0), (0, 1), (12, 3)):
        add("render_thread_background", s, m)
    for g in (GIT, GIT._replace(dirty=True), rec.NO_GIT):
        add("render_where_group", "proj", "~/a/b", "main", g, [])
        add("render_where_group", "", "", "", g,
            cr.render_thread_background(1, 1))
        add("project_name", g, "/x/y/")
    add("project_name", GIT._replace(main_root="", toplevel="/"), "/x/y/")
    add("project_name", GIT._replace(main_root="/", toplevel="/"), "/")
    tail = cr.render_pr("42")
    for text in ("", "short", "時間 answered 🧩 " * 12):
        for cols in (None, 20, 80, 196):
            add("chat_row", fm.S_HUMAN, text, "(no prompt yet)", "F_CHAT_U",
                tail, cols)
            add("chat_row", fm.S_BOT, text, "(no reply yet)", "F_CHAT_B",
                [], cols)
    for t in (TR, TR._replace(user_ts="2026-08-16T02:30:00Z"),
              rec.EMPTY_TRANSCRIPT):
        add("render_chat_rows", t, tail, cr.render_pr("7"), 120)
    for row, grid in ((tail, True), (tail, False), ([], True)):
        add("drawn_line", row, grid)
    return out


# render_status draws whole readouts, so it runs under fewer of CFGS: one
# per profile, both spacings and the subscripts among them.
STATUS_CFGS = (("unknown", True, False), ("jediterm", False, False),
               ("iterm", True, True), ("tmux", False, False))


def status(cfg):
    """render_status over each variant at each width; the records are
    written once, under `records`, and each case names its variant."""
    out = []
    os.environ["HOME"] = HOME
    for tz in ("UTC", "America/New_York"):
        gen.set_tz(tz)
        for name, pay, tr, git, lim, cache, win, rate in status_variants():
            if tz != "UTC" and name not in ("base", "limits-full"):
                continue
            for cols in (None, 50, 120, 196):
                for rules in ((True, False) if cols == 196 else (False,)):
                    out.append({
                        "name": name, "cfg": list(cfg), "tz": tz,
                        "cols": cols, "rules": rules,
                        "out": enc(gen.run(cr.render_status, pay, tr, git,
                                           lim, cols, NOW, rules, win,
                                           rate, cache))})
    return out


def records():
    """Each variant's arguments to render_status but the width and rules."""
    return {name: {"pay": enc(pay), "tr": enc(tr), "git": enc(git),
                   "lim": enc(lim), "cache": enc(cache), "ctx_window": win,
                   "rate": enc(rate)}
            for name, pay, tr, git, lim, cache, win, rate
            in status_variants()}


def main():
    saved = {k: os.environ.get(k) for k in gen.PROFILE_VARS + ("TZ", "HOME")}
    cell_cases, status_cases = [], []
    try:
        for cfg in CFGS:
            configure(*cfg)
            cell_cases += cells(cfg)
            if cfg in STATUS_CFGS:
                status_cases += status(cfg)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        time.tzset()
        importlib.reload(fm)
        importlib.reload(cr)
    gen.OUT = OUT
    try:
        gen.write("cells", {"cases": cell_cases}, by_line="cases")
        gen.write("status", {"cases": status_cases, "home": HOME,
                             "now": NOW, "records": records()},
                  by_line="cases")
    finally:
        gen.OUT = os.path.join(FIXTURES, "formatting")
    print("render: %d cases" % (len(cell_cases) + len(status_cases)))


if __name__ == "__main__":
    main()
