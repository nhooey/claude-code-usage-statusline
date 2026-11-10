// The sender of a message another agent sent: Claude Code's folded
// `› Message from @general-purpose` names the agent's type, and the row
// names the agent by its task, found by which agent's last reply holds the
// message's words.  The agent list and the senders found are kept between
// draws, and the senders in the store across a reload.
import type { EngineInterface } from 'claude-code'

import {
  candidates, firstLine, lastReply, saidBy, soleSender,
} from '../src/agent_message.ts'
import type { AgentLike, MessageLike } from '../src/agent_message.ts'
import { sha256Hex } from '../src/sha256.ts'
import { CONFIG } from './config.ts'
import { folderAgents, folderReplies } from './transcripts.ts'
import { transcriptPath } from './edges.ts'
import { log } from './log.ts'
import { placesFor } from './engine.ts'

type $ = EngineInterface

// The session's agents as `$.agent.list()` last gave them, and when, in
// ms; 0 for never, or for a list an agent's start or end has made stale.
// A module variable, not `$.state`: a render hook may not write state, and
// the row that reads it is drawn afresh with each draw of the transcript.
let agentList: readonly AgentLike[] = []
let agentListAt = 0
let agentListing: Promise<readonly AgentLike[]> | null = null

/** The session's agents, listed again only once CONFIG.agentListMs has
 * passed since the last list, or an agent started or ended since: a
 * message row is drawn on every draw, and one list stands for them all.
 * Draws that come while a list is out wait on that one.  A list that
 * fails is logged and counts as none, so the row names the sender as
 * Claude Code did. */
export async function agentsNow($: $): Promise<readonly AgentLike[]> {
  const now = await $.clock.now()
  if (agentListAt && now - agentListAt < CONFIG.agentListMs) return agentList
  agentListing ??= (async () => {
    try {
      agentList = await $.agent.list()
    } catch (err) {
      await log($, 'no agent list', err)
      agentList = []
    }
    agentListAt = await $.clock.now()
    return agentList
  })().finally(() => {
    agentListing = null
  })
  return agentListing
}

/** An agent has started or ended: the next message row lists them again,
 * and a message no reply held is looked for again, in case its sender is
 * the agent just come or its reply the one just written. */
export function agentsChanged(): void {
  agentListAt = 0
  for (const [text, agent] of senders) {
    if (!agent) senders.delete(text)
  }
}

// The sender of each message its words have been looked for by, keyed by
// its text, null where no one reply held it; the oldest dropped past
// CONFIG.agentSenderMemo.  A module variable, as the agent list is.  A
// message never changes, so a sender once found is its sender for good.
const senders = new Map<string, AgentLike | null>()
// The lookups out, so draws that come while one is out wait on it.
const sending = new Map<string, Promise<AgentLike | null>>()

// The senders found, as the store keeps them for a reload, which starts
// `senders` over: a finished agent may be gone from the list and its
// reply from the folder's tail by then.  Under SENDERS_KEY, each keyed by
// keptKey, the oldest dropped past CONFIG.agentSenderMemo.  A sender not
// found is not kept, so a later load may find it.  `$.store`, not
// `$.state`: a render hook may not write state.
const SENDERS_KEY = 'agent-senders'
let kept: Promise<Record<string, AgentLike>> | null = null

/** The store's key for the sender of `text` in session `session`. */
const keptKey = (session: string, text: string) =>
  sha256Hex(session + '\n' + text).slice(0, 32)

/** The senders the store keeps, read once per load; none where it will
 * not read. */
function keptSenders($: $): Promise<Record<string, AgentLike>> {
  kept ??= $.store.get(SENDERS_KEY).then(
    (got) => got && typeof got === 'object'
      ? { ...got as Record<string, AgentLike> } : {},
    async (err) => {
      await log($, 'no kept senders', err)
      return {}
    })
  return kept
}

/** Keep `agent` as the sender under `key`, for a reload to find; only what
 * the row reads of it. */
async function keepSender($: $, key: string, agent: AgentLike) {
  const all = await keptSenders($)
  delete all[key]
  all[key] = { id: agent.id, type: agent.type,
    description: agent.description, status: agent.status,
    ...agent.name !== undefined ? { name: agent.name } : {} }
  const keys = Object.keys(all)
  for (const old of keys.slice(0, Math.max(0,
    keys.length - CONFIG.agentSenderMemo))) {
    delete all[old]
  }
  await $.store.set(SENDERS_KEY, all)
    .catch((err) => log($, 'sender not kept', err))
}

/** The one agent of the session's `subagents/` folder named or typed
 * `from` whose last reply there holds `head` (transcripts.ts folderAgents,
 * folderReplies); null where none or several do.  For a sender gone from
 * the agent list: an agent finished a while, or one the list did not
 * settle. */
async function folderSender($: $, from: string, head: string):
  Promise<AgentLike | null> {
  if (!head) return null
  const path = await transcriptPath($, await placesFor($))
  if (!path) return null
  const among = (await folderAgents($, path))
    .filter((a) => a.name === from || a.type === from)
  return saidBy(head, await folderReplies($, path, among))
}

/** The sender of `text` as `from` by the words of its message, kept under
 * `key` where found: the one of `agents` whose conversation's last reply
 * holds its first line, else folderSender's. */
async function lookFor($: $, from: string, text: string,
  agents: readonly AgentLike[], key: string): Promise<AgentLike | null> {
  const among = candidates(from, agents).filter((a) => a.id)
  const replies = await Promise.all(among.map(async (a) => {
    try {
      const got = await $.session.messages({ agentId: a.id! })
      return [a, Array.isArray(got)
        ? lastReply(got as readonly MessageLike[]) : ''] as const
    } catch (err) {
      await log($, 'no messages for ' + a.id, err)
      return [a, ''] as const
    }
  }))
  const head = firstLine(text)
  const found = saidBy(head, replies) ??
    await folderSender($, from, head).catch(async (err) => {
      await log($, 'no folder sender', err)
      return null
    })
  if (found) await keepSender($, key, found)
  return found
}

/** The agent that sent `text` as `from`: the one agent of that name or
 * type, with no read; else the one a load before this one found, as the
 * store keeps it; else the one of them whose last reply holds the
 * message's first line (agent_message.ts), each candidate's conversation
 * read once per message; else the one of the session's `subagents/`
 * folder whose reply there holds it (folderSender); null where none finds
 * one.  A read that fails is logged and counts as no reply. */
export async function senderOf($: $, from: string, text: string,
  agents: readonly AgentLike[]): Promise<AgentLike | null> {
  const sole = soleSender(from, agents)
  if (sole) return sole
  if (senders.has(text)) return senders.get(text)!
  let lookup = sending.get(text)
  if (!lookup) {
    lookup = (async () => {
      const key = keptKey(await $.session.id().catch(() => ''), text)
      const found = (await keptSenders($))[key] ??
        await lookFor($, from, text, agents, key)
      senders.set(text, found)
      while (senders.size > CONFIG.agentSenderMemo) {
        senders.delete(senders.keys().next().value!)
      }
      return found
    })().finally(() => {
      sending.delete(text)
    })
    sending.set(text, lookup)
  }
  return lookup
}
