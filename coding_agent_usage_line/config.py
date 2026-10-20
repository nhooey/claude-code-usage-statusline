"""The configuration files: where they are, what they say, and what is
wrong with them (agents/plans/config-merge.md, "Files").

Three files, highest first:

  project-local  <root>/.config/coding-agent-usage-line/config.local.jsonc
  project        <root>/.config/coding-agent-usage-line/config.jsonc
  user           $CODING_AGENT_USAGE_LINE_CONFIG_DIR/config.jsonc, else
                 $XDG_CONFIG_HOME/coding-agent-usage-line/config.jsonc,
                 else ~/.config/coding-agent-usage-line/config.jsonc

`load` finds and reads them and hands back each one's checked values, by
option name, with a warning for whatever it skipped.  options.merge lays
them between the flags and the defaults.  Nothing here stops a run: a file
read by a hook never breaks a session, so what is wrong is skipped at the
smallest unit it can be, and said.

Imports nothing of the package but the spec, and only the stdlib.
"""
import json
import os
from collections import namedtuple

from .options_spec import OPTIONS

NAME = "coding-agent-usage-line"
PROJECT_FILE = "config.jsonc"
LOCAL_FILE = "config.local.jsonc"
# A config file is a few hundred bytes; one this size is something else.
MAX_BYTES = 64 * 1024
# The user-global directory, for the tests, as _STATE_DIR is for state.
CONFIG_DIR_ENV = "CODING_AGENT_USAGE_LINE_CONFIG_DIR"
# Where the project walk starts, in place of the payload's directory: the
# tests point it at a scratch tree, so no golden can find a developer's own
# project file above the directory a fixture names.
PROJECT_DIR_ENV = "CODING_AGENT_USAGE_LINE_PROJECT_DIR"

# The file layers, highest first.
FILE_LAYERS = ("project-local", "project", "user")

# One file's part in the merge: its layer, its path, and the values it gave
# that passed their checks, by option name.  A table's value holds only the
# rows and fields the file set.
Layer = namedtuple("Layer", "name path values")

# What `load` found: the directory the walk started from, the project root
# (None for none), each file layer's path whether or not a file is there
# (None for a project layer with no root), the layers read, and the
# warnings, each "PATH: what".
Found = namedtuple("Found", "start root paths layers warnings")


# ── JSONC ─────────────────────────────────────────────────────────────────


def strip_jsonc(text):
    """`text` with each `//` comment and each trailing comma blanked to
    spaces, outside strings, so json.loads reads what is left and its line
    numbers still hold.  A trailing comma is one followed, past blanks and
    comments, by `}` or `]`."""
    out = list(text)
    i, n = 0, len(text)
    in_string = False
    comma = None            # the index of a comma not yet followed by a value
    while i < n:
        c = text[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_string = False
        elif c == '"':
            in_string, comma = True, None
        elif c == "/" and text.startswith("//", i):
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        elif c == ",":
            comma = i
        elif c in "}]":
            if comma is not None:
                out[comma] = " "
            comma = None
        elif not c.isspace():
            comma = None
        i += 1
    return "".join(out)


# ── Where the files are ───────────────────────────────────────────────────


def user_dir(environ):
    """The user-global configuration directory."""
    given = environ.get(CONFIG_DIR_ENV)
    if given:
        return given
    xdg = environ.get("XDG_CONFIG_HOME")
    # The XDG spec has a relative path ignored.
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, NAME)
    return os.path.join(_home(environ), ".config", NAME)


def _home(environ):
    return environ.get("HOME") or os.path.expanduser("~")


def _project_files(d):
    base = os.path.join(d, ".config", NAME)
    return os.path.join(base, LOCAL_FILE), os.path.join(base, PROJECT_FILE)


def _ancestors(start, environ):
    """`start` and each directory above it, up to but not including $HOME
    or /: $HOME's .config is the user-global file's, never a project's."""
    home = os.path.abspath(_home(environ))
    stops = {home, os.path.realpath(home)}
    d = os.path.abspath(start)
    while d not in stops and os.path.dirname(d) != d:
        yield d
        d = os.path.dirname(d)


