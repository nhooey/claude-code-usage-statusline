// The mod in the engine's test harness: each place it draws, from fixture
// transcripts, against the pure functions it draws with.
//
//   bash mod/tools/plugin-test.sh
//
// The harness runs the mod in its own runtime with nothing beneath it, so
// these tests stand for the engine: they answer `$.fs` from the fixture
// files (mod-tests/fixtures.gen.ts), `$.env`, `$.session`, `$.clock` and
// `$.store` from memory, and `$.process.run` as a directory with no git.
// Each test then works out what the mod should have drawn from the same
// bytes, with the src/ functions alone and no `$`: the records parsed
// straight off the fixture, the reading straight off the tracker store,
// and the document, rows and spans from those.  The drawn text and each
// span's colour must match.  That proves the edges (that `$.fs` was read
// as the bytes are), the filing (the start line's trip through `$.store`)
// and the drawing (spans to Text); the documents themselves are proven
// against the Python's by test/claude.test.ts.  The receipt, which the mod
// writes rather than draws, is checked as the `$.ui.log` lines it sends,
// against receiptLines over the same bytes.
import { expect, mock, test } from 'claude-code/testing'
import type { MockClock } from 'claude-code/testing'
import type { On, RenderElement, RenderPropsOf } from 'claude-code'

import { CALIB, FILES, NOW, TRACKER } from './fixtures.gen.ts'
import { fromBase64 } from '../hooks/edges.ts'
import { merge as mergeConfig, optionsOf } from '../src/config.ts'
import { startKey } from '../hooks/register.tsx'
import { LOG_NAME } from '../hooks/log.ts'
import { CONFIG } from '../hooks/config.ts'
import {
  _readAgentBytes, _recordsOf, agentLabelOf, agentRecordsOf, foldAgentBytes,
  newAgentFold, readPayload, transcriptOf, turnsOf,
} from '../src/claude_records.ts'
import {
  agentFoldText, FOLD_CHECK_BYTES as AGENT_CHECK_BYTES, foldDir, slotNames,
  tailDigest,
} from '../src/agent_fold.ts'
import type { AgentEta, AgentReading } from '../src/claude_records.ts'
import {
  foldLoad, foldMain, foldMeta, foldSave, foldWrites, newMainFold, partName,
} from '../src/main_fold.ts'
import type { FoldMeta, MainFold } from '../src/main_fold.ts'
import { statePath } from '../src/state.ts'
import {
  _windowCostsFiles, _windowCostsText, seedLimitsSnapshot,
} from '../src/claude_calib.ts'
import {
  plistLoads, prepareClaudeReading, statusSourceContext, trackerReading,
} from '../src/claude_sources.ts'
import { trackerV1 } from '../src/sources.ts'
import type { Store } from '../src/sources.ts'
import {
  baseLimits, costFigures, statusFigures, windowFor,
} from '../src/claude.ts'
import { NO_GIT } from '../src/claude_records.ts'
import { settings } from '../src/formatting.ts'
import { ROW_NAMES, bandLines, bandRows, workspaceOf } from '../src/band.ts'
import {
  receiptLines, startLine, withEngineDuration,
} from '../src/receipt.ts'
import type { Span } from '../src/spans.ts'
import * as spec from '../src/spec.ts'
import type { Dict } from '../src/py.ts'

const HOME = '/home/fixture'
const STATE = '/state'
const CWD = '/work'
const SESSION = 'fixture-session'
const MODEL = 'claude-opus-5[1m]'
const WINDOW = 1_000_000
const COLS = 150
// The world's user file (world, below): the look these tests draw, the
// tracker's store, five figures hidden, and 🎤, 🤖 and 🎮 drawn while a
// turn runs and stamped into the transcript.
const USER_FILE = HOME + '/.config/coding-agent-usage-line/config.jsonc'
const USER_SETTINGS = {
  'usage-source': 'claude-usage-tracker',
  'hide': ['*.plan.five_hour', '*.context.share', '*.tokens.cache',
    'account.workspace.project', 'account.workspace.branch'],
  'rows': {
    turn: { live: 'running', transcript: true },
    agent: { live: 'running', transcript: true },
    session: { live: 'running', transcript: true },
  },
}
// The options the mod draws with here: the user file over the defaults.
const OPTIONS = optionsOf(mergeConfig([{ name: 'user', path: USER_FILE,
  mtimeMs: 0, values: USER_SETTINGS }], []))
const HIDE = OPTIONS.hide
// When the band draws each row, and the rows the receipt stamps.
const LIVE = { turn: OPTIONS.rows.turn.live, agent: OPTIONS.rows.agent.live,
  session: OPTIONS.rows.session.live }
const STAMPED = ROW_NAMES.filter((r) => OPTIONS.rows[r].transcript)
// How far in the band's rows' container stands, where live-place draws
// them: under the footer line, hint-inset columns.
const INSET = OPTIONS.livePlace === 'footer' ? OPTIONS.hintInset : 0
// The settings the band is drawn under: its right edge, right-edge,
// derived from live-place, and the receipt's, which stacks on the band.
const BAND_ST = settings({}, OPTIONS.markSpacing, OPTIONS.subscriptDecimals,
  OPTIONS.rightEdge)
const encoder = new TextEncoder()

/** The band where live-place draws it, mounted: above the prompt,
 * or under the footer line, whose mount the band's own sets the width
 * of first, as Claude Code draws the two.  Under the footer, the drawing
 * leaves out Claude Code's own line, which comes first, and the 💳
 * account's row under it. */
async function mountBand($: any, surface: 'terminal' | 'desktop',
  props: RenderPropsOf['AbovePrompt']) {
  const above = await $.ui.mount({ plugin: 'usage-band', surface,
    component: 'AbovePrompt', props })
  if (OPTIONS.livePlace === 'above') return above
  const hint = await $.ui.mount({ plugin: 'usage-band', surface,
    component: 'PromptHint', props: { isDraft: false,
      isWorking: props.isWorking, hint: '-- INSERT --' } })
  return { ...hint, drawn: async () => {
    const tree = await hint.drawn() as Drawn
    // And the 💳 account's row, under it, where it has one.
    const skip = OPTIONS.accountPlace === 'row' ? 2 : 1
    return tree.type === 'Box'
      ? { ...tree, children: (tree.children ?? []).slice(skip) } : tree
  } }
}

const BAND: RenderPropsOf['AbovePrompt'] = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 10,
  bodyColumns: COLS - 5,
  scroll: { offset: 0, bodyRows: 10 },
  view: {},
}

type World = {
  files: Map<string, Uint8Array>
  store: Map<string, unknown>
  // Each status document the mod filed in `$.state`, oldest first.
  docs: Dict[]
  // Whether `$.session.usage` is refused.
  usage: { down: boolean }
  // Each line the mod sent the debug log.
  debug: string[]
  // Each line the mod wrote into the transcript, `$.ui.log`'s default.
  logged: string[]
  clock: MockClock
}

type Run = { argv: readonly string[]; init?: { stdin?: string } }
type Ran = { exitCode: number; stdout: string; stderr: string;
  isStdoutTruncated: boolean; isStderrTruncated: boolean }
const NO_GIT_HERE: Ran = { exitCode: 128, stdout: '',
  stderr: 'not a git repository', isStdoutTruncated: false,
  isStderrTruncated: false }

/** The engine beneath the mod, answered from memory; `run` answers
 * `$.process.run`, a directory with no git by default, `$.session.usage`
 * is refused while `usage.down`, which `usageDown` starts it at, and a
 * fresh calibration is planted unless `calib` is false. */
