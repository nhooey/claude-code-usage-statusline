// spans.ts against spans.py, case by case.
//
// tests/fixtures/gen/formatting.py writes tests/fixtures/formatting/
// spans.json: hand-made span lists for each of join's special cases, then
// seeded random ones, each with what spans.py's helpers make of it and the
// bytes `join` writes under each of its switches.  The escapes have to be
// the Python's byte for byte: they are what the goldens pin.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import * as fm from "../src/formatting.ts";
import * as sp from "../src/spans.ts";
import { enc, revive } from "./formatting_codec.ts";

const FILE = path.join(import.meta.dirname, "..", "..", "tests", "fixtures",
  "formatting", "spans.json");
const DATA = JSON.parse(fs.readFileSync(FILE, "utf-8"));
const RAISES = { raises: true };

test("spans: the helpers and join over every list", () => {
  const widths = {
    unknown: fm.widthsFor("unknown"), jediterm: fm.widthsFor("jediterm"),
    tmux: fm.widthsFor("tmux"),
  };
  for (const c of DATA.cases) {
    const x = revive(c.in);
    const at = JSON.stringify(c.in);
    assert.deepEqual(enc(sp.spans(x)), c.spans, at);
    assert.equal(sp.text(x), c.text, at);
    assert.deepEqual(enc(sp.rstrip(x)), c.rstrip, at);
    assert.deepEqual(enc(sp.lstrip(x)), c.lstrip, at);
    assert.deepEqual(enc(sp.lstrip(x, " ")), c.lstrip_sp, at);
    assert.equal(sp.indent(x), c.indent, at);
    const joins = [];
    for (const close of [false, true]) {
      for (const runs of [false, true]) {
        try {
          joins.push(sp.join(x, close, runs));
        } catch {
          joins.push(RAISES);
        }
      }
    }
    assert.deepEqual(joins, c.join, at);
    for (const [prof, w] of Object.entries(widths)) {
      assert.equal(sp.width(x, w), c.width[prof], `${at} ${prof}`);
    }
  }
});

test("spans: ink and paint", () => {
  const ink = [null, "F_RED"].flatMap((c) =>
    [false, true].map((d) => enc(sp.ink(c, d))));
  assert.deepEqual(ink, DATA.ink);
  assert.deepEqual([
    enc(sp.paint(sp.ink("F_AMB", true), "97٪")),
    enc(sp.paint(sp.span("old", "F_RED", false, true, "B_DRK"), "new")),
  ], DATA.paint);
});
