#!/usr/bin/env python3
"""Generate both languages' constants from the JSONC files under spec/.

    python3 tools/gen-spec.py           # rewrite both
    python3 tools/gen-spec.py --check   # exit 1 if either is out of date

spec/layout.jsonc is the one place the glyphs, the colours, the widths and
cuts, the wide-character table and the terminal-profile rules are written,
each beside the comment that explains it.  This writes them out as
coding_agent_usage_line/spec.py, which formatting.py star-imports, and as
mod/src/spec.ts for the mod, comments and all, so either language's copy can
be read on its own.  spec/state.jsonc, the files both ports keep in the state
directory, goes the same way, to state_spec.py and state_spec.ts.
tests/formatting.py runs --check.

Each JSONC is one object of NAME: value, in the order the values are written
out.  Three forms are read specially:

    "F_BLU": "rgb(100, 170, 255)"   an F_ or B_ name: a foreground or
                                    background colour, written out as an
                                    escape code in Python and as hex in
                                    TypeScript
    "F_SPIN": {"same_as": "F_RED"}  another name's value, which must come
                                    earlier
    [1, 2]                          an array: a tuple in Python

A comment above a member is written above it, and one after it on its line,
with the lines under it that start further right, is written after it.
"""
import json
import os
import re
import sys
import unicodedata

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Each source, and the Python and the TypeScript written from it.
SPECS = [(os.path.join("spec", src),
          os.path.join("coding_agent_usage_line", out + ".py"),
          os.path.join("mod", "src", out + ".ts"))
         for src, out in (("layout.jsonc", "spec"),
                          ("state.jsonc", "state_spec"))]
WIDTH = 79
RGB = re.compile(r"rgb\((\d+), (\d+), (\d+)\)$")


# ── Reading ─────────────────────────────────────────────────────────────────

class Node:
    """A value, with the comments around it in the source.

    lead is a list of comment texts, None for a blank line; tail the comment
    after it on its line and the lines continuing it; col where that comment
    started, measured from the member's own indent.
    """

    def __init__(self, kind, value, raw=None):
        self.kind, self.value, self.raw = kind, value, raw
        self.key = None
        self.lead, self.tail, self.col = [], [], 0


TOKEN = re.compile(r"""
    (?P<ws>[ \t]+) | (?P<nl>\n) | (?P<comment>//[^\n]*)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<number>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
  | (?P<word>true|false|null) | (?P<punct>[{}\[\]:,])
""", re.X)


def width(s):
    """Columns s takes in an editor: the comments align by what shows.

    Everything from U+1F300 up is called wide outright, since a Python
    whose Unicode tables predate a glyph calls it narrow, and --check has to
    give one answer under every Python CI runs."""
    return sum(2 if ord(c) >= 0x1F300
               or unicodedata.east_asian_width(c) in "WF" else 1
               for c in s)


def tokens(text):
    out, line, start, pos = [], 1, 0, 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise SystemExit("%s:%d: cannot read %r"
                             % (NAME, line, text[pos:pos + 20]))
        kind = m.lastgroup
        if kind == "nl":
            line, start = line + 1, m.end()
        elif kind != "ws":
            out.append((kind, m.group(), line, width(text[start:pos])))
        pos = m.end()
    out.append(("eof", "", line + 1, 0))
    return out


