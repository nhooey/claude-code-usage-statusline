#!/usr/bin/env python3
"""Mock up the proposed layout: Claude Code's screen with all three readouts.

A design aid, not a readout.  It draws a short transcript, the turn receipt
the Stop hook would print into it, the band a mod would draw above the
prompt, the prompt, the agent panel's rows and the mode line, from made-up
figures, so the proposal can be looked at in a real terminal before any of
it is built.  The status line is gone from it: the band replaces it.

The proposal it draws:

- One column per metric, in one order, on every row of every readout:
  model, 💰, 🧠, 🧩, 🎯, ⌛ ⛳ 🤖 🔧 🚦, 🔋, 🪫, 💾.  The cells are the agent
  panel's own, drawn by claude_subagent_render's and claude_render's
  renderers, so the figures are formatted as the readouts format them.
- One scope per row, named by its label: 💳 the account, 🎤 the turn,
  🤖💬 the main thread, 🎮 the session, and one row per agent.
- Every row's cells end on the same column, RIGHT_EDGE columns short of the
  terminal's right edge, where Claude Code draws the band's [-] button.
- When the terminal is too narrow for every label to keep LABEL_MIN columns,
  whole columns drop on every row together, in DROP_ORDER.
- --hide takes a path, scope[.group[.metric]], with * for any one part:
  "account", "*.work", "turn.time.eta".  A column hidden on every row it
  could show on is removed; hidden on some, it is left blank there.

Run:  python3 tools/layout-mockup.py [--cols N] [--hide PATH ...]
                                     [--receipt hook|mod] [--plain]
"""
import argparse
import fnmatch
import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from coding_agent_usage_line import formatting as fmt  # noqa: E402
from coding_agent_usage_line.formatting import (  # noqa: E402
    DIM, E_ACCT, E_BOT, E_COSTLINE, E_CTX, E_DATE, E_DIR, E_GIT_OK, E_PROJ,
    E_RESET, E_TIME, E_TURN_ID, E_TURN_PAST,
    E_SESS, E_SESSION, E_TURN, E_WEEK, F_BLU, F_CHAT_B, F_GRN, F_LIM_SESS,
    F_LIM_WEEK, F_PNK, R, S_COST, S_CTX, S_TOK, VAL2_W, VAL_W, dur_fmt,
    fit_cols, humanize, pad_val, seg, strip_ansi, vis_width)
from coding_agent_usage_line.claude_render import (  # noqa: E402
    render_cost, render_tokens)
from coding_agent_usage_line.claude_subagent_render import (  # noqa: E402
    A_CLOCK_W, A_CTX_W, A_DIFF_W, A_ETA_W, A_GAP, A_LIMIT_W, A_LIMIT_WEEK_W,
    A_SPLIT_W, render_agent_cache, render_agent_ctx, render_agent_diff,
    render_agent_elapsed, render_agent_eta, render_agent_limit,
    render_agent_model, render_agent_split, render_kind)

NOW = 1_792_000_000.0
# The five columns Claude Code keeps for the band's [-] button.  The panel's
# rows and the receipt end there too, so all three readouts share one edge.
RIGHT_EDGE = 5
# The fewest columns a row's label keeps before columns start to drop.
LABEL_MIN = 20
# The panel's chrome before a row of the session's own: its pointer and two
# blanks, drawn by Claude Code.  A nested row adds two more per level.
PANEL_CHROME = 3


def ctx_growth(tokens, points):
    """🧠 for a turn: how much the context grew, in tokens and points."""
    return "%s%s%s %s%s" % (S_CTX, F_PNK, pad_val(4, "+" + humanize(tokens)),
                             pad_val(4, "+%d%s" % (points, fmt.E_PCT)), R)


def limit(mark, colour, digits=3):
    return lambda share: render_agent_limit(mark, "1", share, colour, digits=digits)


# key, hide path (group.metric), width, gap before it, renderer.  The gaps
# are the panel row's: two between cells, one inside the ⌛ group.
CELLS = [
    ("model", "state.model", 6, A_GAP, lambda a: render_agent_model(*a)),
    ("cost", "cost.cost", vis_width(S_COST) + 4, A_GAP, lambda c: render_cost("%.4f" % c)),
    ("ctx", "context.size", A_CTX_W, A_GAP,
     lambda a: ctx_growth(*a[1:]) if a[0] == "+" else render_agent_ctx(*a)),
    ("tok", "tokens.io", vis_width(S_TOK) + VAL_W + VAL2_W, A_GAP, lambda a: render_tokens(*a)),
    ("cache", "tokens.cache", 5, A_GAP, render_agent_cache),
    ("clock", "time.elapsed", A_CLOCK_W, A_GAP,
     lambda start: render_agent_elapsed(start * 1000, NOW)),
    ("eta", "time.eta", A_ETA_W, 1,
     lambda a: render_agent_eta((NOW, a[1]), a[0] * 1000, NOW)),
    ("split", "time.split", A_SPLIT_W, 1, lambda a: render_agent_split(*a)),
    ("five", "plan.five_hour", A_LIMIT_W, A_GAP, limit(E_SESS, F_LIM_SESS)),
    ("week", "plan.week", A_LIMIT_WEEK_W, A_GAP, limit(E_WEEK, F_LIM_WEEK, 4)),
    ("diff", "work.diff", A_DIFF_W, A_GAP,
     lambda a: render_agent_diff(SimpleNamespace(lines_added=a[0], lines_removed=a[1]))),
]
# Least important first: the order whole columns drop in when labels run
# short.  💰, then 🔋 and 🪫, are the last to go.
DROP_ORDER = ["diff", "cache", "split", "model", "tok", "eta", "clock", "ctx",
              "week", "five", "cost"]


