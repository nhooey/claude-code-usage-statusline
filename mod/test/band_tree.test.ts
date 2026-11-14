// The band's tree (band_tree.ts) and the subagents' facts it draws
// (subagent_tasks.ts): agentUsageOf against claude.py's agent_usage_of
// over the fixture agents, the progress update off a transcript's tail,
// and the tree's lines, groups, cap and folds over the panel corpus's
// tasks.  The drawn rows themselves are pinned by the rows' cases
// (rows.test.ts, gen-row-cases.ts's tree cases).
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { settings, stripAnsi, visWidth } from "../src/formatting.ts";
import { join } from "../src/spans.ts";
import type { Dict } from "../src/py.ts";
import { foldAgentBytes, newAgentFold } from "../src/claude_records.ts";
import {
  agentClock, agentShares, agentUsageOf, progressOf, taskStatus, treeTasks,
} from "../src/subagent_tasks.ts";
import type { TreeTask } from "../src/subagent_tasks.ts";
import { treeRows } from "../src/band_tree.ts";
import type { TreeInput } from "../src/band_tree.ts";
import { draw } from "../src/grid.ts";
import type { Row } from "../src/grid.ts";
import { bandRows, fixedKeys, treeOf } from "../src/band.ts";
import type { BandOpts, Live, Phase } from "../src/band.ts";
import { corpusAgents } from "../tools/gen-row-cases.ts";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)),
  "../..");
const ST = settings({}, true, false, 5);
const NOW = 1786847000;
const LIMITS = { session_pct: "15", session_reset: "", session_share: "",
  weekly_pct: "87", weekly_reset: "", weekly_share: "", session_turn: "",
  weekly_turn: "" };

/** The fixture agents' transcripts, every one under
 * tests/fixtures/transcripts/subagent/. */
function agentFiles(): string[] {
  const top = path.join(REPO, "tests/fixtures/transcripts/subagent");
  const out: string[] = [];
  for (const d of fs.readdirSync(top).sort()) {
    const sub = path.join(top, d, "subagents");
    if (!fs.existsSync(sub)) continue;
    for (const f of fs.readdirSync(sub).sort()) {
      if (f.endsWith(".jsonl")) out.push(path.join(sub, f));
    }
  }
  return out;
}

test("agentUsageOf is claude.py's agent_usage_of, field for field, over " +
  "every fixture agent", () => {
  const files = agentFiles();
  assert.ok(files.length > 3);
  const py = JSON.parse(execFileSync("python3", ["-c",
    "import sys, json\nfrom coding_agent_usage_line import claude\n" +
    "print(json.dumps([claude.read_agent_usage(p)._asdict() " +
    "for p in sys.argv[1:]]))", ...files], { cwd: REPO, encoding: "utf8" }));
  files.forEach((f, i) => {
    const fold = newAgentFold();
    foldAgentBytes(fold, fs.readFileSync(f), true);
    const got = JSON.parse(JSON.stringify(agentUsageOf(fold))) as Dict;
    const want = py[i] as Dict;
    assert.deepEqual(Object.keys(got).sort(), Object.keys(want).sort(), f);
    for (const k of Object.keys(want)) {
      assert.deepEqual(got[k], want[k], path.basename(f) + " " + k);
    }
  });
});

test("agentClock runs a running agent's open span on to now, and stops a " +
  "finished one's where its file does", () => {
  const usage: Dict = { work: [[100, 160]], tools: [[110, 120]],
    waiting: [], open_at: 200, pending: [] };
  assert.deepEqual(agentClock(usage, false, 300), [50, 10]);
  assert.deepEqual(agentClock(usage, true, 300), [150, 10]);
});

test("agentShares divides what an agent billed in each window by the " +
  "calibrated dollars a percent", () => {
  const usage: Dict = { parts: [[null, 1.0], [1786846000, 2.0]] };
  assert.deepEqual(agentShares(usage, { sess: 0.5, week: 2.0 }, {}),
    { sess: 6, week: 1.5 });
  assert.deepEqual(agentShares(usage, { sess: 0.5 }, {}),
    { sess: 6, week: null });
  assert.deepEqual(agentShares({ parts: [] }, { sess: 0.5 }, {}),
    { sess: null, week: null });
});

test("taskStatus reads a waiting loop as running and an idle teammate as " +
  "done", () => {
  assert.deepEqual(["waiting", "idle", "running", "killed", undefined]
    .map(taskStatus), ["running", "completed", "running", "killed",
    "completed"]);
});

