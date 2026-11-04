# The account's dollar credits on the band

Approved to build. Its steps are `CB1` … `CB5` in [the schedule](_schedule.md).

## Why

An account can hold dollar credits apart from its plan windows, each with
an original amount, what is left and an expiry: claude.ai's cloud session
credit ("$4 of $250 left", expiring in a day) and the Claude Console's
promotional API credit ("$199.99 of $200.00"). Today they are seen only
on the two billing pages. The band shows the plan windows; it should show
these beside them, for every user of the mod, with no secret of theirs
held by the mod and no tool such as SecretSpec required.

## Where each figure is

| Credit                    | Answered by                                                    | Fields                                                                                                 |
| ------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| claude.ai cloud session   | `claude.ai/api/organizations/{org}/usage`, the web sign-in     | a window with `limit_dollars`, `used_dollars`, `remaining_dollars`; its `resets_at` is the expiry      |
| Console promotional       | `platform.claude.com/api/organizations/{org}/prepaid/credits`, the Console sign-in | `promo_tranches[]`: `granted_amount_minor_units`, `remaining_amount_minor_units`, `expires_at`, `granted_at`, `name` |

Both endpoints are undocumented. A public balance API was asked for
(`anthropics/claude-code#47574`) and closed as not planned.

`claude.ai`'s `usage` answer has the shape of
`api.anthropic.com/api/oauth/usage`, which the mod already reads with the
session's own credential (`$.session.authorize()`, spent through
`$.http.fetch`, the secret held by the host). Whether that answer carries
the dollar window too, and whether the same credential reaches the
Console, is what `CB1` settles.

## The design

- **The reading:** a `credits[]` list beside `buckets[]`, each entry `id`,
  `label`, `remaining`, `granted`, `currency`, `expires_at`, `granted_at`,
  `applies_to`. A window or tranche is taken by its fields, never by its
  codename; one missing a field is dropped, not guessed.
- **The cloud session credit:** from the OAuth `usage` answer the mod
  already fetches, at its 5-minute pace, with no setup.
- **The Console credit:** from the session's credential if `CB1` shows it
  reaches the Console; else from a `credits-command` option, any program
  printing the `credits[]` JSON, run at the same pace. The mod needs
  nothing more; a user may wrap theirs in `secretspec run`.
- **Shared:** the mod writes the reading to the cache in
  `~/.local/state/coding-agent-usage-line/`, so the Python status line
  shows the same figures without fetching.
- **On the band:** a `rows.credits` row, `true` by default, each grant as
  what is left of the original and the time to its expiry; one expiring
  within a day marked as a nearly full plan window is.

## The build order

1. **`CB1`, the trial.** Once per process, at the mod's start, it logs
   what the session's credential reaches: the OAuth `usage` answer's keys
   with a value and each window with a dollar limit, then the Console's
   organizations and each one's prepaid credits, as figures only, never a
   body. Nothing drawn changes. After `/reload-plugins` the user tells
   the agent, which reads the `trial: credits` lines in
   `~/.local/state/coding-agent-usage-line/usage-band.log`.
2. **`CB2`, the reading.** `credits[]` in `docs/usage-sources.md`'s format,
   its parser in both ports, with cases.
3. **`CB3`, the sources.** The cloud credit from the OAuth answer; the
   Console credit by what `CB1` found, the credential or
   `credits-command`; the cache shared with the Python port.
4. **`CB4`, the row.** `rows.credits` in `spec/options.jsonc`, the
   defaults file and both ports; its cells and row cases.
5. **`CB5`, docs and the acceptance check, live.** `docs/layout.md`,
   `docs/options.md`, `docs/usage-sources.md`; then in a session here the
   row shows both credits as the billing pages do, and turning it off
   draws none.

## Files

`mod/hooks/register.tsx` (the trial), `mod/hooks/edges.ts` and
`mod/src/sources.ts` (the fetch and the reading),
`coding_agent_usage_line/sources.py`, `mod/src/band.ts`,
`spec/options.jsonc` and its generated files, `mod/defaults/config.jsonc`,
`mod/mod-tests/band.test.ts`, `docs/usage-sources.md`, `docs/layout.md`,
`docs/options.md`.