function world(on: On, run: (e: Run) => Ran = () => NO_GIT_HERE,
  usageDown = false, calib = true): World {
  const files = new Map<string, Uint8Array>()
  for (const [p, b64] of Object.entries(FILES)) files.set(p, fromBase64(b64))
  files.set('/tracker.plist', encoder.encode(TRACKER))
  files.set(USER_FILE, encoder.encode(JSON.stringify(USER_SETTINGS)))
  const clock = mock.clock(on, { now: NOW * 1000 })
  const store = new Map<string, unknown>()
  on('store.get', ($, e) => ({ value: store.get(e.key) }))
  on('store.set', ($, e) => {
    store.set(e.key, e.value)
    return { value: undefined }
  })
  on('store.delete', ($, e) => {
    store.delete(e.key)
    return { value: undefined }
  })
  on('store.keys', () => ({ value: [...store.keys()] }))
  // The kit keeps `$.state`; this only watches the documents go by.
  const docs: Dict[] = []
  on('state.set', ($, e: any, next) => {
    if (e.plugin === 'usage-band' && e.key === 'status') docs.push(e.value)
    return next(e)
  })
  mock.env(on, {
    HOME, CODING_AGENT_USAGE_LINE_STATE_DIR: STATE,
    CLAUDE_CONFIG_DIR: '/claude',
    CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST: '/tracker.plist',
  })
  // The calibration the environment plants, under whatever name the
  // snapshot's scope gives it, and fresh.
  const planted = (p: string) => calib &&
    /\/claude-calibration-[0-9a-f]{64}\.cache$/.test(p)
    ? encoder.encode(JSON.stringify(CALIB)) : undefined
  const fileAt = (p: string) => files.get(p) ?? planted(p)
  const isDir = (p: string) => [...files.keys()].some((f) =>
    f.startsWith(p.endsWith('/') ? p : p + '/'))
  on('fs.stat', ($, e) => {
    const f = fileAt(e.path)
    if (f) {
      return { value: { kind: 'file' as const, size: f.length,
        mtimeMs: NOW * 1000, isLink: false } }
    }
    if (isDir(e.path)) {
      return { value: { kind: 'dir' as const, size: 0, mtimeMs: NOW * 1000,
        isLink: false } }
    }
    return { deny: 'no such file: ' + e.path }
  })
  on('fs.read', ($, e) => {
    const f = fileAt(e.path)
    if (!f) return { deny: 'no such file: ' + e.path }
    if (e.as === 'bytes') {
      let s = ''
      for (const b of f) s += String.fromCharCode(b)
      return { value: { base64: btoa(s) } }
    }
    return { value: new TextDecoder().decode(f) }
  })
  on('fs.write', ($, e) => {
    files.set(e.path, encoder.encode(e.text))
    return { value: undefined }
  })
  on('fs.list', ($, e) => {
    const dir = e.path.endsWith('/') ? e.path : e.path + '/'
    const names = new Map<string, 'file' | 'dir'>()
    for (const f of files.keys()) {
      if (!f.startsWith(dir)) continue
      const rest = f.slice(dir.length)
      const cut = rest.indexOf('/')
      names.set(cut < 0 ? rest : rest.slice(0, cut), cut < 0 ? 'file' : 'dir')
    }
    if (!names.size) return { deny: 'no such directory: ' + e.path }
    return { value: [...names].map(([name, kind]) => ({ name, kind,
      size: kind === 'file' ? files.get(dir + name)!.length : 0,
      mtimeMs: NOW * 1000, isLink: false })) }
  })
  on('process.run', ($, e) => ({ value: run(e) }))
  on('session.cwd', () => ({ value: CWD }))
  on('session.root', () => ({ value: CWD }))
  on('session.model', () => ({ value: MODEL }))
  on('session.id', () => ({ value: SESSION }))
  const usage = { down: usageDown }
  on('session.usage', () => usage.down
    ? { deny: 'usage unavailable' } as any
    : { value: { startedAt: NOW * 1000,
      context: { tokens: 1000, window: WINDOW }, rateLimits: [] } })
  // The engine's own drawings, and the events beneath the mod.
  on('ui.render', () => h('Box', null) as RenderElement)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('classic.SessionStart', () => ({}))
  // The lines `$.ui.log` sends: the debug log's, `{ to: 'debug' }`, and
  // the transcript's.
  const debug: string[] = []
  const logged: string[] = []
  on('ui.log', ($, e) => {
    ;(e.to === 'debug' ? debug : logged).push(e.text)
    return { value: undefined }
  })
  return { files, store, docs, usage, debug, logged, clock }
}

// ════════════════════════════════════════════════════════════════════════════
// What the mod should draw, worked out without it.
// ════════════════════════════════════════════════════════════════════════════

function bytesOf(w: World, p: string): Uint8Array {
  return w.files.get(p)!
}

/** The agents beside a fixture transcript, read straight off its bytes. */
function readingsOf(w: World, transcript: string):
  [string, AgentReading][] {
  const dir = transcript.slice(0, -'.jsonl'.length) + '/'
  return [...w.files.keys()].filter((p) => p.startsWith(dir) &&
    /\/agent-[^/]*\.jsonl$/.test(p)).sort()
    .map((p) => [p, _readAgentBytes(bytesOf(w, p))])
}

function labelIn(w: World) {
  return (p: string): [string, string] => agentLabelOf(p,
    w.files.get(p.slice(0, -'.jsonl'.length) + '.meta.json') ?? null)
}

/** The tracker's reading as the mod's collector should come to it. */
async function preparedOf(now: number) {
  const store: Store = { load: () => ({}), save: () => {},
    findCompatible: () => ({}) }
  const spec = 'claude-usage-tracker'
  return prepareClaudeReading(spec, 'default', 'day',
    statusSourceContext(spec, SESSION, MODEL, now, {}), now, {}, store,
    async () => trackerV1(trackerReading(plistLoads(encoder.encode(TRACKER)))))
}

/** The status document from the fixture's bytes and the world's session. */
async function statusOf(w: World, transcript: string, rate: number | null) {
  const records = _recordsOf(bytesOf(w, transcript))
  const readings = readingsOf(w, transcript)
  const etas: AgentEta[] = []
  const tr = transcriptOf(records, agentRecordsOf(readings, null, etas), etas,
    NOW)
  const turns = turnsOf(records, (s) => agentRecordsOf(readings, s, null),
    null, new Map(), labelIn(w))
  const prepared = await preparedOf(NOW)
  const snap = seedLimitsSnapshot(baseLimits(prepared), prepared.reading)
  const payload = readPayload(JSON.stringify({ session_id: SESSION,
    transcript_path: transcript, cwd: CWD,
    workspace: { current_dir: CWD, project_dir: CWD },
    model: { id: MODEL, display_name: MODEL },
    context_window: { context_window_size: WINDOW } }))
  return statusFigures({ payload, transcript: tr, turns,
    git: { ...NO_GIT, in_git: false }, prepared, snap, calib: CALIB, now: NOW,
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone, rate })
}

const text = (spans: readonly Span[]) => spans.map((s) => s.text).join('')

type Drawn = { type: string; props?: Record<string, unknown>;
  children?: (Drawn | string)[] }

/** Each row the mod drew, as its text and its spans' colours: the Texts
 * directly in the drawing's column, each of whose children is one span. */
async function drawnRows(ui: { drawn: () => Promise<unknown> }) {
  const tree = await ui.drawn() as Drawn
  if (tree.type !== 'Box') return []
  // A pressable row (🎤) is a Button around its Text.
  return (tree.children ?? []).map((c) => typeof c !== 'string' &&
    c.type === 'Button' ? (c.children ?? [])[0] : c).filter((c): c is Drawn =>
    typeof c !== 'string' && c?.type === 'Text').map((row) => {
    const spans = (row.children ?? []) as Drawn[]
    return { text: spans.map((c) => (c.children ?? []).join('')).join(''),
      colours: spans.map((c) => c.props?.color ?? null) }
  })
}

/** Where a prompt's turn tag was drawn: `beside` it on its row, or under
 * it on a line of its own, and the tag's text with its leading blanks. */
async function tagDrawn(ui: { drawn: () => Promise<unknown> }) {
  const tree = await ui.drawn() as Drawn
  const spans = (row: Drawn) => ((row.children ?? []) as Drawn[])
    .map((c) => (c.children ?? []).join('')).join('')
  if (tree.props?.flexDirection === 'row') {
    const box = (tree.children ?? []).at(-1) as Drawn
    return { beside: true, text: spans((box.children ?? [])[0] as Drawn) }
  }
  const rows = await drawnRows(ui)
  return { beside: false, text: rows[rows.length - 1]?.text }
}

