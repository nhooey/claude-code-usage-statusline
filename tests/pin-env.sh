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
  export CODING_AGENT_USAGE_LINE_NOW="$PIN_NOW"

  # The zone.  The readout formats in local time, so a golden generated in
  # +07 and checked in UTC differs by seven hours on the 🕐 and 📅 cells and
  # nowhere else — which reads as a layout failure.
  export TZ=UTC
  export LC_ALL=en_US.UTF-8

  # Isolate scratch files as well as the application state pinned below.
  export TMPDIR="$scratch/tmp"

  # Supply a prepared calibration without scanning the developer's history.
  export CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE="$scratch/tmp/calib.json"
  # Shared source caches and context/rate/report files are private JSON state.
  # A fresh root prevents previous local runs from influencing the goldens.
  export CODING_AGENT_USAGE_LINE_STATE_DIR="$scratch/tmp/source-state"
  export CODING_AGENT_USAGE_LINE_TEST_SOURCE_DIR="$scratch/tmp"
  CLAUDE_FIXTURE_N=0

  # Auto reads native payloads or the fixture plist below, never a live store.
  export CODING_AGENT_USAGE_LINE_USAGE_SOURCE=auto

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

  # The fallback plist uses the tracker's CFDate epoch. Its as_of is pinned
  # 200 seconds before PIN_NOW; reset epochs normalize through v1, then the
  # Claude bridge supplies local STAMP_FMT strings to its accounting. These
  # are the original fixture instants, independent of file mtime and host data.
  export CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST="$scratch/tmp/tracker.plist"
  cat > "$CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>activeProfileId</key><string>golden</string>
<key>profiles_v3</key><string>[{"id":"golden","claudeUsage":{"sessionPercentage":41,"sessionResetTime":808545600,"weeklyPercentage":63,"weeklyResetTime":808707800,"lastUpdated":808539600}}]</string>
</dict></plist>
PLIST

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
  cat > "$CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE" <<'JSON'
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

# Replace the selected v1 reading for a deliberately exceptional golden case.
# Each response gets a new command identity so the collector's fresh cache
# cannot mistake a previous fixture for this one.
set_claude_fixture() { # session %, session reset ISO, week %, week reset ISO
  CLAUDE_FIXTURE_N=$((CLAUDE_FIXTURE_N + 1))
  local path="$CODING_AGENT_USAGE_LINE_TEST_SOURCE_DIR/claude-source-$CLAUDE_FIXTURE_N"
  cat > "$path" <<EOF
#!/bin/sh
printf '%s\\n' '{"schema_version":1,"as_of":$PIN_NOW,"windows":[{"id":"session","duration_seconds":18000,"used_percent":$1,"resets_at":"$2"},{"id":"week","duration_seconds":604800,"used_percent":$3,"resets_at":"$4"}]}'
EOF
  chmod 700 "$path"
  export CODING_AGENT_USAGE_LINE_USAGE_SOURCE="cmd:$path"
}
