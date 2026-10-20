// The row a message from another agent is drawn as: which agent's task
// names the sender, the message's first line, and the cut to the width.
import { test } from "node:test";
import assert from "node:assert/strict";
import { settings, visWidth } from "../src/formatting.ts";
import { firstLine, messageRow, senderLabel } from "../src/agent_message.ts";
import type { AgentLike } from "../src/agent_message.ts";

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

test("the row: the label, a colon and the first line", () => {
  assert.equal(messageRow(st, "Reclaim the right-edge columns",
    "The right edge is now a setting.\nDetails.", 200),
  "› 🤖 Reclaim the right-edge columns: The right edge is now a setting.");
  assert.equal(messageRow(st, "Explore", "", 80), "› 🤖 Explore");
});

test("a long row is cut to the width, by columns, with an ellipsis", () => {
  const text = "The right edge is now a setting in both ports, and more";
  for (const cols of [10, 30, 47, 60]) {
    const row = messageRow(st, "Reclaim the right-edge columns", text, cols);
    assert.ok(visWidth(row, st.widths) <= cols, `${cols}: ${row}`);
    assert.ok(row.endsWith("…"), `${cols}: ${row}`);
    assert.ok(row.startsWith("› "), `${cols}: ${row}`);
  }
  // 🤖 takes two columns: a cut at five leaves `› ` and no half glyph.
  const five = messageRow(st, "Label", text, 5);
  assert.ok(visWidth(five, st.widths) <= 5, five);
});
