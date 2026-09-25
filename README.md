# coding-agent-usage-line

[![tests](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml/badge.svg)](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml)

Usage readouts for [Claude Code](https://claude.com/claude-code) and Codex,
rendered by a standard-library Python package with no installation step.
Operational commands require `--agent claude` or `--agent codex`; Claude keeps
its status, Stop-hook and subagent-panel presentation, while Codex supplies
one-shot status and Stop summaries (use Codex's own `/statusline` for its live
footer).

## Claude Code presentation

Three rows, redrawn continuously under the prompt:

```
👤💬 Why does the elapsed row report two durations when the session age is o…  | 🤖O⁵🏃 💰115   | 🧠   115k    11٪  | ⌛ 🔧  58m 🤖   3h 👤  6h Σ  9.3h  | 📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you spent.¶ ¶ The se…  | 🧩▴2.7M ▾841k  | 📖 🎤 34٪ 🎮 32٪  | 🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m  | 🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                   | 🛫200/s 🎯98٪  | 📝 🎤  7٪ 🎮  7٪  | 🪫 🎤 1.6٪ 🎮 8.4٪ 💳 87٪ 🔜 1.9d  | 💾 +3.4k - 214
```

Two more, printed by the `Stop` hook when a prompt finishes — what that one
prompt cost, stacked on what the session has spent:

```
📊 🎤 Usage: Prompt (last)      🧩 ▴9.6k ▾3.4k  🎯 98٪  🧠+ 8.0٪ + 16k  💰+  0.1   🔋+ 0.02٪ 📖 29٪  🪫+ 0.03٪ 📝  7٪  ⌛🤖+  1m  📅 2026-08-16
📊 🎮 Usage: Session (total)    🧩 ▴ 32k ▾7.9k  🎯 97٪  🧠 39.5٪   79k  💰   0.4   🔋  0.07٪ 💳 41٪  🪫  0.09٪ 💳 63٪  ⌛🤖   6m  🕐   02:23:20
```

And one row per task in the agent panel, replacing the panel's own, while
agents run:

```
◯ 🔍🟢 a1a65eb72… Verify brief citations Reading docs/layout.md       🤖O⁵🏃  🔧  5m  🤖  8m  💰0.1   🧠 41k  🧩▴ 13k ▾  1k  🛫200/s  🎯95٪  🔋.06٪  🪫.01٪  💾 +  84 -  12
◯ 🐚🟢 b1         npm test npm test --watch                                           🤖 13m
```

What you can read off it at a glance:

* 🧩 tokens in and out, 💰 what the session has cost in dollars
* 🛫 how fast the token total is climbing, 🎯 how much of the prompt came
  from cache
* 🧠 how full the context window is
* 🔋 the 5-hour plan window and 🪫 the weekly one, each at three scopes —
  🎤 this turn, 🎮 this session, 💳 the whole account — and 🔜 when it resets
* 📖 / 📝 where the money went: the share of a bill spent re-reading the
  conversation (which `/compact` reclaims) against the share spent caching new
  material (which it does not) — on the status line at two scopes, 🎤 this
  turn and 🎮 this session; on the cost line for the prompt just answered
* every figure counts what the session's subagents, forks and workflow agents
  billed, priced at each one's own model; 🧠 alone is the main thread's,
  because it is read to decide when *this* window needs compacting. Agent
  spend the prompt row cannot carry — a background agent finishing after its
  turn printed — gets a 👥 row of its own, the way a compaction gets 🤏
* ⌛ where the time went, split three ways that add up to the session's
  age: 🔧 inside a tool, 🤖 waiting on the model, 👤 waiting on you —
  and a tool that is a question put to you counts under 👤, not 🔧.
  The same 🔧 🤖 pair sits on each agent's row, splitting its run.
  💾 the working diff, 🌿 the branch, 🤖 the model as
  its initial and version with the effort's glyph against it — `O⁵🏃`, `H⁴🔥`
* on an agent's row: its type as a glyph (🔍 Explore, 📐 Plan, 🔧
  general-purpose, 🐚 a shell …), its run state as a circle (🟢 running, 🟡
  pending, 🔵 done, 🔴 failed, ⚫ killed), its id, its
  name and then what it is doing right now, what *its own* transcript says
  it has billed, 🛫 how fast the panel's token count is climbing, 🔋 🪫
  its share of each plan window, and 💾 the lines it has written, counted off
  its own edits

**Every figure sits on a fixed screen column.** Values are formatted to a fixed
width and carry a unit rather than more digits — `1.2k`, `4.5M`, `1.5h` — so
switching between tabs never moves a number, and nothing on the readout shifts
as the session grows.

