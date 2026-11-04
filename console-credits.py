#!/usr/bin/env python3
"""The Claude Console's credits, for the mod's `credits.command`.

Point `credits.command` at this file; docs/options.md, "The Console's
credits", says how to give it the Console sign-in.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from coding_agent_usage_line.console_credits import main

if __name__ == "__main__":
    raise SystemExit(main())
