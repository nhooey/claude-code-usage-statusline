#!/usr/bin/env python3
"""Shared terminal-formatting ownership contract, independent of either agent."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line import formatting as f

assert f.vis_width("🎯") == 2
assert f.pad_val(4, "🎯") == "  🎯"
assert f.humanize(1234) == "1.2k"
assert f.humanize(632) == "632 "
# Rounding must roll into the next unit, never print "60m" or "24h".
assert f.dur_fmt(3569) == "59m" and f.dur_fmt(3570) == "1h" and f.dur_fmt(3599, 2) == "1h"
assert f.dur_fmt(84599) == "23h" and f.dur_fmt(86399) == "1d"
f.set_mark_spacing(False)
assert f.MARK_SP == "" and f.C_TOK == f.C_TOK_TIGHT
f.set_mark_spacing(True)
assert f.MARK_SP == " " and f.C_TOK == f.C_TOK_TIGHT + 1
f.set_subscript_decimals(True)
assert f.sub_dec("1.2") == "1₂"
f.set_subscript_decimals(False)
# The profile rules, first match wins, read as data since 2026-10-19.
assert f.term_profile({"TMUX": "/tmp/s", "TERMINAL_EMULATOR": "JetBrains-JediTerm"}) == "tmux"
assert f.term_profile({"TMUX": ""}) == "unknown"
assert f.term_profile({"TERMINAL_EMULATOR": "JetBrains-JediTerm"}) == "jediterm"
assert f.term_profile({"TERM_PROGRAM": "iTerm.app"}) == "iterm"
assert f.term_profile({"TERM_PROGRAM": "ghostty"}) == "unknown"
# The colour level, as Claude Code 2.1.304 decides it: true colour lowered
# to 256 under tmux unless CLAUDE_CODE_TMUX_TRUECOLOR, and lifted on the
# terminals it names.
from coding_agent_usage_line.spans import colour_level  # noqa: E402
assert colour_level({"TERM": "xterm-256color"}) == 2
assert colour_level({"TERM": "xterm-256color", "COLORTERM": "truecolor"}) == 3
assert colour_level({"TMUX": "/tmp/t,1,0", "COLORTERM": "truecolor"}) == 2
assert colour_level({"TMUX": "/tmp/t,1,0", "COLORTERM": "truecolor",
                     "CLAUDE_CODE_TMUX_TRUECOLOR": "1"}) == 3
assert colour_level({"TERM": "foot"}) == 3
assert colour_level({"TERM": "foot", "FORCE_COLOR": "2"}) == 2
assert colour_level({"TERM_PROGRAM": "vscode", "TERM": "xterm-256color"}) == 3
assert colour_level({"COLORTERM": "truecolor", "NO_COLOR": "1"}) == 0
assert colour_level({"TERM_PROGRAM": "iTerm.app"}) == 2
assert colour_level({"TERM_PROGRAM": "iTerm.app",
                     "TERM_PROGRAM_VERSION": "3.5.10"}) == 3
# spec.py, state_spec.py, options_spec.py, their .ts and the option tables
# of docs/options.md are generated from spec/*.jsonc.
import subprocess
spec = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "gen-spec.py")
assert subprocess.run([sys.executable, spec, "--check"]).returncode == 0
print("ok shared formatting")
