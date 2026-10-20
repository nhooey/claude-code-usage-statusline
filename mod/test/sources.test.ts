// The usage-source reader against the Python it ports.  Every case is in
// tests/fixtures/sources/, written by tests/fixtures/gen/sources.py from
// the Python reader; this runs each through the TypeScript and compares.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  cachedReading, cacheName, claudeUsageTracker, commandReading, epoch,
  hasReading, isCacheName, nativeReading, normalise, number, periodBounds,
  pyJsonLoads,
} from "../src/sources_node.ts";
import type { Dict } from "../src/sources_node.ts";
import { isDict } from "../src/py.ts";
import {
  legacyLimits, plistLoads, prepareClaudeReading, statusSourceContext,
  trackerReading,
} from "../src/claude_sources_node.ts";

const FIXTURES = path.join(import.meta.dirname, "..", "..", "tests",
                           "fixtures", "sources");

// The fixtures carry NaN where Python wrote one, so they are read the way
// Python reads JSON.
function load(name: string): any {
  return pyJsonLoads(fs.readFileSync(path.join(FIXTURES, name), "utf8"));
}

// Plain objects, so deepEqual compares values and not prototypes, and
// -0 as 0, which JSON cannot tell apart either.
function canon(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canon);
  if (isDict(value)) {
    const out: Dict = {};
    for (const [k, v] of Object.entries(value)) {
      if (v !== undefined) out[k] = canon(v);
    }
    return out;
  }
  return Object.is(value, -0) ? 0 : value;
}

function same(actual: unknown, expected: unknown, what: string) {
  assert.deepEqual(canon(actual), canon(expected), what);
}

function scratch(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "sources-test."));
}

// Sorted keys at every level: one text per value, to sort cache files by.
function sorted(value: unknown): string {
  return JSON.stringify(value, (_k, v) => (isDict(v)
    ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, v[k]])) : v));
}

function setTz(tz: string) {
  process.env.TZ = tz;
}

const counts: { [group: string]: number } = {};
function count(group: string) {
  counts[group] = (counts[group] ?? 0) + 1;
}

test("values: epoch, _number, period_bounds, cache_name", () => {
  const v = load("values.json");
  for (const c of v.epoch) {
    same(epoch(c.input), c.expected, "epoch " + JSON.stringify(c.input));
    count("values");
  }
  for (const c of v.number) {
    same(number(c.input, c.upper), c.expected,
         "number " + JSON.stringify(c.input) + " upper " + c.upper);
    count("values");
  }
  for (const c of v.period_bounds) {
    same(periodBounds(c.kind, c.now), c.expected, c.kind + " " + c.now);
    count("values");
  }
  for (const c of v.cache_name) {
    assert.equal(cacheName(c.input[0], c.input[1], c.input[2], c.input[3]),
                 c.expected);
    assert.ok(isCacheName(c.expected), c.expected);
    count("values");
  }
});

// findCompatible opens a usage cache's name and nothing else in the state
// directory, as state.find_compatible does.
test("isCacheName", () => {
  const h = "0123456789abcdef".repeat(4);
  assert.ok(isCacheName(h + ".json"));
  for (const n of [`claude-calibration-${h}.json`, `reported-${h}.json`,
    `claude-agent-offsets-${h}.json`, `${h}.cache`, `${h}.json.1`,
    h.slice(1) + ".json", h.toUpperCase() + ".json"]) {
    assert.ok(!isCacheName(n), n);
  }
});

test("normalise, has_reading, _cached_reading", () => {
  for (const c of load("normalise.json")) {
    const clean = normalise(c.input, "cmd");
    same(clean, c.expected, c.name);
    assert.equal(hasReading(clean), c.has_reading, c.name);
    for (const ttl of ["60", "300"]) {
      same(cachedReading(c.input, "cmd", c.now, Number(ttl)), c.cached[ttl],
           c.name + " ttl " + ttl);
    }
    count("normalise");
  }
});

test("native_reading", () => {
  for (const c of load("native.json")) {
    same(nativeReading("claude", c.context), c.expected, c.name);
    count("native");
  }
});