def piece(path, text, colour=""):
    """A part of a row's label, with the path --hide names it by."""
    return (path, colour + text + (R if colour else ""))


# One sample session: a turn that asked why the build is slow, the main
# thread answering it, and two agents it started.
TURN_START, SESSION_START = NOW - 4 * 60, NOW - 9 * 3600
ACCOUNT = dict(scope="account", label=[
    piece("account.name", E_ACCT + " account  "),
    piece("plan.reset", "%s %s %s  %s %s %s" % (E_SESS, E_RESET, dur_fmt(6.7 * 60),
                                              E_WEEK, E_RESET, dur_fmt(1.8 * 86400)), DIM)],
    cells=dict(five=15.0, week=87.0))
TURN = dict(scope="turn", label=[piece("turn.name", E_TURN + " "),
                                 piece("chat.prompt", "Why is the build slow?", F_CHAT_B)],
            cells=dict(cost=0.21, ctx=("+", 34_000, 3), tok=(28_000, 7_100), cache=95,
                       clock=TURN_START, eta=(TURN_START, 120),
                       split=(240, 150, 60), five=0.03, week=0.05, diff=(12, 3)))
MAIN = dict(scope="main", label=[piece("main.name", E_BOT + " "),
                                 piece("chat.reply", "The test step takes 80٪ of the build: Jest runs serially",
                                       F_CHAT_B)],
            cells=dict(model=("claude-opus-5-5", "high"), cost=92.0, ctx=(115_000, 1_000_000),
                       tok=(2_100_000, 640_000), cache=98, clock=SESSION_START,
                       eta=(TURN_START, 120), split=(9 * 3600, 4 * 3600, 3 * 3600),
                       five=0.9, week=2.1, diff=(3100, 180)))
SESSION = dict(scope="session", label=[piece("session.name", E_SESSION + " session  "),
                                       piece("workspace.project", E_PROJ + "app ", F_BLU),
                                       piece("workspace.branch", E_GIT_OK + "main", F_GRN)],
               cells=dict(cost=115.0, tok=(2_700_000, 841_000), cache=98, clock=SESSION_START,
                          split=(9 * 3600, 4 * 3600, 3 * 3600), five=1.2, week=3.8,
                          diff=(3400, 214)))
AGENTS = [
    dict(scope="agent", depth=1, label=[
        piece("agent.kind", render_kind("general-purpose", "") + "🟢 "),
        piece("agent.name", "Port renderer  ", fmt.F_BLU),
        piece("chat.doing", "Editing claude_render.py", F_CHAT_B)],
        cells=dict(model=("claude-opus-5-5", "high"), cost=0.4, ctx=(124_000, 1_000_000),
                   tok=(66_000, 3_600), cache=93, clock=NOW - 14 * 60,
                   eta=(NOW - 14 * 60, 180), split=(14 * 60, 5 * 60, 60),
                   five=0.08, week=0.10, diff=(48, 9))),
    dict(scope="agent", depth=2, label=[
        piece("agent.kind", render_kind("Explore", "") + "🟢 "),
        piece("agent.name", "Find callers of seg()  ", fmt.F_BLU),
        piece("chat.doing", "Searching", F_CHAT_B)],
        cells=dict(model=("claude-sonnet-5-5", "medium"), cost=0.1, ctx=(48_000, 200_000),
                   tok=(24_000, 1_000), cache=90, clock=NOW - 8.3 * 60,
                   eta=(NOW - 8.3 * 60, 150), split=(8.3 * 60, 2 * 60, 0),
                   five=0.03, week=0.04, diff=(0, 0))),
]
# The receipt is the band's 🎤 and 🎮 rows as they stood when the turn
# ended, behind the receipt's 📊.
# The receipt's first line: which turn the rows under it bill, by the head
# of its promptId and Claude Code's turn index, and when it ended.
RECEIPT_HEAD = "%s%s 8f37748e #12  %s 2026-10-19  %s 13:06:02" % (
    E_TURN_PAST, E_TURN_ID, E_DATE, E_TIME)
RECEIPT = [dict(TURN, label=[piece("turn.receipt", E_COSTLINE + " ")] + TURN["label"]),
           dict(SESSION, label=[piece("session.receipt", E_COSTLINE + " ")] + SESSION["label"])]


