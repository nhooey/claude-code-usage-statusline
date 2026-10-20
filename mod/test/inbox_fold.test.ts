// inbox_fold.ts against inbox_fold.py: each fixture file's inbox entry,
// folded at each line end, is the text tests/fixtures/inbox-state/ holds,
// which the Python writes (tests/fixtures/gen/state.py) and tests/fold.py
// holds the Python to; the counts read on from the fold are the counts of
// the whole files; and the two ports save the same bytes to the same files
// and read on from each other's.
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import * as cr from "../src/claude_records_node.ts";
import {
  foldInboxEntry, INBOX_CHECK_BYTES, INBOX_FOLD_FORMAT, INBOX_SLOTS,
  inboxEntryText, inboxFoldDir, inboxFoldLoad, inboxFoldOf, inboxFoldText,
  inboxTailDigest, newInboxEntry,
} from "../src/inbox_fold.ts";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../..");
process.chdir(REPO);

type Fixture = {
  format: number; file: string; main: boolean; texts: [number, string][];
};

function fixtures(): Fixture[] {
  const dir = "tests/fixtures/inbox-state";
  return fs.readdirSync(dir).sort().map((f) =>
    JSON.parse(fs.readFileSync(path.join(dir, f), "utf-8")));
}

function tailAt(data: Uint8Array, k: number): string {
  return inboxTailDigest(data.subarray(Math.max(0, k - INBOX_CHECK_BYTES), k));
}

// The format honest, and the two ports' texts byte for byte the same.
test("each fixture file's inbox entry folds as tests/fixtures/inbox-state/ " +
  "holds it", () => {
  const all = fixtures();
  assert.ok(all.length > 3);
  for (const fx of all) {
    assert.equal(fx.format, INBOX_FOLD_FORMAT,
      `${fx.file}: run tests/fixtures/gen/state.py`);
    const data = fs.readFileSync(fx.file);
    const e = newInboxEntry();
    let at = 0;
    for (const [k, text] of fx.texts) {
      foldInboxEntry(e, data.subarray(at, k), fx.main);
      at = k;
      e.tail = tailAt(data, k);
      assert.equal(inboxEntryText(fx.file, e), text,
        `${fx.file} at ${k}: the fold changed; bump "inbox-fold" in ` +
        "spec/state.jsonc");
    }
  }
});

// The Python's entry at each line end, read here, reads on to its last.
test("the Python's saved inbox entry reads on here", () => {
  for (const fx of fixtures()) {
    const data = fs.readFileSync(fx.file);
    const [end, last] = fx.texts[fx.texts.length - 1];
    for (const [k, text] of fx.texts) {
      const fold =
        `{"format":${INBOX_FOLD_FORMAT},"seq":3,"files":[${text}]}`;
      const [seq, entries] = inboxFoldOf(fold)!;
      assert.equal(inboxFoldText(entries, seq), fold, `${fx.file} at ${k}`);
      const g = entries.get(fx.file)!;
      foldInboxEntry(g, data.subarray(k, end), fx.main);
      g.tail = tailAt(data, end);
      assert.equal(inboxEntryText(fx.file, g), last, `${fx.file} from ${k}`);
    }
  }
});

test("the slots are read newest first, past a torn one", () => {
  const fold = (seq: number) => `{"format":${INBOX_FOLD_FORMAT},"seq":${seq},` +
    `"files":[${fixtures()[0].texts[0][1]}]}`;
  assert.equal(inboxFoldLoad([fold(4), fold(5)])[1], 5);
  assert.equal(inboxFoldLoad([fold(5).slice(0, 30), fold(4)])[1], 4);
  const [none, newest] = inboxFoldLoad([fold(5).slice(0, 30), null]);
  assert.deepEqual([none.size, newest], [0, 5]);
  assert.deepEqual(inboxFoldLoad([null, null])[1], 0);
});

