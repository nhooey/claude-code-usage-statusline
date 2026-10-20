// The mod's configuration, in one place.
//
// What the status line takes as flags (`--usage-source`, `--hide`,
// `--mark-spacing`) the mod takes here, set to what the user's status line
// runs with, so the band and the status line read one source and draw one
// grid while they run side by side (agents/plans/redesign.md, "Where the
// plan figures come from").  A change here is a change to the mod: edit,
// then /reload-plugins.
import type { BandPlace, RowName } from '../src/band.ts'
import { RIGHT_EDGE } from '../src/spec.ts'

export const CONFIG = {
  // The usage source, as --usage-source names it: "claude-usage-tracker"
  // reads the menu-bar app's store; "auto", "native", "none" and
  // "cmd:<path>" as the status line takes them.
  usageSource: "claude-usage-tracker",
  // --account and --account-period, for the source's cache scope.
  account: "default",
  period: "day",
  // --hide paths, `scope[.group[.metric]]` with `*` for any one part.
  // 🔋 the 5-hour limit, 🧠's ٪ of the window, and 🎯 the cache hit rate,
  // in every row (asked 2026-10-19).  Keep subagentStatusLine's --hide
  // flags in ~/.claude/settings.json the same, so the panel stacks.
  // 'name.tag' hides the turn's tag lines, 🔻🔖 under the prompt and the
  // receipt's 🔺🔖, with the blank rows around them.  The account row's
  // 📦 project and 🌿 branch, which 🎮 draws under it (asked 2026-10-20):
  // the status line has no account row, so no flag to match.
  hide: ['*.plan.five_hour', '*.context.share', '*.tokens.cache',
    'account.workspace.project', 'account.workspace.branch'] as
    readonly string[],
  // Which of the band's rows, 🎤 "turn", 🤖 "agent" and 🎮 "session", stay
  // where the band draws them once a turn ends; the receipt stamps the
  // others into the transcript (asked 2026-10-20).  None: the receipt has
  // all three, and the band is empty between turns.
  sticky: [] as readonly RowName[],
  // Where the band's rows are drawn: "hint", under Claude Code's footer
  // line (`-- INSERT -- ⏵⏵ auto mode on …`), or "above", over the prompt,
  // where the band can be collapsed with its [-] and scrolled (asked
  // 2026-10-20, to try them under the footer).  Under the footer there is
  // no [-], and the band's rows and the 💳 row end at the terminal's edge
  // instead of RIGHT_EDGE short of it: keep subagentStatusLine's
  // `--right-edge` the same, 0 for "hint" and 5 for "above", so the panel
  // stacks.
  bandPlace: "hint" as BandPlace,
  // Where the 💳 account is drawn: "row", a row of its own under Claude
  // Code's footer line, in that line's container and in its colours, or
  // "tail", in plain text at the right end of the footer line (asked
  // 2026-10-20, to put it under the line).
  accountPlace: "row" as "row" | "tail",
  // The rows under the footer line drawn with a bottom margin of -1, to
  // take up the blank row Claude Code leaves between the footer and the
  // agent panel's `* main` (asked 2026-10-20, to see whether it can go).
  hintTuck: true,
  // How many columns in from the terminal's left edge Claude Code draws
  // the footer line's container, which the 💳 row and the band's rows
  // under it share: they are drawn that much narrower, so their cells
  // stack on the agent panel's and they end where its rows end (seen live
  // 2026-10-20: drawn at the full width, every cell stood 2 columns right
  // of the panel's).
  hintInset: 2,
  // Draw the footer's tail as a ruler of column digits, each the last digit
  // of the column the mod reckons it lands in, to check the padding in each
  // footer shape: right, it ends on the band's last column (asked
  // 2026-10-20).
  footerRuler: false,
  // Draw the folded row of a message another agent sent, Claude Code's
  // `› Message from @general-purpose (ctrl+o to expand)`, as the sending
  // agent's task and the message's first line instead, `› 🤖 <task>:
  // <line>…`, dim, cut to the terminal's width (asked 2026-10-20).  Off,
  // Claude Code's own row.  ctrl+o shows the whole message either way.
  agentMessageRow: true,
  // How long the agents `$.agent.list()` gave are taken as standing, for
  // that row to find its sender's task in: the row is drawn on every draw
  // of the transcript, and a list each time would cross to the engine
  // each time.  An agent starting or ending lists them again at once.
  agentListMs: 5_000,
  // --mark-spacing and --subscript-decimals.
  markSpacing: true,
  subscriptDecimals: false,
  // The version the mod's caches are keyed by, apart from the Python's
  // digest of its source: a change to the accounting is a new version.
  version: "usage-band 0.2.0",
  // How long scripts/agent_lines.py may take over one piece of an agent's
  // file, its output at most 3 MiB: the first read of a session's agents
  // goes through gigabytes, and runs in that process, outside any hook's
  // 10s budget (asked 2026-10-20, so the first read does not crash it).
  agentLinesTimeoutMs: 300_000,
  // How often a live agent's fold is saved, so a reload reads on from it.
  foldSaveMs: 60_000,
  // How often the band reads its figures again with nothing else
  // happening, so the clocks and the 🔜 resets move while idle.
  tickMs: 30_000,
  // How often it reads again while a main-thread turn runs, so 🛫 and the
  // totals keep up with the clocks (decided 2026-10-19); never more often
  // than readSpacing times as long as the last read took, so a long
  // transcript's reads cannot crowd the session.
  tickRunningMs: 5_000,
  readSpacing: 3,
  // A read that takes longer is logged, with how long each of its steps
  // took, and with slowToast shown as a toast at most once per
  // slowToastMs.  Off: the toast took the footer's line, hiding the 💳
  // account at its right end (seen live 2026-10-20).
  slowReadMs: 2_000,
  slowToast: false,
  slowToastMs: 60_000,
  // How often the band and the footer redraw their clocks (🔧 ⌛ ⛳ 🕐 🔜)
  // against the time now, between reads, without reading anything.
  clockMs: 1_000,
  // How many start lines the store keeps, and as many keys of receipts
  // stamped, newest first: each is a few hundred bytes, and the store
  // holds 4 MiB in all.
  startsKept: 400,
  // How long the receipt waits, from turn.complete, for the transcript to
  // bill the turn just ended (Claude Code writes its records after the
  // Stop hooks), and how often it looks.
  receiptWaitMs: 30_000,
  receiptPollMs: 500,
  // How long the band keeps a done turn's 🎤 and 🎮 rows after its receipt
  // is stamped, so the receipt is there before they go.
  receiptHoldMs: 1_000,
} as const;

// The columns the band's rows and the 💳 row end short of the terminal's
// edge, from CONFIG.bandPlace: RIGHT_EDGE above the prompt, where Claude
// Code draws the band's [-], and 0 under the footer line, where it draws
// none (asked 2026-10-20).  subagentStatusLine's `--right-edge` must say
// the same, so the agent panel's rows stack on the band's.
export const BAND_EDGE = CONFIG.bandPlace === 'hint' ? 0 : RIGHT_EDGE;
