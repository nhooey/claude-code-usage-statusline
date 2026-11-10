// The mod's profiling, built in: what each refresh asked of the engine
// (its reads, their bytes, listings and processes, by the part of the
// mod's work each served) and how long the mod's own drawing took each
// minute, by component.  A refresh or a minute past CONFIG's thresholds is
// logged with them, so a heavy one says where its cost went.
import type { EngineInterface } from 'claude-code'

import { CONFIG } from './config.ts'
import type { IoCounts } from './engine.ts'
import { io } from './engine.ts'
import { log } from './log.ts'

type $ = EngineInterface

// The engine counts at the last refresh, so each refresh's line says what
// was asked since: its own reads, and what the work it started behind the
// last one asked, such as a calibration scan.
export type IoUsed = IoCounts & { parts: Record<string, IoCounts> }

const copyIo = (): IoUsed => ({ ...io, parts: Object.fromEntries(
  Object.entries(io.parts).map(([k, v]) => [k, { ...v }])) })

let ioAt = copyIo()

const minus = (a: IoCounts, b: IoCounts | undefined): IoCounts => ({
  reads: a.reads - (b?.reads ?? 0),
  readBytes: a.readBytes - (b?.readBytes ?? 0),
  lists: a.lists - (b?.lists ?? 0), spawns: a.spawns - (b?.spawns ?? 0) })

export function ioSinceLast(): IoUsed {
  const now = copyIo()
  const parts: Record<string, IoCounts> = {}
  for (const [k, v] of Object.entries(now.parts)) {
    const d = minus(v, ioAt.parts[k])
    if (d.reads || d.readBytes || d.lists || d.spawns) parts[k] = d
  }
  const used = { ...minus(now, ioAt), parts }
  ioAt = now
  return used
}

const countsText = (u: IoCounts): string =>
  `${u.reads} reads, ${(u.readBytes / 1048576).toFixed(1)} MiB, ` +
  `${u.lists} listings, ${u.spawns} processes`

/** The counts, then each part's, the costliest by bytes first: what a
 * heavy line names as the culprit. */
export function ioText(u: IoUsed): string {
  const parts = Object.entries(u.parts)
    .sort(([, a], [, b]) => b.readBytes - a.readBytes || b.spawns - a.spawns)
    .map(([k, v]) => `${k}: ${countsText(v)}`)
  return `since the last refresh: ${countsText(u)}` +
    (parts.length ? `; ${parts.join('; ')}` : '')
}

// ── The drawing, timed ──────────────────────────────────────────────────
// Each `ui.render` hook's own time, the engine's drawing beneath it (its
// `next`) left out, and how many times it ran, per component, since the
// last minute's note: what a "heavy drawing" line names.  Timed by the
// runtime's own clock, which costs no call to the engine.
const drawn = new Map<string, { draws: number; ms: number }>()
let drawnSince = 0

const nowMs = (): number =>
  typeof performance !== 'undefined' ? performance.now() : Date.now()

function noteDrawn(component: string, ms: number) {
  const d = drawn.get(component) ?? { draws: 0, ms: 0 }
  d.draws++
  d.ms += ms
  drawn.set(component, d)
}

/** One drawing being timed: where it began, and the time its hook spent
 * in the engine's drawing beneath it (`next`), which is left out. */
export type Draw = { component: string; at: number; inner: number }

export function drawStart(component: string): Draw {
  return { component, at: nowMs(), inner: 0 }
}

/** `f`, a call of the hook's `next`, its time kept out of the hook's. */
export async function drawNext<T>(d: Draw, f: () => T | Promise<T>): Promise<T> {
  const at = nowMs()
  try {
    return await f()
  } finally {
    d.inner += nowMs() - at
  }
}

export function drawEnd(d: Draw) {
  noteDrawn(d.component, nowMs() - d.at - d.inner)
}

/** Once a minute, from the clock: a "heavy drawing" line where the render
 * hooks took CONFIG.drawNoteMs or more of it, each component with its
 * draws and ms, the costliest first. */
export async function noteDrawing($: $, now: number): Promise<void> {
  if (!drawnSince) drawnSince = now
  if (now - drawnSince < 60_000) return
  const minutes = (now - drawnSince) / 60_000
  drawnSince = now
  const text = drawingNote([...drawn], minutes)
  drawn.clear()
  if (text !== null) await log($, text)
}

/** The "heavy drawing" line for `rows`, each component's draws and ms
 * over `minutes`, the costliest first; null below CONFIG.drawNoteMs a
 * minute. */
export function drawingNote(rows: [string, { draws: number; ms: number }][],
  minutes: number): string | null {
  const ms = rows.reduce((s, [, d]) => s + d.ms, 0)
  if (ms / minutes < CONFIG.drawNoteMs) return null
  return `heavy drawing: ${Math.round(ms)}ms in ${minutes.toFixed(1)} ` +
    'min (' + [...rows].sort(([, a], [, b]) => b.ms - a.ms).map(([k, d]) =>
      `${k} ${d.draws} draws ${Math.round(d.ms)}ms`).join(', ') + ')'
}
