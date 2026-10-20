// The main transcript's folds over the real transcripts on this machine:
// the TypeScript's side of tests/fold_real.py, which has the whole story.
//
//   node mod/tools/check-fold.ts [--largest N] [--seed S] [FILE...]
//
// Not in CI: it reads ~/.claude/projects, which is private.  For each
// transcript (every *.jsonl under ~/.claude/projects, or the FILEs named;
// the N largest with --largest) it folds the records as transcriptOf and
// turnsOf do, breaks the fold at three record boundaries, either side of
// every compaction and once inside a line, and checks that each reads on
// to the whole fold.  One line a file, then a total; the exit status is the
// number of files that broke.  `check-folds` in the dev shell runs both.
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { isDeepStrictEqual } from "node:util";
import * as cr from "../src/claude_records.ts";
import * as mf from "../src/main_fold.ts";

type Folds = { tr: cr.TranscriptFold; tu: cr.TurnsFold };

function foldAll(records: readonly cr.Rec[], f?: Folds): Folds {
  return { tr: cr.foldTranscriptAll(records, f?.tr),
    tu: cr.foldTurnsAll(records, f?.tu) };
}

/** Both finishes, with no agents: the agents never reach the fold. */
function finish(f: Folds): unknown {
  return [cr.transcriptFinish(f.tr, [], [], 1e10),
    cr.turnsFinish(f.tu, () => [], null, new Map())];
}

/** mulberry32: a seeded generator, so a run can be repeated. */
function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Every *.jsonl under `dir`, at any depth. */
function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.name.endsWith(".jsonl")) out.push(p);
  }
  return out;
}

/** Where the fold is broken: three record boundaries, and either side of
 * every compaction. */
function breaks(records: readonly cr.Rec[], rand: () => number): number[] {
  const n = records.length;
  const out = new Set<number>();
  for (let i = 0; i < 3; i++) out.add(Math.floor(rand() * (n + 1)));
  records.forEach((r, i) => {
    if (cr.isCompaction(r)) out.add(i).add(i + 1);
  });
  return [...out].sort((a, b) => a - b);
}

/** What broke for one transcript, with its counts. */
function check(file: string, rand: () => number) {
  const data = fs.readFileSync(file);
  const records = cr._recordsOf(data);
  const whole = finish(foldAll(records));
  const at = breaks(records, rand);
  const broke: string[] = [];
  let f = foldAll([]);
  let done = 0;
  for (const k of at) {
    foldAll(records.slice(done, k), f);
    done = k;
    const here = finish(f);
    // Saved as text and read back, as a reload reads it.
    const back = roundTrip(f);
    if (!back) {
      broke.push(`not read back at record ${k}`);
      return { broke, records: records.length, compactions: 0,
        breaks: at.length, state: null };
    }
    f = back;
    if (!isDeepStrictEqual(finish(f), here)) {
      broke.push(`read back otherwise at record ${k}`);
    }
  }
  foldAll(records.slice(done), f);
  if (!isDeepStrictEqual(finish(f), whole)) {
    broke.push(`read on from ${at.length} breaks`);
  }
  const state = stateSize(f);
  const nl = data.lastIndexOf(10,
    Math.max(0, Math.floor(rand() * data.length) - 1));
  if (nl > 0) {
    const start = data.lastIndexOf(10, nl - 1) + 1;
    const cut = start + ((nl - start) >> 1);
    const g = foldAll(cr._recordsOf(data.subarray(0, start)));
    const tail = cr._recordsOf(data.subarray(start, cut));
    const view = { tr: cr.transcriptFoldWith(g.tr, tail),
      tu: cr.turnsFoldWith(g.tu, tail) };
    if (!isDeepStrictEqual(finish(view),
      finish(foldAll(cr._recordsOf(data.subarray(0, cut)))))) {
      broke.push(`cut at byte ${cut}`);
    }
    foldAll(cr._recordsOf(data.subarray(start)), g);
    if (!isDeepStrictEqual(finish(g), whole)) {
      broke.push(`completed after byte ${cut}`);
    }
  }
  return { broke, records: records.length,
    compactions: records.filter(cr.isCompaction).length, breaks: at.length,
    state };
}

// What a round trip's head says of the transcript, which no check reads.
const META: mf.FoldMeta = { offset: 0, first: "", tail: "" };

/** `f` saved as a first save writes it, with no cap on the head. */
function saveAll(f: Folds) {
  return mf.foldSave(f, META, mf.newSaveMark(), mf.FOLD_PART_BYTES,
    Infinity)!;
}

/** `f` saved and read back, or null. */
function roundTrip(f: Folds): Folds | null {
  const got = saveAll(f);
  const files = new Map(got.parts.map(([i, t]) => [mf.partName(i), t]));
  files.set(got.slot, got.head);
  return mf.foldLoad((n) => files.get(n) ?? null)?.fold ?? null;
}

/** The parts, their bytes and the head's bytes of `f` saved. */
function stateSize(f: Folds) {
  const got = saveAll(f);
  return { parts: got.parts.length,
    bytes: got.parts.reduce((n, [, t]) => n + mf.utf8Bytes(t), 0),
    head: mf.utf8Bytes(got.head) };
}

function main(argv: string[]): number {
  let largest = 0, seed = 1;
  const named: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--largest") largest = Number(argv[++i]);
    else if (argv[i] === "--seed") seed = Number(argv[++i]);
    else named.push(argv[i]);
  }
  const home = path.join(os.homedir(), ".claude/projects");
  let files = (named.length ? named : walk(home))
    .map((p) => ({ p, size: fs.statSync(p).size }))
    .sort((a, b) => b.size - a.size || (a.p < b.p ? -1 : 1));
  if (largest) files = files.slice(0, largest);
  const rand = seeded(seed);
  let bad = 0, total = 0, biggest = 0;
  const t0 = performance.now();
  for (const { p, size } of files) {
    const t = performance.now();
    total += size;
    const got = check(p, rand);
    if (got.broke.length) bad++;
    const s = got.state;
    if (s) biggest = Math.max(biggest, s.bytes + s.head);
    console.log(`${got.broke.length ? "FAIL" : "ok  "} ` +
      `${(size / 1e6).toFixed(1).padStart(7)} MB ` +
      `${String(got.records).padStart(7)} records ` +
      `${String(got.compactions).padStart(3)} compactions ` +
      `${String(got.breaks).padStart(3)} breaks  ` +
      (s ? `${String(s.parts).padStart(2)} parts ` +
        `${(s.bytes / 1e6).toFixed(2).padStart(6)} MB + head ` +
        `${(s.head / 1e3).toFixed(1).padStart(6)} KB` : "") +
      `  ${((performance.now() - t) / 1000).toFixed(1).padStart(6)}s  ` +
      path.relative(home, p) +
      (got.broke.length ? `  (${got.broke.join("; ")})` : ""));
  }
  console.log(`${files.length} files, ${(total / 1e9).toFixed(1)} GB, ` +
    `${bad} broke, largest state ${(biggest / 1e6).toFixed(2)} MB, ` +
    `${((performance.now() - t0) / 1000).toFixed(0)}s`);
  return Math.min(bad, 255);
}

process.exitCode = main(process.argv.slice(2));
