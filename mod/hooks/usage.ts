// The usage source: the Claude Usage Tracker's store, the OAuth usage
// answer and the dollar credits asked of it, prepared as the Python
// prepares its reading.
import type { EngineInterface } from 'claude-code'

import { pyJoin } from '../src/claude_records.ts'
import {
  cacheName, commandInput, commandOutput, identity, isCacheName, pyFloat,
  claudeOauthReading, creditsReading, CREDITS_PERIOD, CREDITS_SOURCE,
  CREDITS_TTL, normalise, pyJsonDumps, pyJsonLoads, pyStr, trackerV1,
} from '../src/sources.ts'
import type { Env, Fetch, Reading, Store } from '../src/sources.ts'
import {
  configAccountOf, plistLoads, prepareClaudeReading, statusSourceContext,
  trackerReading,
} from '../src/claude_sources.ts'
import type { PreparedClaudeReading } from '../src/claude_sources.ts'
import { isDict, pyGet } from '../src/py.ts'
import type { Dict } from '../src/py.ts'
import {
  encoder, fileSize, found, fromBase64, listDir, readBytesVia, readText,
  readTextVia, runVia, writeText,
} from './engine.ts'
import type { Places } from './engine.ts'
import { defaultsFault, options } from './configuration.ts'

type $ = EngineInterface

const TRACKER_DOMAIN = 'HamedElfayome.Claude-Usage'

/** The Claude Usage Tracker's store, as readTracker reads it: the override
 * file through `$.fs`, else `defaults export`, since the app's own .plist
 * is binary and a running app's preferences reach it late. */
async function readTracker($: $, home: string): Promise<Dict | null> {
  const override =
    await $.env.get('CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST')
  if (override) {
    const path = override.startsWith('~/') ? home + override.slice(1)
      : override
    const got = await readBytesVia($, path)
    return trackerReading(plistLoads(fromBase64(got.base64)))
  }
  const plist = home + '/Library/Preferences/' + TRACKER_DOMAIN + '.plist'
  if (await fileSize($, plist) === null) return null
  try {
    const r = await runVia($, ['defaults', 'export', TRACKER_DOMAIN, '-'],
      { timeoutMs: 15_000 })
    return trackerReading(r.stdout ? plistLoads(encoder.encode(r.stdout)) : {})
  } catch {
    return {}
  }
}

/** One collector, as fetchSource runs it; the others are no reading. */
async function fetchOne($: $, home: string, selected: string,
  context: Dict): Promise<unknown> {
  if (selected.startsWith('cmd:')) {
    // Exactly one path, or bash over it, passing only the scope fields.
    try {
      const r = await runVia($, ['/bin/sh', '-c',
        'if [ -x "$1" ]; then exec "$1"; else exec bash "$1"; fi', 'sh',
        selected.slice(4)], { stdin: commandInput(context),
        timeoutMs: 5_000 })
      return r.exitCode === 0 ? commandOutput(encoder.encode(r.stdout)) : {}
    } catch {
      return {}
    }
  }
  if (selected === 'claude-usage-tracker') {
    try {
      const raw = await readTracker($, home)
      return raw === null ? {} : trackerV1(raw)
    } catch {
      return {}
    }
  }
  if (selected === 'experimental-claude-oauth') {
    // With the session's own credential, which the engine sets and sends
    // only to a first-party host; none under a third-party provider.
    try {
      const auth = await $.session.authorize()
      if (!auth) return {}
      const r = await $.http.fetch(OAUTH_USAGE_URL, { auth: auth.handle,
        headers: { 'anthropic-beta': 'oauth-2025-04-20' } })
      if (!r.ok) return {}
      return claudeOauthReading(pyJsonLoads(r.text),
        (await $.clock.now()) / 1000)
    } catch {
      return {}
    }
  }
  return {}
}

// Claude's plan windows, as the account's own usage page reads them.
const OAUTH_USAGE_URL = 'https://api.anthropic.com/api/oauth/usage'

let configAccount: { path: string; stamp: string; id: string } | null = null

/** config_account_id through `$`: Claude Code's signed-in account, hashed,
 * from its global config, kept against the file's mtime and size, since
 * the file is a quarter of a megabyte and rewritten often. */
async function configAccountVia($: $, home: string): Promise<string> {
  const dir = await $.env.get('CLAUDE_CONFIG_DIR')
  const path = dir ? (dir.startsWith('~/') ? home + dir.slice(1) : dir) +
    '/.claude.json' : home + '/.claude.json'
  try {
    const st = await $.fs.stat(path)
    const stamp = st.mtimeMs + '/' + st.size
    if (configAccount?.path === path && configAccount.stamp === stamp) {
      return configAccount.id
    }
    const id = configAccountOf(await readTextVia($, path))
    configAccount = { path, stamp, id }
    return id
  } catch {
    return ''
  }
}

/** A cache file of the shared store, or {} where there is none. */
async function readJson($: $, path: string): Promise<Dict> {
  const text = await readText($, path)
  if (text === null) return {}
  try {
    const v = pyJsonLoads(text)
    return isDict(v) ? v : {}
  } catch {
    return {}
  }
}

/** fileStore's load. */
async function storeLoad($: $, dir: string, agent: string, source: string,
  account: string, periodStart: string): Promise<Dict> {
  const value = await readJson($, pyJoin(dir,
    cacheName(agent, source, account, periodStart)))
  const want = identity([agent, source, account, periodStart])
  const have = identity([value.agent, value.source, value.account_name,
    value.period_start])
  return want.join('\0') === have.join('\0') ? value : {}
}

