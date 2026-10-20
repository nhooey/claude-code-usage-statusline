# Configuration: one set of options, merged from files and flags

Being built: steps 1 to 6 are done (each has its Status), so both ports
read the files and draw from them; steps 7 and 8 are the user's, by hand.
[Options](../../docs/options.md) is the reference for the flags and the
files. This document collects the design as it is decided.

## Why

The usage line has two ports, and each takes its settings its own way:

- **The Python package**, `coding_agent_usage_line/`, takes flags on its
  command line, which lives in `~/.claude/settings.json` as the
  `subagentStatusLine` command (and in Codex's hook commands). One command
  serves every project, so a setting cannot differ between projects.
- **The mod**, `mod/`, takes a TypeScript object, `CONFIG` in
  `mod/hooks/config.ts`, read once at module load. A change is an edit to the
  mod's source and a `/reload-plugins`, and it applies to every project too.

Some settings have to agree between the two, and today only comments keep
them in step: `CONFIG.hide` says "keep subagentStatusLine's --hide flags the
same, so the panel stacks", and `CONFIG.bandPlace` says to keep the panel's
`--right-edge` at 0 or 5 to match it. Two copies of one value drift.

The first setting that has to differ by project is where and when each
row appears: the 🎤, 🤖 and 🎮 rows kept under the footer line between turns
and stamped into the transcript too, here only (asked 2026-10-20). Neither
port can say that today; see [The rows table](#the-rows-table).

## The design

### Precedence

Decided 2026-10-20, by the user: a setting is taken from the first layer that
has it, highest first.

| Layer | Where | Python | Mod |
|---|---|---|---|
| command-line flags | the hook command in `settings.json` | yes | none: the mod has no command line |
| project config | the project's files, see [Files](#files) | yes | yes |
| user-global config | one file per user | yes | yes |
| built-in defaults | the options spec | yes | yes |

The mod has no flags layer, so for it a project file is the highest. A flag
the panel's command gives therefore beats a project file for the panel but
not for the band; see [Decided](#decided-2026-10-20), 1, for the flags
that must agree.

### One options spec, generated into both ports

The options are written once, in `spec/options.jsonc`, the way the layout's
constants are written in `spec/layout.jsonc`. `tools/gen-spec.py` writes it
out beside the layout, comments and all:

- `coding_agent_usage_line/options_spec.py`, a tuple of option records;
- `mod/src/options_spec.ts`, the same records, `as const`, with a generated
  `Options` type;
- the option tables of `docs/options.md`, between
  `<!-- options:begin -->` and `<!-- options:end -->` markers, so the prose
  around them stays hand-written.

`python3 tools/gen-spec.py --check` fails while any of the three is out of
date, as it does for the layout today, so `tests/formatting.py` and CI catch
a hand edit.

Each option is one member:

```jsonc
"live-place": {
  "type": "enum",            // bool | int | string | enum | list | table
  "items": ["footer", "above"],   // enum values, or a list's
  "default": "footer",
  "ports": ["mod"],          // which ports read it: "py", "mod" or both
  "file": true,              // settable in a config file
  "flag": null,              // the CLI flag, or null for none
  // Where the mod draws its live rows: under Claude Code's footer line,
  // or above the prompt.
  "doc": "..."
}
```

The rules the records carry:

- **One name.** A file key is the long flag's name without its `--`:
  `usage-source`, `mark-spacing`, `hide`, `right-edge`. An option with no
  flag (`rows`, `live-place`) takes a name of the same shape. The doc
  table, the file and the flag then use one spelling, and the generated
  TypeScript accessor gives it in camel case (`options.usageSource`).
- **Booleans.** One option per switch, its positive name, with
  `"negatable": true` writing both `--mark-spacing` and `--no-mark-spacing`.
  Today's `--no-totals`, `--no-right-align`, `--no-account-totals`,
  `--no-datetime` and `--no-usage-text` become `totals`, `right-align`,
  `account-totals`, `datetime` and `usage-text`, default `true`, and their
  flags keep working; the positive flags are new.
- **Per run, not config.** `--agent`, `--mode`, `--transcript`,
  `--from-figures`, `--all`, `--diagnose`, `--cols`, `--selftest` and
  `--help` describe one run, not a preference: their records say
  `"file": false`, and a config file that sets one is warned about (see
  [Bad values](#unknown-keys-and-bad-values)).
- **Agents.** `"agents": ["claude"]` on the Claude-only flags keeps today's
  rule that `--agent codex` rejects them, which `_CLAUDE_FLAGS` in `cli.py`
  hand-lists now.

The spec holds the flag parser's table too, so `_VALUE_FLAGS`,
`_COMMON_FLAGS` and `_CLAUDE_FLAGS` in `cli.py` and the `USAGE` text are
generated or built from it, and a new option is one member in one file.

### Files

JSON, with `//` line comments allowed (JSONC). TOML would read better, but
`tomllib` arrived in Python 3.11 and the floor is 3.9; YAML has no stdlib
reader in either. The comment stripper is a dozen lines in each port, a
string-aware scan that blanks `//` to the end of the line outside strings,
and its shared cases pin the two to one answer. A file is an object of
`name: value`; a top-level `"version": 1` is reserved for a later change of
shape.

| Layer | Path | Committed |
|---|---|---|
| user-global | `$XDG_CONFIG_HOME/coding-agent-usage-line/config.jsonc`, else `~/.config/coding-agent-usage-line/config.jsonc` | n/a |
| project | `<root>/.config/coding-agent-usage-line/config.jsonc` | yes: what the project wants for everyone |
| project, local | `<root>/.config/coding-agent-usage-line/config.local.jsonc` | no: one person's, ignored by `/.config/**/*.local.*` |

The local file sits above the committed one within the project layer, as
Claude Code's own `.claude/settings.local.json` sits above
`.claude/settings.json`. `CODING_AGENT_USAGE_LINE_CONFIG_DIR` overrides the
user-global directory, for the tests, as `CODING_AGENT_USAGE_LINE_STATE_DIR`
does for state.

**Finding the root.** Each port starts from the session's directory and walks
up, looking in each directory for either project file, and stops at the first
directory that has a `.git` (a directory, or the file a worktree has), at
`$HOME`, or at `/`. The first directory with a project file is the root;
with none, there is no project layer. The walk is file tests only, no `git`
process: the mod would otherwise spawn one per read, and the Python already
pays for `git` in the status line.

| Reader | Starts from |
|---|---|
| the mod | `$.session.root()`: where the session started, or where `/cd` or a worktree move took it; a shell `cd` does not move it |
| the panel (`--mode subagent`) | the payload's `cwd` |
| the status line (`--mode status`) | the payload's `workspace.project_dir`, else `cwd` |
| the Stop hook (`--mode cost`) | the payload's `cwd` |
| Codex | the payload's `cwd`, else the rollout's |
| `--transcript` by hand | the process's working directory |

The band and the panel start from different fields, but within one checkout
both walks stop at the same `.git`, so they find the same files. A worktree
is its own checkout: it sees the committed file, which it checks out, but
not the main checkout's local file, so it reads that one when it has none
of its own; see [Decided](#decided-2026-10-20), 6.

**Reading them in the mod.** Through `$.fs`, with no Node: `$.fs.stat` for
each candidate path in the walk, `$.fs.read` for the ones found. A config
file is a few hundred bytes, far under `$.fs.read`'s 4 MiB, and a file over
64 KiB is refused with a warning rather than read. `HOME` and
`XDG_CONFIG_HOME` come from `$.env.get`, as `edges.ts` reads `HOME` today;
`claude plugin validate` lists the names the module reads, so the new
`CODING_AGENT_USAGE_LINE_CONFIG_DIR` joins them.

**Reading them in Python.** The stdlib only: `os.path.isfile`, `open`,
`json.loads` after the comment strip, in a new module,
`coding_agent_usage_line/config.py`, that imports nothing else of the
package but `options_spec`. Each run reads afresh: the panel runs every few
seconds and each run is one process, so there is nothing to cache, and the
cost is a handful of `stat` calls and two small reads.

### The rows table

Each row the mod can draw is set on its own, by when the mod draws it and
whether a turn's end stamps it into the transcript (decided 2026-10-20).
Where the live rows go is `live-place`, one setting for all of them.

```jsonc
{
  "live-place": "footer",            // "footer" | "above"
  "rows": {
    //   live:       "never"   — the mod never draws it
    //               "running" — drawn while a turn runs, gone at its end
    //               "always"  — drawn while a turn runs, and kept after
    //   transcript: stamped into the transcript when the turn ends
    "turn":    { "live": "running", "transcript": true  },
    "agent":   { "live": "always", "transcript": false },
    "session": { "live": "always", "transcript": false },
    // The 🔻🔖 line under the prompt and the receipt's 🔺🔖 line.
    "tag":     { "live": "never",  "transcript": true  },
    // The 💳 account row; `transcript` is always false for it.
    "account": { "live": "always", "transcript": false }
  }
}
```

Those are the defaults. `live` is one enum, not two booleans, so "drawn
after the turn but not during it" cannot be written. A row that is
`"never"` and `false` is not drawn at all, which retires the hide paths
that drop a whole row (`turn`, `agent`, `session` as scopes, `name.tag`
and `account.*`'s row as a whole); `hide` keeps its other job, hiding
cells. Keeping a row live and stamping it are independent: a row can
stay under the footer line and still leave each turn's figures in the
transcript.

| `live` | `transcript` | The row |
|---|---|---|
| `"running"` | `true` | live while the turn runs, then moved into the transcript |
| `"always"` | `false` | kept live, never stamped |
| `"always"` | `true` | kept live, and each turn leaves a copy in the transcript |
| `"running"` | `false` | live while the turn runs, leaving nothing behind |
| `"never"` | `true` | in the transcript only, as a receipt |
| `"never"` | `false` | not drawn anywhere |

### Merge semantics

- **Scalars** take the highest layer's value.
- **Lists replace.** A layer that sets `hide` sets the whole list, so the
  project's `"hide": []` means none, whatever the user file says. Appending reads well for `hide` but leaves no way to take a path
  back out, and a list that is the union of three files is hard to see
  whole. A repeated flag (`--hide a --hide b`) makes one list, which then
  replaces the files' as any flag does.
- **The merge is per option**, never per file: a project file that sets
  only `rows` leaves every other option to the layers under it.
- **Tables merge per field.** `rows` is a table of records, and a layer
  that sets `rows.agent.transcript` leaves `rows.agent.live` and every
  other row to the layers under it, so a project says only what differs.
- **Derived values are worked out after the merge.** `right-edge`, unset in
  every layer, follows `live-place` (2 for `"footer"`, 5 for `"above"`, as
  `BAND_EDGE` does today), so one setting moves the band and the panel
  together.

`coding-agent-usage-line.py --show-config` prints the merged options, each
with the layer it came from and that layer's path, and exits; the mod logs
the same table to its log on each read that changes it. That answers "why is
it drawing this" without reading three files by hand.

### Unknown keys and bad values

A config file is read in a hook, and a hook never breaks a session, so
nothing in a file stops a port from drawing. What goes wrong is skipped, at
the smallest unit that can be, and said where the person will see it:

| What | Effect |
|---|---|
| a file that is not valid JSON(C) or not an object | the whole file is skipped |
| an unknown key | skipped; the warning names the nearest known key, so `rwos` says `rows` |
| a key the spec knows but says `"file": false` (`mode`, `cols`) | skipped |
| a value of the wrong type, out of range, or not among the enum's | that key is skipped, and the layer under it supplies the value |
| a list with one bad item | the whole list is skipped, not the item: half a `hide` list draws something nobody asked for |
| a key for the other port only (`rows` in the Python) | no warning: the spec knows it |

A bad flag stays an error, exit 2, as today: a flag is typed in a command
and checked before stdin is read.

Where the warnings go:

- **Python:** stderr, one line per problem, prefixed with the file's path.
  The panel's stdout is task rows only and the Stop hook's is one JSON
  object, so nothing goes there. `--diagnose` adds them to its line, and
  `--show-config` lists them under the table.
- **Mod:** its log (`log.ts`), every time, and a `$.ui.notice` once per file
  and modification time, so a typo is seen the first time and not every
  tick. Not a toast: `slowToast` showed that a toast takes the footer line
  and hides the 💳 row (seen live 2026-10-20).

### When the mod reads its configuration

Today `CONFIG` is a module constant, read at load. It becomes a value the
handlers read through one function, `options()`, kept in module state with
the files' modification times, and read again:

- **at load**, as now, and on each `/reload-plugins`;
- **on `session.start`**, since a new session may be in another project;
- **on the idle tick** (`tickMs`, 30 s): one `$.fs.stat` per file found, and
  a read of any whose `mtimeMs` changed. The engine has no file-watch event
  for a mod (the `FileChanged` hook is a shell hook's), and a stat every
  30 s is free next to the transcript reads the tick does anyway;
- **when the root moves**: `$.session.root()` is read on each tick, and a
  new root walks again.

An option that drawing reads (`hide`, `rows`, `live-place`,
`account-place`, `mark-spacing`) applies on the next draw: a changed config
writes `$.state`, as a new status document does, so the band redraws. The
timers' periods are constants (Decided 5 and 15), so no option restarts
one.

### What moves where

#### Every field of `CONFIG`

| `CONFIG` field | Option | Ports | Flag | Notes |
|---|---|---|---|---|
| `usageSource` | `usage-source` | both | `--usage-source` | the env var retires, see [Decided](#decided-2026-10-20), 2 |
| `account` | `account` | both | `--account` | |
| `period` | `account-period` | both | `--account-period` | renamed to the flag's name |
| `hide` | `hide` | both | `--hide`, repeatable | one list for the band and the panel; the comment telling the user to keep them in step goes |
| `sticky` | `rows.<row>.live` | mod | none | `"always"` for a row once sticky; see [The rows table](#the-rows-table) |
| `bandPlace` | `live-place` | mod, and the panel through `right-edge` | none | `"hint"` becomes `"footer"` |
| (`BAND_EDGE`) | `right-edge` | both | `--right-edge` | derived from `live-place` when unset |
| `accountPlace` | `account-place` | mod | none | where the 💳 row goes when `rows.account.live` draws it |
| `hintTuck` | `hint-tuck` | mod | none | |
| `hintInset` | `hint-inset` | mod | none | |
| `footerRuler` | `footer-ruler` | mod | none | a debugging aid; documented as such |
| `markSpacing` | `mark-spacing` | both | `--mark-spacing`, `--no-mark-spacing` | |
| `subscriptDecimals` | `subscript-decimals` | both | `--subscript-decimals` | gains `--no-subscript-decimals` |
| `version` | none | | | stays a constant in `config.ts`: it keys the caches, and a file must not change it |
| `agentLinesTimeoutMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `foldSaveMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `tickMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `tickRunningMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `readSpacing` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `slowReadMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `slowToast` | `slow-toast` | mod | none | |
| `slowToastMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `clockMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `startsKept` | `starts-kept` | mod | none | store size; minimum 1 |
| `receiptWaitMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `receiptPollMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |
| `receiptHoldMs` | none | | | a constant in `config.ts`, Decided 5 and 15 |

The timings stay constants beside `version` (Decided 5 and 15): tuning
values, not settings, so no file can set the mod spinning.

#### Every flag of `cli.py`

| Flag | Option | In a file | Notes |
|---|---|---|---|
| `--agent` | none | no | per run |
| `--mode` | none | no | per run |
| `--transcript` | none | no | per run |
| `--from-figures` | none | no | per run |
| `--all` | none | no | per run |
| `--diagnose` | none | no | per run |
| `--cols` | none | no | per run: the width is the terminal's, never a preference |
| `--selftest`, `-h`, `--help` | none | no | per run |
| `--usage-source` | `usage-source` | yes | |
| `--account` | `account` | yes | |
| `--account-period` | `account-period` | yes | enum `day`, `week`, `month` |
| `--hide` | `hide` | yes | |
| `--right-edge` | `right-edge` | yes | being added to the working tree now |
| `--color` | `color` | yes | cost mode |
| `--column-rules`, `--no-column-rules` | `column-rules` | yes | |
| `--no-totals` | `totals` | yes | default true |
| `--no-right-align` | `right-align` | yes | default true |
| `--no-account-totals` | `account-totals` | yes | default true |
| `--no-datetime` | `datetime` | yes | default true |
| `--no-usage-text` | `usage-text` | yes | default true |
| `--force-newline` | `force-newline` | yes | |
| `--mark-spacing`, `--no-mark-spacing` | `mark-spacing` | yes | |
| `--subscript-decimals` | `subscript-decimals` | yes | |
| `--prefix` | `prefix` | yes | |
| `--label` | `label` | yes | default depends on `usage-text`: the default is computed after the merge, as `right-edge`'s is |
| `--show-config` | none | no | new |

#### How the Python reads the merged options

The Claude adapter reads flags by membership over `argv`
(`_flag(argv, name)` and `"--no-totals" in argv`) in a few dozen places, and
`_flag` takes the first occurrence. Prepending the files' values to `argv` as
flags would therefore let a file beat a flag; appending them would let a
`--no-x` from a file beat a positive flag only where the code checks for the
negative. Neither is safe, so the reads move to one merged `Options` value:

1. `cli.main` parses `argv` against the spec, finds and merges the files,
   and builds `Options`, a frozen mapping of every option to its value and
   layer.
2. `claude.main` and `codex_main` take `Options` instead of `argv`; each
   `_flag(argv, "--x")` and `"--no-x" in argv` becomes `options["x"]`.
3. `_flag` and the forwarding loop in `cli.main` are deleted.

`CODING_AGENT_USAGE_LINE_USAGE_SOURCE` retires (see
[Decided](#decided-2026-10-20), 2): its five call sites read the merged
option instead.

### The engine's plugin options, considered

Claude Code has its own place for a plugin's settings: fields declared in the
manifest's `userConfig`, stored in `settings.json` under
`pluginConfigs[<plugin>].options`, handed to `register(on, options)`, and
drawn as rows of `/config`, which `$.config.set` changes. It was considered
for the mod and not taken:

- **The panel cannot share it.** The Python would have to find and parse
  Claude Code's settings files itself, with their own merge rules, and Codex
  has none; the two ports would again hold two copies of `hide`.
- **It is read at load.** `register` receives the options once; a change
  from `/config` still needs the module to reload or read them again
  through `$.config.list()`.
- **Project scope is unclear.** `pluginConfigs` lives in a settings file,
  and whether a project's `.claude/settings.local.json` entry overrides the
  user's for a plugin's options is the engine's rule, not ours, and is not
  stated in the types; it would need a live test.
- **The types are narrow.** A field is a string, number, boolean or list of
  strings, with `options` only on a string; `hide` fits, but the `rows`
  table and the derived `right-edge` do not.

What it would give is the `/config` menu. That can come later on top of this
design: the mod could declare a few `userConfig` fields and treat them as one
more layer, between the user file and the project files. Not in this plan.

## Tests

### Shared cases

`tests/fixtures/config/`, written by the Python side with `--regen` as the
other shared cases are, and run by both suites. Each case is a set of files
by layer (user, project, project local) with their text, a list of flags,
and the session directory the walk starts from, in a temporary tree; and the
merged options, each with its layer, and the warnings, as the expected
result. Together they cover:

- each precedence pair, flag over local over project over user over default;
- lists replacing, an empty list in a higher layer meaning none, and a
  repeated flag;
- the walk: a file two directories up, a `.git` between that stops it, a
  worktree's `.git` file, no file at all, `$HOME` reached;
- JSONC: `//` in a string kept, `//` after a value stripped, a trailing comma
  before `}` or `]` stripped, and one inside a string kept (Decided 14);
- every row of the bad-value table, and the nearest-key hint;
- the derived values: `right-edge` from `live-place`, `label` from
  `usage-text`.

### Python, `tests/`

- `tests/config.py`: runs the shared cases through `config.py`, and checks
  `--show-config`'s output and that a bad file still draws the panel's rows
  with the warning on stderr only.
- `tests/port-cli.py`: every existing flag still parses to the same
  behaviour, now through the spec; `--no-totals` on the command line and
  `"totals": false` in a file agree.
- `tests/py39-floor.sh` already runs the suites under 3.9, so `config.py`
  is held to the floor without a new check.
- `tools/gen-spec.py --check` covers `options_spec.py`, `options_spec.ts` and
  the doc tables.

### Mod, `mod/test/`

- `mod/test/config.test.ts`: the shared cases through `mod/src/config.ts`,
  the pure merge, with the walk run over a fake `$.fs` built from each
  case's files.
- `mod/test/options_spec.test.ts`: the generated `Options` type and records
  agree with `spec/options.jsonc` (as `spec.test.ts` does for the layout).
- `mod/mod-tests/band.test.ts`: the band's rows during and after a turn,
  and the receipt's, for each `live` and `transcript` value of each row, read through `options()`, and a config change on
  the tick redrawing the band without a reload.

## The build order

Each step is one commit and leaves both ports passing `bash tests/all.sh`
and `npm test`.

1. **The options spec, generated.** `spec/options.jsonc` with every option
   in the tables above; `tools/gen-spec.py` writes `options_spec.py`,
   `options_spec.ts` and the doc tables, with `--check`. Nothing reads them
   yet; `docs/options.md` gains its markers and the same tables it has now,
   generated.

   **Status 2026-10-20: done.** As built:
   - `spec/options.jsonc` is one `OPTIONS` object of 35 records, as
     `spec/state.jsonc` is one `STATE_KINDS`: 26 flags of `cli.py` (with
     `--selftest` and `--help`, `-h` as an alias) and 9 the mod alone reads,
     by the tables above, less the timings (Decided 5). `agentMessageRow`,
     newer than this plan, is `agent-message-row`; `agentListMs` and
     `agentSenderMemo` stay constants with the timings.
   - Every record has `type`, `default`, `ports`, `file`, `flag`,
     `doc-table` and `doc`, in that order, and as needed `items`, `fields`
     (a table's), `metavar`, `derived` (`{from, map}`), `minimum`,
     `agents`, `aliases`, `negatable`, `modes` and `doc-default`.
     `gen-spec.py` refuses a record out of that order or whose default
     does not fit its type. `doc` is written as lines and generated as one
     string; it is the doc table's Effect cell as it reads today, so the
     bools that default true describe their `--no-` flag.
   - The Python's is a dict by name, not a tuple, so a lookup is by name.
     The TypeScript is `as const`, with `Options` over the mod's options
     by camel-case name; `mod/test/options_spec.test.ts` fills it from the
     defaults, so the typecheck holds the two together.
   - The doc tables sit between `<!-- options:begin shared -->` and
     `<!-- options:end shared -->`, and the same for `display`; the
     options with no doc table, the mod's, wait for a section of their own.
   - The defaults are the built-in ones, not `CONFIG`'s: `usage-source`
     `auto` and `hide` empty, as the Python has them; the mod's
     `claude-usage-tracker` and hide list are the user's, for step 7.
     `right-edge` keeps the Python's `5` beside its derived map, which
     gives `2` under `live-place`'s default `footer`, so the panel's
     default moves when step 6 derives it.
2. **The Python parses flags from the spec.** `cli.py`'s flag sets and
   `USAGE` come from it; the positive spellings of the `--no-` flags are
   added. Behaviour is unchanged; `tests/port-cli.py` shows it.

   **Status 2026-10-20: done.** As built:
   - `cli.py` builds `_VALUE_FLAGS`, `_COMMON_FLAGS` and a set per agent
     (`_CLAUDE_FLAGS`, `_CODEX_FLAGS`) from the records with a flag and
     `"py"` in their ports: a flag, its `aliases`, and `--no-` for a
     `negatable` one; `agents` limits a flag to the agents it names. The
     sets are today's, with `--totals`, `--right-align`,
     `--account-totals`, `--datetime`, `--usage-text` and
     `--no-subscript-decimals` new for Claude.
   - Each record with a flag gains `usage`, its line of `--help`: short,
     plain ASCII, and `gen-spec.py` refuses one without the other. `USAGE`
     keeps its hand-written head, modes and Codex note, and builds its
     sections from the records: Shared and Claude display by `doc-table`,
     each display flag with its modes in brackets, and `--selftest` and
     `-h, --help` under Other. A negatable bool shows the spelling that
     changes something first, `--no-totals, --totals`.
   - The negative wins whichever comes first, as it did for
     `--column-rules` and `--mark-spacing`: `cli.main` drops a positive
     spelling from what it forwards when its negative is given, so the
     adapter, which reads some switches by one spelling and some by the
     other, sees one answer. Step 3's `Options` takes this rule over.
3. **The Python reads `Options`, not `argv`.** `claude.py` and the Codex
   path take the merged value, still built from flags and defaults alone;
   `_flag` goes. The goldens show nothing moved.

   **Status 2026-10-20: done.** As built:
   - `coding_agent_usage_line/options.py` holds `Options`, a frozen
     `Mapping` of every option with `"py"` in its ports, by its spec name,
     to its value; `options.layer(name)` gives the layer (`flag`, `env`
     or `default`) and `options.given(name)` whether one above the
     defaults gave it. Values are typed: an int for `cols` and
     `right-edge`, a tuple for `hide`, a bool for a switch.
   - `parse(argv, allowed)` turns the command line into (spelling, value)
     pairs, with `cli.py`'s old errors; `flag_values` folds them by the
     rules `cli.main` and `_flag` applied between them: a repeated `--hide`
     makes one list, a repeated value flag takes the last (`_flag` took
     the first, `cli._parse` the last; nothing passed one twice), and a
     `--no-` spelling wins whichever comes first. `merge` lays the flags
     over the defaults; CM4 adds the files' layers there.
   - `CODING_AGENT_USAGE_LINE_USAGE_SOURCE` is the `env` layer of
     `usage-source`, between the flags and the defaults, so its six call
     sites read `options["usage-source"]` and nothing moved; retiring it
     (Decided 2) is left to CM4, with the docs and the three tests that
     set it.
   - `cli.main` checks, builds `Options` once, and hands it to
     `claude.main` or `codex_main`; the forwarding loop and `_NEGATED` are
     gone. `--selftest` calls `claude.selftest()` directly.
   - In `claude.py`, `_flag` and `column_rules` are gone: 22 `_flag`
     calls and 19 `in argv` tests read `options[...]`. `label` keeps its
     default worked out in `_cost_opts` and `right-edge` is set only when
     given, so the derived values stay CM4's and CM6's (Decided 13).
   - `_flag` and `_costOpts(argv)` in `mod/src/claude_cost.ts`, the
     TypeScript mirror of the cost line that the shared cases drive with
     each case's flags, still read an argv; CM6 decides whether they take
     `options()` or stay a test's reading of a case's flags.
4. **The Python reads the files.** `config.py`: the walk, JSONC, the merge,
   the warnings, `--show-config`, `CODING_AGENT_USAGE_LINE_CONFIG_DIR`;
   `tests/config.py` and the shared cases.

   **Status 2026-10-20: done.** As built:
   - `config.py` finds the three files (`find`, the walk as above, with
     `$HOME` and `/` never looked in, so `$HOME/.config` is only ever the
     user file), reads each (`read`: JSONC, 64 KiB, `"version": 1`) and
     checks each key against the spec, keeping what passes; `load` gives
     the layers, highest first, and the warnings. `options.merge` lays
     them between the flags and the defaults, tables per field;
     `Options.field_layer` gives a field's layer and `Options.warnings`
     the files' warnings. The `env` layer is gone.
   - Decided 6's worktree: with no local file of its own, the main
     checkout's (from `.git`'s `gitdir:` and its `commondir`) at the
     same place under it; with no project file at all, the main
     checkout's local file is looked for from the start's mirror up.
     A submodule's `.git` has no `commondir`, so it has no main checkout.
   - `cli.main` now reads stdin itself (the payload names the project)
     and hands it to `claude.main(options, raw)`. The walk starts per the
     table above; Codex's rollout `cwd` comes from its `session_meta`
     (`codex.rollout_cwd`).
   - A file's `usage-source` this agent cannot read is skipped with a
     warning (`--show-config` checks it for any agent). A flag overriding
     a file for an option with `"mod"` in its ports is a warning, by the
     spec rather than a list (Decided 1). Warnings go to stderr;
     `--diagnose` appends ` config_warnings=N` on both agents' lines;
     `--show-config` (a new spec record, `"file": false`, no `--agent`
     needed, no stdin, walking from the working directory) lists them
     under its table instead. The nearest-key hint is the optimal string
     alignment distance, within `max(1, len // 3)`, ties to spec order,
     so the mod can match it exactly; warning texts carry no parser's
     message, so both ports can write them.
   - Derived values: `label` from `usage-text`; the spec's map now holds
     `C_LABEL` exactly, padded to the widest label, so the goldens hold.
     `right-edge` stays underived (`_NOT_DERIVED_YET`) for step 6.
   - Decided 16: a table field's spec may say `"fixed": [rows]`;
     `rows.transcript` fixes `account`, and gen-spec checks the rows.
   - Decided 2: `CODING_AGENT_USAGE_LINE_USAGE_SOURCE` is retired. The
     goldens' harness writes each environment's source into a scratch
     user config file; `tests/subagent.py` passes `--usage-source`;
     `py39-floor.sh` writes a config file (with a comment and a trailing
     comma) and checks `--show-config` under 3.9.
   - The tests never read this machine's files: a new test override,
     `CODING_AGENT_USAGE_LINE_PROJECT_DIR`, starts the walk in a given
     directory, and run-cases.py sets it to the case's repository and
     `CODING_AGENT_USAGE_LINE_CONFIG_DIR` to scratch. `tests/config.py`
     plants files at every place a developer's own could be (the three
     user-file names and a project file above the status payloads'
     directory), checks a case of each suite still matches its golden,
     and that the same run without the guard does not.
   - The shared cases are `tests/fixtures/config/cases.json`, 37 of
     them, written by `tests/fixtures/gen/config.py` (in `gen/all.py`):
     a file tree, the environment, the start and the flags, and the
     merged options that are not default, each table field a file set,
     and the warnings. The mod runs the cases with no flags; its port of
     `usage-source`'s check needs the sources' names.
5. **The mod reads the files.** `mod/src/config.ts`, the pure merge, and the
   reading through `$.fs` in `mod/hooks/edges.ts`; `config.test.ts` against
   the shared cases. `CONFIG` is still the defaults' source and nothing
   reads the files' values yet.

   **Status 2026-10-20: done.** As built:
   - `mod/src/config.ts` ports `config.py` (`find`, `mainCheckout`,
     `readFile`, `check`, `nearest`), `options.merge` and `cli._merged`'s
     usage-source loop, with no flags layer. `load(start, env, fs,
     agent)` takes a `ConfigFs` (`stat`, `read`, `realPath`, each null
     where Python would fail) and the three variables as a plain object,
     so it is pure. Paths are `posixpath`'s, written out; JSON is read
     by a `json.loads` port that keeps keys in the order written (a
     `Map`) and ints apart from floats (a `bigint`), so `"version": 2.0`
     and the warnings' quoting (`json.dumps` with and without
     `ensure_ascii`) come out as the Python's. Each `Layer` carries its
     file's `mtimeMs` for step 6's tick.
   - `mod/hooks/edges.ts`: `configVia` reads through `$.fs` (bytes,
     decoded strictly with the byte-order mark kept, as Python's
     `open(…, encoding="utf-8")`), starts at `$.session.root()`, and
     checks `usage-source` as Claude's panel does (`agent` `"claude"`;
     the shared cases run with none). `readConfig` keeps the result
     (`configNow()`) and logs one line of the files and the keys each
     gave, then one line per warning, to `usage-band.log`. It runs once
     per load, from `start()` in `register.tsx`, not awaited. No notice
     yet: the notice and the re-reads are step 6's.
   - `CODING_AGENT_USAGE_LINE_PROJECT_DIR`, the Python's test override,
     is not read: the mod's tests set `$.session.root` instead.
   - `mod/test/config.test.ts` runs the 35 cases with no flags over a
     fake file system built from each case's tree, and fails on any path
     asked outside it; `mod/mod-tests/config.test.ts` reads two planted
     files through the harness's `$.fs`, checks the log's lines word for
     word, and that no path the mod asks for, figures included, lies
     outside its world (the hermetic check, as `GoldensAreHermetic` is
     for the Python).
6. **The mod draws from `options()`.** Every `CONFIG.x` in `register.tsx`
   and `edges.ts` becomes `options().x`; the re-reads on `session.start`, the
   tick and a moved root; the redraw on change; the log and the notice.
   `config.ts` keeps only `version` and the timings (Decided 15).
   `BAND_EDGE` becomes the derived `right-edge`, 2 by default (Decided 13).

   **Status 2026-10-21: done.** As built:
   - `options()` in `mod/hooks/edges.ts` is the merged value, typed as
     the generated `Options` (`optionsOf` in `mod/src/config.ts`, camel
     case); every `CONFIG.x` that is an option reads it, in
     `register.tsx`, `edges.ts` (the source, account and period) and the
     settings `settingsOf` makes, which it makes again when
     `mark-spacing`, `subscript-decimals` or `right-edge` change.
     `config.ts` keeps `version`, the timings, `readSpacing`,
     `agentListMs` and `agentSenderMemo` as `CONFIG`; `BAND_EDGE` is gone.
   - Byte for byte as before with no file: the settings the mod drew with
     that are not the spec's defaults (`usage-source`
     `claude-usage-tracker`, the hide list, and `rows` with 🎤, 🤖 and 🎮
     live `"running"` and all three stamped, today's `sticky: []`) are a
     layer of the mod's own, `mod` (`SETTINGS` in `config.ts`,
     `MOD_LAYER`), under the files and over the defaults, so the spec's
     defaults stay the program's (Decided 17). Step 7 moves them to the
     user's file and empties `SETTINGS`. `--show-config` does not know
     the layer; the mod's log names it. `mod-tests/config.test.ts` holds
     the options with no file to the old `CONFIG`, field by field, and
     every band, row, receipt, figures fixture and golden is unchanged.
   - The rows table: `phaseRows` takes each row's `live` (`RowsLive`),
     `receiptLines` the rows `transcript` stamps and whether the tag
     line is drawn; `sticky` and `stickyScopes` are gone
     (`draw-figures.ts --sticky` stays, as live `"always"` and not
     stamped). `rows.tag.transcript` false drops 🔻🔖 and 🔺🔖 as
     `name.tag` does; `rows.tag.live` draws nothing yet, there being no
     live tag row. `rows.account.live` draws the 💳 tail or row always,
     while a turn runs, or never. The hide paths that drop a whole row
     still drop it, beside the table: retiring them is not done.
   - The re-reads: `readConfig` stamps the walk (`find`'s paths and each
     one's `mtimeMs`, and the start), and reads again only when the
     stamp has changed, so a file come, gone or written and a moved root
     are all one check; at load, on each `session.start` and every
     `tickMs` on the tick. One read at a time. A read that changes the
     options bumps a `configured` atom, which every drawing reads, and
     reads the figures again.
   - The log: each read logs the files and every warning, as in step 5,
     and a read that changes the options (or the first) logs
     `config options:` with each mod option and table field a layer above
     the defaults gave, and its layer.
   - The notice: `$.ui.notice` is a line under a tool call's open dialog
     in this engine (2.1.303's types: `notice(tool_use_id, text)`), with
     no call to hang a file's warning on, so the notice is a `$.ui.log`
     line in the transcript, `usage-band: config <the first warning>
     (and N more in usage-band.log)`, once per file and `mtimeMs` per
     load. Not a toast, as decided.
   - `right-edge` is derived in both ports: `_NOT_DERIVED_YET` is gone,
     and the Python derives from `live-place` though it is not one of its
     options (`options._merged_value`), so the panel's default is 2. The
     goldens' harness (`tests/run-cases.py`) writes `"right-edge": 5` in
     its scratch user file, the edge the panel's goldens are drawn at.
     The shared case `right-edge-not-yet-derived` is `right-edge-derived`,
     and `right-edge-set` is new: 38 cases.
   - `_flag` and `_costOpts(argv)` in `mod/src/claude_cost.ts` stay a
     test's reading of a case's flags: the mod draws no cost line.
7. **Move today's settings into files.** The user's `hide` list and
   `--usage-source`, `--mark-spacing` leave the `subagentStatusLine` command
   in `~/.claude/settings.json` and `CONFIG` for the user-global file, so the
   band and the panel read one copy. The command keeps only
   `--agent claude --mode subagent`. This is the user's file, so the step is
   a short note in `docs/options.md` and done by hand, not in a commit.

   Since step 6 the mod's own settings are `SETTINGS` in `config.ts`.
   The user file that draws as now, band and panel, checked with
   `--show-config` (no warning; `right-edge` derived 2):

   ```jsonc
   {
     "usage-source": "claude-usage-tracker",
     "hide": ["*.plan.five_hour", "*.context.share", "*.tokens.cache",
              "account.workspace.project", "account.workspace.branch"],
     "rows": {
       "turn":    { "live": "running", "transcript": true },
       "agent":   { "live": "running", "transcript": true },
       "session": { "live": "running", "transcript": true }
     }
   }
   ```

   Acceptance 1 has the user file with no `rows`, taking the defaults
   (🤖 and 🎮 kept between turns, 🎤 alone stamped): leaving `rows` out
   is that change of look, the user's call. Then the panel's command
   drops its `--mark-spacing`, `--usage-source`, `--right-edge` and
   `--hide` flags in the same edit (a flag that differs from the file is
   warned about, Decided 1), and `SETTINGS` empties to `{}` in a commit.

   **Status 2026-10-21: done,** with `rows` kept (the user's call): the
   user file above is written, `SETTINGS` is `{}` and the ignore line is
   in `.gitignore`; the panel's command is the user's to cut down.
8. **The acceptance check**, below.

## Acceptance

The rows table set in this project only:

1. The user-global file has no `rows`, so the defaults hold everywhere
   else: 🎤 `turn` live `"running"`, every other row live `"always"`, and
   only 🎤 `turn` and the tag lines stamped into the transcript.
2. This repository gets `.config/coding-agent-usage-line/config.local.jsonc`
   (see [Decided](#decided-2026-10-20), 8 and 9):

   ```jsonc
   {
     // 🎤, 🤖 and 🎮 kept under the footer line between turns, and every
     // turn's three stamped into the transcript too.
     "rows": {
       "turn":    { "live": "always", "transcript": true },
       "agent":   { "live": "always", "transcript": true },
       "session": { "live": "always", "transcript": true }
     }
   }
   ```

3. With no `/reload-plugins`: within one tick (30 s) the mod's log shows the
   new table with `rows` from the project-local layer, and
   `coding-agent-usage-line.py --show-config` run here says the same.
4. A turn in a session started in this repository ends: the mod keeps all
   three rows, 🎤, 🤖 and 🎮, where it drew them, and the receipt on the
   closing line stamps all three.
5. A turn in a session started in another repository (or in `/tmp`) ends:
   the mod keeps 🤖 and 🎮, drops 🎤, and the receipt stamps 🎤 alone.
6. `/cd` from this repository to the other moves the session's root, and
   the next tick takes the other project's layer: the next turn there
   stamps 🎤 alone.
7. Making the file invalid (`"live": "allways"`) leaves that row at its
   default, logs one warning naming `"always"`, and shows one notice.

## Decided (2026-10-20)

1. **The flags that must agree.** Step 7 takes `hide` and `right-edge` off
   the panel's command, and the panel warns when a flag overrides what the
   files give for an option both ports must agree on.
2. **The environment.** No environment variable is a setting: retire
   `CODING_AGENT_USAGE_LINE_USAGE_SOURCE`, the one that is. Kept, as not
   settings: secrets (`ANTHROPIC_ADMIN_KEY`, `OPENAI_ADMIN_KEY`,
   `CLAUDE_OAUTH_ACCESS_TOKEN`, `CODEX_USAGE_*`), other programs' own
   (`TERM*`, `TMUX`, `XDG_STATE_HOME`, `CODEX_HOME`), and the test
   overrides (`CODING_AGENT_USAGE_LINE_STATE_DIR`, `_NOW`, `_CLAUDE_*`,
   `_FIGURES_OUT`).
3. **Lists replace** across layers.
4. **The notice:** one `$.ui.notice` per file change, and the log.
5. **The mod's timings** stay constants in `config.ts`, out of the spec.
6. **The project files,** XDG style inside the project (pi0's `config-dir`
   proposal, which cosmiconfig also searches):
   `.config/coding-agent-usage-line/config.jsonc`, committed, and
   `config.local.jsonc` beside it, one person's own. A worktree that has no local file
   reads the main checkout's, found through the git common dir, so
   settings made once follow every worktree.
7. **The ignore line** in the repository's `.gitignore`, added with the
   files' step: `/.config/**/*.local.*`, any tool's local file under the
   root `.config/` (mise's `.config/mise.local.toml` included), and no
   `.config/` deeper in the tree.
8. **This repository's rows** go in its
   `.config/coding-agent-usage-line/config.local.jsonc`: the user's own
   preference, not one for everyone who clones it. All five there are
   live `"always"`, and the three cost rows are stamped too.
9. **The rows table** replaces `sticky`, `bandPlace` and the hide paths
   that drop a whole row; see [The rows table](#the-rows-table).
10. **Tables merge per field** across layers, while lists replace: a
    project that sets `rows.agent.transcript` alone keeps every other row
    and field from the layers under it.
11. **The files stay JSONC,** over YAML and TOML: each port parses it with
    its own JSON reader after stripping comments and trailing commas, with
    no vendored parser and no implicit typing (YAML would need PyYAML and
    the `yaml` package vendored and agreeing; TOML a Python of 3.11 or
    later for the panel and a vendored parser in the mod).
12. **🎤 `turn` defaults to live `"running"`:** shown while a turn runs,
    then left to the transcript's stamped copy; the other rows stay
    `"always"`.
13. **`right-edge` is derived from `live-place` when unset,** in the panel
    too: 2 under the default `"footer"`, 5 under `"above"`. The panel run
    without the mod sets `live-place` or `right-edge` to keep 5.
14. **Trailing commas are accepted:** the comment stripper drops a comma
    before `}` or `]`, and keeps one inside a string, as Decided 11 says;
    the shared cases change to match.
15. **The timings stay constants** in `config.ts` (Decided 5): every `-ms`
    field, `readSpacing`, `agentListMs` and `agentSenderMemo`. "What moves
    where" and step 6 say so.
16. **The 💳 `account` row refuses `"transcript": true`:** a warning, a
    notice and its default kept, as for any bad value; the spec carries
    the rule on the row.
17. **The spec's defaults are the program's own** (`usage-source` `auto`,
    an empty `hide`); the user's `claude-usage-tracker` and hide list move
    to their files in step 7. `--show-config` joins the spec in step 4,
    where it starts working.