def main_checkout(top):
    """The main checkout of the worktree whose top directory is `top`, or
    None: `top/.git` is a file naming the worktree's git directory, whose
    `commondir` names the repository's.  A submodule's git directory has no
    `commondir`, and a bare repository's is no checkout's `.git`."""
    try:
        with open(os.path.join(top, ".git"), encoding="utf-8") as fh:
            line = fh.readline().strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = os.path.join(top, line[len("gitdir:"):].strip())
    try:
        with open(os.path.join(gitdir, "commondir"), encoding="utf-8") as fh:
            common = fh.readline().strip()
    except (OSError, UnicodeDecodeError):
        return None
    common = os.path.normpath(os.path.join(gitdir, common))
    if os.path.basename(common) != ".git":
        return None
    return os.path.dirname(common)


def find(start, environ):
    """The project root and the three files' paths, walking up from
    `start` (config-merge.md, "Finding the root").

    The first directory holding either project file is the root; the walk
    stops at a `.git` (a directory, or a worktree's file), at $HOME and at
    /.  A worktree with no local file of its own takes its main checkout's,
    at the same place under it (Decided 6), so settings made once follow
    every worktree."""
    root = top = None
    for d in _ancestors(start, environ):
        if any(os.path.isfile(p) for p in _project_files(d)):
            root = d
            break
        if os.path.exists(os.path.join(d, ".git")):
            top = d
            break
    if root is not None:
        for d in _ancestors(root, environ):
            if os.path.exists(os.path.join(d, ".git")):
                top = d
                break
    paths = {"user": os.path.join(user_dir(environ), PROJECT_FILE),
             "project-local": None, "project": None}
    if root is not None:
        paths["project-local"], paths["project"] = _project_files(root)
    if paths["project-local"] and os.path.isfile(paths["project-local"]):
        return root, paths
    main = main_checkout(top) if top is not None else None
    if main is None:
        return root, paths
    if root is not None:
        local = _project_files(os.path.normpath(
            os.path.join(main, os.path.relpath(root, top))))[0]
        if os.path.isfile(local):
            paths["project-local"] = local
        return root, paths
    # No project file in the worktree: the main checkout's local file, from
    # the place under it that `start` is under the worktree.
    mirrored = os.path.normpath(
        os.path.join(main, os.path.relpath(os.path.abspath(start), top)))
    for d in _ancestors(mirrored, environ):
        local = _project_files(d)[0]
        if os.path.isfile(local):
            paths["project-local"] = local
            return d, paths
        if d == main:
            break
    return root, paths


# ── What the files say ────────────────────────────────────────────────────


