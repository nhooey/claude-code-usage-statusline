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
};

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
