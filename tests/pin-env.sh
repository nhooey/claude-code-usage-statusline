# shellcheck shell=bash
#
# Sourced by golden.sh and golden-cost.sh.  Not a test, and not executable,
# which is why it carries a shellcheck directive instead of a shebang: a
# shebang here would advertise a way to run it that does nothing.
#
# What it does NOT pin any more is the corpus: both suites generate theirs
# into the scratch directory on every run.  This file is what is left over
# once the inputs are yours -- the clock, the zone, the terminal, the caches
# the program writes through, and two git repositories to be run inside.
#
# Everything the readout reads that is NOT the payload, pinned.  A golden file
# is worth exactly what its environment is worth: an unpinned clock or an
# unpinned repo does not make the test flaky, it makes the golden a record of
# the machine and the minute that generated it.
#
# The differential test this replaced needed almost none of this, because it
# compared two programs reading the same world at the same moment — whatever
# the world said, it said to both, and cancelled.  A golden file has nothing
# to cancel against, so every one of these had to be found and held still.
# Each one below is a difference that was actually observed between two runs.

PIN_NOW=1786847000        # 2026-08-16 02:23:20 UTC.  Chosen against the
                          # corpus rather than at random: it falls 6.7 minutes
                          # before 01-baseline's five_hour resets_at and 1.9
                          # days before its seven_day one, so both 🔜 figures
                          # render as real durations instead of blanks, and it
                          # is after the last record of every generated
                          # transcript -- mkcorpus-status.py and
                          # mkcorpus-cost.py both stamp in offsets BEFORE this
                          # number -- so the elapsed and idle figures are
                          # stable positives rather than negatives.

