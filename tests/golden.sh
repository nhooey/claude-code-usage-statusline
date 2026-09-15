#!/usr/bin/env bash
# Golden test: --mode status against recorded output.
#
#   bash tests/golden.sh              # check
#   bash tests/golden.sh --regen      # re-record, then read the diff
#
# 16 payloads x 6 widths in a clean repo, plus two source-freshness cases,
# plus one payload x 6 widths in a dirty one, plus two payloads x 3 widths
# under --no-mark-spacing and two under --no-column-rules, plus two cases
# about a window boundary -- one that falls inside a turn and one whose
# reading is too coarse to divide by -- against files under golden/.
# Byte-identical stdout is the gate, as it was for the differential test this
# replaces.
#
# The corpus is WRITTEN BY mkcorpus-status.py on every run, into the scratch
# directory, and read from there.  It used to be fourteen payload files kept
# beside this one, eleven of which pointed at a real 8.7 MB session under
# ~/.claude/projects/ -- which is why the suite could not live in the repo
# with the program, and why it needed a guard recording that file's size so a
# prune or a resume would not be reported as a change in the program.  A
# generated corpus needs neither.
#
# WHY THIS IS NOT A DIFFERENTIAL TEST ANY MORE.  It compared the merged
# program against statusline.sh, and that proved the port only while the
# reference was the pre-merge original.  It stopped being one: the bash file
# was hand-edited four times in one sitting to track the Python — the weekly
# glyph, EAW_NARROW, EAW_TEXT_PRES, the jq naughty predicate — so what the
# comparison measured by the end was whether two files edited the same evening
# said the same thing.  It also passed, all 63 comparisons, straight over two
# defects that were in BOTH files identically: the $TMUX branch that trusts
# the variable without stat'ing the socket, and the stale U+1FA70 comment.  A
# differential test cannot fail on an error both sides make, and that is the
# ONLY kind of error a maintained reference can still hold.
#
# --regen is the whole method, and it is not a weakness: a golden file is a
# claim about what the program prints, so a change to the layout is SUPPOSED
# to show up as a diff you read and accept.  The old harness could not do that
# — a layout change failed all 78 comparisons at once, which reports nothing,
# because a gate that is red whatever you do has stopped being a gate.
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
NEW="$DIR/../coding-agent-usage-line.py"
PY=/usr/bin/python3
GOLD="$DIR/golden/status"
OUT="$DIR/out"
SCRATCH="${TMPDIR:-/tmp}/claude-golden-status.$$"
CORPUS="$SCRATCH/corpus"

regen=0
[ "${1:-}" = "--regen" ] && regen=1

# shellcheck source=pin-env.sh
. "$DIR/pin-env.sh"
pin_env "$SCRATCH"
trap 'rm -rf "$SCRATCH"' EXIT