class Reader:
    def __init__(self, text):
        self.toks, self.i = tokens(text), 0
        self.last_line = 0

    def peek(self):
        return self.toks[self.i]

    def take(self, kind=None, text=None):
        t = self.toks[self.i]
        if (kind and t[0] != kind) or (text and t[1] != text):
            raise SystemExit("%s:%d: expected %s, found %r"
                             % (NAME, t[2], text or kind, t[1]))
        self.i += 1
        self.last_line = t[2]
        return t

    def lead(self):
        """The comments and blank lines before the next value."""
        out = []
        while True:
            t = self.peek()
            if t[2] > self.last_line + 1 and self.last_line:
                out.append(None)
            if t[0] != "comment":
                return out
            out.append(t[1][2:])
            self.take()

    def tail(self, node, indent):
        """The comment after a value on its line, and its continuations."""
        if self.peek()[1] == ",":
            self.take()
        t = self.peek()
        if t[0] != "comment" or t[2] != self.last_line:
            return
        node.col = t[3] - indent
        node.tail.append(t[1][2:])
        self.take()
        while True:
            t = self.peek()
            if (t[0] != "comment" or t[2] != self.last_line + 1
                    or t[3] <= indent):
                return
            node.tail.append(t[1][2:])
            self.take()

    def value(self):
        t = self.peek()
        if t[1] == "{":
            return self.members()
        if t[1] == "[":
            return self.elements()
        self.take()
        if t[0] == "string":
            return Node("str", json.loads(t[1]))
        if t[0] == "number":
            return Node("num", None, t[1])
        if t[0] == "word":
            return Node("word", t[1])
        raise SystemExit("%s:%d: unexpected %r" % (NAME, t[2], t[1]))

    def members(self):
        indent = self.take("punct", "{")[3]
        node = Node("obj", [])
        while True:
            lead = self.lead()
            if self.peek()[1] == "}":
                node.end_lead = lead
                self.take()
                return node
            key = self.take("string")
            child = self.value_after(":")
            child.key, child.lead = json.loads(key[1]), lead
            self.tail(child, key[3])
            node.value.append(child)

    def value_after(self, punct):
        self.take("punct", punct)
        return self.value()

    def elements(self):
        self.take("punct", "[")
        node = Node("arr", [])
        while True:
            lead = self.lead()
            if self.peek()[1] == "]":
                node.end_lead = lead
                self.take()
                return node
            indent = self.peek()[3]
            child = self.value()
            child.lead = lead
            self.tail(child, indent)
            node.value.append(child)


# The source being read, for the messages.
NAME = ""


def read(path):
    global NAME
    NAME = os.path.basename(path)
    with open(path, encoding="utf-8") as fh:
        r = Reader(fh.read())
    r.lead()
    root = r.members()
    if r.peek()[0] != "eof":
        raise SystemExit(NAME + ": text after the closing brace")
    names = set()
    for m in root.value:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", m.key):
            raise SystemExit("%s: %r is not a constant's name"
                             % (NAME, m.key))
        alias = same_as(m)
        if alias is not None and alias not in names:
            raise SystemExit("%s: %s is the same as %s, which is not "
                             "written above it" % (NAME, m.key, alias))
        names.add(m.key)
    return root


def same_as(node):
    if (node.kind == "obj" and len(node.value) == 1
            and node.value[0].key == "same_as"):
        return node.value[0].value
    return None


# ── Writing ─────────────────────────────────────────────────────────────────

def escape(ch, lang):
    cp = ord(ch)
    if cp < 0x10000:
        return "\\u%04x" % cp
    return "\\U%08x" % cp if lang == "py" else "\\u{%x}" % cp


def string(s, lang):
    out = []
    for ch in s:
        if ch in "\\\"":
            out.append("\\" + ch)
        # Invisible characters are written as escapes.  Not an unassigned
        # one: that is a glyph newer than this Python's tables (🪫 under
        # 3.9), and it has to come out the same under every Python.
        elif ch != " " and unicodedata.category(ch) in (
                "Cc", "Cf", "Zs", "Zl", "Zp"):
            out.append(escape(ch, lang))
        else:
            out.append(ch)
    return '"%s"' % "".join(out)


