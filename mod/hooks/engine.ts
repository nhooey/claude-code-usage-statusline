// What the mod asks of the engine, and where things are.  Every file read,
// listing and process goes through the helpers here, which count what each
// one cost (`io`, by the part of the mod's work it served) and keep the
// last few files and ranges read, keyed by size and mtime.  The transcript
// the session writes (`found`) and each step's time (`steps`) live here
// too, since every other part of the mod's reading uses them.
//
// Module state, not objects that hold `$`: the engine follows `$` only into
// functions declared at the top of a file, so each read is one, and what
// it keeps lives in its module.  A reload starts it over, and reads on from
// what was saved to disk.
import type { EngineInterface } from 'claude-code'

import { pyJoin } from '../src/claude_records.ts'

type $ = EngineInterface

/** What `$.fs.read` hands back whole; a larger file is read in pieces. */
const FS_READ_MAX = 4 * 1024 * 1024
/** One piece of a larger file, read through `tail | head | base64`: its
 * base64 must fit the 4 MiB `$.process.run` keeps of stdout. */
const PIECE = 2 * 1024 * 1024

export const encoder = new TextEncoder()

// ════════════════════════════════════════════════════════════════════════════
// What the mod asks of the engine.
// ════════════════════════════════════════════════════════════════════════════

/** File reads, the bytes they gave, directory listings and processes. */
export type IoCounts = { reads: number; readBytes: number; lists: number;
  spawns: number }

const noCounts = (): IoCounts => ({ reads: 0, readBytes: 0, lists: 0,
  spawns: 0 })

/** Every file read, the bytes it gave, directory listing and process the
 * mod has asked the engine for since it loaded, counted where each is
 * asked, in all and by the part of the mod's work it served (partOf):
 * what a refresh's log line says it cost (register.tsx, ioSinceLast). */
export const io: IoCounts & { parts: Record<string, IoCounts> } =
  { ...noCounts(), parts: {} }

/** The part a path serves, from the path alone, so work running beside
 * other work is counted where it belongs: the session's transcript, a
 * subagent's files, another transcript (a calibration scan's), or the
 * state and configuration files. */
export function partOf(path: string): string {
  if (path.includes('/subagents/') || path.endsWith('/subagents')) {
    return 'agents'
  }
  if (found.path && path === found.path) return 'transcript'
  if (path.endsWith('.jsonl')) return 'scan'
  return 'files'
}

/** The part a process serves: by the transcript it reads, where its
 * arguments name one, else by the program. */
export function partOfRun(argv: readonly string[]): string {
  const file = argv.find((a) => a.endsWith('.jsonl'))
  if (file) return partOf(file)
  const program = argv[0].slice(argv[0].lastIndexOf('/') + 1)
  if (program === 'git') return 'git'
  if (program === 'defaults') return 'tracker'
  if (program === 'rm' || program === 'rmdir') return 'sweep'
  return 'files'
}

function count(part: string, f: (c: IoCounts) => void) {
  f(io)
  f(io.parts[part] ??= noCounts())
}

export function readTextVia($: $, path: string): Promise<string> {
  count(partOf(path), (c) => c.reads++)
  return $.fs.read(path).then((t) => {
    count(partOf(path), (c) => c.readBytes += t.length)
    return t
  })
}

export function readBytesVia($: $, path: string): Promise<{ base64: string }> {
  count(partOf(path), (c) => c.reads++)
  return $.fs.read(path, { as: 'bytes' }).then((got) => {
    count(partOf(path),
      (c) => c.readBytes += Math.floor(got.base64.length * 3 / 4))
    return got
  })
}

function listVia($: $, dir: string): ReturnType<$['fs']['list']> {
  count(dir.includes('/subagents') ? 'agents'
    : dir.includes('/projects') ? 'scan' : 'files', (c) => c.lists++)
  return $.fs.list(dir)
}

export function runVia($: $, ...args: Parameters<$['process']['run']>):
  ReturnType<$['process']['run']> {
  count(partOfRun(args[0]), (c) => c.spawns++)
  return $.process.run(...args)
}

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

/** The bytes readRange last read, under the file's size and mtime then:
 * whole files of FS_READ_MAX or less, and ranges of RANGE_KEPT_MAX or less
 * of larger ones, the newest WHOLE_KEPT and RANGES_KEPT of each.  A
 * refresh asks for the same transcript's tail several times, for its fold,
 * its fold's check digests and its permission mode, and an idle one asks
 * for bytes that have not changed; each ask read the whole file, or
 * started a shell for a large one. */
const wholeKept = new Map<string, { stamp: string; bytes: Uint8Array }>()
const rangesKept = new Map<string, Uint8Array>()
const WHOLE_KEPT = 4
const RANGES_KEPT = 16
const RANGE_KEPT_MAX = 1024 * 1024

/** `value` set under `key`, as the newest, and the oldest dropped past
 * `max`. */
