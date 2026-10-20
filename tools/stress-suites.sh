#!/usr/bin/env bash
# Run suites of tests/all.sh over and over under CPU load, and count how
# often each fails: the way to see a load-dependent flake, and to see it
# gone.
#
#   bash tools/stress-suites.sh [--runs N] [--jobs J] [--burn B] [SUITE...]
#
# N runs of `bash tests/all.sh SUITE...` (default 12), J at a time
# (default 4), beside B busy loops that do nothing but spin (default the
# number of CPUs).  With no SUITE, every suite.  Each line of the end
# table is a suite, the runs it failed and the runs it had.  The output of
# every failing run is kept, and the folder it is in printed, for the
# failure itself; with no failure the folder is removed.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
runs=12 jobs=4 burn="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)"
while [ $# -gt 0 ]; do
  case "$1" in
    --runs) runs="$2"; shift 2 ;;
    --jobs) jobs="$2"; shift 2 ;;
    --burn) burn="$2"; shift 2 ;;
    --) shift; break ;;
    -*) echo "unknown option $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
for n in "$runs" "$jobs" "$burn"; do
  case "$n" in '' | *[!0-9]*) echo "--runs, --jobs and --burn take numbers" >&2; exit 2 ;; esac
done

work="$(mktemp -d "${TMPDIR:-/tmp}/stress-suites.XXXXXX")"
burners=()
stop() {
  [ ${#burners[@]} -gt 0 ] && kill "${burners[@]}" 2>/dev/null
  wait 2>/dev/null
}
trap stop EXIT
trap 'exit 130' INT TERM

for ((b = 0; b < burn; b++)); do
  ( while :; do :; done ) &
  burners+=($!)
done

echo "$runs runs of tests/all.sh ${*:-(every suite)}, $jobs at a time, beside $burn busy loops"
lanes=()
for ((j = 0; j < jobs; j++)); do
  (
    for ((i = j; i < runs; i += jobs)); do
      bash "$ROOT/tests/all.sh" "$@" >"$work/run-$i.out" 2>&1
      echo "run $((i + 1)) of $runs: $? failed"
    done
  ) &
  lanes+=($!)
done
wait "${lanes[@]}"

# Each table line of all.sh is NAME SECONDS ok|FAIL ...; the wall line
# is not a suite.
awk '$1 != "wall" && ($3 == "ok" || $3 == "FAIL") {
       had[$1]++; if ($3 == "FAIL") failed[$1]++ }
     END { for (s in had) printf "%-24s %3d of %d failed\n", s, failed[s], had[s] }' \
  "$work"/run-*.out | sort

for f in "$work"/run-*.out; do
  grep -q '  FAIL  ' "$f" || rm -f "$f"
done
if ls "$work"/run-*.out >/dev/null 2>&1; then
  echo "failing runs' output: $work"
else
  rm -rf "$work"
fi
