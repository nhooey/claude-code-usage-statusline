#!/usr/bin/env python3
"""Write the cases that pin mod/src/claude.ts's small pure parts to the
glue in claude.py.

    /usr/bin/python3 tests/fixtures/gen/claude.py

The figures documents under tests/fixtures/figures/ pin the glue whole:
mod/test/claude.test.ts builds each one again from its inputs.  These are
the parts a document reaches only at a few values, each case one call:

  ctx_window   ctx_window_for(size, name): the payload's figure, else the
               guess from the model's name.
  window_for   window_for(turns, session_id) with a published window or
               none: only each turn's `ctx` is read, so a turn is written
               as that number.
  pct_str      _pct_str(v), "%g", over figures that round, carry an
               exponent or sit on a tie.
  main_root    _main_root(common, toplevel), git's common dir resolved to
               the main repository's root.

Written to tests/fixtures/claude/glue.json.  A float JSON cannot carry is
{"$float": ...}, as gen/calib.py writes it.
"""
import json
import os
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(FIXTURES))
OUT = os.path.join(FIXTURES, "claude")
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

from calib import enc  # noqa: E402
from coding_agent_usage_line import claude  # noqa: E402

CTX_WINDOW = [
    ("1000000", ""), ("200000", "Opus 5 (1M context)"),
    ("", "Opus 5 (1M context)"), ("", "claude-opus-5[1m]"),
    ("", "claude-opus-5-1000000"), ("", "claude-sonnet-5"),
    ("0", "claude-sonnet-5"), ("-5", "claude-opus-5[1m]"), ("12a", ""),
    ("", ""), ("٣٠٠٠٠٠", ""), ("400000", "claude-haiku-5"),
]

WINDOW_FOR = [
    ([], 0), ([10, 150000], 0), ([150000, 200000], 0), ([200001], 0),
    ([250000, 0], 0), ([10], 400000), ([900000], 200000), ([], 1000000),
]

PCT_STR = [
    None, 0.0, -0.0, 15.0, 15, 0.38, 3.8123456, 100.0, 1e-5, 0.0001,
    0.00012345678, 123456789.0, 999999.5, 999999.4, 2.5e-7, 0.45000000000000007,
    1.234565, 12.5, 0.125, 1e16, float("inf"), float("nan"), 33.333333333,
]

MAIN_ROOT = [
    ("/r/.git", "/r"), ("/r/.git", "/r/.claude/worktrees/w"), (".git", "/r"),
    ("/r/bare.git", "/r"), ("/r/.git", ""), ("../.git", "/r/sub"),
    ("/.git", "/"),
]


def main():
    cases = {
        "ctx_window": [{"size": s, "name": n,
                        "expected": claude.ctx_window_for(s, n)}
                       for s, n in CTX_WINDOW],
        "pct_str": [{"v": enc(v), "expected": claude._pct_str(v)}
                    for v in PCT_STR],
        "main_root": [{"common": c, "toplevel": t,
                       "expected": list(claude._main_root(c, t))}
                      for c, t in MAIN_ROOT],
        "window_for": [],
    }
    # window_for reads the published window from the state directory, so
    # each case publishes into a private one first, or publishes nothing.
    saved = os.environ.get("CODING_AGENT_USAGE_LINE_STATE_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = tmp
        try:
            for i, (ctxs, published) in enumerate(WINDOW_FOR):
                sid = "glue-%d" % i
                if published:
                    claude.publish_ctx_window(sid, published)
                turns = [SimpleNamespace(ctx=c) for c in ctxs]
                cases["window_for"].append({
                    "ctx": ctxs, "published": published,
                    "expected": claude.window_for(turns, sid)})
        finally:
            if saved is None:
                os.environ.pop("CODING_AGENT_USAGE_LINE_STATE_DIR", None)
            else:
                os.environ["CODING_AGENT_USAGE_LINE_STATE_DIR"] = saved
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "glue.json"), "w", encoding="utf-8") as fh:
        json.dump(cases, fh, indent=1, sort_keys=True, ensure_ascii=False,
                  allow_nan=False)
        fh.write("\n")
    print("claude: %d cases" % sum(len(v) for v in cases.values()))


if __name__ == "__main__":
    main()
