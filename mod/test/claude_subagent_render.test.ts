// claude_subagent_render.ts against claude_subagent_render.py, case by case.
//
// tests/fixtures/gen/panel.py writes tests/fixtures/panel/: one file per
// settings group (the terminal's environment, mark spacing and subscript
// decimals), each case the prepared (task, usage, meta, shares) records,
// the plan Limits, the terminal's width, the clock and any --hide paths
// render_task_rows was handed, and the rows it drew, each as the joined
// string and as the spans it was joined from.  Both have to match: the spans are what a mod draws, and
// the string is what the goldens pin.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import * as fm from "../src/formatting.ts";
import * as sr from "../src/claude_subagent_render.ts";
import type { Span } from "../src/spans.ts";
import { revive } from "./formatting_codec.ts";

const DIR = path.join(import.meta.dirname, "..", "..", "tests", "fixtures",
  "panel");
const FILES = fs.readdirSync(DIR).filter((f) => f.endsWith(".json")).sort();

/** A span as panel.py's span_json writes it: the fields at their defaults
 * left out. */
function spanJson(s: Span): { [k: string]: unknown } {
  const out: { [k: string]: unknown } = { text: s.text };
  if (s.colour) out.colour = s.colour;
  if (s.dim) out.dim = s.dim;
  if (s.bold) out.bold = s.bold;
  if (s.bg) out.bg = s.bg;
  return out;
}

let total = 0;
for (const file of FILES) {
  const data = JSON.parse(fs.readFileSync(path.join(DIR, file), "utf-8"));
  const s = data.settings;
  test(`panel: ${file}`, () => {
    const st = fm.settings(s.terminal, s.mark_spacing, s.subscript_decimals);
    assert.equal(st.profile, s.profile, "the group's terminal profile");
    for (const c of data.cases) {
      const inp = revive(c.input);
      const prepared: sr.Prepared[] = inp.tasks.map(
        (r: any) => [r.task, r.usage, r.meta, r.shares] as const);
      const hide = inp.hide ?? [];
      const got = sr.renderTaskRowSpans(st, prepared, inp.limits, inp.cols,
        inp.now, hide);
      const joined = sr.renderTaskRows(st, prepared, inp.limits, inp.cols,
        inp.now, hide);
      assert.deepEqual(got.map(([id, row]) => ({
        id, spans: row.map(spanJson),
      })), c.rows.map((r: any) => ({ id: r.id, spans: r.spans })),
      `${file} ${c.id}: spans`);
      assert.deepEqual(joined.map(([id, row]) => ({ id, row })),
        c.rows.map((r: any) => ({ id: r.id, row: r.row })),
        `${file} ${c.id}: rows`);
      total++;
    }
  });
}

test("panel: every case was run", () => {
  assert.equal(total, 275);
});
