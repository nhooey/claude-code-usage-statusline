#!/usr/bin/env python3
"""Write tests/fixtures/sources/: the usage-source reader's shared cases.

    /usr/bin/python3 tests/fixtures/gen/sources.py

Each file is a list of inputs and the reading Python makes of them, and
mod/test/sources.test.ts runs every one through the TypeScript port in
mod/src/sources.ts and claude_sources.ts and compares.  Run it under
/usr/bin/python3: the status line runs there, and 3.9's fromisoformat is
narrower than a newer Python's, so the expected epochs are 3.9's.

What the files hold:

  values.json     epoch, _number, period_bounds and cache_name over awkward
                  values: the parsing every reading leans on.
  normalise.json  version-1 readings in, normalise, has_reading and
                  _cached_reading out.
  native.json     a payload's rate_limits in, native_reading out.
  tracker.json    tracker stores as plist text in, tracker_reading and
                  claude_usage_tracker out.  A store tracker_reading
                  raises on is marked so; claude_usage_tracker returns no
                  reading there, in both languages.
  command.json    scripts in, command_reading and the stdin it sent out.
  limits.json     readings and a time zone in, legacy_limits out.
  collect.json    scenarios: steps sharing one state directory, each a
                  spec, payload and clock in, and the prepared reading, its
                  limits, its calibration scope and every cache file
                  afterwards out.

Paths under the scratch directory are written as ${DIR}, which the test
puts back as its own.
"""
import base64
import json
import os
import plistlib
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(FIXTURES))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from coding_agent_usage_line import (  # noqa: E402
    claude, claude_sources, sources, state)
from cases import ENVS, PIN_NOW  # noqa: E402

OUT = os.path.join(FIXTURES, "sources")
APPLE = 978307200
TRACKER_ENV = "CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST"
CONFIG_ENV = "CLAUDE_CONFIG_DIR"
STATE_ENV = "CODING_AGENT_USAGE_LINE_STATE_DIR"

# run-cases.py's tracker store: profiles_v3 as a <string>, as the goldens
# plant it.  The app itself writes <data>; plist_store() below does that.
TRACKER = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>activeProfileId</key><string>golden</string>
<key>profiles_v3</key><string>%s</string>
</dict></plist>
"""


def golden_store(usage, ident="golden"):
    """A store of one profile; ident None leaves its `id` out."""
    profile = ({"claudeUsage": usage} if ident is None
               else {"id": ident, "claudeUsage": usage})
    profiles = json.dumps([profile], separators=(",", ":"))
    text = TRACKER % profiles.replace("&", "&amp;").replace("<", "&lt;")
    return text.replace(">golden<", ">%s<" % ident) if ident else text


def plist_store(usage, active="P1", selected=False, extra=None):
    """The app's own shape: profiles_v3 as <data>, beside a credential."""
    profiles = [{"id": "P0", "claudeUsage": {"sessionPercentage": 1,
                                             "weeklyPercentage": 1},
                 "isSelectedForDisplay": selected},
                {"id": "P1", "claudeUsage": usage,
                 "oauthAccountJSON": "oauth-canary-must-never-be-copied"}]
    value = {"profiles_v3": json.dumps(profiles).encode()}
    if active is not None:
        value["activeProfileId"] = active
    value.update(extra or {})
    return plistlib.dumps(value).decode()


def set_tz(name):
    os.environ["TZ"] = name
    time.tzset()


def write(name, data):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def scrub(value, directory):
    """The scratch directory as ${DIR}, wherever it appears."""
    text = json.dumps(value, sort_keys=True)
    return json.loads(text.replace(directory, "${DIR}"))


# ════════════════════════════════════════════════════════════════════════════

EPOCHS = [
    1786847000, 1786847000.5, 0, -1, 4102444800, 4102444801, True, None,
    float("nan"), float("inf"), [1], {"a": 1},
    "2026-08-16T04:00:00Z", "2026-08-16", "2026-08-16T04", "2026-08-16T04:00",
    "2026-08-16 04:00:00.123+05:30", "2026-08-16T04:00:00.123456-07:00",
    "2026-08-16T04:00:00:123", "2026-08-16T", "2026-08-16T04:00+24:00",
    "2026-08-16T04:00+23:59", "2026-08-16T04:00:00.5Z", "2026-08-16T24:00:00",
    "2026-02-29", "2028-02-29T00:00:00Z", "2026-13-01", "0000-01-01",
    "1969-12-31T23:59:59Z", "2100-01-01T00:00:00Z", "2100-01-01T00:00:01Z",
    "2026-08-16T04:00:00+05:30:15", "2026-08-16T04:00:00+05:30:15.000001",
    "2026-08-16T04:00:00+0530", "2026-08-16X04:00", "2026-08-16\u00e904:00",
    "2026-08-16\U0001F600" "04:00", "2026/08/16", "20260816", "1786847000",
    " 2026-08-16", "2026-08-16T04:00:00ZZ", "2026-08-16T4:00", "",
    "2026-08-16T04:00:", "2026-08-16T04:00:00.", "2026-08-16T04:00:00.1234",
]

