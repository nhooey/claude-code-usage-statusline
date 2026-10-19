// claude_records.ts against claude_records.py, case by case.
//
// tests/fixtures/gen/records.py runs the Python's functions and writes each
// call's arguments and result under tests/fixtures/records/; this runs the
// same call through the TypeScript and compares the two with deepEqual.
// Records come back with the Python's field names, so a TypeScript record
// is compared with its keys turned back to snake_case.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import * as cr from "../src/claude_records.ts";

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

/** A record's fields under the Python's names. */
function snake(r: any): any {
  return Object.fromEntries(Object.entries(r).map(([k, v]) =>
    [k.replace(/[A-Z]/g, (c) => "_" + c.toLowerCase()), v]));
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
  read_payload: (c) => snake(cr.readPayload(c.args[0])),
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
    const got = cr.agentRecords(c.args[0], seen, seen ? null : etas)
      .map(snake);
    // The same reading through the cache, written then served from it.
    const cache = { stateDir: tmp(), version: "test", now: 1e12 };
    for (let i = 0; i < 2; i++) {
      assert.deepEqual(cr.agentRecords(c.args[0], seen && new Set(c.args[1]),
        null, cache).map(snake), got);
    }
    return [got, etas];
  },
  publish_agent_offsets: (c) => {
    const dir = tmp();
    const agents = c.args[1].map(unsnake) as cr.AgentRec[];
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
};

/** A fresh private directory, for state a case writes. */
function tmp(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "claude-records-"));
}

/** A record the Python wrote, under the TypeScript's names. */
function unsnake(r: any): any {
  return Object.fromEntries(Object.entries(r).map(([k, v]) =>
    [k.replace(/_([a-z])/g, (_, c) => c.toUpperCase()), v]));
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
