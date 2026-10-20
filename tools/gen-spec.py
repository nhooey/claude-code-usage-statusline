#!/usr/bin/env python3
"""Generate both languages' constants from the JSONC files under spec/.

    python3 tools/gen-spec.py           # rewrite them all
    python3 tools/gen-spec.py --check   # exit 1 if any is out of date

spec/layout.jsonc is the one place the glyphs, the colours, the widths and
cuts, the wide-character table and the terminal-profile rules are written,
each beside the comment that explains it.  This writes them out as
coding_agent_usage_line/spec.py, which formatting.py star-imports, and as
mod/src/spec.ts for the mod, comments and all, so either language's copy can
be read on its own.  spec/state.jsonc, the files both ports keep in the state
directory, goes the same way, to state_spec.py and state_spec.ts, and so
does spec/options.jsonc, every option either port takes, to options_spec.py
and options_spec.ts, with an Options type for the mod's and the option
tables of docs/options.md, between their markers.  tests/formatting.py
runs --check.

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
                          ("state.jsonc", "state_spec"),
                          ("options.jsonc", "options_spec"))]
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
        # A string too long for the width has nothing to break at, so it
        # runs past it.
        if one is not None and (len(pad + prefix + one + suffix) <= WIDTH
                                or node.kind not in ("obj", "arr")):
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
            prefix, col = "export const " + m.key + " = ", m.col + 12
            suffix = " as const;" if m.key in AS_CONST else ";"
        lines += lang.block(prefix, m, suffix, 0, col)
    if lang.name == "ts" and root.value and root.value[0].key == "OPTIONS":
        lines += [""] + options_type(plain(root.value[0]))
    return "\n".join(l.rstrip() for l in lines) + "\n"


# ── The options ─────────────────────────────────────────────────────────────

# Constants written `as const` in TypeScript, so their records keep their
# literal types.
AS_CONST = {"OPTIONS"}
TYPES = ("bool", "int", "string", "enum", "list", "table")
FIELDS = ("type", "items", "fields", "metavar", "default", "derived",
          "minimum", "ports", "agents", "file", "flag", "aliases",
          "negatable", "modes", "doc-table", "doc-default", "usage", "doc")
REQUIRED = ("type", "default", "ports", "file", "flag", "doc-table", "doc")
MODES = ["status", "cost", "subagent"]
DOC = os.path.join("docs", "options.md")
# The tables of docs/options.md, by the name their markers give, and the
# column between the option and its effect.
DOC_TABLES = {"shared": "Default", "display": "Modes"}


def plain(node):
    """The value a node holds, as json.loads would give it."""
    if node.kind == "obj":
        return {c.key: plain(c) for c in node.value}
    if node.kind == "arr":
        return [plain(c) for c in node.value]
    if node.kind == "num":
        return json.loads(node.raw)
    if node.kind == "word":
        return json.loads(node.value)
    return node.value


def join_docs(root):
    """Each option's doc and usage, written as lines, made the one string
    each is."""
    for opt in root.value[0].value:
        for f in opt.value:
            if f.key in ("doc", "usage") and f.kind == "arr":
                f.kind, f.value = "str", " ".join(c.value for c in f.value)


def fits(t, value, items):
    if value is None:
        return True
    if t == "bool":
        return isinstance(value, bool)
    if t == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "string":
        return isinstance(value, str)
    if t == "enum":
        return value in items
    if t == "list":
        return (isinstance(value, list)
                and all(isinstance(v, str) for v in value))
    return isinstance(value, dict)


def check_options(opts):
    """Refuse a record the ports could not read the same way."""
    def bad(name, why):
        raise SystemExit("options.jsonc: %s: %s" % (name, why))
    for name, o in opts.items():
        if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", name):
            bad(name, "not a flag's name")
        for k in o:
            if k not in FIELDS:
                bad(name, "unknown field %r" % k)
        for k in REQUIRED:
            if k not in o:
                bad(name, "no %r" % k)
        keys = [k for k in FIELDS if k in o]
        if list(o) != keys:
            bad(name, "fields out of order, want %s" % ", ".join(keys))
        t = o["type"]
        if t not in TYPES:
            bad(name, "unknown type %r" % t)
        if (t == "enum") != ("items" in o):
            bad(name, "items go with an enum, and only with one")
        if (t == "table") != ("fields" in o):
            bad(name, "fields go with a table, and only with one")
        if t == "table":
            if not isinstance(o["default"], dict) or not o["default"]:
                bad(name, "a table's default names its rows")
            for row, rec in o["default"].items():
                if set(rec) != set(o["fields"]):
                    bad(name, "row %r has other fields than the table's"
                        % row)
                for k, v in rec.items():
                    ft = o["fields"][k]
                    if not fits(ft["type"], v, ft.get("items")):
                        bad(name, "%s.%s is not a %s" % (row, k, ft["type"]))
        elif not fits(t, o["default"], o.get("items")):
            bad(name, "default %r is not a %s" % (o["default"], t))
        if not o["ports"] or set(o["ports"]) - {"py", "mod"}:
            bad(name, "ports are \"py\", \"mod\" or both")
        flag = o["flag"]
        if flag is not None and flag != "--" + name:
            bad(name, "its flag is --%s" % name)
        if flag is None and "py" in o["ports"] and o["file"] is False:
            bad(name, "the Python could not be given it")
        if (flag is not None) != ("usage" in o):
            bad(name, "a usage line goes with a flag, and only with one")
        if "usage" in o and not o["usage"].isascii():
            bad(name, "the usage text is plain ASCII, for any terminal")
        if o.get("negatable") and t != "bool":
            bad(name, "only a bool is negatable")
        if "minimum" in o and t != "int":
            bad(name, "only an int has a minimum")
        if "derived" in o:
            src = o["derived"]["from"]
            if src not in opts:
                bad(name, "derived from %r, which is no option" % src)
            for v in o["derived"]["map"].values():
                if not fits(t, v, o.get("items")):
                    bad(name, "derives %r, not a %s" % (v, t))
        if o["doc-table"] is not None:
            if o["doc-table"] not in DOC_TABLES:
                bad(name, "no doc table %r" % o["doc-table"])
            if flag is None:
                bad(name, "the doc tables are of flags")
        if o["doc-table"] == "display" and "modes" not in o:
            bad(name, "a display option says its modes")
        if set(o.get("modes", [])) - set(MODES):
            bad(name, "modes are %s" % ", ".join(MODES))


def camel(name):
    head, *rest = name.split("-")
    return head + "".join(w.capitalize() for w in rest)


def ts_type(t, items):
    if t in ("enum",):
        return " | ".join(json.dumps(i, ensure_ascii=False) for i in items)
    return {"bool": "boolean", "int": "number", "string": "string",
            "list": "readonly string[]"}[t]


def options_type(opts):
    """Options: the mod's merged value of each option it reads."""
    lines = ["// The merged value of each option the mod reads, by the camel",
             "// case of its name.",
             "export type Options = {"]
    for name, o in opts.items():
        if "mod" not in o["ports"]:
            continue
        if o["type"] == "table":
            lines.append("  readonly %s: {" % camel(name))
            for row in o["default"]:
                lines.append("    readonly %s: {" % camel(row))
                lines += ["      readonly %s: %s;"
                          % (camel(k), ts_type(f["type"], f.get("items")))
                          for k, f in o["fields"].items()]
                lines.append("    };")
            lines.append("  };")
            continue
        t = ts_type(o["type"], o.get("items"))
        if o["default"] is None and "derived" not in o:
            t += " | null"
        lines.append("  readonly %s: %s;" % (camel(name), t))
    lines.append("};")
    return lines