NUMBERS = [
    42, 42.5, -1, 0, -0.5, 100, 100.5, True, False, None, "42", " 42 ",
    "1_000", "_1", "1__0", "1e2", "1E-2", ".5", "5.", "inf", "-inf", "nan",
    "Infinity", "0x10", "", " ", "\t7\n", "\u00a07", "\u20077", "1,5", [1],
    {"a": 1}, float("nan"), float("inf"), 1e308, "1e400",
]


def values():
    period = []
    for kind in ("day", "week", "month"):
        for now in (PIN_NOW, PIN_NOW + 0.25, 1786847999.9999996, 1785542400,
                    1785542399.5):
            period.append({"kind": kind, "now": now,
                           "expected": list(sources.period_bounds(kind, now))})
    names = [["claude", "native", "session:s", "1786838400"],
             ["claude", "claude-usage-tracker", "default", "1786320000"],
             ["claude", "cmd:/x/y", "acct\u00e9", "0"]]
    return {
        "epoch": [{"input": v, "expected": sources.epoch(v)} for v in EPOCHS],
        "number": [{"input": v, "upper": upper,
                    "expected": sources._number(v, upper)}
                   for v in NUMBERS for upper in (None, 100)],
        "period_bounds": period,
        "cache_name": [{"input": n, "expected": state.cache_name(*n)}
                       for n in names],
    }


# ════════════════════════════════════════════════════════════════════════════

DOCS_READING = {
    "schema_version": 1, "as_of": "2026-09-26T08:00:00Z",
    "buckets": [
        {"id": "general", "label": "General", "windows": [
            {"id": "weekly", "duration_seconds": 604800, "used_percent": 97,
             "resets_at": "2026-10-01T17:17:00Z"}]},
        {"id": "spark", "label": "Spark", "windows": [
            {"id": "five-hour", "duration_seconds": 18000,
             "used_percent": 100, "resets_at": "2026-09-26T20:15:00Z"},
            {"id": "weekly", "duration_seconds": 604800,
             "used_percent": 100, "resets_at": "2026-10-01T15:15:00Z"}]}]}

NORMALISE = [
    ("docs example", DOCS_READING),
    ("golden env reading", ENVS["app-41-63"]["source"]),
    ("flat windows, strings", {"schema_version": 1, "as_of": PIN_NOW,
                               "windows": [{"id": "x", "used_percent": "42",
                                            "resets_at": PIN_NOW - 1}]}),
    ("schema 1.0", {"schema_version": 1.0, "windows": [
        {"id": "x", "used_percent": 1}]}),
    ("schema true", {"schema_version": True, "windows": [
        {"id": "x", "used_percent": 1}]}),
    ("schema string", {"schema_version": "1", "windows": []}),
    ("not a dict", [1, 2]),
    ("empty", {}),
    ("buckets not a list", {"schema_version": 1, "buckets": {"a": 1}}),
    ("windows not a list", {"schema_version": 1, "windows": "x"}),
    ("windows null", {"schema_version": 1, "windows": None}),
    ("buckets beat windows", {"schema_version": 1,
                              "buckets": [{"id": "b", "windows": [
                                  {"id": "w", "used_percent": 5}]}],
                              "windows": [{"id": "flat", "used_percent": 6}]}),
    ("malformed numbers", {"schema_version": 1, "as_of": "yesterday",
                           "windows": [
        {"id": "a", "used_percent": 101, "duration_seconds": -5},
        {"id": "b", "used_percent": float("nan"),
         "duration_seconds": float("inf")},
        {"id": "c", "used_percent": True, "resets_at": True},
        {"id": "d", "used_percent": None, "resets_at": "2026-08-16"},
        {"id": "e", "used_percent": "1_0", "duration_seconds": " 60 "},
        {"used_percent": 50}, {"id": "", "used_percent": 50},
        {"id": 5, "used_percent": 50}, "not a window"]}),
    ("labels and control characters", {"schema_version": 1, "buckets": [
        {"id": "ok", "label": "Line\nbreak", "model": "m", "feature": "f",
         "windows": [{"id": "w", "used_percent": 1}]},
        {"id": "c1\u0085", "windows": [{"id": "w", "used_percent": 2}]},
        {"id": "x" * 128, "label": "L" * 129, "windows": [
            {"id": "y" * 129, "used_percent": 3},
            {"id": "z", "used_percent": 4, "heading": "own heading",
             "model": None}]},
        {"id": "\U0001F600" * 128, "windows": [
            {"id": "e", "used_percent": 5}]},
        {"id": "no windows"}, {"id": "bad windows", "windows": "x"}, 7]}),
    ("bucket order is first seen", {"schema_version": 1, "buckets": [
        {"id": "b", "windows": [{"id": "1", "used_percent": 1}]},
        {"id": "1", "windows": [{"id": "2", "used_percent": 2}]},
        {"id": "a", "windows": [{"id": "3", "used_percent": 3}]},
        {"id": "b", "label": "Late", "model": "m2",
         "windows": [{"id": "4", "used_percent": 4}]}]}),
    ("account totals", {"schema_version": 1, "windows": [], "account": {
        "period_start": "2026-08-16T00:00:00Z", "period_end": PIN_NOW,
        "input_tokens": 100, "cached_input_tokens": 40,
        "output_tokens": "9", "reasoning_output_tokens": 3,
        "cost_usd": 1.25, "scope": "organization", "secret": "x"}}),
    ("account subset larger", {"schema_version": 1, "account": {
        "input_tokens": 10, "cached_input_tokens": 40, "cost_usd": 2}}),
    ("account reasoning larger", {"schema_version": 1, "account": {
        "output_tokens": 1, "reasoning_output_tokens": 2}}),
    ("account period backwards", {"schema_version": 1, "account": {
        "period_start": PIN_NOW, "period_end": PIN_NOW - 1}}),
    ("account scope too long", {"schema_version": 1, "account": {
        "scope": "s" * 65, "cost_usd": -1}}),
    ("envelope only", {"schema_version": 1, "windows": [{"id": "x"}],
                       "account": {"scope": "organization"}}),
    ("expired and live", {"schema_version": 1, "as_of": PIN_NOW - 30,
                          "windows": [
        {"id": "old", "duration_seconds": 18000, "used_percent": 10,
         "resets_at": PIN_NOW},
        {"id": "new", "duration_seconds": 604800, "used_percent": 20,
         "resets_at": PIN_NOW + 1}],
        "fetched_at": PIN_NOW - 10, "attempted_at": "5", "retry_at": None,
        "fail_count": 2}),
    ("canonical again", {"schema_version": 1, "source": "x", "as_of": 5,
                         "buckets": [{"id": "default", "label": "default",
                                      "windows": [
        {"id": "five_hour", "duration_seconds": 18000.0,
         "used_percent": 41.0, "resets_at": PIN_NOW + 100}]}],
        "account": {}}),
]


