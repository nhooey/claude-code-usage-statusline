// agent_fold.ts against agent_fold.py: each fixture agent's fold, saved at
// each line end, is the text tests/fixtures/agent-state/ holds, which the
// Python writes (tests/fixtures/gen/state.py) and tests/fold.py holds the
// Python to; and each text, read back, reads on to the last.
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import * as cr from "../src/claude_records_node.ts";
import {
  AGENT_FOLD_FORMAT, agentFoldOf, agentFoldText, FOLD_CHECK_BYTES,
  foldCandidates, foldDir, slotNames, tailDigest,
} from "../src/agent_fold.ts";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../..");
process.chdir(REPO);

type Fixture = { format: number; agent: string; texts: [number, string][] };

function fixtures(): Fixture[] {
  const dir = "tests/fixtures/agent-state";
  return fs.readdirSync(dir).sort().map((f) =>
    JSON.parse(fs.readFileSync(path.join(dir, f), "utf-8")));
}

function tailAt(data: Uint8Array, k: number): string {
  return tailDigest(data.subarray(Math.max(0, k - FOLD_CHECK_BYTES), k));
}

// The format honest, and the two ports' texts byte for byte the same.
test("each fixture agent's fold saves as tests/fixtures/agent-state/ " +
  "holds it", () => {
  const all = fixtures();
  assert.ok(all.length > 0);
  for (const fx of all) {
    assert.equal(fx.format, AGENT_FOLD_FORMAT,
      `${fx.agent}: run tests/fixtures/gen/state.py`);
    const data = fs.readFileSync(fx.agent);
    const f = cr.newAgentFold();
    let at = 0;
    for (const [k, text] of fx.texts) {
      cr.foldAgentBytes(f, data.subarray(at, k));
      at = k;
      assert.equal(agentFoldText(f, 1, tailAt(data, k)), text,
        `${fx.agent} at ${k}: the fold changed; bump "agent-fold" in ` +
        "spec/state.jsonc");
    }
  }
});

// The Python's text at each line end, read here, reads on to its last.
test("the Python's saved agent fold reads on here", () => {
  for (const fx of fixtures()) {
    if (!fx.texts.length) continue;
    const data = fs.readFileSync(fx.agent);
    const [end, last] = fx.texts[fx.texts.length - 1];
    for (const [k, text] of fx.texts) {
      const [seq, tail, g] = agentFoldOf(text)!;
      assert.equal(agentFoldText(g, seq, tail), text, `${fx.agent} at ${k}`);
      cr.foldAgentBytes(g, data.subarray(k, end));
      assert.equal(agentFoldText(g, 1, tailAt(data, end)), last,
        `${fx.agent} from ${k}`);
    }
  }
});

// The newer slot first, a torn one passed over, and with neither, the
// highest seq either starts with.
test("the slots are read newest first, past a torn one", () => {
  const fx = fixtures().find((f) => f.texts.length > 1)!;
  const [, older] = fx.texts[0];
  const [, newer] = fx.texts[1];
  const o = older.replace('"seq":1,', '"seq":4,');
  const n = newer.replace('"seq":1,', '"seq":5,');
  assert.deepEqual(foldCandidates([o, n]).folds.map(([s]) => s), [5, 4]);
  assert.deepEqual(foldCandidates([n.slice(0, 40), o]).folds.map(([s]) => s),
    [4]);
  assert.deepEqual(foldCandidates([n.slice(0, 40), null]),
    { folds: [], newest: 5 });
  assert.deepEqual(foldCandidates([null, null]), { folds: [], newest: 0 });
});

// The Node port and the Python's panel save to the same files: one reads
// on from the other's.
test("a fold the Python saved is read on here, and the reverse", () => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "agent-fold-"));
  const tr = path.join(state, "s.jsonl");
  const agent = path.join(state, "s", "subagents", "agent-x.jsonl");
  fs.mkdirSync(path.dirname(agent), { recursive: true });
  fs.writeFileSync(tr, "");
  const fx = fixtures().find((f) => f.texts.length > 3)!;
  const data = fs.readFileSync(fx.agent);
  const [half] = fx.texts[fx.texts.length >> 1];
  const [end, last] = fx.texts[fx.texts.length - 1];
  const python = () => execFileSync("python3", ["-c",
    "import sys\nfrom coding_agent_usage_line import agent_fold\n" +
    "agent_fold.fold_file(sys.argv[1], sys.argv[2])", tr, agent],
  { env: { ...process.env, CODING_AGENT_USAGE_LINE_STATE_DIR: state } });
  const dir = foldDir(state, tr);
  const [a, b] = slotNames(agent).map((n) => path.join(dir, n));
  fs.writeFileSync(agent, data.subarray(0, half));
  python();
  assert.deepEqual([fs.existsSync(a), fs.existsSync(b)], [false, true]);
  fs.writeFileSync(agent, data.subarray(0, end));
  const f = cr.agentFoldFile(dir, agent)!;
  assert.equal(agentFoldText(f, 1, tailAt(data, end)), last);
  assert.equal(fs.readFileSync(a, "utf-8"),
    last.replace('"seq":1,', '"seq":2,'));
  const more = '{"type":"user","promptId":"p9"}\n';
  fs.writeFileSync(agent, Buffer.concat([data.subarray(0, end),
    Buffer.from(more)]));
  python();
  const [seq, , g] = agentFoldOf(fs.readFileSync(b, "utf-8"))!;
  assert.deepEqual([seq, g.pos, g.pid], [3, end + more.length, "p9"]);
  fs.rmSync(state, { recursive: true });
});
