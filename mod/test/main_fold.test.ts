// The main transcript's folds, broken anywhere: a fold finished at any
// record, or with a half-written last line, reads on to what the whole
// fold reads; and saved as text, the same bytes main_fold.py writes, read
// back by either port and read on.  tests/fold.py holds the Python's side
// of the same cases.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import * as cr from "../src/claude_records_node.ts";
import * as mf from "../src/main_fold.ts";

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

// ════════════════════════════════════════════════════════════════════════════
// The folds saved as text.
// ════════════════════════════════════════════════════════════════════════════

const MAIN_FOLD = ["-m", "coding_agent_usage_line.main_fold"];

type Texts = { parts: string[]; head: string };

/** A first save's texts of `f`, folded to `end` of `data`. */
function saved(f: mf.MainFold, data: Uint8Array, end: number,
  partBytes = mf.FOLD_PART_BYTES): Texts {
  const got = mf.foldSave(f, mf.foldMeta(data, end), mf.newSaveMark(),
    partBytes)!;
  return { parts: got.parts.map(([, t]) => t), head: got.head };
}

/** Where tests/fixtures/state/ keeps `p`'s saved fold. */
function fixtureOf(p: string): { format: number } & Texts {
  return JSON.parse(fs.readFileSync(path.join("tests/fixtures/state",
    path.relative("tests/fixtures", p).replaceAll("/", "--") + ".json"),
  "utf-8"));
}

function lineEnds(data: Uint8Array): number[] {
  const out: number[] = [];
  for (let at = data.indexOf(10); at >= 0; at = data.indexOf(10, at + 1)) {
    out.push(at + 1);
  }
  return out;
}

function foldMain(f: mf.MainFold, records: readonly cr.Rec[]): mf.MainFold {
  for (const r of records) mf.foldMain(f, r);
  return f;
}

/** A saved fold in `dir`, read as the mod reads one. */
function loadDir(dir: string) {
  return mf.foldLoad((name) => {
    try {
      return fs.readFileSync(path.join(dir, name), "utf-8");
    } catch {
      return null;
    }
  });
}

function tmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "main-fold-"));
}

// The Python writes a float as this does: shortest digits, JavaScript's
// layout.  Seeded, over every magnitude a double has.
test("a float is written as JSON.stringify writes it", () => {
  let a = 7;
  const rand = () => (a = (a * 1103515245 + 12345) % 2147483648) / 2147483648;
  const xs = Array.from({ length: 3000 }, (_, i) =>
    (rand() - 0.5) * 10 ** Math.floor(rand() * 600 - 320) * (i % 7 ? 1 : 3));
  xs.push(0.1, 1e21, 1e-7, 2 ** 53 + 2, 1700000000.123, 5e-324);
  const dir = tmp();
  const file = path.join(dir, "floats.json");
  fs.writeFileSync(file, JSON.stringify(xs));
  const out = execFileSync("python3", ["-c",
    "import sys, json\nfrom coding_agent_usage_line.main_fold import " +
    "js_num\nprint(json.dumps([js_num(x) for x in " +
    "json.load(open(sys.argv[1]))]))", file]).toString();
  fs.rmSync(dir, { recursive: true });
  assert.deepEqual(JSON.parse(out), xs.map((x) => JSON.stringify(x)));
});

// The format honest: a change to either fold, or to what is saved of it,
// changes the text, and the fixtures fail until the format is bumped and
// tests/fixtures/gen/state.py run.
test("each fixture's fold saves as tests/fixtures/state/ holds it", () => {
  for (const p of FILES) {
    const want = fixtureOf(p);
    assert.equal(want.format, mf.MAIN_FOLD_FORMAT,
      `${p}: run tests/fixtures/gen/state.py`);
    const data = fs.readFileSync(p);
    const end = data.lastIndexOf(10) + 1;
    assert.deepEqual(saved(foldMain(mf.newMainFold(),
      cr._recordsOf(data.subarray(0, end))), data, end),
    { parts: want.parts, head: want.head },
    `${p}: the fold changed; bump "main-fold" in spec/state.jsonc`);
  }
});

