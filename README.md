# claude-code-usage-statusline

[![tests](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml/badge.svg)](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml)

Three readouts for [Claude Code](https://claude.com/claude-code) — a **status
line** under the prompt, a **prompt-cost line** printed once per turn, and a
row per running **subagent** in the agent panel — rendered by one Python file
with no dependencies.

## What it looks like

Three rows, redrawn continuously under the prompt:

```
👤💬 Why does the elapsed row report two durations when the session age is one number, and which…  | 🤖O⁵🏃  | 🧩▴2.7M ▾841k  | 🔋 🎤 1.2٪ 🎮 3.8٪ 💳 15٪ 🔜 6.7m  | 📅  2026-08-16
🤖💬 Two figures, because one of them is not a duration you spent.¶ ¶ The session age is wall cl…  | 💰 115  | 🛫200/s 🎯98٪  | 🪫 🎤 1.6٪ 🎮 8.4٪ 💳 87٪ 🔜 1.9d  | 🕐    02:23:20
📦repo  📁~/src/statusline-fixture/deep/tree  🌿golden-clean                                       |         | 🧠 115k   11٪  | ⌛ 🎤   5m 👤   5h 🤖  4h Σ  9.3h  | 💾 +3.4k - 214
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
◯ 🔍🟢 a1a65eb72… Verify brief citations Reading docs/layout.md   🤖O⁵🏃  ⌛ 13m  🧩▴ 13k ▾  1k  🛫200/s  🎯95٪  🧠 41k  💰 0.1  🔋.06٪  🪫.01٪
◯ 🐚🟢 b1         npm test npm test --watch                                       ⌛ 13m
```

What you can read off it at a glance:

* 🧩 tokens in and out, 💰 what the session has cost in dollars
* 🛫 how fast the token total is climbing, 🎯 how much of the prompt came
  from cache
* 🧠 how full the context window is
* 🔋 the 5-hour plan window and 🪫 the weekly one, each at three scopes —
  🎤 this turn, 🎮 this session, 💳 the whole account — and 🔜 when it resets
* 📖 / 📝 on the cost line: whether this prompt's money went on re-reading the
  conversation (which `/compact` reclaims) or on new material (which it does not)
* every figure counts what the session's subagents, forks and workflow agents
  billed, priced at each one's own model; 🧠 alone is the main thread's,
  because it is read to decide when *this* window needs compacting. Agent
  spend the prompt row cannot carry — a background agent finishing after its
  turn printed — gets a 👥 row of its own, the way a compaction gets 🤏
* ⌛ where the time went, 💾 the working diff, 🌿 the branch, 🤖 the model as
  its initial and version with the effort's glyph against it — `O⁵🏃`, `H⁴🔥`
* on an agent's row: its type as a glyph (🔍 Explore, 📐 Plan, 🔧
  general-purpose, 🐚 a shell …), its run state as a circle (🟢 running, 🟡
  pending, 🔵 done, 🔴 failed, ⚫ killed), its id, its
  name and then what it is doing right now, what *its own* transcript says
  it has billed, 🛫 how fast the panel's token count is climbing, and 🔋 🪫
  its share of each plan window

**Every figure sits on a fixed screen column.** Values are formatted to a fixed
width and carry a unit rather than more digits — `1.2k`, `4.5M`, `1.5h` — so
switching between tabs never moves a number, and nothing on the readout shifts
as the session grows.

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
    "command": "~/src/claude-code-usage-statusline/claude-code-usage-statusline.py --mode status --mark-spacing"
  },
  "subagentStatusLine": {
    "type": "command",
    "command": "~/src/claude-code-usage-statusline/claude-code-usage-statusline.py --mode subagent --mark-spacing"
  },
  "hooks": {
    "Stop": [
      { "hooks": [ {
          "type": "command",
          "command": "~/src/claude-code-usage-statusline/claude-code-usage-statusline.py --mode cost --no-usage-text --force-newline --mark-spacing",
          "timeout": 20
      } ] }
    ]
  }
}
```

That is the whole installation: one file, the standard library, and the JSON
Claude Code already sends. It runs on Python 3.9 — the macOS Command Line Tools
interpreter — so it works in any project rather than only one whose devshell
supplies newer packages.

The 🔋 and 🪫 plan rows use Claude Code's own `rate_limits` whenever the payload
carries them. When it does not, they can fall back to an optional
[usage source](docs/usage-sources.md); without one, those two rows simply show
what Claude Code said and blank where it said nothing.

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
| [Development](docs/development.md) | a map of the one file, the style rules, and where this is going |

## License

MIT — the full text is in [`LICENSE`](LICENSE).
