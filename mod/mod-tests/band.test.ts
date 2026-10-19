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
import { startKey } from '../hooks/register.tsx'
import { LOG_NAME } from '../hooks/log.ts'
import {
  _readAgentBytes, _recordsOf, agentLabelOf, agentRecordsOf, readPayload,
  transcriptOf, turnsOf,
} from '../src/claude_records.ts'
import type { AgentEta, AgentReading } from '../src/claude_records.ts'
import { seedLimitsSnapshot } from '../src/claude_calib.ts'
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
import { bandLines, workspaceOf } from '../src/band.ts'
import {
  receiptLines, startLine, withEngineDuration,
} from '../src/receipt.ts'
import type { Span } from '../src/spans.ts'
import * as spec from '../src/spec.ts'
import { pyRstrip } from '../src/py.ts'
import type { Dict } from '../src/py.ts'

const HOME = '/home/fixture'
const STATE = '/state'
const CWD = '/work'
const SESSION = 'fixture-session'
const MODEL = 'claude-opus-5[1m]'
const WINDOW = 1_000_000
const COLS = 150
const encoder = new TextEncoder()

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
  // Each line the mod sent the debug log.
  debug: string[]
  // Each line the mod wrote into the transcript, `$.ui.log`'s default.
  logged: string[]
  clock: MockClock
}

type Run = { argv: readonly string[] }
type Ran = { exitCode: number; stdout: string; stderr: string;
  isStdoutTruncated: boolean; isStderrTruncated: boolean }
const NO_GIT_HERE: Ran = { exitCode: 128, stdout: '',
  stderr: 'not a git repository', isStdoutTruncated: false,
  isStderrTruncated: false }

/** The engine beneath the mod, answered from memory; `run` answers
 * `$.process.run`, a directory with no git by default, and the first
 * `usageFails` reads of `$.session.usage` are refused. */
function world(on: On, run: (e: Run) => Ran = () => NO_GIT_HERE,
  usageFails = 0): World {
  const files = new Map<string, Uint8Array>()
  for (const [p, b64] of Object.entries(FILES)) files.set(p, fromBase64(b64))
  files.set('/tracker.plist', encoder.encode(TRACKER))
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
  // The calibration the environment plants, under whatever name the mod's
  // version keys it by, and fresh.
  const planted = (p: string) => /\/claude-calibration-ts-[0-9a-f]+\.cache$/
    .test(p) ? encoder.encode(JSON.stringify(CALIB)) : undefined
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
  on('session.usage', () => usageFails-- > 0
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
  return { files, store, docs, debug, logged, clock }
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
  return (tree.children ?? []).filter((c): c is Drawn =>
    typeof c !== 'string' && c.type === 'Text').map((row) => {
    const spans = (row.children ?? []) as Drawn[]
    return { text: spans.map((c) => (c.children ?? []).join('')).join(''),
      colours: spans.map((c) => c.props?.color ?? null) }
  })
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
      const ui = await $.ui.mount({ plugin: 'usage-band', surface,
        component: 'AbovePrompt', props: BAND })
      const lines = bandLines(settings({}), doc, COLS, [], { home: HOME,
        rate: null, phase: 'done', indent: spec.C_CHROME_CONT })
      expect(lines.length).toBeGreaterThan(0)
      expect(await drawnRows(ui)).toEqual(expected(lines))
      // No blank top row, where Claude Code's `[-]` would stand alone.
      expect(((await ui.drawn()) as Drawn).props?.marginTop).toBeUndefined()
    })
}

test('a turn running draws the running phase', async ($, on) => {
  const w = world(on)
  await start($, 'terminal', STATUS)
  const doc = lastDoc(w)
  const ui = await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
    component: 'AbovePrompt', props: { ...BAND, isWorking: true } })
  const lines = bandLines(settings({}), doc, COLS, [], { home: HOME,
    rate: null, phase: 'running', indent: spec.C_CHROME_CONT })
  expect(await drawnRows(ui)).toEqual(expected(lines))
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
  await blankClosing($, 'Worked', 65_000)
})