**Brightness is magnitude.** A figure with no ceiling of its own — tokens,
the rate, the cost, a duration, the diff — is dim until it is worth noticing
and full strength after: 100k tokens, 1k/s, a dollar, ten minutes, a hundred
lines, the same cuts on the status line and on every agent row. Percentages
have their ceiling built in and stay bright; the limit rows use brightness for
scope and urgency instead. See [Layout](docs/layout.md#brightness-as-magnitude-everywhere-else).

It fits what it has: the columns compress as the terminal narrows, and drop
gracefully when the terminal will not say how wide it is.

## Install

```sh
git clone https://github.com/nhooey/claude-code-usage-statusline.git ~/src/claude-code-usage-statusline
```

Then point `~/.claude/settings.json` at it:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/src/claude-code-usage-statusline/coding-agent-usage-line.py --agent claude --mode status --mark-spacing"
  },
  "subagentStatusLine": {
    "type": "command",
    "command": "~/src/claude-code-usage-statusline/coding-agent-usage-line.py --agent claude --mode subagent --mark-spacing"
  },
  "hooks": {
    "Stop": [
      { "hooks": [ {
          "type": "command",
          "command": "~/src/claude-code-usage-statusline/coding-agent-usage-line.py --agent claude --mode cost --no-usage-text --force-newline --mark-spacing",
          "timeout": 20
      } ] }
    ]
  }
}
```

Keep the launcher and its sibling `coding_agent_usage_line/` package together;
there are no third-party Python dependencies or package-install steps.
It runs on Python 3.9 — the macOS Command Line Tools
interpreter — so it works in any project rather than only one whose devshell
supplies newer packages.

For Codex, add a Stop hook in either `~/.codex/hooks.json` or a project's
`.codex/hooks.json` (after reviewing it with Codex's `/hooks` command and
trusting the project):

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ {
          "type": "command",
          "command": "~/src/claude-code-usage-statusline/coding-agent-usage-line.py --agent codex --mode cost",
          "timeout": 30
      } ] }
    ]
  }
}
```

Codex hook `systemMessage` output is a warning/event-stream message, not a
replacement footer. Keep Codex's configured `tui.status_line` to its built-in
identifiers and use `/statusline` for the live footer. This project does not
edit either settings file for you. Review new or changed definitions in
`/hooks` before they run; see the [official hook guide](https://learn.chatgpt.com/docs/hooks).

For a saved Codex rollout:

```sh
./coding-agent-usage-line.py --agent codex --usage-source native --transcript /path/to/rollout.jsonl
./coding-agent-usage-line.py --agent codex --mode cost --all --usage-source none --transcript /path/to/rollout.jsonl
```

Codex reports retain full model names and reasoning effort. Subscription quota
buckets are separate labeled groups: a general weekly-only bucket stays
weekly-only even when Spark has both five-hour and weekly meters. Missing
metrics are not fabricated as zero, and subscription tokens are not priced as
API spending. Codex does not support Claude's subagent-panel hook.

Per-child token usage is reportable, but Codex does not supply a documented
per-child share of each subscription quota bucket. This project's Claude
shares are calibrated estimates; the Codex port does not reuse that calibration
or apportion account percentages across children. It leaves those percentages
unavailable rather than treating account-level meters as child-level readings.

Select account intake independently with `--usage-source`: native agent data,
a custom command, an optional tracker, Codex's managed app-server, organization
APIs, or explicit experimental subscription APIs. The default `auto` prefers
current native data. No Claude Usage app is required; use `--usage-source native`
to avoid external refreshes. See [usage sources](docs/usage-sources.md).

Migration: update hook commands to `coding-agent-usage-line.py` and add
`--agent claude` or `--agent codex`. There is no old-executable shim. The product
name has changed; the repository, clone URL and checkout name remain
`claude-code-usage-statusline` for now.

Common tweaks: add `--no-column-rules` to the status command for plain gaps
instead of the faint `|` borders, or `--no-mark-spacing` to tighten the readout
on a narrow terminal. The [full list](docs/options.md) is in the docs.

## Documentation

| | |
|---|---|
| [Options](docs/options.md) | every flag, in both modes, and what it removes or moves |
| [Layout and rendering](docs/layout.md) | the fixed-width grid, the column rules, what each colour and mark means |
| [Usage sources](docs/usage-sources.md) | where plan figures come from when the payload carries none, and how to write your own in twenty lines |
| [Accounting](docs/accounting.md) | how costs and window shares are derived, and what the two modes tell each other |
| [Glyphs and terminals](docs/glyphs-and-terminals.md) | why the width tables are hand-maintained, and how to pick a glyph that does not break alignment |
| [Tests](docs/tests.md) | the suites, what CI runs, and what needs a real terminal |
| [Development](docs/development.md) | the module boundaries, style rules, and implementation plan |

## License

MIT — the full text is in [`LICENSE`](LICENSE).
