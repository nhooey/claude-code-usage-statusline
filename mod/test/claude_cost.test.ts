// claude_cost.ts and claude_cost_render.ts against the cost goldens.
//
// For each cost case in tests/fixtures/cases.json this draws the case's
// committed figures document at its width and flags, as run-cases.py's
// render stage has the Python draw it with --from-figures, and compares
// the systemMessage with tests/golden/cost/<id>.txt byte for byte.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { settings } from "../src/formatting.ts";
import { _cols, _costOpts, renderCostFigures } from "../src/claude_cost.ts";
import type { CostFigures } from "../src/claude_cost.ts";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../..");
const FIXTURES = path.join(REPO, "tests/fixtures");

type Case = {
  id: string; suite: string; env: string; cols: number; flags: string[];
};

/** run-cases.py's fill: the placeholders back to paths.  None of them is
 * drawn, but the document is read as the Python reads it. */
function fill(text: string): string {
  return text.replaceAll("${HOME}", os.homedir())
    .replaceAll("${FIXTURES}", FIXTURES)
    .replaceAll("${SCRATCH}", path.join(os.tmpdir(), "cost-scratch"));
}

const cases: Case[] = JSON.parse(fs.readFileSync(
  path.join(FIXTURES, "cases.json"), "utf-8")).cases
  .filter((c: Case) => c.suite === "cost");

test("every cost case is here", () => {
  assert.equal(cases.length, 87);
});

const savedTz = process.env.TZ;

for (const c of cases) {
  test(c.id, () => {
    const env = JSON.parse(fs.readFileSync(
      path.join(FIXTURES, "env", c.env + ".json"), "utf-8"));
    const fig: CostFigures = JSON.parse(fill(fs.readFileSync(
      path.join(FIXTURES, "figures/cost", c.id + ".json"), "utf-8")));
    // The argv the render stage is run with, then the edge's work: the
    // terminal profile from the case's environment, the switches cli.py
    // applies before anything renders, and the document's zone.
    const argv = ["--agent", "claude", "--mode", "cost", "--cols",
      String(c.cols), ...c.flags];
    const st = settings(env.terminal,
      !argv.includes("--no-mark-spacing"),
      argv.includes("--subscript-decimals"));
    if (fig.clock.tz) process.env.TZ = fig.clock.tz;
    try {
      const opts = _costOpts(argv, _cols(argv, () => {
        throw new Error("no terminal to measure");
      }));
      const got = renderCostFigures(st, fig, opts);
      // run-cases.py's stdout_of: the message, less trailing newlines.
      const want = fs.readFileSync(
        path.join(REPO, "tests/golden/cost", c.id + ".txt"), "utf-8");
      assert.equal(got.replace(/\n+$/, ""), want.replace(/\n+$/, ""));
    } finally {
      if (savedTz === undefined) delete process.env.TZ;
      else process.env.TZ = savedTz;
    }
  });
}

// tests/fixtures/gen/receipt.py's cases: each distinct document drawn by
// the Python's render stage in colour, flush left, without totals, under a
// prefix and label of its own, at widths that cut the labels, and with the
// clock in zones either side of UTC.
const receipt: { [k: string]: any }[] = JSON.parse(fs.readFileSync(
  path.join(FIXTURES, "receipt/cases.json"), "utf-8")).cases;

receipt.forEach((c, i) => {
  test(`receipt ${i}: ${c.figures} @${c.cols} ${c.flags.join(" ")}`, () => {
    const fig: CostFigures = JSON.parse(fill(fs.readFileSync(
      path.join(FIXTURES, "figures/cost", c.figures), "utf-8")));
    const argv = ["--cols", String(c.cols), ...c.flags];
    const st = settings(c.terminal, !argv.includes("--no-mark-spacing"),
      argv.includes("--subscript-decimals"));
    process.env.TZ = c.tz;
    try {
      const opts = _costOpts(argv, _cols(argv, () => null));
      assert.equal(renderCostFigures(st, fig, opts), c.out);
    } finally {
      if (savedTz === undefined) delete process.env.TZ;
      else process.env.TZ = savedTz;
    }
  });
});
