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
