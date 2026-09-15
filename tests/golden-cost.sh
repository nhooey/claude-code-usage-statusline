#!/usr/bin/env bash
# Golden test: --mode cost against recorded output.
#
#   bash ~/.claude/tests/golden-cost.sh              # check
#   bash ~/.claude/tests/golden-cost.sh --regen      # re-record, read the diff
#
# 8 synthetic transcripts x 5 widths, plus the status line's plan cache
# planted (at ordinary figures and at a full window), plus four cases under
# --no-mark-spacing, plus the display switches, plus two window-boundary
# cases at two widths each -- a reset inside the last turn, and a reading too
# coarse to divide by.  Byte-identical stdout is the gate.
#
# The differential test this replaces took real transcripts on its command
# line and had no corpus at all, which is why it could never be a golden: its
# input was different every run and belonged to whoever ran it.  It also
# carried four hand-written allowances — a sed patch to the reference, a mask
# over 🔋/🪫, and a gate over per-row label truncation — each of them a place
# where the two programs were known to differ and the harness had to be told
# to look away.  A golden file has no reference to differ from, so all four
# allowances are gone: what the program prints IS the expectation, and a
# change to it is a diff to read rather than a rule to write.
#
# See mkcorpus-cost.py for what each transcript is for.
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
NEW="$DIR/../coding-agent-usage-line.py"
PY=/usr/bin/python3
GOLD="$DIR/golden/cost"
OUT="$DIR/out-cost"
SCRATCH="${TMPDIR:-/tmp}/claude-golden-cost.$$"

regen=0
[ "${1:-}" = "--regen" ] && regen=1

# shellcheck source=pin-env.sh
. "$DIR/pin-env.sh"
pin_env "$SCRATCH"
trap 'rm -rf "$SCRATCH"' EXIT

CORPUS="$SCRATCH/cost"
"$PY" "$DIR/mkcorpus-cost.py" "$CORPUS" || { echo "FATAL: corpus" >&2; exit 2; }

