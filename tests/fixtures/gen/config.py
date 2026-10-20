#!/usr/bin/env python3
"""Write the shared configuration cases, tests/fixtures/config/cases.json,
which pin coding_agent_usage_line/config.py and the mod's port of it to one
answer (agents/plans/config-merge.md, "Shared cases").

    /usr/bin/python3 tests/fixtures/gen/config.py

Each case is a tree of files built in a scratch directory, the environment
and the directory the walk starts from, and the flags; and what the Python
made of them, recorded under "expected":

  tree      relative path -> the file's text, or null for a directory.
            `${ROOT}` in a text is the scratch directory's path
  env       the variables the reader sees; `${ROOT}` as above.  HOME is
            ${ROOT}/home unless the case says otherwise
  start     where the walk starts
  flags     the command line's options; the mod, which has none, runs the
            cases whose flags are empty
  expected  root      the project root found, or null
            paths     each file layer's path, found or not; null for a
                      project layer with no root
            options   every option whose layer is not "default", as
                      [value, layer]; a table's fields are under "fields"
            fields    "table.row.field" -> [value, layer], for each field
                      a file set
            warnings  in order, each "PATH: what"

tests/config.py runs every case again and compares it with this file.
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(FIXTURES))
OUT = os.path.join(FIXTURES, "config", "cases.json")
sys.path.insert(0, REPO)

from coding_agent_usage_line import cli, config  # noqa: E402
from coding_agent_usage_line.options import flag_values, parse  # noqa: E402

D = ".config/coding-agent-usage-line/"
USER = "home/" + D + "config.jsonc"
PROJECT = "home/p/" + D + "config.jsonc"
LOCAL = "home/p/" + D + "config.local.jsonc"


def case(id, about, tree, start="${ROOT}/home/p", env=None, flags=()):
    return {"id": id, "about": about, "tree": tree,
            "env": dict({"HOME": "${ROOT}/home"}, **(env or {})),
            "start": start, "flags": list(flags)}


CASES = [
    # ── Precedence ──────────────────────────────────────────────────────
    case("defaults", "no file anywhere: the defaults, and label derived",
         {"home/p/.git/": None}),
    case("user", "the user file alone",
         {USER: '{"account": "u", "totals": false}', "home/p/.git/": None}),
    case("project-over-user", "the committed project file over the user's",
         {USER: '{"account": "u", "prefix": "U"}',
          PROJECT: '{"account": "p"}', "home/p/.git/": None}),
    case("local-over-project", "the local file over the committed one, and"
         " each key from the highest layer that has it",
         {USER: '{"account": "u", "prefix": "U", "color": true}',
          PROJECT: '{"account": "p", "prefix": "P"}',
          LOCAL: '{"account": "l"}', "home/p/.git/": None}),
    case("flag-over-local", "a flag over every file",
         {LOCAL: '{"account": "l", "usage-text": false}',
          "home/p/.git/": None},
         flags=["--account", "f", "--usage-text"]),
    case("config-dir-over-xdg", "the tests' directory over XDG's",
         {"cfg/config.jsonc": '{"account": "cfg"}',
          "xdg/coding-agent-usage-line/config.jsonc": '{"account": "xdg"}',
          USER: '{"account": "home"}'},
         env={"CODING_AGENT_USAGE_LINE_CONFIG_DIR": "${ROOT}/cfg",
              "XDG_CONFIG_HOME": "${ROOT}/xdg"}),
    case("xdg-over-home", "XDG_CONFIG_HOME over ~/.config",
         {"xdg/coding-agent-usage-line/config.jsonc": '{"account": "xdg"}',
          USER: '{"account": "home"}'},
         env={"XDG_CONFIG_HOME": "${ROOT}/xdg"}),
    case("xdg-relative-ignored", "a relative XDG_CONFIG_HOME is ignored",
         {USER: '{"account": "home"}'}, env={"XDG_CONFIG_HOME": "xdg"}),

    # ── Lists replace ───────────────────────────────────────────────────
    case("list-empty-replaces", "a project's empty hide means none",
         {USER: '{"hide": ["a", "b"]}', PROJECT: '{"hide": []}',
          "home/p/.git/": None}),
    case("list-flag-repeated", "a repeated flag makes one list, which"
         " replaces the files'; a flag over a file for an option the mod"
         " reads is said",
         {PROJECT: '{"hide": ["c"]}', "home/p/.git/": None},
         flags=["--hide", "a", "--hide", "b"]),

    # ── Tables merge per field ──────────────────────────────────────────
    case("table-per-field", "rows merged field by field across three files",
         {USER: '{"rows": {"agent": {"transcript": true}}}',
          PROJECT: '{"rows": {"agent": {"live": "never"},'
                   ' "turn": {"live": "never"}}}',
          LOCAL: '{"rows": {"turn": {"live": "always"}}}',
          "home/p/.git/": None}),

    # ── The walk ────────────────────────────────────────────────────────
    case("walk-two-up", "a file two directories above the start",
         {PROJECT: '{"account": "p"}', "home/p/.git/": None,
          "home/p/a/b/": None}, start="${ROOT}/home/p/a/b"),
    case("walk-git-stops", "a .git between the start and the file stops"
         " the walk",
         {PROJECT: '{"account": "p"}', "home/p/sub/.git/": None,
          "home/p/sub/a/": None}, start="${ROOT}/home/p/sub/a"),
    case("walk-file-at-git", "the directory with .git is still looked in",
         {LOCAL: '{"account": "l"}', "home/p/.git/": None,
          "home/p/a/": None}, start="${ROOT}/home/p/a"),
    case("walk-none", "no project file up to $HOME",
         {"home/p/a/": None}, start="${ROOT}/home/p/a"),
    case("walk-stops-at-home", "$HOME's .config is the user file's, never"
         " a project's, and nothing above $HOME is looked in",
         {USER: '{"account": "home"}',
          D + "config.jsonc": '{"account": "above-home"}',
          "home/p/": None}),
    case("walk-missing-start", "a start that does not exist still walks up",
         {PROJECT: '{"account": "p"}'}, start="${ROOT}/home/p/gone/deeper"),
    case("worktree-takes-main-local", "a worktree with no local file reads"
         " its main checkout's, at the same place",
         {"home/main/" + D + "config.local.jsonc": '{"account": "main"}',
          "home/main/.git/worktrees/wt/commondir": "../..\n",
          "home/wt/.git": "gitdir: ${ROOT}/home/main/.git/worktrees/wt\n",
          "home/wt/a/": None}, start="${ROOT}/home/wt/a"),
    case("worktree-committed-and-main-local", "a worktree's committed file,"
         " with the main checkout's local file over it",
         {"home/main/" + D + "config.jsonc": '{"account": "main-p"}',
          "home/main/" + D + "config.local.jsonc": '{"account": "main-l"}',
          "home/main/.git/worktrees/wt/commondir": "../..\n",
          "home/wt/" + D + "config.jsonc": '{"account": "wt-p",'
                                           ' "prefix": "W"}',
          "home/wt/.git": "gitdir: ../main/.git/worktrees/wt\n"},
         start="${ROOT}/home/wt"),
    case("worktree-own-local", "a worktree's own local file wins",
         {"home/main/" + D + "config.local.jsonc": '{"account": "main"}',
          "home/main/.git/worktrees/wt/commondir": "../..\n",
          "home/wt/" + D + "config.local.jsonc": '{"account": "wt"}',
          "home/wt/.git": "gitdir: ${ROOT}/home/main/.git/worktrees/wt\n"},
         start="${ROOT}/home/wt"),
    case("submodule-no-main", "a submodule's .git file has no commondir,"
         " so no main checkout",
         {"home/sup/" + D + "config.local.jsonc": '{"account": "sup"}',
          "home/sup/.git/modules/sub/HEAD": "ref: refs/heads/main\n",
          "home/sup/sub/.git": "gitdir: ../.git/modules/sub\n"},
         start="${ROOT}/home/sup/sub"),

    # ── JSONC ───────────────────────────────────────────────────────────
    case("jsonc", "// in a string kept, // after a value stripped, trailing"
         " commas stripped, and one inside a string kept",
         {PROJECT: '{\n  // a comment\n  "prefix": "a//b", // after\n'
                   '  "label": "x,}",\n  "hide": ["p", "q",],\n'
                   '  "account": "a\\"//,]",\n}\n',
          "home/p/.git/": None}),
    case("version", "\"version\": 1 is read past",
         {PROJECT: '{"version": 1, "account": "v1"}', "home/p/.git/": None}),
    case("version-unknown", "another version skips the file",
         {USER: '{"account": "u"}',
          PROJECT: '{"version": 2, "account": "v2"}', "home/p/.git/": None}),

    # ── Bad files and values ────────────────────────────────────────────
    case("bad-json", "a file that is not JSONC is skipped whole",
         {USER: '{"account": "u"}', PROJECT: '{"account": "p",,}',
          "home/p/.git/": None}),
    case("not-object", "a file that is not an object is skipped whole",
         {USER: '{"account": "u"}', PROJECT: '["account"]',
          "home/p/.git/": None}),
    case("unknown-keys", "an unknown key, with the nearest known one when"
         " one is near",
         {PROJECT: '{"rwos": {}, "usage-sorce": "none", "zzzzzz": 1,'
                   ' "account": "kept"}', "home/p/.git/": None}),
    case("per-run-keys", "a key that describes one run is skipped",
         {PROJECT: '{"cols": 80, "mode": "cost", "show-config": true,'
                   ' "account": "kept"}', "home/p/.git/": None}),
    case("bad-values", "each value of the wrong type, out of range or not"
         " the enum's is skipped, and the layer under supplies it",
         {USER: '{"totals": false, "hint-inset": 4, "live-place": "above",'
                ' "account-period": "week", "prefix": "U"}',
          PROJECT: '{"totals": "no", "hint-inset": -1,'
                   ' "live-place": "abovee", "account-period": "year",'
                   ' "prefix": 7, "starts-kept": 0, "label": null}',
          "home/p/.git/": None}),
    case("usage-source-unknown", "a usage source no agent reads is"
         " skipped, and the layer under supplies it",
         {USER: '{"usage-source": "native"}',
          PROJECT: '{"usage-source": "bogus"}', "home/p/.git/": None}),
    case("whole-floats", "a whole float is an int, another float is not",
         {PROJECT: '{"hint-inset": 3.0, "starts-kept": 2.5}',
          "home/p/.git/": None}),
    case("list-bad-item", "one bad item skips the whole list",
         {USER: '{"hide": ["u"]}', PROJECT: '{"hide": ["a", 1]}',
          "home/p/.git/": None}),
    case("table-bad-parts", "a table's bad rows and fields are skipped"
         " alone, and the account row refuses to be stamped",
         {PROJECT: '{"rows": {"turn": {"live": "allways",'
                   ' "transcript": false}, "tunr": {}, "agent": 3,'
                   ' "session": {"lvie": "never", "live": "running"},'
                   ' "account": {"transcript": true, "live": "never"}}}',
          "home/p/.git/": None}),
    case("table-not-object", "a table that is not an object is skipped",
         {USER: '{"rows": {"tag": {"live": "always"}}}',
          PROJECT: '{"rows": []}', "home/p/.git/": None}),

    # ── Derived values ──────────────────────────────────────────────────
    case("derived-label", "label follows usage-text from a file",
         {PROJECT: '{"usage-text": false}', "home/p/.git/": None}),
    case("derived-label-set", "a label a layer sets is not derived",
         {USER: '{"label": "L"}', PROJECT: '{"usage-text": false}',
          "home/p/.git/": None}),
    case("right-edge-not-yet-derived", "right-edge keeps its default under"
         " live-place until the mod draws from the merged options",
         {PROJECT: '{"live-place": "above"}', "home/p/.git/": None}),
]


def fill(text, root):
    return text.replace("${ROOT}", root)


def unfill(text, root):
    return text.replace(root, "${ROOT}")


def build(tree, root):
    for rel, text in tree.items():
        path = os.path.join(root, rel)
        if text is None:
            os.makedirs(path, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(fill(text, root))


def _plain(value):
    if isinstance(value, tuple):
        return list(value)
    return value


def run(c):
    """What the Python makes of case `c`, as its "expected" records it."""
    root = tempfile.mkdtemp(prefix="config-case.")
    try:
        build(c["tree"], root)
        env = {k: fill(v, root) for k, v in c["env"].items()}
        found = config.load(fill(c["start"], root), env)
        options = cli._merged(flag_values(parse(c["flags"])), found, None,
                              ("py", "mod"))
        values, fields = {}, {}
        for name in options:
            value = options[name]
            if isinstance(value, dict) or hasattr(value, "items"):
                for row, rec in value.items():
                    for field, v in rec.items():
                        layer = options.field_layer(name, row, field)
                        if layer != "default":
                            fields["%s.%s.%s" % (name, row, field)] = [v, layer]
            elif options.layer(name) != "default":
                values[name] = [_plain(value), options.layer(name)]
        expected = {
            "root": found.root, "paths": found.paths, "options": values,
            "fields": fields, "warnings": list(options.warnings)}
        return json.loads(unfill(json.dumps(expected, ensure_ascii=False),
                                 root))
    finally:
        shutil.rmtree(root)


def main():
    cases = [dict(c, expected=run(c)) for c in CASES]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("[\n" + ",\n".join(json.dumps(c, ensure_ascii=False)
                                    for c in cases) + "\n]\n")
    print("config: %d cases" % len(cases))


if __name__ == "__main__":
    main()
