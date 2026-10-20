# Saved running totals: fold the transcript once

A proposal, not built yet. Commit ec4dc64 saves the session's cut-down
records, so a reload no longer runs Python over the whole transcript again.
Each reload still folds every record, though, and so does every document
after it. This plan turns the two folds into running totals saved on disk.
It also gives every cache both ports keep one name and one format. The
first step under that contract fixes the panel's `🪫 ?`.

## Why

- **Every document folds the whole session.** `statusDoc` (`mod/hooks/edges.ts`)
  hands every record read so far to `transcriptOf`, then to `turnsOf`
  through `turnsVia`. Both walk the whole list on each document, and
  `transcriptOf` walks it four times. `turnsNow` does the same for the
  receipt. The 205 MB transcript in `~/.claude/projects` is 75,365 records.
  Python takes 1.0s to parse them, then 2.0s for `read_transcript` and 1.3s
  for `read_turns` (measured 2026-10-20). The TypeScript walks the same
  records in the hooks worker on every document.
- **The saved cut is large and only grows.** This session's cut is 20 MB in
  21 parts of about 1 MB each, at 160 MB of transcript. A reload reads and
  parses all 21 parts in the worker before folding them again.
- **What the folds keep is small.** On the four largest transcripts here, an
  estimate of the state a fold must carry from one record to the next is
  0.35 to 1.8 MB (below). The cut is ten to sixty times that.
- **The panel draws `🪫 ?` on every agent row.** `agent_window_shares` asks
  `calibration(scan=False)` for its unit. That reads
  `claude-calibration-<sha256(scope\0windows)>.json`, which only the retired
  Python status line wrote. The mod writes the same fields to
  `claude-calibration-ts-<sha256(version\0scope\0windows)>.cache`, keyed by
  `CONFIG.version`. The two never meet, so the panel has no unit.
- **The caches have drifted apart.** Each port names its own copy of the
  same cache, and each keys it its own way: the Python by a digest of its
  own source (`_source_digest`), the mod by `CONFIG.version`. The window
  costs are kept three times over: `claude-window-costs.cache`,
  `claude-window-costs-ts.cache` and `claude-window-costs-mod.cache`. The
  Python's calibration cache is one file per pair of window starts, and none
  is ever removed: the state directory holds 65,075 of them. They are `.json`
  files too, and `state.find_compatible` opens every `.json` in the
  directory as a usage cache whenever it looks for one.

## The design

### Fold, then finish

Each fold splits into two functions:

- **The fold** takes a state and one record, and updates the state. It reads
  nothing but the record.
- **The finish** takes the state and what is only known at render, and
  returns the figures. The state is left as it was, so the fold can go on.

`transcriptOf(records, agents, etas, now)` becomes
`transcriptFinish(foldAll(records), agents, etas, now)`, and `turnsOf` becomes
`turnsFinish(foldAll(records), agentsOf, offsets, held, label)`, in both
ports. The old names stay as wrappers, so every caller and every shared case
reads as before.

The split falls where the code already has it:

| Input | Known | Goes into |
|---|---|---|
| the main transcript's records | as each line is written | the fold |
| the agents' records and ETAs (`agents`, `agent_etas`) | each render, from the agent folds | the finish |
| the Stop hook's offsets, `held`, `label` | each render | the finish |
| `now` | each render | the finish |

The fold therefore never depends on the agent files, and a saved state stays
true however the agents change.

Every pass in `transcriptOf` is already a left fold over `records`:

- the dedupe, with its set of request ids;
- the own parts, with the open compaction;
- the context reading, with `firstCtx`;
- the last texts;
- the clock, with its spans, `pending`, the ETA state, the background map,
  the idle and the open turn's id;
- the diff lines, with their tool-use ids;
- `liveAgentEtas`' agent ends.

They become one walk with one state. The finish does the rest:

- `openToolSpans` against `now`, and the running and waiting calls;
- `threadClock`;
- the agents' sums;
- the `own_parts` total.

`turnsOf`'s main loop is a fold too. `_foldAgents`, the Δctx walk and the
freeze are the finish, run over a copy of the turns, so the agents added in
one render never reach the state.

**The order of additions is kept.** The finish adds the agents after every
main record, as the whole fold does now, so the floats come out bit for bit
the same. The equivalence tests compare exactly, with no tolerance.

**The open line.** `recordsOf` also returns the records of a last line that
has no newline yet, which can be half written. The fold takes only whole
lines. Records past the last newline are folded into the state and undone
after the finish: each list keeps its length, each set the keys it gained,
and the small mutable part is copied first. A half-written last line is rare,
so the cost is rare too.

### The state

What the fold carries, by port-neutral name:

| Part | Grows with | Changes after it is written |
|---|---|---|
| request ids seen (both folds share one set) | requests | no |
| tool-use ids `diffLines` has counted (one set) | edits and writes | no |
| closed turns | prompts and compactions | no: only the open turn changes |
| prompt ids, each with its turn's index (`byPid`) | prompts | no: the first one stays |
| agent ends (`scanAgentEnd`) | agents | no: a later entry wins on load |
| own parts | requests and compactions | no, except those since the open compaction |
| the clock's spans, tool spans and blocked spans | turns and tool calls | no |
| the open turn, `pending`, the ETA state, the open compaction, the background map, the queue count, the context reading, the last texts, the scalars | nothing | yes, on every record |

Everything but the last row is append-only. The last row is small: `pending`
holds only the calls still open.

**How big.** The estimate (`measure.py`, a throwaway script that counts what
each part holds; step 3 measures the real state):

| Transcript | Records | Requests | Turns | Compactions | Tool results | Est. state |
|---|---|---|---|---|---|---|
| 221 MB | 24,962 | 4,209 | ~351 | 34 | 4,292 | 0.7 MB |
| 206 MB | 75,365 | 12,255 | ~510 | 83 | 12,975 | 1.8 MB |
| 160 MB (this repo) | 28,398 | 1,846 | ~264 | 13 | 2,077 | 0.3 MB |
| 156 MB | 72,908 | 7,670 | ~1,744 | 55 | 6,390 | 1.6 MB |

At 1.8 MB, the largest state is under 4 MiB but not by enough: a session
twice that long would not fit. So the state is saved in parts, the way the
cut is.

- **A log of the append-only parts.** Each entry is one JSON line tagged with
  its list: `["req", id]`, `["turn", {...}]`, `["part", epoch, usd]` and so
  on. It goes into part files of at most `MAIN_CUT_PART` (1,000,000)
  characters each, which is under 4 MiB as UTF-8. A part only grows, and every
  part but the last is never written again. A save writes only the last part
  and any new parts.
- **A head, written last.** The head holds the format, the byte offset the
  state covers, the transcript's check digests, the number of entries in
  each part, and the mutable small state. Until the head is written, the one
  before it is still true: its counts take a prefix of each part, as
  `mainCutHeadOf` takes one now.
- **A cap on the head.** If the head would be over `MAIN_CUT_PART`, the state
  is not saved. It stays in memory, and the next reload folds from the start.
  The log turns this into a log line; it is not expected to happen.

In memory the sets stay sets and the lists stay lists. The log is only how
they are saved.

### What invalidates a saved state

| Event | How it is seen | What happens |
|---|---|---|
| The fold's code changed in either port | the head's format differs from the spec's | fold from the start |
| The transcript was truncated | its size is below the head's offset | fold from the start |
| The transcript was rewritten in place | the digest of the `COST_TAIL_BYTES` (4 KiB) before the offset differs, as `_tail_digest` checks the window costs; or the digest of its first 4 KiB differs | fold from the start |
| A compaction | nothing to see | nothing: Claude Code appends `compact_boundary` and `isCompactSummary` records to the same file, and the fold already counts them. The equivalence tests run over a transcript with 83 compactions |
| `/resume` that forks, or `/clear` | a new transcript path | a new state, keyed by the path's digest |
| A torn head or part | it does not parse, or holds fewer entries than the head names | fold from the start |

**Keeping the format honest.** A format bumped by hand is only as good as
the memory of whoever changed the fold. So the tests write the saved state
of every fixture transcript to `tests/fixtures/state/`, with the format it was
written under. The check fails when a state differs from its fixture while
the spec's format still matches the fixture's. A change to the fold then
cannot land without a new format, and the two ports cannot drift apart
without failing the same check.

### The shared-state contract

The contract covers every file both ports keep in the state directory:

- **One table in the spec.** The table lives in `spec/layout.jsonc`, generated
  into `spec.py` and `spec.ts` by `tools/gen-spec.py`. Each cache kind has one
  row: its file-name prefix, what its key is a digest of, its extension and
  its format number. Neither port's version is in it: not `CONFIG.version`,
  and not `_source_digest`.
- **One path function per port** (`state_path(kind, *key)` and `statePath`).
  It joins the state directory, the prefix, and a sha256 of the kind's
  format and key parts, separated by `\0`. Shared cases pin the name it
  gives for each kind, in both ports.
- **One write rule.** The Python writes a temporary file and calls
  `os.replace`. `$.fs` has `read`, `write`, `stat` and `list`, and the mod
  calls no rename, so a mod write is treated as one that can tear. A file
  in parts writes its head last, and the reader checks it, as the cut does.
  A single-file cache is read with a parse check, and a torn file reads as
  missing.