/** inbox-now copied into a scratch session, each file cut to `k` bytes. */
function session(tmp: string, k: number): {
  tr: string; files: string[]; targets: Map<string, string>;
} {
  const src = "tests/fixtures/records/inputs";
  const tr = path.join(tmp, "inbox-now.jsonl");
  const sub = path.join(tmp, "inbox-now", "subagents");
  fs.mkdirSync(sub, { recursive: true });
  const names = fs.readdirSync(path.join(src, "inbox-now", "subagents"))
    .filter((n) => n.endsWith(".jsonl")).sort();
  const files = [tr, ...names.map((n) => path.join(sub, n))];
  const from = [path.join(src, "inbox-now.jsonl"),
    ...names.map((n) => path.join(src, "inbox-now", "subagents", n))];
  files.forEach((f, i) => {
    fs.writeFileSync(f, fs.readFileSync(from[i]).subarray(0, k));
    fs.utimesSync(f, 1_800_000_000, 1_800_000_000 + i);
  });
  return { tr, files, targets: new Map(files.slice(1).map((f) =>
    [path.basename(f).slice("agent-".length, -".jsonl".length), f])) };
}

test("the inbox read on from its fold counts as the whole files", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "inbox-fold-"));
  const state = path.join(tmp, "state");
  const longest = 3100;
  const slots = new Set<string>();
  for (let k = 0; k <= longest; k += 37) {
    const { tr, files, targets } = session(tmp, k);
    for (const since of [null, 0, 4e9]) {
      assert.deepEqual(cr.inboxFoldCounts(state, tr, files, targets, since),
        cr.inboxCounts(files, targets, since), `at ${k}, since ${since}`);
    }
    for (const n of fs.readdirSync(inboxFoldDir(state, tr))) slots.add(n);
  }
  assert.deepEqual([...slots].sort(), [...INBOX_SLOTS]);
  const { tr, files, targets } = session(tmp, longest);
  assert.deepEqual(Object.fromEntries(
    cr.inboxFoldCounts(state, tr, files, targets)), { b1: 1 });
  fs.rmSync(tmp, { recursive: true });
});

// The Node port and the Python's panel save to the same files, byte for
// byte: one reads on from the other's.
test("an inbox fold the Python saved is read on here, and the reverse", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "inbox-fold-"));
  const python = (state: string, tr: string, files: string[],
    targets: Map<string, string>) => execFileSync("python3", ["-c",
    "import json, sys\nfrom coding_agent_usage_line import inbox_fold\n" +
    "a = json.loads(sys.argv[1])\n" +
    "print(json.dumps(inbox_fold.counts(*a)))",
    JSON.stringify([tr, files, Object.fromEntries(targets)])],
  { env: { ...process.env, CODING_AGENT_USAGE_LINE_STATE_DIR: state } })
    .toString();
  const slot = (state: string, tr: string, i: number) => fs.readFileSync(
    path.join(inboxFoldDir(state, tr), INBOX_SLOTS[i]), "utf-8");
  const py = path.join(tmp, "py"), node = path.join(tmp, "node");
  // Each from nothing, at half the session: the same bytes.
  let s = session(tmp, 1500);
  assert.equal(python(py, s.tr, s.files, s.targets).trim(),
    JSON.stringify(Object.fromEntries(
      cr.inboxFoldCounts(node, s.tr, s.files, s.targets))));
  assert.equal(slot(node, s.tr, 1), slot(py, s.tr, 1));
  // Each read on from the other's, to the end: the same bytes again.
  s = session(tmp, 3100);
  python(node, s.tr, s.files, s.targets);
  cr.inboxFoldCounts(py, s.tr, s.files, s.targets);
  assert.equal(slot(node, s.tr, 0), slot(py, s.tr, 0));
  const [seq, entries] = inboxFoldOf(slot(py, s.tr, 0))!;
  assert.equal(seq, 2);
  assert.equal(entries.get(s.tr)!.pos, fs.statSync(s.tr).size);
  fs.rmSync(tmp, { recursive: true });
});
