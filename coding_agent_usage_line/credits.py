"""The account's credits against the `credits` option's conditions.

A condition is one map of `field`, `op`, `value` and `unit`
(agents/plans/credit-balances.md, "The configuration"):

    {"field": "balance", "op": "<=", "value": 20, "unit": "usd"}

`balance` is what is left, in `usd` or as a `percent` of what was granted;
`spent` is what the credit has paid for, in `usd`; `expiry` is the time to
its expiry, in `days`, `hours` or `minutes`.  A condition whose figure the
credit doesn't have, or that is malformed, doesn't hold.  mod/src/credits.ts
is its twin, held to it by tests/fixtures/sources/conditions.json.
"""
import math

OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
       "=": lambda a, b: a == b, "!=": lambda a, b: a != b,
       ">=": lambda a, b: a >= b, ">": lambda a, b: a > b}
UNITS = {"balance": ("usd", "percent"), "spent": ("usd",),
         "expiry": ("days", "hours", "minutes")}
SECONDS = {"days": 86400, "hours": 3600, "minutes": 60}


def _figure(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)): return None
    value = float(value)
    return value if math.isfinite(value) else None


def expired(credit, now):
    """Whether `credit`'s expiry has passed: it is never drawn then."""
    at = _figure(credit.get("expires_at")) if isinstance(credit, dict) else None
    return at is not None and at <= now


def _measure(credit, field, unit, now):
    if field == "balance" and unit == "usd": return _figure(credit.get("remaining"))
    if field == "balance":
        left, granted = _figure(credit.get("remaining")), _figure(credit.get("granted"))
        return None if left is None or not granted else left / granted * 100
    if field == "spent": return _figure(credit.get("spent"))
    at = _figure(credit.get("expires_at"))
    return None if at is None else (at - now) / SECONDS[unit]


def met(credit, condition, now):
    """Whether one condition holds of `credit` at `now`."""
    if not isinstance(credit, dict) or not isinstance(condition, dict): return False
    field, op, unit = condition.get("field"), condition.get("op"), condition.get("unit")
    value = _figure(condition.get("value"))
    if (not isinstance(field, str) or field not in UNITS or unit not in UNITS[field]
            or not isinstance(op, str) or op not in OPS or value is None): return False
    figure = _measure(credit, field, unit, now)
    return figure is not None and OPS[op](figure, value)


def shown(credit, conditions, now):
    """Whether `credit` is drawn: any one condition holds, and it hasn't
    expired.  An empty list never draws it."""
    if expired(credit, now) or not isinstance(conditions, list): return False
    return any(met(credit, c, now) for c in conditions)


def colour(credit, amber, red, now):
    """"red", "amber" or None: red wins."""
    for name, conditions in (("red", red), ("amber", amber)):
        if isinstance(conditions, list) and any(met(credit, c, now) for c in conditions):
            return name
    return None
