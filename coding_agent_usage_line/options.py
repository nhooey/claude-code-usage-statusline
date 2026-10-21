"""The merged options: every option of spec/options.jsonc this port reads,
its value, and the layer it came from.

The adapters read options from here, never from argv: a flag, a config file
and a default then reach them as one answer per option, whichever spelling
or layer gave it.  Imports nothing of the package but the spec and
config.py, which reads the files whose layers `merge` takes and the
defaults file under them.
"""
from collections.abc import Mapping
from types import MappingProxyType

from .config import load_defaults
from .options_spec import OPTIONS

# The layers, highest first (config-merge.md, "Precedence"), and "derived"
# for a value worked out from another option's when no layer set it.
LAYERS = ("flag", "project-local", "project", "user", "default")

# This port's options, by every spelling of their flags.
_PY = {name: o for name, o in OPTIONS.items() if "py" in o["ports"]}
_BY_FLAG = {}
_BY_NEGATIVE = {}
for _name, _o in _PY.items():
    if _o["flag"]:
        _BY_FLAG[_o["flag"]] = _name
        for _alias in _o.get("aliases", ()):
            _BY_FLAG[_alias] = _name
        if _o.get("negatable"):
            _BY_NEGATIVE["--no-" + _o["flag"][2:]] = _name


class Options(Mapping):
    """A frozen mapping of option name to value, with each value's layer.

    `options["totals"]` is the value; `options.layer("totals")` says which
    layer gave it, and `options.given("transcript")` whether any layer
    above the defaults did.  A table's layer is the highest that set any
    of its fields, and `options.field_layer("rows", "turn", "live")` the
    one that set that field.  `options.warnings` are what the files'
    reading skipped, each "PATH: what", for --diagnose to count.
    """
    __slots__ = ("_values", "_layers", "_fields", "warnings")

    def __init__(self, values, layers, fields=None, warnings=()):
        object.__setattr__(self, "_values", dict(values))
        object.__setattr__(self, "_layers", dict(layers))
        object.__setattr__(self, "_fields", dict(fields or {}))
        object.__setattr__(self, "warnings", tuple(warnings))

    def __setattr__(self, name, value):
        raise AttributeError("Options is frozen")

    def __getitem__(self, name):
        return self._values[name]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def layer(self, name):
        return self._layers[name]

    def given(self, name):
        return self._layers[name] not in ("default", "derived")

    def field_layer(self, name, row, field):
        return self._fields.get((name, row, field), "default")

    def __repr__(self):
        return "Options(%r)" % self._values


def flag_values(parsed):
    """The flags' layer from `parsed`, a list of (spelling, value) pairs in
    command-line order, value True for a switch: option name to value.

    A repeated list flag makes one list.  A repeated value flag takes the
    last.  A negatable switch is False when its `--no-` spelling is given
    anywhere, whichever comes first, as --column-rules and --mark-spacing
    always had it.
    """
    values = {}
    negated = set()
    for spelling, value in parsed:
        if spelling in _BY_NEGATIVE:
            negated.add(_BY_NEGATIVE[spelling])
            continue
        name = _BY_FLAG[spelling]
        kind = _PY[name]["type"]
        if kind == "list":
            values[name] = values.get(name, ()) + (value,)
        elif kind == "int":
            values[name] = int(value)
        else:
            values[name] = value
    for name in negated:
        values[name] = False
    return values


def _derive_key(value):
    """An option's value as a `derived` map's key: JSON's spelling."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _table(name, default, files):
    """A table's value, merged field by field from the lowest layer up,
    with the layer of each field a file set."""
    rows = {row: dict(rec) for row, rec in default.items()}
    fields, layer = {}, "default"
    for f in reversed(files):
        if name not in f.values:
            continue
        layer = f.name
        for row, rec in f.values[name].items():
            for field, value in rec.items():
                rows[row][field] = value
                fields[(name, row, field)] = f.name
    value = MappingProxyType({row: MappingProxyType(rec)
                              for row, rec in rows.items()})
    return value, layer, fields


def merge(flags, files=(), ports=("py",), warnings=(), defaults=None):
    """Options from the flags' layer over the files' (config.Layer, highest
    first) and `defaults`, the defaults file's (config.load_defaults, which
    raises config.DefaultsError while that file is wrong, when None):
    every option the `ports` read, with its layer.  Lists replace and
    tables merge per field (Decided 3 and 10); a derived value is worked
    out after, from the merged one it follows."""
    if defaults is None:
        defaults = load_defaults()
    values, layers, fields = {}, {}, {}
    for name, option in OPTIONS.items():
        if not set(ports) & set(option["ports"]):
            continue
        if option["type"] == "table":
            values[name], layers[name], got = _table(name, defaults[name],
                                                     files)
            fields.update(got)
            continue
        if name in flags:
            values[name], layers[name] = flags[name], "flag"
            continue
        for f in files:
            if name in f.values:
                values[name], layers[name] = f.values[name], f.name
                break
        else:
            values[name], layers[name] = defaults[name], "default"
    for name, option in OPTIONS.items():
        derived = option.get("derived")
        if derived and layers.get(name) == "default":
            # The map names every value the option followed can take
            # (tools/gen-spec.py holds it to that).
            key = _derive_key(_merged_value(derived["from"], values, flags,
                                            files, defaults))
            values[name], layers[name] = derived["map"][key], "derived"
    return Options(values, layers, fields, warnings)


def _merged_value(name, values, flags, files, defaults):
    """The merged value of `name`, which a derived option follows: as the
    merge gave it, or for an option of the other port only, which these
    Options leave out (right-edge follows the mod's live-place, Decided
    13), from the highest layer that sets it."""
    if name in values:
        return values[name]
    if name in flags:
        return flags[name]
    for f in files:
        if name in f.values:
            return f.values[name]
    return defaults[name]


def from_flags(parsed, files=()):
    """Options from (spelling, value) pairs, the files' layers and the
    defaults."""
    return merge(flag_values(parsed), files)


def parse(argv, allowed=None):
    """A command line as (spelling, value) pairs, in order; value True for
    a switch.  `allowed` limits the spellings, every flag of this port's
    by default.  Raises ValueError on anything else."""
    parsed = []
    index = 0
    argv = list(argv)
    while index < len(argv):
        item = argv[index]
        if not item.startswith("-"):
            raise ValueError("unexpected argument %r" % item)
        name = _BY_FLAG.get(item) or _BY_NEGATIVE.get(item)
        if name is None or (allowed is not None and item not in allowed):
            raise ValueError("unknown option %s" % item)
        if item in _BY_FLAG and _PY[name]["type"] != "bool":
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                raise ValueError("%s requires a value" % item)
            parsed.append((item, argv[index + 1])); index += 2
        else:
            parsed.append((item, True)); index += 1
    return parsed


def from_argv(argv, files=()):
    """Options from a command line and the defaults, and any files' layers
    given: for callers that hold an argv, such as the tests."""
    return from_flags(parse(argv), files)