mkdir -p "$GOLD" "$OUT"
rm -f "$OUT"/*.got "$OUT"/*.want

# Stop payloads have no native quota envelope.  Use a fresh v1 fixture rather
# than the status line's retired plan-cache handoff.
set_claude_fixture 41 2026-08-16T04:00:00Z 63 2026-08-18T01:00:00Z

pass=0; fail=0; missing=0; wrote=0

check() {   # $1 name, $2 transcript, $3 cols ("" unknown), $4... extra flags
  local name="$1" tr="$2" cols="$3" got want
  shift 3
  # The hook answers in JSON; the row is the systemMessage inside it.  Compare
  # the row rather than the envelope: a golden full of \u escapes is a golden
  # nobody can read a diff of.
  got=$( cd "$SCRATCH/repo" \
         && "$PY" "$NEW" --agent claude --mode cost --transcript "$tr" --cols "${cols:-0}" \
            "$@" </dev/null \
         | "$PY" -c 'import json,sys
d = json.load(sys.stdin)
sys.stdout.write(d.get("systemMessage", ""))' )
  want="$GOLD/$name.txt"
  if [ "$regen" -eq 1 ]; then
    printf '%s' "$got" > "$want"; wrote=$((wrote + 1)); return
  fi
  if [ ! -f "$want" ]; then
    printf '  MISS  %-32s (no golden — run --regen)\n' "$name"
    missing=$((missing + 1)); return
  fi
  if [ "$got" = "$(cat "$want")" ]; then
    printf '  ok    %-32s\n' "$name"; pass=$((pass + 1))
  else
    printf '  FAIL  %-32s\n' "$name"
    printf '%s' "$got" > "$OUT/$name.got"; cp "$want" "$OUT/$name.want"
    fail=$((fail + 1))
  fi
}

echo "=== golden: cost mode ==="
for tr in "$CORPUS"/*.jsonl; do
  base=$(basename "$tr" .jsonl)
  for c in 196 150 120 92 ""; do
    check "$base@${c:-none}" "$tr" "$c"
  done
done

# ── --no-mark-spacing ───────────────────────────────────────────────────────
#
# The cost row's two unspaced cells, 🧩 and 🎯, follow the status line's
# MARK_SP as of 2026-08-27; the other five hold a sign in that column and do
# not move.  Every case here has a same-width sibling directly above it, so the
# diff between the pair IS the flag: two columns, both of them on those cells.
#
# 02 as well as 01, because the compaction row is laid out against a third
# label and a different chrome, and a width change that only holds for two rows
# is the failure this suite exists to catch.
echo "--- --no-mark-spacing ---"
for c in 196 120 ""; do
  check "tight-01@${c:-none}" "$CORPUS/01-plain.jsonl" "$c" --no-mark-spacing
done
check "tight-02@150" "$CORPUS/02-compaction.jsonl" 150 --no-mark-spacing

# The plan cache present.  With it absent the rows fall back to the menu-bar
# app's snapshot, which is the path every case above takes; with it present
# they quote what the STATUS line last read out of Claude Code's own payload,
# and preferring it is the whole reason the channel exists.  Two sources, and
# only one of them was being rendered.
echo "--- with the status line's plan cache planted ---"
# Written in the shape _write_plan_cache() actually writes, which is not the
# shape the payload carries: the percentages are numbers, and the reset times
# are the app's local "%Y-%m-%d %H:%M" rather than the payload's epoch, so
# calibration() can parse either source with the one strptime it has.  Written
# by hand the obvious way first — strings, epochs — the whole cost line came
# back as a bare "{}": round() raised on a str inside limit_cell, main_cost's
# catch-all swallowed it, and every one of these five cases recorded an empty
# golden.  The fixture has to match the writer, not the payload.
set_claude_fixture 15 2026-08-16T02:30:00Z 87 2026-08-18T01:00:00Z
for c in 196 150 120 92 ""; do
  check "plan-cache-01@${c:-none}" "$CORPUS/01-plain.jsonl" "$c"
done

# A FULL window, which nothing above reaches.  The totals row's figure after
# the slash is the same reading the status line puts beside 💳, and until
# 2026-08-27 this row clamped it to "99٪" where the status line drew 💯 --
# two readouts disagreeing about the one moment either of them matters.  No
# case went near 99.5, so nothing said so.  This is that case.
set_claude_fixture 99.6 2026-08-16T02:30:00Z 100 2026-08-18T01:00:00Z
for c in 196 120; do
  check "plan-full-01@$c" "$CORPUS/01-plain.jsonl" "$c"
done
check "plan-full-tight-01@196" "$CORPUS/01-plain.jsonl" 196 --no-mark-spacing

# ── the switches ────────────────────────────────────────────────────────────
#
# Four options that each REMOVE something, so each has to be checked at a
# width where what it removes was visible.  The interesting one is
# --force-newline at 196: the auto rule never fires there, so a case that
# passes only because the window was narrow would prove nothing about the
# flag.  And 92 is where the auto rule cannot help either, which is the other
# end of the same question.
echo "--- switches ---"
for c in 196 150 120 92; do
  check "no-acct-01@$c"    "$CORPUS/01-plain.jsonl" "$c" --no-account-totals
done
for c in 196 120; do
  check "no-datetime-01@$c" "$CORPUS/01-plain.jsonl" "$c" --no-datetime
  check "no-usage-01@$c"    "$CORPUS/01-plain.jsonl" "$c" --no-usage-text
  check "force-nl-01@$c"    "$CORPUS/01-plain.jsonl" "$c" --force-newline
done
# All three row labels at once — the compaction row is the only place the
# third one appears, and it is a separate constant.
check "no-usage-02@150" "$CORPUS/02-compaction.jsonl" 150 --no-usage-text
# Everything off together, at the width where the block is tightest.  The
# stacking has to survive four simultaneous width changes, which is the case
# no single-flag run covers.
check "all-off-01@92" "$CORPUS/01-plain.jsonl" 92 \
      --no-account-totals --no-datetime --no-usage-text --force-newline
check "all-off-02@92" "$CORPUS/02-compaction.jsonl" 92 \
      --no-account-totals --no-datetime --no-usage-text --force-newline

# ── a window that opens INSIDE the last turn ────────────────────────────────
#
# The cost row's 🔋 and 🪫 are this prompt's share of each window and the row
# below them is the session's, so the first has to be a part of the second --
# and until 2026-09-03 a reset could make it larger.  The per-prompt cell
# divided the WHOLE turn's cost by the unit while the totals row dropped that
# same turn whole for being older than the boundary, so the delta printed a
# figure the total beneath it did not contain.  See turn_cost_since.
#
# 01-plain's last turn is prompted at 01:30:00 and bills its one call at
# 01:31:00.  The boundary is planted at 01:31, between the two: under the old
# rule the totals row says this session put 0 into the 5-hour window while the
# row above it reports a non-zero share of that same window, and under the new
# one they are equal, the last turn being the only turn inside.  The weekly
# figures are untouched by the plant and are what says so.
echo "--- a window that opens inside the last turn ---"
set_claude_fixture 15 2026-08-16T06:31:00Z 87 2026-08-18T01:00:00Z
for c in 196 120; do
  check "straddle-01@$c" "$CORPUS/01-plain.jsonl" "$c"
done

# ── a reading too coarse to divide by ───────────────────────────────────────
#
# Below CALIB_MIN_PCT no unit is derived, so both 🔋 cells go -- the delta
# above and the share below -- while 💳 keeps the reading itself, which is
# what was never in doubt.  Checked at two widths because the cells vanish
# rather than blank, and a group that changes width is exactly what seg()
# pads on the left: the 🪫 row beneath keeps its figures, so this is also the
# case where one row of the stacked pair loses a cell the other keeps.
#
# The calib fixture has to go for this one -- pin-env.sh plants the short
# shape, two UNITS stated, which calibration() returns before it looks at a
# reading at all, so a floor on the reading is unreachable through it.  See
# the twin case in golden.sh; the key here is the pair of starts THIS plan
# cache implies, which is a different pair.
echo "--- a reading too coarse to calibrate from ---"
set_claude_fixture 1 2026-08-16T06:31:00Z 87 2026-08-18T01:00:00Z
cat > "$CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE" <<'JSON'
{
  "windows": "2026-08-16 01:31:00|2026-08-11 01:00:00",
  "sess_cost": 5.50, "sess_pct": 1.0,
  "week_cost": 356.70, "week_pct": 87.0
}
JSON
for c in 196 120; do
  check "uncalibrated-01@$c" "$CORPUS/01-plain.jsonl" "$c"
done

# Put the fixture back, for the reason golden.sh's twin gives.
cat > "$CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE" <<'JSON'
{"sess": 5.50, "week": 4.10}
JSON

# ── --subscript-decimals ────────────────────────────────────────────────────
#
# The cost row is where the switch is most likely to break something, because
# this is the readout whose two rows STACK: dec_align holds a point in a fixed
# column and the flag takes the point away, so what has to still be true is
# that the two rows move identically and the fraction reservation is unchanged
# -- seg() pads on the left, so a cell that came out one column narrower would
# be shoved right, off the field beneath it.  The plan cache is planted so the
# 🔋 and 🪫 cells carry figures at all; without it they are blank and the case
# would exercise nothing.
echo "--- --subscript-decimals ---"
set_claude_fixture 15 2026-08-16T02:30:00Z 87 2026-08-18T01:00:00Z
for c in 196 120; do
  check "subdec-01@$c" "$CORPUS/01-plain.jsonl" "$c" --subscript-decimals
done
check "subdec-tight-01@196" "$CORPUS/01-plain.jsonl" 196 \
      --subscript-decimals --no-mark-spacing

echo
if [ "$regen" -eq 1 ]; then
  echo "wrote $wrote goldens under $GOLD"
  echo "READ THE DIFF before accepting them: this is the step where a layout"
  echo "regression gets blessed as the new expected output."
  exit 0
fi
echo "pass $pass   fail $fail   missing $missing"
[ "$fail" -eq 0 ] && [ "$missing" -eq 0 ]