def normalise_cases():
    out = []
    for name, value in NORMALISE:
        clean = sources.normalise(value, "cmd")
        cached = {}
        for ttl in (60, 300):
            cached[str(ttl)] = sources._cached_reading(value, "cmd",
                                                       PIN_NOW, ttl)
        out.append({"name": name, "input": value, "expected": clean,
                    "has_reading": sources.has_reading(clean),
                    "cached": cached, "now": PIN_NOW})
    return out


# ════════════════════════════════════════════════════════════════════════════

CLAUDE_LIMITS = {
    "five_hour": {"used_percentage": 15, "resets_at": PIN_NOW + 400},
    "seven_day": {"used_percentage": 87.5, "resets_at": PIN_NOW + 160000}}

NATIVE = [
    ("claude payload", CLAUDE_LIMITS),
    ("claude, iso resets", {
        "five_hour": {"used_percentage": 15,
                      "resets_at": "2026-08-16T04:00:00Z"},
        "seven_day": {"used_percent": 3, "reset_at": "2026-08-18T01:00:00Z"}}),
    ("used_percentage null beats used_percent", {
        "five_hour": {"used_percentage": None, "used_percent": 5}}),
    ("window minutes", {
        "primary": {"used_percent": 4, "window_minutes": 300},
        "secondary": {"used_percent": 6, "window_minutes": 10080,
                      "limit_window_seconds": 99}}),
    ("explicit null duration", {
        "five_hour": {"used_percentage": 1, "duration_seconds": None}}),
    ("limit ids", {"limit_id": 7, "five_hour": {
        "used_percentage": 1, "bucket_id": "", "heading": "H"},
        "seven_day": {"used_percentage": 2, "limit_id": "L"}}),
    ("limitId fallback", {"limitId": "codex", "five_hour": {
        "used_percentage": 1}}),
    ("list in resets_at", {"five_hour": {"used_percentage": 1,
                                         "resets_at": [1, 2]}}),
    ("duplicates", {"five_hour": {"used_percentage": 1, "resets_at": 5},
                    "primary": {"used_percent": 2, "duration_seconds": 18000,
                                "resets_at": 5}}),
    ("codex snapshot", {"rateLimits": {
        "limitId": "codex", "limitName": "General",
        "primary": {"usedPercent": 12, "windowDurationMins": 300,
                    "resetsAt": PIN_NOW + 100},
        "secondary": {"usedPercent": 40, "windowDurationMins": 0,
                      "resetsAt": PIN_NOW + 9000}}}),
    ("codex keyed map", {
        "rateLimitsByLimitId": {
            "codex": {"limitName": "General", "primary": {
                "usedPercent": 1, "windowDurationMins": 300}},
            "spark": {"limitId": "spark", "normalModelSlug": "gpt-spark",
                      "feature": "spark", "secondary": {
                          "usedPercent": 99, "windowDurationMins": 10080}}},
        "rateLimits": {"limitId": "codex", "primary": {
            "usedPercent": 1, "windowDurationMins": 300}}}),
    ("rate_limits key nested", {"rate_limits": CLAUDE_LIMITS}),
    ("rate_limits null", {"rate_limits": None}),
    ("not a dict", [1]),
    ("empty", {}),
]