/** fileStore's save. */
async function storeSave($: $, dir: string, agent: string, source: string,
  account: string, periodStart: string, value: Dict): Promise<void> {
  await writeText($, pyJoin(dir, cacheName(agent, source, account,
    periodStart)), pyJsonDumps({ ...value, agent: String(agent),
    source: String(source), account_name: String(account),
    period_start: String(periodStart) }, true))
}

/** fileStore's findCompatible: the newest reading for this account and
 * period from any source. */
async function storeFind($: $, dir: string, agent: string, account: string,
  periodStart: string): Promise<Dict> {
  let newest: Dict = {}
  for (const e of await listDir($, dir)) {
    if (!isCacheName(e.name)) continue
    const value = await readJson($, pyJoin(dir, e.name))
    if (value.agent !== agent || value.account_name !== account ||
        pyStr(pyGet(value, 'period_start')) !== pyStr(periodStart)) {
      continue
    }
    const mine = pyFloat(pyGet(value, 'as_of'))
    const theirs = pyFloat(pyGet(newest, 'as_of', -1))
    const newer = mine === null || theirs === null
      ? Object.keys(newest).length === 0 : mine > theirs
    if (newer) newest = value
  }
  return newest
}

/** prepare_claude_reading through `$`, with the mod's configuration and
 * the status line's shared cache, so the two read one reading. */
export async function preparedVia($: $, places: Places, raw: Dict,
  sessionId: string, model: string, now: number):
  Promise<PreparedClaudeReading> {
  const o = options()
  if (o === null) throw new Error('no options: ' + (defaultsFault ?? 'unread'))
  const { usageSource: spec, account, accountPeriod } = o
  const context = statusSourceContext(spec, sessionId, model, now, raw)
  const dir = places.stateDir
  const store: Store = {
    load: (a, s, c, p) => storeLoad($, dir, a, s, c, p),
    save: (a, s, c, p, v) => storeSave($, dir, a, s, c, p, v),
    findCompatible: (a, c, p) => storeFind($, dir, a, c, p),
  }
  const fetch: Fetch = (selected, ctx) =>
    fetchOne($, places.home, selected, ctx)
  const env: Env = {}
  // Under auto, the account's own usage endpoint in place of the tracker
  // app, which need not be running: the mod can ask it as the session.
  return prepareClaudeReading(spec, account, accountPeriod, context,
    now, env, store, fetch, () => configAccountVia($, places.home),
    'experimental-claude-oauth')
}

/** Whether an ask for the credits is under way, so a document doesn't
 * start a second. */
let creditsAsking = false

/** The account's credits, refreshed once CREDITS_TTL has passed since the
 * last ask, behind the document as calibrationVia scans: a document takes
 * the kept credits, and an ask that is due starts after it, whose answer
 * the next document takes, so a slow or refused endpoint never holds the
 * status document.  The ask is of the OAuth usage answer and then
 * `command`, a program printing the credits[] JSON (the `credits`
 * option's), the first of a credit's id kept; and the answer is kept for
 * the status line in the shared store
 * under the signed-in account.  With none, the usage endpoint isn't
 * asked, and only the command's credits are kept, under `account`.  When
 * every ask fails the last credits are kept, and the next ask waits out
 * the same pace. */
export async function creditsVia($: $, places: Places, now: number,
  account: string, command: string | null = null): Promise<Reading> {
  const signedIn = await configAccountVia($, places.home)
  const who = signedIn || (command ? account : '')
  if (!who) return {}
  const dir = places.stateDir
  const kept = await storeLoad($, dir, 'claude', CREDITS_SOURCE, who,
    CREDITS_PERIOD)
  const asked = pyFloat(pyGet(kept, 'attempted_at'))
  const due = asked === null || now - asked >= CREDITS_TTL || now < asked
  if (due && !creditsAsking) {
    creditsAsking = true
    void askCredits($, places, who, signedIn, command, kept, now)
      .catch(() => {})
      .finally(() => {
        creditsAsking = false
      })
  }
  return normalise(kept, CREDITS_SOURCE)
}

/** creditsVia's ask: the usage endpoint's credits and then the command's,
 * saved with attempted_at, or the last credits when neither answers. */
async function askCredits($: $, places: Places, who: string,
  signedIn: string, command: string | null, kept: unknown,
  now: number): Promise<void> {
  const found: unknown[] = []
  let answered = false
  try {
    const auth = signedIn ? await $.session.authorize() : null
    if (auth) {
      const r = await $.http.fetch(OAUTH_USAGE_URL, { auth: auth.handle,
        headers: { 'anthropic-beta': 'oauth-2025-04-20' } })
      if (r.ok) {
        const got = creditsReading(pyJsonLoads(r.text), now)
        found.push(...(Array.isArray(got.credits) ? got.credits : []))
        answered = true
      }
    }
  } catch {
    // No answer: the command's, or the last credits.
  }
  if (command) {
    const got = await fetchOne($, places.home, 'cmd:' + command, {})
    if (isDict(got) && Object.keys(got).length) {
      found.push(...(Array.isArray(got.credits) ? got.credits : []))
      answered = true
    }
  }
  const reading = answered ? normalise({ schema_version: 1, as_of: now,
    credits: found }, CREDITS_SOURCE) : normalise(kept, CREDITS_SOURCE)
  await storeSave($, places.stateDir, 'claude', CREDITS_SOURCE, who,
    CREDITS_PERIOD, { ...reading, attempted_at: now })
}
