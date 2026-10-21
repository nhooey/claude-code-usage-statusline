// claude_records.ts against claude_records.py, case by case.
//
// tests/fixtures/gen/records.py runs the Python's functions and writes each
// call's arguments and result under tests/fixtures/records/; this runs the
// same call through the TypeScript and compares the two with deepEqual.
// Records keep the Python's field names, so they compare as they are.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import * as cr from "../src/claude_records_node.ts";
import { execFileSync } from "node:child_process";
import {
  agentReadingOf, foldAgentBytes, foldAgentRecord, newAgentFold,
} from "../src/claude_records.ts";
import { agentFoldOf, agentFoldText } from "../src/agent_fold.ts";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../..");
const DIR = path.join(REPO, "tests/fixtures/records");
// The cases spell paths from the repository root, as the generator ran.
process.chdir(REPO);

type Case = { fn: string; args: any[]; kw: Record<string, any>; out: any };

/** The generator's JSON back to values: {"$float": ...} is what JSON
 * cannot spell. */
function revive(v: any): any {
  if (Array.isArray(v)) return v.map(revive);
  if (v !== null && typeof v === "object") {
    if (Object.keys(v).length === 1 && "$float" in v) {
      return { inf: Infinity, "-inf": -Infinity, nan: NaN, "-0": -0 }[
        v.$float as string];
    }
    return Object.fromEntries(Object.entries(v).map(([k, x]) =>
      [k, revive(x)]));
  }
  return v;
}

/** A Map as the dict the Python returns. */
function dict(m: ReadonlyMap<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(m);
}

function indicesKept(p: string): number[] {
  const recs = cr._records(p);
  const kept = new Set(cr._dedupeUsage(recs));
  return recs.flatMap((r, i) => kept.has(r) ? [i] : []);
}

