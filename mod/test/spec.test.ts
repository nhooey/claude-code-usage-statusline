// spec.ts is generated from spec/layout.jsonc; these pin the forms the
// generator writes, which every other module reads.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as spec from "../src/spec.ts";

test("glyphs are literals", () => {
  assert.equal(spec.E_TOK, "🧩");
});

test("colours are hex, and an alias is its target's value", () => {
  assert.equal(spec.F_BLU, "#64aaff");
  assert.equal(spec.F_SPIN, spec.F_RED);
});

test("tables are arrays", () => {
  assert.deepEqual(spec.EAW_WIDE[0], [4352, 4447]);
  assert.deepEqual(spec.WIDTH_PROFILES[1].profiles, ["tmux", "iterm"]);
});
