// The mod's read of the configuration files, in the engine's test harness:
// what a session's start reads through `$.fs` and says in the mod's log.
// test/config.test.ts holds the reading itself to the Python's over the
// shared cases; this holds the edges (hooks/edges.ts, readConfig) to it.
//
// Hermetic, as tests/config.py's GoldensAreHermetic is for the Python: the
// harness has nothing beneath the mod, and this world answers `$.fs`,
// `$.env` and `$.session` from memory.  Every path the mod asks for, the
// configuration's and the figures' alike, must lie under the world's own
// directories, so no developer's config file, state directory or
// ~/.claude.json can reach a result.
import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

import { LOG_NAME } from '../hooks/log.ts'
import { optionsTable, unconfigured } from '../hooks/edges.ts'
import { MOD_LAYER, merge as mergeConfig, optionsOf } from '../src/config.ts'

const HOME = '/home/fixture'
const STATE = '/state'
const CLAUDE = '/claude'
const PROJECT = '/work/p'
const D = '/.config/coding-agent-usage-line/'
const USER_FILE = HOME + D + 'config.jsonc'
const PROJECT_FILE = PROJECT + D + 'config.jsonc'
// The only places a path the mod asks for may be.
const PLACES = [HOME, STATE, CLAUDE, PROJECT]
const ENV: { [name: string]: string } = {
  HOME, CODING_AGENT_USAGE_LINE_STATE_DIR: STATE, CLAUDE_CONFIG_DIR: CLAUDE,
}

type World = { files: Map<string, string>; asked: string[]; names: string[] }

/** The engine beneath the mod: a user file with a typo, a project file
 * with a source Claude cannot read, and the project's `.git`. */
function world(on: On): World {
  const files = new Map<string, string>([
    [USER_FILE, '{"rwos": {}, "account": "u"}'],
    [PROJECT_FILE, '{"hide": [], "usage-source": "codex-app-server"}'],
  ])
  const dirs = new Set([PROJECT + '/.git'])
  const asked: string[] = []
  const names: string[] = []
  const isDir = (p: string) => dirs.has(p) ||
    [...files.keys(), ...dirs].some((f) => f.startsWith(p + '/'))
  mock.clock(on, { now: 1_800_000_000_000 })
  on('env.get', ($, e) => {
    names.push(e.name)
    return { value: ENV[e.name] }
  })
  on('fs.stat', ($, e) => {
    asked.push(e.path)
    const f = files.get(e.path)
    if (f === undefined && !isDir(e.path)) {
      return { deny: 'no such file: ' + e.path }
    }
    return { value: { kind: f === undefined ? 'dir' as const : 'file' as const,
      size: f === undefined ? 0 : new TextEncoder().encode(f).length,
      mtimeMs: 1, isLink: false, realPath: e.path } }
  })
  on('fs.read', ($, e) => {
    asked.push(e.path)
    const f = files.get(e.path)
    if (f === undefined) return { deny: 'no such file: ' + e.path }
    if (e.as === 'bytes') {
      let s = ''
      for (const b of new TextEncoder().encode(f)) s += String.fromCharCode(b)
      return { value: { base64: btoa(s) } }
    }
    return { value: f }
  })
  on('fs.write', ($, e) => {
    asked.push(e.path)
    files.set(e.path, e.text)
    return { value: undefined }
  })
  on('fs.list', ($, e) => {
    asked.push(e.path)
    return { deny: 'no such directory: ' + e.path }
  })
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
  on('process.run', () => ({ value: { exitCode: 128, stdout: '',
    stderr: 'not a git repository', isStdoutTruncated: false,
    isStderrTruncated: false } }))
  on('session.cwd', () => ({ value: PROJECT + '/sub' }))
  on('session.root', () => ({ value: PROJECT }))
  on('session.id', () => ({ value: 'config-session' }))
  on('session.model', () => ({ value: 'claude-opus-5' }))
  on('session.usage', () => ({ deny: 'usage unavailable' }) as any)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('ui.log', () => ({ value: undefined }))
  return { files, asked, names }
}

// The test's environment has timers, which the hooks' types leave out.
declare const setTimeout: (f: () => void, ms: number) => unknown