function expected(lines: readonly (readonly Span[])[]) {
  const named = spec as unknown as Record<string, string>
  return lines.map((l) => ({ text: text(l),
    colours: l.map((s) => s.colour ? named[s.colour] : null) }))
}

/** The status document the band draws: the last one filed. */
function lastDoc(w: World): Dict {
  expect(w.docs.length).toBeGreaterThan(0)
  return w.docs[w.docs.length - 1]
}

// ════════════════════════════════════════════════════════════════════════════
// The tests.
// ════════════════════════════════════════════════════════════════════════════

const STATUS = '/fixtures/transcripts/status/agents.jsonl'
const COST = '/fixtures/transcripts/cost/09-agents.jsonl'
const MAIN = '/fixtures/transcripts/status/main.jsonl'

async function start($: any, surface: 'terminal' | 'desktop',
  transcript: string) {
  await $.classic.SessionStart({ source: 'startup', session_id: SESSION,
    transcript_path: transcript })
  await $.session.start({ cwd: CWD, surface, isInteractive: true })
  await settle()
}

// The test's environment has timers, which the hooks' types leave out.
declare const setTimeout: (f: () => void, ms: number) => unknown

/** Lets the reads the session's and turns' hooks start, and do not wait
 * for, run to their end. */
async function settle() {
  for (let i = 0; i < 50; i++) await new Promise((r) => setTimeout(() => r(undefined), 0))
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`the band is bandLines over the status document (${surface})`,
    async ($, on) => {
      const w = world(on)
      await start($, surface, STATUS)
      const doc = lastDoc(w)
      // The edges read the fixture as its bytes are: the document is the
      // one made straight from them.
      const want = await statusOf(w, STATUS, doc.rate as number | null)
      expect(JSON.parse(JSON.stringify(doc)))
        .toEqual(JSON.parse(JSON.stringify(want)))
      const ui = await mountBand($, surface, BAND)
      // Between turns the band draws nothing: the receipt has the rows.
      const lines = bandLines(BAND_ST, doc, COLS, HIDE, { home: HOME,
        rate: null, phase: 'done', live: LIVE, inset: INSET })
      expect(lines).toEqual([])
      expect(await drawnRows(ui)).toEqual([])
    })
}

test('a turn running draws the running phase', async ($, on) => {
  const w = world(on)
  await start($, 'terminal', STATUS)
  const doc = lastDoc(w)
  const ui = await mountBand($, 'terminal', { ...BAND, isWorking: true })
  const lines = bandLines(BAND_ST, doc, COLS, HIDE, { home: HOME,
    rate: null, phase: 'running', live: LIVE, inset: INSET })
  expect(await drawnRows(ui)).toEqual(expected(lines))
  // No blank top row, where Claude Code's `[-]` would stand alone.
  expect(((await ui.drawn()) as Drawn).props?.marginTop).toBeUndefined()
})

test('a survey above the prompt leaves the band to the engine',
  async ($, on) => {
    world(on)
    await start($, 'terminal', STATUS)
    const ui = await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
      component: 'AbovePrompt', props: { ...BAND, hasSurvey: true } })
    expect(await ui.find({ type: 'Text' })).toBeUndefined()
  })

/** The closing line as the mod draws it: one row high, a space and no
 * more, with no `✻ <word> for` and no tag. */
async function blankClosing($: any, word: string, durationMs: number) {
  const ui = await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
    component: 'TurnDuration', props: { word, durationMs },
    viewport: { columns: COLS, rows: 40 } })
  const tree = await ui.drawn() as Drawn
  expect(tree.type).toBe('Box')
  expect(tree.props?.height).toBe(1)
  const rows = (tree.children ?? []) as Drawn[]
  expect(rows.length).toBe(1)
  expect(rows[0].type).toBe('Text')
  expect(rows[0].children).toEqual([' '])
}

test('a turn ends on a blank closing line', async ($, on) => {
  world(on)
  await start($, 'terminal', COST)
  await $.turn.complete({ answer: '', durationMs: 65_000,
    isAborted: false, turnId: 't1', reason: 'answer' })
  await settle()
  await blankClosing($, 'Worked', 65_000)
})

test('pressing 🎤 under the footer scrolls to the prompt the turn opened ' +
  'with, and logs the call and its answer', async ($, on) => {
    const w = world(on)
    await start($, 'terminal', STATUS)
    // Two prompts drawn; the turn opened with the second.
    for (const [text, requestId] of [['Earlier.', 'prompt-0'],
      ['Go on.', 'prompt-1']]) {
      await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
        component: 'UserMessage', requestId, props: { text,
          isExpanded: false, origin: { kind: 'composer' } } })
    }
    await $.turn.start({ text: 'Go on.', turnId: 't3' })
    await settle()
    const hint = await $.ui.mount({ plugin: 'usage-band',
      surface: 'terminal', component: 'PromptHint', props: { isDraft: false,
        isWorking: true, hint: '-- INSERT --' } })
    const buttons = await hint.findAll({ type: 'Button' })
    // 🎤 alone presses: not 🤖, 🎮 or 💳.
    expect(buttons.length).toBe(1)
    const tree = await hint.drawn() as Drawn
    const pressed = (tree.children ?? []).find((c) =>
      typeof c !== 'string' && c.type === 'Button') as Drawn
    // Plain: no `[ ]` chrome, no hotkey; the row's own Text inside.
    expect(pressed.props?.plain).toBe(true)
    expect(pressed.props?.hotkey).toBeUndefined()
    const row = (pressed.children ?? [])[0] as Drawn
    expect(((row.children ?? [])[0] as Drawn).children?.join(''))
      .toMatch(/^🎤/)
    await hint.press({ key: String(pressed.props?.key ?? buttons[0].key) })
    // The kit resolves `$.ui.scroll` itself, to a site, and has none for
    // a transcript row: no hook of the test's can answer it (an
    // `on('ui.scroll')` is never reached), so the call it was handed is
    // read off the log, its answer the kit's refusal.
    expect(logOf(w)).toContain('press 🎤: $.ui.scroll({"to":{"requestId":' +
      '"prompt-1"},"block":"start"}) threw: no implementation for ui.scroll')
  })

test('pressing 🎤 with no prompt drawn says so and scrolls nowhere',
  async ($, on) => {
    const w = world(on)
    await start($, 'terminal', STATUS)
    const hint = await $.ui.mount({ plugin: 'usage-band',
      surface: 'terminal', component: 'PromptHint', props: { isDraft: false,
        isWorking: true, hint: '-- INSERT --' } })
    const [button] = await hint.findAll({ type: 'Button' })
    await hint.press({ key: String(button.key) })
    expect(logOf(w)).toContain('press 🎤: no prompt drawn to scroll to')
    expect(logOf(w)).not.toContain('$.ui.scroll')
  })

test('a prompt from the composer gets its turn tag under it, at no indent',
  async ($, on) => {
    const w = world(on)
    await start($, 'terminal', STATUS)
    // The prompt's record reaches the transcript as the turn opens.
    const prompt = JSON.stringify({ message: { content: 'Go on.' },
      promptId: 'p-next', promptSource: 'typed',
      timestamp: '2026-08-16T08:20:00Z', type: 'user',
      userType: 'external' }) + '\n'
    const before = w.files.get(STATUS)!
    const grown = new Uint8Array(before.length + prompt.length)
    grown.set(before)
    grown.set(encoder.encode(prompt), before.length)
    w.files.set(STATUS, grown)
    await $.turn.start({ text: 'Go on.', turnId: 't3' })
    await settle()
    const doc = lastDoc(w)
    expect((doc.transcript as Dict).prompt_id).toBe('p-next')
    const tag = startLine(doc)
    expect(tag.length).toBeGreaterThan(0)
    const props = { text: 'Go on.', isExpanded: false }
    const typed = await $.ui.mount({ plugin: 'usage-band',
      surface: 'terminal', component: 'UserMessage',
      props: { ...props, origin: { kind: 'composer' } } })
    // A short prompt has it on a line of its own too, so its 🔻🔖 stacks
    // with the receipt's 🔺🔖, both at no indent.
    expect(await tagDrawn(typed)).toEqual({ beside: false,
      text: text(tag) })
    const other = await $.ui.mount({ plugin: 'usage-band',
      surface: 'terminal', component: 'UserMessage',
      props: { ...props, origin: { kind: 'unclassified' } } as any })
    expect(await drawnRows(other)).toEqual([])
  })


