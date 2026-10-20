// The one-line row Claude Code draws for a message another agent sent,
// drawn with what the message is about.
//
// Folded, Claude Code draws such a message as one dim row naming its
// sender, `› Message from @general-purpose (ctrl+o to expand)`: the
// sender's name, which for a subagent with no name of its own is only its
// type, so two agents of one type read alike and none says what it was
// asked.  The mod draws the row instead as the agent's task, as its Agent
// call described it, and the message's first line, `› 🤖📨 Reclaim the
// right-edge columns: The right edge is now a setting in both ports…`, cut
// to the terminal's width (asked 2026-10-20).  The task is bold at full
// strength and the rest dim, so the task is what the eye finds (asked
// 2026-10-20).
//
// The sender is known only by name (`e.props.from.name`), so its agent is
// found in `$.agent.list()` by that: an agent whose own name it is (a
// named subagent), else one whose type it is, the live ones before the
// rest.  Where that finds more than one, the message's own words pick it:
// the one agent of them whose last reply holds the message's first line
// (asked 2026-10-20: ten `general-purpose` agents all read
// `general-purpose`).  Where none or several hold it, or there were none
// to begin with, the row names the sender as Claude Code did: a guess
// between two agents' tasks would put one agent's words under the other's.
//
// Pure: the caller lists the agents, reads their replies and measures the
// row.
import { E_BOT, E_INBOX } from "./spec.ts";
import { cut, span, width } from "./spans.ts";
import type { Span } from "./spans.ts";
import type { Settings } from "./formatting.ts";

/** What the row reads of an agent: `$.agent.list()`'s AgentInfo, in part. */
export type AgentLike = {
  readonly id?: string;
  readonly type: string;
  readonly description: string;
  readonly status: string;
  readonly name?: string;
};

/** What the row reads of a message of an agent's conversation:
 * `$.session.messages({ agentId })`'s SessionMessage, in part. */
export type MessageLike = {
  readonly role: string;
  readonly text: string;
  readonly toolUses?: readonly { readonly input?: unknown }[];
};

// The statuses of an agent whose loop has not ended (AgentStatus): one of
// these is the sender of a message just arrived before any agent that is
// done, whose entry the engine keeps for a while after.
const LIVE = new Set(["pending", "running", "waiting", "idle"]);

/** The agents of `agents` that `pick` matches, the live ones where there
 * are any, else all of them. */
function liveFirst(agents: readonly AgentLike[],
  pick: (a: AgentLike) => boolean): AgentLike[] {
  const all = agents.filter(pick);
  const live = all.filter((a) => LIVE.has(a.status));
  return live.length ? live : all;
}

/** The one agent of `agents` that `pick` matches, the live ones first:
 * the only live match, else the only match of all; null where there are
 * none, or more than one at the first of those that has any. */
function onlyOne(agents: readonly AgentLike[],
  pick: (a: AgentLike) => boolean): AgentLike | null {
  const among = liveFirst(agents, pick);
  return among.length === 1 ? among[0] : null;
}

/** The one agent the sender named `from` is by its name alone: by its own
 * name and then by its type; null where no one agent is. */
export function soleSender(from: string,
  agents: readonly AgentLike[]): AgentLike | null {
  return onlyOne(agents, (a) => a.name === from) ??
    onlyOne(agents, (a) => a.type === from);
}

/** The agents the sender named `from` may be, where its name alone picks
 * none: every one whose own name or type it is, the live ones first. */
export function candidates(from: string,
  agents: readonly AgentLike[]): AgentLike[] {
  return liveFirst(agents, (a) => a.name === from || a.type === from);
}

/** What the row calls the sender: `agent`'s task, its whitespace folded,
 * or `from` itself where there is no agent or its task is blank. */
export function taskOf(agent: AgentLike | null, from: string): string {
  return agent?.description.replace(/\s+/g, " ").trim() || from;
}

/** What the row calls the sender named `from`, by its name alone. */
export function senderLabel(from: string,
  agents: readonly AgentLike[]): string {
  return taskOf(soleSender(from, agents), from);
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

/** An agent's last reply, its whitespace collapsed as firstLine collapses
 * it: the text of its last assistant message and the string arguments of
 * that message's tool calls, since a message sent with a tool (SendMessage)
 * is written there and not in the text.  "" for an agent with none. */
export function lastReply(messages: readonly MessageLike[]): string {
  let i = messages.length - 1;
  while (i >= 0 && messages[i].role !== "assistant") i--;
  if (i < 0) return "";
  const last = messages[i];
  const parts = [last.text];
  for (const use of last.toolUses ?? []) {
    const input = use.input;
    if (input && typeof input === "object") {
      for (const v of Object.values(input)) {
        if (typeof v === "string") parts.push(v);
      }
    }
  }
  return parts.join(" ").replace(/\s+/g, " ").trim();
}

/** The one agent whose reply holds `head`, a message's first line as
 * firstLine gives it; null where none does, or more than one, or `head`
 * is blank.  `replies` pairs each candidate with its lastReply. */
export function saidBy(head: string,
  replies: readonly (readonly [AgentLike, string])[]): AgentLike | null {
  if (!head) return null;
  const hits = replies.filter(([, reply]) => reply.includes(head));
  return hits.length === 1 ? hits[0][0] : null;
}

/** The row as spans: `› 🤖📨 ` dim, the sender's label bold at full
 * strength, and after a dim colon the message's first line, dim; cut to
 * `cols` columns with an ellipsis, counted as the terminal counts them
 * (formatting.visWidth), the `…` in the style of the piece it cuts.  All
 * of it on B_MSG, padded with blanks to `cols`, so the row is a faint bar
 * out to the right margin (asked 2026-10-20). */
export function messageSpans(st: Settings, label: string, text: string,
  cols: number): Span[] {
  const head = firstLine(text);
  const row = [span("› " + E_BOT + E_INBOX + " ", null, true, false, "B_MSG"),
    span(label, null, false, true, "B_MSG")];
  if (head) row.push(span(": " + head, null, true, false, "B_MSG"));
  const out = cut(row, Math.max(1, cols), st.widths);
  const pad = Math.max(1, cols) - width(out, st.widths);
  if (pad > 0) out.push(span(" ".repeat(pad), null, false, false, "B_MSG"));
  return out;
}
