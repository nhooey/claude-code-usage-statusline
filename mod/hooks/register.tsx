// The usage band: the usage line's grid drawn in Claude Code's own screen.
//
// agents/plans/redesign.md has the design.  Three places are drawn:
//
//   AbovePrompt   the band, bandLines over the last status document, at the
//                 body's width plus the five columns the gutter takes;
//   TurnDuration  the turn's closing line, `✻ <word> for <duration> · ` and
//                 the receipt's head, with the receipt's rows under it;
//   UserMessage   under a prompt typed at the composer, its turn's tag.
//
// The handlers do the reading (edges.ts) and file what they read: the
// status document in `$.state`, so a new one redraws the band, and each
// receipt and start line in `$.store`, so they outlive the module and a
// reload draws them again.  The drawings read only what was filed.  What
// a handler catches goes to the mod's log (log.ts), never to the engine.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderElement } from 'claude-code'

import type { FiguresDoc } from '../types'
import * as spec from '../src/spec.ts'
import { settings } from '../src/formatting.ts'
import type { Env, Settings } from '../src/formatting.ts'
import type { Span } from '../src/spans.ts'
import { bandLines, workspaceOf } from '../src/band.ts'
import {
  drawRows, receiptHead, receiptRows, startLine, withEngineDuration,
} from '../src/receipt.ts'
import type { Row } from '../src/grid.ts'
import { sha256Hex } from '../src/sha256.ts'
import type { Dict } from '../src/py.ts'
import { CONFIG } from './config.ts'
import { costDoc, placesOf, seen, statusDoc } from './edges.ts'
import type { Places } from './edges.ts'
import { log } from './log.ts'

type $ = EngineInterface

// Bumped by each load, so the timer an earlier load started stops.
const generation = atom({ plugin: 'usage-band', key: 'generation' } as const, 0)
const status = atom({ plugin: 'usage-band', key: 'status' } as const, null)
const rate = atom({ plugin: 'usage-band', key: 'rate' } as const, null)
const filed = atom({ plugin: 'usage-band', key: 'filed' } as const, 0)

/** What a receipt files: its head and its rows, undrawn, so the closing
 * line draws them at whatever width it is drawn at. */
export type Filed = { head: Span[]; rows: Row[] }

/** The store's keys: a receipt by its turn's duration, which is what the
 * closing line is handed, and a start line by its prompt's text. */
export const receiptKey = (durationMs: number) => 'receipt:' + durationMs
export const startKey = (text: string) =>
  'start:' + sha256Hex(text).slice(0, 32)

let places: Places | null = null
let st: Settings | null = null

async function placesFor($: $): Promise<Places> {
  places ??= await placesOf($)
  return places
}

async function settingsOf($: $): Promise<Settings> {
  if (st) return st
  const env: { [k: string]: string | undefined } = {}
  // The variables formatting.settings reads for the terminal's profile.
  env.TMUX = await $.env.get('TMUX')
  env.TERMINAL_EMULATOR = await $.env.get('TERMINAL_EMULATOR')
  env.TERM_PROGRAM = await $.env.get('TERM_PROGRAM')
  st = settings(env as Env, CONFIG.markSpacing, CONFIG.subscriptDecimals)
  return st
}

let refreshing: Promise<void> | null = null
let again = false
// The prompt a turn opened with, until the transcript holds its record:
// its text, which the start line is filed under, and the tag that stood
// before it, which the new one must differ from.
let pending: { text: string; before: unknown } | null = null

/** Reads the status document afresh; the write redraws the band.  One at
 * a time: a call while one runs asks for one more after it. */
async function refresh($: $): Promise<void> {
  if (refreshing) {
    again = true
    return refreshing
  }
  refreshing = (async () => {
    do {
      again = false
      let doc: Dict
      try {
        doc = await statusDoc($, await placesFor($))
      } catch (err) {
        // A read that failed leaves the last document up, and the next
        // event reads again.
        await log($, 'refresh: no status document', err)
        continue
      }
      try {
        await update($, status, () => doc as FiguresDoc)
        await update($, rate, () => (doc.rate as number | null) ?? null)
      } catch (err) {
        await log($, 'refresh: the band was not updated', err)
      }
      try {
        await fileStart($, doc)
      } catch (err) {
        await log($, 'refresh: no start line', err)
      }
    } while (again)
  })()
  try {
    await refreshing
  } finally {
    refreshing = null
  }
}