- **No `.json`.** Every shared file ends `.cache`, so `find_compatible` never
  opens one.
- **Writers that agree by construction.** Both ports fold the same bytes into
  the same state, so two writers that save the same range write the same
  text. That holds only while the two ports match byte for byte, which the
  shared cases check.

The kinds, and where each ends up:

| Kind | Python today | Mod today | After | Step |
|---|---|---|---|---|
| calibration | `claude-calibration-<h>.json` | `claude-calibration-ts-<h>.cache` | `claude-calibration-<sha(format\0scope)>.cache`, one per scope, with the windows inside | 1 |
| main fold | none | none (the cut) | `claude-main-fold/<sha(path)>/head.cache`, `part-N.cache` | 4 to 6 |
| main cut | none | `claude-main-cuts-mod/` | removed | 7 |
| agent fold | none (`read_agent_usage` reads the whole file each tick) | `claude-agent-folds-mod/<h>/<h>.json` | `claude-agent-fold/<sha(transcript)>/<sha(path)>.cache` | 8 |
| agent files | `claude-agent-files-<h>.cache` | `claude-agent-files-ts-<h>.cache` | replaced by the agent folds | 8 |
| window costs | `claude-window-costs.cache` | `-ts.cache` (node), `-mod.cache` (mod) | `claude-window-costs.cache` | 9 |
| agent offsets | `claude-agent-offsets-<h>.json` | the same file, read only | already shared; renamed `.cache` only if the Stop hook moves to the mod | none |

## The build order

Each step lands as its own commit, and the tests pass after each one.

1. **The calibration cache, shared.** This step fixes the panel's `🪫 ?` and
   starts the contract with its first kind.
   - Add `STATE_CALIBRATION_FORMAT` to the spec's new state table, and
     generate it into both ports.
   - Both ports name the file
     `claude-calibration-<sha256(format\0scope)>.cache`. Today's name has one
     file per pair of window starts. With the windows inside the file
     instead, there is one file per scope, and a reset overwrites it.
     `_read_calib_cache` and `calibrationVia` already treat a file for other
     windows as a miss.
   - Both write the fields they write today: `windows`, `sess_cost`,
     `week_cost`, `sess_pct`, `week_pct`. They use `pyJsonDumps` and its
     Python twin with one set of separators, so the two files are
     byte-identical. A shared case checks it: the same inputs, written by
     each port, give the same bytes.
   - The Python's `calibration_cache_path` and the mod's
     `_calibrationCacheName` both call the contract's path function.
     `CALIB_CACHE_OVERRIDE` and the planted fixtures in `tests/fixtures/env/`
     are unchanged.
   - The panel then reads the scan the mod wrote, with `scan=False`, at any
     age, as it does now.
   - Old files are removed once: `claude-calibration-<64 hex>.json` and
     `claude-calibration-ts-<64 hex>.cache`, and nothing else. See the open
     questions.

   **Status 2026-10-20: done.** As built:
   - The table is `STATE_KINDS` in `spec/state.jsonc`, one row per kind
     (prefix, key parts, suffix, format), generated to `state_spec.py` and
     `mod/src/state_spec.ts`. The calibration row's `format` is what was
     planned as `STATE_CALIBRATION_FORMAT`.
   - The path functions are `state.state_name` / `state_path` and the mod's
     `stateName` / `statePath` (`mod/src/state.ts`). The text is
     `calib_cache_text` and `_calibCacheText`.
   - `find_compatible`, and the mod's two ports of it, open only a usage
     cache's name, 64 hex digits and `.json`.
   - The Python removes the old files, since `$.fs` cannot remove one: one
     listing at most a second long per run, then the marker
     `claude-calibration-old-removed`. Its first live run removed 65,075
     `.json` files and the `-ts-` ones. A mod still running the old code
     writes `-ts-` files after the marker; removing the marker once every
     session's mod is refreshed sweeps them on the next run.
