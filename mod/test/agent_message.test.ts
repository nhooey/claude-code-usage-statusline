// The row a message from another agent is drawn as: which agent's task
// names the sender, by its name or by the words of its last reply, the
// message's first line, and the row's styles and cut to the width.
import { test } from "node:test";
import assert from "node:assert/strict";
import { settings, visWidth } from "../src/formatting.ts";
import {
  candidates, firstLine, lastReply, messageSpans, saidBy, senderLabel,
} from "../src/agent_message.ts";
import type { AgentLike, MessageLike } from "../src/agent_message.ts";
import { text as spansText } from "../src/spans.ts";

const st = settings({}, true, false);

const agent = (type: string, description: string, status = "running",
  name?: string): AgentLike => ({ type, description, status, name });

test("the one agent of the sender's type names it by its task", () => {
  const agents = [agent("general-purpose", "Reclaim the right-edge columns"),
    agent("Explore", "Find the width helpers")];
  assert.equal(senderLabel("general-purpose", agents),
    "Reclaim the right-edge columns");
});

test("a live agent of the type is taken over ones that are done", () => {
  const agents = [agent("general-purpose", "Old task", "completed"),
    agent("general-purpose", "New task", "idle"),
    agent("general-purpose", "Failed task", "failed")];
  assert.equal(senderLabel("general-purpose", agents), "New task");
});

test("two of the type, or none, leave the sender's name", () => {
  assert.equal(senderLabel("general-purpose",
    [agent("general-purpose", "One"), agent("general-purpose", "Two")]),
  "general-purpose");
  // Two done and none live is still two.
  assert.equal(senderLabel("general-purpose",
    [agent("general-purpose", "One", "completed"),
      agent("general-purpose", "Two", "killed")]), "general-purpose");
  assert.equal(senderLabel("general-purpose", []), "general-purpose");
  assert.equal(senderLabel("general-purpose", [agent("Explore", "One")]),
    "general-purpose");
});

test("one done agent of the type, with none live, is the sender", () => {
  assert.equal(senderLabel("Explore",
    [agent("Explore", "Only one", "completed")]), "Only one");
});

test("an agent's own name is matched before any type", () => {
  const agents = [agent("general-purpose", "By type"),
    agent("general-purpose", "By name", "running", "reviewer"),
    agent("reviewer", "A type named so")];
  assert.equal(senderLabel("reviewer", agents), "By name");
  // Two of that name fall back to the type, and so to its one agent.
  const twice = [...agents,
    agent("Explore", "Also by name", "running", "reviewer")];
  assert.equal(senderLabel("reviewer", twice), "A type named so");
});

test("a blank task leaves the sender's name; a task's whitespace folds", () => {
  assert.equal(senderLabel("Explore", [agent("Explore", "  ")]), "Explore");
  assert.equal(senderLabel("Explore", [agent("Explore", " Find\n  it ")]),
    "Find it");
});

test("the first line is the first with words on it, folded", () => {
  assert.equal(firstLine("\n  \n  The right  edge\tis set.\nMore."),
    "The right edge is set.");
  assert.equal(firstLine("one\r\ntwo"), "one");
  assert.equal(firstLine(" \n "), "");
});

const said = (role: string, text: string,
  ...inputs: Record<string, unknown>[]): MessageLike =>
  ({ role, text, toolUses: inputs.map((input) => ({ input })) });

test("the candidates: every agent of the name or type, the live first", () => {
  const agents = [agent("general-purpose", "One"),
    agent("general-purpose", "Two"),
    agent("general-purpose", "Done", "completed"),
    agent("Explore", "Named", "running", "general-purpose"),
    agent("Explore", "Other")];
  assert.deepEqual(candidates("general-purpose", agents)
    .map((a) => a.description), ["One", "Two", "Named"]);
  // With none live, the done ones.
  assert.deepEqual(candidates("Plan", [agent("Plan", "A", "completed"),
    agent("Plan", "B", "killed")]).map((a) => a.description), ["A", "B"]);
  assert.deepEqual(candidates("Plan", agents), []);
});

test("the last reply: the last assistant message's text and its tool " +
  "calls' string arguments, folded", () => {
  assert.equal(lastReply([said("assistant", "Old."),
    said("assistant", " The edge\n is  set. ",
      { to: "main", message: "Sent\twith a tool.", count: 3 }),
    said("user", "A tool's result.")]),
  "The edge is set. main Sent with a tool.");
  assert.equal(lastReply([said("user", "Only asked.")]), "");
  assert.equal(lastReply([]), "");
  // A message with no tool calls listed at all.
  assert.equal(lastReply([{ role: "assistant", text: "Bare." }]), "Bare.");
});

