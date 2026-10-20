"""An agent transcript's lines, cut down to what the mod's fold reads.

    python3 agent_lines.py PATH START END

Reads PATH's whole lines from byte START, stopping before END or once the
output nears OUT_MAX, and prints the offset it stopped at, then one line
per line read: its length in bytes, a tab, and its record with only the
fields foldAgentRecord (src/claude_records.ts) reads, as ASCII JSON.  A
line that is not a JSON object prints as "-", which the fold skips as it
skips the line itself.

    python3 agent_lines.py fold PATH END DIR

The session's own transcript, for foldOf (hooks/edges.ts), with nothing
printed but an offset: the fold saved in DIR, the main-fold state
directory, read on over PATH's whole lines up to END and saved back into
DIR, as coding_agent_usage_line/main_fold.py's fold_on does it.  The
offset is the one saved to, from which the mod reads the head and the
parts itself.  No record passes through the 4 MiB of output the engine
keeps of a process.  The package is the repository's, beside mod/; a copy
of mod/ on its own has none, and exits 1 having written nothing, for the
mod to fold the bytes itself.

Run as a process so the parsing is the process's time, not the hooks
worker's: 99% of a big agent file is tool results' text and request
blobs, which the fold never reads (measured 2026-10-20).
"""

import json
import os
import sys

# Under the 4 MiB the engine passes of a process's output.
OUT_MAX = 3 * 1024 * 1024
# Records the fold reads more of than their type and time, all small.
WHOLE = {"assistant", "system", "queue-operation"}
# What the fold reads of a block in a user record's content list.
BLOCK_KEYS = ("type", "tool_use_id", "id", "name")


def block(b):
    if not isinstance(b, dict):
        return b
    return {k: b[k] for k in BLOCK_KEYS if k in b}


def hunk(h):
    if not isinstance(h, dict):
        return None
    lines = h.get("lines")
    if isinstance(lines, list):
        # Only a line's first character, `+` or `-`, is counted.
        lines = [l[0] if isinstance(l, str) and l else
                 (l if isinstance(l, str) else None) for l in lines]
    return {"lines": lines}


def tool_result(res):
    """diffLines' reading of toolUseResult: the patch's +/- lines, or a
    created file's line count, kept as that many newlines."""
    if not isinstance(res, dict):
        return None
    patch = res.get("structuredPatch")
    if isinstance(patch, list) and patch:
        return {"structuredPatch": [hunk(h) for h in patch]}
    content = res.get("content")
    if res.get("type") == "create" and isinstance(content, str):
        return {"type": "create", "content": "\n" * len(content.splitlines())}
    return {}


def project(r):
    t = r.get("type")
    if t in WHOLE:
        return r
    if t != "user":
        return {k: r[k] for k in ("type", "timestamp") if k in r}
    r = dict(r)
    m = r.get("message")
    if isinstance(m, dict) and isinstance(m.get("content"), list):
        r["message"] = dict(m, content=[block(b) for b in m["content"]])
    if "toolUseResult" in r:
        r["toolUseResult"] = tool_result(r["toolUseResult"])
    return r


def line_of(raw):
    try:
        # A leading byte-order mark dropped, as TextDecoder drops it.
        r = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return "-"
    if not isinstance(r, dict):
        return "-"
    return json.dumps(project(r), separators=(",", ":"))


def fold(path, end, d):
    # The repository holds mod/scripts/ and the package side by side.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    try:
        from coding_agent_usage_line.main_fold import fold_on
    except ImportError as e:
        sys.exit("no coding_agent_usage_line package beside mod/: %s" % e)
    sys.stdout.write("%d\n" % fold_on(path, d, end))


def main():
    if sys.argv[1:2] == ["fold"]:
        fold(sys.argv[2], int(sys.argv[3]), sys.argv[4])
        return
    path, pos, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    out, size = [], 0
    with open(path, "rb") as f:
        f.seek(pos)
        while pos < end:
            raw = f.readline(end - pos)
            if not raw.endswith(b"\n"):
                break
            text = "%d\t%s\n" % (len(raw), line_of(raw))
            if len(text) > OUT_MAX:
                # A record too big to pass even cut down: skipped.
                text = "%d\t-\n" % len(raw)
            if out and size + len(text) > OUT_MAX:
                break
            out.append(text)
            size += len(text)
            pos += len(raw)
    sys.stdout.write("%d\n" % pos)
    sys.stdout.write("".join(out))


if __name__ == "__main__":
    main()