/** The start line, once a document shows the pending prompt's record:
 * filed under the prompt's text for its UserMessage to find. */
async function fileStart($: $, doc: Dict): Promise<void> {
  const tr = doc.transcript as Dict | undefined
  if (!pending || !tr?.prompt_id || tr.prompt_id === pending.before) return
  const spans = startLine(doc)
  const text = pending.text
  pending = null
  if (spans.length) await remember($, 'starts', startKey(text), spans)
}

// Reads the figures again every tick, so the clocks move while idle.
async function tick($: $, mine: number) {
  while ((await read($, generation)) === mine) {
    await $.clock.sleep(CONFIG.tickMs)
    if ((await read($, generation)) !== mine) return
    await refresh($)
  }
}

// Whether this load of the module has started its tick.
let started = false

/** Starts this load's tick, once, from whichever event comes first: the
 * engine sends session.start at a process's start and at a reload, but a
 * mod must not lean on its coming before a turn's events.  The log's line
 * says which load ran in which session, so a live test can tell a mod that
 * failed from one that was never loaded (a `claude --resume` without
 * `--plugin-dir`). */
async function start($: $, by: string): Promise<void> {
  if (started) return
  started = true
  try {
    const cwd = await $.session.cwd().catch(() => '?')
    await log($, `started by ${by} in ${cwd}`)
    const mine = (await read($, generation)) + 1
    await update($, generation, () => mine)
    void tick($, mine).catch((err) => log($, 'tick stopped', err))
  } catch (err) {
    await log($, 'no tick', err)
  }
}

/** Keep `key` in the store under `index`, the newest last, dropping the
 * oldest past CONFIG.receiptsKept so the store stays small. */
async function remember($: $, index: string, key: string, value: unknown) {
  await $.store.set(key, value)
  const keys = ((await $.store.get(index)) as string[] | undefined) ?? []
  const kept = [...keys.filter((k) => k !== key), key]
  for (const old of kept.splice(0, Math.max(0,
    kept.length - CONFIG.receiptsKept))) {
    await $.store.delete(old)
  }
  await $.store.set(index, kept)
  await update($, filed, (n) => n + 1)
}

/** A row of spans as Text: each span a nested Text in its own colour,
 * named in spec and drawn as its hex. */
function line(Text: any, spans: readonly Span[], key: string,
  dim = false): RenderElement {
  // Only the props a span sets: a Text's props are plain values, and an
  // undefined one is not.
  const style = (s: Span) => {
    const p: Record<string, string | boolean> = {}
    const named = spec as unknown as Record<string, string>
    if (s.colour) p.color = named[s.colour]
    if (s.bg) p.backgroundColor = named[s.bg]
    if (s.dim) p.dimColor = true
    if (s.bold) p.bold = true
    return p
  }
  const outer: Record<string, string | boolean> = { wrap: 'truncate-end' }
  if (dim) outer.dimColor = true
  return (
    <Text key={key} {...outer}>
      {spans.map((s, i) => (
        <Text key={key + '.' + i} {...style(s)}>{s.text}</Text>
      ))}
    </Text>
  )
}

/** A duration as Claude Code's closing line writes it: "5s", "4m 2s",
 * "1h 3m". */
