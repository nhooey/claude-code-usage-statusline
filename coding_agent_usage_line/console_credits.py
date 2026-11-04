"""The Claude Console's credits, as a `credits.command` for the mod.

The Console reports an organization's promotional and prepaid credits
only to its own web sign-in, at an undocumented endpoint, and refuses
Claude Code's credential.  This asks it with a sign-in that a command of
the user's choosing prints, so the sign-in stays in whatever store they
keep it in: SecretSpec, 1Password's `op`, the macOS keychain, the Linux
keyring, or a file only they can read.  The command is found, first of:

  $CODING_AGENT_USAGE_LINE_CONSOLE_SESSION_COMMAND
  <the user configuration directory>/console-session-command, one line

and runs through /bin/sh.  Its output, the value of the Console's
`sessionKey` cookie, is sent to platform.claude.com alone and never
printed, logged or saved.

Prints {"schema_version": 1, "credits": [...]} as docs/usage-sources.md
gives credits[], and exits 0; on any failure prints nothing and exits 1,
so the mod keeps the credits it had.
"""
import json
import os
import subprocess
import sys

from .config import user_dir

CONSOLE = "https://platform.claude.com"
ORGS_URL = CONSOLE + "/api/organizations"
COMMAND_ENV = "CODING_AGENT_USAGE_LINE_CONSOLE_SESSION_COMMAND"
COMMAND_FILE = "console-session-command"
# The mod gives a credits command 5 seconds: the sign-in, the
# organizations and each one's credits share them.
SESSION_TIMEOUT = 2.0
REQUEST_TIMEOUT = 1.5
# Currencies whose minor unit is the unit itself; the rest have cents.
ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "ISK"}


class Failure(Exception):
    """Why no credits were read, in words that hold no secret."""


def session_command(environ):
    """The command that prints the sign-in, or None."""
    command = environ.get(COMMAND_ENV, "").strip()
    if command:
        return command
    path = os.path.join(user_dir(environ), COMMAND_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = [l.strip() for l in fh if l.strip() and not l.lstrip().startswith("#")]
    except OSError:
        return None
    return lines[0] if lines else None


def read_session(command, timeout=SESSION_TIMEOUT):
    """The sign-in the command prints, its first line."""
    try:
        done = subprocess.run(["/bin/sh", "-c", command], stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Failure("the sign-in command took longer than %gs" % timeout)
    if done.returncode != 0:
        raise Failure("the sign-in command exited %d" % done.returncode)
    value = done.stdout.decode("utf-8", "replace").strip().splitlines()
    value = value[0].strip() if value else ""
    if not value or any(c in value for c in ";\r\n\0 "):
        raise Failure("the sign-in command printed no usable sign-in")
    return value


def http_get(url, session, timeout=REQUEST_TIMEOUT):
    """GET a Console URL with the sign-in: (status, parsed JSON or None)."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen
    if not url.startswith(CONSOLE + "/"):
        raise Failure("refusing to send the sign-in off the Console")
    request = Request(url, headers={"Cookie": "sessionKey=" + session,
                                    "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as answer:
            status, body = answer.status, answer.read()
    except HTTPError as error:
        return error.code, None
    except (URLError, OSError):
        raise Failure("the Console did not answer")
    try:
        return status, json.loads(body.decode("utf-8"))
    except ValueError:
        return status, None


def _amount(minor, currency):
    if isinstance(minor, bool) or not isinstance(minor, (int, float)):
        return None
    return minor / (1 if currency in ZERO_DECIMAL else 100)


def tranche_credit(org, kind, index, tranche):
    """One credits[] entry from one of the Console's tranches, or None."""
    if not isinstance(tranche, dict):
        return None
    currency = tranche.get("currency")
    currency = currency.upper() if isinstance(currency, str) else "USD"
    remaining = _amount(tranche.get("remaining_amount_minor_units"), currency)
    if remaining is None:
        return None
    key = tranche.get("program_id") or tranche.get("name") or index
    credit = {"id": "console:%s:%s:%s" % (org[:8], kind, key), "kind": kind,
              "remaining": remaining, "currency": currency}
    granted = _amount(tranche.get("granted_amount_minor_units"), currency)
    if granted is not None:
        credit["granted"] = granted
    for field in ("expires_at", "granted_at"):
        if isinstance(tranche.get(field), (str, int, float)):
            credit[field] = tranche[field]
    if isinstance(tranche.get("name"), str):
        credit["label"] = tranche["name"][:80]
    return credit


def org_credits(org, answer):
    """An organization's credits from its prepaid/credits answer."""
    if not isinstance(answer, dict):
        return []
    found = []
    for field, kind in (("promo_tranches", "promo"), ("tranches", "prepaid")):
        tranches = answer.get(field)
        if not isinstance(tranches, list):
            continue
        for index, tranche in enumerate(tranches):
            credit = tranche_credit(org, kind, index, tranche)
            if credit is not None:
                found.append(credit)
    return found


def credits(session, get=http_get):
    """Every organization's credits the sign-in reaches."""
    status, orgs = get(ORGS_URL, session)
    if status != 200 or not isinstance(orgs, list):
        raise Failure("the Console's organizations answered %s" % status)
    found = []
    for org in orgs:
        uuid = org.get("uuid") if isinstance(org, dict) else None
        if not isinstance(uuid, str) or len(uuid) != 36 or \
                any(c not in "0123456789abcdef-" for c in uuid):
            continue
        status, answer = get("%s/%s/prepaid/credits" % (ORGS_URL, uuid), session)
        if status == 200:
            found.extend(org_credits(uuid, answer))
    return found


def main(environ=None, get=http_get, out=None, err=None):
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    command = session_command(environ)
    if not command:
        err.write("console-credits: no sign-in command: set %s, or write one in %s\n"
                  % (COMMAND_ENV, os.path.join(user_dir(environ), COMMAND_FILE)))
        return 1
    try:
        found = credits(read_session(command), get)
    except Failure as failure:
        err.write("console-credits: %s\n" % failure)
        return 1
    out.write(json.dumps({"schema_version": 1, "credits": found},
                         separators=(",", ":")) + "\n")
    return 0
