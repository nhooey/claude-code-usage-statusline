// The mod's configuration, in one place.
//
// What the status line takes as flags (`--usage-source`, `--hide`,
// `--mark-spacing`) the mod takes here, set to what the user's status line
// runs with, so the band and the status line read one source and draw one
// grid while they run side by side (agents/plans/redesign.md, "Where the
// plan figures come from").  A change here is a change to the mod: edit,
// then /reload-plugins.

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
  hide: ['*.plan.five_hour', '*.context.share', '*.tokens.cache'] as
    readonly string[],
  // --mark-spacing and --subscript-decimals.
  markSpacing: true,
  subscriptDecimals: false,
  // The version the mod's caches are keyed by, apart from the Python's
  // digest of its source: a change to the accounting is a new version.
  version: "usage-band 0.2.0",
  // How often the band reads its figures again with nothing else
  // happening, so the clocks and the 🔜 resets move while idle.
  tickMs: 30_000,
  // How often it reads again while a main-thread turn runs, so 🛫 and the
  // totals keep up with the clocks (decided 2026-10-19); never more often
  // than readSpacing times as long as the last read took, so a long
  // transcript's reads cannot crowd the session.
  tickRunningMs: 5_000,
  readSpacing: 3,
  // A read that takes longer is logged and shown as a toast, with how
  // long each of its steps took; a toast at most once per slowToastMs.
  slowReadMs: 2_000,
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