test('a transcript over 4 MiB is read in pieces through the shell',
  async ($, on) => {
    // The shell's `tail -c +N | head -c L | base64`, over the world's
    // files: what readRange asks for a file `$.fs.read` will not take.
    const ranged: string[] = []
    const w: World = world(on, (e) => {
      const [cmd, , script, , from, file, want] = e.argv
      if (cmd !== '/bin/sh' || !script.includes('base64')) return NO_GIT_HERE
      ranged.push(from)
      const f = w.files.get(file)!
      const piece = f.subarray(Number(from) - 1,
        Number(from) - 1 + Number(want))
      let s = ''
      for (const b of piece) s += String.fromCharCode(b)
      return { ...NO_GIT_HERE, exitCode: 0, stdout: btoa(s) + '\n',
        stderr: '' }
    })
    // main.jsonl's records again and again past the limit: the requests
    // repeat, so the reading is the one copy's, read through every piece.
    const one = w.files.get(MAIN)!
    const copies = Math.ceil((4.5 * 1024 * 1024) / one.length)
    const big = new Uint8Array(one.length * copies)
    for (let i = 0; i < copies; i++) big.set(one, i * one.length)
    w.files.set(MAIN, big)
    await start($, 'terminal', MAIN)
    expect(ranged.length).toBeGreaterThan(1)
    const doc = lastDoc(w)
    const want = await statusOf(w, MAIN, doc.rate as number | null)
    expect(JSON.parse(JSON.stringify(doc)))
      .toEqual(JSON.parse(JSON.stringify(want)))
  })

// With no calibration yet, a document starts the scan behind it, which
// writes the window-cost cache the Python shares, in window_costs_text's
// bytes, through the shell: a temporary file renamed over it, never
// `$.fs.write`, which a reader can see torn.
test('a scan writes the shared window-cost cache through a rename',
  async ($, on) => {
    const costs = statePath(STATE, 'window-costs')
    const viaShell: string[] = []
    const w: World = world(on, (e) => {
      const [cmd, , script, , path] = e.argv
      if (cmd !== '/bin/sh' || !script.includes('mv -f')) return NO_GIT_HERE
      viaShell.push(path)
      w.files.set(path, encoder.encode(e.init?.stdin ?? ''))
      return { ...NO_GIT_HERE, exitCode: 0, stderr: '' }
    }, false, false)
    const path = '/claude/projects/-work/scanned.jsonl'
    const bytes = w.files.get(MAIN)!
    w.files.set(path, bytes)
    await start($, 'terminal', MAIN)
    for (let i = 0; i < 20 && !w.files.has(costs); i++) await settle()
    expect(viaShell).toEqual([costs])
    const text = new TextDecoder().decode(w.files.get(costs)!)
    const files = _windowCostsFiles(text)!
    expect(_windowCostsText(files)).toBe(text)
    expect(files[path].off).toBe(bytes.lastIndexOf(10) + 1)
    expect(files[path].recs.length).toBeGreaterThan(0)
  })

// ════════════════════════════════════════════════════════════════════════════
// The folds saved, and a reload reading on from them.
// ════════════════════════════════════════════════════════════════════════════

/** A transcript of main.jsonl's bytes at a path no other test reads, so no
 * fold is kept for it yet; and the line end halfway through. */
function savedWorld(on: On, path: string) {
  const w = world(on)
  const bytes = w.files.get(MAIN)!
  w.files.set(path, bytes)
  const half = bytes.indexOf(10, bytes.length >> 1) + 1
  return { w, bytes, half, dir: statePath(STATE, 'main-fold', path) }
}

/** `fold` saved for a transcript, with `meta`, into `dir`, as a first save
 * writes it. */
function plant(w: World, dir: string, fold: MainFold, meta: FoldMeta) {
  const save = foldSave(fold, meta)!
  for (const [i, t] of save.parts) {
    w.files.set(dir + '/' + partName(i), encoder.encode(t))
  }
  w.files.set(dir + '/' + save.slot, encoder.encode(save.head))
}

/** The status document over `bytes` in place of `path`'s own. */
async function statusOver(w: World, path: string, bytes: Uint8Array,
  rate: number | null) {
  const was = w.files.get(path)!
  w.files.set(path, bytes)
  try {
    return JSON.parse(JSON.stringify(await statusOf(w, path, rate)))
  } finally {
    w.files.set(path, was)
  }
}

// The saved fold planted empty, at the halfway line: a reload that reads
// on from it folds only the lines after it, which the document shows.
test('a reload reads on from the saved fold, not the whole transcript',
  async ($, on) => {
    const path = '/claude/projects/-work/saved-fold.jsonl'
    const { w, bytes, half, dir } = savedWorld(on, path)
    plant(w, dir, newMainFold(), foldMeta(bytes, half))
    await start($, 'terminal', path)
    const doc = JSON.parse(JSON.stringify(lastDoc(w)))
    const rate = doc.rate as number | null
    expect(doc).toEqual(await statusOver(w, path, bytes.subarray(half), rate))
    expect(doc).not.toEqual(await statusOver(w, path, bytes, rate))
  })

// One whose transcript's bytes are not the ones it was folded from is
// passed over, the transcript folded from the start, and saved afresh.
test('a saved fold of other bytes is not read, and is saved over',
  async ($, on) => {
    const path = '/claude/projects/-work/saved-other.jsonl'
    const { w, bytes, half, dir } = savedWorld(on, path)
    const other = bytes.slice()
    other[0] = 0x20
    plant(w, dir, newMainFold(), foldMeta(other, half))
    await start($, 'terminal', path)
    const doc = JSON.parse(JSON.stringify(lastDoc(w)))
    expect(doc).toEqual(await statusOver(w, path, bytes,
      doc.rate as number | null))
    const whole = newMainFold()
    for (const r of _recordsOf(bytes)) foldMain(whole, r)
    const back = foldLoad((n) => {
      const f = w.files.get(dir + '/' + n)
      return f ? new TextDecoder().decode(f) : null
    })
    expect(back?.meta).toEqual(foldMeta(bytes, bytes.lastIndexOf(10) + 1))
    expect(JSON.stringify(foldSave(back!.fold, back!.meta)))
      .toBe(JSON.stringify(foldSave(whole, back!.meta)))
  })

// The worker, scripts/agent_lines.py's fold mode, runs where the saved fold
// is a megabyte or more behind.  Here it saves the fold of the whole
// transcript, though half was planted, so the document says whose fold the
// mod read on from: the worker's, read back through `$.fs`, with no records
// passed.  test/main_fold.test.ts checks that the worker writes what the
// mod writes.
test('a reload reads on from the state the worker saved', async ($, on) => {
  const path = '/claude/projects/-work/worker-fold.jsonl'
  const ran: string[] = []
  const w: World = world(on, (e) => {
    const [, , script, mode, file, end, dir] = e.argv
    if (!script?.endsWith('/scripts/agent_lines.py')) return NO_GIT_HERE
    ran.push(mode)
    if (mode !== 'fold') return { ...NO_GIT_HERE, exitCode: 1 }
    const bytes = w.files.get(file)!.subarray(0, Number(end))
    const to = bytes.lastIndexOf(10) + 1
    const f = newMainFold()
    for (const r of _recordsOf(bytes.subarray(0, to))) foldMain(f, r)
    for (const [n, t] of foldWrites(f, foldMeta(bytes, to), null)!.writes) {
      w.files.set(dir + '/' + n, encoder.encode(t))
    }
    return { ...NO_GIT_HERE, exitCode: 0, stdout: to + '\n', stderr: '' }
  })
  const one = w.files.get(MAIN)!
  // Blank lines past the records, which no fold reads, to pass the megabyte.
  const bytes = new Uint8Array(one.length + 1.2 * 1024 * 1024).fill(10)
  bytes.set(one)
  w.files.set(path, bytes)
  const half = one.indexOf(10, one.length >> 1) + 1
  const dir = statePath(STATE, 'main-fold', path)
  plant(w, dir, newMainFold(), foldMeta(bytes, half))
  await start($, 'terminal', path)
  expect(ran).toEqual(['fold'])
  const doc = JSON.parse(JSON.stringify(lastDoc(w)))
  const rate = doc.rate as number | null
  expect(doc).toEqual(await statusOver(w, path, bytes, rate))
  expect(doc).not.toEqual(await statusOver(w, path, bytes.subarray(half),
    rate))
})