def hidden(patterns, path):
    """Whether a pattern names `path` or a path above it: "turn.time" hides
    "turn.time.eta", and "*" stands for any one part."""
    parts = path.split(".")
    for p in patterns:
        want = p.split(".")
        if len(want) <= len(parts) and all(fnmatch.fnmatchcase(a, b)
                                           for a, b in zip(parts, want)):
            return True
    return False


def chrome(row):
    """What Claude Code draws before a panel row: the pointer, and two more
    columns per level of nesting."""
    if "depth" not in row:
        return ""
    return DIM + "  " * (row["depth"] - 1) + ("└ " if row["depth"] > 1 else "") + "◯  " + R


def label_text(row, patterns):
    return "".join(t for path, t in row["label"]
                   if not hidden(patterns, row["scope"] + "." + path)
                   and not hidden(patterns, row["scope"] + "." + path.split(".")[0]))


def layout(rows, cols, patterns):
    """The columns every row draws, after --hide and the narrow-window drop."""
    keys = [k for k, *_ in CELLS
            if any(k in r["cells"] and not hidden(patterns, r["scope"] + "." + path)
                   for r in rows for kk, path, *_ in CELLS if kk == k)]
    width = {k: w + gap for k, _, w, gap, _ in CELLS}
    lead = max(vis_width(strip_ansi(chrome(r))) for r in rows)
    for k in DROP_ORDER:
        if cols - RIGHT_EDGE - lead - sum(width[c] for c in keys) >= LABEL_MIN:
            break
        if k in keys:
            keys.remove(k)
    return keys


def draw(row, keys, cols, patterns):
    right = ""
    for k, path, w, gap, render in CELLS:
        if k not in keys:
            continue
        show = k in row["cells"] and not hidden(patterns, row["scope"] + "." + path)
        right += " " * gap + seg(w, render(row["cells"][k]) if show else "")
    head = chrome(row)
    room = cols - RIGHT_EDGE - vis_width(strip_ansi(head)) - vis_width(strip_ansi(right))
    text = label_text(row, patterns)
    if vis_width(strip_ansi(text)) > room:
        text = fit_cols(strip_ansi(text), room)
    return head + seg(room, text) + right


def screen(cols, patterns, receipt_by="hook"):
    rule = "─" * cols
    band = [r for r in (ACCOUNT, TURN, MAIN, SESSION) if not hidden(patterns, r["scope"])]
    receipt = [r for r in RECEIPT if not hidden(patterns, r["scope"])]
    agents = [r for r in AGENTS if not hidden(patterns, r["scope"])]
    keys = layout(band + receipt + agents, cols, patterns)
    out = [
        DIM + "❯ " + R + "Why is the build slow?",
        "",
        "⏺ Bash(npm run build -- --profile)",
        "  ⎿  compile 31s · bundle 18s · test 3m 12s",
        "",
        "⏺ The test step takes 80٪ of the build: Jest runs the suites serially",
        "  because maxWorkers is 1 in jest.config.js.",
        "",
    ]
    rows = [draw(r, keys, cols, patterns) for r in receipt]
    if receipt_by == "hook":
        # Claude Code draws a Stop hook's systemMessage behind "Stop says: ",
        # and no setting changes it, so the receipt opens on a newline.
        out += [DIM + "Stop says: " + R, RECEIPT_HEAD] + rows
        out += ["", DIM + "✻ Worked for 4m 2s · done 1:06 PM" + R]
    else:
        # The mod redraws the TurnDuration line instead, with the receipt's
        # head on it and its rows under it, and the Stop hook prints nothing.
        out += [DIM + "✻ Worked for 4m 2s · " + R + RECEIPT_HEAD] + rows

    band_rows = [draw(r, keys, cols, patterns) for r in band]
    if band_rows:
        # Claude Code's [-] button, on the band's first row.
        band_rows[0] = seg(cols - RIGHT_EDGE, band_rows[0]) + "  " + DIM + "[-]" + R
    out += band_rows
    out += [DIM + rule + R, "❯ ", DIM + rule + R]
    if agents:
        out.append(DIM + "◯  main" + R)  # Claude Code's own row; no hook draws it
        out += [draw(r, keys, cols, patterns) for r in agents]
    out.append(DIM + "  -- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle)" + R)
    return "\n".join(line.rstrip() for line in out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cols", type=int, default=fmt.term_cols() or 160,
                    help="terminal width to draw for (default: this terminal's, else 160)")
    ap.add_argument("--hide", action="append", default=[], metavar="PATH",
                    help="scope[.group[.metric]] to hide; repeatable")
    ap.add_argument("--receipt", choices=("hook", "mod"), default="mod",
                    help="draw the receipt as the Stop hook's message, or as the "
                         "mod's rewrite of the turn's closing line")
    ap.add_argument("--plain", action="store_true", help="no colour")
    a = ap.parse_args(argv)
    text = screen(a.cols, a.hide, a.receipt)
    print(strip_ansi(text) if a.plain else text)


if __name__ == "__main__":
    main()
