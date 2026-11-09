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
`$.http.fetch`, the secret held by the host). `CB1` found:

- **The cloud session credit is in that answer:** the window
  `iguana_necktie`, `limit` 250, `used` 245.58, `remaining` 4.42,
  `resets_at` 2026-11-05T07:59Z, read with the session's credential in
  two sessions.
- **The answer has an `extra_usage` key** besides `seven_day`, `limits`
  and `spend`. `CB1` logged keys and dollar windows only, so its figures
  are `CB1b`'s to log.

`CB1b` found, logging at each turn's end:

- **Extra usage is off on this account by the user's choice:**
  `is_enabled` false, `user_disabled` true, `credits_ever_enabled` true,
  `spend_limit_reached` false. Its `monthly_limit`, `used_credits`,
  `utilization`, `currency`, `decimal_places`, `daily` and `weekly` are
  all null while it is off, so the 💸 figures are still unseen.
- **Local turns don't spend the cloud credit:** its `used` stayed at
  245.58 across 2½ hours of this checkout's turns, with no line logged
  after the first. It is spent by cloud sessions alone.
- **The Console refuses that credential:** its organizations request
  answers 403. The Console's credits come from `credits-command` alone.

## The design

- **The reading:** a `credits[]` list beside `buckets[]`, each entry `id`,
  `kind`, `label`, `remaining`, `granted`, `spent`, `currency`,
  `expires_at`, `granted_at`, `applies_to`, as `docs/usage-sources.md`
  gives it. A window or tranche is taken by its fields, never by its
  codename; one missing a field is dropped, not guessed.
- **The cloud session credit:** from the OAuth `usage` answer the mod
  already fetches, at its 5-minute pace, with no setup.
- **The Console credits:** from the `credits.command` option, any program
  printing the `credits[]` JSON, run at the same pace. The mod needs
  nothing more; a user may wrap theirs in `secretspec run`.
- **Shared:** the mod writes the reading to the cache in
  `~/.local/state/coding-agent-usage-line/`, so the Python status line
  shows the same figures without fetching.
- **On the band:** each credit as its glyph, its balance and 🔜 with the
  time to its expiry, drawn when its `show` conditions say, as below.
- **On the rows:** the 🎤 turn, 🤖 agent, 🎮 session and subagent rows
  say which pool paid for their work and how much, as below.

## The credits

| Credit                     | Glyph | Drawn as          | With `original`       | Drawn by default       |
| -------------------------- | ----- | ----------------- | --------------------- | ---------------------- |
| Cloud session credit       | ⛅    | `⛅ $4.4 🔜 15h`  | `⛅ $4.4/250 🔜 15h`  | balance > $0           |
| Console promotional credit | 🎁    | `🎁 $200 🔜 9.6d` | `🎁 $200/200 🔜 9.6d` | balance > $0           |
| Console prepaid credit     | 💵    | `💵 $37`          | `💵 $37/100`          | balance ≤ $20, or expiry < 7 days |
| Extra usage                | 💸    | `💸 $38 🔜 26d`   | `💸 $38/50 🔜 26d`    | spent > $0             |
| Claude Code guest passes   | 🎫    | `🎫 2`            | `🎫 2/3`              | never                  |

- **The figure:** what is left, in `moneyFmt`'s four characters. Extra
  usage's is what is left of the month's cap, its 🔜 the month's reset;
  the guest passes' a count. A prepaid credit's 🔜 is drawn only within
  the amber expiry.
- **No figure:** a credit whose source is unset or failing meets no
  condition; `show-missing` draws it as `?`, as the 💳 row draws a
  missing total.
- **Expired:** kept in the reading, never drawn.
- **Every glyph draws two columns,** with no variation selector.

## The configuration

`credits` is a table beside `rows`. Every condition is one map of
`field`, `op`, `value` and `unit`, the same four keys every time; `op` is
one of `<`, `<=`, `=`, `!=`, `>=`, `>`, and every map names its unit. A
credit is drawn when any one condition in its `show` list holds, and an
empty list never draws it. A list in a configuration file replaces the
lower layers' whole list, as `hide` does.

| `field`   | `unit`                       | Means                                              |
| --------- | ---------------------------- | -------------------------------------------------- |
| `balance` | `usd` or `percent`           | what is left, in dollars or as a share of the original |
| `spent`   | `usd`                        | what it has paid for since its period began        |
| `expiry`  | `days`, `hours` or `minutes` | the time to its expiry                             |

```jsonc
"credits": {
  // Where: "account" on the 💳 row, "row" on a row of their own, or false.
  "place": "account",
  // Each credit is drawn when any one condition in its list holds;
  // an empty list never draws it.  op: "<", "<=", "=", "!=", ">=", ">".
  "show": {
    "cloud":   [{"field": "balance", "op": ">", "value": 0, "unit": "usd"}],
    "promo":   [{"field": "balance", "op": ">", "value": 0, "unit": "usd"}],
    "prepaid": [{"field": "balance", "op": "<=", "value": 20, "unit": "usd"},
                {"field": "expiry", "op": "<", "value": 7, "unit": "days"}],
    "extra":   [{"field": "spent", "op": ">", "value": 0, "unit": "usd"}],
    "passes":  []
  },
  // The colours, by the same conditions, for every credit: red wins.
  "amber": [{"field": "expiry", "op": "<", "value": 7, "unit": "days"},
            {"field": "balance", "op": "<", "value": 20, "unit": "percent"}],
  "red":   [{"field": "expiry", "op": "<", "value": 1, "unit": "days"},
            {"field": "balance", "op": "=", "value": 0, "unit": "usd"}],
  // A credit with no figure, its source failing or unset: "?" or nothing.
  "show-missing": false,
  // Each credit's original amount after its figure: $4.4/250.
  "original": false,
  // A program that prints the credits[] JSON, for the Console's credits.
  "command": null
}
```

