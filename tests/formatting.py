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
f.set_mark_spacing(False)
assert f.MARK_SP == "" and f.C_TOK == f.C_TOK_TIGHT
f.set_mark_spacing(True)
assert f.MARK_SP == " " and f.C_TOK == f.C_TOK_TIGHT + 1
f.set_subscript_decimals(True)
assert f.sub_dec("1.2") == "1₂"
f.set_subscript_decimals(False)
print("ok shared formatting")
