// The one-line row Claude Code draws for a message another agent sent,
// drawn with what the message is about.
//
// Folded, Claude Code draws such a message as one dim row naming its
// sender, `› Message from @general-purpose (ctrl+o to expand)`: the
// sender's name, which for a subagent with no name of its own is only its
// type, so two agents of one type read alike and none says what it was
// asked.  The mod draws the row instead as the agent's task, as its Agent
// call described it, and the message's first line, `› 🤖 Reclaim the
// right-edge columns: The right edge is now a setting in both ports…`, cut
// to the terminal's width (asked 2026-10-20).
//
// The sender is known only by name (`e.props.from.name`), so its agent is
// found in `$.agent.list()` by that: an agent whose own name it is (a
// named subagent), else one whose type it is, the live ones before the
// rest.  Where that finds more than one, or none, the row names the
// sender as Claude Code did: a guess between two agents' tasks would put
// one agent's words under the other's.
//
// Pure: the caller lists the agents and measures the row.
import { fitCols } from "./formatting.ts";
import type { Settings } from "./formatting.ts";

/** What the row reads of an agent: `$.agent.list()`'s AgentInfo, in part. */
export type AgentLike = {
  readonly type: string;
  readonly description: string;
  readonly status: string;
  readonly name?: string;
};

// The statuses of an agent whose loop has not ended (AgentStatus): one of
// these is the sender of a message just arrived before any agent that is
// done, whose entry the engine keeps for a while after.
const LIVE = new Set(["pending", "running", "waiting", "idle"]);

/** The one agent of `agents` that `pick` matches, the live ones first:
 * the only live match, else the only match of all; null where there are
 * none, or more than one at the first of those that has any. */
function onlyOne(agents: readonly AgentLike[],
  pick: (a: AgentLike) => boolean): AgentLike | null {
  const all = agents.filter(pick);
  const live = all.filter((a) => LIVE.has(a.status));
  const among = live.length ? live : all;
  return among.length === 1 ? among[0] : null;
}

/** What the row calls the sender named `from`: the task of the agent it
 * is, by its own name and then by its type, or `from` itself where no one
 * agent is (see above), or that agent's task is blank. */
export function senderLabel(from: string,
  agents: readonly AgentLike[]): string {
  const agent = onlyOne(agents, (a) => a.name === from) ??
    onlyOne(agents, (a) => a.type === from);
  const task = agent?.description.replace(/\s+/g, " ").trim();
  return task || from;
}

/** The message's first line with words on it, its whitespace collapsed;
 * "" for a message of none. */
export function firstLine(text: string): string {
  for (const line of text.split(/\r?\n/)) {
    const words = line.replace(/\s+/g, " ").trim();
    if (words) return words;
  }
  return "";
}

/** The row: `› 🤖 `, the sender's label, and after a colon the message's
 * first line, cut to `cols` columns with an ellipsis, counted as the
 * terminal counts them (formatting.visWidth). */
export function messageRow(st: Settings, label: string, text: string,
  cols: number): string {
  const head = firstLine(text);
  const row = "› 🤖 " + label + (head ? ": " + head : "");
  return fitCols(st, row, Math.max(1, cols));
}
