// mod-tests/fixtures.gen.ts, the fixture files the harness tests answer
// `$.fs` with, is what tools/gen-mod-fixtures.ts writes from the fixtures
// now: a fixture that changed without it would leave the harness testing
// the mod against old bytes.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { render } from "../tools/gen-mod-fixtures.ts";

const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../mod-tests/fixtures.gen.ts");

test("mod-tests/fixtures.gen.ts is current", () => {
  assert.ok(fs.readFileSync(OUT, "utf-8") === render(),
    "stale: run node mod/tools/gen-mod-fixtures.ts");
});
