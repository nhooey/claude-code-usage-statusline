#!/usr/bin/env bash
# Golden test: --mode status against recorded output.
#
#   bash tests/golden.sh              # check
#   bash tests/golden.sh --regen      # re-record, then read the diff
#
# 16 payloads x 6 widths in a clean repo, plus two source-freshness cases,
# plus one payload x 6 widths in a dirty one, plus two payloads x 3 widths
# under --no-mark-spacing and two under --no-column-rules, against files under
# golden/.  Byte-identical stdout is the gate, as it was for the differential
# test this replaces.
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
NEW="$DIR/../claude-code-usage-statusline.py"
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
  got=$( cd "$wd" && "$PY" "$NEW" --mode status --cols "${cols:-0}" $flags < "$payload" )
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
cat > "$CLAUDE_PLAN_CACHE" <<'JSON'
{
  "session_pct": 15.0,
  "session_resets_at": "2026-08-16 02:30",
  "weekly_pct": 87.0,
  "weekly_resets_at": "2026-08-18 01:00",
  "as_of": "2026-08-16 01:00"
}
JSON
for p in 02-no-limits 10-empty-payload; do
  check "stale-plan-$p@196" "$CORPUS/$p.json" 196 "$SCRATCH/repo"
done

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

echo
if [ "$regen" -eq 1 ]; then
  echo "wrote $wrote goldens under $GOLD"
  echo "READ THE DIFF before accepting them: this is the step where a layout"
  echo "regression gets blessed as the new expected output."
  exit 0
fi
echo "pass $pass   fail $fail   missing $missing"
[ "$fail" -eq 0 ] && [ "$missing" -eq 0 ]