To draw a credit always, give it `{"field": "balance", "op": ">=",
"value": 0, "unit": "usd"}`, which every known figure meets.

## Spending on the rows

One pool pays for a session's work at a time, chosen by its credential
and its plan windows:

| The session                                    | Pays                                       | 🎤 turn row                            |
| ---------------------------------------------- | ------------------------------------------ | -------------------------------------- |
| A plan login, its windows under 100%           | the plan                                   | `💰6.4       🧠-42k`, the column blank |
| A plan login, a window at 100%, extra usage on | 💸 extra usage                             | `💰6.4  💸2.1  🧠-42k`                 |
| An API key                                     | 🎁 the promotional credit, then 💵 prepaid | `💰6.4  🎁6.4  🧠-42k`                 |
| A Claude Code on the web session               | ⛅ the cloud credit                        | `💰6.4  ⛅6.4  🧠-42k`                 |

- **The column:** after 💰, the payer's glyph and dollars; blank while
  the plan pays, which 🔋 and 🪫 already show. A turn that crossed into
  another pool shows the part after the crossing; the 🎮 session row
  sums its turns, a figure per pool it used.
- **The amount:** each record's share of 💰, the API-equivalent estimate,
  billed to the pool paying when it was made, so an agent's row bills its
  own records. The 🎮 session row takes the measured fall in the pool's
  balance instead, once two readings bracket the session.

## Decided (2026-11-04, by the user)

1. **The conditions** are `{field, op, value, unit}` maps with the math
   operators, over `balance`, `spent` and `expiry`, as "The
   configuration" has them.
2. **`credits.place`** defaults to `"account"`: the 💳 row, after 🪫.
3. **The cloud session credit's glyph** is ⛅, the one cloud drawn two
   columns wide in every terminal.
4. **The rows' column** follows 💰: the payer's glyph and dollars, blank
   while the plan pays.
5. **The rows' amounts** are each record's share of the 💰 estimate,
   billed to the payer; the 🎮 session row takes the measured fall in the
   balance once two readings bracket the session.

6. **The configuration's shape** is the nested `credits` table, read
   through a `record` option type whose fields may be lists of
   conditions, alone or by credit.
7. **Extra usage's figures** are read as dollars until they are seen with
   extra usage on.

## The build order

1. **`CB1`, the trial.** Once per process, at the mod's start, it logs
   what the session's credential reaches: the OAuth `usage` answer's keys
   with a value and each window with a dollar limit, then the Console's
   organizations and each one's prepaid credits, as figures only, never a
   body. Nothing drawn changes. Its findings are above, and its code is
   out of the mod.
2. **`CB1b`, the second trial.** It logs `extra_usage`'s figures and the
   cloud credit's `used` at each turn's end, as figures only: extra
   usage's cap, spend and reset, and whether a local session moves the
   cloud credit. Its findings are above, and its code is out of the mod.
3. **`CB2`, the reading.** `credits[]` in `docs/usage-sources.md`'s format,
   its parser in both ports, with cases.
4. **`CB3`, the sources.** The cloud credit and extra usage from the OAuth
   answer, asked every 5 minutes apart from the plan windows, and kept per
   signed-in account in a file the Python port reads without asking.
5. **`CB4`, the conditions and the cells.** The conditions evaluated in
   both ports (`coding_agent_usage_line/credits.py`, `mod/src/credits.ts`)
   with shared cases, the five glyphs in `spec/layout.jsonc`, and each
   credit's cell in the mod.
6. **`CB4b`, the credits drawn.** `credits` in `spec/options.jsonc`, the
   defaults file and both ports' configuration readers, through a
   `record` type; the credits on the 💳 row; the Console credits from
   `credits.command`, merged into the kept credits. Its `place` is
   `"account"` or `"none"`: a row of their own, and `show-missing`, are
   left until they're wanted.
7. **`CB6`, the spending column.** The payer of each record, the column on
   the 🎤, 🤖, 🎮 and subagent rows, and the session row's measured
   figure; its cases.
8. **`CB5`, docs and the acceptance check, live.** `docs/layout.md`,
   `docs/options.md`, `docs/usage-sources.md`; then in a session here the
   band shows both credits as the billing pages do, and a `show` of `[]`
   draws none.

## Files

`mod/hooks/usage.ts` and
`mod/src/sources.ts` (the fetch and the reading),
`coding_agent_usage_line/sources.py`, `mod/src/band.ts`,
`spec/options.jsonc` and its generated files, `mod/defaults/config.jsonc`,
`mod/mod-tests/band.test.ts`, `docs/usage-sources.md`, `docs/layout.md`,
`docs/options.md`.
