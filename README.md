# coding-agent-usage-line

[![tests](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml/badge.svg)](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml)

Three readouts for [Claude Code](https://claude.com/claude-code) that show what
your session is costing, how much of your plan it has used, where the time went,
and what every subagent is doing. Every figure stays on the same screen column,
so you can switch tabs and compare sessions at a glance.

## Session status line

Redrawn under the prompt as the session changes. Installed as `statusLine`.

```
👤💬 Why is the build slow?         🤖O⁵🏃 💰115     🧠   115k    11٪    ⌛ ⛳   4m 🤖 2.8h 🔧  58m 🚦 5.5h    📅  2026-08-16
🤖💬 The test step takes 80٪ of…    🧩▴2.7M ▾841k    📖 🎤 34٪ 🎮 32٪    🔋 🎤 1.2٪ 🎮 3.8٪ 💳  15٪ 🔜 6.7m    🕐    02:23:20
📦app  📁~/src/app  🌿main          🤖200/s 🎯98٪    📝 🎤  7٪ 🎮  7٪    🪫 🎤 1.6٪ 🎮 8.4٪ 💳  87٪ 🔜 1.9d    💾 +3.4k - 214
```

Read these three first:

* **💰 115**: the session has cost $115 at API prices.
* **🔋 💳 15٪ 🔜 6.7m**: the account has used 15٪ of its 5-hour window, which
  resets in 6.7 minutes. 🪫 is the same for the weekly window.
* **🧠 115k 11٪**: the context holds 115k tokens, 11٪ of the window.

| | Chat and project | Session | Context | Time and plan | Clock |
|---|---|---|---|---|---|
| **Row 1** | 👤💬 Prompt · 🎨 Style | 🤖 Model · 💰 Cost | 🧠 Context | ⌛ Elapsed | 📅 Date |
| **Row 2** | 🤖💬 Reply · 🔀 PR | 🧩 Tokens | 📖 Rereads | 🔋 5-hour | 🕐 Clock |
| **Row 3** | 📦 Project · 📁 Directory · 🌿 Branch · 💻 Shells · 📡 Monitors · 📨 Queue · 🤏 Compactions | Doing · 🎯 Hits | 📝 Caching | 🪫 Weekly | 💾 Diff |

## Agent tree

One row per subagent or shell in Claude Code's agent panel, indented under the
agent that started it. Installed as `subagentStatusLine`.

```
⏺  🔩🟢 🤖266/s 👶🏻1 a1b2c3d4e… Port renderer Editing…   ⏺   🤖O⁵🏃  💰 0.4   🧠 124k  12٪  🧩 ▴ 66k ▾3.6k  🎯93٪  ⌛ 14m ⛳   3m 🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀  🔋.08٪  🪫.10٪  💾 +  48 -   9
└ ◯  🔍🟢 🔧 42s      c7d8e9f0a… Find callers of seg()  └ ◯ 🤖S⁵🚶  💰 0.1   🧠  48k  24٪  🧩 ▴ 24k ▾  1k  🎯90٪  ⌛8.3m ⛳ 2.5m 🤖⠶⠦ 🔧⠄⠀ 🚦⠀⠀  🔋.03٪  🪫.04٪  💾 +   0 -   0
◯  📐⚫ ✅ 4m       f3e4d5c6b… Plan docs rewrite        ◯   🤖O⁵🏃  💰 0.2   🧠  42k   4٪  🧩 ▴ 26k ▾2.9k   🎯85٪  ⌛  5m ⛳    ? 🤖⠶⠆ 🔧⠀⠀ 🚦⠆⠀  🔋.04٪  🪫.05٪  💾 + 120 -  30
◯  🐚🟢             b1         npm test --watch         ◯                                                                  ⌛ 13m
```

| Side | Cells, left to right |
|---|---|
| **Left** | Kind · State · Doing · 👶🏻 Children · 🤏 Compactions · 💻 Shells · 📡 Monitors · 📨 Queue · ID · Name, 🌿 worktree branch and activity |
| **Right** | Tree · 🤖 Model · 💰 Cost · 🧠 Context · 🧩 Tokens · 🎯 Hits · ⌛ Elapsed · ⛳ ETA · 🤖 Thinking · 🔧 Tools · 🚦 Waiting · 🔋 5-hour · 🪫 Weekly · 💾 Diff |

The right side uses the session status line's cells, for that one agent. A
shell has no transcript, so its row shows only how long it has run.

## Prompt receipt

Printed once each prompt finishes, what the prompt cost over the session's
running total. Installed as the `Stop` hook.

```
📊 🎤    🧩 ▴ 28k ▾7.1k  🎯 95٪  🧠+ 3.4٪ +6.8k  💰+  0.2   🔋+ 0.03٪ 📖 32٪  🪫+ 0.05٪ 📝 18٪  ⌛🤖+  4m  🔧+  3m  📅 2026-08-16
📊 🎮    🧩 ▴ 68k ▾ 14k  🎯 97٪  🧠 27.1٪   54k  💰   0.6   🔋  0.1٪  💳 41٪  🪫  0.14٪ 💳 63٪  ⌛🤖  13m  🔧   3m  🕐   02:23:20
```

A `+` marks what the prompt added to the total below it.

## Install

You need Python 3.9 or newer. The program uses only the standard library, so
there is nothing to install beyond a clone:

```sh
git clone https://github.com/nhooey/claude-code-usage-statusline.git ~/src/claude-code-usage-statusline
```

Then merge [`examples/claude/settings.json`](examples/claude/settings.json)
into `~/.claude/settings.json`. It has one entry per readout:

| Entry | Readout |
|---|---|
| `statusLine` | session status line |
| `subagentStatusLine` | agent tree |
| `hooks.Stop` | prompt receipt |

Each is independent, so you can install only the ones you want. The paths
assume the clone above. Keep
`coding-agent-usage-line.py` and the `coding_agent_usage_line/` directory
beside it together.

For ⛳ ETAs, link the skill that has agents report them, and tell them to use
it:

```sh
ln -s ~/src/claude-code-usage-statusline/skills/coding-agent-usage-line-report-eta ~/.claude/skills/
echo 'For any task you expect to take more than about a minute, as the main agent or as a subagent, follow the `coding-agent-usage-line-report-eta` skill.' >> ~/.claude/CLAUDE.md
```

## Legend

The legend has one table per topic. Each glyph has a name, and a ✓ marks each
readout that draws it. Where a glyph means something different on one
readout, the table says so.

### Chat and project

| Glyph | Name | Meaning | Status | Tree | Receipt |
|---|---|---|:-:|:-:|:-:|
| 👤💬 | Prompt | your last prompt | ✓ | | |
| 🤖💬 | Reply | the model's last reply | ✓ | | |
| ¶ | Newline | a newline inside a chat row | ✓ | | |
| 🎨 | Style | output style, when not the default | ✓ | | |
| 🔀 | PR | pull request number | ✓ | | |
| 📨 | Queue | messages waiting: on the status line, for the main thread's next turn; on the tree, sent to the agent and not yet delivered, Claude Code's "N queued" | ✓ | ✓ | |
| 📦 | Project | the project; in a worktree, the main repository | ✓ | | |
| 📁 | Directory | current directory | ✓ | | |
| 🌿 | Branch | branch, clean tree; on the tree, the branch of a worktree the agent works in apart from the session's | ✓ | ✓ | |
| 🍂 ✱ | Dirty | branch, uncommitted changes | ✓ | | |
| 💾 | Diff | lines added and removed | ✓ | ✓ | |
| 📅 | Date | today's date; on the receipt, when it printed | ✓ | | ✓ |
| 🕐 | Clock | the time; on the receipt, when it printed | ✓ | | ✓ |

### Model

| Glyph | Name | Meaning | Status | Tree | Receipt |
|---|---|---|:-:|:-:|:-:|
| 🤖 `O⁵` | Model | family initial and major version, such as `O⁵` Opus 5, `S⁵` Sonnet 5 or `H⁴` Haiku 4.5 | ✓ | ✓ | |
| 🐢 | Low | reasoning effort `low` | ✓ | ✓ | |
| 🚶 | Medium | reasoning effort `medium` | ✓ | ✓ | |
| 🏃 | High | reasoning effort `high` | ✓ | ✓ | |
| 🚀 | Xhigh | reasoning effort `xhigh` | ✓ | ✓ | |
| 🔥 | Max | reasoning effort `max` | ✓ | ✓ | |

### Cost and tokens

| Glyph | Name | Meaning | Status | Tree | Receipt |
|---|---|---|:-:|:-:|:-:|
| 💰 | Cost | cost in dollars, at API prices | ✓ | ✓ | ✓ |
| 🧩 | Tokens | tokens in and out | ✓ | ✓ | ✓ |
| ▴ | Input | billable-equivalent input tokens | ✓ | ✓ | ✓ |
| ▾ | Output | output tokens | ✓ | ✓ | ✓ |
| 🛫 | Rate | tokens per second, where no state applies: an offline read, a shell | ✓ | ✓ | |
| 🔧 🚦 🤖 … | Doing | what the thread is doing and for how long: 🔧 a tool, 🚦 waiting on you or an agent (or between turns), 🤖 the model, which shows the token rate until it has written nothing for a minute (amber from ten). On the tree, the cell after the state circle, with the paused and ended marks too | ✓ | ✓ | |
| 🎯 | Hits | prompt-cache hit rate | ✓ | ✓ | ✓ |

### Context

| Glyph | Name | Meaning | Status | Tree | Receipt |
|---|---|---|:-:|:-:|:-:|
| 🧠 | Context | context size and share of the window; on the receipt, its change | ✓ | ✓ | ✓ |
| 📖 | Rereads | share of the bill spent re-reading the conversation | ✓ | | ✓ |
| 📝 | Caching | share of the bill spent caching new material | ✓ | | ✓ |
| 🤏 | Compactions | how often the window has been compacted; on the receipt, a compaction's own row | ✓ | ✓ | ✓ |

* 📖 is the part of the bill that `/compact` or `/clear` can reduce. A bright
  📖 🎤 means at least two thirds of the last prompt's cost went on
  re-reading, so compacting would pay off.
* Compacting does not reduce 📝. It covers tool results and files that were
  read.

### Time

| Glyph | Name | Meaning | Status | Tree | Receipt |
|---|---|---|:-:|:-:|:-:|
| ⌛ | Elapsed | the time row; on the tree, the agent's age | ✓ | ✓ | |
| ⛳ | ETA | time the answer or agent says it has left | ✓ | ✓ | |
| 🤖 | Thinking | time with the model | ✓ | ✓ | |
| 🔧 | Tools | time inside tools | ✓ | ✓ | ✓ |
| 🚦 | Waiting | time waiting on you, or on agents it started | ✓ | ✓ | |
| ⠄ ⠆ ⠦ ⠶ | Gauge | that figure's share of ⌛ | | ✓ | |
| ⌛🤖 | Answering | time with the model, per prompt and its agents | | | ✓ |

* **🤖 🔧 🚦 add up to ⌛.** The status line prints them as durations. The tree
  prints them as gauges with eight dots between the three, so
  `🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀` means five eighths thinking, two in tools and one waiting.
* **Each row counts its own thread.** A parent waiting on the agents it
  started reads that time as 🚦. So do `AskUserQuestion`, `ExitPlanMode` and
  `Agent` calls.
* **The receipt counts agents where its tokens do.** Each row's ⌛🤖 and 🔧
  add the agents it bills, off each agent's own clock, so the 🎮 row is the
  status line's 🤖 and 🔧 plus every agent's, and can pass the session's age.
* **The receipt splits each prompt the same way.** Its ⌛🤖 and 🔧 are the
  status line's 🤖 and 🔧 over that one prompt, and the 🎮 row sums them. It
  prints no 🚦: what a prompt waited on is in neither figure.
* **⛳ comes from a skill.** Agents report their time left through the
  [`coding-agent-usage-line-report-eta`](skills/coding-agent-usage-line-report-eta/SKILL.md)
  skill (see [ETA](docs/layout.md#eta)). ⛳ reads `?` until a report
  arrives and after the answer finishes. A parent's ETA is never earlier
  than that of any agent it still has running.

### Plan windows

| Glyph | Name | Meaning | Status | Tree | Receipt |
|---|---|---|:-:|:-:|:-:|
| 🔋 | 5-hour | share of the 5-hour window | ✓ | ✓ | ✓ |
| 🪫 | Weekly | share of the weekly window | ✓ | ✓ | ✓ |
| 🎤 | Prompt | the last prompt's share | ✓ | | ✓ |
| 🎮 | Session | this session's share | ✓ | | ✓ |
| 💳 | Account | the whole account's share, on every device | ✓ | | ✓ |
| 🔜 | Reset | time until the window resets | ✓ | | |
| 💯 | Full | a full 100٪ | ✓ | ✓ | ✓ |
| `?` | Unknown | a share that cannot be derived yet | ✓ | ✓ | |

* **🎤 and 🎮 are estimates.** The program prices the session's requests and
  divides by a dollars-per-percent rate calibrated from this machine's
  history. See [Accounting](docs/accounting.md).
* **💳 is the plan's own figure.** It comes from Claude Code or another
  [usage source](docs/usage-sources.md).
* **On the tree**, 🔋 and 🪫 are the agent's own share of each window.

### Background tasks

| Glyph | Name | Meaning | Status | Tree | Receipt |
|---|---|---|:-:|:-:|:-:|
| 💻 | Shells | background shells it started and has not heard the end of; on the status line, the main thread's | ✓ | ✓ | |
| 📡 | Monitors | Monitors it started and has not heard the end of; on the status line, the main thread's | ✓ | ✓ | |

On the tree, both are drawn while the agent runs and while it is paused, and
not once it has failed or been killed. Paused, the state mark after 🟡 still
says which one it waits on; the count says how many.

### Agent kind

These glyphs fill the tree's first cell. Each is named for the agent type it
stands for; `other` covers every other type, custom agents included.

| Glyph | Name | Glyph | Name |
|---|---|---|---|
| 🔩 | general-purpose | 🍴 | fork |
| 🎩 | claude | 🔗 | workflow |
| 🔍 | Explore | 🐚 | shell |
| 📐 | Plan | 🌐 | remote |
| 📚 | claude-code-guide | 🎎 | teammate |
| 📟 | statusline-setup | 👥 | other |

### Agent state

These glyphs fill the tree's second cell: a phase, then an activity within it.

| Glyph | Name | Meaning |
|---|---|---|
| 🟢 | Running | the agent is working |
| 🟡 | Paused | it ended its turn, but work it started is still going |
| ⚫ | Ended | it has finished, for good |

| Phase | Glyph | Name | Meaning |
|---|---|---|---|
| 🟢 | 🤖 | Thinking | the model has the floor |
| 🟢 | 🔧 | Tool | a tool call is waiting on its result |
| 🟢 | 🚦 | Waiting | on a question to you, or on an agent it started |
| 🟡 | 💤 | Agents | an agent under it is still running or not started |
| 🟡 | 💻 | Shell | a background shell it has not heard the end of |
| 🟡 | 📡 | Monitor | a Monitor it has not heard the end of |
| 🟡 | ⛳ | ETA | nothing it can name, but a live ETA in its last message |
| 🟡 | 🥚 | Pending | not started |
| ⚫ | ✅ | Completed | finished, and waiting on nothing |
| ⚫ | ❌ | Failed | ended with an error |
| ⚫ | 🛑 | Killed | stopped |
| ⚫ 🟡 | 💥 | API error | its last answer died on an API error once Claude Code's retries ran out; paused or ended as it otherwise would be |

Claude Code calls an agent completed both when it has finished and when it has
ended its turn to wait. The row reads the agent's transcript and its children
to tell the two apart.

### Agent tree shape

| Glyph | Name | Meaning |
|---|---|---|
| 👶🏻 | Children | how many agents hang directly under it |
| ◯ ├ └ │ | Tree | the panel's tree, drawn again where the figures start in a wide window, so parents and leaves are visible beside their figures |
| ⏺ | Expanded | the selected parent, whose children are showing |

### Receipt rows

| Glyph | Name | Meaning |
|---|---|---|
| 📊 | Receipt | marks every receipt row |
| 🎤 | Prompt | the prompt just answered |
| 🎮 | Session | the session so far |
| 🤏 | Compaction | a compaction, which fires no `Stop` hook of its own |
| 👥 | Late | one row per agent that finished after its prompt's row had printed, led by its name and id |
| 🔺🔖 | Turn | the turn the 🎤 row bills, already answered: the first 8 characters of its `promptId`, then Claude Code's turn index |

## Three rules the display follows

* **Figures never move.** Every value has a fixed width and gets a unit
  instead of more digits, as in `1.2k`, `4.5M` or `1.5h`. A number stays in
  the same place from the first prompt to the thousandth.
* **Brightness shows magnitude.** A figure with no natural ceiling stays dim
  until it matters: 100k tokens, 1k tokens/s, $1, ten minutes or 100 lines.
  Percentages already have a ceiling, so they follow separate rules.
* **Agents are counted.** On the status line and the receipt, the tokens,
  costs, plan shares and times include every subagent, fork and workflow
  agent, each priced at its own model's rates. 🧠 is the exception: it shows
  only the main thread, because it tells you when *this* context window
  needs compacting. Each row of the agent tree counts its own agent alone.

The session status line is designed for terminals 170 columns or wider. On a
narrower terminal the chat text is shortened first, and below about 135
columns the project, path and branch move to a fourth line of their own.
[Layout](docs/layout.md) covers every cell in detail.

## Customizing

Two flags cover most adjustments:

* `--column-rules` draws faint `|` dividers between the status line's columns,
  at 170 columns or wider.
* `--no-mark-spacing` removes the space after each mark, for tighter terminals.

[Options](docs/options.md) lists every flag.

By default, 💳 and 🔜 come from the rate limits that Claude Code includes in
the status line's input. `--usage-source` can take them from elsewhere:

* the Claude Usage Tracker app
* an organization API
* a script of your own

See [Usage sources](docs/usage-sources.md).

## Codex

The program also reports on Codex sessions with `--agent codex`. It prints a
prompt receipt from a Codex `Stop` hook, and a one-shot session status line
for a saved rollout. For the live footer, use Codex's own `/statusline`. Codex does not report per-agent
quota shares, so those fields are left blank rather than estimated. See
[Codex](docs/codex.md) for setup.

## Documentation

| | |
|---|---|
| [Layout](docs/layout.md) | every cell on the three readouts in detail, and the colour rules |
| [Accounting](docs/accounting.md) | how the program derives costs, plan shares and time |
| [Options](docs/options.md) | every flag and environment variable |
| [Usage sources](docs/usage-sources.md) | where plan figures come from, and how to write your own source |
| [Codex](docs/codex.md) | setup and differences for Codex |
| [Glyphs and terminals](docs/glyphs-and-terminals.md) | how to choose a glyph that keeps the columns aligned |
| [Tests](docs/tests.md) | the test suites and what CI runs |
| [Development](docs/development.md) | how the code is organized, and the style rules |

## License

MIT. See [`LICENSE`](LICENSE).
