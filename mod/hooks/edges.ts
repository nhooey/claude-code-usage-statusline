// The mod's edges: every read the figures documents are made from, through
// `$`, and the two documents built from them: the status document the band
// draws, and the cost document the receipt is stamped from.
//
// The src/ ports are pure where the plan says (figures from records, spans
// from figures), and their Node edges live in src/*_node.ts, which the mod
// never imports: this module is the mod's version of those, reading the
// transcript and the agent files through `$.fs`, git and the usage source
// through `$.process.run`, and the clock through `$.clock`.  What it reads
// it hands to src/claude.ts's statusFigures and costFigures, which are the
// Python's status_figures and cost_figures past their reads.
//
// The reads keep what they have read in memory between documents, as the
// Python keeps its agent cache and cost cache on disk: a transcript is only
// ever appended to, so each document reads only the bytes past the last
// complete line it parsed before.
import type { EngineInterface } from 'claude-code'

import {
  _agentDir, _agentStatePath, _readAgentBytes, _recordsOf, agentLabelOf,
  agentOffsetsOf, agentRecordsOf, cmpStr, EMPTY_TRANSCRIPT, pyJoin,
  readPayload, transcriptOf, turnsOf,
} from '../src/claude_records.ts'
import type {
  AgentEta, AgentReading, AgentRec, Payload, Rec, Transcript, Turn,
} from '../src/claude_records.ts'
import {
  _calibrationCacheName, _calibrationOf, _idKey, _pricedRecord,
  _windowCostsOf, _windowsKey, _windowStarts, CALIB_TTL, COST_TAIL_BYTES,
  seedLimitsSnapshot,
} from '../src/claude_calib.ts'
import type { Calib, Priced, Snapshot } from '../src/claude_calib.ts'
import {
  cacheName, commandInput, commandOutput, identity, pyFloat, pyJsonDumps,
  pyJsonLoads, pyStr, trackerV1,
} from '../src/sources.ts'
import type { Env, Fetch, Store } from '../src/sources.ts'
import {
  plistLoads, prepareClaudeReading, statusSourceContext, trackerReading,
} from '../src/claude_sources.ts'
import type { PreparedClaudeReading } from '../src/claude_sources.ts'
import {
  baseLimits, costFigures, detectGit, sessionRate, statusFigures, windowFor,
} from '../src/claude.ts'
import type { RateSample } from '../src/claude.ts'
import { sha256Hex } from '../src/sha256.ts'
import { isDict, pyGet } from '../src/py.ts'
import type { Dict } from '../src/py.ts'
import { CONFIG } from './config.ts'

type $ = EngineInterface

/** What `$.fs.read` hands back whole; a larger file is read in pieces. */
const FS_READ_MAX = 4 * 1024 * 1024
/** One piece of a larger file, read through `tail | head | base64`: its
 * base64 must fit the 4 MiB `$.process.run` keeps of stdout. */
const PIECE = 2 * 1024 * 1024

const encoder = new TextEncoder()

// ════════════════════════════════════════════════════════════════════════════
// Bytes.
// ════════════════════════════════════════════════════════════════════════════

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const B64_INDEX = new Map([...B64].map((c, i) => [c, i]))

/** Standard base64 to bytes, whitespace skipped: `$.fs.read`'s `base64`,
 * and base64(1)'s output. */
export function fromBase64(text: string): Uint8Array {
  const native = (Uint8Array as unknown as {
    fromBase64?: (s: string) => Uint8Array })['fromBase64']
  const clean = text.replace(/[\s=]+/g, '')
  if (native) return native(clean + '='.repeat((4 - clean.length % 4) % 4))
  const out = new Uint8Array(Math.floor(clean.length * 3 / 4))
  let bits = 0, acc = 0, n = 0
  for (const c of clean) {
    acc = (acc << 6) | (B64_INDEX.get(c) ?? 0)
    bits += 6
    if (bits >= 8) {
      bits -= 8
      out[n++] = (acc >> bits) & 0xff
    }
  }
  return out.subarray(0, n)
}

function concat(parts: readonly Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0))
  let at = 0
  for (const p of parts) {
    out.set(p, at)
    at += p.length
  }
  return out
}