test("the message's words pick its sender out of several", () => {
  const one = agent("general-purpose", "Reclaim the right edge");
  const two = agent("general-purpose", "Count the transcript");
  const head = firstLine("The right edge is now a setting.\nMore.");
  // One reply holds it: that agent.
  assert.equal(saidBy(head, [[one, "Done. The right edge is now a " +
    "setting. More."], [two, "Still counting."]]), one);
  // None does, or both do: no one.
  assert.equal(saidBy(head, [[one, "Other."], [two, "Still counting."]]),
    null);
  assert.equal(saidBy(head, [[one, "The right edge is now a setting."],
    [two, "Quoting: The right edge is now a setting."]]), null);
  // A blank message picks no one, though every reply holds "".
  assert.equal(saidBy("", [[one, "Anything."]]), null);
  assert.equal(saidBy(head, []), null);
});

test("the match folds whitespace on both sides alike", () => {
  const one = agent("general-purpose", "One");
  const two = agent("general-purpose", "Two");
  const head = firstLine("  The right\tedge   is set.  \n\nMore.");
  const reply = lastReply([said("assistant",
    "The right\n  edge is\r\n set.  \n\nMore.")]);
  assert.equal(saidBy(head, [[one, reply], [two, ""]]), one);
});

// The row's pieces less the blanks that pad it to the width.
const styles = (spans: ReturnType<typeof messageSpans>) =>
  spans.filter((s) => s.text.trim()).map((s) => [s.text, s.dim, s.bold]);

test("the row is a faint bar out to the width, on B_MSG", () => {
  for (const [label, text, cols] of [["Reclaim", "The edge.", 80],
    ["Reclaim the right-edge columns", "The right edge is now", 20],
    ["Label", "Text", 5]] as const) {
    const row = messageSpans(st, label, text, cols);
    for (const s of row) assert.equal(s.bg, "B_MSG");
    assert.equal(visWidth(spansText(row), st.widths), cols, `${cols}`);
  }
});

test("the row: `› 🤖📨 ` dim, the label bold, the first line dim", () => {
  const row = messageSpans(st, "Reclaim the right-edge columns",
    "The right edge is now a setting.\nDetails.", 200);
  assert.deepEqual(styles(row), [
    ["› 🤖📨 ", true, false],
    ["Reclaim the right-edge columns", false, true],
    [": The right edge is now a setting.", true, false],
  ]);
  for (const s of row) assert.equal(s.colour, null);
  assert.deepEqual(styles(messageSpans(st, "Explore", "", 80)),
    [["› 🤖📨 ", true, false], ["Explore", false, true]]);
});

test("📨 is two columns in every profile, as 🤖 is", () => {
  const envs = [{}, { TMUX: "1" },
    { TERMINAL_EMULATOR: "JetBrains-JediTerm" },
    { TERM_PROGRAM: "iTerm.app" }];
  assert.deepEqual(envs.map((env) => settings(env).profile),
    ["unknown", "tmux", "jediterm", "iterm"]);
  for (const env of envs) {
    const w = settings(env).widths;
    assert.equal(visWidth("📨", w), 2, JSON.stringify(env));
    assert.equal(visWidth("› 🤖📨 ", w), 7, JSON.stringify(env));
  }
});

test("a long row is cut to the width, by columns, with an ellipsis", () => {
  const text = "The right edge is now a setting in both ports, and more";
  for (const cols of [5, 8, 10, 30, 47, 60]) {
    const row = messageSpans(st, "Reclaim the right-edge columns", text,
      cols);
    const drawn = spansText(row);
    assert.ok(visWidth(drawn, st.widths) <= cols, `${cols}: ${drawn}`);
    assert.ok(drawn.endsWith("…"), `${cols}: ${drawn}`);
    assert.ok(drawn.startsWith("› "), `${cols}: ${drawn}`);
  }
  // Cut in the label, the `…` is bold with it and nothing follows.
  const inLabel = messageSpans(st, "Reclaim the right-edge columns", text,
    20);
  assert.deepEqual(styles(inLabel),
    [["› 🤖📨 ", true, false], ["Reclaim the …", false, true]]);
  // Cut in the message, the `…` is dim with it.
  const inText = messageSpans(st, "Task", text, 24);
  assert.deepEqual(styles(inText), [["› 🤖📨 ", true, false],
    ["Task", false, true], [": The right …", true, false]]);
  // 🤖 and 📨 take two columns each: a cut at five leaves `› 🤖` and the
  // `…`, and no half glyph.
  const five = spansText(messageSpans(st, "Label", text, 5));
  assert.equal(five, "› 🤖…");
});
