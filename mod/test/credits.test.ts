// Each credit's cell on the 💳 row, as creditCell draws it.  The
// conditions are the shared cases' (sources.test.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { creditCell, drawnCredits } from "../src/credits.ts";
import { settings } from "../src/formatting.ts";
import type { Span } from "../src/spans.ts";

const st = settings({}, true, false);
const NOW = 1_793_800_000;
const text = (spans: Span[]) => spans.map((s) => s.text).join("");
const tints = (spans: Span[]) => spans.map((s) => s.colour ?? null);

test("each credit's glyph, figure and expiry", () => {
  const cloud = { id: "c", kind: "cloud", remaining: 4.42, granted: 250,
    expires_at: NOW + 15 * 3600 };
  assert.equal(text(creditCell(st, cloud, null, false, NOW)),
    "⛅ $4.4 🔜 15h");
  assert.equal(text(creditCell(st, cloud, null, true, NOW)),
    "⛅ $4.4/250 🔜 15h");
  const promo = { id: "p", kind: "promo", remaining: 200, granted: 200,
    expires_at: NOW + 9.6 * 86400 };
  assert.equal(text(creditCell(st, promo, null, true, NOW)),
    "🎁 $200/200 🔜 9.6d");
  const passes = { id: "g", kind: "passes", remaining: 2, granted: 3 };
  assert.equal(text(creditCell(st, passes, null, true, NOW)), "🎫 2/3");
  const extra = { id: "x", kind: "extra", remaining: 12, granted: 50,
    spent: 38 };
  assert.equal(text(creditCell(st, extra, null, false, NOW)), "💸 $12.0");
});

test("a prepaid credit's expiry only while it is coloured, and the figure " +
  "takes the colour", () => {
  const prepaid = { id: "pp", kind: "prepaid", remaining: 37, granted: 100,
    expires_at: NOW + 200 * 86400 };
  assert.equal(text(creditCell(st, prepaid, null, false, NOW)), "💵 $37.0");
  const amber = creditCell(st, { ...prepaid, expires_at: NOW + 3 * 86400 },
    "amber", false, NOW);
  assert.equal(text(amber), "💵 $37.0 🔜 3d");
  assert.deepEqual(tints(amber), [null, "F_AMB", null]);
  assert.deepEqual(tints(creditCell(st, prepaid, "red", false, NOW)),
    [null, "F_RED", null]);
});

test("the credits drawn: by kind's show list, unexpired, with each colour, " +
  "and none with place none", () => {
  const option = {
    place: "account",
    show: { cloud: [{ field: "balance", op: ">", value: 0, unit: "usd" }],
      promo: [] },
    amber: [{ field: "balance", op: "<", value: 20, unit: "percent" }],
    red: [{ field: "balance", op: "=", value: 0, unit: "usd" }],
  };
  const credits = [
    { id: "c", kind: "cloud", remaining: 4.4, granted: 250 },
    { id: "d", kind: "cloud", remaining: 0, granted: 250 },
    { id: "e", kind: "cloud", remaining: 9, expires_at: NOW },
    { id: "p", kind: "promo", remaining: 200, granted: 200 },
    { id: "x", kind: "extra", remaining: 12, spent: 38 }];
  assert.deepEqual(drawnCredits(credits, option, NOW).map((d) =>
    [d.credit.id, d.tint]), [["c", "amber"]]);
  assert.deepEqual(drawnCredits(credits, { ...option, place: "none" }, NOW),
    []);
  assert.deepEqual(drawnCredits(null, option, NOW), []);
});
