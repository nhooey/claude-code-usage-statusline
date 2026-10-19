#!/usr/bin/env python3
"""Regenerate everything under tests/fixtures/ but gen/ itself.

    python3 tests/fixtures/gen/all.py

Then read `git diff tests/fixtures/` before committing: the fixtures are
inputs, so a change to them is a change to every golden that reads them.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import calib  # noqa: E402
import cases  # noqa: E402
import cost  # noqa: E402
import formatting  # noqa: E402
import panel  # noqa: E402
import receipt  # noqa: E402
import records  # noqa: E402
import render  # noqa: E402
import sources  # noqa: E402
import status  # noqa: E402

# Written whole each time, so a fixture whose generator entry is gone does
# not linger.
for d in ("env", "payloads", "transcripts"):
    shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)
status.main(ROOT)
cost.main(ROOT)
panel.main(ROOT)
cases.main(ROOT)
# Under 3.9 as well: 3.12's sum() of floats rounds differently.
calib.main()
formatting.main()
render.main()
# After cases.json, whose subagent cases it runs to capture the corpus.
panel.main_panel()
# Draws the committed cost figures documents, which run-cases.py writes.
receipt.main()
records.main()
# Last, since it sets TZ for the process.  Under /usr/bin/python3: its
# expected epochs are 3.9's fromisoformat, quirks included.
sources.main()
