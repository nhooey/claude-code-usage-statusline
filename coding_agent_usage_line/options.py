"""The merged options: every option of spec/options.jsonc this port reads,
its value, and the layer it came from.

The adapters read options from here, never from argv: a flag, a config file
and a default then reach them as one answer per option, whichever spelling
or layer gave it.  Imports nothing of the package but the spec.
"""
import os
from collections.abc import Mapping

from .options_spec import OPTIONS

# The layers, highest first.  `env` is CODING_AGENT_USAGE_LINE_USAGE_SOURCE,
# the one setting still read from the environment.
LAYERS = ("flag", "env", "default")

_USAGE_SOURCE_ENV = "CODING_AGENT_USAGE_LINE_USAGE_SOURCE"

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
    above the defaults did.
    """
    __slots__ = ("_values", "_layers")

    def __init__(self, values, layers):
        object.__setattr__(self, "_values", dict(values))
        object.__setattr__(self, "_layers", dict(layers))

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
        return self._layers[name] != "default"

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


def merge(flags, environ=None):
    """Options from the flags' layer over the environment's and the
    defaults: every option this port reads, with its layer."""
    environ = os.environ if environ is None else environ
    values, layers = {}, {}
    for name, option in _PY.items():
        if name in flags:
            values[name], layers[name] = flags[name], "flag"
        elif name == "usage-source" and environ.get(_USAGE_SOURCE_ENV):
            values[name], layers[name] = environ[_USAGE_SOURCE_ENV], "env"
        else:
            values[name], layers[name] = option["default"], "default"
    return Options(values, layers)


def from_flags(parsed, environ=None):
    """Options from (spelling, value) pairs and the defaults alone."""
    return merge(flag_values(parsed), environ)


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


def from_argv(argv, environ=None):
    """Options from a command line and the defaults: for callers that hold
    an argv, such as the tests."""
    return from_flags(parse(argv), environ)
