// The receipt's turn timed by the engine's duration, which the transcript
// records only after turn.complete has fired.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { receiptTurn, withEngineDuration } from "../src/receipt.ts";
import { decodeTurn } from "../src/claude_cost.ts";
import type { Dict } from "../src/py.ts";

const DIR = path.join(import.meta.dirname, "..", "..", "tests", "fixtures",
                      "figures", "cost");
const doc = JSON.parse(fs.readFileSync(
  path.join(DIR, "10-turn-id@120.json"), "utf8")) as Dict;
const i = receiptTurn((doc.turns as Dict[]).map(decodeTurn));
const turn = (fig: Dict) => (fig.turns as Dict[])[i];
const acc = (fig: Dict) => ((fig.accounting as Dict).turns as Dict[])[i];

test("a longer engine duration times the turn, the rest as the model's", () => {
  const dur = turn(doc).dur_s as number;
  const got = withEngineDuration(doc, (dur + 5) * 1000);
  assert.equal(turn(got).dur_s, dur + 5);
  assert.equal(acc(got).model_s, (acc(doc).model_s as number) + 5);
  assert.equal(acc(got).tool_s, acc(doc).tool_s);
  // The document it was given is left as it was.
  assert.equal(turn(doc).dur_s, dur);
});

test("a shorter or missing engine duration leaves the document alone", () => {
  const dur = turn(doc).dur_s as number;
  assert.equal(withEngineDuration(doc, (dur - 1) * 1000), doc);
  assert.equal(withEngineDuration(doc, 0), doc);
});

test("a many-line opener draws on one row in the band and the receipt", async () => {
  const { bandRows } = await import("../src/band.ts");
  const { receiptRows } = await import("../src/receipt.ts");
  const { settings } = await import("../src/formatting.ts");
  const st = settings({}, true, false);
  const text = "Another session sent a message:\n<message>\nhello\n</message>";
  const cost = structuredClone(doc);
  (cost.turns as Dict[])[i] = { ...turn(doc), text };
  const flat = (r: { label: readonly { spans: readonly { text: string }[] }[] }) =>
    r.label.flatMap((p) => p.spans.map((s) => s.text)).join("");
  assert.doesNotMatch(flat(receiptRows(st, cost, null).turn!), /\n/);
  const sdir = path.join(DIR, "..", "status");
  const name = fs.readdirSync(sdir).find((f) => {
    const d = JSON.parse(fs.readFileSync(path.join(sdir, f), "utf8"));
    return d.open_turn;
  })!;
  const status = JSON.parse(fs.readFileSync(path.join(sdir, name), "utf8"));
  status.open_turn = { ...status.open_turn, text };
  const rows = bandRows(st, status, { home: "/", rate: null,
    phase: "running" });
  assert.doesNotMatch(flat(rows.turn), /\n/);
});