mkdir -p "$GOLD" "$OUT"
rm -f "$OUT"/*.got "$OUT"/*.want   # else a stale failure looks like a live one

# The corpus, written fresh.  Into the scratch directory rather than beside
# this script, so a run cannot leave a fixture behind for the next one to read
# and there is no copy on disk to drift away from the generator.
"$PY" "$DIR/mkcorpus-status.py" "$CORPUS" || { echo "FATAL: corpus" >&2; exit 2; }

pass=0; fail=0; missing=0; wrote=0

check() {   # $1 = case name, $2 = payload, $3 = cols ("" for unknown),
            # $4 = cwd, $5 = extra flags (unquoted on purpose, so a caller can
            # pass more than one)
  local name="$1" payload="$2" cols="$3" wd="$4" flags="${5:-}" got want
  # "--cols 0" is how the program is told to pretend the width is unknown;
  # without it, it finds a real one and renders a layout the golden never saw.
  # shellcheck disable=SC2086
  got=$( cd "$wd" && "$PY" "$NEW" --agent claude --mode status --cols "${cols:-0}" $flags < "$payload" )
  want="$GOLD/$name.txt"
  if [ "$regen" -eq 1 ]; then
    printf '%s' "$got" > "$want"
    wrote=$((wrote + 1))
    return
  fi
  if [ ! -f "$want" ]; then
    printf '  MISS  %-32s (no golden — run --regen)\n' "$name"
    missing=$((missing + 1)); return
  fi
  if [ "$got" = "$(cat "$want")" ]; then
    printf '  ok    %-32s\n' "$name"
    pass=$((pass + 1))
  else
    printf '  FAIL  %-32s\n' "$name"
    printf '%s' "$got" > "$OUT/$name.got"
    cp "$want" "$OUT/$name.want"
    fail=$((fail + 1))
  fi
}

echo "=== golden: status mode ==="
for payload in "$CORPUS"/*.json; do
  base=$(basename "$payload" .json)
  for c in 196 150 120 92 60 ""; do
    check "$base@${c:-none}" "$payload" "$c" "$SCRATCH/repo"
  done
done

# The dirty tree, on one payload only. 🍂 and ✱ are two cells on row 3 and
# they do not interact with the rest of the layout, so crossing every payload
# with every repo state would buy nothing but six times the goldens.
echo "--- dirty tree ---"
for c in 196 150 120 92 60 ""; do
  check "dirty-01@${c:-none}" "$CORPUS/01-baseline.json" "$c" "$SCRATCH/repo-dirty"
done

# ── which source a payload without rate_limits quotes ───────────────────────
#
# Two payloads carry no rate_limits, and until 2026-08-25 they fell through to
# the menu-bar app unconditionally.  They no longer do: limits_snapshot takes
# whichever reading was TAKEN more recently, because the app is polled on its
# own schedule and an expired plan cache is not evidence that the app is
# fresher.  That is a two-branch decision and both branches need a case.
#
# Above, the plan cache is the fresher: every payload from 01 onward writes it
# stamped at the pinned minute, against the app fixture's 02:20.  So 02 and 10
# in the main loop are already the plan-cache branch.
#
# Here it is planted STALE — an as_of well behind the app's — and the same two
# payloads have to come back with the app's 41٪ and 63٪ instead.  This is the
# case that would have caught the failure the change was made for: the cost
# row quoting a three-hour-old app snapshot under a status row reading the
# live one, because "expired" was being read as "beaten".
echo "--- a stale plan cache loses to the app ---"
# Pin a selected fallback response so a preceding native fixture with the
# same synthetic session cannot satisfy this historical check from cache.
set_claude_fixture 41 2026-08-16T04:00:00Z 63 2026-08-18T01:00:00Z
for p in 02-no-limits 10-empty-payload; do
  check "stale-plan-$p@196" "$CORPUS/$p.json" 196 "$SCRATCH/repo"
done
export CODING_AGENT_USAGE_LINE_USAGE_SOURCE=auto

# ── --no-mark-spacing ───────────────────────────────────────────────────────
#
# The switch closes the blank between every column-4 mark and its value, and
# that is not a local change: column 4 loses four columns, LINE3_RESERVED
# follows it down, and so does how much of the pwd survives when the width is
# unknown.  Three widths rather than six, because the failures live at the
# ends — 196 shows the column at full size, "" exercises the pwd budget that
# moved with it, and 92 is where the left half is already competing for room.
# Two payloads: 01 for the ordinary reading and 08 for the one whose account
# figures are wide enough to touch their marks.
echo "--- --no-mark-spacing ---"
for c in 196 92 ""; do
  check "tight-01@${c:-none}" "$CORPUS/01-baseline.json" \
        "$c" "$SCRATCH/repo" --no-mark-spacing
  check "tight-08@${c:-none}" "$CORPUS/08-limits-critical.json" \
        "$c" "$SCRATCH/repo" --no-mark-spacing
done

# ── --no-column-rules ───────────────────────────────────────────────────────
#
# The rules are painted INTO SEG_GAP and take no column, so the switch is
# ink-only and these cases must come out byte-identical to the same payload at
# a width below RULE_MIN -- which is the property worth pinning, because the
# failure mode of a divider is that it costs a column and shifts the grid.
# Only at 196: it is the one width in this corpus that carries the rules at
# all, so every other width would test nothing.  Two payloads, for the two
# shapes of the first gap: 01 leaves column 1 empty, 04 fills it.
echo "--- --no-column-rules ---"
check "norules-01@196" "$CORPUS/01-baseline.json" 196 "$SCRATCH/repo" \
      --no-column-rules
check "norules-04@196" "$CORPUS/04-pr-and-style.json" 196 "$SCRATCH/repo" \
      --no-column-rules

# ── a window that opens INSIDE the last turn ────────────────────────────────
#
# The three fields of column 4 are one window read at three scopes, so
# 🎤 <= 🎮 <= 💳 is an ordering the column asserts merely by existing.  Until
# 2026-09-03 a single reset could break it, because the two figures this
# session derives were bounded by different rules: 🎮 dropped or kept a turn
# WHOLE on the stamp of its prompt, and 🎤 had no window bound on it at all.
# A turn that began before a reset and was still running after it therefore
# went entirely to 🎤 and not at all to 🎮, and the row printed a part larger
# than the whole it belongs to -- observed live as `🎤 18٪  🎮 0٪  💳 1٪`.
#
# The boundary here is planted at 02:18, which falls between the last turn's
# prompt (02:15:20) and its calls (02:15:32 onward), so the last turn is the
# straddling one and both cells move.  Under the old rule this case renders
# 🎮 as 0٪ under a non-zero 🎤; under turn_cost_since they are equal, because
# the last turn is the only one inside the window and 🎮 sums exactly it.
#
# 02-no-limits is the payload because it carries no rate_limits of its own --
# every other payload would overwrite this cache with the figures it brought
# -- and because a payload without them is the only kind whose window this
# file can choose.  15٪ keeps the reading clear of CALIB_MIN_PCT; the case
# below is the one that goes under it.
echo "--- a window that opens inside the last turn ---"
set_claude_fixture 15 2026-08-16T07:18:00Z 87 2026-08-18T01:00:00Z
check "straddle-02@196" "$CORPUS/02-no-limits.json" 196 "$SCRATCH/repo"

# ── a reading too coarse to divide by ───────────────────────────────────────
#
# used_percentage is quantised to whole percent, so a reading of 1 is a band
# half a point wide either side -- the unit derived from it is uncertain by a
# factor of three, and so is every share divided into it.  Below
# CALIB_MIN_PCT nothing is derived at all and the two scopes this session owns
# print "?", which render_limit's fig() has always drawn for a figure it does
# not have.  💳 is unaffected: it is the reading itself, not something divided
# by it.  The weekly row keeps its figures, which is the point of checking
# both windows in one case -- the floor is per window, not per readout.
#
# THE CALIB FIXTURE HAS TO GO for this one, and it is the only case here that
# touches it.  pin-env.sh plants the short shape -- two UNITS, stated -- which
# calibration() returns before it ever looks at a reading, so a floor on the
# reading is unreachable through it.  What replaces it is the LIVE shape:
# window costs keyed by the boundaries they were measured over, plus the two
# readings they were measured WITH, which is the pairing added the same day.
# The key must be the two starts the plan cache above implies, formatted as
# calibration() formats them -- "%s|%s" over two datetimes -- or the entry
# misses and the suite goes off to scan this machine's transcripts.
echo "--- a reading too coarse to calibrate from ---"
set_claude_fixture 1 2026-08-16T07:18:00Z 87 2026-08-18T01:00:00Z
cat > "$CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE" <<'JSON'
{
  "windows": "2026-08-16 02:18:00|2026-08-11 01:00:00",
  "sess_cost": 5.50, "sess_pct": 1.0,
  "week_cost": 356.70, "week_pct": 87.0
}
JSON
check "uncalibrated-02@196" "$CORPUS/02-no-limits.json" 196 "$SCRATCH/repo"

# Put the fixture back.  Nothing runs after this today, and that is exactly
# why: the next case added below would otherwise inherit a live-shape cache
# keyed to one particular pair of boundaries, miss on it, and scan the
# machine -- which is slow, and answers with whoever ran it.
cat > "$CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE" <<'JSON'
{"sess": 5.50, "week": 4.10}
JSON

# ── --subscript-decimals ────────────────────────────────────────────────────
# Ordinary corpus payloads must again choose their supplied native windows;
# only the final no-limits fixture below selects a command response.
export CODING_AGENT_USAGE_LINE_USAGE_SOURCE=auto
#
# The switch reaches five formatters at once, so what has to be pinned is not
# one cell but the WIDTH of every row it touches: no field is narrowed for it
# yet, so a row that changes width under the flag is a bug and a golden is
# what says so.  Three widths for the three regimes -- 196 where column 4 is
# whole, 92 where the left half is already competing for room, and "" where
# the pwd budget decides.  Two payloads: 01 for the ordinary readings and 08,
# whose limit figures are the ones that carry decimals at every scope.
#
echo "--- --subscript-decimals ---"
for c in 196 92 ""; do
  check "subdec-01@${c:-none}" "$CORPUS/01-baseline.json" \
        "$c" "$SCRATCH/repo" --subscript-decimals
  check "subdec-08@${c:-none}" "$CORPUS/08-limits-critical.json" \
        "$c" "$SCRATCH/repo" --subscript-decimals
done

# THE LEADING ZERO COMING BACK, which neither payload above reaches: both
# carry limit figures over 1٪ at every scope, so neither exercises the one
# case where this form differs from the point form by more than a glyph.
# Under 1٪ the status line writes ".38" and this has to write "0₃₈" -- "₃₈"
# and 38 being the same glyph sequence one point size apart -- so the field is
# the SAME WIDTH either way and the switch buys nothing there.  That is
# exactly why it wants a golden: it is the branch somebody tidies away later
# on the grounds that the zero is redundant, and the row it breaks is a
# fraction of a percent misread as tens of them.
#
# The straddle plant is reused to get there.  It puts the 5-hour boundary
# inside the last turn, which leaves this session holding 0.63٪ of the window
# -- the only sub-1 limit reading this corpus produces.
set_claude_fixture 15 2026-08-16T07:18:00Z 87 2026-08-18T01:00:00Z
check "subdec-sub1-02@196" "$CORPUS/02-no-limits.json" 196 "$SCRATCH/repo" \
      --subscript-decimals

# ── the model label, one case per branch of short_model ─────────────────────
export CODING_AGENT_USAGE_LINE_USAGE_SOURCE=auto
#
# 05-haiku-max and 11-sonnet-200k already carry two of the three branches
# across the main loop: Haiku 4.5 as the family that fits whole, Sonnet 4.6 as
# the family that does not and keeps the squeeze.  The two below are the ones
# no payload in the corpus reaches, and they are the reason the rule was
# rewritten on 2026-09-07.
#
# Fable is the case that prompted it: a five-letter family with one version
# anybody is running, drawn as "Fabl5" for a digit that separated it from
# nothing.  Mythos is the case nobody would have noticed -- it was not in the
# family list at all, so it fell through the passthrough and drew as "Mytho",
# a family name with its last letter eaten.  Both are one width apiece: the
# cell is five columns wherever it lands and the label does not interact with
# the layout around it, so the six-width sweep the main loop does would buy
# six copies of one answer.
echo "--- the model label ---"
"$PY" - "$CORPUS/01-baseline.json" "$SCRATCH/fable.json" "Fable 5" \
        claude-fable-5 <<'PYE'
import json, sys
d = json.load(open(sys.argv[1]))
d["model"] = {"id": sys.argv[4], "display_name": sys.argv[3]}
json.dump(d, open(sys.argv[2], "w"))
PYE
"$PY" - "$CORPUS/01-baseline.json" "$SCRATCH/mythos.json" "Mythos 5" \
        claude-mythos-5 <<'PYE'
import json, sys
d = json.load(open(sys.argv[1]))
d["model"] = {"id": sys.argv[4], "display_name": sys.argv[3]}
json.dump(d, open(sys.argv[2], "w"))
PYE
check "model-fable@196"  "$SCRATCH/fable.json"  196 "$SCRATCH/repo"
check "model-mythos@196" "$SCRATCH/mythos.json" 196 "$SCRATCH/repo"

echo
if [ "$regen" -eq 1 ]; then
  echo "wrote $wrote goldens under $GOLD"
  echo "READ THE DIFF before accepting them: this is the step where a layout"
  echo "regression gets blessed as the new expected output."
  exit 0
fi
echo "pass $pass   fail $fail   missing $missing"
[ "$fail" -eq 0 ] && [ "$missing" -eq 0 ]