2. **The folds split into fold and finish,** in both ports, with nothing
   saved yet. `transcriptOf`, `turnsOf`, `read_transcript` and `read_turns`
   become wrappers over them. The existing shared cases pass unchanged. New
   cases fold every fixture transcript up to each record boundary, finish it,
   go on to the end, and compare the result with the whole fold, field for
   field. The open-line undo gets cases of its own: a half-written last
   line, finished, then the line completed.

   **Status 2026-10-20: done.** As built:
   - Two folds, not one: `TranscriptFold` and `TurnsFold` (`TranscriptFold`
     and `TurnsFold` in the Python too), each with its own `pending`,
     `wrote` and `ends`. The two request-id sets are not the one set the
     table above names: the status line's dedupe keys a missing id as `"?"`
     and counts records before the first prompt, and the turns' does
     neither, so one set would move a figure. Two folds also keep the
     Python's `read_transcript` from paying for the turns, and the reverse.
   - The functions are `foldTranscript` / `transcriptFinish` and
     `foldTurns` / `turnsFinish` (`fold_transcript`, `transcript_finish`,
     `fold_turns`, `turns_finish`), with `foldTranscriptAll` and
     `foldTurnsAll` for a list. `transcriptOf`, `turnsOf`,
     `read_transcript` and `read_turns` are wrappers, and every shared case
     and golden passes unchanged.
   - `byPid` maps to a turn's index, so the finish can file the agents
     under copies of the turns. The open turn is always the last.
   - The open line is folded on a copy (`transcriptFoldWith`,
     `turnsFoldWith`, and `copy.deepcopy` in the Python), not undone: the
     copy is the whole state, but only while a last line has no newline.
   - The cases are `mod/test/main_fold.test.ts` and a new suite,
     `tests/fold.py`: every fixture finished at every record boundary and
     folded on, and cut inside each line and just before its newline,
     finished, and completed. The Python's `_records` also yields records
     that are not objects, which its readers raise on; the suite hands the
     folds only objects, as the TypeScript's `_recordsOf` keeps them.
   - The Python is no slower: on the 206 MB transcript, `read_transcript`
     went from 1.8s to 1.4s and `read_turns` from 1.2s to 1.3s.
3. **The real-transcript check.** `mod/tools/check-fold.ts` and
   `tests/fold_real.py` walk `~/.claude/projects/**/*.jsonl` (4,484 files
   here), not in CI, since they are private. For each file they compare the
   whole fold with folds broken at a seeded set of points: record
   boundaries, mid-line, and either side of every compaction. They also
   report the saved state's size, and that size replaces the estimate above.
   Each later step reruns them before it lands.

   **Status 2026-10-20: done.** As built:
   - `tests/fold_real.py` and `mod/tools/check-fold.ts`, run together by
     `check-folds` in the dev shell, with `--largest N`, `--seed S` and
     transcripts by name. The breaks are three seeded record boundaries,
     either side of every compaction, and one cut inside a line, folded on
     a copy and then completed. The finishes take no agents: the agents
     never reach the fold.
   - First run, every file under `~/.claude/projects` (4,495, the agents'
     included, 10.1 GB): none broke, in either port. The Python took 173s
     and the TypeScript 109s.
   - There is no saved state yet to measure, so the size is reported from
     step 4 on, which saves it.
4. **The state saved as text,** in both ports: the log, the head and its
   cap. Shared cases round-trip each fixture's state at each break point
   across the ports. The Python writes and the TypeScript reads on, then the
   other way, and both must give the same text. `tests/fixtures/state/` and
   the format check from "Keeping the format honest" land here.

   **Status 2026-10-20: done.** As built:
   - **`$.fs.write` can tear.** Claude Code 2.1.304's `write` makes the
     directory, then calls `fs/promises.writeFile(path, text, "utf8")`,
     which truncates and then writes. A Node loop rewriting a 3 MB file
     while another read it saw 1,820 torn reads out of 2,500 (0, 8,192,
     65,536, 524,288 bytes...). So the head alternates between two slots,
     `head-a.cache` and `head-b.cache`, each with a `seq`. A reader tries
     the higher `seq` first and falls back to the other slot. A part
     rewritten mid-read leaves a head whose counts it cannot meet, which
     also falls back to the other slot, and then to a fold from the start.
   - `mod/src/main_fold.ts` and `coding_agent_usage_line/main_fold.py`
     write the same bytes. The Python writes numbers as `JSON.stringify`
     does (`js_num`), and escapes lone surrogates as it does; reading back,
     it makes float fields floats and tuples tuples again. Entries are
     arrays tagged by one letter: `r w e s t b p` for the status line's
     fold and `S W E P T` for the turns'. Parts are counted in UTF-8 bytes,
     at most `part_bytes` (1,000,000) each, so both ports split them alike.
   - `spec/state.jsonc`'s `main-fold` row has format 1, `part_bytes` and
     `check_bytes` (4,096). The files go in one directory,
     `claude-main-fold-<sha(format\0path)>/`, which holds `head-a.cache`,
     `head-b.cache` and `part-N.cache`: the contract's `statePath`, not the
     `claude-main-fold/<sha(path)>/` the table above sketched.
   - `tests/fixtures/state/` holds each of 40 fixture transcripts' saves,
     written by `tests/fixtures/gen/state.py`. `tests/fold.py` and
     `mod/test/main_fold.test.ts` check:
     - each fixture saves as its text there, unless the format moved;
     - the text read back at every line end reads on to that text, in
       parts of 300 bytes too;
     - the Python's state at every line end is the TypeScript's byte for
       byte, and reads on in the TypeScript; the TypeScript's reads on in
       the Python (`python3 -m coding_agent_usage_line.main_fold every` and
       `readon`);
     - saves as the fold grows, as the mod makes them, and the slot before
       a torn head.
   - `check-folds` now also saves the fold as text at each break, reads it
     back and reads on. Measured, both ports alike:

     | Transcript | Records | Parts | Parts' bytes | Head |
     |---|---|---|---|---|
     | 221 MB | 24,962 | 2 | 1.21 MB | 3.2 KB |
     | 206 MB | 75,365 | 4 | 3.78 MB | 6.1 KB |
     | 165 MB (this repo) | 30,953 | 1 | 0.99 MB | 21.5 KB |
     | 156 MB | 72,908 | 7 | 6.78 MB | 8.6 KB |

     The estimate was low: the closed turns are 5.1 MB of the 156 MB
     transcript's 6.8, since each keeps its parts, tools and waits.
