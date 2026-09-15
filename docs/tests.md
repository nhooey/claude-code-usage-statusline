# Tests

The tests live in `tests/`, beside the program. They did not until
2026-08-28: ten of the thirteen status payloads read a real 8.7 MB session
transcript under `~/.claude/projects/`, which is somebody's actual
conversation. Both corpora are generated now — `mkcorpus-status.py` and
`mkcorpus-cost.py` write their fixtures into the scratch directory at the top
of every run — so nothing in here belongs to anyone, and a fixture cannot
drift away from the generator that describes it.

```sh
bash tests/golden.sh              # status mode, 135 comparisons — seconds
bash tests/golden-cost.sh         # cost mode, 77 comparisons — seconds
bash tests/py39-floor.sh          # the claimed 3.9 floor, checked — seconds
python3 tests/usage-source.py     # tracker/command/cache migration, 39 cases — seconds
python3 tests/agents.py           # agent spend: reader, fold-in, late row, scan — seconds
python3 tests/subagent.py         # the agent panel rows: file lookup, billing, shares, shape — seconds
python3 tests/rate.py             # the status line's 🛫: the sampler and its cell; the brightness cuts — seconds
python3 tests/formatting.py       # shared width/formatting/configuration
python3 tests/sources-v1.py       # normalized schema and quota hierarchy
python3 tests/source-cache.py     # source precedence, freshness, backoff, isolation
python3 tests/claude-sources.py   # shared intake to Claude display projection
python3 tests/claude-subagent-render.py # prepared panel rows without I/O
python3 tests/http-sources.py     # offline admin/private endpoint contracts
python3 tests/app-server.py       # fake app-server framing, buckets and cleanup
python3 tests/codex.py            # rollout accounting, descendants and reporting state
python3 tests/port-cli.py         # public CLI, held-open stdin and concurrent late usage
tests/compaction-once.py          # replay real sessions — MINUTES, see below
tests/agents-once.py              # the same for agent spend — MINUTES
./coding-agent-usage-line.py --selftest    # needs a real tty
bash tests/probe-advance.sh       # needs a real tty; measures, does not assert
```

The first seven must end `fail 0   missing 0` (or `fail 0`). A deliberate layout change is
accepted with `--regen` **after reading the diff** — that is the step where a
regression gets blessed as the new expected output.

All the deterministic suites above also run in CI over Python 3.9 and
3.13, plus `shellcheck` over `tests/*.sh` — see
`.github/workflows/tests.yml`. `usage-source.py` reads a macOS app's
preference store and is in CI anyway: it builds its own fixture store with
`plistlib`, so it needs neither macOS nor the app. HTTP and app-server tests
likewise use fixtures, not live credentials. The two real-history replay
scripts and two real-terminal checks are manual: CI has neither those private
histories nor the specific terminal whose rendering is being checked.

**Run the suites from a directory macOS does not guard.** Under `Documents`,
`Downloads` or `Desktop`, TCC can make Python's import machinery raise
`PermissionError: [Errno 1] Operation not permitted` part-way through a run,
which reads as a fault in the program and is not one.

`--selftest` is the only check that catches a glyph which measures correctly and
paints wrong, and it needs a real terminal tab. Run it in each terminal, and
look at the drawn rows as well as the numbers.

`rate.py` exists because the goldens cannot show the figure it checks: they
pin the clock, so every render of a case is the sampler's first tick and the
🛫 field is blank in every golden file — correctly, and uselessly as a test
of the slope. The suite steps the clock by hand against a scratch state directory
and pins the tick, the depth of the history, a damaged file, and the cell.
It also pins the brightness-as-magnitude rule — one fixed cut per kind, dim
under it, and a dim first field reset before the second — because the goldens
record the escapes without saying which of them is the rule and which the
value, and a re-bless would accept a 🛫 that dimmed the 🎯 beside it.

`tests/README.md` carries the rest, including what the generated session is
built to reach and why the differential test against the two programs this one
replaced was retired.

`compaction-once.py` is the one test that still reads real sessions: the rule
it checks is about a SEQUENCE of Stop hooks across a whole conversation, so it
replays whatever transcripts this machine has under `~/.claude/projects/`. It
records nothing, so it takes no fixture with it. **It costs minutes, not
seconds** — its runtime scales with the reader's history, and one recent run
read 149 sessions to find the 28 with a compaction in them and took over ten
minutes. Give it no timeout, or a generous one.

`agents-once.py` is its sibling for agent spend: every session with a
`subagents/` directory and a Stop record, each Stop replayed with the main
file cut before its record and each agent file cut at its stamp, the state
file published between Stops the way the live hook publishes it. It asserts
that every agent request is on a 🎤 or 👥 row at the Stop that first saw it,
and on the 👥 row at no later Stop. Same cost as its sibling, for the same
reason.