// Each Python function, as the TypeScript is called for it.
const RUN: Record<string, (c: Case) => unknown> = {
  _num: (c) => cr._num(c.args[0]),
  _first: (c) => cr._first(c.args[0], c.args.slice(1), c.kw.default),
  read_payload: (c) => cr.readPayload(c.args[0]),
  _records: (c) => cr._records(c.args[0]),
  _dedupe_usage: (c) => indicesKept(c.args[0]),
  ts_epoch: (c) => cr.tsEpoch(c.args[0]),
  _stamp_utc: (c) => cr._stampUtc(c.args[0]),
  squash: (c) => cr.squash(c.args[0], c.args[1]),
  _price: (c) => cr._price(c.args[0]),
  _usd: (c) => cr._usd(c.args[0], c.args[1], c.args[2], c.args[3],
    c.args[4]),

  classify: (c) => cr._records(c.args[0]).map((r) => [
    cr.opensTurn(r), cr.queuedText(r), cr.queueStep(r), cr.isCompaction(r),
    cr.turnStartText(r), cr.isWork(r), cr.endsTurn(r),
    cr.notificationText(r)]),
  scan_tool_spans: (c) => {
    const pending: cr.Pending = new Map();
    const tools: cr.Span[] = [], blocked: cr.Span[] = [];
    for (const r of cr._records(c.args[0])) {
      cr.scanToolSpans(r, pending, tools, blocked);
    }
    if (c.args[1] !== null) {
      cr.openToolSpans(pending, c.args[1], tools, blocked);
    }
    return { pending: [...pending].map(([k, [t, n]]) => [k, t, n]),
      tools, blocked };
  },
  tool_spans: (c) => {
    const blocked: cr.Span[] = [];
    return [cr.toolSpans(cr._records(c.args[0]), blocked), blocked];
  },
  agent_diff: (c) => cr.agentDiff(cr._records(c.args[0])),
  scan_background: (c) => {
    const open = new Map<string, string>();
    for (const r of cr._records(c.args[0])) cr.scanBackground(r, open);
    return [...open];
  },
  scan_agent_end: (c) => {
    const ends = new Map<string, number>();
    for (const r of cr._records(c.args[0])) cr.scanAgentEnd(r, ends);
    return [...ends];
  },
  live_eta: (c) => {
    const state = cr.newEtaState();
    return cr._records(c.args[0]).map((r) => {
      cr.liveEta(r, state);
      return [...state];
    });
  },
  eta_report: (c) => cr.etaReport(typeof c.args[0] === "string"
    ? cr._records(c.args[0]) : c.args[0]),
  agent_span: (c) => {
    const state: cr.SpanState = [null, null];
    const spans: cr.Span[] = [];
    const trace = cr._records(c.args[0]).map((r) => {
      cr.agentSpan(r, state, spans);
      return [[...state], [...spans]];
    });
    cr.closeAgentSpan(state, spans);
    return [...trace, [[...state], [...spans]]];
  },
  thread_clock: (c) => cr.threadClock(c.args[0], c.args[1], c.args[2]),
  split_clock: (c) => cr.splitClock(c.args[0], c.args[1], c.args[2],
    c.args[3]),
  turn_clock: (c) => cr.turnClock(c.args[0], c.args[1], c.args[2],
    c.args[3]),
  eta_finish: (c) => cr.etaFinish(c.args[0]),
  union_seconds: (c) => cr.unionSeconds(c.args[0]),
  net_tool_seconds: (c) => cr.netToolSeconds(c.args[0], c.args[1]),

  agent_files: (c) => cr.agentFiles(c.args[0]),
  _read_agent_file: (c) => cr._readAgentFile(c.args[0]),
  agent_label_id: (c) => cr.agentLabelId(c.args[0]),
  agent_label: (c) => cr.agentLabel(c.args[0]),
  agent_records: (c) => {
    const etas: (readonly [number | null, number | null])[] = [];
    const seen = c.args.length > 1 ? new Set<unknown>(c.args[1]) : null;
    const got = cr.agentRecords(c.args[0], seen, seen ? null : etas);
    // The same reading through the saved folds, written then read on.
    const stateDir = tmp();
    for (let i = 0; i < 2; i++) {
      assert.deepEqual(cr.agentRecords(c.args[0], seen && new Set(c.args[1]),
        null, stateDir), got);
    }
    return [got, etas];
  },
  publish_agent_offsets: (c) => {
    const dir = tmp();
    const agents = c.args[1] as cr.AgentRec[];
    const held = c.args[2] && new Map(Object.entries(c.args[2])) as
      Map<string, number>;
    cr.publishAgentOffsets(c.args[0], agents, held, dir);
    const p = cr._agentStatePath(c.args[0], dir);
    const got = cr.agentOffsets(c.args[0], dir);
    return [path.basename(p), fs.readFileSync(p, "utf-8"),
      got && dict(got)];
  },
  agent_offsets: (c) => {
    const dir = tmp();
    if (c.args[1] !== null) {
      fs.writeFileSync(cr._agentStatePath(c.args[0], dir), c.args[1]);
    }
    const got = cr.agentOffsets(c.args[0], dir);
    return got && dict(got);
  },
  inbox_classify: (c) => cr._records(c.args[0]).map((r) =>
    [cr.queuedSend(r), cr.inboxDelivery(r)]),
  inbox_sends: (c) => cr.inboxSends(c.args[0]),
  inbox_deliveries: (c) => cr.inboxDeliveries(c.args[0]),
  marked_records: (c) => cr.markedRecords(c.args[0],
    c.args[1].map((m: string) => new TextEncoder().encode(m))),
  inbox_counts: (c) => dict(cr.inboxCounts(c.args[0],
    new Map(Object.entries(c.args[1])), c.args[2] ?? null)),

  read_transcript: (c) => cr.readTranscript(c.args[0], null, [],
    c.kw.now ?? null),
  read_turns: (c) => {
    const held = new Map<string, number>();
    const turns = turnsWith(c.args[0], c.args[1], held);
    return [turns, dict(held)];
  },
  read_turns_settled: (c) => turnsWith(c.args[0], c.args[1], null),
  turn_model_s: (c) => cr.turnModelS(c.args[0]),
  turn_times: (c) => cr.turnTimes(c.args[0]),
  _settled: (c) => cr._settled(c.args[0]),
  open_turn: (c) => cr.openTurn(c.args[0]),
};

/** readTurns' core over the file at `p`, with the offsets the Python read
 * from its state directory handed in. */
function turnsWith(p: string, offsets: Record<string, number> | null,
  held: Map<string, number> | null): cr.Turn[] {
  return cr.turnsOf(cr._records(p), (seen) => cr.agentRecords(p, seen),
    offsets && new Map(Object.entries(offsets)), held, cr.agentLabel);
}

/** A fresh private directory, for state a case writes. */
function tmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "claude-records-"));
}


for (const file of fs.readdirSync(DIR).filter((f) => f.endsWith(".json"))
  .sort()) {
  const cases: Case[] = revive(JSON.parse(
    fs.readFileSync(path.join(DIR, file), "utf-8"))).cases;
  const byFn = new Map<string, Case[]>();
  for (const c of cases) {
    byFn.set(c.fn, [...(byFn.get(c.fn) ?? []), c]);
  }
  for (const [fn, group] of byFn) {
    test(`${file.replace(/\.json$/, "")}: ${fn} (${group.length})`, () => {
      const run = RUN[fn];
      assert.ok(run, `no TypeScript runner for ${fn}`);
      for (const c of group) {
        const got = run(c);
        assert.deepEqual(got, c.out,
          `${fn}(${JSON.stringify(c.args).slice(0, 300)})`);
      }
    });
  }
}

