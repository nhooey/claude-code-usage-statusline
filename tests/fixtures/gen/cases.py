#!/usr/bin/env python3
"""Write cases.json and env/*.json: every golden case, as data.

    python3 tests/fixtures/gen/all.py      # this and the corpora, together

golden.sh and golden-cost.sh used to hold these as shell: a loop per sweep,
and the environment planted between them as side effects (a usage-source
command, a calibration cache rewritten in place).  A second implementation
cannot run that, so it is spelt out here instead and tests/run-cases.py
replays it.  What each case and environment is FOR is in tests/README.md.

ORDER MATTERS.  The cases of one suite share one state directory, in the
order listed, as they did under the shell suites: a payload with rate_limits
writes the plan cache that a later payload without them reads.  The runner
keeps the order, and so must anything else that runs these.
"""
import json
import os

# 2026-08-16 02:23:20 UTC.  6.7 minutes before 01-baseline's 5-hour reset and
# 1.9 days before its weekly one, so both 🔜 countdowns draw real figures, and
# after every generated record, so every elapsed figure is positive.
PIN_NOW = 1786847000

STATUS_WIDTHS = (196, 150, 120, 92, 60, None)
COST_WIDTHS = (196, 150, 120, 92, None)

STATUS_PAYLOADS = (
    "01-baseline", "02-no-limits", "03-no-transcript", "04-pr-and-style",
    "05-haiku-max", "06-zero-cost", "07-big-numbers", "08-limits-critical",
    "09-no-session-id", "10-empty-payload", "11-sonnet-200k", "12-root-cwd",
    "13-empty-transcript", "14-limits-full", "15-cache-warn",
    "16-cache-crit", "17-rounding-boundary", "18-agents",
    "19-queue-and-compact",
)
COST_TRANSCRIPTS = (
    "01-plain", "02-compaction", "03-single-turn", "04-tool-result",
    "05-sidechain", "06-interrupted", "07-empty", "08-woken", "09-agents",
    "10-turn-id", "11-turn-id-late",
)
# The agent panel's sessions; see gen/panel.py.  05 is an empty panel, which
# prints nothing at any width, so it is run at one.
SUBAGENT_PAYLOADS = ("01-mixed", "02-parked", "03-tree", "04-bare",
                     "05-empty")
SUBAGENT_WIDTHS = (220, 160, 120, 92, 60, None)

# Everything a run reads that is not its input.  `source` is null for `auto`,
# which reads the payload's own rate_limits or the tracker store below, or a
# version-1 reading the runner serves from a command.  `calib` is the
# calibration cache's whole content: the short shape, two units stated, is
# taken as is; the live shape is keyed by the window starts it was measured
# over and is used only by the cases about a too-coarse reading.
CALIB_UNITS = {"sess": 5.50, "week": 4.10}


def reading(sess_pct, sess_reset, week_pct, week_reset):
    return {"schema_version": 1, "as_of": PIN_NOW, "windows": [
        {"id": "session", "duration_seconds": 18000,
         "used_percent": sess_pct, "resets_at": sess_reset},
        {"id": "week", "duration_seconds": 604800,
         "used_percent": week_pct, "resets_at": week_reset}]}


def env(source=None, calib=CALIB_UNITS, repo="clean", terminal=None):
    return {
        "now": PIN_NOW,
        "tz": "UTC",
        "locale": "en_US.UTF-8",
        # Pinned to JediTerm's profile, not left to whichever terminal runs
        # the suite.  TMUX and TERM_PROGRAM are unset.
        # The agent panel's cases name others; see ENVS.
        "terminal": ({"TERMINAL_EMULATOR": "JetBrains-JediTerm"}
                     if terminal is None else terminal),
        # The Claude Usage Tracker store `auto` falls back to, in its own
        # CFDate epoch: as_of 200 seconds before PIN_NOW.
        "tracker": {"sessionPercentage": 41, "sessionResetTime": 808545600,
                    "weeklyPercentage": 63, "weeklyResetTime": 808707800,
                    "lastUpdated": 808539600},
        "source": source,
        "calib": calib,
        # A fresh git repository as the working directory: `clean` on branch
        # golden-clean with one empty commit, `dirty` on golden-dirty with a
        # staged file besides.
        "repo": repo,
    }


