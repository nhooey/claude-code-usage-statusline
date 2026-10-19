#!/usr/bin/env bash
# Validate the mod and run its harness tests (mod-tests/) in Claude Code's
# own test runner.
#
#   bash mod/tools/plugin-test.sh
#
# `claude plugin test <folder>` runs every *.test.ts under the folder, and
# mod/ is both the plugin and the Node port, whose test/*.test.ts import
# node:test and will not load in the mod's runtime.  So the plugin's own
# files are copied to a scratch folder and the runner pointed at that:
# the manifest, the hooks, the ports they import, the state contract and
# the harness tests.  Nothing is installed and no settings are touched.
set -euo pipefail

mod="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="$(mktemp -d "${TMPDIR:-/tmp}/usage-band-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/.claude-plugin"
cp "$mod/.claude-plugin/plugin.json" "$work/.claude-plugin/"
cp -R "$mod/hooks" "$mod/src" "$mod/types" "$mod/mod-tests" "$work/"

claude plugin validate "$work"
claude plugin test "$work"