pin_env() {               # $1 = scratch dir; wiped and rebuilt on every call
  local scratch="$1"
  rm -rf "$scratch"
  mkdir -p "$scratch/tmp"

  # The clock.  See frozen_now() in the program: every renderer already took a
  # `now`, and this is what finally fills it in.
  export CLAUDE_STATUSLINE_NOW="$PIN_NOW"

  # The zone.  The readout formats in local time, so a golden generated in
  # +07 and checked in UTC differs by seven hours on the 🕐 and 📅 cells and
  # nowhere else — which reads as a layout failure.
  export TZ=UTC
  export LC_ALL=en_US.UTF-8

  # TMPDIR holds three per-session files the program writes and reads back:
  # the plan-window baseline that the 🔋/🪫 deltas are measured from, the
  # published context window, and the menu-bar app's usage snapshot.  A fresh
  # directory every run means the baseline is always absent, so every delta
  # starts at zero — which is a stated value rather than whatever this machine
  # happened to have consumed since the session opened.
  export TMPDIR="$scratch/tmp"

  # Both of these default into /tmp, shared with the live readout.  Isolated
  # for the reason PLAN_CACHE's own comment gives: a test must not be able to
  # write to the thing it is testing around.  Fourteen of the sixteen payloads
  # carry rate_limits, and an unisolated run publishes 08-limits-critical's
  # figures to the real cost line and leaves them there for five minutes.
  export CLAUDE_PLAN_CACHE="$scratch/tmp/plan-limits.json"
  export CLAUDE_CALIB_CACHE="$scratch/tmp/calib.json"

  # The terminal profile, which selects the per-terminal width overrides.
  # Pinned to jediterm — Neil's terminal, and the profile the override tables
  # exist for — rather than to the empty "unknown" fallback.  Both tables are
  # empty today, so this changes nothing yet; the point is what happens when
  # one is finally filled in from a probe run.  Pinned to jediterm, that lands
  # as a golden diff naming the rows that moved.  Left unpinned, the same
  # change makes the suite pass or fail depending on which terminal ran it.
  unset TMUX
  unset TERM_PROGRAM
  export TERMINAL_EMULATOR=JetBrains-JediTerm

  # The menu-bar app's snapshot, planted.  Two payloads carry no rate_limits
  # and fall through to this file; unplanted, the program finds it stale and
  # shells out to usage-limits.sh, which reports this machine's real plan
  # consumption — a number that is different every hour and belongs to nobody
  # but Neil.  Fresh mtime, so the 60-second TTL is satisfied and the shell-out
  # never happens.
  #
  # `as_of` is the field that decides which source a render quotes, so it is
  # pinned rather than left to the file's mtime — 200 seconds before PIN_NOW,
  # which is older than the plan cache any payload with rate_limits writes
  # (stamped at the pinned minute, 20 seconds old) and newer than the stale
  # one planted at the end of golden.sh.  Both branches of limits_snapshot
  # are therefore chosen by a number in a fixture rather than by whether a
  # real minute happened to tick during the run, which is how the app and the
  # plan cache traded places between two adjacent cases of one suite.
  #
  # The reset times are LOCAL "%Y-%m-%d %H:%M" strings because that is what
  # usage-limits.sh actually emits.  They were bare epochs, which short_dur
  # also accepts — so the countdown rendered and the fixture looked right —
  # but _window_starts parses with one strptime and an epoch is not a date,
  # so the two fallback payloads reached _with_shares with no window boundary
  # and drew "?" where the live program draws a figure.  A fixture that is
  # merely accepted is not the same as a fixture that is faithful.  These two
  # are the same instants as the epochs they replace, under TZ=UTC: 1786852800
  # is 1.6h after PIN_NOW and 1787014800 is 1.9d after it.
  cat > "$scratch/tmp/claude-usage-cache.json" <<'JSON'
{
  "session_pct": 41,
  "session_resets_at": "2026-08-16 04:00",
  "weekly_pct": 63,
  "weekly_resets_at": "2026-08-18 01:00",
  "as_of": "2026-08-16 02:20"
}
JSON

  # The calibration, planted for the same reason and a worse one: uncached, it
  # walks every transcript on this machine to derive dollars-per-percent, so
  # its answer depends on what has been run here lately and it costs a
  # directory scan per invocation.  These two figures are a plausible reading
  # held still, not a measurement.
  #
  # SHAPE MATTERS.  calibration() reads a dict with no "windows" key as a
  # planted fixture and takes the two figures as the UNITS themselves.  The
  # live cache has that key and holds the two window COSTS instead, so it can
  # be invalidated when a reset moves a boundary — but the boundaries here
  # come from each payload's rate_limits and differ per case, so a fixture in
  # the live shape would miss on every one of them and send the suite off to
  # scan this machine's transcripts.  Keep this file in the short shape.
  #
  # And the VALUES matter now that both readouts divide by them.  Under the
  # generated corpus the main transcript's four turns cost $34.64 at list
  # price, of which $21.14 falls inside the 5-hour window each payload's
  # rate_limits opens, so 5.50 and 4.10 render as 3.8٪ of a window standing at
  # 15٪ and 8.4٪ of one standing at 87٪.  A session share has to come out
  # BELOW the plan-wide figure beside it: an earlier pair put it at 18٪ of a
  # window holding 15٪, which is a possible reading of a bad calibration and
  # an impossible row to leave in a golden file for somebody to find.  These
  # two are a plausible reading held still, not a measurement.
  cat > "$CLAUDE_CALIB_CACHE" <<'JSON'
{"sess": 5.50, "week": 4.10}
JSON

  # detect_git() reads the process's cwd, so the branch name, the dirty
  # marker and the project name all come from wherever the harness was
  # started.  A golden generated inside this checkout would encode today's
  # branch and today's uncommitted work.
  git init -q -b golden-clean "$scratch/repo" 2>/dev/null
  git -C "$scratch/repo" -c user.name=golden -c user.email=golden@invalid \
      commit -q --allow-empty -m fixture 2>/dev/null

  # And a second one, dirty, so the 🍂 branch glyph and the ✱ marker are
  # covered at all.  The differential test could never cover them
  # deliberately: it took whatever state the checkout happened to be in, and
  # proved only that both programs read it the same way.
  git init -q -b golden-dirty "$scratch/repo-dirty" 2>/dev/null
  git -C "$scratch/repo-dirty" -c user.name=golden -c user.email=golden@invalid \
      commit -q --allow-empty -m fixture 2>/dev/null
  echo uncommitted > "$scratch/repo-dirty/changed.txt"
  git -C "$scratch/repo-dirty" add changed.txt 2>/dev/null
}