// Session 36be113b on 2026-10-21 (records.py's handback.jsonl): a peer's
// hand-back delivered into a running turn stays in it, the prompt sent
// again from a dequeue with no content opens its own turn, and 🎤 reads an
// agent's message out of Claude Code's frame.
test("a hand-back stays in its turn, and a queued prompt opens one", () => {
  const p = path.join(DIR, "inputs/handback.jsonl");
  const turns = cr.readTurns(p, []);
  assert.deepEqual(
    turns.map((t) => [t.text, t.prompt_id, t.turn_index, t.calls]), [
      ["make it work", "H1", 26, 2],
      ["make it work", "H3", 27, 1],
      ["agent message: push it", "H4", 27, 1],
      ["agent report: Rule added.\nLine two.", "H5", 28, 1]]);
  const tr = cr.readTranscript(p, []);
  assert.deepEqual([tr.prompt_id, tr.turn_index], ["H5", 28]);
});

// The mod reads an agent's file as it grows, folding only what was appended
// since its last read: cut anywhere, mid-line included, the file folded
// piece by piece reads as the Python reads it whole.
test("an agent file folded as it grows reads as it does whole", () => {
  let files = 0;
  for (const file of fs.readdirSync(DIR).filter((f) => f.endsWith(".json"))) {
    const cases: Case[] = revive(JSON.parse(
      fs.readFileSync(path.join(DIR, file), "utf-8"))).cases;
    for (const c of cases.filter((c) => c.fn === "_read_agent_file")) {
      if (c.out === null) continue;
      const data = fs.readFileSync(c.args[0]);
      for (const step of [1, 7, 97, 4096]) {
        const fold = newAgentFold();
        for (let end = step; end < data.length; end += step) {
          foldAgentBytes(fold, data.subarray(fold.pos, end));
        }
        foldAgentBytes(fold, data.subarray(fold.pos), true);
        assert.deepEqual(agentReadingOf(fold), c.out,
          `${c.args[0]} in pieces of ${step}`);
      }
      files++;
    }
  }
  assert.ok(files > 0, "no _read_agent_file cases");
});

/** Each `_read_agent_file` case with a reading: its file, and the reading
 * the Python made of it whole. */
function agentCases(): Case[] {
  return fs.readdirSync(DIR).filter((f) => f.endsWith(".json")).flatMap((f) =>
    (revive(JSON.parse(fs.readFileSync(path.join(DIR, f), "utf-8")))
      .cases as Case[]).filter((c) =>
      c.fn === "_read_agent_file" && c.out !== null));
}

// What mod/scripts/agent_lines.py cuts a file down to folds as the file
// does whole, a piece at a time, as the mod reads a large stretch.
test("an agent file's lines cut down by agent_lines.py read as it does whole",
  () => {
    const script = path.join(REPO, "mod/scripts/agent_lines.py");
    for (const c of agentCases()) {
      const data = fs.readFileSync(c.args[0]);
      const whole = data.lastIndexOf(10) + 1;
      const fold = newAgentFold();
      while (fold.pos < whole) {
        const out = execFileSync("python3", [script, c.args[0],
          String(fold.pos), String(data.length)]).toString().split("\n");
        for (const l of out.slice(1).filter(Boolean)) {
          const tab = l.indexOf("\t");
          let r: unknown = null;
          try {
            r = JSON.parse(l.slice(tab + 1));
          } catch {
            // Skipped, as the line itself is.
          }
          foldAgentRecord(fold, Number(l.slice(0, tab)), r);
        }
        assert.equal(fold.pos, Number(out[0]), c.args[0]);
      }
      foldAgentBytes(fold, data.subarray(fold.pos), true);
      assert.deepEqual(agentReadingOf(fold), c.out, c.args[0]);
      // And the whole fold, the panel's fields too.
      const all = newAgentFold();
      foldAgentBytes(all, data, true);
      assert.equal(agentFoldText(fold, 1, ""), agentFoldText(all, 1, ""),
        c.args[0]);
    }
  });

// A fold saved halfway and read back goes on to the same reading, and one
// saved under another format is not read back.
test("an agent fold saved and read back reads on as before", () => {
  for (const c of agentCases()) {
    const data = fs.readFileSync(c.args[0]);
    const fold = newAgentFold();
    foldAgentBytes(fold, data.subarray(0, data.length >> 1));
    const text = agentFoldText(fold, 1, "");
    assert.equal(agentFoldOf(text.replace(/^\{"format":\d+/,
      '{"format":0')), null);
    const back = agentFoldOf(text)![2];
    foldAgentBytes(back, data.subarray(back.pos), true);
    assert.deepEqual(agentReadingOf(back), c.out, c.args[0]);
  }
});