// A copy of mod/ on its own (a GitHub install, a dev mod) has no package
// beside the worker, which exits 1: the mod then folds the transcript
// itself, a piece at a time, so no more than a piece of it is held at
// once, and saves the fold, as the worker would have.  The copies of
// main.jsonl's records past two pieces' length put piece ends mid-record.
test('with no package for the worker, the mod folds the bytes in pieces',
  { timeoutMs: 60_000 }, async ($, on) => {
    const path = '/claude/projects/-work/no-worker.jsonl'
    const ran: string[] = []
    let widest = 0
    // Where each shell read starts: read whole, every one is a multiple of
    // its 2 MiB; read in pieces, each piece after the first starts at a
    // line's end, off that grid.
    const froms: number[] = []
    const w: World = world(on, (e) => {
      const [cmd, , script, mode, from, file, want] = e.argv
      if (script?.endsWith('/scripts/agent_lines.py')) {
        ran.push(mode)
        return { ...NO_GIT_HERE, exitCode: 1, stderr:
          'no coding_agent_usage_line package beside mod/' }
      }
      if (cmd !== '/bin/sh' || !script.includes('base64')) return NO_GIT_HERE
      widest = Math.max(widest, Number(want))
      // Not the check digests' reads, of 4 KiB.
      if (Number(want) > 4096) froms.push(Number(from) - 1)
      const f = w.files.get(file)!
      const piece = f.subarray(Number(from) - 1,
        Number(from) - 1 + Number(want))
      const s: string[] = []
      for (let i = 0; i < piece.length; i += 8192) {
        s.push(String.fromCharCode(...piece.subarray(i, i + 8192)))
      }
      return { ...NO_GIT_HERE, exitCode: 0, stdout: btoa(s.join('')) + '\n',
        stderr: '' }
    })
    const one = w.files.get(MAIN)!
    const copies = Math.ceil((17 * 1024 * 1024) / one.length)
    const bytes = new Uint8Array(one.length * copies)
    for (let i = 0; i < copies; i++) bytes.set(one, i * one.length)
    w.files.set(path, bytes)
    await start($, 'terminal', path)
    expect(ran).toEqual(['fold'])
    expect(widest).toBeLessThanOrEqual(2 * 1024 * 1024)
    const starts = froms.filter((at) => at % (2 * 1024 * 1024) !== 0 &&
      bytes[at - 1] === 10)
    expect(starts.length).toBeGreaterThanOrEqual(2)
    const doc = JSON.parse(JSON.stringify(lastDoc(w)))
    expect(doc).toEqual(await statusOver(w, path, bytes,
      doc.rate as number | null))
    const whole = newMainFold()
    for (const r of _recordsOf(bytes)) foldMain(whole, r)
    const dir = statePath(STATE, 'main-fold', path)
    const back = foldLoad((n) => {
      const f = w.files.get(dir + '/' + n)
      return f ? new TextDecoder().decode(f) : null
    })
    expect(back?.meta).toEqual(foldMeta(bytes, bytes.length))
    expect(JSON.stringify(foldSave(back!.fold, back!.meta)))
      .toBe(JSON.stringify(foldSave(whole, back!.meta)))
  })

// The saved cuts the mod once kept are removed on its first read: `rm`
// is handed only the names a cut was saved under, and `rmdir` each
// directory, so one that holds anything else stays.
test('the old saved cuts are removed, by their names alone', async ($, on) => {
  const ran: (readonly string[])[] = []
  const w = world(on, (e) => {
    if (e.argv[0] === '/bin/rm' || e.argv[0] === '/bin/rmdir') {
      ran.push(e.argv)
      return { ...NO_GIT_HERE, exitCode: 0, stderr: '' }
    }
    return NO_GIT_HERE
  })
  const cuts = STATE + '/claude-main-cuts-mod'
  const a = cuts + '/' + '0123456789abcdef'.repeat(2)
  const b = cuts + '/' + 'fedcba9876543210'.repeat(2)
  for (const p of [a + '/head.json', a + '/part-0.jsonl', a + '/part-12.jsonl',
    b + '/head.json', b + '/notes.txt', cuts + '/keep/head.json',
    cuts + '/stray.json']) {
    w.files.set(p, encoder.encode('{}'))
  }
  await start($, 'terminal', MAIN)
  expect(ran).toEqual([
    ['/bin/rm', '-f', '--', a + '/head.json', a + '/part-0.jsonl',
      a + '/part-12.jsonl', b + '/head.json'],
    ['/bin/rmdir', '--', a, b, cuts],
  ])
})

// ════════════════════════════════════════════════════════════════════════════
// The agents' folds saved, and a reload reading on from them.
// ════════════════════════════════════════════════════════════════════════════

/** The status fixture and its agent at paths no other test reads, so no
 * fold is kept for them yet: the transcript, the agent's path and bytes,
 * the line end halfway through those, and the agent's two slots. */
function agentWorld(on: On, name: string) {
  const w = world(on)
  const path = `/claude/projects/-work/${name}.jsonl`
  const agent = `/claude/projects/-work/${name}/subagents/agent-fork1.jsonl`
  w.files.set(path, w.files.get(STATUS)!)
  const bytes = w.files.get(
    '/fixtures/transcripts/status/agents/subagents/agent-fork1.jsonl')!
  w.files.set(agent, bytes)
  const half = bytes.indexOf(10, bytes.length >> 1) + 1
  const dir = foldDir(STATE, path)
  const slots = slotNames(agent).map((n) => dir + '/' + n)
  return { w, path, agent, bytes, half, slots }
}

/** The check digest of `bytes` at `pos`. */
function tailAt(bytes: Uint8Array, pos: number) {
  return tailDigest(bytes.subarray(Math.max(0, pos - AGENT_CHECK_BYTES), pos))
}

/** An empty fold at `pos`, read on over `bytes` from there. */
function readOn(bytes: Uint8Array, pos: number) {
  const f = newAgentFold()
  f.pos = pos
  foldAgentBytes(f, bytes.subarray(pos))
  return f
}

// An agent's fold planted empty at its halfway line, as a first save
// writes it, to the second slot: a reload reads on from it, so the fold
// the mod saves, to the first slot, holds only the second half.
test('a reload reads an agent on from its saved fold, and saves it to ' +
  'the other slot', async ($, on) => {
  const { w, path, bytes, half, slots } = agentWorld(on, 'agent-saved')
  const empty = newAgentFold()
  empty.pos = half
  w.files.set(slots[1], encoder.encode(
    agentFoldText(empty, 1, tailAt(bytes, half))))
  await start($, 'terminal', path)
  const end = bytes.lastIndexOf(10) + 1
  expect(new TextDecoder().decode(w.files.get(slots[0])!)).toBe(
    agentFoldText(readOn(bytes, half), 2, tailAt(bytes, end)))
})

