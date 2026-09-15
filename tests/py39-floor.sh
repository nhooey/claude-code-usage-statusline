#!/usr/bin/env bash
# The Python 3.9 floor, CHECKED rather than claimed.
#
# The opening paragraph of README.md promises 3.9, and until this script
# existed nothing verified it: the program is developed against whatever
# python3 is first on PATH, which on this machine is much newer.  A 3.10-only
# construct — a match statement, `int | None` in an annotation evaluated at
# runtime, a new stdlib name — compiles and runs perfectly there and breaks
# for every reader on a stock macOS.
#
# /usr/bin/python3 IS 3.9 on macOS and is the point of the check, so it is
# preferred over anything on PATH.  A newer /usr/bin/python3 on some future
# macOS would make this check vacuous rather than wrong, and it says so.
#
# Two things are checked, because they fail differently:
#   1. py_compile over the program and tests/*.py — catches SYNTAX that 3.9
#      does not have.  Cheap, and covers every line including ones no test
#      reaches.
#   2. One render in each mode under 3.9 — catches a NAME 3.9 does not have,
#      which compiles fine and raises at import or at call.
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
PROG="$DIR/../coding-agent-usage-line.py"
PY="${PY39:-/usr/bin/python3}"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/coding-agent-usage-line-pycache}"

pass=0; fail=0

ok()   { pass=$((pass+1)); printf '  ok    %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && \
         printf '%s\n' "$2" | sed 's/^/          /'; }

[ -x "$PY" ] || { echo "no $PY — set PY39 to a 3.9 interpreter" >&2; exit 2; }

ver=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "--- floor check under $PY (Python $ver) ---"
case "$ver" in
  3.9) : ;;
  *) echo "  note: $PY is $ver, not 3.9 — this run checks $ver, and the 3.9"
     echo "        claim in README.md is NOT verified by it." ;;
esac

# 1. syntax, over the launcher, package, and offline fixtures.
for f in "$PROG" "$DIR"/*.py "$DIR"/../coding_agent_usage_line/*.py; do
    if out=$("$PY" -m py_compile "$f" 2>&1); then
        ok "compile $(basename "$f")"
    else
        bad "compile $(basename "$f")" "$out"
    fi
done

# 2. one render in each mode.  Minimal payloads: enough to reach the
#    renderers, not enough to depend on a fixture that could drift.
tmp=$(mktemp -d) || exit 2
trap 'rm -rf "$tmp"' EXIT
: > "$tmp/t.jsonl"
export CODING_AGENT_USAGE_LINE_STATE_DIR="$tmp/state"
export CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR="$tmp/projects"
export CODING_AGENT_USAGE_LINE_USAGE_SOURCE=native
export CODEX_HOME="$tmp/codex"

status_payload() {
    printf '{"session_id":"py39","transcript_path":"%s","cwd":"%s",' \
        "$tmp/t.jsonl" "$tmp"
    printf '"model":{"display_name":"Opus"},"workspace":{"current_dir":"%s"}}' "$tmp"
}

if out=$(status_payload | "$PY" "$PROG" --agent claude --mode status 2>&1) && [ -n "$out" ]; then
    ok "render --mode status"
else
    bad "render --mode status" "$out"
fi

if out=$(status_payload | "$PY" "$PROG" --agent claude --mode cost 2>&1); then
    ok "render --mode cost"
else
    bad "render --mode cost" "$out"
fi

if out=$("$PY" "$PROG" --agent codex --mode status --transcript "$tmp/t.jsonl" \
         --usage-source native 2>&1) && [ -n "$out" ]; then
    ok "render Codex status"
else
    bad "render Codex status" "$out"
fi

if out=$("$PY" "$PROG" --agent codex --mode cost --transcript "$tmp/t.jsonl" \
         --usage-source native 2>&1) && [ -n "$out" ]; then
    ok "render Codex cost"
else
    bad "render Codex cost" "$out"
fi

if out=$("$PY" "$PROG" --agent codex --mode subagent --usage-source native 2>&1); then
    bad "reject Codex subagent" "$out"
else
    ok "reject Codex subagent"
fi

printf '\npass %d   fail %d   missing 0\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