function keep<V>(m: Map<string, V>, key: string, value: V, max: number) {
  m.delete(key)
  m.set(key, value)
  while (m.size > max) m.delete(m.keys().next().value as string)
}

/** The bytes of `path` from `start` to `end`, of a file `size` long (`end`
 * where it is read to its end).  A file `$.fs.read` takes whole is read so
 * and cut; a larger one, which it refuses, in pieces through the shell,
 * since `$.fs` reads no range.  Bytes read before under the size and
 * mtime the file has now are not read again. */
export async function readRange($: $, path: string, start: number,
  end: number, size: number = end): Promise<Uint8Array> {
  if (end <= start) return new Uint8Array(0)
  const st = await $.fs.stat(path).catch(() => null)
  const stamp = st ? st.size + ':' + st.mtimeMs : null
  if (size <= FS_READ_MAX) {
    const was = wholeKept.get(path)
    if (stamp !== null && was?.stamp === stamp) {
      return was.bytes.subarray(start, end)
    }
    const got = await readBytesVia($, path)
    const bytes = fromBase64(got.base64)
    if (stamp !== null) keep(wholeKept, path, { stamp, bytes }, WHOLE_KEPT)
    return bytes.subarray(start, end)
  }
  const key = [path, start, end, stamp].join('\0')
  const was = stamp !== null ? rangesKept.get(key) : undefined
  if (was) return was
  const got = await readPieces($, path, start, end)
  if (stamp !== null && end - start <= RANGE_KEPT_MAX) {
    keep(rangesKept, key, got, RANGES_KEPT)
  }
  return got
}

/** `path` from `start` to `end`, PIECE at a time, through the shell. */
async function readPieces($: $, path: string, start: number, end: number):
  Promise<Uint8Array> {
  const parts: Uint8Array[] = []
  steps.native = 'fromBase64' in Uint8Array ? 'yes' : 'no'
  for (let at = start; at < end;) {
    const want = Math.min(PIECE, end - at)
    const r = await timed($, 'shell', () => runVia($, ['/bin/sh', '-c',
      'tail -c +"$1" "$2" | head -c "$3" | base64', 'sh',
      String(at + 1), path, String(want)], { timeoutMs: 30_000 }))
    if (r.exitCode !== 0) throw new Error('could not read ' + path)
    steps.pieces = ((steps.pieces as number) || 0) + 1
    const piece = await timed($, 'decode', async () => fromBase64(r.stdout))
    if (!piece.length) break
    parts.push(piece)
    at += piece.length
  }
  return concat(parts)
}

export async function readText($: $, path: string): Promise<string | null> {
  try {
    return await readTextVia($, path)
  } catch {
    return null
  }
}

/** `$.fs.write`, false where it could not: a cache that will not write
 * is a miss next time. */
export async function writeText($: $, path: string, text: string): Promise<boolean> {
  try {
    await $.fs.write(path, text)
    return true
  } catch {
    return false
  }
}


// The transcript transcriptPath last found, and the session id it found
// it for: a /clear or a /resume in the same process moves the session on,
// and the transcript with it.
export const found = { session: '', path: '' }

/** How long each step of the last statusDoc took, in ms, in the order they
 * ran, with how many shell pieces its transcript read took and whether
 * the runtime decodes base64 natively: what a slow read's log line says,
 * so the cost of a first read after a reload can be found. */
export const steps: { [step: string]: number | string } = {}

/** `f`, its length added to `steps` under `name`. */
export async function timed<T>($: $, name: string, f: () => Promise<T>): Promise<T> {
  const began = await $.clock.now()
  try {
    return await f()
  } finally {
    steps[name] = ((steps[name] as number) || 0) +
      Math.round((await $.clock.now()) - began)
  }
}

// ════════════════════════════════════════════════════════════════════════════
// Directories.
// ════════════════════════════════════════════════════════════════════════════

/** How many paths one `rm` is handed. */
export const RM_AT_ONCE = 500

const AGENT_NAME = /^agent-[\s\S]*\.jsonl$/

export type Listed = { path: string; size: number; mtimeMs: number }

/** `$.fs.list`, or nothing where the directory will not list. */
export async function listDir($: $, dir: string) {
  try {
    return await listVia($, dir)
  } catch {
    return []
  }
}

/** Every agent transcript under `dir`, at any depth, hidden names skipped:
 * the walk agentFiles and projectFiles both make. */
export async function agentWalk($: $, dir: string, out: Listed[]): Promise<void> {
  for (const e of await listDir($, dir)) {
    if (e.name.startsWith('.')) continue
    const p = pyJoin(dir, e.name)
    if (e.kind === 'dir') await agentWalk($, p, out)
    else if (AGENT_NAME.test(e.name)) {
      out.push({ path: p, size: e.size, mtimeMs: e.mtimeMs })
    }
  }
}


// ════════════════════════════════════════════════════════════════════════════
// Where things are.
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
