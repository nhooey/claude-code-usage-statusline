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
  hide: [] as readonly string[],
  // --mark-spacing and --subscript-decimals.
  markSpacing: true,
  subscriptDecimals: false,
  // The version the mod's caches are keyed by, apart from the Python's
  // digest of its source: a change to the accounting is a new version.
  version: "usage-band 0.2.0",
  // How often the band reads its figures again with nothing else
  // happening, so the clocks and the 🔜 resets move while idle.
  tickMs: 30_000,
  // How many receipts the store keeps, newest first: each is a few
  // kilobytes, and the store holds 4 MiB in all.
  receiptsKept: 400,
} as const;
