// The main transcript's folds, broken anywhere: a fold finished at any
// record, or with a half-written last line, reads on to what the whole
// fold reads.  tests/fold.py holds the Python's side of the same cases.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import * as cr from "../src/claude_records_node.ts";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../..");
process.chdir(REPO);

/** Every fixture transcript that is a session's own, not an agent's. */
const FILES = execFileSync("git", ["ls-files", "tests/fixtures"]).toString()
  .split("\n").filter((f) => f.endsWith(".jsonl") &&
    !path.basename(f).startsWith("agent-"));

type Folds = { tr: cr.TranscriptFold; tu: cr.TurnsFold };

function foldAll(records: readonly cr.Rec[], f?: Folds): Folds {
  return { tr: cr.foldTranscriptAll(records, f?.tr),
    tu: cr.foldTurnsAll(records, f?.tu) };
}

/** Both finishes of `f`, with the agents beside `p` and a clock, so every
 * input a finish takes is in play; with what the turns' finish held. */
function finish(p: string, f: Folds): unknown {
  const etas: cr.AgentEta[] = [];
  const agents = cr.agentRecords(p, null, etas);
  const held = new Map<string, number>();
  return [cr.transcriptFinish(f.tr, agents, etas, 1e10),
    cr.turnsFinish(f.tu, (seen) => cr.agentRecords(p, seen), null, held,
      cr.agentLabel), [...held]];
}

test("there are fixture transcripts to fold", () => {
  assert.ok(FILES.length > 10, String(FILES.length));
});

// Finished at every record boundary, then folded on to the end, each
// fixture reads as its whole fold: a finish leaves the fold as it was.
test("a fold finished at any record reads on as the whole fold", () => {
  for (const p of FILES) {
    const records = cr._records(p);
    const whole = finish(p, foldAll(records));
    for (let k = 0; k <= records.length; k++) {
      const f = foldAll(records.slice(0, k));
      assert.deepEqual(finish(p, f), finish(p, foldAll(records.slice(0, k))),
        `${p} at ${k}`);
      foldAll(records.slice(k), f);
      assert.deepEqual(finish(p, f), whole, `${p} broken at ${k}`);
    }
  }
});

// A last line with no newline yet is folded on a copy, so the fold reads
// it now and the line completed later: cut inside each line, and just
// before its newline, where it parses whole.
test("a half-written last line reads now, and once completed", () => {
  for (const p of FILES) {
    const data = fs.readFileSync(p);
    const whole = finish(p, foldAll(cr._recordsOf(data)));
    for (let end = data.indexOf(10); end >= 0;
      end = data.indexOf(10, end + 1)) {
      const start = data.lastIndexOf(10, end - 1) + 1;
      for (const cut of new Set([start + ((end - start) >> 1), end])) {
        const f = foldAll(cr._recordsOf(data.subarray(0, start)));
        const before = finish(p, f);
        const tail = cr._recordsOf(data.subarray(start, cut));
        const view = { tr: cr.transcriptFoldWith(f.tr, tail),
          tu: cr.turnsFoldWith(f.tu, tail) };
        assert.deepEqual(finish(p, view),
          finish(p, foldAll(cr._recordsOf(data.subarray(0, cut)))),
          `${p} cut at ${cut}`);
        assert.deepEqual(finish(p, f), before, `${p} left as it was`);
        foldAll(cr._recordsOf(data.subarray(start)), f);
        assert.deepEqual(finish(p, f), whole, `${p} completed at ${cut}`);
      }
    }
  }
});
