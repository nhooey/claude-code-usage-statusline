# Options

```
coding-agent-usage-line.py --agent claude|codex [--mode status|cost|subagent] [options]
coding-agent-usage-line.py --selftest
```

`--agent` is required for every mode. Only `--help` and `--selftest` run
without it. Flags are validated before stdin is read, so a malformed hook
command fails at once (exit 2) instead of waiting for input.

A bare invocation draws everything. Every Claude display switch either removes
something or changes spacing, so you only add flags to take things away.

| I want to… | Use |
|---|---|
| read a saved transcript by hand | `--transcript PATH`, plus `--mode cost --all` for every prompt |
| plain gaps instead of the faint `\|` rules | `--no-column-rules` |
| a tighter readout on a narrow terminal | `--no-mark-spacing` |
| shorter cost-line labels | `--no-usage-text` |
| see why a plan figure is blank | `--diagnose` |
| change where plan figures come from | `--usage-source SPEC` — see [Usage sources](usage-sources.md) |

## Modes

| Mode | Reads on stdin | Prints | Agents |
|---|---|---|---|
| `status` (default) | the status-line JSON payload | three rows (Claude); a summary and quota lines (Codex) | both |
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
| `--diagnose` | off | Write one redacted line to stderr: which source was used, whether a reading was available, whether it is stale, and when a failed source will be retried. Codex adds child-rollout coverage. Never prints credentials, command paths or raw responses. |
| `--cols N` | detected | Terminal width. `0` means "unknown", which forces the fallback layout. Claude only; Codex accepts and ignores it. |

### Terminal width

A status-line command runs with pipes for stdio, so it can't ask its own
terminal for a width. The program walks up its process ancestry to the first
process with a terminal and asks that device, on every render, so a resize is
picked up on the next frame. There is no terminal under `claude -p` or in
cloud sessions; the readout then uses a fallback layout that doesn't depend on
the width. `--cols` overrides the walk. The tests use it for reproducible
output.

In `subagent` mode the panel supplies `columns` in its payload and that is
used unless `--cols` is given.

## Claude display options

| Option | Modes | Effect |
|---|---|---|
| `--no-column-rules` | status | Drop the faint `\|` rules between the columns. Nothing moves. |
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

`--column-rules` and `--mark-spacing` are the defaults and are accepted so a
settings file can say explicitly what it wants. A flag given for a mode it
doesn't apply to is accepted and ignored. With `--agent codex` these flags are
rejected as unknown options (exit 2), except `--prefix` and `--label`, which
are accepted and ignored.

### `--no-mark-spacing`

Closes the one-column gap between a mark and its value, for terminals too
narrow for the full readout. On the status line this narrows column 4 by four
columns and column 3 by two:

```
default   ⌛ 🔧  58m 🤖   3h 👤  6h Σ  9.3h
          🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m
tight     ⌛ 🔧 58m 🤖  3h 👤 6h Σ 9.3h
          🔋 🎤1.2٪ 🎮3.8٪ 💳15٪ 🔜6.7m
```

On the cost line it reaches only the marks with nothing after them — 🧩, 🎯,
💳, 📖 and 📝:

```
default   🧩 ▴9.6k ▾3.4k  🎯 98٪  🧠+ 8.0٪ + 16k  💰+  0.1   🔋+ 0.02٪ 📖 29٪
tight     🧩▴9.6k ▾3.4k  🎯98٪  🧠+ 8.0٪ + 16k  💰+  0.1   🔋+ 0.02٪ 📖29٪
```

The column after 🧠, 💰, 🔋, 🪫 and ⌛🤖 holds a `+` on the prompt row and a
blank on the totals row beneath it. That column is what keeps the two rows
stacked digit under digit, so it stays. The agent panel's rows have no mark
spacing to close and don't change.

It also turns off the column rules. See
[Column rules](layout.md#column-rules).

### `--no-column-rules`

The rules are painted into gaps the grid leaves anyway, so turning them off
changes the ink and nothing else. They are already off below 170 columns, when
the width is unknown, and under `--no-mark-spacing`; the flag turns them off at
the widths that would otherwise draw them.

### `--subscript-decimals`

Writes the digits after a decimal point as subscripts (U+2080–U+2089), so the
point takes no column:

```
off   🧩▴2.7M ▾841k    🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m
on    🧩▴ 2₇M ▾841k    🔋 🎤  1₂٪ 🎮  3₈٪ 💳 15٪ 🔜  6₇m
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
cost, time inside tools, lines written and the plan-window shares — comes
from the agent's own transcript,
`<session>/subagents/agent-<id>.jsonl`, with workflow agents one directory
further down. A task with no transcript (a shell, a remote agent) shows only
what the payload gives.

The payload's `columns` is already net of the panel's own chrome: the `◯ `
pointer before the row and two columns of padding after it. An agent started
by another agent is drawn one level deeper, with `├ ` before its pointer. The
payload doesn't count those two columns, so the row makes itself two columns
narrower for each level below the first (the depth is `spawnDepth` in the
agent's `.meta.json` sidecar). That keeps every row's right-hand cells on the
same columns as its parent's.

`--cols`, `--usage-source`, `--account`, `--account-period`, `--diagnose` and
`--subscript-decimals` apply in this mode.

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