def cell(text):
    return text.replace("|", "\\|")


def doc_table(opts, which):
    """One table of docs/options.md, a row per option it lists."""
    second = DOC_TABLES[which]
    rows = ["| Option | %s | Effect |" % second, "|---|---|---|"]
    for name, o in opts.items():
        if o["doc-table"] != which:
            continue
        flag = o["flag"]
        if o.get("negatable") and o["default"] is True:
            flag = "--no-" + flag[2:]
        if o["type"] != "bool":
            flag += " " + (o.get("metavar") or "|".join(o["items"]))
        if second == "Modes":
            modes = o["modes"]
            mid = "all" if sorted(modes) == sorted(MODES) else ", ".join(modes)
        elif "doc-default" in o:
            mid = o["doc-default"]
        elif o["default"] in (None, []):
            mid = "none"
        elif o["default"] is False:
            mid = "off"
        else:
            mid = "`%s`" % o["default"]
        rows.append("| %s | %s | %s |" % (cell("`%s`" % flag), cell(mid),
                                          cell(o["doc"])))
    return rows


def with_doc_tables(text, opts):
    """docs/options.md with each table between its markers written anew."""
    for which in DOC_TABLES:
        begin = "<!-- options:begin %s -->" % which
        end = "<!-- options:end %s -->" % which
        m = re.search(r"^%s\n.*?^%s$" % (re.escape(begin), re.escape(end)),
                      text, re.M | re.S)
        if not m:
            raise SystemExit("%s: no %s ... %s" % (DOC, begin, end))
        body = "\n".join([begin] + doc_table(opts, which) + [end])
        text = text[:m.start()] + body + text[m.end():]
    return text


def main():
    outs = {}
    for source, py_out, ts_out in SPECS:
        root = read(os.path.join(REPO, source))
        src = source.replace(os.sep, "/")
        if source.endswith("options.jsonc"):
            join_docs(root)
            opts = plain(root.value[0])
            check_options(opts)
            doc = os.path.join(REPO, DOC)
            with open(doc, encoding="utf-8") as fh:
                outs[doc] = with_doc_tables(fh.read(), opts)
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
