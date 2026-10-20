# Options

```
coding-agent-usage-line.py --agent claude|codex [--mode status|cost|subagent] [options]
coding-agent-usage-line.py --selftest
```

`--agent` is required for every mode. Only `--help` and `--selftest` run
without it. Flags are validated before stdin is read, so a malformed hook
command fails at once (exit 2) instead of waiting for input.

A bare invocation draws everything but the column rules. Every other Claude
display switch either removes something or changes spacing, so apart from
`--column-rules` you only add flags to take things away.

| I want to… | Use |
|---|---|
| read a saved transcript by hand | `--transcript PATH`, plus `--mode cost --all` for every prompt |
| faint `\|` rules between the columns | `--column-rules` |
| a tighter readout on a narrow terminal | `--no-mark-spacing` |
| shorter cost-line labels | `--no-usage-text` |
| see why a plan figure is blank | `--diagnose` |
| change where plan figures come from | `--usage-source SPEC` — see [Usage sources](usage-sources.md) |

## Modes

| Mode | Reads on stdin | Prints | Agents |
|---|---|---|---|
| `status` (default) | the status-line JSON payload | three rows, or four on a narrow terminal (Claude); a summary and quota lines (Codex) | both |
| `cost` | the Stop-hook JSON payload | `{"systemMessage": "..."}`, or `{}` when there is nothing to report | both |
| `subagent` | the agent panel's task list | one `{"id": ..., "content": ...}` line per task | Claude only |
| `--selftest` | nothing | specimen rows drawn on the terminal, and a report of where the cursor landed | — |

Hooks never break a session: a missing transcript or an internal error in
`cost` mode prints `{}` and exits 0. In `subagent` mode unreadable input
prints nothing, which leaves the panel's own rows in place.

`--agent codex --mode subagent` exits 2, because Codex has no agent-panel
hook. Use `--mode cost --all` for its child-agent reports. See
[Codex](codex.md).

`--selftest` needs a real terminal tab: it draws rows on `/dev/tty` and asks
the terminal where the cursor ended up. See
[Glyphs and terminals](glyphs-and-terminals.md).

## Shared options

These work for both agents.