// The Python's state at every line end, in parts of 300 bytes, is what
// this writes there, byte for byte, and read here goes on to the fixture.
test("the Python's saved fold reads on here", () => {
  for (const p of FILES) {
    const want = fixtureOf(p);
    const data = fs.readFileSync(p);
    const end = data.lastIndexOf(10) + 1;
    const dir = tmp();
    execFileSync("python3", [...MAIN_FOLD, "every", p, dir, "--part-bytes",
      "300"]);
    const f = mf.newMainFold();
    let done = 0;
    for (const k of lineEnds(data)) {
      foldMain(f, cr._recordsOf(data.subarray(done, k)));
      done = k;
      const at = path.join(dir, String(k));
      const mine = saved(f, data, k, 300);
      const seq = mf.foldHeadOf(mine.head)!.seq;
      assert.deepEqual({ parts: mine.parts.map((_, i) =>
        fs.readFileSync(path.join(at, mf.partName(i)), "utf-8")),
      head: fs.readFileSync(path.join(at, mf.HEAD_SLOTS[seq % 2]), "utf-8") },
      mine, `${p} at ${k}`);
      const back = loadDir(at);
      assert.ok(back, `${p} at ${k}`);
      assert.equal(back.meta.offset, k);
      foldMain(back.fold, cr._recordsOf(data.subarray(k, end)));
      assert.deepEqual(saved(back.fold, data, end),
        { parts: want.parts, head: want.head }, `${p} read on from ${k}`);
    }
    fs.rmSync(dir, { recursive: true });
  }
});

// And the other way: this one's state at every line end, read on by the
// Python, saves as the fixture.
test("a fold saved here reads on in the Python", () => {
  for (const p of FILES) {
    const want = fixtureOf(p);
    const data = fs.readFileSync(p);
    const dir = tmp();
    const f = mf.newMainFold();
    let done = 0;
    const ends = lineEnds(data);
    for (const k of ends) {
      foldMain(f, cr._recordsOf(data.subarray(done, k)));
      done = k;
      const got = mf.foldSave(f, mf.foldMeta(data, k))!;
      const at = path.join(dir, String(k));
      fs.mkdirSync(at);
      for (const [i, t] of got.parts) {
        fs.writeFileSync(path.join(at, mf.partName(i)), t);
      }
      fs.writeFileSync(path.join(at, got.slot), got.head);
    }
    const out = execFileSync("python3", [...MAIN_FOLD, "readon", p, dir],
      { maxBuffer: 1 << 28 })
      .toString().split("\n").filter(Boolean).map((l) => JSON.parse(l));
    assert.equal(out.length, ends.length, p);
    for (const o of out) {
      assert.deepEqual({ parts: o.parts, head: o.head },
        { parts: want.parts, head: want.head }, `${p} read on from ${o.at}`);
    }
    fs.rmSync(dir, { recursive: true });
  }
});

// As the mod saves it: a part at a time as the fold grows, then a head in
// the other slot; and with the newest head torn, the one before it reads.
test("a fold saved as it grows reads back, and past a torn head", () => {
  for (const p of FILES) {
    const want = fixtureOf(p);
    const data = fs.readFileSync(p);
    const end = data.lastIndexOf(10) + 1;
    const ends = lineEnds(data);
    const files = new Map<string, string>();
    const f = mf.newMainFold();
    let mark = mf.newSaveMark(), done = 0;
    for (const k of ends) {
      foldMain(f, cr._recordsOf(data.subarray(done, k)));
      done = k;
      const got = mf.foldSave(f, mf.foldMeta(data, k), mark, 300)!;
      for (const [i, t] of got.parts) files.set(mf.partName(i), t);
      files.set(got.slot, got.head);
      mark = got.mark;
      const back = mf.foldLoad((n) => files.get(n) ?? null);
      assert.ok(back, `${p} at ${k}`);
      assert.deepEqual(finish(p, back.fold), finish(p, f), `${p} at ${k}`);
    }
    if (ends.length < 2) continue;
    const newest = mf.HEAD_SLOTS[mark.seq % 2];
    const text = files.get(newest)!;
    files.set(newest, text.slice(0, text.length >> 1));
    const back = mf.foldLoad((n) => files.get(n) ?? null);
    assert.equal(back?.meta.offset, ends[ends.length - 2], p);
    foldMain(back!.fold, cr._recordsOf(data.subarray(back!.meta.offset,
      end)));
    assert.deepEqual(saved(back!.fold, data, end),
      { parts: want.parts, head: want.head }, `${p} past a torn head`);
  }
});

// ════════════════════════════════════════════════════════════════════════════
// The worker: scripts/agent_lines.py's fold mode, the mod's cold read.
// ════════════════════════════════════════════════════════════════════════════

const WORKER = path.join(REPO, "mod/scripts/agent_lines.py");

