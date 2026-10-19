// The row builders against their shared cases, tests/fixtures/rows/, which
// tools/gen-row-cases.ts writes from them.  As with the grid's cases, each
// is replayed from its document and options, and the generator's output
// must be what is committed, so a change to a builder shows up as a change
// to the cases, made by regenerating them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join as pathJoin } from "node:path";
import { settings, visWidth } from "../src/formatting.ts";
import type { Env } from "../src/formatting.ts";
import { join, width } from "../src/spans.ts";
import { RIGHT_EDGE } from "../src/spec.ts";
import type { Span } from "../src/spans.ts";
import { draw } from "../src/grid.ts";
import {
  accountText, bandRows, fixedKeys, footerTail, phaseRows,
} from "../src/band.ts";
import { receiptTurn } from "../src/receipt.ts";
import { decodeTurn } from "../src/claude_cost.ts";
import { spanFrom, spanJson } from "../tools/gen-grid-cases.ts";
import {
  FIGURES, HOME, OUT, document, drawBand, drawReceipt, drawStart, generate,
  inZone,
} from "../tools/gen-row-cases.ts";
import type { BandCase, ReceiptCase } from "../tools/gen-row-cases.ts";

type Same = { same: string[] };
type File = { settings: { profiles: { [name: string]: Env } };
  band: (BandCase & Same & { rows: unknown[][][]; lines: string[] })[];
  receipt: (ReceiptCase & Same & { head: unknown[][]; rows: unknown[][][];
    lines: string[] })[];
  start: { doc: string; same: string[]; spans: unknown[][];
    line: string }[] };

const files = readdirSync(OUT).filter((f) => f.endsWith(".json")).sort();

test("the committed cases are the generator's", () => {
  const want = generate();
  assert.deepEqual(files, [...want.keys()].sort());
  for (const f of files) {
    assert.ok(readFileSync(pathJoin(OUT, f), "utf8") === want.get(f),
      f + " differs: run node mod/tools/gen-row-cases.ts and read the diff");
  }
});

/** The text of a committed document. */
const text = (id: string): string =>
  readFileSync(pathJoin(FIGURES, id + ".json"), "utf8");

/** Spans as the cases write them, and their joined line. */
function same(got: readonly Span[], want: readonly unknown[][],
  line: string, where: string): void {
  assert.deepEqual(got.map(spanJson), want, where);
  assert.equal(join(got), line, where);
  assert.equal(join(want.map(spanFrom)), line, where);
}

for (const f of files) {
  const data = JSON.parse(readFileSync(pathJoin(OUT, f), "utf8")) as File;
  for (const [profile, env] of Object.entries(data.settings.profiles)) {
    const st = settings(env);
    test(`${f} under ${profile}: band`, () => {
      for (const c of data.band) {
        const where = JSON.stringify([c.doc, c.cols, c.hide, c.phase]);
        const rows = drawBand(st, document(c.doc), c);
        assert.equal(rows.length, c.rows.length, where);
        rows.forEach((r, i) => same(r, c.rows[i], c.lines[i], where));
      }
    });
    test(`${f} under ${profile}: receipt`, () => {
      for (const c of data.receipt) {
        const where = JSON.stringify([c.doc, c.cols, c.hide, c.workspace]);
        const got = drawReceipt(st, document(c.doc), c);
        assert.equal(got.rows.length, c.rows.length, where);
        got.rows.forEach((r, i) => same(r, c.rows[i], c.lines[i], where));
        same(got.head, c.head, c.lines[c.rows.length], where);
      }
    });
    test(`${f} under ${profile}: start`, () => {
      for (const c of data.start) {
        same(drawStart(document(c.doc)), c.spans, c.line, c.doc);
      }
    });
  }
}

test("a case's `same` documents are its document, byte for byte", () => {
  const data = JSON.parse(readFileSync(pathJoin(OUT, files[0]), "utf8")) as
    File;
  for (const c of [...data.start, ...data.receipt]) {
    for (const id of c.same) assert.equal(text(id), text(c.doc), id);
  }
});

test("the band's columns do not move with the phase or the figures", () => {
  const st = settings({});
  const keys = fixedKeys(st, 155, []);
  for (const id of ["status/01-baseline@196", "status/03-no-transcript@196",
    "status/18-agents@196"]) {
    const fig = document(id);
    for (const phase of ["running", "done"] as const) {
      const rows = inZone(fig, () => phaseRows(bandRows(st, fig,
        { home: HOME, rate: null, phase }), phase));
      for (const r of rows) {
        // Every row is drawn on the same keys to the same right edge, so
        // each column starts where the others' do.
        const drawn = draw(st, r, keys, 155, []);
        assert.equal(width(drawn, st.widths), 155 - RIGHT_EDGE, id);
      }
    }
  }
});

test("the receipt bills the cost line's turn", () => {
  const fig = document("cost/09-agents@196");
  const turns = (fig.turns as { [k: string]: unknown }[]).map(decodeTurn);
  const i = receiptTurn(turns);
  assert.ok(turns[i].calls && !turns[i].agent && !turns[i].compact);
  assert.equal(i, turns.length - 1);
  assert.equal(receiptTurn([]), -1);
});

test("the footer's tail ends on the 💳 account details where the band's rows end", () => {
  const st = settings({});
  const fig = document("status/01-baseline@196");
  const hint = "-- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle)";
  const text = inZone(fig, () => accountText(st, fig, []));
  assert.ok(text.includes("💳"), text);
  const tail = inZone(fig, () => footerTail(st, fig, [], hint, 155));
  assert.ok(tail.endsWith(text), tail);
  // Two blanks in, the hint, then the tail: to the band's right edge.
  assert.equal(2 + visWidth(hint, st.widths) + visWidth(tail, st.widths),
    155 - RIGHT_EDGE);
  // Too narrow a row still parts the two by two blanks.
  assert.ok(inZone(fig, () => footerTail(st, fig, [], hint, 40))
    .startsWith("  " + text.slice(0, 1)));
  assert.equal(inZone(fig, () => footerTail(st, fig, ["account"], hint, 155)),
    "");
});
