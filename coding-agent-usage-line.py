#!/usr/bin/env python3
"""Thin, installation-free launcher for coding-agent-usage-line."""
import os
import sys

# importlib-based fixture tests do not put this launcher's directory on
# sys.path.  A checkout must remain runnable without installation.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from coding_agent_usage_line.cli import main as cli_main

if __name__ == "__main__":
    raise SystemExit(cli_main())
