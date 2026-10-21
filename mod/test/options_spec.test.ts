// options_spec.ts is generated from spec/options.jsonc; these pin the forms
// the generator writes: the records `as const`, with no default for an
// option a file may set (its default is the defaults file's alone), and an
// Options type that the defaults file, merged, fills.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { OPTIONS, type Options } from "../src/options_spec.ts";
import { DEFAULTS_REL, merge, optionsOf, parseDefaults } from "../src/config.ts";

test("the records keep their literal values", () => {
  assert.deepEqual(OPTIONS["live-place"].items, ["footer", "above"]);
  assert.equal(OPTIONS["usage-source"].flag, "--usage-source");
  assert.deepEqual(OPTIONS.rows.rows,
    ["turn", "agent", "session", "tag", "account"]);
  assert.equal(OPTIONS.mode.default, "status");
});

test("no option a file may set has a default in the spec", () => {
  for (const [name, o] of Object.entries(OPTIONS)) {
    assert.equal("default" in o, !o.file, name);
  }
});

test("the defaults file, merged, fills every option the mod reads", () => {
  const p = path.join(import.meta.dirname, "..", DEFAULTS_REL);
  const options: Options = optionsOf(merge([], [],
    parseDefaults(p, fs.readFileSync(p, "utf8"))));
  const mod = Object.entries(OPTIONS)
    .filter(([, o]) => (o.ports as readonly string[]).includes("mod"))
    .map(([name]) => name.replace(/-(\w)/g, (_, c: string) => c.toUpperCase()));
  assert.deepEqual(Object.keys(options).sort(), mod.sort());
  assert.equal(options.rightEdge, 2);
  assert.equal(options.rows.turn.live, "running");
});
