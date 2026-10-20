// The mod in the engine's test harness: the folded row of a message
// another agent sent, drawn as that agent's task, bold, and the message's
// first line, dim; the agent found by its name, else by its last reply.
//
//   bash mod/tools/plugin-test.sh
//
// As band.test.ts does, the tests stand for the engine: `$.agent.list()`
// is answered from a list each test sets, `$.session.messages({ agentId
// })` from the replies it sets, each read counted, `$.env` and `$.clock` from
// memory, and Claude Code's own row as a Box, so a drawing that is the
// mod's own tells apart from one it left to the engine.  What the mod
// should draw is worked out with agent_message.ts alone, from the same
// agents and text.
import { expect, mock, test } from 'claude-code/testing'
import type { AgentInfo, On, RenderElement, RenderPropsOf } from 'claude-code'

import { settings } from '../src/formatting.ts'
import { messageSpans, senderLabel } from '../src/agent_message.ts'
import { BAND_EDGE, CONFIG } from '../hooks/config.ts'

const NOW = 1_790_000_000_000
const COLS = 60
const TEXT = 'The right edge is now a setting in both ports, from one ' +
  'flag.\nThe rest of the report.'

type World = { agents: AgentInfo[]; listed: number;
  replies: Record<string, string>; read: string[];
  clock: ReturnType<typeof mock.clock> }

/** The engine beneath the mod: its agents as `world.agents` holds them,
 * each list counted; each agent's conversation one user message and the
 * reply `world.replies` holds for it, or a deny where it holds none, each
 * read noted; and its own drawing of every row a Box. */
function world(on: On): World {
  const w: World = { agents: [], listed: 0, replies: {}, read: [],
    clock: mock.clock(on, { now: NOW }) }
  mock.env(on, { HOME: '/home/fixture' })
  on('agent.list', () => {
    w.listed++
    return { value: w.agents }
  })
  on('session.messages', ($, e) => {
    const id = e.agentId ?? 'main'
    w.read.push(id)
    const reply = w.replies[id]
    return { value: reply === undefined ? { deny: 'no ' + id } : [
      { role: 'user', text: 'Go.', toolUses: [] },
      { role: 'assistant', text: reply, toolUses: [] }] }
  })
  on('ui.render', () => h('Box', null) as RenderElement)
  on('ui.log', () => ({ value: undefined }))
  return w
}

const agent = (id: string, type: string, description: string,
  status: AgentInfo['status'] = 'running', name?: string): AgentInfo =>
  ({ id, type, description, status, ...name ? { name } : {} })

const FROM: RenderPropsOf['UserMessage'] = {
  text: TEXT, isExpanded: false, origin: { kind: 'unclassified' },
  from: { name: 'general-purpose' },
}

type Drawn = { type: string; props?: Record<string, unknown>;
  children?: (Drawn | string)[] }

/** The row's pieces as drawn: each nested Text's text, and whether it is
 * dim and bold. */
const pieces = (tree: Drawn) => (tree.children ?? []).map((c) =>
  typeof c === 'string' ? [c, false, false]
    : [(c.children ?? []).join(''), c.props?.dimColor === true,
        c.props?.bold === true])

/** The row's text as drawn. */
const textOf = (tree: Drawn) => pieces(tree).map((p) => p[0]).join('')

async function drawn($: any, props: RenderPropsOf['UserMessage']):
  Promise<Drawn> {
  const ui = await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
    component: 'UserMessage', props,
    viewport: { columns: COLS, rows: 40 } })
  return await ui.drawn() as Drawn
}

/** The row's pieces as agent_message.ts would draw them, labelled
 * `label`, by default the one its sender's name alone finds. */
const expected = (w: World, props: RenderPropsOf['UserMessage'],
  label = senderLabel(props.from!.name, w.agents)) =>
  messageSpans(settings({}, CONFIG.markSpacing, CONFIG.subscriptDecimals),
    label, props.text, COLS - BAND_EDGE).map((s) => [s.text, s.dim, s.bold])

for (const surface of ['terminal', 'desktop'] as const) {
  test(`one agent of the sender's type: its task bold, the first line ` +
    `dim, cut to the width (${surface})`, async ($, on) => {
    const w = world(on)
    w.agents = [agent('a1', 'general-purpose',
      'Reclaim the right-edge columns'), agent('a2', 'Explore', 'Look')]
    const ui = await $.ui.mount({ plugin: 'usage-band', surface,
      component: 'UserMessage', props: FROM,
      viewport: { columns: COLS, rows: 40 } })
    const tree = await ui.drawn() as Drawn
    expect(tree.type).toBe('Text')
    expect(tree.props?.wrap).toBe('truncate-end')
    // Not dim as a whole: a dim around the row would dim the task too.
    expect(tree.props?.dimColor).toBe(undefined)
    expect(pieces(tree)).toEqual(expected(w, FROM))
    expect(pieces(tree).slice(0, 2)).toEqual([['› 🤖📨 ', true, false],
      ['Reclaim the right-edge columns', false, true]])
    const rest = pieces(tree)[2]
    expect(rest[1]).toBe(true)
    expect(rest[2]).toBe(false)
    expect(String(rest[0]).startsWith(': The right edge')).toBe(true)
    expect(String(rest[0]).endsWith('…')).toBe(true)
    // One agent of the type: no conversation read.
    expect(w.read).toEqual([])
  })
}