/** Every file in `dir`, by name, as its text. */
function filesIn(dir: string): Map<string, string> {
  return new Map(fs.readdirSync(dir).sort().map((n) =>
    [n, fs.readFileSync(path.join(dir, n), "utf-8")]));
}

/** `writes` written over `files`, as the mod writes them through $.fs. */
function writeOver(files: Map<string, string>,
  writes: readonly [string, string][]): Map<string, string> {
  for (const [n, t] of writes) files.set(n, t);
  return new Map([...files].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
}

/** What foldOf does where the worker cannot: the fold saved in `files`,
 * where it was folded from `data`'s bytes, read on to `end` and saved back
 * in foldWrites' order; or, with none, folded from the start.  And the
 * offset then saved to. */
function modSave(files: Map<string, string>, data: Uint8Array, end: number):
  number {
  const back = mf.foldLoad((n) => files.get(n) ?? null);
  const fits = back !== null && back.meta.offset <= data.length &&
    JSON.stringify(mf.foldMeta(data, back.meta.offset)) ===
      JSON.stringify(back.meta);
  const f = fits ? back.fold : mf.newMainFold();
  const from = fits ? back.meta.offset : 0;
  if (end <= from) return from;
  foldMain(f, cr._recordsOf(data.subarray(from, end)));
  writeOver(files, mf.foldWrites(f, mf.foldMeta(data, end),
    fits ? back.mark : null)!.writes);
  return end;
}

// The state the worker saves is the one the mod saves for the same
// transcript and offset, file for file and byte for byte: from nothing,
// read on from a state the mod saved at a line end, from one already at
// the end, and from one of other bytes, which both start over from.
test("the worker saves the fold as the mod saves it", () => {
  for (const p of FILES) {
    const data = fs.readFileSync(p);
    const ends = lineEnds(data);
    const end = ends.at(-1) ?? 0;
    const other = Buffer.from(data);
    if (other.length) other[0] ^= 1;
    const plants: [string, Uint8Array, number | null][] = [
      ["nothing", data, null],
      ["the first line", data, ends[0] ?? null],
      ["halfway", data, ends[ends.length >> 1] ?? null],
      ["the end", data, end],
      ["other bytes", other, ends[ends.length >> 1] ?? null]];
    for (const [what, bytes, k] of plants) {
      const dir = tmp();
      const files = new Map<string, string>();
      if (k !== null) {
        const f = foldMain(mf.newMainFold(),
          cr._recordsOf(bytes.subarray(0, k)));
        const w = mf.foldWrites(f, mf.foldMeta(bytes, k), null)!;
        for (const [n, t] of w.writes) fs.writeFileSync(path.join(dir, n), t);
        writeOver(files, w.writes);
      }
      const out = execFileSync("python3", [WORKER, "fold", p,
        String(data.length), dir]).toString();
      const to = modSave(files, data, end);
      assert.equal(out, `${to}\n`, `${p} from ${what}`);
      assert.deepEqual(filesIn(dir), files, `${p} from ${what}`);
      fs.rmSync(dir, { recursive: true });
    }
  }
});

// A copy of mod/ on its own, as a GitHub install or a dev mod has it, has
// no package beside the worker: it exits 1, says so, and writes nothing,
// so foldOf folds the bytes itself (mod-tests/band.test.ts).
test("the worker with no package beside it exits 1 and writes nothing",
  () => {
    const root = tmp();
    const scripts = path.join(root, "mod", "scripts");
    fs.mkdirSync(scripts, { recursive: true });
    fs.copyFileSync(WORKER, path.join(scripts, "agent_lines.py"));
    const dir = tmp();
    const p = FILES[0];
    const r = spawnSync("python3", [path.join(scripts, "agent_lines.py"),
      "fold", p, String(fs.statSync(p).size), dir], { encoding: "utf-8" });
    assert.equal(r.status, 1, r.stderr);
    assert.equal(r.stdout, "");
    assert.match(r.stderr, /no coding_agent_usage_line package beside mod/);
    assert.deepEqual(fs.readdirSync(dir), []);
    fs.rmSync(root, { recursive: true });
    fs.rmSync(dir, { recursive: true });
  });

test("a head over its cap is not saved", () => {
  const f = mf.newMainFold();
  f.tr.userText = "x".repeat(2000);
  assert.equal(mf.foldSave(f, mf.foldMeta(new Uint8Array(0), 0),
    mf.newSaveMark(), 1000, 1000), null);
});