def native_cases():
    out = []
    for name, raw in NATIVE:
        for key in ("rate_limits", "rateLimits", "quota"):
            for as_of in (PIN_NOW, None):
                context = {key: raw, "as_of": as_of}
                out.append({"name": "%s (%s, as_of %s)" % (name, key, as_of),
                            "context": context,
                            "expected": sources.native_reading("claude",
                                                               context)})
    # An empty rate_limits falls through to the next key, as `or` does.
    for context in ({"rate_limits": {}, "quota": CLAUDE_LIMITS},
                    {"rate_limits": [], "rateLimits": CLAUDE_LIMITS},
                    {"rate_limits": 0}, {}, None):
        out.append({"name": "fallthrough %r" % (context,),
                    "context": context,
                    "expected": sources.native_reading("claude", context)})
    return out


# ════════════════════════════════════════════════════════════════════════════

TRACKER_USAGE = ENVS["default"]["tracker"]
APP_USAGE = {"sessionPercentage": 98,
             "sessionResetTime": 1788864600.363 - APPLE,
             "weeklyPercentage": 10, "opusWeeklyPercentage": 3,
             "weeklyResetTime": 1789434000.363 - APPLE,
             "lastUpdated": PIN_NOW - 60 - APPLE}


def tracker_inputs():
    golden = golden_store(TRACKER_USAGE)
    yield "golden store", golden, "UTC"
    yield "app store", plist_store(APP_USAGE), "UTC"
    yield "active P0", plist_store(APP_USAGE, active="P0"), "UTC"
    yield "selected fallback", plist_store(APP_USAGE, active="gone",
                                           selected=True), "UTC"
    yield "first fallback", plist_store(APP_USAGE, active="gone"), "UTC"
    yield "no active id", plist_store(APP_USAGE, active=None), "UTC"
    yield "weekly only", golden_store({"weeklyPercentage": 63,
                                       "weeklyResetTime": 808707800}), "UTC"
    yield "stamps and strings", golden_store({
        "sessionPercentage": "41.5", "sessionResetTime": " 808545600 ",
        "weeklyPercentage": 63, "weeklyResetTime": "2026-08-18 01:00",
        "lastUpdated": "2026-08-16  2:20"}), "America/New_York"
    yield "bad stamps", golden_store({
        "sessionPercentage": 1, "sessionResetTime": "2026-02-30 01:00",
        "weeklyPercentage": 2, "weeklyResetTime": True,
        "lastUpdated": "nan"}), "UTC"
    yield "reset passed", golden_store({
        "sessionPercentage": 41, "sessionResetTime": PIN_NOW - 5 - APPLE,
        "weeklyPercentage": 63, "weeklyResetTime": 808707800,
        "lastUpdated": 808539600}), "UTC"
    yield "malformed profiles json", TRACKER % "[{", "UTC"
    yield "profiles not a list", TRACKER % "{}", "UTC"
    yield "profiles empty", TRACKER % "[]", "UTC"
    yield "usage missing", TRACKER % '[{"id":"golden"}]', "UTC"
    yield "first profile empty", TRACKER % "[{}, 5]", "UTC"
    yield "pre-migration store", plistlib.dumps(
        {"usageHistory_ABC": "{}"}).decode(), "UTC"
    yield "data with a BOM", plistlib.dumps({"profiles_v3": b"\xef\xbb\xbf" +
        json.dumps([{"claudeUsage": APP_USAGE}]).encode()}).decode(), "UTC"
    yield "data, invalid utf-8", plistlib.dumps({"profiles_v3": b"\xff[" +
        json.dumps([{"claudeUsage": APP_USAGE}]).encode()}).decode(), "UTC"
    wrapped = base64.b64encode(json.dumps(
        [{"id": "P1", "claudeUsage": APP_USAGE}]).encode()).decode()
    yield "data, ragged base64", (
        '<?xml version="1.0"?><plist version="1.0"><dict>'
        "<key>profiles_v3</key><data>\n\t%s\n\t%s !\n</data>"
        "</dict></plist>" % (wrapped[:30], wrapped[30:])), "UTC"
    yield "data, bad padding", (
        '<plist><dict><key>profiles_v3</key><data>%s</data></dict></plist>'
        % wrapped[:-2].rstrip("=")[:-1]), "UTC"
    yield "types", (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!-- a comment -->\n'
        '<plist version="1.0"><dict>\n'
        "<key>n</key><integer>0x1F</integer><key>m</key><integer>-1_0"
        "</integer><key>r</key><real>2.5e1</real><key>t</key><true/>"
        "<key>f</key><false/><key>d</key><date>2026-08-16T02:23:20Z</date>"
        "<key>a</key><array><string>x &amp; &#x3c;y&#62;</string>"
        "<string><![CDATA[<z>]]></string></array>"
        "<key>activeProfileId</key><string>golden</string>"
        "<key>profiles_v3</key><string>%s</string>"
        "</dict></plist>\r\n" % json.dumps(
            [{"id": "golden", "claudeUsage": TRACKER_USAGE}])
        .replace("&", "&amp;").replace("<", "&lt;")), "UTC"
    yield "not a plist", "hello", "UTC"
    yield "binary plist refused", "bplist00", "UTC"
    yield "entity declaration", (
        '<?xml version="1.0"?><!DOCTYPE plist [<!ENTITY e "x">]>'
        "<plist><dict><key>a</key><string>&e;</string></dict></plist>"), "UTC"
    yield "missing value", (
        "<plist><dict><key>a</key></dict></plist>"), "UTC"
    yield "mismatched tags", "<plist><dict></plist>", "UTC"
    yield "undefined entity", (
        "<plist><dict><key>a</key><string>&nope;</string></dict></plist>"),\
        "UTC"
    yield "root array", "<plist><array/></plist>", "UTC"
    yield "empty plist", "<plist></plist>", "UTC"
    yield "bad integer", (
        "<plist><dict><key>a</key><integer> 0x1F </integer></dict></plist>"),\
        "UTC"


