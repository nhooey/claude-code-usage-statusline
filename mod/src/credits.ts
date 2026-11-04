// The account's credits against the `credits` option's conditions, and
// each credit's cell on the 💳 row.
//
// A condition is one map of `field`, `op`, `value` and `unit`
// (agents/plans/credit-balances.md, "The configuration"):
//
//     {"field": "balance", "op": "<=", "value": 20, "unit": "usd"}
//
// `balance` is what is left, in `usd` or as a `percent` of what was
// granted; `spent` is what the credit has paid for, in `usd`; `expiry` is
// the time to its expiry, in `days`, `hours` or `minutes`.  A condition
// whose figure the credit doesn't have, or that is malformed, doesn't hold.
// coding_agent_usage_line/credits.py is the conditions' twin, held to them
// by tests/fixtures/sources/conditions.json.

import { untilReset } from "./cells.ts";
import { moneyFmt } from "./formatting.ts";
import type { Settings } from "./formatting.ts";
import { isDict } from "./py.ts";
import type { Dict } from "./py.ts";
import {
  E_CLOUD, E_EXTRA, E_PASSES, E_PREPAID, E_PROMO, E_RESET,
} from "./spec.ts";
import { span } from "./spans.ts";
import type { Span } from "./spans.ts";

const OPS: { [op: string]: (a: number, b: number) => boolean } = {
  "<": (a, b) => a < b, "<=": (a, b) => a <= b, "=": (a, b) => a === b,
  "!=": (a, b) => a !== b, ">=": (a, b) => a >= b, ">": (a, b) => a > b,
};
const UNITS: { [field: string]: readonly string[] } = {
  balance: ["usd", "percent"], spent: ["usd"],
  expiry: ["days", "hours", "minutes"],
};
const SECONDS: { [unit: string]: number } = {
  days: 86400, hours: 3600, minutes: 60,
};

function figure(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Whether `credit`'s expiry has passed: it is never drawn then. */
export function expired(credit: unknown, now: number): boolean {
  const at = isDict(credit) ? figure(credit.expires_at) : null;
  return at !== null && at <= now;
}

function measure(credit: Dict, field: string, unit: string, now: number):
    number | null {
  if (field === "balance" && unit === "usd") return figure(credit.remaining);
  if (field === "balance") {
    const left = figure(credit.remaining), granted = figure(credit.granted);
    return left === null || !granted ? null : left / granted * 100;
  }
  if (field === "spent") return figure(credit.spent);
  const at = figure(credit.expires_at);
  return at === null ? null : (at - now) / SECONDS[unit]!;
}

/** Whether one condition holds of `credit` at `now`. */
export function met(credit: unknown, condition: unknown, now: number):
    boolean {
  if (!isDict(credit) || !isDict(condition)) return false;
  const { field, op, unit } = condition;
  const value = figure(condition.value);
  if (typeof field !== "string" || !Object.hasOwn(UNITS, field) ||
      typeof unit !== "string" || !UNITS[field]!.includes(unit) ||
      typeof op !== "string" || !Object.hasOwn(OPS, op) || value === null) {
    return false;
  }
  const got = measure(credit, field, unit, now);
  return got !== null && OPS[op]!(got, value);
}

/** Whether `credit` is drawn: any one condition holds, and it hasn't
 * expired.  An empty list never draws it. */
export function shown(credit: unknown, conditions: unknown, now: number):
    boolean {
  if (expired(credit, now) || !Array.isArray(conditions)) return false;
  return conditions.some((c) => met(credit, c, now));
}

/** "red", "amber" or null: red wins. */
export function colour(credit: unknown, amber: unknown, red: unknown,
  now: number): "red" | "amber" | null {
  for (const [name, conditions] of [["red", red], ["amber", amber]] as
       const) {
    if (Array.isArray(conditions) &&
        conditions.some((c) => met(credit, c, now))) return name;
  }
  return null;
}

const GLYPHS: { [kind: string]: string } = {
  cloud: E_CLOUD, promo: E_PROMO, prepaid: E_PREPAID, extra: E_EXTRA,
  passes: E_PASSES,
};

/** A credit's figure: dollars in moneyFmt's four characters after `$`, or
 * a count of passes. */
function amount(st: Settings, kind: string, value: number): string {
  return kind === "passes" ? String(Math.trunc(value))
    : moneyFmt(st, value);
}

/** One credit's cell: its glyph, what is left, with `original` what was
 * granted after a slash, and 🔜 the time to its expiry.  A prepaid
 * credit's 🔜 is drawn only while it is coloured, so a credit that lasts a
 * year doesn't carry its year.  The figure takes the colour. */
export function creditCell(st: Settings, credit: Dict, tint: "red" |
  "amber" | null, original: boolean, now: number): Span[] {
  const kind = String(credit.kind);
  const left = figure(credit.remaining) ?? 0;
  const granted = figure(credit.granted);
  let text = (kind === "passes" ? "" : "$") + amount(st, kind, left);
  if (original && granted !== null) text += "/" + amount(st, kind, granted);
  const out: Span[] = [span((GLYPHS[kind] ?? "") + " "),
    span(text, tint === "red" ? "F_RED" : tint === "amber" ? "F_AMB" : null)];
  const reset = untilReset(st, figure(credit.expires_at), now);
  if (reset !== null && (kind !== "prepaid" || tint !== null)) {
    out.push(span(" " + E_RESET + " " + reset));
  }
  return out;
}

/** The credits the 💳 row draws and the colour of each, in the reading's
 * order, by the `credits` option: none with `place` "none"; else each
 * credit whose kind's `show` list holds, unexpired. */
export function drawnCredits(credits: unknown, option: {
  readonly place: string;
  readonly show: { readonly [kind: string]: unknown };
  readonly amber: unknown; readonly red: unknown;
}, now: number): { credit: Dict; tint: "red" | "amber" | null }[] {
  if (option.place === "none" || !Array.isArray(credits)) return [];
  return credits.filter((c): c is Dict => isDict(c) &&
    shown(c, option.show[String(c.kind)] ?? [], now))
    .map((credit) => ({ credit,
      tint: colour(credit, option.amber, option.red, now) }));
}