class Lang:
    """What differs between the two outputs."""

    def __init__(self, name, comment, indent, open_, close):
        self.name, self.comment, self.indent = name, comment, indent
        self.open, self.close = open_, close

    def scalar(self, node, key=None):
        if node.kind == "num":
            return node.raw
        if node.kind == "word":
            if self.name == "py":
                return {"true": "True", "false": "False",
                        "null": "None"}[node.value]
            return node.value
        m = RGB.match(node.value) if key and key[:2] in ("F_", "B_") else None
        if m:
            rgb = [int(x) for x in m.groups()]
            if self.name == "py":
                return '"\\033[%d;2;%d;%d;%dm"' % (
                    38 if key.startswith("F_") else 48, *rgb)
            return '"#%02x%02x%02x"' % tuple(rgb)
        return string(node.value, self.name)

    def flat(self, node, key=None):
        """The value on one line, or None if a comment inside forbids it."""
        if node.kind == "arr":
            parts = []
            for c in node.value:
                if c.lead or c.tail:
                    return None
                p = self.flat(c)
                if p is None:
                    return None
                parts.append(p)
            if self.name == "py" and len(parts) == 1:
                return "(%s,)" % parts[0]
            return self.open + ", ".join(parts) + self.close
        if node.kind == "obj":
            alias = same_as(node)
            if alias is not None and key is not None:
                return alias
            parts = []
            for c in node.value:
                if c.lead or c.tail:
                    return None
                p = self.flat(c)
                if p is None:
                    return None
                parts.append("%s: %s" % (string(c.key, self.name), p))
            return "{" + ", ".join(parts) + "}"
        return self.scalar(node, key)

    def comments(self, lead, pad):
        out = []
        for c in lead:
            out.append("" if c is None else pad + self.comment + c)
        return out

    def with_tail(self, code, node, col):
        """code, then node's trailing comment, aligned at col."""
        if not node.tail:
            return [code]
        col = max(col, width(code) + 2)
        out = [code + " " * (col - width(code)) + self.comment
               + node.tail[0]]
        out += [" " * col + self.comment + t for t in node.tail[1:]]
        return out

    def block(self, prefix, node, suffix, depth, col):
        """prefix + value + suffix, over as many lines as it needs."""
        pad = " " * (self.indent * depth)
        one = self.flat(node, prefix and node.key)
        if one is not None and len(pad + prefix + one + suffix) <= WIDTH:
            return self.with_tail(pad + prefix + one + suffix, node, col)
        kids = node.value
        opener = "{" if node.kind == "obj" else self.open
        closer = "}" if node.kind == "obj" else self.close
        inner = " " * (self.indent * (depth + 1))
        lines = [pad + prefix + opener]
        flats = [self.flat(c) for c in kids]
        if node.kind == "arr" and all(
                f is not None and c.kind in ("num", "arr")
                for f, c in zip(flats, kids)):
            # Numbers, or pairs of them: packed to the width, as a table
            # of ranges reads best.
            line = inner
            for f in flats:
                if len(line) + len(f) + 1 > WIDTH and line.strip():
                    lines.append(line.rstrip())
                    line = inner
                line += f + ", "
            lines.append(line.rstrip())
        else:
            for c in kids:
                lines += self.comments(c.lead, inner)
                key = ("" if node.kind == "arr"
                       else string(c.key, self.name) + ": ")
                lines += self.block(key, c, ",", depth + 1,
                                    len(inner) + c.col)
        lines += self.comments(getattr(node, "end_lead", []), inner)
        lines += self.with_tail(pad + closer + suffix, node, col)
        return lines


PY = Lang("py", "#", 4, "(", ")")
TS = Lang("ts", "//", 2, "[", "]")
HEAD = ("Generated by tools/gen-spec.py from %s.  Do not edit:",
        "change the JSONC and run `python3 tools/gen-spec.py`.")


def render(lang, root, source):
    c = lang.comment
    # The JSONC's own header is about the JSONC, so it stays there.
    lines = [c + " " + (h % source if "%" in h else h) for h in HEAD] + [""]
    for m in root.value:
        lines += lang.comments(m.lead, "")
        if lang.name == "py":
            prefix, suffix, col = m.key + " = ", "", m.col - 2
        else:
            prefix, suffix, col = "export const " + m.key + " = ", ";", \
                m.col + 12
        lines += lang.block(prefix, m, suffix, 0, col)
    return "\n".join(l.rstrip() for l in lines) + "\n"


def main():
    outs = {}
    for source, py_out, ts_out in SPECS:
        root = read(os.path.join(REPO, source))
        src = source.replace(os.sep, "/")
        outs[os.path.join(REPO, py_out)] = render(PY, root, src)
        outs[os.path.join(REPO, ts_out)] = render(TS, root, src)
    if sys.argv[1:] == ["--check"]:
        stale = []
        for path, text in outs.items():
            try:
                with open(path, encoding="utf-8") as fh:
                    if fh.read() == text:
                        continue
            except FileNotFoundError:
                pass
            stale.append(os.path.relpath(path, REPO))
        if stale:
            sys.stderr.write("out of date: %s: run python3 tools/gen-spec.py\n"
                             % ", ".join(stale))
            return 1
        return 0
    for path, text in outs.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