5. **The mod folds as it reads.** `recordsOf` becomes `foldOf`. It keeps the
   state in memory between documents and folds only the lines after its
   offset. `statusDoc` and `turnsNow` call the finishes. With nothing saved
   yet, this already ends the per-document refold. The state is saved under
   the contract at most once per `CONFIG.foldSaveMs`, and a reload reads on
   from it once the checks in "What invalidates a saved state" pass. The
   saved cut is still read when there is no state, so the first reload after
   upgrading folds the cut and not the transcript.

   **Status 2026-10-20: done.** As built:
   - `foldOf` in `mod/hooks/edges.ts` keeps the folds, their offset and
     the last save's mark per transcript. It folds the whole lines past
     the offset, through `agent_lines.py`'s main mode for a megabyte or
     more, else from the bytes, and folds a half-written last line on a
     copy (`transcriptFoldWith`, `turnsFoldWith`). `statusDoc` and
     `turnsNow` call `transcriptFinish` and `turnsFinish`.
   - A reload reads both head slots, newest `seq` first. It takes the first
     whose offset is within the file, whose two digests match, and whose
     parts read whole. Else it folds the saved cut, else the transcript.
     The cut is read but no longer written.
   - A save writes the new parts, then the head. A save that starts over
     (no mark: a fresh fold, or a save that failed) first empties both
     head slots, so an older head never reads parts it was not written
     beside. A head over its cap is logged once and not saved.
   - `readRange` takes the file's size: a small range of a file over
     4 MiB went to `$.fs.read`, which refuses it. The window costs' tail
     digest had the same fault and now passes the size too.
   - Two harness tests in `mod/mod-tests/band.test.ts`. A fold planted
     empty at the halfway line is read on from: the document is the second
     half's. A fold planted against other bytes is passed over, the
     transcript folded whole, and saved over.
   - Measured in Node, over the whole of each transcript:

     | Transcript | `sum` before | `turns` before | Load | `sum` after | `turns` after |
     |---|---|---|---|---|---|
     | 165 MB (this repo) | 168 ms | 78 ms | 7 ms | 1.0 ms | 0.7 ms |
     | 206 MB | 503 ms | 252 ms | 38 ms | 3.2 ms | 2.9 ms |
     | 156 MB | 442 ms | 238 ms | 46 ms | 1.5 ms | 3.3 ms |

     Before, every document paid `sum` and `turns` over all records, not
     only the first after a reload. In the mod's runtime the log showed
     `sum 1080, turns 962` (2,421 ms in all) for the first read after a
     reload of the 165 MB session. A live reload's own numbers are still
     to be read from `usage-band.log`. It logs only reads over the slow
     threshold, and a read from a saved fold should no longer be one.