def nearest(word, known):
    """The known word nearest `word`, by edits (a swap of two neighbours
    counts one), when it is near enough to be the one meant; else None.
    The mod's port picks the same."""
    best, best_d = None, None
    for k in known:
        d = _distance(word, k)
        if best_d is None or d < best_d:
            best, best_d = k, d
    if best_d is not None and best_d <= max(1, len(word) // 3):
        return best
    return None


def _distance(a, b):
    """The optimal string alignment distance of `a` and `b`."""
    rows = [list(range(len(b) + 1))]
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            row[j] = min(rows[i - 1][j] + 1, row[j - 1] + 1,
                         rows[i - 1][j - 1] + cost)
            if (i > 1 and j > 1 and a[i - 1] == b[j - 2]
                    and a[i - 2] == b[j - 1]):
                row[j] = min(row[j], rows[i - 2][j - 2] + 1)
        rows.append(row)
    return rows[-1][-1]


def _hint(word, known):
    near = nearest(word, known)
    return " (did you mean %s?)" % json.dumps(near) if near else ""


def _quoted(items):
    return ", ".join(json.dumps(i, ensure_ascii=False) for i in items)


def _scalar(kind, value, spec, where):
    """`value` checked as a `kind`: (value, None) when it fits, else
    (None, why)."""
    if kind == "bool":
        if isinstance(value, bool):
            return value, None
        return None, "%s must be true or false" % where
    if kind == "int":
        # A whole float is the int JSON in the mod cannot tell from it.
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        least = spec.get("minimum")
        if isinstance(value, int) and not isinstance(value, bool) and (
                least is None or value >= least):
            return value, None
        if least is None:
            return None, "%s must be a whole number" % where
        return None, "%s must be a whole number, %d or more" % (where, least)
    if kind == "string":
        if isinstance(value, str):
            return value, None
        return None, "%s must be a string" % where
    if kind == "enum":
        if isinstance(value, str) and value in spec["items"]:
            return value, None
        hint = _hint(value, spec["items"]) if isinstance(value, str) else ""
        return None, "%s must be one of %s%s" % (where, _quoted(spec["items"]),
                                                hint)
    if kind == "list":
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return tuple(value), None
        return None, "%s must be a list of strings" % where
    raise ValueError(kind)


def _table(name, option, value):
    """A table's value checked field by field: (the rows and fields that
    passed, [why for each that did not])."""
    if not isinstance(value, dict):
        return {}, ["%s must be an object" % json.dumps(name)]
    kept, why = {}, []
    rows = list(option["default"])
    for row, rec in value.items():
        where = json.dumps("%s.%s" % (name, row))
        if row not in option["default"]:
            why.append("%s is no row%s" % (where, _hint(row, rows)))
            continue
        if not isinstance(rec, dict):
            why.append("%s must be an object" % where)
            continue
        for field, v in rec.items():
            spec = option["fields"].get(field)
            where = json.dumps("%s.%s.%s" % (name, row, field))
            if spec is None:
                why.append("%s is no field%s"
                           % (where, _hint(field, list(option["fields"]))))
                continue
            got, bad = _scalar(spec["type"], v, spec, where)
            if bad is None and row in spec.get("fixed", ()) and (
                    got != option["default"][row][field]):
                bad = "%s is always %s" % (
                    where, json.dumps(option["default"][row][field]))
            if bad is not None:
                why.append(bad)
            else:
                kept.setdefault(row, {})[field] = got
    return kept, why


def check(name, value):
    """One key of a file: (the value to merge, or None to skip it, [why
    for each part skipped])."""
    option = OPTIONS.get(name)
    if option is None:
        return None, ["%s is no option%s" % (json.dumps(name),
                                             _hint(name, list(OPTIONS)))]
    if not option["file"]:
        return None, ["%s describes one run, so no file sets it"
                      % json.dumps(name)]
    if option["type"] == "table":
        kept, why = _table(name, option, value)
        return (kept or None), why
    got, bad = _scalar(option["type"], value, option, json.dumps(name))
    return got, ([] if bad is None else [bad])


def read(path):
    """One file's checked values, by option name, and its warnings, each
    "PATH: what"; ({}, []) when there is no file."""
    try:
        if not os.path.isfile(path):
            return {}, []
        if os.path.getsize(path) > MAX_BYTES:
            return {}, ["%s: over %d KiB, so the file is skipped"
                        % (path, MAX_BYTES // 1024)]
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return {}, ["%s: unreadable, so the file is skipped" % path]
    try:
        data = json.loads(strip_jsonc(text))
    except ValueError:
        return {}, ["%s: not valid JSONC, so the file is skipped" % path]
    if not isinstance(data, dict):
        return {}, ["%s: not an object, so the file is skipped" % path]
    values, warnings = {}, []
    for name, value in data.items():
        if name == "version":
            # Reserved for a later change of shape.
            if value == 1 and not isinstance(value, bool):
                continue
            return {}, ["%s: \"version\" %s is not one this program reads, "
                        "so the file is skipped"
                        % (path, json.dumps(value, ensure_ascii=False))]
        got, why = check(name, value)
        warnings += ["%s: %s; skipped" % (path, w) for w in why]
        if got is not None:
            values[name] = got
    return values, warnings


def load(start, environ=None):
    """Every file layer from `start`'s project and the user, highest
    first, read and checked."""
    environ = os.environ if environ is None else environ
    start = environ.get(PROJECT_DIR_ENV) or start
    root, paths = find(start, environ)
    layers, warnings = [], []
    for name in FILE_LAYERS:
        if paths[name] is None:
            continue
        values, why = read(paths[name])
        warnings += why
        if values:
            layers.append(Layer(name, paths[name], values))
    return Found(os.path.abspath(start), root, paths, layers, warnings)


def start_dir(agent, mode, payload, transcript_cwd=None):
    """Where the project walk starts, by who is reading (config-merge.md,
    "Finding the root"): the payload's directory, else the process's."""
    payload = payload if isinstance(payload, dict) else {}
    tried = [payload.get("cwd"), transcript_cwd]
    if agent == "claude" and mode == "status":
        workspace = payload.get("workspace")
        if isinstance(workspace, dict):
            tried.insert(0, workspace.get("project_dir"))
    for value in tried:
        if isinstance(value, str) and value:
            return value
    return os.getcwd()