test("progressOf is the first worded line of the last assistant text " +
  "block, the ETA report left out", () => {
  const rec = (content: unknown) => JSON.stringify({ type: "assistant",
    message: { role: "assistant", content } });
  const tail = [
    rec([{ type: "text", text: "Reading the grid first." }]),
    JSON.stringify({ type: "user", message: { content: [{
      type: "tool_result", content: "ok" }] } }),
    rec([{ type: "text", text: "\n  Now the tree.\nMore words." },
      { type: "tool_use", name: "Read", input: {} }]),
    rec([{ type: "text",
      text: "⛳ skills/coding-agent-usage-line-report-eta: ETA 4m" }]),
  ].join("\n");
  assert.equal(progressOf(tail, false), "Now the tree.");
  assert.equal(progressOf('{"half": ' + "\n" + tail, true), "Now the tree.");
  assert.equal(progressOf(rec([{ type: "tool_use", input: {} }]), false), "");
});

test("treeTasks builds each task from the list and the fold, and the " +
  "sidecar takes the list's type and parent where it has none", () => {
  const [t] = treeTasks([{ id: "a1", listed: { id: "a1", status: "waiting",
    type: "Explore", parentId: "p", description: "Look around",
    name: "Moss" }, meta: null, fold: null, inbox: 2, branch: "b",
  progress: "Reading" }], NOW, () => 200000, null, null);
  assert.equal(t.task.status, "running");
  assert.equal(t.task.name, "Moss");
  assert.equal(t.task.type, "local_agent");
  assert.deepEqual(t.meta, { agentType: "Explore", parentAgentId: "p" });
  assert.deepEqual([t.usage.inbox, t.usage.branch, t.usage.eta,
    t.usage.ctx_window], [2, "b", null, 0]);
  assert.equal(t.progress, "Reading");
});

/** The tree over a corpus case's tasks, under 🧵 main, as plain lines at
 * 200 columns. */
function tree(id: string, over: Partial<TreeInput> = {},
  hide: string[] = [], turnStart: number | null = null): string[] {
  const doc = corpusAgents(id, "Checking the binary");
  const blank = (scope: string): Row => ({ scope, label: [], cells: {} });
  const rows = treeRows(ST, { session: blank("session"),
    main: blank("main"), turn: blank("turn"),
    workspace: { project: "repo", branch: "main", dirty: false, dir: "",
      pr: "38", style: "" },
    mainPhase: "🟢", mainInbox: 0, mainProgress: doc.main_progress as string,
    turnPhase: "🟢", agents: { tasks: doc.tasks as TreeTask[],
      limits: LIMITS, now: NOW, turnStart }, cap: 6, ...over }, hide);
  const keys = fixedKeys(ST, 200, hide);
  return rows.map((r) => stripAnsi(join(draw(ST, r, keys, 200, hide)))
    .trimEnd());
}

