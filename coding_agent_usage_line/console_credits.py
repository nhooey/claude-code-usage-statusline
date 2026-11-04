"""The Claude Console's credits, as a `credits.command` for the mod.

The Console reports an organization's promotional and prepaid credits
only to a signed-in browser, behind bot protection, so no program reads
them.  This prints the ones the user writes down from the Console's
billing page instead, in

  <the user configuration directory>/console-credits.json

as {"credits": [...]}, each entry as docs/usage-sources.md gives
credits[]: an id, a kind ("promo" or "prepaid"), what is left, and
optionally what was granted and when it expires.  The figure is as fresh
as the file; the expiry counts down by itself.

Prints {"schema_version": 1, "credits": [...]} and exits 0.  Prints
nothing and exits 1 when the file is missing or not JSON, so the mod
keeps the credits it had.  An entry the reading would drop is named on
stderr, which a run by hand shows.
"""
import json
import os
import sys

from .config import user_dir
from .sources import _credits

FILE = "console-credits.json"


def path_of(environ):
    return os.path.join(user_dir(environ), FILE)


def written(path):
    """The credits[] the file holds, or raise ValueError saying why not."""
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
    except OSError:
        raise ValueError("no %s" % path)
    except ValueError as error:
        raise ValueError("%s is not JSON: %s" % (path, error))
    entries = value.get("credits") if isinstance(value, dict) else value
    if not isinstance(entries, list):
        raise ValueError('%s holds no "credits" list' % path)
    return entries


def main(environ=None, out=None, err=None):
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    path = path_of(environ)
    try:
        entries = written(path)
    except ValueError as why:
        err.write("console-credits: %s\n" % why)
        return 1
    kept = {c["id"] for c in _credits(entries)}
    for index, entry in enumerate(entries):
        ident = entry.get("id") if isinstance(entry, dict) else None
        if ident not in kept:
            err.write("console-credits: credits[%d] dropped: it needs an id, a kind "
                      "of promo, prepaid, cloud, extra or passes, and a remaining "
                      "of no more than granted\n" % index)
    out.write(json.dumps({"schema_version": 1, "credits": entries},
                         separators=(",", ":")) + "\n")
    return 0
