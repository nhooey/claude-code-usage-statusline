# Tests

Everything is standard-library Python and bash, so there is nothing to install.
Run the whole deterministic set from the repository root, the mod's included,
side by side, with one line per suite on how it went:

```sh
bash tests/all.sh                  # every suite, about 17 s
bash tests/all.sh status node      # the ones named
bash tests/all.sh --repeat 20 node # again, until a round fails
```

It exits with the number of suites that failed and prints the end of each
failing one's output. `--repeat N` is for a flaky suite: it stops at the first
round with a failure and exits with that round's status. The mod's suites want `mod/node_modules` (`npm ci`),
the engine's types under `mod/.claude-plugin/types/` and the `claude` CLI;
without them those lines fail and the rest still run. Or one at a time, in
bash or zsh:

```sh
for s in golden golden-cost py39-floor; do
  bash "tests/$s.sh" || { echo "FAIL: $s"; break; }
done
for t in usage-source sources-v1 source-cache http-sources app-server \
         claude-sources codex formatting port-cli agents subagent \
         claude-subagent-render rate grid; do
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
| `python3 tests/run-cases.py` | both suites below, from the committed cases in `tests/fixtures/`, and each case's [figures](../tests/README.md#figures) and render stages apart; then the [agent panel's](../tests/README.md#agent-panel-cases) 45 `--mode subagent` goldens and its 275 render cases | `pass 273   fail 0   missing 0`, then `panel    275 cases   0 files differ` |
| `bash tests/golden.sh` | `--mode status` output, byte for byte, against 141 golden files | `pass 141   fail 0   missing 0` |
| `bash tests/golden-cost.sh` | `--mode cost` output against 87 golden files | `pass 87   fail 0   missing 0` |
| `bash tests/py39-floor.sh` | the Python 3.9 floor: compiles everything and renders each mode under 3.9 | `pass 53   fail 0   missing 0` |
| `cd mod && node --test 'test/*.test.ts'` | the TypeScript port against the cases the Python writes under `tests/fixtures/`: the spec, the usage-source reader, the accounting, the calibration, the formatters and spans, and the status line, the receipt and the agent panel, cell by cell and against every golden | `ℹ fail 0` |
| `cd mod && npm ci && npm run typecheck` | the TypeScript port's types, with TypeScript and Node's type definitions from the lockfile | no output |
| `python3 tests/usage-source.py` | the Claude Usage Tracker reader, `cmd:` sources, and the scoped source cache | `pass 39   fail 0   missing 0` |
| `python3 tests/sources-v1.py` | the normalized v1 reading: schema, timestamps, separate quota buckets | `ok …` |
| `python3 tests/source-cache.py` | source precedence, freshness, refresh backoff, cache isolation | `ok …` |
| `python3 tests/http-sources.py` | admin and experimental HTTP sources against injected transports | `ok …` |
| `python3 tests/app-server.py` | a fake Codex app-server: framing, buckets, bounded cleanup | `ok …` |
| `python3 tests/claude-sources.py` | a normalized reading projected onto Claude's limit rows | `ok …` |
| `python3 tests/codex.py` | Codex rollout accounting, child threads, Stop report state | `ok …` |
| `python3 tests/formatting.py` | shared width and formatting helpers, display switches | `ok …` |
| `python3 tests/port-cli.py` | the public CLI end to end, including held-open stdin and concurrent Stops | unittest `OK` (15 tests) |
| `python3 tests/agents.py` | agent spend: reading agent files, folding them into turns, the 👥 row, the tool-time partition, the receipt's per-turn share of it with its agents', the cache of each agent file's reading, and the calibration scan's cache of each file's priced requests, and the main thread's open shells and Monitors, and the receipt's turn tag, and a running agent's row waiting for its end | `pass 88   fail 0` |
| `python3 tests/fold.py` | the main transcript's folds broken anywhere: finished at every record, or with a half-written last line, each reads on as the whole fold | `pass 79   fail 0` |
| `python3 tests/subagent.py` | the agent-panel rows: finding an agent's file, billing, window shares, nesting, the reported ETA and its inheritance, the inbox, silence, compactions, open shells and Monitors, API errors and worktree branch, a window share that never starts the calibration scan, row shape | `pass 117   fail 0` |
| `python3 tests/claude-subagent-render.py` | panel row rendering with no file or source reads | `ok …` |
| `python3 tests/rate.py` | the 🛫 token-rate sampler, the Doing cell and the main thread's states, column 2 in the padded profile, and the brightness-as-magnitude cuts, and the 🧠 estimate after a compaction | `pass 71   fail 0` |
| `python3 tests/grid.py` | `grid.py`, the redesigned grid, against the [cases the TypeScript writes](../tests/README.md#grid-cases), under each profile they name | `pass 22159   fail 0` |

The goldens pin the clock, so every render is the rate sampler's first tick
and there is no rate to show: the Doing figure is 🤖 and how long the corpus
transcript has been quiet. `rate.py` exists to check what the goldens cannot:
it steps the clock itself.

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
| `check-folds [--largest N] [FILE…]` | breaks the transcript folds over every real transcript, in both ports; minutes over your whole history |
| `./coding-agent-usage-line.py --selftest` | measures the layout in the terminal you run it in; needs a real tty |
| `bash tests/probe-advance.sh` | measures every glyph's cursor advance in this terminal; needs a real tty and asserts nothing |

A runner has no Claude history to replay and no real terminal to measure.
See [tests/README.md](../tests/README.md#manual-checks) for how to run each.

## Changing what the readout draws

Edit the program, then re-record and read the diff:

```sh
python3 tests/run-cases.py --regen  # or golden.sh / golden-cost.sh --regen
git diff tests/golden/
```

A change to a test input goes in its generator under `tests/fixtures/gen/`;
run `python3 tests/fixtures/gen/all.py` and read `git diff tests/fixtures/`
before re-recording.

Accept the new goldens only if every line that moved is one you meant to move,
and commit them with the change. `--regen` is the step where a regression gets
recorded as the expected output, so the diff is the review.

A failing golden run writes both sides under `tests/out/` (status),
`tests/out-cost/` (cost) or `tests/out-subagent/` (the agent panel) as
`NAME.got` and `NAME.want`. A failing panel case names its file and case;
`python3 tests/fixtures/gen/all.py` and `git diff tests/fixtures/panel/`
show the rows that moved.

[tests/README.md](../tests/README.md) covers how the goldens are built, what
the pinned environment holds still, what each case is for, and the recorded
behaviours that look like bugs.
