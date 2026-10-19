#!/usr/bin/env bash
# Every deterministic suite, side by side, and one line each on how it went.
#
#   bash tests/all.sh              # every suite
#   bash tests/all.sh status node  # the ones named
#
# The suites share no state, so they run at once; the longest, the status
# goldens' chain of cases, is about the wall time of the whole.  Each line
# is the suite's name, its seconds, ok or FAIL, and the result line it
# printed.  A failing suite's output follows the table, and the exit status
# is the number of suites that failed.  The manual checks of docs/tests.md
# are not here.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/all-suites.XXXXXX")"
trap 'rm -rf "$work"' EXIT

# name | directory under ROOT | command.  In the order the table prints.
SUITES='
status|.|bash tests/golden.sh
cost|.|bash tests/golden-cost.sh
subagent-goldens|.|python3 tests/run-cases.py --suite subagent
panel|.|python3 tests/run-cases.py --suite panel
py39-floor|.|bash tests/py39-floor.sh
usage-source|.|python3 tests/usage-source.py
sources-v1|.|python3 tests/sources-v1.py
source-cache|.|python3 tests/source-cache.py
http-sources|.|python3 tests/http-sources.py
app-server|.|python3 tests/app-server.py
claude-sources|.|python3 tests/claude-sources.py
codex|.|python3 tests/codex.py
formatting|.|python3 tests/formatting.py
port-cli|.|python3 tests/port-cli.py
agents|.|python3 tests/agents.py
subagent|.|python3 tests/subagent.py
claude-subagent-render|.|python3 tests/claude-subagent-render.py
rate|.|python3 tests/rate.py
grid|.|python3 tests/grid.py
spec|.|python3 tools/gen-spec.py --check
node|mod|node --test test/*.test.ts
typecheck|mod|npm run -s typecheck
typecheck-plugin|mod|npm run -s typecheck:plugin
plugin-test|mod|npm run -s test:plugin
plugin-validate|mod|claude plugin validate .
'

now() {
  if [ -n "${EPOCHREALTIME:-}" ]; then echo "$EPOCHREALTIME"
  else python3 -c 'import time; print(time.time())'; fi
}

# wanted NAME [ASKED...]: NAME is one of those asked for, or none were.
wanted() {
  [ $# -le 1 ] && return 0
  local n
  for n in "${@:2}"; do [ "$n" = "$1" ] && return 0; done
  return 1
}

names=()
t0=$(now)
while IFS='|' read -r name dir cmd; do
  [ -n "$name" ] || continue
  wanted "$name" "$@" || continue
  names+=("$name")
  (
    cd "$ROOT/$dir" || exit 1
    start=$(now)
    # Word splitting is the point: each command is a plain argv.  The glob
    # is node's, so it is not expanded here.
    set -f
    # shellcheck disable=SC2086
    $cmd >"$work/$name.out" 2>&1
    rc=$?
    echo "$rc $start $(now)" >"$work/$name.rc"
  ) &
done <<EOF
$SUITES
EOF
wait
t1=$(now)
if [ ${#names[@]} -eq 0 ]; then
  echo "no suite named $*; the names are the first column of SUITES" >&2
  exit 2
fi

# The line a suite sums itself up in: its last that counts or says ok.
result() {
  grep -E 'pass [0-9]+ +fail|^ℹ (pass|fail) |files differ|^ok |^OK|^Ran [0-9]|[0-9]+ pass|Validation (passed|failed)' "$1" \
    | grep -v '^  ok ' | tail -2 | tr '\n' ' ' | sed 's/  */ /g'
}

failed=0
for name in "${names[@]}"; do
  read -r rc start end <"$work/$name.rc"
  secs=$(python3 -c "print('%.1f' % ($end - $start))")
  if [ "$rc" -eq 0 ]; then mark=ok; else mark=FAIL; failed=$((failed + 1)); fi
  printf '%-24s %6ss  %-4s  %s\n' "$name" "$secs" "$mark" \
    "$(result "$work/$name.out")"
done
printf '%-24s %6ss  %d of %d failed\n' "wall" \
  "$(python3 -c "print('%.1f' % ($t1 - $t0))")" "$failed" "${#names[@]}"

for name in "${names[@]}"; do
  read -r rc _ <"$work/$name.rc"
  [ "$rc" -eq 0 ] && continue
  echo
  echo "=== $name failed: the last 40 lines ==="
  tail -40 "$work/$name.out"
done
exit "$failed"