test("the tree draws 🎮 with the workspace, then 🎤, then 🧵 main and " +
  "its agents, each line three columns a level", () => {
  const lines = tree("03-tree@220");
  const heads = lines.map((l) => l.slice(0, l.search(/[🎮🧵🎤🎩🔍🔩]/u)));
  assert.deepEqual(heads, ["⊟ ", "├─ ", "╰⊟ ", "   ├⊟ ", "   │  ├─ ",
    "   │  ╰⊟ ", "   │     ╰⊟ ", "   │        ╰─ ", "   ╰─ "]);
  assert.match(lines[0], /^⊟ 🎮 📦repo 🌿main  🔀#38/u);
  assert.match(lines[1], /^├─ 🎤🟢 turn$/u);
  assert.match(lines[2], /^╰⊟ 🧵🟢 main  Checking the binary/u);
});

test("without 🧵 main, 🎤 is the root's last child", () => {
  const lines = tree("03-tree@220", { main: null, agents: null });
  assert.deepEqual(lines.map((l) => l.slice(0, l.search(/[🎮🎤]/u))),
    ["⊟ ", "╰─ "]);
});

test("every figure keeps its column on every row of the tree", () => {
  const lines = tree("03-tree@220");
  const at = (l: string) => visWidth(l.slice(0, l.indexOf("⌛")), ST.widths);
  const agents = lines.slice(3);
  assert.equal(new Set(agents.map(at)).size, 1);
});

test("an agent's label packs its own counts before its name, with no " +
  "blank slots for the counts other rows have", () => {
  const lines = tree("03-tree@220");
  const label = (name: string) => lines.find((l) => l.includes(name))!;
  assert.match(label("Trunk"), /🎩🟢 🤏2 Trunk/u);
  assert.match(label("Twig"), /🔍🟢 📨1 Twig/u);
  assert.match(label("Tendril"), /🔩🟢 Tendril/u);
  assert.match(label("Moss"), /🔍🟢 Moss/u);
});

test("past the cap the later siblings fold into their parent's … N more, " +
  "and every shown row's parents stay", () => {
  const lines = tree("03-tree@220", { cap: 2 });
  assert.equal(lines.length, 7);
  assert.match(lines[3], /^   ├⊟ 🎩🟢 🤏2 Trunk/u);
  assert.match(lines[4], /^   │  ├─ 🔍🟢 📨1 Twig/u);
  assert.match(lines[5], /^   │  ╰⊞ … 3 more/u);
  assert.match(lines[6], /^   ╰⊞ … 1 more/u);
});

test("a folded agent draws ⊞ and counts every agent hidden under it", () => {
  const lines = tree("03-tree@220", { folded: new Set(["t1"]) });
  const trunk = lines.find((l) => l.includes("Trunk"))!;
  assert.match(trunk, /├⊞ 🎩🟢 👶🏻4 🤏2 Trunk/u);
  assert.ok(!lines.some((l) => l.includes("Twig")));
});

test("✅ N done sums the agents that ended since the turn opened, under " +
  "🧵 main", () => {
  const lines = tree("01-mixed@220", {}, [], NOW - 3600);
  const done = lines.find((l) => l.includes("done"))!;
  assert.match(done, /^   ╰⊞ ✅ 4 done +✅  18m/u);
  // Only those since the turn opened.
  assert.match(tree("01-mixed@220", {}, [], 1786845500).find((l) =>
    l.includes("done"))!, /✅ 2 done/u);
  assert.ok(!lines.some((l) => l.includes("Daisy")));
  assert.ok(!tree("01-mixed@220").some((l) => l.includes("done")));
});

test("the progress update is drawn for a working or waiting thread " +
  "alone, and chat.progress hides it", () => {
  assert.ok(tree("01-mixed@220").some((l) =>
    /Marigold  Running the suite/u.test(l)));
  assert.ok(!tree("01-mixed@220", {}, ["*.chat.progress"]).some((l) =>
    l.includes("Running the suite") || l.includes("Checking the binary")));
  assert.ok(!tree("01-mixed@220", { mainPhase: "⚫" }).some((l) =>
    l.includes("Checking the binary")));
});

/** The band's tree over the baseline status document, its turn opened an
 * hour before the clock, with 01-mixed@220's agents, in `phase` and with
 * `rows.subagents.live` at `agents`, as plain lines at 200 columns. */
function bandTree(phase: Phase, agents: Live): string[] {
  const file = path.join(REPO, "tests/fixtures/figures/status/" +
    "01-baseline@196.json");
  const base = JSON.parse(fs.readFileSync(file, "utf8")) as Dict;
  const fig: Dict = { ...base,
    transcript: { ...base.transcript as Dict, turn_s: NOW - 3600 },
    agents: corpusAgents("01-mixed@220", "") };
  const opts: BandOpts = { rate: null, phase, agents,
    live: { turn: "running", agent: "always", session: "always" },
    places: { turn: "above", agent: "above", session: "above" } };
  const rows = treeOf(ST, fig, bandRows(ST, fig, opts), opts, []);
  const keys = fixedKeys(ST, 200, []);
  return rows.map((r) => stripAnsi(join(draw(ST, r, keys, 200, [])))
    .trimEnd());
}

test("between turns live \"always\" keeps the running agents under 🧵 " +
  "and draws no ✅ N done, which the running turn draws", () => {
  const running = bandTree("running", "always");
  assert.ok(running.some((l) => /✅ 4 done/u.test(l)));
  const done = bandTree("done", "always");
  assert.match(done[1], /^╰⊟ 🧵⚫ main/u);
  assert.ok(done.some((l) => /🔍🟢 Marigold/u.test(l)));
  assert.ok(!done.some((l) => l.includes("done")));
  assert.ok(!done.some((l) => l.includes("Daisy")));
});

test("between turns live \"running\" draws no agents", () => {
  assert.ok(bandTree("running", "running").some((l) =>
    l.includes("Marigold")));
  const done = bandTree("done", "running");
  assert.equal(done.length, 2);
  assert.match(done[1], /^╰─ 🧵⚫ main/u);
});