// The newer slot torn, as $.fs.write can leave it to a reader, and the
// older one sound: the older is read on from, and saved over.
test('a torn agent fold falls back to the other slot', async ($, on) => {
  const { w, path, bytes, half, slots } = agentWorld(on, 'agent-torn')
  const sound = readOn(bytes.subarray(0, half), 0)
  w.files.set(slots[1], encoder.encode(
    agentFoldText(sound, 3, tailAt(bytes, half))))
  const torn = agentFoldText(sound, 4, tailAt(bytes, half))
  w.files.set(slots[0], encoder.encode(torn.slice(0, torn.length >> 1)))
  await start($, 'terminal', path)
  const end = bytes.lastIndexOf(10) + 1
  expect(new TextDecoder().decode(w.files.get(slots[0])!)).toBe(
    agentFoldText(readOn(bytes, 0), 4, tailAt(bytes, end)))
})

// A fold saved against other bytes is passed over, and the file folded
// from its start, saved after the highest seq either slot holds.
test('an agent fold of other bytes is not read', async ($, on) => {
  const { w, path, bytes, half, slots } = agentWorld(on, 'agent-other')
  w.files.set(slots[0], encoder.encode(
    agentFoldText(readOn(bytes.subarray(0, half), 0), 6, 'f'.repeat(64))))
  await start($, 'terminal', path)
  const end = bytes.lastIndexOf(10) + 1
  expect(new TextDecoder().decode(w.files.get(slots[1])!)).toBe(
    agentFoldText(readOn(bytes, 0), 7, tailAt(bytes, end)))
  expect(w.files.get(slots[0])!.length).toBeGreaterThan(0)
})

test('the old agent folds are removed, by their names alone',
  async ($, on) => {
    const ran: (readonly string[])[] = []
    const w = world(on, (e) => {
      if (e.argv[0] === '/bin/rm' || e.argv[0] === '/bin/rmdir') {
        ran.push(e.argv)
        return { ...NO_GIT_HERE, exitCode: 0, stderr: '' }
      }
      return NO_GIT_HERE
    })
    const old = STATE + '/claude-agent-folds-mod'
    const a = old + '/' + '0123456789abcdef'.repeat(2)
    const f = '89abcdef01234567'.repeat(2) + '.json'
    for (const p of [a + '/' + f, a + '/notes.txt', old + '/stray.json']) {
      w.files.set(p, encoder.encode('{}'))
    }
    await start($, 'terminal', STATUS)
    expect(ran.filter((r) => r.some((x) => x.startsWith(old)))).toEqual([
      ['/bin/rm', '-f', '--', a + '/' + f],
      ['/bin/rmdir', '--', a, old],
    ])
  })

// ════════════════════════════════════════════════════════════════════════════
// A resumed session, and the events a live one sends in another order.
//
// In a live session Claude Code's security plugin passes the classic
// events by a user's mod, so these send none: the mod finds the transcript
// by the session's id under the projects directory, as it must there.
// ════════════════════════════════════════════════════════════════════════════

const RESUMED = `/claude/projects/-work/${SESSION}.jsonl`
const ASKED = 'Say done.'
const ASKED_MS = 5_000

/** The history a resume opens on: the status fixture, where the session's
 * id would put it. */
function resumed(w: World) {
  w.files.set(RESUMED, w.files.get(STATUS)!)
}

/** The transcript grown by `recs`, one line each, as the engine appends. */
function grow(w: World, ...recs: object[]) {
  const add = encoder.encode(recs.map((r) => JSON.stringify(r) + '\n')
    .join(''))
  const before = w.files.get(RESUMED)!
  const grown = new Uint8Array(before.length + add.length)
  grown.set(before)
  grown.set(add, before.length)
  w.files.set(RESUMED, grown)
}

/** A turn that calls no tool: the prompt's record as it opens, the
 * answer's as it ends. */
async function askAndAnswer($: any, w: World) {
  grow(w, { message: { content: ASKED }, promptId: 'p-resume',
    promptSource: 'typed', timestamp: '2026-08-16T02:20:00Z', type: 'user',
    userType: 'external' })
  await $.turn.start({ text: ASKED, turnId: 't-resume' })
  await settle()
  grow(w, ANSWER)
  await $.turn.complete(COMPLETE)
  await settle()
}

const ANSWER = { isSidechain: false, message: { content: [{ text: 'Done.',
  type: 'text' }], id: 'req-r1', usage: { cache_creation_input_tokens: 500,
  cache_read_input_tokens: 41000, input_tokens: 3, output_tokens: 40 } },
requestId: 'req-r1', timestamp: '2026-08-16T02:20:05Z', type: 'assistant' }
const COMPLETE = { answer: 'Done.', durationMs: ASKED_MS, isAborted: false,
  turnId: 't-resume', reason: 'answer' } as const

/** A turn as Claude Code runs one live: the prompt's record as it opens,
 * and turn.complete before the answer's record, which Claude Code writes
 * only after its Stop hooks; `land` says whether it is written at all. */
async function askLive($: any, w: World, land: boolean) {
  grow(w, { message: { content: ASKED }, promptId: 'p-resume',
    promptSource: 'typed', timestamp: '2026-08-16T02:20:00Z', type: 'user',
    userType: 'external' })
  await $.turn.start({ text: ASKED, turnId: 't-resume' })
  await settle()
  await $.turn.complete(COMPLETE)
  await settle()
  await w.clock.settle()
  expect(stamped(w)).toBe(false)
  if (land) grow(w, ANSWER)
}

/** Whether the mod has filed a receipt for a closing line to draw. */
function stamped(w: World): boolean {
  return [...w.store.keys()].some((k) => k.startsWith('receipt-at:'))
}

/** Moves the clock on in the mod's polling steps until it has stamped, or
 * `ms` have passed. */
async function until(w: World, ms: number) {
  for (let t = 0; t < ms && !stamped(w); t += 500) {
    await w.clock.advance(500)
  }
}

/** The receipt's lines as the closing line should draw them at `now`,
 * worked out from the transcript's bytes: receiptLines over the cost
 * document, at the band's width with the band's indent. */
async function receiptOf(w: World, now: number): Promise<Span[][]> {
  const doc = lastDoc(w)
  const records = _recordsOf(bytesOf(w, RESUMED))
  const readings = readingsOf(w, RESUMED)
  const turns = turnsOf(records, (s) => agentRecordsOf(readings, s, null),
    null, new Map(), labelIn(w))
  const prepared = await preparedOf(now)
  const snap = seedLimitsSnapshot(baseLimits(prepared), prepared.reading)
  const fig = withEngineDuration(costFigures(turns, windowFor(turns,
    Number(doc.context_window)), CALIB, snap, prepared, now,
  Intl.DateTimeFormat().resolvedOptions().timeZone), ASKED_MS)
  const main = bandRows(BAND_ST, doc,
    { home: HOME, rate: null, phase: 'done' }).main
  return receiptLines(BAND_ST, fig, COLS, HIDE,
    workspaceOf(doc, HOME), true, main, STAMPED, INSET)
}

/** The closing line of a turn that took `durationMs`, as drawn. */
async function closing($: any, durationMs: number) {
  return drawnRows(await $.ui.mount({ plugin: 'usage-band',
    surface: 'terminal', component: 'TurnDuration',
    props: { word: 'Worked', durationMs },
    viewport: { columns: COLS, rows: 40 } }))
}

test('a turn whose records land after turn.complete gets its receipt drawn as its closing line',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    // The band draws first, and the receipt is laid out at its width.
    await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
      component: 'AbovePrompt', props: BAND })
    await askLive($, w, true)
    await until(w, 5_000)
    const want = await receiptOf(w, w.clock.now() / 1000)
    // 🎤, 🤖 and 🎮 at no indent, a blank row, then the 🔺🔖 tag line,
    // drawn as the start line is.
    expect(want.length).toBe(5)
    expect(text(want[0]).trimStart().startsWith(spec.E_TURN)).toBe(true)
    expect(text(want[1]).trimStart().startsWith(spec.E_BOT)).toBe(true)
    expect(text(want[2]).trimStart().startsWith(spec.E_SESSION)).toBe(true)
    expect(text(want[3])).toBe(' ')
    expect(text(want[4])).toContain('p-resume'.slice(0, 8))
    expect(text(want[4]).startsWith(spec.E_TURN_PAST)).toBe(true)
    expect(text(want[4])).toContain(spec.E_DATE)
    expect(text(want[4])).not.toContain(spec.E_ACCT)
    // The closing line draws it, on the band's columns, and nothing goes
    // to the transcript as a notice.
    expect(await closing($, ASKED_MS)).toEqual(expected(want))
    // A blank row above it, apart from the answer, and one under it.
    const drawn = await (await $.ui.mount({ plugin: 'usage-band',
      surface: 'terminal', component: 'TurnDuration',
      props: { word: 'Worked', durationMs: ASKED_MS },
      viewport: { columns: COLS, rows: 40 } })).drawn() as Drawn
    expect(drawn.props?.marginTop).toBe(1)
    expect(drawn.props?.marginBottom).toBe(1)
    expect(w.logged).toEqual([])
    // turn.complete again over the same turn: the same receipt, once.
    await $.turn.complete(COMPLETE)
    await settle()
    await w.clock.advance(5_000)
    expect(await closing($, ASKED_MS)).toEqual(expected(want))
    expect(logOf(w)).not.toContain('no receipt')
  })

