// The engine beneath the mod in its tests, answered from memory: `$.fs`
// from the fixture files (fixtures.gen.ts), `$.env`, `$.session`,
// `$.clock` and `$.store` from memory, and `$.process.run` as a directory
// with no git unless a test answers it.  `world` mounts it, and gives back
// what the mod read, wrote, listed, ran and logged, for a test to check.
import { mock } from 'claude-code/testing'
import type { MockClock } from 'claude-code/testing'
import type { On, RenderElement } from 'claude-code'

import { CALIB, FILES, NOW, TRACKER } from './fixtures.gen.ts'
import { DEFAULTS_TEXT, isDefaults } from './defaults.ts'
import { fromBase64 } from '../hooks/engine.ts'
import type { Dict } from '../src/py.ts'

export const HOME = '/home/fixture'
export const STATE = '/state'
export const CWD = '/work'
export const SESSION = 'fixture-session'
export const MODEL = 'claude-opus-5[1m]'
export const WINDOW = 1_000_000

// The world's user file (world): the look these tests draw, the
// tracker's store, five figures hidden, and 🎤, 🤖 and 🎮 drawn while a
// turn runs and stamped into the transcript.
export const USER_FILE = HOME + '/.config/coding-agent-usage-line/config.jsonc'
export const USER_SETTINGS = {
  'usage-source': 'claude-usage-tracker',
  'hide': ['*.plan.five_hour', '*.context.share', '*.tokens.cache',
    'account.workspace.project', 'account.workspace.branch'],
  'rows': {
    turn: { live: 'running', transcript: true },
    agent: { live: 'running', transcript: true },
    session: { live: 'running', transcript: true },
  },
}

const encoder = new TextEncoder()

export type World = {
  files: Map<string, Uint8Array>
  store: Map<string, unknown>
  // Each status document the mod filed in `$.state`, oldest first.
  docs: Dict[]
  // Whether `$.session.usage` is refused, and, while `hung` holds a list,
  // each ask held unanswered until its function is called.
  usage: { down: boolean; hung?: (() => void)[] }
  // Each line the mod sent the debug log.
  debug: string[]
  // Each line the mod wrote into the transcript, `$.ui.log`'s default.
  logged: string[]
  clock: MockClock
  // The session `$.session.id` answers, which a /resume switches.
  session: { id: string }
  // The usage endpoint's answer, and the requests made of it; with no
  // answer there is no credential, and nothing is asked.
  oauth: { body: string | null; asked: { url: string; auth?: string }[];
    hang?: boolean }
  // The path of each `$.fs.read` and each `$.fs.list`, and the argv of
  // each `$.process.run`, in order.
  reads: string[]
  lists: string[]
  runs: (readonly string[])[]
  // Each file's mtime in ms where a test set one; NOW otherwise.
  mtimes: Map<string, number>
}

export type Run = { argv: readonly string[]; init?: { stdin?: string } }
export type Ran = { exitCode: number; stdout: string; stderr: string;
  isStdoutTruncated: boolean; isStderrTruncated: boolean }
export const NO_GIT_HERE: Ran = { exitCode: 128, stdout: '',
  stderr: 'not a git repository', isStdoutTruncated: false,
  isStderrTruncated: false }

/** The engine beneath the mod, answered from memory; `run` answers
 * `$.process.run`, a directory with no git by default, `$.session.usage`
 * is refused while `usage.down`, which `usageDown` starts it at, and a
 * fresh calibration is planted unless `calib` is false. */
export function world(on: On, run: (e: Run) => Ran = () => NO_GIT_HERE,
  usageDown = false, calib = true,
  terminal: Record<string, string> = {}): World {
  const files = new Map<string, Uint8Array>()
  const mtimes = new Map<string, number>()
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
    // The terminal's variables, none by default: Claude Code's colour
    // level is then under true colour, and the 256 set is drawn.
    ...terminal,
  })
  // The calibration the environment plants, under whatever name the
  // snapshot's scope gives it, and fresh.
  const planted = (p: string) => calib &&
    /\/claude-calibration-[0-9a-f]{64}\.cache$/.test(p)
    ? encoder.encode(JSON.stringify(CALIB)) : undefined
  const fileAt = (p: string) => files.get(p) ?? planted(p) ??
    (isDefaults(p) ? encoder.encode(DEFAULTS_TEXT) : undefined)
  const isDir = (p: string) => [...files.keys()].some((f) =>
    f.startsWith(p.endsWith('/') ? p : p + '/'))
  on('fs.stat', ($, e) => {
    const f = fileAt(e.path)
    if (f) {
      return { value: { kind: 'file' as const, size: f.length,
        mtimeMs: mtimes.get(e.path) ?? NOW * 1000, isLink: false } }
    }
    if (isDir(e.path)) {
      return { value: { kind: 'dir' as const, size: 0, mtimeMs: NOW * 1000,
        isLink: false } }
    }
    return { deny: 'no such file: ' + e.path }
  })
  const reads: string[] = [], lists: string[] = []
  on('fs.read', ($, e) => {
    reads.push(e.path)
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
    lists.push(e.path)
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
      mtimeMs: mtimes.get(dir + name) ?? NOW * 1000, isLink: false })) }
  })
  const runs: (readonly string[])[] = []
  on('process.run', ($, e) => {
    runs.push(e.argv)
    return { value: run(e) }
  })
  on('session.cwd', () => ({ value: CWD }))
  on('session.root', () => ({ value: CWD }))
  on('session.model', () => ({ value: MODEL }))
  const session = { id: SESSION }
  on('session.id', () => ({ value: session.id }))
  const oauth: World['oauth'] = { body: null, asked: [] }
  on('session.authorize', () => ({ value: oauth.body === null ? null
    : { handle: 'test-handle', kind: 'bearer' as const } }))
  on('http.fetch', ($, e: any) => {
    oauth.asked.push({ url: e.url, auth: e.init?.auth })
    if (oauth.hang) return new Promise(() => {})
    return oauth.body === null ? { deny: 'no network in tests' } as any
      : { value: { status: 200, ok: true, headers: {}, text: oauth.body } }
  })
  const usage: World['usage'] = { down: usageDown }
  const reading = () => ({ value: { startedAt: NOW * 1000,
    context: { tokens: 1000, window: WINDOW }, rateLimits: [] } })
  on('session.usage', () => usage.hung
    ? new Promise((r) => usage.hung!.push(() => r(reading())))
    : usage.down
    ? { deny: 'usage unavailable' } as any
    : { value: { startedAt: NOW * 1000,
      context: { tokens: 1000, window: WINDOW }, rateLimits: [] } })
  // The engine's own drawings, and the events beneath the mod.
  on('ui.render', () => h('Box', null) as RenderElement)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  // The lines `$.ui.log` sends: the debug log's, `{ to: 'debug' }`, and
  // the transcript's.
  const debug: string[] = []
  const logged: string[] = []
  on('ui.log', ($, e) => {
    ;(e.to === 'debug' ? debug : logged).push(e.text)
    return { value: undefined }
  })
  return { files, store, docs, usage, debug, logged, clock, session,
    oauth, reads, lists, runs, mtimes }
}
