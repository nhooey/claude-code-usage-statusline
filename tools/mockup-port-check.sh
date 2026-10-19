#!/bin/bash
# Check that mod/tools/layout-mockup.ts prints what tools/layout-mockup.py
# prints, byte for byte, over a matrix of options under each terminal
# profile.  Kept only until the Python mockup is deleted.
#
#     bash tools/mockup-port-check.sh
#
# Each language runs the whole matrix in one process per profile, since the
# Python reads the profile at import: one argv per line on stdin, and each
# run's output behind a "=== argv" line.  The outputs are then compared.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/mockup-port.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

# The matrix: every --cols (and none, the terminal's or 160), --part,
# --phase, --labels, --grid, --agents and --hide set, with and without
# --plain, and both --receipt forms for the whole screen.
/usr/bin/python3 - > "$WORK/argv.jsonl" <<'EOF'
import itertools, json
HIDES = [[], ["account"], ["*.work"], ["turn.time.eta"],
         ["session.workspace"], ["*.state.rate"],
         ["*.plan", "main", "agent.chat"],
         ["session", "turn.chat", "*.clock.time"]]
for cols, part, phase, labels, grid, agents, hide, plain, receipt in \
        itertools.product((200, 160, 150, 125, 100, 80, 60, 40, None),
                          ("screen", "band", "receipt", "start", "panel"),
                          ("done", "running"), ("spill", "clip"),
                          ("fixed", "rows"), (0, 1, 2), HIDES,
                          (False, True), ("mod", "hook")):
    if receipt == "hook" and part != "screen":
        continue
    argv = [] if cols is None else ["--cols", str(cols)]
    argv += ["--part", part, "--phase", phase, "--labels", labels,
             "--grid", grid, "--agents", str(agents), "--receipt", receipt]
    for h in hide:
        argv += ["--hide", h]
    print(json.dumps(argv + (["--plain"] if plain else [])))
EOF

cat > "$WORK/run.py" <<'EOF'
import contextlib, importlib.util, io, json, sys
spec = importlib.util.spec_from_file_location("mockup", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
for line in sys.stdin:
    argv = json.loads(line)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.main(argv)
    sys.stdout.write("=== %s\n%s" % (" ".join(argv), buf.getvalue()))
EOF

cat > "$WORK/run.ts" <<'EOF'
import { readFileSync } from "node:fs";
const { run } = await import(process.argv[2]);
const out: string[] = [];
for (const line of readFileSync(0, "utf8").split("\n")) {
  if (!line) continue;
  const argv = JSON.parse(line) as string[];
  out.push("=== " + argv.join(" ") + "\n" + run(argv, process.env));
}
process.stdout.write(out.join(""));
EOF

profiles=(unknown "" tmux TMUX=/tmp/tmux-501/default,1,0
          iterm TERM_PROGRAM=iTerm.app
          jediterm TERMINAL_EMULATOR=JetBrains-JediTerm)
for ((i = 0; i < ${#profiles[@]}; i += 2)); do
  name=${profiles[i]} set=${profiles[i + 1]}
  clean=(env -u TMUX -u TERM_PROGRAM -u TERMINAL_EMULATOR $set)
  "${clean[@]}" /usr/bin/python3 "$WORK/run.py" "$REPO/tools/layout-mockup.py" \
    < "$WORK/argv.jsonl" > "$WORK/$name.py.txt" &
  "${clean[@]}" node "$WORK/run.ts" "$REPO/mod/tools/layout-mockup.ts" \
    < "$WORK/argv.jsonl" > "$WORK/$name.ts.txt" &
done
wait

runs=$(wc -l < "$WORK/argv.jsonl")
fail=0
for ((i = 0; i < ${#profiles[@]}; i += 2)); do
  name=${profiles[i]}
  if cmp -s "$WORK/$name.py.txt" "$WORK/$name.ts.txt"; then
    echo "$name: $runs runs identical"
  else
    echo "$name: DIFFERS"
    diff "$WORK/$name.py.txt" "$WORK/$name.ts.txt" | head -20
    fail=1
  fi
done
exit $fail