/** The file's size, or null where it is not a file. */
export async function fileSize($: $, path: string): Promise<number | null> {
  try {
    const st = await $.fs.stat(path)
    return st.kind === 'file' ? st.size : null
  } catch {
    return null
  }
}

/** The bytes of `path` from `start` to `end`.  A file `$.fs.read` takes
 * whole is read so and cut; a larger one, which it refuses, in pieces
 * through the shell, since `$.fs` reads no range. */
export async function readRange($: $, path: string, start: number,
  end: number): Promise<Uint8Array> {
  if (end <= start) return new Uint8Array(0)
  if (end <= FS_READ_MAX) {
    const got = await $.fs.read(path, { as: 'bytes' })
    return fromBase64(got.base64).subarray(start, end)
  }
  const parts: Uint8Array[] = []
  for (let at = start; at < end;) {
    const want = Math.min(PIECE, end - at)
    const r = await $.process.run(['/bin/sh', '-c',
      'tail -c +"$1" "$2" | head -c "$3" | base64', 'sh',
      String(at + 1), path, String(want)], { timeoutMs: 30_000 })
    if (r.exitCode !== 0) throw new Error('could not read ' + path)
    const piece = fromBase64(r.stdout)
    if (!piece.length) break
    parts.push(piece)
    at += piece.length
  }
  return concat(parts)
}

async function readText($: $, path: string): Promise<string | null> {
  try {
    return await $.fs.read(path)
  } catch {
    return null
  }
}

/** `$.fs.write`, false where it could not: a cache that will not write
 * is a miss next time. */
async function writeText($: $, path: string, text: string): Promise<boolean> {
  try {
    await $.fs.write(path, text)
    return true
  } catch {
    return false
  }
}

// ════════════════════════════════════════════════════════════════════════════
// What is kept between documents.
//
// Module state, not objects that hold `$`: the engine follows `$` only into
// functions declared at the top of a file, so each read is one, and what
// it keeps lives here.  A reload starts it over, which costs one full read.
// ════════════════════════════════════════════════════════════════════════════

type Parsed = { stable: number; records: Rec[] }
type AgentKept = { stamp: string; reading: AgentReading }
type CostKept = { off: number; tail: string | null; recs: Priced[] }

/** What the session tells the mod that the status line's payload carries,
 * as handlers learn it: the transcript from a classic event, the model's
 * effort from a turn's step.  `session` is the id the transcript is the
 * one for, where that is known: a /clear or a /resume in the same process
 * moves the session on, and the transcript with it. */
export type Seen = { transcript: string; session: string; effort: string }

export const seen: Seen = { transcript: '', session: '', effort: '' }
const parsed = new Map<string, Parsed>()
const agentKept = new Map<string, AgentKept>()
const agentLabels = new Map<string, [string, string]>()
const costs = new Map<string, CostKept>()
let costsRead = false
let scanning = false
let samples: RateSample[] = []

// ════════════════════════════════════════════════════════════════════════════
// The transcripts.
// ════════════════════════════════════════════════════════════════════════════

/** A file's records as _recordsOf reads them, kept between documents: the
 * records up to the last complete line, and the bytes after it read again
 * each time, since a live transcript's last line can be half written.  A
 * file that shrank is read again from the start. */
export async function recordsOf($: $, path: string): Promise<Rec[]> {
  const size = await fileSize($, path)
  if (size === null) {
    parsed.delete(path)
    return []
  }
  let got = parsed.get(path)
  if (!got || size < got.stable) got = { stable: 0, records: [] }
  let data: Uint8Array
  try {
    data = await readRange($, path, got.stable, size)
  } catch {
    return got.records
  }
  const nl = data.lastIndexOf(10)
  if (nl >= 0) {
    got = { stable: got.stable + nl + 1,
      records: [...got.records, ..._recordsOf(data.subarray(0, nl + 1))] }
  }
  parsed.set(path, got)
  const rest = data.subarray(nl + 1)
  return rest.length ? [...got.records, ..._recordsOf(rest)] : got.records
}

const AGENT_NAME = /^agent-[\s\S]*\.jsonl$/

type Listed = { path: string; size: number; mtimeMs: number }

/** `$.fs.list`, or nothing where the directory will not list. */
async function listDir($: $, dir: string) {
  try {
    return await $.fs.list(dir)
  } catch {
    return []
  }
}