export function duration(ms: number): string {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

/** The transcript's path, from a classic event's envelope, and the session
 * it is the one for. */
async function learn($: $, e: { transcript_path?: string;
  session_id?: string }) {
  if (e.transcript_path) {
    seen.transcript = e.transcript_path
    seen.session = e.session_id ?? ''
  }
}

async function home($: $): Promise<string> {
  return (await placesFor($)).home
}

export const register: Register = on => {
  // Where the transcript is: every classic event names it, when it comes
  // (transcriptPath says why it may not).  Only the envelope is read, and
  // nothing here can refuse the event.
  on('classic.SessionStart', async ($, e, next) => {
    await learn($, e).catch(() => {})
    return next(e)
  })
  on('classic.UserPromptSubmit', async ($, e, next) => {
    await learn($, e).catch(() => {})
    return next(e)
  })
  on('classic.Stop', async ($, e, next) => {
    await learn($, e).catch(() => {})
    return next(e)
  })

  // The main thread's effort, which the payload carries and `$.session`
  // does not: off each of its model requests.
  on('turn.step', async function* ($, e, next) {
    if (!e.agentId && e.effort !== undefined) {
      seen.effort = String(e.effort)
    }
    return yield* next(e)
  })

  // Each event below starts this load's tick if no event has yet (start).
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await start($, 'session.start')
    await refresh($)
    return result
  })

  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    await start($, 'tool.call')
    void refresh($).catch((err) => log($, 'refresh', err))
    return result
  })

  // A turn opens: the band again, and the start line for its prompt once
  // a document shows the prompt's record, this one or a later one.
  on('turn.start', async ($, e, next) => {
    const result = await next(e)
    await start($, 'turn.start')
    if (e.agentId) return result
    const tr = (await read($, status))?.transcript as Dict | undefined
    pending = { text: e.text, before: tr?.prompt_id ?? '' }
    await refresh($)
    return result
  })

  // A turn ends: the band again, and the receipt, filed under the turn's
  // duration for the closing line to find.  A subagent's turn has none.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await start($, 'turn.complete')
    // The receipt's 📦 🌿 come from a status document, so a turn that ends
    // before any was read waits for one; otherwise the band reads again
    // beside the receipt.
    if ((await read($, status)) === null) await refresh($)
    else void refresh($).catch((err) => log($, 'refresh', err))
    if (e.agentId) return result
    try {
      const where = await placesFor($)
      const last = await read($, status)
      const published = last ? Number(last.context_window) || 0 : 0
      const got = await costDoc($, where, published)
      const doc = got ? withEngineDuration(got as Dict, e.durationMs) : null
      if (doc) {
        // 📦 🌿 from the band's last status document (decision 7).
        const ws = last ? workspaceOf(last as Dict, where.home) : null
        const st = await settingsOf($)
        const { turn, session } = receiptRows(st, doc, ws)
        const value: Filed = { head: receiptHead(doc),
          rows: [...(turn ? [turn] : []), session] }
        await remember($, 'receipts', receiptKey(e.durationMs), value)
      } else {
        await log($, 'no receipt: no transcript found for this session')
      }
    } catch (err) {
      // No receipt: the engine's own closing line stands.
      await log($, 'no receipt', err)
    }
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const doc = await read($, status)
    if (e.props.hasSurvey || doc === null) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const lines = bandLines(await settingsOf($), doc as Dict,
      e.props.bodyColumns + 5, CONFIG.hide, { home: await home($),
        rate: await read($, rate),
        phase: e.props.isWorking ? 'running' : 'done' })
    return (
      <Box flexDirection="column">
        {lines.map((l, i) => line(Text, l, 'band' + i))}
      </Box>
    )
  })

  // Drawn whole rather than around next(e): the engine's line is a
  // full-width row, so text set beside it would land at the right edge.
  on('ui.render', { component: 'TurnDuration' }, async ($, e, next) => {
    await read($, filed)
    const got = (await $.store.get(receiptKey(e.props.durationMs))) as
      Filed | undefined
    if (!got) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const cols = e.viewport?.columns ?? 150
    const rows = drawRows(await settingsOf($), got.rows, cols, CONFIG.hide)
    const close: Span = { text: `✻ ${e.props.word} for ` +
      `${duration(e.props.durationMs)} · `, colour: null, dim: false,
    bold: false, bg: null }
    return (
      <Box flexDirection="column">
        {line(Text, [close, ...got.head], 'head', true)}
        {rows.map((l, i) => line(Text, l, 'row' + i))}
      </Box>
    )
  })

  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const row = await next(e)
    if (e.props.origin.kind !== 'composer') return row
    await read($, filed)
    const tag = (await $.store.get(startKey(e.props.text))) as
      Span[] | undefined
    if (!tag) return row
    const { Box, Text } = $.ui.resolve(e)
    const pad: Span = { text: '  ', colour: null, dim: true, bold: false,
      bg: null }
    return (
      <Box flexDirection="column">
        {row}
        {line(Text, [pad, ...tag], 'tag', true)}
      </Box>
    )
  })
}