test('a turn a task notification follows still gets its receipt and tag',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
      component: 'AbovePrompt', props: BAND })
    await askLive($, w, true)
    // Delivered as the turn ends, after its answer, and written as a turn
    // of its own that never runs (seen live 2026-10-20).
    grow(w, { message: { content: '<task-notification>\n<task-id>a1' +
      '</task-id>\n<status>completed</status>\n</task-notification>' },
    origin: { kind: 'task-notification' }, promptId: 'p-notice',
    promptSource: 'system', timestamp: '2026-08-16T02:20:06Z',
    type: 'user', userType: 'external' })
    await until(w, 5_000)
    expect(stamped(w)).toBe(true)
    const want = await receiptOf(w, w.clock.now() / 1000)
    expect(text(want.at(-1)!)).toContain('p-resume'.slice(0, 8))
    expect(text(want.at(-1)!).startsWith(spec.E_TURN_PAST)).toBe(true)
    expect(await closing($, ASKED_MS)).toEqual(expected(want))
    // On past the band's hold, which the stamp's handler sleeps through.
    await w.clock.advance(5_000)
    expect(logOf(w)).not.toContain('no receipt')
  })

test('a task notification written before turn.complete does not take the receipt',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
      component: 'AbovePrompt', props: BAND })
    grow(w, { message: { content: ASKED }, promptId: 'p-resume',
      promptSource: 'typed', timestamp: '2026-08-16T02:20:00Z', type: 'user',
      userType: 'external' })
    await $.turn.start({ text: ASKED, turnId: 't-resume' })
    await settle()
    // The answer, and the notification 17 ms after the turn's end, both
    // in the transcript by the time the refresh after turn.complete reads
    // it (seen live 2026-10-20), so the newest prompt is the
    // notification's, a turn that never runs.
    grow(w, ANSWER, { message: { content: '<task-notification>\n' +
      '<task-id>a1</task-id>\n<status>completed</status>\n' +
      '</task-notification>' }, origin: { kind: 'task-notification' },
    promptId: 'p-notice', promptSource: 'system',
    timestamp: '2026-08-16T02:20:06Z', type: 'user', userType: 'external' })
    await $.turn.complete(COMPLETE)
    await settle()
    await until(w, 5_000)
    expect(stamped(w)).toBe(true)
    const want = await receiptOf(w, w.clock.now() / 1000)
    expect(text(want.at(-1)!)).toContain('p-resume'.slice(0, 8))
    expect(await closing($, ASKED_MS)).toEqual(expected(want))
    await w.clock.advance(5_000)
    expect(logOf(w)).not.toContain('no receipt')
  })

test('a turn the context was compacted in gets its receipt and tag',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
      component: 'AbovePrompt', props: BAND })
    grow(w, { message: { content: ASKED }, promptId: 'p-resume',
      promptSource: 'typed', timestamp: '2026-08-16T02:20:00Z', type: 'user',
      userType: 'external' })
    await $.turn.start({ text: ASKED, turnId: 't-resume' })
    await settle()
    // The context compacted as the turn opened, its summary written under
    // the turn's prompt (seen live 2026-10-20): the fold gives the
    // compaction a turn of its own, and the answer lands in it.
    grow(w, { compactMetadata: { durationMs: 26, preTokens: 366000,
      trigger: 'auto' }, subtype: 'compact_boundary',
    timestamp: '2026-08-16T02:20:01Z', type: 'system' },
    { isCompactSummary: true, isVisibleInTranscriptOnly: true,
      message: { content: 'This session is being continued from a ' +
        'previous conversation.' }, promptId: 'p-resume',
      timestamp: '2026-08-16T02:19:00Z', type: 'user',
      userType: 'external' })
    await $.turn.complete(COMPLETE)
    await settle()
    await w.clock.settle()
    grow(w, ANSWER)
    await until(w, 5_000)
    expect(stamped(w)).toBe(true)
    const want = await receiptOf(w, w.clock.now() / 1000)
    // 🎤 is the turn, its prompt and tag, the compaction billed in it.
    expect(text(want[0])).toContain(ASKED)
    expect(text(want.at(-1)!)).toContain('p-resume'.slice(0, 8))
    expect(await closing($, ASKED_MS)).toEqual(expected(want))
    await w.clock.advance(5_000)
    expect(logOf(w)).not.toContain('no receipt')
  })

test('a turn whose records never land logs why and stamps nothing',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    await askLive($, w, false)
    await until(w, 31_000)
    expect(stamped(w)).toBe(false)
    await blankClosing($, 'Worked', ASKED_MS)
    expect(logOf(w)).toContain('no receipt: the turn was not billed ' +
      'within 30s')
  })

/** A prompt sent before it was finished, as the transcript held it live
 * (session 4b531313, 2026-10-20, prompt 8d8ad942): the prompt in turn slot
 * 320, its attachment, two requests and no reply; then, `replaced`, the
 * full prompt in the same slot under the same parent. */
function rewound(w: World, replaced: boolean) {
  const at = { promptIndex: 250, turnIndex: 320 }
  if (!replaced) {
    grow(w, { message: { content: 'Blocked:' }, parentUuid: 'u-before',
      promptId: 'p-cut', promptSource: 'typed',
      timestamp: '2026-08-16T02:20:00Z', turnPosition: at, type: 'user',
      userType: 'external', uuid: 'u-cut' },
    { attachment: { type: 'total_tokens_reminder' }, parentUuid: 'u-cut',
      timestamp: '2026-08-16T02:20:00Z', type: 'attachment',
      uuid: 'u-cut-att' },
    { querySource: 'repl_main_thread', timestamp: '2026-08-16T02:20:00Z',
      type: 'api-request' },
    { lastPrompt: 'Blocked:', leafUuid: 'u-cut-att', type: 'last-prompt' },
    { querySource: 'repl_main_thread', timestamp: '2026-08-16T02:20:01Z',
      type: 'api-request' })
    return
  }
  grow(w, { message: { content: 'Blocked:\n1. Y' }, parentUuid: 'u-before',
    promptId: 'p-full', promptSource: 'typed',
    timestamp: '2026-08-16T02:22:00Z', turnPosition: at, type: 'user',
    userType: 'external', uuid: 'u-full' })
}

test('a prompt rewound before any reply logs that it billed nothing, at once',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    rewound(w, false)
    await $.turn.start({ text: 'Blocked:', turnId: 't-cut' })
    await settle()
    // Interrupted: nothing counted, so no usage.
    await $.turn.complete({ answer: '', durationMs: 2_000, isAborted: true,
      turnId: 't-cut', reason: 'aborted' })
    await settle()
    await until(w, 2_000)
    expect(stamped(w)).toBe(false)
    expect(logOf(w)).toContain('no receipt: the turn billed nothing ' +
      '(interrupted): p-cut')
    await w.clock.advance(31_000)
    expect(logOf(w)).not.toContain('not billed within')
    expect(logOf(w).split('no receipt').length).toBe(2)
  })