/** Lets the reads a session's start begins, and does not wait for, end. */
async function settle() {
  for (let i = 0; i < 50; i++) {
    await new Promise((r) => setTimeout(() => r(undefined), 0))
  }
}

test('a session start reads the config files and logs every warning once',
  async ($, on) => {
    const w = world(on)
    await $.session.start({ cwd: PROJECT, surface: 'terminal',
      isInteractive: true })
    await settle()
    const log = w.files.get(STATE + '/' + LOG_NAME) ?? ''
    expect(log).toContain(`config from ${PROJECT}: project ${PROJECT_FILE}` +
      ` (hide); user ${USER_FILE} (account)`)
    const warnings = [
      `${USER_FILE}: "rwos" is no option (did you mean "rows"?); skipped`,
      `${PROJECT_FILE}: "usage-source" "codex-app-server" is no source ` +
        'claude reads; skipped',
    ]
    for (const w of warnings) {
      expect(log.split('config: ' + w).length - 1).toBe(1)
    }
  })

// The options with no file, field by field: the spec's defaults
// (spec/options.jsonc), the mod's own layer (hooks/config.ts, SETTINGS)
// being empty; right-edge is derived from live-place.
test('with no configuration file the options are the defaults', () => {
  expect(unconfigured()).toEqual({
    usageSource: 'auto',
    account: 'default',
    accountPeriod: 'day',
    rightEdge: 2,
    hide: [],
    markSpacing: true,
    subscriptDecimals: false,
    livePlace: 'footer',
    rows: {
      turn: { live: 'running', transcript: true },
      agent: { live: 'always', transcript: false },
      session: { live: 'always', transcript: false },
      tag: { live: 'never', transcript: true },
      account: { live: 'always', transcript: false },
    },
    accountPlace: 'tail',
    hintTuck: false,
    hintInset: 2,
    footerRuler: false,
    agentMessageRow: true,
    slowToast: false,
    startsKept: 400,
  })
})

test('a session start logs the options the files gave',
  async ($, on) => {
    const w = world(on)
    await $.session.start({ cwd: PROJECT, surface: 'terminal',
      isInteractive: true })
    await settle()
    const log = w.files.get(STATE + '/' + LOG_NAME) ?? ''
    expect(log).toContain('config options: ' +
      'account "u" (user); right-edge 2 (derived); hide [] (project)\n')
  })

// The mod's own layer, were SETTINGS to hold any: under every file, over
// the defaults, per field in a table, and named "mod" in the log's table.
test('a non-empty mod layer merges under the files and is named in the log',
  () => {
    const m = mergeConfig([
      { name: 'user', path: USER_FILE, mtimeMs: 1,
        values: { 'hide': [], 'rows': { agent: { live: 'never' } } } },
      { name: MOD_LAYER, path: 'mod/hooks/config.ts', mtimeMs: 0,
        values: { 'usage-source': 'claude-usage-tracker',
          'hide': ['*.context.share'],
          'rows': { agent: { live: 'running', transcript: true } } } },
    ], [])
    const o = optionsOf(m)
    expect(o.usageSource).toBe('claude-usage-tracker')
    expect(o.hide).toEqual([])
    expect(o.rows.agent).toEqual({ live: 'never', transcript: true })
    expect(optionsTable(m)).toBe(
      'usage-source "claude-usage-tracker" (mod); right-edge 2 (derived); ' +
      'hide [] (user); rows.agent.live "never" (user); ' +
      'rows.agent.transcript true (mod)')
  })

test('the mod asks for no path outside the world it is handed',
  async ($, on) => {
    const w = world(on)
    await $.session.start({ cwd: PROJECT, surface: 'terminal',
      isInteractive: true })
    await settle()
    // The walk's and the figures' reads both ran.
    expect(w.asked).toContain(PROJECT_FILE)
    expect(w.asked).toContain(USER_FILE)
    for (const name of ['HOME', 'XDG_CONFIG_HOME',
      'CODING_AGENT_USAGE_LINE_CONFIG_DIR']) {
      expect(w.names).toContain(name)
    }
    const outside = w.asked.filter((p) =>
      !PLACES.some((d) => p === d || p.startsWith(d + '/')))
    expect(outside).toEqual([])
  })