def tracker_cases(scratch):
    out = []
    path = os.path.join(scratch, "tracker.plist")
    os.environ[TRACKER_ENV] = path
    for name, text, tz in tracker_inputs():
        set_tz(tz)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        case = {"name": name, "plist": text, "tz": tz}
        try:
            with open(path, "rb") as fh:
                case["tracker_reading"] = claude.tracker_reading(
                    plistlib.load(fh))
        except Exception as exc:  # noqa: BLE001 -- recorded, not hidden
            case["tracker_reading"] = {"raises": type(exc).__name__}
        try:
            case["expected"] = sources.claude_usage_tracker()
        except Exception as exc:  # noqa: BLE001
            case["expected"] = {"raises": type(exc).__name__}
        out.append(case)
    set_tz("UTC")
    return out


# ════════════════════════════════════════════════════════════════════════════

def printf(value):
    """A shell script printing one JSON value."""
    text = value if isinstance(value, str) else json.dumps(value)
    return "#!/bin/sh\ncat > \"$0.stdin\"\nprintf '%%s\\n' '%s'\n" % (
        text.replace("'", "'\\''"))


SCOPE = {"agent": "claude", "session": "s1", "model": "claude-opus-5-5",
         "account": "default", "period": "day",
         "period_start": 1786838400.0, "period_end": float(PIN_NOW)}

COMMANDS = [
    ("v1 reading", printf(ENVS["app-41-63"]["source"]), True, SCOPE),
    ("docs reading", printf(DOCS_READING), True, SCOPE),
    ("flat adapter, bash fallback", printf(
        {"session_pct": 7, "weekly_pct": 8,
         "session_resets_at": PIN_NOW + 7200}), False,
     {"agent": "claude", "session": "s", "account": "a", "period": "day"}),
    ("flat with a schema is not flat", printf(
        {"schema_version": 2, "session_pct": 7}), True, {}),
    ("nan and infinity", printf(
        '{"schema_version":1,"windows":[{"id":"x","used_percent":NaN,'
        '"duration_seconds":Infinity},{"id":"y","used_percent":-Infinity},'
        '{"id":"z","used_percent":5}]}'), True, {}),
    ("canary dropped", printf(
        {"schema_version": 1, "as_of": 1, "windows": [
            {"id": "x", "used_percent": 9}],
         "account": {"access_token": "canary", "cost_usd": 1}}), True, {}),
    ("context whitelist", printf({"schema_version": 1, "windows": []}), True,
     {"agent": "claude", "session": "s\u00e9\U0001F600", "model": "m\n",
      "account": "a" * 257, "period": 5, "secret": "x",
      "period_start": "2026-08-16T00:00:00Z", "period_end": -1,
      "rate_limits": CLAUDE_LIMITS}),
    ("context, fractional bounds", printf({"schema_version": 1}), True,
     {"period_start": 0.00001, "period_end": 1786847000.25}),
    ("nonzero exit", "#!/bin/sh\ncat > \"$0.stdin\"\n"
     "printf '{\"schema_version\":1,\"windows\":[{\"id\":\"x\","
     "\"used_percent\":1}]}'\nexit 3\n", True, {}),
    ("not json", "#!/bin/sh\ncat > \"$0.stdin\"\necho nope\n", True, {}),
    ("two values", "#!/bin/sh\ncat > \"$0.stdin\"\necho '{} {}'\n", True, {}),
    ("trailing whitespace", printf('  {"schema_version":1,"windows":'
                                   '[{"id":"x","used_percent":1}]}\t'),
     True, {}),
    ("bom", "#!/bin/sh\ncat > \"$0.stdin\"\nprintf '\\357\\273\\277{}'\n",
     True, {}),
    ("invalid utf-8", "#!/bin/sh\ncat > \"$0.stdin\"\n"
     "printf '{\"schema_version\":1,\"windows\":[{\"id\":\"\\377\"}]}'\n",
     True, {}),
    ("escapes", printf(
        '{"schema_version":1,"windows":[{"id":"\\u00e9\\ud83d\\ude00",'
        '"used_percent":1,"resets_at":"2026-08-16T04:00:00\\u005a"}]}'),
     True, {}),
    ("not a dict", printf([1, 2]), True, {}),
    ("too large", "#!/bin/sh\ncat > \"$0.stdin\"\n"
     "head -c 1100000 /dev/zero | tr '\\0' ' '\n", True, {}),
    ("ignores stdin", "#!/bin/sh\nprintf '{\"schema_version\":1,"
     "\"windows\":[{\"id\":\"x\",\"used_percent\":2}]}'\n", True, {}),
    # Records no stdin: under load the shell may not reach `cat` inside the
    # half second, which made what it recorded depend on the machine.
    ("timeout", "#!/bin/sh\nsleep 3\n"
     "printf '{\"schema_version\":1}'\n", True, {}),
]