| Option | Default | Effect |
|---|---|---|
| `--agent claude\|codex` | — | Which transcript format and hook conventions to use. Required. |
| `--mode MODE` | `status` | See [Modes](#modes). |
| `--transcript PATH` | the payload's path | Read this transcript instead of the one the payload names, and don't read stdin. For offline use: it skips the Stop hook's wait for the transcript to finish writing, and never records "already reported" state, so it can't change what the live hook reports next. |
| `--usage-source SPEC` | `auto` | Where plan/quota figures come from. See [Usage sources](usage-sources.md). |
| `--account NAME` | `default` | A non-secret label that keeps cached readings for different accounts apart. Never put a token here. |
| `--account-period day\|week\|month` | `day` | The UTC calendar period for organization reports (`anthropic-admin`, `openai-admin`). Weeks start on Monday. |
| `--all` | off | With `--mode cost`: list every prompt as plain text instead of emitting a hook response. Codex also lists completed child agents. Doesn't consume Stop-hook state. |
| `--from-figures PATH` | none | Claude: draw a saved figures document instead of reading any input. The test suite saves one per case; useful for redrawing a captured layout. See [the tests' README](../tests/README.md#figures). |
| `--diagnose` | off | Write one redacted line to stderr: which source was used, whether a reading was available, whether it is stale, and when a failed source will be retried. Claude's status line adds the session's cost and lines two ways, as a check on each other: `cost_usd` and `lines`, this program's own over the transcript and the agent files, as the cost line totals them, and `claude_cost_usd` and `claude_lines`, the totals Claude Code's payload gave; each is blank where its side has none. Codex adds child-rollout coverage. Never prints credentials, command paths or raw responses. |
| `--cols N` | detected | Terminal width. `0` means "unknown", which forces the fallback layout. Claude only; Codex accepts and ignores it. |
| `--right-edge N` | `5` | The columns every agent-panel row leaves blank at the terminal's right edge. `5` is the room Claude Code keeps for the mod's band `[-]` above the prompt; `0` matches the mod with its band under the footer line, where there is no `[-]`. Claude only. |
| `--hide PATH` | none | Repeatable. Leave a column or a part of a row's label out of the redesigned grid; see [Hiding](#hiding). Only the agent panel draws on the grid so far; the other modes, and Codex, accept it and ignore it. |

### Terminal width

A status-line command runs with pipes for stdio, so it can't ask its own
terminal for a width. The program walks up its process ancestry to the first
process with a terminal and asks that device, on every render, so a resize is
picked up on the next frame. There is no terminal under `claude -p` or in
cloud sessions; the readout then uses a fallback layout that doesn't depend on
the width. `--cols` overrides the walk. The tests use it for reproducible
output.

In `subagent` mode the panel supplies `columns` in its payload, the
terminal's width less 6, and the terminal's width worked out from it is used
unless `--cols` is given. `--cols` is the terminal's width in every mode.

## Claude display options

| Option | Modes | Effect |
|---|---|---|
| `--column-rules` | status | Draw faint `\|` rules between the columns. Nothing moves. |
| `--no-mark-spacing` | all | Close the blank between a mark and its value. |
| `--subscript-decimals` | all | Write fractions as subscript digits: `1.2٪` becomes `1₂٪`. |
| `--color` | cost | Colour the rows. Off by default because the Stop hook's message is shown as plain text. |
| `--no-totals` | cost | Drop the 🎮 session-totals row. |
| `--no-right-align` | cost | Print the rows flush left. |
| `--no-account-totals` | cost | Drop the second half of each 🔋 and 🪫 cell: `💳 41٪` on the totals row, `📖`/`📝` on the prompt row. |
| `--no-datetime` | cost | Drop the 📅 date and 🕐 time cells. |
| `--no-usage-text` | cost | Drop the `Usage: …` words from the row labels, keeping each row's glyph. |
| `--force-newline` | cost | Always start the message with a blank line. |
| `--prefix TEXT` | cost | The mark at the start of each row. Default `📊`. |
| `--label TEXT` | cost | The label of the prompt row. Default `🎤 Usage: Prompt (last)`, or `🎤` with `--no-usage-text`. |

`--no-column-rules` and `--mark-spacing` are the defaults and are accepted so a
settings file can say explicitly what it wants. A flag given for a mode it
doesn't apply to is accepted and ignored. With `--agent codex` these flags are
rejected as unknown options (exit 2), except `--prefix` and `--label`, which
are accepted and ignored.

### `--no-mark-spacing`

Closes the one-column gap between a mark and its value, for terminals too
narrow for the full readout. On the status line this narrows column 4 by four
columns and column 3 by two:

```
default   ⌛ ⛳    ? 🤖 2.8h 🔧  58m 🚦 5.5h
          🔋 🎤 1.2٪ 🎮 3.8٪ 💳  15٪ 🔜 6.7m
tight     ⌛ ⛳   ? 🤖2.8h 🔧 58m 🚦5.5h
          🔋 🎤1.2٪ 🎮3.8٪ 💳 15٪ 🔜6.7m
```

On the cost line it reaches only the marks with nothing after them — 🧩, 🎯,
💳, 📖 and 📝:

```
default   🧩 ▴9.6k ▾3.4k  🎯 98٪  🧠+ 8.0٪ + 16k  💰+  0.1   🔋+ 0.02٪ 📖 29٪
tight     🧩▴9.6k ▾3.4k  🎯98٪  🧠+ 8.0٪ + 16k  💰+  0.1   🔋+ 0.02٪ 📖29٪
```

The column after 🧠, 💰, 🔋, 🪫, ⌛🤖 and 🔧 holds a `+` on the prompt row and a
blank on the totals row beneath it. That column is what keeps the two rows
stacked digit under digit, so it stays. The agent panel's rows have no mark
spacing to close and don't change.

It also keeps the column rules off, even under `--column-rules`. See
[Column rules](layout.md#column-rules).

### `--column-rules`

The rules are painted into gaps the grid leaves anyway, so turning them on
changes the ink and nothing else. They stay off below 170 columns, when the
width is unknown, and under `--no-mark-spacing`, even when asked for.
`--no-column-rules` wins if both are given.

### `--subscript-decimals`

Writes the digits after a decimal point as subscripts (U+2080–U+2089), so the
point takes no column:

```
off   🧩▴2.7M ▾841k    🔋 🎤 1.2٪ 🎮 3.8٪ 💳  15٪ 🔜 6.7m
on    🧩▴ 2₇M ▾841k    🔋 🎤  1₂٪ 🎮  3₈٪ 💳  15٪ 🔜  6₇m
```

(Two cells from the status line's second row.)

A reading under 1٪ keeps its leading zero — `.08٪` becomes `0₀₈٪` — because
`₀₈` alone reads as a small 8. That makes the sub-1 reading the same width in
both forms, and it is the widest reading, so **no field gets narrower**: a
shorter figure just gets another column of padding and nothing on the row
moves. The option changes how figures look, not how much room they take.

Both JediTerm and Ghostty draw the subscript digits one column wide, which is
what the program assumes.

## Agent panel rows (`--mode subagent`)

This mode is the `subagentStatusLine` setting. While the session has tasks in
its agent panel — Agent tool calls, forks, background shells, workflows —
Claude Code runs the command every few seconds with the task list on stdin and
replaces each panel row with the `content` printed for its `id`. A task left
out keeps the panel's own row. What each cell means is covered in
[Layout](layout.md).

The payload carries each task's name, type, status, start time, model, effort
and a running token count. Everything else — tokens, cache rate, context,
cost, time inside tools, lines written, the plan-window shares and the ETA
the agent reported — comes from the agent's own transcript,
`<session>/subagents/agent-<id>.jsonl`, with workflow agents one directory
further down. A task with no transcript (a shell, a remote agent) shows only
what the payload gives.

Each row is laid out on the redesigned grid
([the plan](../agents/plans/redesign.md)), the columns the mod's band and
receipt draw: model, 🛫, 💰, 🧠, 🧩, 🎯, ⌛ ⛳ 🤖 🔧 🚦, 🔋, 🪫, 💾. On an agent
row the 🛫 column says what the agent is doing and for how long, or its token
rate. The label before them is the kind and its phase, the 👶🏻 🤏 💻 📡 📨
counts some rows carry, the name, a worktree's 🌿 branch and the activity.

The rows are laid out for the terminal's width, the payload's `columns` plus
6, so the figures fall on the same screen columns as the band's. Claude Code
draws the panel's chrome before each row, `  ◯ ` at the top level and two
more blanks for each level an agent started by another agent sits below it
(the depth is `spawnDepth` in the agent's `.meta.json` sidecar, or the
panel's own tree); the row counts it toward the width and does not print it.
Every row ends five columns short of the terminal's edge, as the band does
above the prompt; `--right-edge 0` takes them back, for the band under the
footer line.
The columns follow from the width and `--hide` alone, kept for two levels of
nesting whether any agent runs or not, so no column moves when an agent
starts; a deeper row cuts its own label instead. On a narrow terminal whole
columns drop from every row at once, 🛫 first and 💰 last. At an unknown
width (`--cols 0` and no payload width) every column is drawn and the label
keeps 20 columns.

`--cols`, `--hide`, `--right-edge`, `--usage-source`, `--account`,
`--account-period`, `--diagnose` and `--subscript-decimals` apply in this
mode.

### Hiding

`--hide scope[.group[.metric]]`, repeatable, with `*` for any one part,
leaves out a column or a label part. A path names what it hides on rows of
that scope; a column hidden on every row that could draw it is removed and
the others close up, and one hidden on some rows only is left blank there.
The band's and the receipt's rows count too, so `--hide agent.state.rate`
blanks 🛫 on the agent rows and keeps its place, while `--hide '*.state.rate'`
removes it.

| Part | Values |
|---|---|
| scope | `account`, `turn`, `main`, `session`, `agent` |
| group | `plan` (🔋 🪫), `cost` (💰), `tokens` (🧩 🎯), `context` (🧠), `time` (⌛ ⛳ 🤖 🔧 🚦), `work` (💾), `state` (model, 🛫, and on agent rows the 👶🏻 🤏 💻 📡 📨 counts), `chat` (the activity), `workspace` (🌿), `name` (the name and the kind) |

On an agent row:

| Path | Hides |
|---|---|
| `agent.name.kind` | the spinner, the kind's mark and the phase circle |
| `agent.name.label` | the agent's name |
| `agent.workspace.branch` | 🌿 and a worktree's branch |
| `agent.chat.doing` | what it is doing, the panel's activity text |
| `agent.state.kids`, `.compact`, `.shells`, `.monitors`, `.inbox` | 👶🏻, 🤏, 💻, 📡, 📨 |
| `agent.state.model`, `.rate`, `agent.cost`, `agent.context`, `agent.tokens.io`, `.cache`, `agent.time.elapsed`, `.eta`, `.split`, `agent.plan.five_hour`, `.week`, `agent.work` | the columns |
| `agent.context.share` | 🧠's ٪ of the window, its size set flush right; hidden on every scope (`*.context.share`), 🧠's column narrows by the ٪'s room |

```
--hide agent                  every agent row, empty
--hide '*.work'               💾 on every row
--hide agent.time.eta         ⛳ on the agent rows, blank in its column
--hide '*.state.rate'         🛫 everywhere
--hide '*.context.share'      🧠's ٪ everywhere, its column narrower
```

## Environment variables

| Variable | Effect |
|---|---|
| `CODING_AGENT_USAGE_LINE_USAGE_SOURCE` | Default for `--usage-source`. The flag wins. |
| `CODING_AGENT_USAGE_LINE_STATE_DIR` | Where caches and per-session state live. Default `$XDG_STATE_HOME/coding-agent-usage-line`, or `~/.local/state/coding-agent-usage-line`. |
| `CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR` | Where Claude transcripts live, for calibration. Default `~/.claude/projects`. |
| `CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST` | Read an exported Claude Usage Tracker store from this path instead of the running app's preferences. |
| `CODEX_HOME` | Codex's data directory, used to find child-agent rollouts. Default `~/.codex`. |
| `ANTHROPIC_ADMIN_KEY`, `OPENAI_ADMIN_KEY`, `CLAUDE_OAUTH_ACCESS_TOKEN`, `CODEX_USAGE_ACCESS_TOKEN`, `CODEX_USAGE_ACCOUNT_ID` | Credentials for the sources that need them. See [Usage sources](usage-sources.md#sources). |

Two more exist for the test suites: `CODING_AGENT_USAGE_LINE_NOW` freezes the
clock and `CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE` supplies a prepared
calibration. Neither is for everyday use.

## Migrating from `claude-code-usage-statusline.py`

The program used to be a single file, `claude-code-usage-statusline.py`. It is
now `coding-agent-usage-line.py` beside the `coding_agent_usage_line/`
package, and every operational command needs `--agent`. There is no
compatibility shim under the old name.

1. In `~/.claude/settings.json`, change each command's program to
   `coding-agent-usage-line.py` and add `--agent claude`.
2. Rename environment variables:

   | Old | New |
   |---|---|
   | `CLAUDE_USAGE_SOURCE` | `CODING_AGENT_USAGE_LINE_USAGE_SOURCE` |
   | `CLAUDE_PROJECTS_DIR` | `CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR` |
   | `CLAUDE_USAGE_TRACKER_PLIST` | `CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST` |
   | `CLAUDE_CALIB_CACHE` | `CODING_AGENT_USAGE_LINE_CLAUDE_CALIB_CACHE` |
   | `CLAUDE_STATUSLINE_NOW` | `CODING_AGENT_USAGE_LINE_NOW` |

   `CLAUDE_PLAN_CACHE` and `CLAUDE_LIMIT_CACHE` are gone: readings are now
   cached under the state directory. The old names are ignored.
3. Credential variables (`ANTHROPIC_ADMIN_KEY` and the rest) keep their vendor
   names.

The repository and its clone URL are still `claude-code-usage-statusline`.