6. **The cold read folds in Python.** `agent_lines.py`'s `main` mode becomes
   a `fold` mode. It loads the saved state, folds the transcript from its
   offset to the end, writes the parts and the head itself with
   `os.replace`, and prints the new offset. The mod then reads the head and
   the new parts through `$.fs`. No more cut records pass through the
   process's 4 MiB of output, and the worker parses no record it did not
   need. Python 3.9 and the standard library are enough: `json`, `hashlib`
   and `os`.

   **Status 2026-10-20: done.** As built:
   - The mode is `agent_lines.py fold PATH END DIR`. It imports the
     repository's package from beside `mod/` and calls
     `main_fold.fold_on`, which does the work and prints the offset it
     saved to. The `main` mode stays, as the fallback, until step 7.
   - `fold_on` reads a head only where the transcript still holds the bytes
     it was folded from (`load` takes a `fits` check). It folds a line at a
     time, so it holds only the fold. It saves in `fold_writes` order:
     both heads emptied on a start-over, then the parts, then the head,
     each through `os.replace`. The mod's `saveMainFold` writes
     `foldWrites`, the same list. With nothing new, or a head over its cap,
     it writes nothing.
   - `foldOf` runs the worker on a reload where the newest head is a
     megabyte or more behind, or there is none, and then reads the state
     once. A megabyte or more appended to a fold already in memory is saved
     at once, folded on by the worker, and read back whole. Where Python
     fails, the failure is logged once and the main mode reads the records,
     as before. A copy of `mod/` on its own (a GitHub install, a dev mod)
     has no package, so it always takes that path. The slow-read log line
     names the step `worker`.
   - Cases: `mod/test/main_fold.test.ts` runs the worker on every fixture,
     from nothing, from a state the mod saved at the first line, halfway
     and at the end, and from a state of other bytes. In each case the
     directory must equal, file for file and byte for byte, what `foldOf`
     writes. `tests/fold.py` also runs the worker under `/usr/bin/python3`
     (3.9.6). `band.test.ts` checks that a reload reads on from the state
     the worker saved, with no main mode run. `tests/fold_real.py` checks
     the worker on real transcripts and prints its time. On the 40 largest
     here, nothing broke.
   - `fold_save` joins each part's lines once, where it had added them one
     at a time (0.85 s of the worker's 4.3 s on the 206 MB transcript). A
     line with no `\r` skips the newline split (1.0 s). The bytes written
     are unchanged.
   - Measured under `/usr/bin/python3` 3.9.6, the worker from nothing, and
     Node's `foldLoad` of what it wrote:

     | Transcript | Worker | Peak RSS | Load in Node |
     |---|---|---|---|
     | 221 MB | 1.2 s | 74 MB | 11 ms |
     | 206 MB | 2.5 s | 88 MB | 39 ms |
     | 166 MB (this repo) | 1.5 s | 47 MB | 7 ms |
     | 156 MB | 2.3 s | 105 MB | 36 ms |

     Reading on 3 MB from a saved state took 0.12 s, and a run with
     nothing new took 0.17 s. Before this, the first read after a reload
     with no state took 2,548 ms in the mod's runtime (`fold 1298, load
     1821, records 1964`), all of it in the hooks worker. Its own time
     after a live reload is still to be read from `usage-band.log`.
7. **The cut, dropped.** Once the folds read the state, nothing reads
   records: `recordsOf` had two callers, and both use the finishes now. Remove
   the `MainCut` code, `MAIN_CUT_VERSION`, `savedCut` and `saveCut`, and the
   part of `main` mode that wrote records. `claude-main-cuts-mod/` is deleted
   on the mod's first run (20 MB for this session alone).

   **Status 2026-10-20: done.** As built:
   - The cut's code is gone from `claude_records.ts` and `edges.ts`
     (`MAIN_CUT_VERSION`, `MAIN_CUT_PART`, `mainCut*`, `cutPath`,
     `savedCut`), and so is `agent_lines.py`'s `main` mode with
     `mainLines`, its caller. A reload with no saved fold starts from
     nothing.
   - **The fallback where the worker cannot run** is the mod folding the
     bytes itself, `FOLD_PIECE` (8 MiB) at a time, so no more than a piece
     is held at once: reading the rest in one piece is what crashed the
     hooks worker at 157 MB. A copy of `mod/` on its own (a GitHub install,
     a dev mod) has no package beside the worker, which then exits 1
     naming that and writes nothing. Vendoring the package into `mod/` was
     passed over: the worker needs `main_fold`, `claude_records`,
     `formatting`, `state` and the specs, about 6,000 lines that would need
     a generator and a staleness check, and it would still leave a mod
     with no `python3` without a sound path. The bytes cost the fallback
     only once a transcript, since the fold is saved after: Node folds the
     221 MB transcript in 8 MiB pieces in 0.8 s at 212 MB peak RSS, before
     the shell's reads and base64.
   - `dropCuts` (`edges.ts`) removes `claude-main-cuts-mod/` on a load's
     first read, as the calibration sweep does: `$.fs` removes nothing, so
     `/bin/rm -f --` is handed only the names a cut was saved under (a
     32-hex directory's `head.json` and `part-N.jsonl`), then `/bin/rmdir
     --` each directory and the top, which leaves one holding anything
     else.
   - Cases: `main_fold.test.ts` runs the worker copied alone into an
     empty tree; `band.test.ts` folds a 17 MiB transcript with the worker
     failing, checks the reads restart at line ends and the saved fold is
     the whole one, and checks the `rm` and `rmdir` argv over a planted
     cuts directory with a stray file in it.
   - To check live: `/reload-plugins` in a session with a cut leaves no
     `claude-main-cuts-mod/` in the state directory, and a dev-mod copy
     logs `fold worker: python3 exited 1` once, then draws.
8. **The panel on the agent folds.** The agent fold grows to hold what
   `read_agent_usage` needs as well as what `foldAgentRecord` keeps now:
   compactions, the last stamp, the API-error flag, the cwd, the block
   count, the background map, the model and the effort. It moves under the
   contract, and the Python panel loads it, folds the new lines and saves it
   back. A panel tick then reads only what was written since the last tick,
   and the mod and the panel share one file per agent. The inbox's sends and
   deliveries join the folds, the main fold's and each agent's, so
   `inbox_counts` stops scanning the main transcript from the start on each
   tick. The agent-files caches of both ports are replaced and removed.

   **Status 2026-10-20: done,** but for the inbox, which is `RT8i`. As
   built:
   - `spec/state.jsonc`'s `agent-fold` row, format 1, `check_bytes` 4,096:
     one directory per session,
     `claude-agent-fold-<sha(format\0transcript)>/`, and in it one fold per
     agent file, `<sha256(path)>-a.cache` and `-b.cache`, not the
     `<sha(path)>.cache` the table above sketched. `$.fs.write` can tear,
     so a fold is written whole to the two slots in turn, as the main
     fold's head is: its text starts `{"format":1,"seq":N,`, a reader tries
     the higher `seq` first and falls back to the other slot, and a fold
     started over saves after the highest `seq` either slot holds. A fold
     names `pos`, the offset folded to, and `tail`, the sha256 of the 4 KiB
     before it. It is read on from only while both still fit the file, so
     a file rewritten in place, even to the same size, is folded afresh.
   - The fold is `AgentFold` in both ports (`claude_records.{py,ts}`), as
     before, plus the compactions, the last stamp, the API-error flag, the
     cwd, the block count, the background tasks and the effort of the last
     request it bills (first wins, as `_dedupe_usage` keeps; the request
     ids for that are rebuilt on a load, not saved). Its text is
     `agent_fold.fold_text` and `agentFoldText` (`agent_fold.{py,ts}`,
     new): one JSON object, every set and map a list in insertion order.
   - The panel: `prepare_subagent_tasks` reads each agent through
     `agent_fold.fold_file` and finishes it with `agent_usage_of`.
     `read_agent_usage(path)` is that finish over a whole fold. The
     Python's `_agent_file_readings`, the Node port's `_agentFileReadings`
     (its `cache` argument is now a state directory) and the mod's
     `agentReadings` read on from the same files, so the panel, the Stop
     hook and the mod share one fold per agent. The Python saves on every
     read that folded anything, through `os.replace`. The mod saves at most
     once per `CONFIG.foldSaveMs`, with the tail taken from the bytes it
     read. A last line with no newline is folded on a copy and not saved.
   - Removed: `claude-agent-files-<h>.cache` and `-ts-<h>.cache`, with
     `_agent_cache_version`'s source-digest key and the two-second settle
     rule, by the Python once (marker `claude-agent-files-old-removed`);
     and the mod's `claude-agent-folds-mod/`, by the mod on a load's first
     read, through `rm` and `rmdir` on the names it wrote (`dropOldDir`,
     which `dropCuts` now calls too).
   - Swept: the daily calibration sweep, in both ports, also removes a
     `claude-agent-fold-` or `claude-main-fold-` directory none of whose
     files was written for eight days: the names a fold writes, then the
     directory (`_sweep_fold_dir`, `staleFoldFiles`).
   - Cases: `tests/fixtures/agent-state/` holds the text of each of 37
     fixture agents' folds at every line end, written by
     `tests/fixtures/gen/state.py`. `tests/fold.py` and
     `mod/test/agent_fold.test.ts` hold each port to it byte for byte, and
     read each text back on to the last, whose panel reading must be the
     whole file's. `agent_fold.test.ts` also hands a fold from the Python
     to the Node port and back through one state directory. `band.test.ts`
     plants a fold halfway, a torn newer slot and a fold of other bytes,
     and checks the slot the mod writes, and the old directory's removal.
     `tests/agents.py` checks the slots, a read on, and a same-size
     rewrite read afresh.
   - Measured by `time-panel` (new, in the dev shell): the panel's read,
     `prepare_subagent_tasks`, with every agent of a session as a task,
     against a scratch state directory. "The rest" is the tick less
     `inbox_counts`, which `RT8i` moves:

     | Session | Agents | Their files | Tick before | After, warm | The rest before | After, warm | Cold, after |
     |---|---|---|---|---|---|---|---|
     | most agents here | 1,662 | 137 MB | 1,100–1,160 ms | 500–540 ms | 1,000–1,065 ms | 410–460 ms | 2.1 s |
     | this repo's | 82 | 214 MB | 2,000–2,060 ms | 390–410 ms | 1,590–1,640 ms | 34–35 ms | 2.0 s |

     Before, every tick read every agent file whole. The cold tick is that
     read once, and saves 1.3 to 1.7 MB of folds. What is left of a warm
     tick with 1,662 agents is opening two slots and 4 KiB of each file,
     the sidecars and the git checks: about 0.25 ms an agent.
9. **The window costs, one file.** The three copies become one under the
   contract. It is keyed by the format, no longer by `_source_digest` or
   `CONFIG.version`, and written by whichever port scans.

   **Status 2026-10-20: done.** As built:
   - `spec/state.jsonc`'s `window-costs` row has no key parts, so the file
     is `claude-window-costs-<sha256("1")>.cache`, one for the machine, not
     the `claude-window-costs.cache` the table above names. Its text is
     `{"files":{<path>:{"off":…,"recs":[[epoch,id,usd],…],"tail":…}}}`:
     compact, every object's keys sorted, and every number in a record a
     float (`window_costs_text`, `_windowCostsText`). Sorted keys make the
     bytes the same whatever order each port listed the files in.
   - Both write through a rename. The Python writes a temporary file and
     calls `os.replace`, as before; the Node port uses `writeAtomic`. The
     mod pipes the text to `/bin/sh` on stdin, `cat` to `<path>.$$`, then
     `mv -f` (`writeAtomicVia`), which also lifts `$.fs.write`'s 4 MiB cap.
     It reads the file through `readRange`, in pieces past 4 MiB.
   - `_source_digest` is gone. The format is now bumped by hand, and
     `tests/fixtures/calib/costs-format.json` holds it honest: it pins the
     corpus scan's text under the format it was written with, and
     `gen/calib.py` refuses to write a moved text under the same format,
     as `claude_calib.test.ts` checks the TypeScript's.
   - `tests/fixtures/calib/scan.json` now pins each step's scan cache as
     its text, which the TypeScript must write byte for byte. A new
     `shared` scenario plants a cache billing ten times over (the other
     port's, read as its own), one torn in half and an empty one, which
     each port must read as none and write whole again.
   - Old files: the Python lists the state directory once and removes
     `claude-window-costs.cache`, `-ts.cache`, `-mod.cache` and the
     `claude-window-costs.cache.<pid>` files killed saves left (35 here,
     up to 4 MB each), then writes `claude-window-costs-old-removed`. The
     mod does the same once a load, with `/bin/rm -f --` on the exact
     names `oldWindowCosts` matched, by the same marker. As with step 1, a
     mod still running the old code writes `-mod.cache` after the marker;
     removing the marker once every session's mod is refreshed sweeps it.
   - `tests/claude-sources.py` ran one `calibration()` against the real
     state directory, which the old-file removals then listed. It now
     runs in a scratch one. The daily sweep
     also removes a `claude-window-costs-<hex>.cache` (a past format's)
     or its temporary file untouched for eight days.
   - A harness test in `band.test.ts` starts a scan with no calibration
     planted, and checks the mod wrote the shared file through the shell,
     in `_windowCostsText`'s bytes.
   - Measured by `time-window-costs` (new, in the dev shell) over this
     machine's `~/.claude/projects`, a week's window, into a scratch state
     directory:

     | Port | Cold scan before | after | Cache hit before | after | Cache |
     |---|---|---|---|---|---|
     | Python | 22.2 s | 19.5 s | 74–172 ms | 72–106 ms | 1.94 MB |
     | Node | 114 s | 112 s | 233–479 ms | 240–326 ms | 1.95 MB |

     The scans cost what they did: the change is where the cache lives,
     not how it is read. What it buys is the second port's cold scan. Each
     port used to pay its own, on every upgrade for the Python and every
     version for the mod; now whichever scans first warms the file for the
     other, and only a format bump starts it cold.

Steps 1, 2 and 3 are independent of one another. Steps 4 to 7 must land in
order. Step 8 needs the contract from step 1 and the text form from step 4.
Step 9 needs only step 1.

## Decided (2026-10-20)

1. **The old calibration files go.** Step 1 deletes the
   `claude-calibration-*.json` files and the `-ts-` ones on its first run.
2. **The state table** is a sibling `spec/state.jsonc`, generated by
   `tools/gen-spec.py` beside `spec/layout.jsonc`.
3. **One format number per cache kind.**
4. **`$.fs.write`'s atomicity is tested first;** alternating `head-a` and
   `head-b` slots go in only if a write can tear.
5. **The panel's inbox moves to the folds in a commit of its own,** after
   step 8.
