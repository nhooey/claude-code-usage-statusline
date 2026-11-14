# coding-agent-usage-line

[![tests](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml/badge.svg)](https://github.com/nhooey/claude-code-usage-statusline/actions/workflows/tests.yml)

Three readouts for [Claude Code](https://claude.com/claude-code) that show what
your session is costing, how much of your plan it has used, where the time went,
and what every subagent is doing. They share one grid, so every figure stays on
the same screen column on every row, and you can switch tabs and compare
sessions at a glance.

## Above the prompt and under the footer line

Drawn by the `usage-band` mod in [`mod/`](mod/README.md), one scope a row.
Above the prompt, the session's threads as a tree: 🎮 the session at its
root, 🎤 the turn while it runs, then 🧵 the main thread with the
subagents it started under it; under Claude Code's own footer line, the 💳
account, just over the agent panel, whose rows Claude Code draws itself.
Here the two places are drawn together, the prompt between them left out:

```
  ⊟ 🎮 📦repo 🌿golden-clean                  💰 35                🧩▴2.7M ▾841k  🎯98٪  ⌛9.3h         🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀  🔋 3.8٪   🪫 8.45٪
  ├─ 🎤🟢 turn               🤖O⁵🏃  🛫 200   💰6.4   🧠-42k  -4٪  🧩▴525k ▾151k  🎯98٪  ⌛  5m         🤖⠶⠆ 🔧⠆⠀ 🚦⠀⠀  🔋 1.2٪   🪫 1.56٪
  ╰⊟ 🧵🟢 main  Checking     🤖O⁵🏃  🤖   3m  💰 35   🧠115k  11٪  🧩▴2.7M ▾841k  🎯98٪  ⌛9.3h         🤖⠆⠀ 🔧⠄⠀ 🚦⠶⠄  🔋 3.8٪   🪫 8.45٪
     ├─ 🎩🟢 Clover          🤖O⁵🏃  🤖  13m  💰0.0   🧠 32k  16٪  🧩▴7.1k ▾400   🎯93٪  ⌛ 15m         🤖⠶⠶ 🔧⠀⠀ 🚦⠀⠀  🔋  .01٪  🪫  .011٪
     ├─ 🔍🟢 Marigold  Run…  🤖O⁵🏃  🔧  11m  💰0.1   🧠 32k  16٪  🧩▴ 14k ▾800   🎯93٪  ⌛ 12m ⛳ +50s 🤖⠄⠀ 🔧⠶⠦ 🚦⠀⠀  🔋  .02٪  🪫  .022٪  💾 +  9  -  4
     ├─ 👥🟢 Willow          🤖H⁴    🤖 8.3m  💰0.0   🧠 10    0٪  🧩▴ 10  ▾ 10   🎯 0٪  ⌛ 10m         🤖⠶⠶ 🔧⠀⠀ 🚦⠀⠀  🔋  .00٪  🪫  .000٪
     ╰⊞ … 4 more                     🏃   3   💰0.1                🧩▴ 20k ▾1.7k  🎯95٪  ⌛ 14m         🤖⠦⠀ 🔧⠄⠀ 🚦⠶⠀  🔋  .02٪  🪫  .027٪
  -- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle)
  📁~/src/statusline-fixture/deep/tree                                                    💳 🔋  15٪ 🔜 6.7m  🪫  87٪ 🔜 1.9d    📅 2026-08-16  🕐 02:23:20
```

Read these three first:

* **🎮 💰 35**: the session has cost $35 at API prices.
* **💳 🔋 15٪ 🔜 6.7m**: the account has used 15٪ of its 5-hour window, which
  resets in 6.7 minutes. 🪫 is the same for the weekly window.
* **🧵 🧠115k 11٪**: the main thread's context holds 115k tokens, 11٪ of the
  window.

| Row | Label | Scope | Place |
|---|---|---|---|
| 🎮 | the mark, then 📦 🌿 🔀 | the main thread and every agent | above the prompt, the tree's root |
| 🧵 | the mark, its state, 📨 with the messages waiting for its next turn, `main` and its latest progress update | the main thread alone | above the prompt, under 🎮 |
| subagents | each one's head, name and latest progress update | each subagent alone | above the prompt, under the thread that started it; between turns, those running or paused |
| 🎤 | the mark and its state | the turn | above the prompt, last, while a turn runs |
| 💳 | 📁 Directory · 🎨 Style · 💳 Account · 🔋 🪫 Windows · 🔜 Resets · 📅 Date · 🕐 Clock | the account and where the session works | under the footer line |

Each row's place is `rows` in the
[configuration files](docs/options.md#configuration-files); see
[Layout](docs/layout.md#the-rows).

Every row's figures, left to right: 🤖 Model · 🛫 Rate or Doing · 💰 Cost ·
🧠 Context · 🧩 Tokens · 🎯 Hits · ⌛ Elapsed · ⛳ ETA · 🤖 Thinking · 🔧 Tools ·
🚦 Waiting · 🔋 5-hour · 🪫 Weekly · 💾 Diff.

## Prompt receipt

Stamped by the mod as each turn ends, in place of Claude Code's `✻ Worked for
…` line, and kept in the transcript: the 🎤 row as it stood when the turn
ended, dim, then the turn's tag. 🧵 and 🎮 stay live on screen, and
`rows` can stamp them too.

```
                         🎤                   💰0.2   🧠+21k +10٪  🧩▴ 18k ▾3.5k  🎯97٪  ⌛  3m         🤖⠶⠄ 🔧⠦⠀ 🚦⠀⠀  🔋  .03٪  🪫  .043٪

🔺🔖 8f37748e #12  💳 🔋  41٪  🪫  63٪  📅 2026-08-16  🕐 02:23:20
```

The prompt that opened the turn carries the same tag under it, 🔻🔖, with
the account's limits as the turn started, so the two lines side by side
show what the turn took from each plan window.

## Install

You need Python 3.9 or newer. The program uses only the standard library, so
there is nothing to install beyond a clone:

```sh
git clone https://github.com/nhooey/claude-code-usage-statusline.git ~/src/claude-code-usage-statusline
```

The rows above the prompt and under the footer line, and the receipt, are
the mod's. Install it from
the clone, which Claude Code then reads in place:

```sh
cd ~/src/claude-code-usage-statusline
claude plugin marketplace add "$PWD"
claude plugin install usage-band@claude-code-usage-statusline
```

Its settings, such as the usage source and what it hides, are in the
[configuration files](docs/options.md#configuration-files);
[`mod/README.md`](mod/README.md) has the rest.

Every setting's default is in one file,
[`mod/defaults/config.jsonc`](mod/defaults/config.jsonc), which both the
Python program and the mod read at every run. To change settings, copy it
and edit the copy; a diff against the repository's file then shows exactly
what you changed:

```sh
mkdir -p ~/.config/coding-agent-usage-line
cp mod/defaults/config.jsonc ~/.config/coding-agent-usage-line/config.jsonc
diff mod/defaults/config.jsonc ~/.config/coding-agent-usage-line/config.jsonc
```

A project's settings go in its own `.config/coding-agent-usage-line/`
instead; see [Configuration files](docs/options.md#configuration-files).

For ⛳ ETAs, link the skill that has agents report them, and tell them to use
it:

```sh
ln -s ~/src/claude-code-usage-statusline/skills/coding-agent-usage-line-report-eta ~/.claude/skills/
echo 'For any task you expect to take more than about a minute, as the main agent or as a subagent, follow the `coding-agent-usage-line-report-eta` skill.' >> ~/.claude/CLAUDE.md
```

## Legend

The legend has one table per topic. Each glyph has a name, and a ✓ marks each
readout that draws it: the mod's rows, above the prompt and under the
footer line, the subagent rows and the receipt. Where a glyph means something
different on one readout, the table says so.

### Rows

| Glyph | Name | Meaning | Rows | Subagent | Receipt |
|---|---|---|:-:|:-:|:-:|
| 💳 | Account | the plan's own figures for the whole account, on every device, and where the session works; under the footer line | ✓ | | |
| 🎤 | Turn | the turn; above the prompt while it runs | ✓ | | ✓ |
| 🧵 | Main thread | the main thread alone; in the band's tree under 🎮; on the receipt when `rows` stamps it | ✓ | | ✓ |
| 🎮 | Session | the main thread and every agent; the root of the band's tree above the prompt; on the receipt when `rows` stamps it | ✓ | | ✓ |
| ⊟ ⊞ | Fold | in the band's tree, a row with children, opened or folded; `✅ N done` and `… N more` are folded | ✓ | | |

### Chat and project

| Glyph | Name | Meaning | Rows | Subagent | Receipt |
|---|---|---|:-:|:-:|:-:|
| 🎨 | Style | output style, when not the default, on 💳 | ✓ | | |
| 🔀 | PR | pull request number, on 💳 | ✓ | | |
| 📨 | Queue | messages sent to the agent and not yet delivered, Claude Code's "N queued"; on the 🧵 row, messages waiting for the main thread's next turn | ✓ | ✓ | |
| 📦 | Project | the project, on 💳; in a worktree, the main repository | ✓ | | |
| 📁 | Directory | current directory, on 💳, the project's root drawn as 📦 | ✓ | | |
| 🌿 | Branch | branch, clean tree, on 💳; on a subagent row, the branch of a worktree the agent works in apart from the session's | ✓ | ✓ | |
| 🍂 ✱ | Dirty | branch, uncommitted changes, on 💳 | ✓ | | |
| 💾 | Diff | lines added and removed; blank where none were | ✓ | ✓ | ✓ |
| 📅 | Date | today's date; on the receipt, when it was stamped | ✓ | | ✓ |
| 🕐 | Clock | the time; on the receipt, when it was stamped | ✓ | | ✓ |

### Model

| Glyph | Name | Meaning | Rows | Subagent | Receipt |
|---|---|---|:-:|:-:|:-:|
| 🤖 `O⁵` | Model | family initial and major version, such as `O⁵` Opus 5, `S⁵` Sonnet 5 or `H⁴` Haiku 4.5; on the rows, the turn's | ✓ | ✓ | |
| 🐢 | Low | reasoning effort `low` | ✓ | ✓ | |
| 🚶 | Medium | reasoning effort `medium` | ✓ | ✓ | |
| 🏃 | High | reasoning effort `high` | ✓ | ✓ | |
| 🚀 | Xhigh | reasoning effort `xhigh` | ✓ | ✓ | |
| 🔥 | Max | reasoning effort `max` | ✓ | ✓ | |

### Cost and tokens

| Glyph | Name | Meaning | Rows | Subagent | Receipt |
|---|---|---|:-:|:-:|:-:|
| 💰 | Cost | cost in dollars, at API prices | ✓ | ✓ | ✓ |
| `~` | Estimate | a figure partly estimated: 💰 with a compaction in it, 🧠 read from one | ✓ | | ✓ |
| 🧩 | Tokens | tokens in and out | ✓ | ✓ | ✓ |
| ▴ | Input | billable-equivalent input tokens | ✓ | ✓ | ✓ |
| ▾ | Output | output tokens | ✓ | ✓ | ✓ |
| 🛫 | Rate | the main thread's tokens per second, on the 🎤 row; on a subagent row, a shell's | ✓ | ✓ | |
| 🔧 🚦 🤖 … | Doing | in 🛫's column, what the thread is doing and for how long: 🔧 a tool, 🚦 waiting on you or an agent, 🤖 the model, which shows the token rate until it has written nothing for a minute (amber from ten). On a subagent row, with the paused and ended marks too | ✓ | ✓ | |
| 🎯 | Hits | prompt-cache hit rate | ✓ | ✓ | ✓ |

### Context

| Glyph | Name | Meaning | Rows | Subagent | Receipt |
|---|---|---|:-:|:-:|:-:|
| 🧠 | Context | context size and share of the window; on the 🎤 row, how much the turn grew it | ✓ | ✓ | ✓ |
| 🤏 | Compactions | how often the agent's window has been compacted | | ✓ | |

### Time

| Glyph | Name | Meaning | Rows | Subagent | Receipt |
|---|---|---|:-:|:-:|:-:|
| ⌛ | Elapsed | how long the row's scope has run; on a subagent row, the agent's age | ✓ | ✓ | ✓ |
| ⛳ | ETA | time the answer or agent says it has left; on the receipt, the turn's last report | ✓ | ✓ | ✓ |
| 🤖 | Thinking | time with the model | ✓ | ✓ | ✓ |
| 🔧 | Tools | time inside tools | ✓ | ✓ | ✓ |
| 🚦 | Waiting | time waiting on you, or on agents it started | ✓ | ✓ | ✓ |
| ⠄ ⠆ ⠦ ⠶ | Gauge | that figure's share of the three | ✓ | ✓ | ✓ |

* **🤖 🔧 🚦 are gauges** with eight dots between the three, so
  `🤖⠶⠄ 🔧⠆⠀ 🚦⠄⠀` means five eighths thinking, two in tools and one waiting.
  On the main thread's row and a subagent's they share out ⌛. The 🎤 and 🎮
  rows sum agent-seconds, which can outrun the wall clock, so there they are
  proportions of themselves.
* **Each row counts its own thread.** A parent waiting on the agents it
  started reads that time as 🚦. So do `AskUserQuestion`, `ExitPlanMode` and
  `Agent` calls.
* **⛳ comes from a skill.** Agents report their time left through the
  [`coding-agent-usage-line-report-eta`](skills/coding-agent-usage-line-report-eta/SKILL.md)
  skill (see [ETA](docs/layout.md#eta)). ⛳ is blank until a report
  arrives and after the answer finishes. A parent's ETA is never earlier
  than that of any agent it still has running.

### Plan windows

| Glyph | Name | Meaning | Rows | Subagent | Receipt |
|---|---|---|:-:|:-:|:-:|
| 🔋 | 5-hour | share of the 5-hour window | ✓ | ✓ | ✓ |
| 🪫 | Weekly | share of the weekly window | ✓ | ✓ | ✓ |
| 🔜 | Reset | time until the window resets, on the 💳 row | ✓ | | |
| 💯 | Full | a full 100٪ | ✓ | ✓ | ✓ |
| `?` | Unknown | a share that cannot be derived yet | ✓ | ✓ | ✓ |

* **The 💳 row's shares are the plan's own figure.** They come from Claude
  Code or another [usage source](docs/usage-sources.md).
* **Every other row's are estimates.** The program prices the row's requests
  and divides by a dollars-per-percent rate calibrated from this machine's
  history. See [Accounting](docs/accounting.md).

### Background tasks

| Glyph | Name | Meaning | Rows | Subagent | Receipt |
|---|---|---|:-:|:-:|:-:|
| 💻 | Shells | background shells it started and has not heard the end of | | ✓ | |
| 📡 | Monitors | Monitors it started and has not heard the end of | | ✓ | |

Both are drawn while the agent runs and while it is paused, and not once it
has failed or been killed. Paused, the state mark after 🟡 still says which
one it waits on; the count says how many.

### Agent kind

These glyphs open a subagent row. Each is named
for the agent type it
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

A subagent row's phase follows its kind; what the agent is doing within it fills
the 🛫 column, with how long it has been doing it.

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

### Subagent rows

| Glyph | Name | Meaning |
|---|---|---|
| 👶🏻 | Children | how many agents hang directly under it |

### Turn tags

| Glyph | Name | Meaning |
|---|---|---|
| 🔻🔖 | Start | under a prompt, the turn it opens: the first 8 characters of its `promptId`, then Claude Code's turn index, the account's 💳 🔋 and 🪫 as it started, and when it started |
| 🔺🔖 | End | under the receipt, the turn it bills, already answered, the account's 💳 🔋 and 🪫 as it was stamped, and when it was stamped |
| `› 🤖📨` | Message | a message from another agent, folded: the sender's task in bold, then the message's first line, dim; where several agents share the sender's name, the one whose last reply holds that line |

## Three rules the display follows

* **Figures never move.** Every value has a fixed width and gets a unit
  instead of more digits, as in `1.2k`, `4.5M` or `1.5h`. A number stays in
  the same place from the first prompt to the thousandth.
* **Brightness shows magnitude.** A figure with no natural ceiling stays dim
  until it matters: 100k tokens, 1k tokens/s, $1, ten minutes or 100 lines.
  Percentages already have a ceiling, so they follow separate rules.
* **Agents are counted.** On the 🎤 and 🎮 rows, the tokens, costs, plan
  shares and times include every subagent, fork and workflow agent, each
  priced at its own model's rates. The 🧵 row is the main thread alone,
  and its 🧠 tells you when *this* context window needs compacting. Each
  subagent row counts its own agent alone.

On a narrow terminal each row's label is shortened first, down to 12
columns; then whole columns drop from every row at once, least important
first, so the grid never breaks. [Layout](docs/layout.md) covers every cell
in detail.

## Customizing

`hide` in a [configuration file](docs/options.md#configuration-files),
`scope[.group[.metric]]`, hides a row, a group of cells or one cell, the
same path on every readout. The defaults hide nothing, as in the renders
above. See [Hiding](docs/layout.md#hiding).

[Options](docs/options.md) lists every flag.

The 💳 row's figures come from the usage source the mod is configured with
(`usage-source`, `auto` by default), and the Python program's from
`--usage-source`. Besides the rate limits Claude Code reports, either can
take them from:

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