test('a prompt from the composer gets its turn tag under it',
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
    const doc = lastDoc(w)
    expect((doc.transcript as Dict).prompt_id).toBe('p-next')
    const tag = startLine(doc)
    expect(tag.length).toBeGreaterThan(0)
    const props = { text: 'Go on.', isExpanded: false }
    const typed = await $.ui.mount({ plugin: 'usage-band',
      surface: 'terminal', component: 'UserMessage',
      props: { ...props, origin: { kind: 'composer' } } })
    const drawn = await drawnRows(typed)
    expect(drawn[drawn.length - 1]?.text).toBe('  ' + text(tag))
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
  grow(w, ANSWER)
  await $.turn.complete(COMPLETE)
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
  await $.turn.complete(COMPLETE)
  await w.clock.settle()
  expect(w.logged).toEqual([])
  if (land) grow(w, ANSWER)
}

/** Moves the clock on in the mod's polling steps until it has logged, or
 * `ms` have passed. */
async function until(w: World, ms: number) {
  for (let t = 0; t < ms && !w.logged.length; t += 500) {
    await w.clock.advance(500)
  }
}

/** The receipt's lines as the mod should log them at `now`, worked out
 * from the transcript's bytes: receiptLines over the cost document, at the
 * band's width, its rows' indent left to Claude Code's notice chrome. */
async function receiptOf(w: World, now: number): Promise<string[]> {
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
  const { head, rows } = receiptLines(settings({}), fig, COLS, [],
    workspaceOf(doc, HOME), true, spec.C_CHROME_CONT)
  const pad = ' '.repeat(spec.C_CHROME_CONT)
  return [text(head), ...rows.map((r) => {
    const t = text(r)
    expect(t.startsWith(pad)).toBe(true)
    return t.slice(pad.length)
  })].map((l) => pyRstrip(l))
}

test('a turn whose records land after turn.complete gets its receipt, once',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    // The band draws first, and the receipt is laid out at its width.
    await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
      component: 'AbovePrompt', props: BAND })
    await askLive($, w, true)
    await until(w, 5_000)
    const want = await receiptOf(w, w.clock.now() / 1000)
    expect(want.length).toBe(3)
    expect(want[0]).toContain('p-resume'.slice(0, 8))
    expect(w.logged).toEqual(want)
    // turn.complete again over the same turn: nothing more.
    await $.turn.complete(COMPLETE)
    await w.clock.advance(5_000)
    expect(w.logged).toEqual(want)
    expect(logOf(w)).not.toContain('no receipt')
  })

test('a turn whose records never land logs why and stamps nothing',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await askLive($, w, false)
    await until(w, 31_000)
    expect(w.logged).toEqual([])
    expect(logOf(w)).toContain('no receipt: the turn was not billed ' +
      'within 30s')
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
  const st = settings({})

  const band = await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
    component: 'AbovePrompt', props: BAND })
  const lines = bandLines(st, doc, COLS, [], { home: HOME, rate: null,
    phase: 'done', indent: spec.C_CHROME_CONT })
  expect(lines.length).toBeGreaterThan(0)
  expect(await drawnRows(band)).toEqual(expected(lines))

  const tag = startLine(doc)
  expect(tag.length).toBeGreaterThan(0)
  expect(w.store.get(startKey(ASKED))).toBeDefined()
  const typed = await $.ui.mount({ plugin: 'usage-band', surface: 'terminal',
    component: 'UserMessage', props: { text: ASKED, isExpanded: false,
      origin: { kind: 'composer' } } })
  const under = await drawnRows(typed)
  expect(under[under.length - 1]?.text).toBe('  ' + text(tag))

  await blankClosing($, 'Crunched', ASKED_MS)
}

test('a resumed session whose first turn calls no tool draws all three',
  async ($, on) => {
    const w = world(on)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    await askAndAnswer($, w)
    await drewAll($, w)
    expect(logOf(w)).toContain('started by session.start in ' + CWD)
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

test('a refresh that throws once is logged, and the next one draws',
  async ($, on) => {
    const w = world(on, undefined, 1)
    resumed(w)
    await $.session.start({ cwd: CWD, surface: 'terminal',
      isInteractive: true })
    // The first read failed: nothing filed, and the log says why, in its
    // file and in the debug log.
    expect(w.docs.length).toBe(0)
    const why = /refresh: no status document: .*usage unavailable/
    expect(logOf(w)).toMatch(why)
    expect(w.debug.some((l) => why.test(l))).toBe(true)
    await askAndAnswer($, w)
    await drewAll($, w)
  })