test("tracker: plist store to reading", async () => {
  const dir = scratch();
  const file = path.join(dir, "tracker.plist");
  const env = { CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST: file };
  try {
    for (const c of load("tracker.json")) {
      setTz(c.tz);
      fs.writeFileSync(file, c.plist);
      const bytes = new Uint8Array(fs.readFileSync(file));
      if (isDict(c.tracker_reading) && "raises" in c.tracker_reading) {
        assert.throws(() => trackerReading(plistLoads(bytes)), c.name);
      } else {
        same(trackerReading(plistLoads(bytes)), c.tracker_reading, c.name);
      }
      // A store expat refuses, or one that is not a dict, is no reading in
      // both languages: neither readout falls over on it.
      same(await claudeUsageTracker(env), c.expected, c.name);
      count("tracker");
    }
  } finally {
    setTz("UTC");
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("command_reading and what it is sent", async () => {
  const dir = scratch();
  try {
    // One file, rewritten for each case: macOS looks over every new
    // executable on its first run, for a tenth of a second, and a file it
    // has looked at once it lets run.  A case with no script gets a name
    // never written.
    const file = path.join(dir, "cmd");
    for (const c of load("command.json")) {
      fs.rmSync(file + ".stdin", { force: true });
      if (c.script !== null) {
        fs.writeFileSync(file, c.script);
        fs.chmodSync(file, c.executable ? 0o700 : 0o600);
      }
      const run = c.script !== null ? file : path.join(dir, "missing");
      same(await commandReading(run, c.context, c.timeout), c.expected,
           c.name);
      let stdin: string | null = null;
      try { stdin = fs.readFileSync(run + ".stdin", "utf8"); } catch { /**/ }
      assert.equal(stdin, c.stdin, c.name + " stdin");
      count("command");
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("legacy_limits", () => {
  try {
    for (const c of load("limits.json")) {
      setTz(c.tz);
      same(legacyLimits(c.reading), c.expected, c.name + " in " + c.tz);
      count("limits");
    }
  } finally {
    setTz("UTC");
  }
});

test("collect: scenarios over one state directory", async () => {
  setTz("UTC");
  for (const scenario of load("collect.json")) {
    const dir = scratch();
    const stateDir = path.join(dir, "state");
    const tracker = path.join(dir, "tracker.plist");
    const env = { CODING_AGENT_USAGE_LINE_STATE_DIR: stateDir,
                  CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST: tracker };
    const put = (value: unknown) =>
      pyJsonLoads(JSON.stringify(value).replaceAll("${DIR}", dir));
    const scrub = (value: unknown) =>
      JSON.parse(JSON.stringify(canon(value)).replaceAll(dir, "${DIR}"));
    try {
      let n = 0;
      for (const s of scenario.steps) {
        const what = scenario.name + ", step " + n++;
        for (const [name, script] of Object.entries(s.commands)) {
          fs.writeFileSync(path.join(dir, name), script as string,
                           { mode: 0o700 });
        }
        if (s.tracker === null) fs.rmSync(tracker, { force: true });
        else fs.writeFileSync(tracker, s.tracker);
        const spec = s.spec.replaceAll("${DIR}", dir);
        const context = s.context !== null ? s.context
          : statusSourceContext(spec, s.session, "claude-opus-5-5", s.now,
                                s.payload);
        same(context, put(s.built_context), what + " context");
        const prepared = await prepareClaudeReading(
          spec, s.account, s.period, context, s.now, env);
        same(scrub(prepared.reading), s.reading, what + " reading");
        same(prepared.limits, s.limits, what + " limits");
        // Every cache file, as Python left it: the same contents under the
        // same names, which is what lets the two share one cache.
        const files: Dict[] = [];
        for (const entry of fs.readdirSync(stateDir).sort()) {
          if (!entry.endsWith(".json")) continue;
          const value = pyJsonLoads(fs.readFileSync(
            path.join(stateDir, entry), "utf8")) as Dict;
          assert.equal(entry, cacheName(value.agent as string,
                                        value.source as string,
                                        value.account_name as string,
                                        value.period_start as string),
                       what + " cache name");
          files.push(scrub(value));
        }
        const order = (list: unknown[]) =>
          list.map((f) => canon(f)).sort((a, b) =>
            sorted(a) < sorted(b) ? -1 : 1);
        same(order(files), order(s.state), what + " state");
        count("collect");
      }
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }
});

test("every case ran", () => {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  console.log("# sources shared cases: " + total + " " +
              JSON.stringify(counts));
  assert.ok(total > 0);
});