/** Every agent transcript under `dir`, at any depth, hidden names skipped:
 * the walk agentFiles and projectFiles both make. */
async function agentWalk($: $, dir: string, out: Listed[]): Promise<void> {
  for (const e of await listDir($, dir)) {
    if (e.name.startsWith('.')) continue
    const p = pyJoin(dir, e.name)
    if (e.kind === 'dir') await agentWalk($, p, out)
    else if (AGENT_NAME.test(e.name)) {
      out.push({ path: p, size: e.size, mtimeMs: e.mtimeMs })
    }
  }
}

/** agentFiles through `$.fs.list`, sorted so the walk is stable. */
export async function agentFiles($: $, transcript: string):
  Promise<Listed[]> {
  const out: Listed[] = []
  const d = _agentDir(transcript)
  if (d) await agentWalk($, d, out)
  return out.sort((a, b) => cmpStr(a.path, b.path))
}

/** The session's agent readings, as _agentFileReadings makes them, each
 * file read again only when its size or mtime moved; and each agent's
 * label from its sidecar, kept once read. */
export async function agentReadings($: $, transcript: string):
  Promise<[string, AgentReading][]> {
  const out: [string, AgentReading][] = []
  for (const f of await agentFiles($, transcript)) {
    const stamp = f.size + ':' + f.mtimeMs
    let got = agentKept.get(f.path)
    if (!got || got.stamp !== stamp) {
      try {
        got = { stamp, reading: _readAgentBytes(
          await readRange($, f.path, 0, f.size)) }
      } catch {
        continue
      }
      agentKept.set(f.path, got)
    }
    out.push([f.path, got.reading])
    if (!agentLabels.has(f.path)) {
      // No sidecar yet reads as the id for now; it is asked for again
      // next time, and kept once read.
      const meta = await readText($,
        f.path.slice(0, -'.jsonl'.length) + '.meta.json')
      if (meta !== null) {
        agentLabels.set(f.path, agentLabelOf(f.path, encoder.encode(meta)))
      }
    }
  }
  return out
}

/** agent_label's reading of a file's sidecar, as agentReadings read it. */
function labelOf(path: string): [string, string] {
  return agentLabels.get(path) ?? agentLabelOf(path, null)
}

/** The offsets the last Stop hook published for this transcript (the
 * status line's, which keeps publishing them), or null. */
export async function agentOffsets($: $, transcript: string,
  stateDir: string): Promise<Map<string, number> | null> {
  const text = await readText($, _agentStatePath(transcript, stateDir))
  if (text === null) return null
  try {
    return agentOffsetsOf(text)
  } catch {
    return null
  }
}

/** read_turns over records already read, with the agents' readings and
 * the published offsets. */
async function turnsVia($: $, places: Places, path: string,
  records: readonly Rec[], readings: [string, AgentReading][]):
  Promise<Turn[]> {
  const offsets = await agentOffsets($, path, places.stateDir)
  return turnsOf(records, (s) => agentRecordsOf(readings, s, null),
    offsets, new Map(), labelOf)
}

