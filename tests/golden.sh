#!/usr/bin/env bash
# The status cases of tests/fixtures/cases.json, kept under this name for CI
# and habit.  See run-cases.py; --regen passes through.
exec /usr/bin/python3 "$(dirname "$0")/run-cases.py" --suite status "$@"