ENVS = {
    "default": env(),
    "dirty": env(repo="dirty"),
    "app-41-63": env(reading(41, "2026-08-16T04:00:00Z",
                             63, "2026-08-18T01:00:00Z")),
    "straddle": env(reading(15, "2026-08-16T07:18:00Z",
                            87, "2026-08-18T01:00:00Z")),
    "coarse": env(reading(1, "2026-08-16T07:18:00Z",
                          87, "2026-08-18T01:00:00Z"),
                  calib={"windows": "2026-08-16 02:18:00|2026-08-11 01:00:00",
                         "sess_cost": 5.50, "sess_pct": 1.0,
                         "week_cost": 356.70, "week_pct": 87.0}),
    "plan-cache": env(reading(15, "2026-08-16T02:30:00Z",
                              87, "2026-08-18T01:00:00Z")),
    "plan-full": env(reading(99.6, "2026-08-16T02:30:00Z",
                             100, "2026-08-18T01:00:00Z")),
    "straddle-cost": env(reading(15, "2026-08-16T06:31:00Z",
                                 87, "2026-08-18T01:00:00Z")),
    "coarse-cost": env(reading(1, "2026-08-16T06:31:00Z",
                               87, "2026-08-18T01:00:00Z"),
                       calib={"windows":
                              "2026-08-16 01:31:00|2026-08-11 01:00:00",
                              "sess_cost": 5.50, "sess_pct": 1.0,
                              "week_cost": 356.70, "week_pct": 87.0}),
}
# The agent panel's other terminals: tmux and iTerm pad their marks, and an
# unknown terminal corrects no width.  The profile is read at import, so it
# is an environment and not a flag.
_APP_41_63 = ENVS["app-41-63"]["source"]
ENVS.update({
    "tmux": env(_APP_41_63, terminal={"TMUX": "/tmp/tmux-501/default,1,0"}),
    "iterm": env(_APP_41_63, terminal={"TERM_PROGRAM": "iTerm.app"}),
    "unknown-term": env(_APP_41_63, terminal={}),
})


def width(c):
    return "none" if c is None else str(c)


def status_cases():
    out = []

    def case(name, payload, c, env="default", flags=()):
        out.append({"id": "%s@%s" % (name, width(c)), "suite": "status",
                    "input": "payloads/status/%s.json" % payload,
                    "cols": c or 0, "env": env, "flags": list(flags)})

    for p in STATUS_PAYLOADS:
        for c in STATUS_WIDTHS:
            case(p, p, c)
    # The dirty tree, on one payload only: 🍂 and ✱ do not interact with the
    # rest of the layout, so crossing every payload with it buys nothing.
    for c in STATUS_WIDTHS:
        case("dirty-01", "01-baseline", c, env="dirty")
    # The two payloads without rate_limits.  In the main sweep they quote the
    # reading 01-baseline left in the cache; here a selected `cmd:` source
    # replaces it, and they must come back with its 41٪ and 63٪.
    for p in ("02-no-limits", "10-empty-payload"):
        case("stale-plan-" + p, p, 196, env="app-41-63")
    # --no-mark-spacing moves column 4 and the pwd budget with it, so the
    # failures are at the ends: 196 whole, 92 crowded, unknown the budget.
    # 08 for account figures wide enough to touch their marks.
    for c in (196, 92, None):
        case("tight-01", "01-baseline", c, flags=["--no-mark-spacing"])
        case("tight-08", "08-limits-critical", c, flags=["--no-mark-spacing"])
    # The rules are painted into the gap and take no column, so these must
    # match the unruled goldens once the `|` are spaces.  196 is the one width
    # that carries them; 01 leaves column 1 empty and 04 fills it.
    case("rules-01", "01-baseline", 196, flags=["--column-rules"])
    case("rules-04", "04-pr-and-style", 196, flags=["--column-rules"])
    # A 5-hour boundary at 02:18, between the last turn's prompt and its
    # calls: 🎤 <= 🎮 <= 💳 must hold for the turn that straddles it.  02
    # because a payload with its own rate_limits would overwrite the plant.
    case("straddle-02", "02-no-limits", 196, env="straddle")
    # A 1٪ reading, under CALIB_MIN_PCT: the session's shares print "?" and
    # 💳 keeps the reading.  The calibration is the live shape, keyed by the
    # two window starts this reading implies, or it would miss and scan.
    case("uncalibrated-02", "02-no-limits", 196, env="coarse")
    # The switch reaches five formatters and must change no row's width.
    for c in (196, 92, None):
        case("subdec-01", "01-baseline", c, flags=["--subscript-decimals"])
        case("subdec-08", "08-limits-critical", c,
             flags=["--subscript-decimals"])
    # Under 1٪, where the point form writes ".38" and this one "0₃₈": the
    # straddle plant leaves this session 0.63٪, the corpus's only such share.
    case("subdec-sub1-02", "02-no-limits", 196, env="straddle",
         flags=["--subscript-decimals"])
    # short_model's branches no corpus payload reaches; see gen/status.py.
    case("model-fable", "model-fable", 196)
    case("model-mythos", "model-mythos", 196)
    return out


