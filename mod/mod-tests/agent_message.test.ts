// The mod in the engine's test harness: the folded row of a message
// another agent sent, drawn as that agent's task and the message's first
// line.
//
//   bash mod/tools/plugin-test.sh
//
// As band.test.ts does, the tests stand for the engine: `$.agent.list()`
// is answered from a list each test sets, `$.env` and `$.clock` from
// memory, and Claude Code's own row as a Box, so a drawing that is the
// mod's own tells apart from one it left to the engine.  What the mod
// should draw is worked out with agent_message.ts alone, from the same
// agents and text.
import { expect, mock, test } from 'claude-code/testing'
import type { AgentInfo, On, RenderElement, RenderPropsOf } from 'claude-code'

import { settings } from '../src/formatting.ts'
import { messageRow, senderLabel } from '../src/agent_message.ts'
import { CONFIG } from '../hooks/config.ts'

const NOW = 1_790_000_000_000
const COLS = 60
const TEXT = 'The right edge is now a setting in both ports, from one ' +
  'flag.\nThe rest of the report.'

type World = { agents: AgentInfo[]; listed: number;
  clock: ReturnType<typeof mock.clock> }

/** The engine beneath the mod: its agents as `world.agents` holds them,
 * each list counted, and its own drawing of every row a Box. */
function world(on: On): World {
  const w: World = { agents: [], listed: 0,
    clock: mock.clock(on, { now: NOW }) }
  mock.env(on, { HOME: '/home/fixture' })
  on('agent.list', () => {
    w.listed++
    return { value: w.agents }
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

async function drawn($: any, props: RenderPropsOf['UserMessage']):
  Promise<Drawn> {
  const ui = await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
    component: 'UserMessage', props,
    viewport: { columns: COLS, rows: 40 } })
  return await ui.drawn() as Drawn
}

/** The row as agent_message.ts would draw it from the same agents. */
const expected = (w: World, props: RenderPropsOf['UserMessage']) =>
  messageRow(settings({}, CONFIG.markSpacing, CONFIG.subscriptDecimals),
    senderLabel(props.from!.name, w.agents), props.text, COLS)

for (const surface of ['terminal', 'desktop'] as const) {
  test(`one agent of the sender's type: its task and the first line, ` +
    `dim, cut to the width (${surface})`, async ($, on) => {
    const w = world(on)
    w.agents = [agent('a1', 'general-purpose',
      'Reclaim the right-edge columns'), agent('a2', 'Explore', 'Look')]
    const ui = await $.ui.mount({ plugin: 'usage-band', surface,
      component: 'UserMessage', props: FROM,
      viewport: { columns: COLS, rows: 40 } })
    const tree = await ui.drawn() as Drawn
    expect(tree.type).toBe('Text')
    expect(tree.props?.dimColor).toBe(true)
    const row = (tree.children ?? []).join('')
    expect(row).toBe(expected(w, FROM))
    expect(row.startsWith('› 🤖 Reclaim the right-edge columns: The right ' +
      'edge')).toBe(true)
    expect(row.endsWith('…')).toBe(true)
  })
}

test('two agents of the type: the sender named as Claude Code names it',
  async ($, on) => {
    const w = world(on)
    w.agents = [agent('a1', 'general-purpose', 'One'),
      agent('a2', 'general-purpose', 'Two')]
    const tree = await drawn($, FROM)
    expect((tree.children ?? []).join('')).toBe('› 🤖 general-purpose: The ' +
      'right edge is now a setting in bo…')
    expect((tree.children ?? []).join('')).toBe(expected(w, FROM))
  })

test('a named agent: its own task', async ($, on) => {
  const w = world(on)
  w.agents = [agent('a1', 'general-purpose', 'By type'),
    agent('a2', 'general-purpose', 'Review the diff', 'running', 'reviewer')]
  const props = { ...FROM, text: 'Looks fine.', from: { name: 'reviewer' } }
  const tree = await drawn($, props)
  expect((tree.children ?? []).join('')).toBe(
    '› 🤖 Review the diff: Looks fine.')
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
    expect((await drawn($, FROM)).children?.join('')).toMatch(/First task/)
    await w.clock.advance(CONFIG.agentListMs)
    expect((await drawn($, FROM)).children?.join('')).toMatch(/Second task/)
    expect(w.listed).toBe(2)
  })
