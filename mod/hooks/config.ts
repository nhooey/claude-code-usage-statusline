// The mod's constants, and the settings it carries until the user's own
// configuration file holds them.
//
// What the mod draws is set by the options (spec/options.jsonc), merged
// from the configuration files over the defaults file
// (defaults/config.jsonc) the way the Python merges them
// (docs/options.md, "Configuration files"; edges.ts, options()).  What
// stays here are the constants no file may set: the version the caches are
// keyed by, and the timings (agents/plans/config-merge.md, Decided 5 and
// 15).  A change here is a change to the mod: edit, then /reload-plugins.
import type { Value } from '../src/config.ts'

export const CONFIG = {
  // The version the mod's caches are keyed by, apart from the Python's
  // digest of its source: a change to the accounting is a new version.
  version: "usage-band 0.2.0",
  // How long scripts/agent_lines.py may take over one piece of an agent's
  // file, its output at most 3 MiB: the first read of a session's agents
  // goes through gigabytes, and runs in that process, outside any hook's
  // 10s budget (asked 2026-10-20, so the first read does not crash it).
  agentLinesTimeoutMs: 300_000,
  // How often a live agent's fold, and the main transcript's, is saved, so
  // a reload reads on from it.
  foldSaveMs: 60_000,
  // How often the band reads its figures again with nothing else
  // happening, so the clocks and the 🔜 resets move while idle; and how
  // often it looks at the configuration files for a change.
  tickMs: 30_000,
  // How often it reads again while a main-thread turn runs, so 🛫 and the
  // totals keep up with the clocks (decided 2026-10-19); never more often
  // than readSpacing times as long as the last read took, so a long
  // transcript's reads cannot crowd the session.
  tickRunningMs: 5_000,
  readSpacing: 3,
  // A read that takes longer is logged, with how long each of its steps
  // took, and with the option slow-toast shown as a toast at most once per
  // slowToastMs.
  slowReadMs: 2_000,
  slowToastMs: 60_000,
  // How often the band and the footer redraw their clocks (🔧 ⌛ ⛳ 🕐 🔜)
  // against the time now, between reads, without reading anything.
  clockMs: 1_000,
  // How long the receipt waits, from turn.complete, for the transcript to
  // bill the turn just ended (Claude Code writes its records after the
  // Stop hooks), and how often it looks.
  receiptWaitMs: 30_000,
  receiptPollMs: 500,
  // How long the band keeps a done turn's 🎤 and 🎮 rows after its receipt
  // is stamped, so the receipt is there before they go.
  receiptHoldMs: 1_000,
  // How long the agents `$.agent.list()` gave are taken as standing, for
  // an agent's message row to find its sender's task in: the row is drawn
  // on every draw of the transcript, and a list each time would cross to
  // the engine each time.  An agent starting or ending lists them again
  // at once.
  agentListMs: 5_000,
  // How many messages that row keeps the sender of, once their words have
  // picked it out of several agents of one name: a message never changes,
  // so its agents' replies are read once and not on every draw.  The
  // oldest goes first.
  agentSenderMemo: 256,
} as const;

// One more layer under the configuration files, named "mod": a setting
// the mod draws with that is not the options' default and that no file
// gives.  Empty: a person's settings are in their own file,
// ~/.config/coding-agent-usage-line/config.jsonc (docs/options.md), which
// the band and the agent panel both read.
export const SETTINGS: { readonly [option: string]: Value } = {}
