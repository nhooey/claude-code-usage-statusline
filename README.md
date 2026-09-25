# coding-agent-usage-line

[![tests](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml/badge.svg)](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml)

A status line for [Claude Code](https://claude.com/claude-code) that shows what
your session is costing, how much of your plan it has used, where the time went,
and what every subagent is doing. Every figure stays on the same screen column,
so you can switch tabs and compare sessions at a glance.

```
👤💬 Why does the elapsed row report two durations when the …               | 🤖O⁵🏃 💰115   | 🧠   115k    11٪  | ⌛ 🔧  58m 🤖   3h 👤  6h Σ  9.3h  | 📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you …               | 🧩▴2.7M ▾841k  | 📖 🎤 34٪ 🎮 32٪  | 🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m  | 🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                | 🛫200/s 🎯98٪  | 📝 🎤  7٪ 🎮  7٪  | 🪫 🎤 1.6٪ 🎮 8.4٪ 💳 87٪ 🔜 1.9d  | 💾 +3.4k - 214
```

Start with three figures:

* **💰 115** — this session has cost $115 at API prices, as Claude Code
  reports it.
* **🔋 💳 15٪ 🔜 6.7m** — your account has used 15٪ of its 5-hour window, which
  resets in 6.7 minutes. **🪫** is the same for the weekly window.
* **🧠 115k 11٪** — the context window holds 115k tokens, 11٪ of its size.

The rest of this page explains the other figures, starting with the most useful.

## Install

You need Python 3.9 or newer. The program uses only the standard library, so
there is nothing to install beyond a clone:

```sh
git clone https://github.com/nhooey/claude-code-usage-statusline.git ~/src/claude-code-usage-statusline
```

Then add this to `~/.claude/settings.json`:

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

Each of the three entries is independent, so you can install only the ones you
want. Keep `coding-agent-usage-line.py` and the `coding_agent_usage_line/`
directory beside it together.

## The three readouts

### The status line

The status line is redrawn under the prompt as the session changes. The chat
text and the project details are on the left. On the right is a grid of five
columns, three rows deep:

| Column | Row 1 | Row 2 | Row 3 |
|---|---|---|---|
| Session | 🤖 model and effort, 💰 cost | 🧩 tokens ▴ in, ▾ out | 🛫 tokens per second, 🎯 cache hit rate |
| Context | 🧠 context used: tokens, ٪ | 📖 share of cost spent re-reading the conversation | 📝 share of cost spent caching new material |
| Time and plan | ⌛ time spent in 🔧 tools, 🤖 the model, 👤 waiting on you, Σ the session's age | 🔋 5-hour window | 🪫 weekly window |
| Clock | 📅 date | 🕐 time | 💾 lines added and removed |

`O⁵🏃` is Opus 5 at high effort. The effort glyphs, from lowest to highest,
are 🐢 🚶 🏃 🚀 🔥.

<details>
<summary><b>The plan rows: 🎤 🎮 💳 🔜</b></summary>

Each window row shows four fields, and each one covers a wider scope than the
one before it:

```
🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m
```

* 🎤 the last prompt's share of the window
* 🎮 this session's share
* 💳 how much of the window the whole account has used, counting every device
* 🔜 time until the window resets

💳 comes from Claude Code or another [usage source](docs/usage-sources.md).
🎤 and 🎮 are estimates: the program prices the session's requests and divides
by a dollars-per-percent rate it calibrates from this machine's history. See
[Accounting](docs/accounting.md).

</details>

<details>
<summary><b>📖 and 📝: whether <code>/compact</code> would help</b></summary>

Most of a long session's cost goes on re-reading the conversation from the
cache. 📖 is that share of the bill, and `/compact` or `/clear` can reduce it.
📝 is the share spent caching new material, such as tool results and files that
were read. Compacting does not reduce 📝.

A bright 📖 🎤 figure means that at least two thirds of the last prompt's cost
went on re-reading, so compacting would pay off.

</details>

<details>
<summary><b>⌛: where the time went</b></summary>

```
⌛ 🔧  58m 🤖   3h 👤  6h Σ  9.3h
```

The session's age (Σ) splits into three parts that add up to it exactly:

* 🔧 time spent inside tools
* 🤖 time the model spent thinking
* 👤 time the session spent waiting for you

A tool that asks you a question, such as `AskUserQuestion` or `ExitPlanMode`,
counts as 👤 time rather than 🔧 time.

</details>

### After each prompt

When a prompt finishes, the `Stop` hook prints what that prompt cost above the
session's running total:

```
📊 🎤    🧩 ▴ 28k ▾7.1k  🎯 95٪  🧠+ 3.4٪ +6.8k  💰+  0.2   🔋+ 0.03٪ 📖 32٪  🪫+ 0.05٪ 📝 18٪  ⌛🤖+  5m  📅 2026-08-16
📊 🎮    🧩 ▴ 68k ▾ 14k  🎯 97٪  🧠 27.1٪   54k  💰   0.6   🔋  0.1٪  💳 41٪  🪫  0.14٪ 💳 63٪  ⌛🤖  10m  🕐   02:23:20
```

A `+` marks what the prompt added to the total below it. Two other rows appear
when they apply. 🤏 reports what a compaction cost. 👥 reports spending by
agents that finished after their prompt's row had already been printed.

### The agent panel

While subagents run, each task in Claude Code's agent panel gets a row of its
own. Claude Code indents an agent that another agent started, and the columns
stay aligned at every depth:

```
◯  🔧🟢 a1b2c3d4e… Port the renderer Editing claude_render.py        🤖O⁵🏃  🔧  4m  🤖8.6m  💰0.4   🧠124k  🧩▴ 66k ▾3.6k  🛫266/s  🎯93٪  🔋.08٪  🪫.10٪  💾 +  48 -   9
├ ◯  🔍🟢 c7d8e9f0a… Find every caller of seg() Searching for seg(   🤖S⁵🚶  🔧  1m  🤖7.3m  💰0.1   🧠 48k  🧩▴ 24k ▾  1k  🛫 80/s  🎯90٪  🔋.03٪  🪫.04٪  💾 +   0 -   0
◯  📐🔵 f3e4d5c6b… Plan the docs rewrite                             🤖O⁵🏃          🤖  4m  💰0.2   🧠 42k  🧩▴ 26k ▾2.9k           🎯85٪  🔋.04٪  🪫.05٪  💾 + 120 -  30
◯  🐚🟢 b1         npm test npm test --watch                                         🤖 13m
```

Each row starts with the agent's type and state, followed by its ID, its name
and what it is doing now. The rest of the row shows the agent's own usage in the
same cells as the status line. The type glyphs include 🔧 general-purpose,
🔍 Explore, 📐 Plan and 🐚 shell. The state circles are 🟢 running, 🟡 pending,
🔵 done, 🔴 failed and ⚫ killed.

A parent's 🔧 includes the tool time of the agents it started. A shell has no
transcript, so its row shows only how long it has been running.

## Three rules the display follows

**Figures never move.** Every value has a fixed width and gets a unit instead of
more digits, as in `1.2k`, `4.5M` or `1.5h`. A number stays in the same place
from the first prompt to the thousandth.

**Brightness shows magnitude.** A figure with no natural ceiling stays dim until
it matters: 100k tokens, 1k tokens/s, $1, ten minutes or 100 lines.
Percentages already have a ceiling, so they follow separate rules.

**Agents are counted.** The tokens, costs, plan shares and times that the
program computes include every subagent, fork and workflow agent, each priced at
its own model's rates. 🧠 is
the exception: it shows only the main thread, because it tells you when *this*
context window needs compacting.

The grid is designed for terminals 170 columns or wider. On a narrower terminal
the chat text is shortened first and the column rules are removed.
[Layout](docs/layout.md) covers the details, including a
[legend of every glyph](docs/layout.md#glyph-legend).

## Customizing

Two flags cover most adjustments:

* `--no-column-rules` replaces the faint `|` dividers with plain spaces.
* `--no-mark-spacing` removes the space after each mark, for tighter terminals.

[Options](docs/options.md) lists every flag.

**Plan figures.** By default, 💳 and 🔜 come from the rate limits that Claude
Code includes in the status line's input. `--usage-source` can take them from
elsewhere, such as the Claude Usage Tracker app, an organization API, or a
script of your own. See [Usage sources](docs/usage-sources.md).

## Codex

The program also reports on Codex sessions with `--agent codex`. It prints a
summary from a Codex `Stop` hook and a one-shot status for a saved rollout. For
the live footer, use Codex's own `/statusline`. Codex does not report per-agent
quota shares, so those fields are left blank rather than estimated. See
[Codex](docs/codex.md) for setup.

## Documentation

| | |
|---|---|
| [Layout](docs/layout.md) | every cell on the three readouts, the colour rules, and the glyph legend |
| [Accounting](docs/accounting.md) | how the program derives costs, plan shares and time |
| [Options](docs/options.md) | every flag and environment variable |
| [Usage sources](docs/usage-sources.md) | where plan figures come from, and how to write your own source |
| [Codex](docs/codex.md) | setup and differences for Codex |
| [Glyphs and terminals](docs/glyphs-and-terminals.md) | how to choose a glyph that keeps the columns aligned |
| [Tests](docs/tests.md) | the test suites and what CI runs |
| [Development](docs/development.md) | how the code is organized, and the style rules |

## License

MIT. See [`LICENSE`](LICENSE).
