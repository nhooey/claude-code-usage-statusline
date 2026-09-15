#!/usr/bin/env python3
"""Offline JSON-RPC framing/timeout contract for the Codex app-server reader."""
import os, stat, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from coding_agent_usage_line.sources import codex_app_server

SERVER = '''#!/usr/bin/env python3
import json, os, sys
for line in sys.stdin:
    msg=json.loads(line)
    if msg.get("method") == "initialize":
        os.write(1, b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\\n')
    elif msg.get("method") == "account/rateLimits/read":
        answer={"jsonrpc":"2.0","id":2,"result":{"rateLimitsByLimitId":{"general":{"limitId":"general","limitName":"General","primary":{"usedPercent":31,"windowDurationMins":300,"resetsAt":"2026-09-14T20:15:00Z"},"secondary":{"usedPercent":89,"windowDurationMins":10080,"resetsAt":"2026-09-21T15:15:00Z"}},"spark":{"limitId":"spark","limitName":"Spark","primary":{"usedPercent":100,"windowDurationMins":300,"resetsAt":"2026-09-14T21:15:00Z"},"secondary":{"usedPercent":100,"windowDurationMins":10080,"resetsAt":"2026-09-21T16:15:00Z"}}}}}
        raw=(json.dumps(answer)+"\\n").encode(); os.write(1, raw[:17]); os.write(1, raw[17:])
'''
SILENT = '#!/bin/sh\nexec sleep 10\n'
with tempfile.TemporaryDirectory() as tmp:
    path=os.path.join(tmp, "server")
    with open(path, "w") as fh: fh.write(SERVER)
    os.chmod(path, stat.S_IRWXU)
    got=codex_app_server(path, timeout=2)
    assert [(b["id"], len(b["windows"])) for b in got["buckets"]] == [("general", 2), ("spark", 2)]
    assert got["buckets"][0]["windows"][0]["resets_at"] != got["buckets"][1]["windows"][0]["resets_at"]
    with open(path, "w") as fh: fh.write(SILENT)
    os.chmod(path, stat.S_IRWXU)
    assert codex_app_server(path, timeout=.1) == {}
print("ok app-server framing, buckets, silence")
