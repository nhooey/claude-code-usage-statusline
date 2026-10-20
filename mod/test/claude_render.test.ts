// claude_render.ts and figures.ts against the status goldens.
//
// Each status case in tests/fixtures/cases.json has a committed figures
// document and a golden, and tests/run-cases.py's render stage draws the
// one and compares it with the other.  This does the same through the
// TypeScript: the document's placeholders filled as run-cases.py fills
// them, the settings from the case's environment and flags, and the drawn
// text compared byte for byte, less trailing newlines, which the shell
// suites' $( ) dropped.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { renderStatusFigures, statusSettings } from "../src/figures.ts";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../..");
const FIXTURES = path.join(REPO, "tests/fixtures");
const GOLDEN = path.join(REPO, "tests/golden/status");
// What os.path.expanduser("~") reads, both to fill ${HOME} and to show the
// working directory under it as "~".
const HOME = process.env.HOME || os.homedir();
// Any directory does: only the repositories' basenames are drawn.
const SCRATCH = "/tmp/claude-golden-status.scratch";

type Case = {
  id: string; suite: string; env: string; flags: string[]; cols: number;
};

function fill(text: string): string {
  return text.replaceAll("${HOME}", HOME).replaceAll("${FIXTURES}", FIXTURES)
    .replaceAll("${SCRATCH}", SCRATCH);
}

function rstripNewlines(s: string): string {
  return s.replace(/\n+$/, "");
}

const cases = (JSON.parse(fs.readFileSync(path.join(FIXTURES, "cases.json"),
  "utf-8")).cases as Case[]).filter((c) => c.suite === "status");

test("every status case has its figures and golden", () => {
  assert.equal(cases.length, 142);
});

test("status goldens, drawn from their figures", () => {
  const savedTz = process.env.TZ;
  const fails: string[] = [];
  try {
    for (const c of cases) {
      const fig = JSON.parse(fill(fs.readFileSync(
        path.join(FIXTURES, "figures/status", c.id + ".json"), "utf-8")));
      const env = JSON.parse(fs.readFileSync(
        path.join(FIXTURES, "env", c.env + ".json"), "utf-8"));
      // _fig_zone: the clock cells are drawn in the document's zone.
      process.env.TZ = fig.clock.tz ?? env.tz;
      const argv = ["--cols", String(c.cols), ...c.flags];
      const got = renderStatusFigures(statusSettings(env.terminal, argv),
        fig, argv, HOME);
      const want = fs.readFileSync(path.join(GOLDEN, c.id + ".txt"),
        "utf-8");
      if (rstripNewlines(got) !== rstripNewlines(want)) {
        fails.push(c.id);
        if (fails.length === 1) {
          assert.equal(rstripNewlines(got), rstripNewlines(want), c.id);
        }
      }
    }
  } finally {
    if (savedTz === undefined) delete process.env.TZ;
    else process.env.TZ = savedTz;
  }
  assert.deepEqual(fails, []);
});
