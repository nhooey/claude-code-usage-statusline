// options_spec.ts is generated from spec/options.jsonc; these pin the forms
// the generator writes: the records `as const`, and an Options type that
// the mod's defaults, read from them, fill.
import { test } from "node:test";
import assert from "node:assert/strict";
import { OPTIONS, type Options } from "../src/options_spec.ts";

test("the records keep their literal values", () => {
  assert.equal(OPTIONS["live-place"].default, "footer");
  assert.deepEqual(OPTIONS["live-place"].items, ["footer", "above"]);
  assert.equal(OPTIONS["usage-source"].flag, "--usage-source");
  assert.equal(OPTIONS.rows.default.turn.live, "running");
  assert.equal(OPTIONS.rows.default.agent.live, "always");
});

test("every option the mod reads has a default of its type", () => {
  const d = OPTIONS;
  // Written out by hand, so a record whose default stops fitting its
  // generated type fails the typecheck here.
  const defaults: Options = {
    usageSource: d["usage-source"].default,
    account: d.account.default,
    accountPeriod: d["account-period"].default,
    rightEdge: d["right-edge"].derived.map[d["live-place"].default],
    hide: d.hide.default,
    markSpacing: d["mark-spacing"].default,
    subscriptDecimals: d["subscript-decimals"].default,
    livePlace: d["live-place"].default,
    rows: d.rows.default,
    accountPlace: d["account-place"].default,
    hintTuck: d["hint-tuck"].default,
    hintInset: d["hint-inset"].default,
    footerRuler: d["footer-ruler"].default,
    agentMessageRow: d["agent-message-row"].default,
    slowToast: d["slow-toast"].default,
    startsKept: d["starts-kept"].default,
  };
  const mod = Object.entries(OPTIONS)
    .filter(([, o]) => (o.ports as readonly string[]).includes("mod"))
    .map(([name]) => name.replace(/-(\w)/g, (_, c: string) => c.toUpperCase()));
  assert.deepEqual(Object.keys(defaults).sort(), mod.sort());
  assert.equal(defaults.rightEdge, 2);
});