def command_cases(scratch):
    out = []
    for index, (name, script, executable, context) in enumerate(COMMANDS):
        path = os.path.join(scratch, "cmd-%02d" % index)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        os.chmod(path, 0o700 if executable else 0o600)
        timeout = 0.5 if name == "timeout" else 5
        got = sources.command_reading(path, context, timeout=timeout)
        try:
            with open(path + ".stdin", encoding="utf-8") as fh:
                stdin = fh.read()
        except OSError:
            stdin = None
        out.append({"name": name, "script": script, "executable": executable,
                    "context": context, "timeout": timeout,
                    "expected": got, "stdin": stdin})
    out.append({"name": "missing", "script": None, "executable": False,
                "context": {}, "timeout": 5, "stdin": None,
                "expected": sources.command_reading(
                    os.path.join(scratch, "absent"), {})})
    return out


# ════════════════════════════════════════════════════════════════════════════

def window(ident, duration, pct, reset, **extra):
    w = {"id": ident, "duration_seconds": duration, "used_percent": pct,
         "resets_at": reset}
    w.update(extra)
    return w


def default_bucket(*windows, **extra):
    bucket = {"id": "default", "label": "default", "windows": list(windows)}
    bucket.update(extra)
    return {"schema_version": 1, "buckets": [bucket]}


LIMITS = [
    ("both", default_bucket(window("five_hour", 18000.0, 41.0, PIN_NOW + 400),
                            window("seven_day", 604800.0, 63.0,
                                   PIN_NOW + 160000))),
    ("fractions", default_bucket(
        window("a", 18000, 33.3333333, 1786848000.5),
        window("b", 604800, 99.6, 1786847999.9999996))),
    ("ties to even", default_bucket(window("a", 18000, 0.0078125, None),
                                    window("b", 604800, 0.0234375, None))),
    ("tiny and whole", default_bucket(window("a", 18000, 0.0000004, 0),
                                      window("b", 604800, 100, 4102444800))),
    ("first of each", default_bucket(
        window("a", 18000, 1, None), window("b", 18000, 2, None),
        window("c", 604800, 3, None), window("d", 604800, 4, None))),
    ("missing and expired skipped", default_bucket(
        window("a", 18000, None, 5), window("b", 18000, 7, 5, expired=True),
        window("c", 18000, 8, 6), window("d", 604800, 9, None))),
    ("weekly only", default_bucket(window("w", 604800, 63, PIN_NOW))),
    ("other durations", default_bucket(window("a", 3600, 1, None))),
    ("labelled bucket", default_bucket(window("a", 18000, 1, None),
                                       label="General")),
    ("empty label", default_bucket(window("a", 18000, 1, None), label="")),
    ("null label", default_bucket(window("a", 18000, 1, None), label=None)),
    ("model bucket", default_bucket(window("a", 18000, 1, None), model="m")),
    ("empty model", default_bucket(window("a", 18000, 1, None), model="")),
    ("other id", {"schema_version": 1, "buckets": [
        {"id": "general", "windows": [window("a", 18000, 1, None)]}]}),
    ("two buckets", {"schema_version": 1, "buckets": [
        {"id": "default", "windows": [window("a", 18000, 1, None)]},
        {"id": "b", "windows": [window("a", 18000, 1, None)]}]}),
    ("no buckets", {"schema_version": 1, "buckets": []}),
    ("empty", {}),
    ("not a dict", [1]),
]


def limits_cases():
    out = []
    for tz in ("UTC", "America/New_York", "Asia/Kolkata"):
        set_tz(tz)
        for name, reading in LIMITS:
            out.append({"name": name, "tz": tz, "reading": reading,
                        "expected": claude_sources.legacy_limits(
                            reading)._asdict()})
    set_tz("UTC")
    return out


# ════════════════════════════════════════════════════════════════════════════

def status_context(spec, session, model, as_of, payload):
    """main_status's source context, which is inline there.

    Copied so the scenarios hand the collector what a render would: the
    payload's own rate_limits only for the sources allowed to read them.
    claude_sources.ts has it as statusSourceContext.
    """
    context = {"session": session, "model": model, "as_of": as_of}
    if spec in ("", "auto", "native", "none", "off"):
        native = payload.get("rate_limits") if isinstance(payload,
                                                          dict) else None
        if isinstance(native, dict):
            context["rate_limits"] = native
    return context


