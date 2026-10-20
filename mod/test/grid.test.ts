// The grid against its shared cases, tests/fixtures/grid/, which
// tools/gen-grid-cases.ts writes from it.  The cases are checked two ways:
// each is replayed from its plain-data rows, as a port would replay it, and
// the generator's output must be what is committed, so a change to the grid
// shows up as a change to the cases, made by regenerating them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join as pathJoin } from "node:path";
import { settings, visWidth } from "../src/formatting.ts";
import type { Env } from "../src/formatting.ts";
import { join } from "../src/spans.ts";
import { draw, hidden, layout } from "../src/grid.ts";
import { GRID_CELLS, RIGHT_EDGE } from "../src/spec.ts";
import {
  OUT, generate, rowFrom, spanFrom, spanJson,
} from "../tools/gen-grid-cases.ts";

type Layout = { cols: number; hide: string[]; fixed: boolean;
  rows: string[]; keys: string[] };
type Draw = { row: string; keys: string[]; cols: number; hide: string[];
  spill: boolean; spans: unknown[][]; line: string };
type File = { settings: { profiles: { [name: string]: Env } };
  rows: { [id: string]: unknown }; layout: Layout[]; draw: Draw[] };

const files = readdirSync(OUT).filter((f) => f.endsWith(".json")).sort();

test("the committed cases are the generator's", () => {
  const want = generate();
  assert.deepEqual(files, [...want.keys()].sort());
  for (const f of files) {
    assert.ok(readFileSync(pathJoin(OUT, f), "utf8") === want.get(f),
      f + " differs: run node mod/tools/gen-grid-cases.ts and read the diff");
  }
});

for (const f of files) {
  const data = JSON.parse(readFileSync(pathJoin(OUT, f), "utf8")) as File;
  const rows = new Map(Object.entries(data.rows)
    .map(([id, r]) => [id, rowFrom(r)]));
  for (const [profile, env] of Object.entries(data.settings.profiles)) {
    const st = settings(env);
    test(`${f} under ${profile}: layout`, () => {
      for (const c of data.layout) {
        assert.deepEqual(layout(st, c.rows.map((id) => rows.get(id)!), c.cols,
          c.hide, c.fixed), c.keys, JSON.stringify(c));
      }
    });
    test(`${f} under ${profile}: draw`, () => {
      for (const c of data.draw) {
        const got = draw(st, rows.get(c.row)!, c.keys, c.cols, c.hide,
          c.spill);
        const where = JSON.stringify([c.row, c.cols, c.hide, c.spill]);
        assert.deepEqual(got.map(spanJson), c.spans, where);
        assert.equal(join(got), c.line, where);
        assert.equal(join(c.spans.map(spanFrom)), c.line, where);
      }
    });
  }
}

test("a hide path names itself and every path under it", () => {
  assert.ok(hidden(["turn.time"], "turn.time.eta"));
  assert.ok(hidden(["*.work"], "session.work.diff"));
  assert.ok(hidden(["account"], "account"));
  assert.ok(!hidden(["turn.time.eta"], "turn.time"));
  assert.ok(!hidden(["*.work"], "session"));
  assert.ok(hidden(["t?rn.[a-c]*"], "turn.chat.prompt"));
  assert.ok(!hidden(["t?rn.[!a-c]*"], "turn.chat.prompt"));
});

test("at a right edge of 0 a row ends at the terminal's edge", () => {
  // As the mod draws the band under the footer line, where there is no
  // [-] (asked 2026-10-20), and as tests/grid.py has it.
  const st0 = settings({}, true, false, 0);
  const st5 = settings({});
  assert.equal(st5.rightEdge, RIGHT_EDGE);
  const data = JSON.parse(readFileSync(pathJoin(OUT, files[0]), "utf8")) as
    File;
  const rows = [...Object.values(data.rows)].map(rowFrom);
  const row = rowFrom(data.rows[data.draw[0].row]);
  const keys = GRID_CELLS.map((g) => g.key);
  for (const cols of [120, 160, 196]) {
    assert.equal(visWidth(join(draw(st0, row, keys, cols, [])), st0.widths),
      cols, String(cols));
  }
  // The narrowest width that keeps every column, RIGHT_EDGE sooner.
  const all = (st: typeof st0): number => {
    const n = layout(st, rows, 1 << 30, []).length;
    let w = 1;
    while (layout(st, rows, w, []).length < n) w++;
    return w;
  };
  assert.equal(all(st5) - all(st0), RIGHT_EDGE);
});
