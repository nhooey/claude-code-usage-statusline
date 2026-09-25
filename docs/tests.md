# Tests

Everything is standard-library Python and bash, so there is nothing to install.
Run the whole deterministic set from the repository root, in bash or zsh:

```sh
for s in golden golden-cost py39-floor; do
  bash "tests/$s.sh" || { echo "FAIL: $s"; break; }
done
for t in usage-source sources-v1 source-cache http-sources app-server \
         claude-sources codex formatting port-cli agents subagent \
         claude-subagent-render rate; do
  python3 "tests/$t.py" || { echo "FAIL: $t"; break; }
done
```

Each suite exits non-zero on failure. They take seconds, use generated fixtures
only, and never read your credentials or your `~/.claude` history.

Run them from a directory macOS does not guard. Under `Documents`, `Downloads`
or `Desktop`, TCC can make Python's imports fail part-way through with
`PermissionError: [Errno 1] Operation not permitted`, which looks like a bug in
the program and is not.

## The suites

| Command | Checks | Result line |
|---|---|---|
| `bash tests/golden.sh` | `--mode status` output, byte for byte, against 135 golden files | `pass 135   fail 0   missing 0` |
| `bash tests/golden-cost.sh` | `--mode cost` output against 77 golden files | `pass 77   fail 0   missing 0` |
| `bash tests/py39-floor.sh` | the Python 3.9 floor: compiles everything and renders each mode under 3.9 | `pass 37   fail 0   missing 0` |
| `python3 tests/usage-source.py` | the Claude Usage Tracker reader, `cmd:` sources, and the scoped source cache | `pass 39   fail 0   missing 0` |
| `python3 tests/sources-v1.py` | the normalized v1 reading: schema, timestamps, separate quota buckets | `ok …` |
| `python3 tests/source-cache.py` | source precedence, freshness, refresh backoff, cache isolation | `ok …` |
| `python3 tests/http-sources.py` | admin and experimental HTTP sources against injected transports | `ok …` |
| `python3 tests/app-server.py` | a fake Codex app-server: framing, buckets, bounded cleanup | `ok …` |
| `python3 tests/claude-sources.py` | a normalized reading projected onto Claude's limit rows | `ok …` |
| `python3 tests/codex.py` | Codex rollout accounting, child threads, Stop report state | `ok …` |
| `python3 tests/formatting.py` | shared width and formatting helpers, display switches | `ok …` |
| `python3 tests/port-cli.py` | the public CLI end to end, including held-open stdin and concurrent Stops | unittest `OK` (14 tests) |
| `python3 tests/agents.py` | agent spend: reading agent files, folding them into turns, the 👥 row, the tool-time partition | `pass 51   fail 0` |
| `python3 tests/subagent.py` | the agent-panel rows: finding an agent's file, billing, window shares, nesting, row shape | `pass 57   fail 0` |
| `python3 tests/claude-subagent-render.py` | panel row rendering with no file or source reads | `ok …` |
| `python3 tests/rate.py` | the 🛫 token-rate sampler and cell, and the brightness-as-magnitude cuts | `pass 51   fail 0` |

The goldens pin the clock, so every render is the rate sampler's first tick and
🛫 is blank in every golden file. `rate.py` exists to check what the goldens
cannot: it steps the clock itself.

## What CI runs

[`.github/workflows/tests.yml`](../.github/workflows/tests.yml) runs on every
push and pull request:

- **goldens** — every suite in the table above except `py39-floor.sh`, on
  Python 3.9 and 3.13. The two golden scripts call `/usr/bin/python3`
  directly, so they run on the runner's system Python whichever matrix entry
  is active.
- **python 3.9 floor** — `py39-floor.sh`, pointed at a real 3.9 through `PY39`.
- **shell** — `bash -n` and `shellcheck -S warning` over `tests/*.sh`.

`usage-source.py` runs in CI even though it reads a macOS app's preference
store: it builds its own store with `plistlib`, so it needs neither macOS nor
the app.

## Checks that stay manual

| Command | Why CI cannot run it |
|---|---|
| `tests/compaction-once.py [TRANSCRIPT…]` | replays your real sessions to check every compaction is reported exactly once; minutes, not seconds |
| `tests/agents-once.py [TRANSCRIPT…]` | the same for agent spend reported late |
| `./coding-agent-usage-line.py --selftest` | measures the layout in the terminal you run it in; needs a real tty |
| `bash tests/probe-advance.sh` | measures every glyph's cursor advance in this terminal; needs a real tty and asserts nothing |

A runner has no Claude history to replay and no real terminal to measure.
See [tests/README.md](../tests/README.md#manual-checks) for how to run each.

## Changing what the readout draws

Edit the program, then re-record and read the diff:

```sh
bash tests/golden.sh --regen        # or golden-cost.sh --regen
git diff tests/golden/
```

Accept the new goldens only if every line that moved is one you meant to move,
and commit them with the change. `--regen` is the step where a regression gets
recorded as the expected output, so the diff is the review.

A failing golden run writes both sides under `tests/out/` (status) or
`tests/out-cost/` (cost) as `NAME.got` and `NAME.want`.

[tests/README.md](../tests/README.md) covers how the goldens are built, what
the pinned environment holds still, what each case is for, and the recorded
behaviours that look like bugs.