GOLDEN = golden_store(TRACKER_USAGE)
STALE_TRACKER = golden_store(dict(TRACKER_USAGE,
                                  lastUpdated=TRACKER_USAGE["lastUpdated"]
                                  - 3600))
PAYLOAD = {"session_id": "s1", "rate_limits": CLAUDE_LIMITS}
EMPTY_LIMITS = {"session_id": "s1", "rate_limits": {
    "five_hour": {"used_percentage": None}}}
CMD_OK = printf(ENVS["plan-cache"]["source"])
CMD_FLAT = printf({"session_pct": 7, "weekly_pct": 8,
                   "session_resets_at": PIN_NOW + 7200,
                   "weekly_resets_at": "2026-08-18T01:00:00Z"})
CMD_FAIL = "#!/bin/sh\nexit 1\n"


def step(now, spec="auto", payload=None, context=None, tracker=GOLDEN,
         commands=None, account="default", period="day", session="s1",
         claude_json=None):
    """claude_json is Claude Code's global config, written to
    $CLAUDE_CONFIG_DIR/.claude.json; None leaves none there."""
    return {"now": now, "spec": spec, "payload": payload, "context": context,
            "tracker": tracker, "commands": commands or {},
            "account": account, "period": period, "session": session,
            "claude_json": claude_json}


def claude_json(uuid):
    """A config with its signed-in account, beside the fields that must
    not be read."""
    return json.dumps({"numStartups": 3, "oauthAccount": {
        "accountUuid": uuid, "emailAddress": "canary@example.invalid",
        "organizationUuid": "org-canary"}})


N = PIN_NOW
SCENARIOS = [
    ("auto: payload, then its cache, then the tracker", [
        step(N, payload=PAYLOAD),
        step(N + 30),
        step(N + 59),
        step(N + 120),
        step(N + 150),
        step(N + 200, tracker=None),
        step(N + 201, tracker=None),
        step(N + 300, tracker=None),
        step(N + 600),
    ]),
    ("auto: no payload, the tracker straight away", [
        step(N, payload={"session_id": "s1"}),
        step(N + 10, tracker=STALE_TRACKER),
        step(N + 70, tracker=STALE_TRACKER),
    ]),
    ("auto: a payload with no figures is no reading", [
        step(N, payload=EMPTY_LIMITS),
    ]),
    ("auto: a stale native reading, then nothing better", [
        step(N, context={"session": "s1", "rate_limits": CLAUDE_LIMITS},
             tracker=None),
        step(N + 1, context={"session": "s1", "rate_limits": CLAUDE_LIMITS}),
    ]),
    ("tracker: explicit, the payload ignored", [
        step(N, spec="claude-usage-tracker", payload=PAYLOAD),
        step(N + 61, spec="claude-usage-tracker", payload=PAYLOAD,
             tracker=None),
        step(N + 62, spec="none"),
        step(N + 63, spec="off", payload=PAYLOAD),
    ]),
    # The live panel and mod: a fetch, then the cache it left, then a
    # fetch again.  Each names one calibration cache, by one scope.
    ("tracker: fresh, then cached, one scope", [
        step(N, spec="claude-usage-tracker"),
        step(N + 30, spec="claude-usage-tracker"),
        step(N + 61, spec="claude-usage-tracker"),
    ]),
    # The calibration cache is the account's, not the session's: two
    # sessions on one tracker profile read through two reading caches and
    # name one calibration file, and another profile names another.
    ("tracker: two sessions, one profile, one scope", [
        step(N, spec="claude-usage-tracker", session="s1"),
        step(N + 1, spec="claude-usage-tracker", session="s2"),
        step(N + 2, spec="claude-usage-tracker", session="s2"),
    ]),
    ("tracker: another profile, another scope", [
        step(N, spec="claude-usage-tracker"),
        step(N + 61, spec="claude-usage-tracker",
             tracker=golden_store(TRACKER_USAGE, ident="other")),
    ]),
    # No id to key by: the session, as the reading caches are keyed.
    ("tracker: a profile with no id, the session", [
        step(N, spec="claude-usage-tracker",
             tracker=golden_store(TRACKER_USAGE, ident=None)),
        step(N + 1, spec="claude-usage-tracker", session="s2",
             tracker=golden_store(TRACKER_USAGE, ident=None)),
    ]),
    ("tracker: a reset that has passed", [
        step(N, spec="claude-usage-tracker", tracker=golden_store(
            dict(TRACKER_USAGE, sessionResetTime=N - 1 - APPLE))),
    ]),
    ("cmd: success, failure, recovery", [
        step(N, spec="cmd:${DIR}/cmd-ok", commands={"cmd-ok": CMD_OK},
             account="acct"),
        step(N + 61, spec="cmd:${DIR}/cmd-ok", commands={"cmd-ok": CMD_FAIL},
             account="acct"),
        step(N + 62, spec="cmd:${DIR}/cmd-ok", account="acct"),
        step(N + 64, spec="cmd:${DIR}/cmd-ok", commands={"cmd-ok": CMD_OK},
             account="acct"),
        step(N + 65, spec="none", account="acct"),
        step(N + 66, spec="none", account="other"),
    ]),
    ("cmd: flat adapter, week and month", [
        step(N, spec="cmd:${DIR}/flat", commands={"flat": CMD_FLAT},
             period="week"),
        step(N + 1, spec="cmd:${DIR}/flat", period="month"),
        step(N + 2, spec="cmd:${DIR}/missing", period="month"),
    ]),
    ("native: two sessions, one signed-in account", [
        step(N, spec="native", payload=PAYLOAD, claude_json=claude_json(
            "11111111-2222-3333-4444-555555555555")),
        step(N + 5, spec="native", claude_json=claude_json(
            "11111111-2222-3333-4444-555555555555")),
        step(N + 6, spec="auto", session="s2",
             payload={"session_id": "s2", "rate_limits": CLAUDE_LIMITS},
             claude_json=claude_json("11111111-2222-3333-4444-555555555555")),
    ]),
    ("native: another account, another scope", [
        step(N, spec="native", payload=PAYLOAD, claude_json=claude_json(
            "66666666-7777-8888-9999-000000000000")),
        step(N + 1, spec="native", payload=PAYLOAD,
             claude_json='{"oauthAccount": {"accountUuid": 5}}'),
    ]),
    ("native: live, then cached, then none", [
        step(N, spec="native", payload=PAYLOAD),
        step(N + 5, spec="native"),
        step(N + 400, spec="native"),
        step(N + 401, spec="", payload={}, session=""),
    ]),
]


