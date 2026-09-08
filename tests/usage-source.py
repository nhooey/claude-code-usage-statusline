#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The usage-source layer, checked without a Mac, an app, or a network.

This is the one part of the program that reads somebody ELSE'S store, and the
only part whose input is a schema nobody here controls.  It is also the part
that was broken for days without a word: the previous implementation lived in
two shell scripts outside the repository, the app changed where it kept its
history, and the wrapper answered "{}" from then on.  Nothing could have
caught that, because nothing here could see it.

So the fixture IS the schema.  build_store() below writes the shape observed
in a live store on 2026-09-08, and a future app release that moves a field
fails here with the field named, in a file a reader can diff against the real
thing:

    defaults export HamedElfayome.Claude-Usage - > /tmp/store.plist
    CLAUDE_USAGE_TRACKER_PLIST=/tmp/store.plist \\
        ./claude-code-usage-statusline.py --mode status < payload.json

Not a golden test.  Goldens pin a LAYOUT and these cases pin VALUES, which is
why they are assertions with names rather than files to diff: "session_pct is
98" is worth reading in the test, and "a credential never reaches the cache"
cannot be expressed as a rendered row at all.

Run:  python3 tests/usage-source.py
"""

import importlib.util
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time

DIR = os.path.dirname(os.path.abspath(__file__))
PROG = os.path.join(DIR, "..", "claude-code-usage-statusline.py")

# 2026-09-08 09:37 UTC, and every stamp below is relative to it.  TZ is forced
# to UTC in main() for the reason pin-env.sh forces it: these cases compare
# formatted local stamps, and a stamp is a record of the zone that made it.
NOW = 1788860278.0
APPLE = 978307200.0

# A credential-shaped string, planted in the fixture beside the figures.  The
# real store keeps `oauthAccountJSON` and an API session key in the same
# record as `claudeUsage`; this is the canary for the whitelist in
# normalise_reading, and it is a nonsense value so that finding it anywhere is
# unambiguous.
CANARY = "oauth-canary-must-never-be-copied"

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


def load_program():
    """The program, imported.  Its filename is not an identifier, so this is
    the only way in — and importing rather than running it is the point: these
    cases call four functions directly and never render a row."""
    spec = importlib.util.spec_from_file_location("statusline", PROG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_store(path, usage=None, active="P1", extra=None):
    """A Claude Usage Tracker UserDefaults store, as `defaults export` prints
    one.  Two profiles, so profile selection is exercised by every case that
    reads the fixture rather than by one case that remembers to."""
    if usage is None:
        usage = {
            "sessionPercentage": 98,
            "sessionResetTime": 1788864600.363 - APPLE,
            "weeklyPercentage": 10,
            "opusWeeklyPercentage": 3,
            "weeklyResetTime": 1789434000.363 - APPLE,
            "lastUpdated": NOW - 60 - APPLE,
        }
    profiles = [
        {"id": "P0", "name": "other", "claudeUsage": {"sessionPercentage": 1,
                                                      "weeklyPercentage": 1}},
        {"id": "P1", "name": "main", "claudeUsage": usage,
         "oauthAccountJSON": CANARY, "apiSessionKeyExpiry": 799287597},
    ]
    store = {"activeProfileId": active,
             "profiles_v3": json.dumps(profiles).encode("utf-8"),
             "AppleLanguages": ["en"]}
    store.update(extra or {})
    with open(path, "wb") as fh:
        plistlib.dump(store, fh)
    return path


def main():
    os.environ["TZ"] = "UTC"
    time.tzset()
    m = load_program()
    tmp = tempfile.mkdtemp(prefix="claude-usage-source.")
    try:
        run_cases(m, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\npass %d   fail %d   missing 0" % (pass_n, fail_n))
    return 1 if fail_n else 0


def run_cases(m, tmp):
    store = build_store(os.path.join(tmp, "store.plist"))

    # ── the tracker's schema ────────────────────────────────────────────────
    print("--- the Claude Usage Tracker store ---")
    with open(store, "rb") as fh:
        raw = m.tracker_reading(plistlib.load(fh))
    check("session_pct", raw.get("session_pct"), 98)
    check("weekly_pct", raw.get("weekly_pct"), 10)
    check("weekly_opus_pct", raw.get("weekly_opus_pct"), 3)
    # Apple epoch in, Unix epoch out.  A 25-year error is the one this
    # conversion makes when it is not made.
    check("session reset -> unix epoch",
          raw.get("session_resets_at"), 1788864600.363)
    check("as_of -> unix epoch", raw.get("as_of"), NOW - 60)

    reading = m.normalise_reading(raw, now=NOW)
    # UTC, per main() — the live store these figures were copied out of was
    # written in Asia/Bangkok and read 17:50 there.  A stamp is a record of
    # the zone that formatted it, which is the whole reason the zone is forced.
    check("normalised session reset",
          reading.get("session_resets_at"), "2026-09-08 10:50")
    check("normalised weekly reset",
          reading.get("weekly_resets_at"), "2026-09-15 01:00")
    check("normalised as_of", reading.get("as_of"), "2026-09-08 09:36")
    check("reset provenance", reading.get("session_reset_source"), "app")
    check("no field but the seven", sorted(reading),
          ["as_of", "session_pct", "session_reset_source", "session_resets_at",
           "weekly_opus_pct", "weekly_pct", "weekly_resets_at"])
    if CANARY in json.dumps(reading):
        bad("credential dropped", "the canary reached the reading")
    else:
        ok("credential dropped")

    # ── profile selection ───────────────────────────────────────────────────
    print("--- which profile ---")
    other = build_store(os.path.join(tmp, "other.plist"), active="P0")
    with open(other, "rb") as fh:
        r = m.tracker_reading(plistlib.load(fh))
    check("activeProfileId chooses", r.get("session_pct"), 1)

    nomatch = build_store(os.path.join(tmp, "nomatch.plist"), active="gone")
    with open(nomatch, "rb") as fh:
        r = m.tracker_reading(plistlib.load(fh))
    check("unknown active id falls back to the first", r.get("session_pct"), 1)

    # ── schemas that are not this one ───────────────────────────────────────
    #
    # The 2026-08 store: a usageHistory_<uuid> key holding snapshots, and no
    # profiles_v3 at all.  This is the shape the retired shell scripts read,
    # and the case exists to say out loud that the program answers "nothing"
    # for it rather than something wrong.
    print("--- a store this does not understand ---")
    check("pre-migration store", m.tracker_reading(
        {"usageHistory_ABC": json.dumps({"snapshots": []}),
         "usageHistoryMigratedToFiles_v1": True}), {})
    check("empty store", m.tracker_reading({}), {})
    check("profiles_v3 is not JSON",
          m.tracker_reading({"profiles_v3": b"{not json"}), {})
    check("profile without claudeUsage",
          m.tracker_reading({"activeProfileId": "P1",
                             "profiles_v3": json.dumps([{"id": "P1"}])}), {})

    # ── normalise_reading, on its own ───────────────────────────────────────
    print("--- normalising a reading ---")
    check("stamps pass through", m.normalise_reading(
        {"session_pct": "42", "session_resets_at": "2026-09-08 17:50"},
        now=NOW).get("session_resets_at"), "2026-09-08 17:50")
    # A reset in the past renders as a countdown of zero, which reads as a
    # window about to turn over rather than as a reading nobody should trust.
    check("a past reset is dropped", "session_resets_at" in m.normalise_reading(
        {"session_pct": 42, "session_resets_at": NOW - 1}, now=NOW), False)
    check("a reset a minute out is dropped too",
          "session_resets_at" in m.normalise_reading(
              {"session_pct": 42, "session_resets_at": NOW + 60}, now=NOW),
          False)
    check("percentages become numbers",
          m.normalise_reading({"session_pct": "42"}, now=NOW).get("session_pct"),
          42.0)
    check("a reading with no percentage is not a reading",
          m.normalise_reading({"as_of": NOW, "weekly_resets_at": NOW + 9999},
                              now=NOW), {})
    check("as_of defaults to now",
          m.normalise_reading({"weekly_pct": 3}, now=NOW).get("as_of"),
          "2026-09-08 09:37")
    check("not a dict", m.normalise_reading(["nope"], now=NOW), {})

    # ── choosing a source ───────────────────────────────────────────────────
    print("--- --usage-source ---")
    check("none", m.usage_source("none"), None)
    check("off", m.usage_source("off"), None)
    check("a name", m.usage_source("claude-usage-tracker").name,
          "claude-usage-tracker")
    check("a name nobody has", m.usage_source("no-such-source"), None)
    check("cmd:", m.usage_source("cmd:/bin/echo").name, "cmd:/bin/echo")
    os.environ["CLAUDE_USAGE_TRACKER_PLIST"] = store
    src = m.usage_source("auto")
    check("auto finds the tracker when its store is readable",
          src and src.name, "claude-usage-tracker")
    check("and reads it", m.normalise_reading(src.read(), now=NOW)
          .get("session_pct"), 98.0)

    # ── an external source ──────────────────────────────────────────────────
    #
    # The contract in one script: print JSON, exit 0.  Written without the
    # execute bit on purpose — CommandSource falls back to bash, which is what
    # a fresh clone of somebody's dotfiles hands you.
    print("--- cmd: sources ---")
    script = os.path.join(tmp, "src.sh")
    with open(script, "w") as fh:
        fh.write('#!/bin/sh\nprintf \'{"session_pct": 7, "weekly_pct": 8, '
                 '"session_resets_at": %d}\\n\' %d\n' % (0, NOW + 7200))
    check("bash fallback for a non-executable script",
          m.normalise_reading(m.CommandSource(script).read(), now=NOW)
          .get("session_pct"), 7.0)

    broken = os.path.join(tmp, "broken.sh")
    with open(broken, "w") as fh:
        fh.write("#!/bin/sh\necho not json\nexit 3\n")
    check("a failing script is not a reading",
          m.CommandSource(broken).read(), {})
    check("a missing script is not available",
          m.CommandSource(os.path.join(tmp, "nope.sh")).available(), False)

    # ── the cache in front of all of it ─────────────────────────────────────
    print("--- the reading cache ---")
    cache = os.path.join(tmp, "cache.json")
    m.LIMIT_CACHE = cache
    os.environ["CLAUDE_STATUSLINE_NOW"] = "%d" % NOW
    m.set_usage_source("claude-usage-tracker")
    got = m._read_limit_cache()
    check("a cold cache is filled from the source",
          got.get("session_pct"), 98.0)
    check("and written to disk", os.path.isfile(cache), True)
    with open(cache) as fh:
        on_disk = fh.read()
    if CANARY in on_disk:
        bad("no credential on disk", "the canary reached %s" % cache)
    else:
        ok("no credential on disk")

    # A source that answers nothing must not erase a good reading: the app
    # quitting is a momentary event and a blank readout that outlives it is
    # not.  Age the cache past LIMIT_TTL and read again with a dead source.
    old = time.time() - 3600
    os.utime(cache, (old, old))
    m.set_usage_source("cmd:" + broken)
    check("a failed refresh keeps the previous reading",
          m._read_limit_cache().get("session_pct"), 98.0)

    m.set_usage_source("none")
    check("--usage-source none still reads the cache",
          m._read_limit_cache().get("session_pct"), 98.0)

    # ── end to end ──────────────────────────────────────────────────────────
    #
    # One render, through the program as a process, with a payload carrying no
    # rate_limits — the case the whole channel exists for.  The 5-hour figure
    # from the fixture store has to appear on the row.
    print("--- one render off a fixture store ---")
    env = dict(os.environ)
    env.update({"CLAUDE_USAGE_TRACKER_PLIST": store,
                "CLAUDE_STATUSLINE_NOW": "%d" % NOW,
                "TZ": "UTC", "TMPDIR": tmp,
                "CLAUDE_LIMIT_CACHE": os.path.join(tmp, "e2e.json"),
                "CLAUDE_PLAN_CACHE": os.path.join(tmp, "e2e-plan.json"),
                "CLAUDE_CALIB_CACHE": os.path.join(tmp, "e2e-calib.json")})
    env.pop("CLAUDE_USAGE_SOURCE", None)
    transcript = os.path.join(tmp, "t.jsonl")
    open(transcript, "w").close()
    payload = json.dumps({"session_id": "usage-source",
                          "transcript_path": transcript, "cwd": tmp,
                          "model": {"display_name": "Opus 5"},
                          "workspace": {"current_dir": tmp}})
    p = subprocess.run([sys.executable, PROG, "--mode", "status",
                        "--cols", "196", "--usage-source", "auto"],
                       input=payload, capture_output=True, text=True, env=env)
    if "98" in p.stdout:
        ok("the fixture's 98٪ reaches the row")
    else:
        bad("the fixture's 98٪ reaches the row", p.stdout + p.stderr)
    # A cache of its own, and no file at that path: the run above left a
    # filled one behind, and "none" means ask nobody, not forget everything.
    env["CLAUDE_LIMIT_CACHE"] = os.path.join(tmp, "e2e-none.json")
    p = subprocess.run([sys.executable, PROG, "--mode", "status",
                        "--cols", "196", "--usage-source", "none"],
                       input=payload, capture_output=True, text=True, env=env)
    if "98" in p.stdout:
        bad("--usage-source none asks nobody",
            "a figure appeared with no source and no cache")
    else:
        ok("--usage-source none asks nobody")


if __name__ == "__main__":
    sys.exit(main())
