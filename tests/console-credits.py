#!/usr/bin/env python3
"""console-credits.py: the Console's tranches as credits[], its sign-in
from a command and never shown, and every failure an exit 1 with nothing
printed.  No network: the Console is a fake."""
import io, json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line import console_credits as cc
from coding_agent_usage_line import sources

ORG = "0f0f0f0f-1111-2222-3333-444455556666"
SECRET = "sk-ant-sid01-not-a-real-sign-in"
PREPAID = {"balance_credits": 3700,
           "promo_tranches": [{"name": "Promotional credit", "program_id": "promo-oct",
                               "granted_amount_minor_units": 20000,
                               "remaining_amount_minor_units": 19999, "currency": "usd",
                               "granted_at": "2026-10-15T00:00:00Z",
                               "expires_at": "2026-11-14T00:00:00Z"},
                              {"name": "no figure"}],
           "tranches": [{"granted_amount_minor_units": 10000,
                         "remaining_amount_minor_units": 3700}]}

def console(answers):
    """A fake get: each URL's (status, body), and the calls it saw."""
    seen = []
    def get(url, session):
        seen.append((url, session))
        return answers.get(url, (404, None))
    return get, seen

ANSWERS = {cc.ORGS_URL: (200, [{"uuid": ORG}, {"uuid": "not-a-uuid"}]),
           "%s/%s/prepaid/credits" % (cc.ORGS_URL, ORG): (200, PREPAID)}

def run(environ, answers=ANSWERS):
    get, seen = console(answers)
    out, err = io.StringIO(), io.StringIO()
    code = cc.main(environ, get, out, err)
    return code, out.getvalue(), err.getvalue(), seen

with tempfile.TemporaryDirectory() as tmp:
    base = {"CODING_AGENT_USAGE_LINE_CONFIG_DIR": tmp, "PATH": os.environ["PATH"]}
    printing = dict(base, **{cc.COMMAND_ENV: "printf '%s\\n' " + SECRET})

    # The tranches become a promo and a prepaid credit, in dollars, and a
    # tranche with no figure is dropped.
    code, out, err, seen = run(printing)
    assert code == 0 and err == "", (code, err)
    reading = json.loads(out)
    assert reading["schema_version"] == 1
    promo, prepaid = reading["credits"]
    assert promo == {"id": "console:0f0f0f0f:promo:promo-oct", "kind": "promo",
                     "remaining": 199.99, "granted": 200.0, "currency": "USD",
                     "granted_at": "2026-10-15T00:00:00Z",
                     "expires_at": "2026-11-14T00:00:00Z",
                     "label": "Promotional credit"}, promo
    assert prepaid["kind"] == "prepaid" and prepaid["remaining"] == 37.0, prepaid
    assert prepaid["id"] == "console:0f0f0f0f:prepaid:0"
    # The reading passes the shared validation as it is.
    kept = sources._credits(reading["credits"])
    assert [c["id"] for c in kept] == [promo["id"], prepaid["id"]], kept
    # The sign-in reaches the Console's two URLs only, and is never shown;
    # an organization that is no UUID is not asked.
    assert [u for u, _ in seen] == [cc.ORGS_URL, "%s/%s/prepaid/credits" % (cc.ORGS_URL, ORG)], seen
    assert all(s == SECRET for _, s in seen)
    assert SECRET not in out and SECRET not in err

    # The command can come from the configuration directory instead, its
    # first line that is no comment.
    with open(os.path.join(tmp, cc.COMMAND_FILE), "w") as fh:
        fh.write("# the Console sign-in\nprintf %s " + SECRET + "\n")
    code, out, _, seen = run(base)
    assert code == 0 and seen and seen[0][1] == SECRET

    # Every failure exits 1, prints nothing, and says why without the sign-in.
    os.remove(os.path.join(tmp, cc.COMMAND_FILE))
    cases = [
        (base, ANSWERS, "no sign-in command"),
        (dict(base, **{cc.COMMAND_ENV: "exit 3"}), ANSWERS, "exited 3"),
        (dict(base, **{cc.COMMAND_ENV: "true"}), ANSWERS, "no usable sign-in"),
        (dict(base, **{cc.COMMAND_ENV: "printf 'a; b'"}), ANSWERS, "no usable sign-in"),
        (printing, {cc.ORGS_URL: (403, None)}, "answered 403"),
        (printing, {cc.ORGS_URL: (200, {"not": "a list"})}, "answered 200"),
    ]
    for environ, answers, why in cases:
        code, out, err, _ = run(environ, answers)
        assert code == 1 and out == "", (why, code, out)
        assert why in err and SECRET not in err, (why, err)
    try:
        cc.read_session("sleep 5", timeout=0.2)
        raise AssertionError("a slow sign-in command must fail")
    except cc.Failure as failure:
        assert "longer than" in str(failure)

    # The sign-in is never sent off the Console.
    try:
        cc.http_get("https://example.com/api", SECRET)
        raise AssertionError("http_get must refuse another host")
    except cc.Failure as failure:
        assert "off the Console" in str(failure)

    # The launcher runs as a credits.command: no sign-in command, exit 1,
    # nothing on stdout.
    launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "console-credits.py")
    done = subprocess.run([launcher], env=base, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=30)
    assert done.returncode == 1 and done.stdout == b"", done
print("ok console credits")
