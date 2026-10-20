// src/config.ts against the shared cases, tests/fixtures/config/cases.json,
// written by tests/fixtures/gen/config.py from what the Python makes of
// each: the walk run over a fake file system built from the case's tree,
// and the root, the paths, the merged options that are not default with
// their layers, each table field a file set, and the warnings, all as the
// Python found them.  The mod has no command line, so a case with flags is
// the Python's alone.
//
// Hermetic: the fake is the only file system the walk is given, the
// environment is the case's, and every path the walk asks for must lie
// under the case's own root, so no developer's config file, state or
// ~/.claude.json can reach a result.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";

import {
  CONFIG_ENV, dumpsUnicode, jsonLoads, load, nearest, stripJsonc,
} from "../src/config.ts";
import type { ConfigEnv, ConfigFs, FileStat, Rows } from "../src/config.ts";

const CASES = path.join(import.meta.dirname, "..", "..", "tests", "fixtures",
  "config", "cases.json");
// The case's scratch directory, which the Python's ${ROOT} stands for.
const ROOT = "/config-case";

type Case = {
  id: string; about: string;
  tree: { [rel: string]: string | null };
  env: { [name: string]: string };
  start: string; flags: string[];
  expected: {
    root: string | null;
    paths: { [layer: string]: string | null };
    options: { [name: string]: [unknown, string] };
    fields: { [path: string]: [unknown, string] };
    warnings: string[];
  };
};

const fill = (text: string) => text.replaceAll("${ROOT}", ROOT);
const cases = JSON.parse(fs.readFileSync(CASES, "utf8")) as Case[];

/** A file system holding the case's tree and nothing else, which records
 * every path it is asked about. */
function fakeFs(tree: Case["tree"]): { fs: ConfigFs; asked: string[] } {
  const files = new Map<string, string>();
  const dirs = new Set<string>();
  for (const [rel, text] of Object.entries(tree)) {
    const p = ROOT + "/" + rel.replace(/\/$/, "");
    if (text === null) dirs.add(p);
    else files.set(p, fill(text));
  }
  for (const p of [...files.keys(), ...dirs]) {
    for (let d = path.posix.dirname(p); d !== "/"; d = path.posix.dirname(d)) {
      dirs.add(d);
    }
  }
  const asked: string[] = [];
  // As the OS reads one, `..` taken off the directory before it: a
  // worktree's `.git` may name its git directory relatively.
  const stat = async (p: string): Promise<FileStat | null> => {
    asked.push(p);
    p = path.posix.normalize(p);
    const text = files.get(p);
    if (text !== undefined) {
      return { kind: "file", size: Buffer.byteLength(text), mtimeMs: 1 };
    }
    return dirs.has(p) ? { kind: "dir", size: 0, mtimeMs: 0 } : null;
  };
  return {
    asked,
    fs: {
      stat,
      read: async (p) => {
        asked.push(p);
        return files.get(path.posix.normalize(p)) ?? null;
      },
      realPath: async (p) => (await stat(p)) ? p : null,
    },
  };
}

function caseEnv(c: Case): ConfigEnv {
  const env: { [name: string]: string } = {};
  for (const [k, v] of Object.entries(c.env)) env[k] = fill(v);
  return env;
}

const filled = (v: unknown): unknown => JSON.parse(fill(JSON.stringify(v)));

test("the shared cases are the Python's, 38 of them", () => {
  assert.equal(cases.length, 38);
  assert.deepEqual(cases.filter((c) => c.flags.length).map((c) => c.id),
    ["flag-over-local", "list-flag-repeated"]);
});

for (const c of cases) {
  if (c.flags.length) continue;
  test(`config case ${c.id}: ${c.about}`, async () => {
    const env = caseEnv(c);
    for (const name of Object.keys(env)) {
      assert.ok((CONFIG_ENV as readonly string[]).includes(name),
        `the case sets ${name}, which the mod does not read`);
    }
    const { fs: fake, asked } = fakeFs(c.tree);
    const found = await load(fill(c.start), env, fake);
    const options: Case["expected"]["options"] = {};
    const fields: Case["expected"]["fields"] = {};
    for (const [name, value] of Object.entries(found.options.values)) {
      const layer = found.options.layers[name];
      if (name === "rows") {
        for (const [row, rec] of Object.entries(value as Rows)) {
          for (const [field, v] of Object.entries(rec)) {
            const at = found.options.fields[`${name}.${row}.${field}`];
            if (at) fields[`${name}.${row}.${field}`] = [v, at];
          }
        }
      } else if (layer !== "default") {
        options[name] = [value, layer];
      }
    }
    assert.deepEqual({
      root: found.root, paths: found.paths, options, fields,
      warnings: found.options.warnings,
    }, filled(c.expected));
    const outside = asked.filter((p) => !p.startsWith(ROOT + "/"));
    assert.deepEqual(outside, [], "the walk asked outside the case's tree");
  });
}

test("the reader reaches no file and no variable but those it is handed",
  () => {
    // Pure: what it reads comes through ConfigFs and ConfigEnv, so the
    // cases above, run over a fake, cannot meet this machine's files.
    const source = fs.readFileSync(
      path.join(import.meta.dirname, "..", "src", "config.ts"), "utf8");
    assert.ok(!/\bprocess\.|from "node:/.test(source),
      "src/config.ts reaches past ConfigFs and ConfigEnv");
  });

test("JSONC: comments and trailing commas outside strings only", () => {
  assert.equal(stripJsonc('{"a": "//x", // c\n "b": [1,],}'),
    '{"a": "//x",     \n "b": [1 ] }');
});

test("json.loads' shapes: key order kept, 1 apart from 1.0", () => {
  const got = jsonLoads('{"2": 1, "1": 1.0, "2": NaN}') as Map<string, unknown>;
  assert.deepEqual([...got.keys()], ["2", "1"]);
  assert.equal(got.get("1"), 1);
  assert.ok(Number.isNaN(got.get("2")));
  assert.equal(jsonLoads("12345678901234567890"), 12345678901234567890n);
  assert.equal(dumpsUnicode(jsonLoads('[2.0, {"é": "\\u0001"}]')),
    '[2.0, {"é": "\\u0001"}]');
});

test("the nearest key: within a third of the word, ties to the first", () => {
  assert.equal(nearest("rwos", ["rows", "hide"]), "rows");
  assert.equal(nearest("ab", ["ac", "ad"]), "ac");
  assert.equal(nearest("zzzzzz", ["rows"]), null);
});