// ════════════════════════════════════════════════════════════════════════════
// The usage source.
// ════════════════════════════════════════════════════════════════════════════

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
    const got = await $.fs.read(path, { as: 'bytes' })
    return trackerReading(plistLoads(fromBase64(got.base64)))
  }
  const plist = home + '/Library/Preferences/' + TRACKER_DOMAIN + '.plist'
  if (await fileSize($, plist) === null) return null
  try {
    const r = await $.process.run(['defaults', 'export', TRACKER_DOMAIN, '-'],
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
      const r = await $.process.run(['/bin/sh', '-c',
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
  return {}
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
    if (!e.name.endsWith('.json') || e.name.startsWith('reported-')) continue
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
async function preparedVia($: $, places: Places, raw: Dict,
  sessionId: string, model: string, now: number):
  Promise<PreparedClaudeReading> {
  const spec = CONFIG.usageSource
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
  return prepareClaudeReading(spec, CONFIG.account, CONFIG.period, context,
    now, env, store, fetch)
}

// ════════════════════════════════════════════════════════════════════════════
// The calibration.
// ════════════════════════════════════════════════════════════════════════════

/** The calibration, as calibration() makes it, with the scan moved off the
 * render: a document takes the cached scan for these windows, however old,
 * and a cache older than CALIB_TTL (or none) starts one scan behind it,
 * whose result the next document takes.  Until the first scan lands the
 * shares are blank, where the status line's first render waits for it. */
export async function calibrationVia($: $, places: Places, snap: Snapshot,
  now: number): Promise<Calib> {
  const [ss, ws] = _windowStarts(snap)
  const windows = _windowsKey(ss, ws)
  const path = pyJoin(places.stateDir,
    _calibrationCacheName(windows, snap, CONFIG.version))
  let cached: Dict | null = null
  let fresh = false
  try {
    const st = await $.fs.stat(path)
    const d = pyJsonLoads(await $.fs.read(path))
    if (isDict(d) && (!('windows' in d) ||
        (d.windows === windows && 'sess_pct' in d))) {
      cached = d
      fresh = st.mtimeMs / 1000 > now - CALIB_TTL
    }
  } catch {
    // No scan for these windows yet.
  }
  if (!fresh && !scanning && (ss !== null || ws !== null)) {
    scanning = true
    void scanWindows($, places, snap, windows, path).catch(() => {})
      .finally(() => {
        scanning = false
      })
  }
  return _calibrationOf(snap, cached, null)
}

/** _windowCosts through `$`, then the cache written as _writeCalibCache
 * writes it.  The files are listed with their mtimes first, so only the
 * ones _windowCostsOf would open are read. */
async function scanWindows($: $, places: Places, snap: Snapshot,
  windows: string, path: string): Promise<void> {
  const [ss, ws] = _windowStarts(snap)
  const files = await projectFiles($, places.projectsDir)
  const mtime = new Map(files.map((f) => [f.path, f.mtimeMs / 1000]))
  const paths = files.map((f) => f.path)
  const wanted: string[] = []
  _windowCostsOf(ss, ws, paths, (p) => mtime.get(p) ?? null, (p) => {
    wanted.push(p)
    return []
  })
  await readCosts($, places)
  const recs = new Map<string, Priced[]>()
  for (const p of wanted) recs.set(p, await pricedOf($, p))
  const [sc, wc] = _windowCostsOf(ss, ws, paths,
    (p) => mtime.get(p) ?? null, (p) => recs.get(p) ?? [])
  await saveCosts($, places, new Set(wanted))
  await writeText($, path, pyJsonDumps({ windows, sess_cost: sc,
    week_cost: wc, sess_pct: pyGet(snap, 'session_pct'),
    week_pct: pyGet(snap, 'weekly_pct') }, false,
  ['sess_cost', 'week_cost', 'sess_pct', 'week_pct']))
}

function costsPath(places: Places): string {
  return pyJoin(places.stateDir, 'claude-window-costs-mod.cache')
}

/** The cost cache, once a load: each file's offset, the digest of the
 * bytes before it, and its priced records up to it, as _CostCache keeps
 * them, in a file of the mod's own. */
async function readCosts($: $, places: Places): Promise<void> {
  if (costsRead) return
  costsRead = true
  const text = await readText($, costsPath(places))
  if (text === null) return
  try {
    const d = pyJsonLoads(text)
    if (isDict(d) && d.version === CONFIG.version && isDict(d.files)) {
      for (const [k, v] of Object.entries(d.files)) {
        costs.set(k, v as CostKept)
      }
    }
  } catch {
    // A cache that will not parse: read everything.
  }
}

/** The cost cache written back, keeping only the files this scan read:
 * the others have aged out of both windows. */
async function saveCosts($: $, places: Places,
  keep: ReadonlySet<string>): Promise<void> {
  const files: Dict = {}
  for (const [k, v] of costs) if (keep.has(k)) files[k] = v
  try {
    await writeText($, costsPath(places), pyJsonDumps(
      { version: CONFIG.version, files }, false, ['']))
  } catch {
    // Unwritable: the next load scans again.
  }
}

/** _tailDigest through `$`: the COST_TAIL_BYTES before `off`. */
async function tailOf($: $, path: string, off: number):
  Promise<string | null> {
  try {
    const b = await readRange($, path, Math.max(0, off - COST_TAIL_BYTES),
      off)
    return b.length === Math.min(off, COST_TAIL_BYTES) ? sha256Hex(b) : null
  } catch {
    return null
  }
}

/** _CostCache.records through `$`: the file's priced records, read past
 * the offset kept for it when the bytes before it are unchanged. */
async function pricedOf($: $, path: string): Promise<Priced[]> {
  const size = await fileSize($, path)
  if (size === null) return []
  let got = costs.get(path)
  if (got && (got.off > size || await tailOf($, path, got.off) !==
      got.tail)) {
    got = undefined
  }
  let off = got?.off ?? 0, recs = got?.recs ?? []
  const seenIds = new Set(recs.map(([, k]) => _idKey(k)))
  let data: Uint8Array
  try {
    data = await readRange($, path, off, size)
  } catch {
    return recs
  }
  const fresh: Priced[] = []
  let partial: Priced | null = null
  let s = 0
  for (;;) {
    const e = data.indexOf(10, s)
    if (e < 0) {
      if (s < data.length) partial = _pricedRecord(data.subarray(s))
      break
    }
    const rec = _pricedRecord(data.subarray(s, e + 1))
    s = e + 1
    if (rec === null) continue
    const key = _idKey(rec[1])
    if (seenIds.has(key)) continue
    seenIds.add(key)
    fresh.push(rec)
  }
  off += s
  recs = [...recs, ...fresh]
  costs.set(path, { off, tail: await tailOf($, path, off), recs })
  return partial !== null && !seenIds.has(_idKey(partial[1]))
    ? [...recs, partial] : recs
}

/** projectFiles through `$.fs.list`: `<dir>/*\/*.jsonl` and every
 * `<dir>/*\/*\/subagents/**\/agent-*.jsonl`, with their mtimes. */
async function projectFiles($: $, dir: string): Promise<Listed[]> {
  const out: Listed[] = []
  const subs: string[] = []
  for (const proj of await listDir($, dir)) {
    if (proj.kind !== 'dir' || proj.name.startsWith('.')) continue
    const p = pyJoin(dir, proj.name)
    for (const e of await listDir($, p)) {
      if (e.name.startsWith('.')) continue
      if (e.kind === 'file' && e.name.endsWith('.jsonl')) {
        out.push({ path: pyJoin(p, e.name), size: e.size,
          mtimeMs: e.mtimeMs })
      } else if (e.kind === 'dir') {
        subs.push(pyJoin(pyJoin(p, e.name), 'subagents'))
      }
    }
  }
  for (const s of subs) await agentWalk($, s, out)
  return out
}

// ════════════════════════════════════════════════════════════════════════════
// The session.
// ════════════════════════════════════════════════════════════════════════════

/** Where things are: the status line's state directory and Claude Code's
 * projects directory, from HOME and the variables the Python reads. */
export type Places = { home: string; stateDir: string; projectsDir: string }

export async function placesOf($: $): Promise<Places> {
  const home = (await $.env.get('HOME')) ?? ''
  const state = (await $.env.get('CODING_AGENT_USAGE_LINE_STATE_DIR')) ||
    ((await $.env.get('XDG_STATE_HOME')) || home + '/.local/state') +
      '/coding-agent-usage-line'
  const config = (await $.env.get('CLAUDE_CONFIG_DIR')) || home + '/.claude'
  return { home, stateDir: state, projectsDir: config + '/projects' }
}

/** The status line's payload, made from `$.session` and what the handlers
 * have seen, and read by readPayload as the Python reads stdin. */
export async function payloadOf($: $, transcript: string): Promise<{
  raw: Dict; payload: Payload }> {
  const cwd = await $.session.cwd()
  const root = await $.session.root()
  const model = await $.session.model()
  const id = await $.session.id()
  const usage = await $.session.usage()
  const limit = (kind: string) => {
    const l = usage.rateLimits.find((r) => r.kind === kind)
    if (!l) return undefined
    return { used_percentage: l.percentUsed, resets_at: l.resetsAt ?
      Date.parse(l.resetsAt) / 1000 : undefined }
  }
  const raw: Dict = {
    session_id: id,
    transcript_path: transcript,
    cwd,
    workspace: { current_dir: cwd, project_dir: root || cwd },
    model: { id: model, display_name: model },
    context_window: { context_window_size: usage.context.window },
    ...(usage.cost ? { cost: { total_cost_usd: usage.cost.usd } } : {}),
    ...(seen.effort ? { effort: { level: seen.effort } } : {}),
    rate_limits: { five_hour: limit('five_hour'),
      seven_day: limit('seven_day') },
  }
  return { raw, payload: readPayload(JSON.stringify(raw)) }
}

/** The transcript's path: the one a classic event named, else the file
 * named for the session's id under the projects directory.
 *
 * The classic events are the lesser source: Claude Code's own security
 * plugin passes them by a user's mod (its debug log says "classic.
 * SessionStart bypassed by cc-plugin-sec-default"), so in a live session
 * the path is found by the session's id, and found again when the id
 * moves on. */
export async function transcriptPath($: $, places: Places):
  Promise<string> {
  const id = await $.session.id()
  if (seen.transcript && (!seen.session || seen.session === id)) {
    return seen.transcript
  }
  for (const p of await listDir($, places.projectsDir)) {
    if (p.kind !== 'dir') continue
    const path = pyJoin(pyJoin(places.projectsDir, p.name), id + '.jsonl')
    if (await fileSize($, path) !== null) {
      seen.transcript = path
      seen.session = id
      return path
    }
  }
  return ''
}

/** detect_git through `$.process.run`, in the session's directory. */
async function gitVia($: $, cwd: string) {
  return detectGit(async (args) => {
    try {
      const r = await $.process.run(['git', '--no-optional-locks', ...args],
        { cwd, timeoutMs: 2_000 })
      return r.exitCode === 0 ? r.stdout.trim() : null
    } catch {
      return null
    }
  })
}

/** The zone the runtime draws its clocks in, as the document records it. */
export function localZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null
  } catch {
    return null
  }
}

/** status_figures through `$`. */
export async function statusDoc($: $, places: Places): Promise<Dict> {
  const now = (await $.clock.now()) / 1000
  const path = await transcriptPath($, places)
  const { raw, payload } = await payloadOf($, path)
  let tr: Transcript = EMPTY_TRANSCRIPT
  let turns: Turn[] | null = null
  if (path && await fileSize($, path) !== null) {
    const records = await recordsOf($, path)
    const readings = await agentReadings($, path)
    const etas: AgentEta[] = []
    const agents: AgentRec[] = agentRecordsOf(readings, null, etas)
    // A tool call still running counts to now: this is a live session.
    tr = transcriptOf(records, agents, etas, now)
    turns = await turnsVia($, places, path, records, readings)
  }
  const prepared = await preparedVia($, places, raw, payload.session_id,
    payload.model_id || payload.model, now)
  const snap = seedLimitsSnapshot(baseLimits(prepared), prepared.reading)
  const calib = await calibrationVia($, places, snap, now)
  // Decision 1: the main thread's own tokens, sampled in memory.
  const tokens = tr.own_tok_up === null ? null
    : tr.own_tok_up + tr.own_tok_down
  const [kept, rate] = sessionRate(samples, tokens, now)
  samples = kept
  return statusFigures({ payload, transcript: tr, turns,
    git: await gitVia($, payload.current_dir), prepared, snap, calib, now,
    tz: localZone(), rate })
}

/** The session's turns as read_turns makes them from the transcript as it
 * stands, with the transcript's path; null with no transcript found.  No
 * settling wait: the receipt's stamp polls this until the newest prompt's
 * turn is billed. */
export async function turnsNow($: $, places: Places):
  Promise<{ path: string; turns: Turn[] } | null> {
  const path = await transcriptPath($, places)
  if (!path || await fileSize($, path) === null) return null
  const records = await recordsOf($, path)
  return { path, turns: await turnsVia($, places, path, records,
    await agentReadings($, path)) }
}

/** cost_figures through `$`, over turns turnsNow read.  `published` is the
 * band's last context window, as window_for reads the status line's. */
export async function costDoc($: $, places: Places, path: string,
  turns: Turn[], published: number): Promise<Dict> {
  const now = (await $.clock.now()) / 1000
  const { raw, payload } = await payloadOf($, path)
  const prepared = await preparedVia($, places, raw, payload.session_id,
    payload.model_id || payload.model, now)
  const snap = seedLimitsSnapshot(baseLimits(prepared), prepared.reading)
  const calib = await calibrationVia($, places, snap, now)
  return costFigures(turns, windowFor(turns, published), calib, snap,
    prepared, now, localZone())
}