test('two agents of the type, neither reply the message\'s: the sender ' +
  'named as Claude Code names it', async ($, on) => {
    const w = world(on)
    w.agents = [agent('a1', 'general-purpose', 'One'),
      agent('a2', 'general-purpose', 'Two')]
    w.replies = { a1: 'Something else.' }
    const tree = await drawn($, FROM)
    expect(textOf(tree)).toBe('› 🤖📨 general-purpose: The right edge is ' +
      'now a setting i…')
    expect(pieces(tree)).toEqual(expected(w, FROM))
    expect(w.read.sort()).toEqual(['a1', 'a2'])
  })

test('two agents of the type: the one whose last reply holds the ' +
  'message, read once per message', async ($, on) => {
    const w = world(on)
    w.agents = [agent('a1', 'general-purpose', 'Count the transcript'),
      agent('a2', 'general-purpose', 'Reclaim the right-edge columns'),
      agent('a3', 'Explore', 'Look')]
    w.replies = { a1: 'Still counting.',
      a2: 'Done.\n\nThe right edge is now a  setting in both ports, ' +
        'from one\nflag.\nThe rest of the report.' }
    const tree = await drawn($, FROM)
    expect(pieces(tree)).toEqual(
      expected(w, FROM, 'Reclaim the right-edge columns'))
    expect(pieces(tree)[1]).toEqual(
      ['Reclaim the right-edge columns', false, true])
    expect(w.read.sort()).toEqual(['a1', 'a2'])
    // A second draw of the message reads no conversation, though the
    // agents are listed again, and the reply has moved on.
    w.replies.a2 = 'Something later.'
    await w.clock.advance(CONFIG.agentListMs)
    expect(pieces(await drawn($, FROM))).toEqual(pieces(tree))
    expect(w.read.length).toBe(2)
    expect(w.listed).toBe(2)
  })

test('draws of one message while its replies are read share the reads',
  async ($, on) => {
    const w = world(on)
    w.agents = [agent('a1', 'general-purpose', 'One'),
      agent('a2', 'general-purpose', 'Two')]
    w.replies = { a1: 'The right edge is now a setting in both ports, ' +
      'from one flag.', a2: 'No.' }
    const trees = await Promise.all([drawn($, FROM), drawn($, FROM)])
    expect(textOf(trees[0])).toMatch(/^› 🤖📨 One: /)
    expect(textOf(trees[1])).toBe(textOf(trees[0]))
    expect(w.read.length).toBe(2)
  })

test('a named agent: its own task', async ($, on) => {
  const w = world(on)
  w.agents = [agent('a1', 'general-purpose', 'By type'),
    agent('a2', 'general-purpose', 'Review the diff', 'running', 'reviewer')]
  const props = { ...FROM, text: 'Looks fine.', from: { name: 'reviewer' } }
  const tree = await drawn($, props)
  expect(pieces(tree)).toEqual([['› 🤖📨 ', true, false],
    ['Review the diff', false, true], [': Looks fine.', true, false]])
  expect(w.read).toEqual([])
})

test('unfolded, and on rows no agent sent, Claude Code draws its own',
  async ($, on) => {
    const w = world(on)
    w.agents = [agent('a1', 'general-purpose', 'Task')]
    expect((await drawn($, { ...FROM, isExpanded: true })).type).toBe('Box')
    const { from: _, ...prompt } = FROM
    expect((await drawn($, prompt)).type).toBe('Box')
    expect((await drawn($, { ...prompt, origin: { kind: 'composer' } }))
      .type).toBe('Box')
    // None of them asked for the agents.
    expect(w.listed).toBe(0)
  })

test('the agents are listed once per CONFIG.agentListMs, not per draw',
  async ($, on) => {
    const w = world(on)
    w.agents = [agent('a1', 'general-purpose', 'First task')]
    await drawn($, FROM)
    await drawn($, FROM)
    await drawn($, FROM)
    expect(w.listed).toBe(1)
    // A new agent's task waits for the next list.
    w.agents = [agent('a1', 'general-purpose', 'Second task')]
    expect(textOf(await drawn($, FROM))).toMatch(/First task/)
    await w.clock.advance(CONFIG.agentListMs)
    expect(textOf(await drawn($, FROM))).toMatch(/Second task/)
    expect(w.listed).toBe(2)
  })