def cost_cases():
    out = []

    # A Stop payload carries no quota envelope, so every cost case reads a
    # planted source: app-41-63 unless it says otherwise.
    def case(name, transcript, c, env="app-41-63", flags=()):
        out.append({"id": "%s@%s" % (name, width(c)), "suite": "cost",
                    "input": "transcripts/cost/%s.jsonl" % transcript,
                    "cols": c or 0, "env": env, "flags": list(flags)})

    for t in COST_TRANSCRIPTS:
        for c in COST_WIDTHS:
            case(t, t, c)
    # 🧩 and 🎯 follow MARK_SP; each case has a same-width sibling above, so
    # the pair's diff is the flag.  02 for the compaction row's own label.
    tight = ["--no-mark-spacing"]
    for c in (196, 120, None):
        case("tight-01", "01-plain", c, flags=tight)
    case("tight-02", "02-compaction", 150, flags=tight)
    # A second reading, so the 🔋 and 🪫 cells are not only ever 41٪ / 63٪.
    for c in COST_WIDTHS:
        case("plan-cache-01", "01-plain", c, env="plan-cache")
    # A full window: the totals row must draw 💯 as the status line does,
    # not clamp to 99٪.
    for c in (196, 120):
        case("plan-full-01", "01-plain", c, env="plan-full")
    case("plan-full-tight-01", "01-plain", 196, env="plan-full", flags=tight)
    # Each switch removes something, so each is checked where it was visible.
    # --force-newline at 196 because the auto rule never fires there.  They
    # ran after plan-full was planted in the shell suite, so they read it.
    for c in (196, 150, 120, 92):
        case("no-acct-01", "01-plain", c, env="plan-full",
             flags=["--no-account-totals"])
    for c in (196, 120):
        case("no-datetime-01", "01-plain", c, env="plan-full",
             flags=["--no-datetime"])
        case("no-usage-01", "01-plain", c, env="plan-full",
             flags=["--no-usage-text"])
        case("force-nl-01", "01-plain", c, env="plan-full",
             flags=["--force-newline"])
    case("no-usage-02", "02-compaction", 150, env="plan-full",
         flags=["--no-usage-text"])
    # All four at once, at the tightest width.
    all_off = ["--no-account-totals", "--no-datetime", "--no-usage-text",
               "--force-newline"]
    case("all-off-01", "01-plain", 92, env="plan-full", flags=all_off)
    case("all-off-02", "02-compaction", 92, env="plan-full", flags=all_off)
    # A boundary at 01:31, between 01-plain's last prompt and its one call:
    # the prompt's share must be part of the session's, not larger.
    for c in (196, 120):
        case("straddle-01", "01-plain", c, env="straddle-cost")
    # Below CALIB_MIN_PCT both 🔋 cells go while 🪫 keeps its figures, so one
    # stacked row loses a cell the other keeps.
    for c in (196, 120):
        case("uncalibrated-01", "01-plain", c, env="coarse-cost")
    # The two rows stack on a held decimal column, which the flag takes the
    # point out of; both must move identically.  plan-cache so 🔋 🪫 draw.
    sub = ["--subscript-decimals"]
    for c in (196, 120):
        case("subdec-01", "01-plain", c, env="plan-cache", flags=sub)
    case("subdec-tight-01", "01-plain", 196, env="plan-cache",
         flags=sub + tight)
    return out


def subagent_cases():
    out = []

    # The panel's payload carries no quota envelope either, so every case
    # reads a planted source, app-41-63's unless its terminal says otherwise.
    # Its tasks' working directories are ${SCRATCH} paths, the fixture
    # repositories, so an agent in the dirty one draws its branch.
    def case(name, payload, c, env="app-41-63", flags=()):
        out.append({"id": "%s@%s" % (name, width(c)), "suite": "subagent",
                    "input": "payloads/subagent/%s.json" % payload,
                    "cols": c or 0, "env": env, "flags": list(flags)})

    for p in SUBAGENT_PAYLOADS:
        for c in SUBAGENT_WIDTHS if p != "05-empty" else (None,):
            case(p, p, c)
    # Each switch and terminal on the two sessions with the most cells, at a
    # width where every cell draws and one where they crowd.
    for p in ("01-mixed", "03-tree"):
        for c in (220, 120):
            case("tight-" + p, p, c, flags=["--no-mark-spacing"])
            case("subdec-" + p, p, c, flags=["--subscript-decimals"])
            for e in ("tmux", "iterm", "unknown-term"):
                case(e + "-" + p, p, c, env=e)
    return out


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def main(root):
    for name, e in sorted(ENVS.items()):
        write_json(os.path.join(root, "env", name + ".json"), e)
    write_json(os.path.join(root, "cases.json"),
               {"cases": status_cases() + cost_cases() + subagent_cases()})