test('a prompt replaced in its turn slot logs that it billed nothing',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    rewound(w, false)
    await $.turn.start({ text: 'Blocked:', turnId: 't-cut' })
    await settle()
    // An end that says nothing of the interrupt: the transcript tells,
    // once the full prompt takes the slot.
    await $.turn.complete({ answer: '', durationMs: 2_000, isAborted: false,
      turnId: 't-cut', reason: 'answer' })
    await settle()
    await until(w, 5_000)
    expect(logOf(w)).not.toContain('no receipt')
    rewound(w, true)
    await until(w, 2_000)
    expect(stamped(w)).toBe(false)
    expect(logOf(w)).toContain('no receipt: the turn billed nothing ' +
      '(replaced): p-cut')
    await w.clock.advance(31_000)
    expect(logOf(w)).not.toContain('not billed within')
  })

/** The mod's log file, as the world holds it. */
function logOf(w: World): string {
  const f = w.files.get(STATE + '/' + LOG_NAME)
  return f ? new TextDecoder().decode(f) : ''
}

/** All three places drawn for the turn askAndAnswer ran: the band over
 * the last document and the start line under the prompt, each against the
 * src/ functions over the same bytes, and the blank closing line. */
async function drewAll($: any, w: World) {
  const doc = lastDoc(w)
  expect((doc.transcript as Dict).prompt_id).toBe('p-resume')
  // The transcript as read straight off its bytes.  Not the whole
  // document: by now the usage reading comes from the cache the first
  // refresh wrote, which carries its scope fields, where a fresh reading
  // does not.
  const want = await statusOf(w, RESUMED, doc.rate as number | null)
  expect(JSON.parse(JSON.stringify(doc.transcript)))
    .toEqual(JSON.parse(JSON.stringify(want.transcript)))
  const st = BAND_ST

  const mount = () => mountBand($, 'terminal', BAND)
  // The band drawn as of now, its clocks moved on as the mod moves them.
  const shown = (phase: 'running' | 'done') => {
    const now = Math.max(Number((doc.clock as Dict).now),
      w.clock.now() / 1000)
    return bandLines(st, { ...doc, clock: { ...(doc.clock as Dict), now } },
      COLS, HIDE, { home: HOME, rate: null, phase, live: LIVE,
        inset: INSET })
  }
  // The turn has ended, but until its receipt is stamped, and a second
  // more, the band keeps its 🎤 and 🎮 rows.
  expect(await drawnRows(await mount())).toEqual(expected(shown('running')))
  await until(w, 5_000)
  expect(stamped(w)).toBe(true)
  await w.clock.advance(1_000)
  // Then nothing: the receipt has stamped 🤖 with 🎤 and 🎮.
  expect(shown('done')).toEqual([])
  expect(await drawnRows(await mount())).toEqual([])

  const tag = startLine(doc)
  expect(tag.length).toBeGreaterThan(0)
  expect(w.store.get(startKey(ASKED))).toBeDefined()
  const typed = await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
    component: 'UserMessage', props: { text: ASKED, isExpanded: false,
      origin: { kind: 'composer' } } })
  expect(await tagDrawn(typed)).toEqual({ beside: false, text: text(tag) })

  // The receipt the hold waited for: its three rows, a blank row and its
  // tag line on the closing line.
  expect((await closing($, ASKED_MS)).length).toBe(5)
}

test('a resumed session whose first turn calls no tool draws all three',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    await askAndAnswer($, w)
    await drewAll($, w)
    expect(logOf(w)).toContain('started by session.start in ' + CWD)
  })

// The project's local file the acceptance check writes
// (config-merge.md, "Acceptance"): 🎤, 🤖 and 🎮 kept under the footer
// line between turns, and stamped into the transcript too.
const LOCAL = CWD + '/.config/coding-agent-usage-line/config.local.jsonc'
const KEPT_AND_STAMPED = '{"rows": {' +
  '"turn": {"live": "always", "transcript": true}, ' +
  '"agent": {"live": "always", "transcript": true}, ' +
  '"session": {"live": "always", "transcript": true}}}'

test('a project file found on the tick keeps the rows and stamps them, ' +
  'with no reload', async ($, on) => {
  const w = world(on)
  resumed(w)
  await $.session.start({ cwd: CWD, surface: 'terminal',
    isInteractive: true })
  await settle()
  await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
    component: 'AbovePrompt', props: BAND })
  expect(logOf(w)).toContain(`config from ${CWD}: user ${USER_FILE}` +
    ' (usage-source, hide, rows)')
  // The file comes after the session's start; the tick's next look at the
  // files reads it.
  w.files.set(LOCAL, encoder.encode(KEPT_AND_STAMPED))
  await w.clock.advance(CONFIG.tickMs)
  await settle()
  expect(logOf(w)).toContain(`config from ${CWD}: project-local ${LOCAL}` +
    ` (rows); user ${USER_FILE} (usage-source, hide, rows)`)
  expect(logOf(w)).toContain('config options: ' +
    'usage-source "claude-usage-tracker" (user); right-edge 2 (derived); ' +
    'hide ' + JSON.stringify(HIDE) + ' (user); rows.turn.live "always" (project-local); ' +
    'rows.turn.transcript true (project-local); ' +
    'rows.agent.live "always" (project-local); ' +
    'rows.agent.transcript true (project-local); ' +
    'rows.session.live "always" (project-local); ' +
    'rows.session.transcript true (project-local)')
  await askLive($, w, true)
  await until(w, 5_000)
  expect(stamped(w)).toBe(true)
  await w.clock.advance(1_000)
  // The turn is done, and the band keeps all three rows.
  const doc = lastDoc(w)
  const now = Math.max(Number((doc.clock as Dict).now), w.clock.now() / 1000)
  const kept = bandLines(BAND_ST, { ...doc, clock: { ...(doc.clock as Dict),
    now } }, COLS, HIDE, { home: HOME, rate: null, phase: 'done',
    live: { turn: 'always', agent: 'always', session: 'always' },
    inset: INSET })
  expect(kept.length).toBe(3)
  expect(await drawnRows(await mountBand($, 'terminal', BAND)))
    .toEqual(expected(kept))
  // And the receipt stamps all three too: three rows, a blank row and the
  // tag line.
  expect((await closing($, ASKED_MS)).length).toBe(5)
  // A good file: no notice in the transcript.
  expect(w.logged.filter((l) => l.includes('config'))).toEqual([])
})

test('a bad value in a file is logged, noticed once, and its default kept',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    w.files.set(LOCAL, encoder.encode(
      '{"rows": {"turn": {"live": "allways"}}}'))
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    const warning = `${LOCAL}: "rows.turn.live" must be one of "never", ` +
      '"running", "always" (did you mean "always"?); skipped'
    expect(logOf(w)).toContain('config: ' + warning)
    expect(w.logged).toEqual(['usage-band: config ' + warning])
    // Another session's start, and a tick: the file is as it was, so no
    // second read and no second notice.
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await w.clock.advance(CONFIG.tickMs)
    await settle()
    expect(w.logged.length).toBe(1)
    expect(logOf(w).split('config: ' + warning).length - 1).toBe(1)
    // 🎤 as the layer under the file has it, "running": gone once the
    // turn ends.
    await askLive($, w, true)
    await until(w, 5_000)
    await w.clock.advance(1_000)
    expect(await drawnRows(await mountBand($, 'terminal', BAND)))
      .toEqual([])
  })

test('a turn before any session.start still draws all three',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await askAndAnswer($, w)
    await drewAll($, w)
    // The first event started the load's tick, and said so.
    expect(logOf(w)).toContain('started by turn.start')
  })

test('a refresh that throws is logged, and the next one draws',
  async ($, on) => {
    const w = world(on, undefined, true)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await settle()
    // The start's reads failed: nothing filed, and the log says why, in
    // its file and in the debug log.
    expect(w.docs.length).toBe(0)
    const why = /refresh: no status document: .*usage unavailable/
    expect(logOf(w)).toMatch(why)
    expect(w.debug.some((l) => why.test(l))).toBe(true)
    w.usage.down = false
    await askAndAnswer($, w)
    await drewAll($, w)
  })
