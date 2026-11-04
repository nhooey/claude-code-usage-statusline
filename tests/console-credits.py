#!/usr/bin/env python3
"""console-credits.py: the credits written in console-credits.json, as a
credits.command prints them; a missing or broken file an exit 1 with
nothing printed; an entry the reading drops named on stderr."""
import io, json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line import console_credits as cc
from coding_agent_usage_line import sources

PROMO = {"id": "console-promo", "kind": "promo", "remaining": 199.99, "granted": 200,
         "currency": "USD", "expires_at": "2026-11-14T00:00:00Z", "label": "Promotional credit"}

def run(environ):
    out, err = io.StringIO(), io.StringIO()
    code = cc.main(environ, out, err)
    return code, out.getvalue(), err.getvalue()

with tempfile.TemporaryDirectory() as tmp:
    environ = {"CODING_AGENT_USAGE_LINE_CONFIG_DIR": tmp}
    path = os.path.join(tmp, cc.FILE)
    def write(text):
        with open(path, "w") as fh: fh.write(text)

    # No file, or one that isn't JSON or holds no list: exit 1, nothing out.
    for text, why in ((None, "no " + path), ("{not json", "is not JSON"),
                      ('{"credits": 3}', 'holds no "credits" list')):
        if text is not None: write(text)
        code, out, err = run(environ)
        assert code == 1 and out == "" and why in err, (text, code, out, err)

    # The written credits, as the reading takes them.
    write(json.dumps({"credits": [PROMO]}))
    code, out, err = run(environ)
    assert code == 0 and err == "", (code, err)
    reading = json.loads(out)
    assert reading == {"schema_version": 1, "credits": [PROMO]}, reading
    kept = sources._credits(reading["credits"])
    assert [(c["kind"], c["remaining"], c["expires_at"]) for c in kept] == \
        [("promo", 199.99, 1794614400)], kept

    # A bare list works too, and an entry the reading drops is named.
    write(json.dumps([PROMO, {"id": "bad", "kind": "promo", "remaining": 300, "granted": 200},
                      {"kind": "prepaid", "remaining": 5}]))
    code, out, err = run(environ)
    assert code == 0 and len(json.loads(out)["credits"]) == 3
    assert "credits[1] dropped" in err and "credits[2] dropped" in err and "credits[0]" not in err, err

    # The launcher runs as a credits.command.
    write(json.dumps({"credits": [PROMO]}))
    launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "console-credits.py")
    done = subprocess.run([launcher], env=dict(environ, PATH=os.environ["PATH"]),
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    assert done.returncode == 0 and json.loads(done.stdout)["credits"] == [PROMO], done
print("ok console credits")