def collect_cases(scratch):
    out = []
    for name, steps in SCENARIOS:
        directory = tempfile.mkdtemp(dir=scratch)
        state_dir = os.path.join(directory, "state")
        tracker = os.path.join(directory, "tracker.plist")
        config = os.path.join(directory, "config")
        os.makedirs(config)
        os.environ[STATE_ENV] = state_dir
        os.environ[TRACKER_ENV] = tracker
        os.environ[CONFIG_ENV] = config
        done = []
        for s in steps:
            for cmd, script in s["commands"].items():
                path = os.path.join(directory, cmd)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(script)
                os.chmod(path, 0o700)
            if s["tracker"] is None:
                if os.path.exists(tracker):
                    os.unlink(tracker)
            else:
                with open(tracker, "w", encoding="utf-8") as fh:
                    fh.write(s["tracker"])
            config_file = os.path.join(config, ".claude.json")
            if s["claude_json"] is None:
                if os.path.exists(config_file):
                    os.unlink(config_file)
            else:
                with open(config_file, "w", encoding="utf-8") as fh:
                    fh.write(s["claude_json"])
            spec = s["spec"].replace("${DIR}", directory)
            context = s["context"]
            if context is None:
                # The test builds this with statusSourceContext and checks
                # it against built_context.
                context = status_context(spec, s["session"],
                                         "claude-opus-5-5", s["now"],
                                         s["payload"])
            prepared = claude_sources.prepare_claude_reading(
                spec, s["account"], s["period"], context, s["now"])
            # The calibration cache's scope, which names its file: the
            # same for a fresh reading and a cached one.
            scope = claude.seed_limits_snapshot(
                prepared.limits if prepared.reading else claude.NO_LIMITS,
                prepared.reading).get("_scope", "")
            files = []
            for entry in sorted(os.listdir(state_dir)):
                if entry.endswith(".json"):
                    with open(os.path.join(state_dir, entry)) as fh:
                        files.append(json.load(fh))
            files.sort(key=lambda f: json.dumps(scrub(f, directory),
                                                sort_keys=True))
            done.append(scrub(dict(s, built_context=context,
                                   reading=prepared.reading,
                                   limits=prepared.limits._asdict(),
                                   scope=scope, state=files), directory))
        out.append({"name": name, "steps": done})
    return out


def main():
    for name in ("ANTHROPIC_ADMIN_KEY", "OPENAI_ADMIN_KEY",
                 "CLAUDE_OAUTH_ACCESS_TOKEN", "CODEX_USAGE_ACCESS_TOKEN",
                 "CODEX_USAGE_ACCOUNT_ID", "XDG_STATE_HOME"):
        os.environ.pop(name, None)
    set_tz("UTC")
    scratch = tempfile.mkdtemp(prefix="sources-fixtures.")
    # Never this machine's own config: a payload's reading would carry its
    # account.  collect_cases points each scenario at its own.
    os.environ[CONFIG_ENV] = os.path.join(scratch, "no-config")
    try:
        shutil.rmtree(OUT, ignore_errors=True)
        write("values.json", values())
        write("normalise.json", normalise_cases())
        write("native.json", native_cases())
        write("tracker.json", tracker_cases(scratch))
        write("command.json", command_cases(scratch))
        write("limits.json", limits_cases())
        write("collect.json", collect_cases(scratch))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
