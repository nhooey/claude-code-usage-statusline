// The usage band: the usage line's grid drawn in Claude Code's own screen.
//
// agents/plans/redesign.md has the design.  Three places are drawn:
//
//   AbovePrompt   the band, bandLines over the last status document, at the
//                 body's width plus the five columns the gutter takes, a
//                 blank row above it;
//   TurnDuration  the turn's closing line: the turn's receipt, blank until
//                 it is stamped;
//   UserMessage   under a prompt typed at the composer, its turn's tag.
//
// The band's 🎤 and 🎮 rows are live while a turn runs; once the turn has
// ended and Claude Code has written its records, the mod stamps them,
// frozen, as the receipt its closing line draws (stamp).
//
// The handlers do the reading (edges.ts) and file what they read: the
// status document in `$.state`, so a new one redraws the band, and each
// start line in `$.store`, so it outlives the module and a reload draws it
// again.  The drawings read only what was filed.  What a handler catches
// goes to the mod's log (log.ts), never to the engine.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderElement } from 'claude-code'

import type { FiguresDoc } from '../types'
import { settings } from '../src/formatting.ts'
import type { Env, Settings } from '../src/formatting.ts'
import type { Span } from '../src/spans.ts'
import type { Turn } from '../src/claude_records.ts'
import { bandLines, bandRows, footerRuler, footerTail, modeOfHint,
  workspaceOf }
  from '../src/band.ts'
import {
  newestBilled, receiptLines, receiptTurn, startLine, tagsHidden, turnKey,
  withEngineDuration,
} from '../src/receipt.ts'
import { sha256Hex } from '../src/sha256.ts'
import type { Dict } from '../src/py.ts'
import * as spec from '../src/spec.ts'
import { CONFIG } from './config.ts'
import { costDoc, permissionModeOf, placesOf, seen, statusDoc, steps,
  transcriptPath, turnsNow } from './edges.ts'
import type { Places } from './edges.ts'
import { log } from './log.ts'

type $ = EngineInterface

// Bumped by each load, so the timer an earlier load started stops.
const generation = atom({ plugin: 'usage-band', key: 'generation' } as const, 0)
const status = atom({ plugin: 'usage-band', key: 'status' } as const, null)
const rate = atom({ plugin: 'usage-band', key: 'rate' } as const, null)
const filed = atom({ plugin: 'usage-band', key: 'filed' } as const, 0)
const clockNow = atom({ plugin: 'usage-band', key: 'now' } as const, 0)
const held = atom({ plugin: 'usage-band', key: 'held' } as const, false)

/** The store's key for a start line: its prompt's text. */
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
// When the last read finished and how long it took, in ms, and whether a
// main-thread turn runs: the tick's pace.
let readAt = 0
let readMs = 0
let turnRunning = false
// When the last slow read's toast was shown, in ms.
let toastAt = 0

/** A read that took `ms`: logged, with each step's ms, and shown as a
 * toast at most once per slowToastMs, so a slow read is seen as it happens
 * (asked 2026-10-19: the mod times itself and warns when it is slow). */
async function slow($: $, ms: number): Promise<void> {
  const parts = Object.entries(steps).map(([k, v]) => `${k} ${v}`)
  const text = `slow read: ${Math.round(ms)}ms (${parts.join(', ')})`
  await log($, text)
  const now = await $.clock.now()
  if (now - toastAt >= CONFIG.slowToastMs) {
    toastAt = now
    $.ui.toast(text)
  }
}
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
      const began = await $.clock.now()
      try {
        doc = await statusDoc($, await placesFor($))
        readAt = await $.clock.now()
        readMs = readAt - began
        if (readMs > CONFIG.slowReadMs) await slow($, readMs)
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
      // The classic hook events that carry the mode were seen not to
      // reach the mod (2026-10-20), so it is read off the transcript.
      try {
        const places = await placesFor($)
        noteMode($, 'transcript', await permissionModeOf($,
          await transcriptPath($, places)))
      } catch (err) {
        await log($, 'refresh: no permission mode', err)
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
  const spans = startLine(doc, CONFIG.hide)
  const text = pending.text
  pending = null
  if (spans.length) await remember($, 'starts', startKey(text), spans)
}

// Reads the figures again every tickMs while idle, and every
// tickRunningMs while a turn runs, spaced by readSpacing times the last
// read's length.  It looks each clockMs, so a turn that starts mid-wait
// gets the faster pace at once.
async function tick($: $, mine: number) {
  while ((await read($, generation)) === mine) {
    await $.clock.sleep(CONFIG.clockMs)
    if ((await read($, generation)) !== mine) return
    const pace = turnRunning
      ? Math.max(CONFIG.tickRunningMs, CONFIG.readSpacing * readMs)
      : CONFIG.tickMs
    if ((await $.clock.now()) - readAt >= pace) await refresh($)
  }
}

// Moves the time the band draws at every clockMs, so its clocks run
// between reads (decided 2026-10-19); the figures wait for the next read.
async function clock($: $, mine: number) {
  while ((await read($, generation)) === mine) {
    await $.clock.sleep(CONFIG.clockMs)
    if ((await read($, generation)) !== mine) return
    const now = (await $.clock.now()) / 1000
    await update($, clockNow, () => now)
  }
}

/** `doc` drawn at `now` where that is later than when it was read: its
 * figures as read, its clocks as they stand now. */
function at(doc: Dict, now: number): Dict {
  const clock = doc.clock as Dict | undefined
  const then = clock ? Number(clock.now) : NaN
  return clock && now > then ? { ...doc, clock: { ...clock, now } } : doc
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
    void clock($, mine).catch((err) => log($, 'clock stopped', err))
  } catch (err) {
    await log($, 'no tick', err)
  }
}

/** Keep `key` in the store under `index`, the newest last, dropping the
 * oldest past CONFIG.startsKept so the store stays small. */
async function remember($: $, index: string, key: string, value: unknown) {
  await $.store.set(key, value)
  const keys = ((await $.store.get(index)) as string[] | undefined) ?? []
  const kept = [...keys.filter((k) => k !== key), key]
  for (const old of kept.splice(0, Math.max(0,
    kept.length - CONFIG.startsKept))) {
    await $.store.delete(old)
  }
  await $.store.set(index, kept)
  await update($, filed, (n) => n + 1)
}

// The width the band last drew at, the terminal's: the receipt is laid out
// at it, so its columns are the band's.  0 until the band has drawn.
let bandCols = 0
// The footer's hint and widths last logged.
let hintSeen = ''
// The session's permission mode, as the last classic hook event gave it:
// the footer's `hint` leaves its pill out, so footerTail counts it apart.
let permissionMode: string | undefined
// The mode the footer's hint last named, which outranks the transcript's.
let hintMode: string | undefined

// The events seen carrying no mode, logged once each.
const modeless = new Set<string>()

/** Records the permission mode an event carries, logging each change, and
 * each kind of event that carries none, once. */
function noteMode($: $, from: string, mode: string | undefined): void {
  if (mode === undefined && !modeless.has(from)) {
    modeless.add(from)
    void log($, 'no permission mode on ' + from)
  }
  if (mode === undefined || mode === permissionMode) return
  permissionMode = mode
  void log($, 'permission mode ' + mode + ' from ' + from)
}

/** The store's key for a stamped receipt: its session and its turn. */
export const receiptKey = (session: string, turn: string) =>
  'receipt:' + sha256Hex(session + '\0' + turn).slice(0, 32)

// The receipts being stamped, so two turn.completes over one turn stamp it
// once even before the first has filed its key.
const stamping = new Set<string>()

/** The store's key for the receipt a closing line draws: the turn's
 * duration, which the line is drawn with and turn.complete carries. */
const receiptAt = (durationMs: number) => 'receipt-at:' + durationMs

/** Stamps the receipt of the turn that opened with `prompt` (its id, ""
 * for any) into the transcript.  Claude Code writes a turn's assistant
 * records only after its Stop hooks have run, after turn.complete, so the
 * transcript is read every CONFIG.receiptPollMs until the newest prompt's
 * turn is billed and two reads agree on what it billed, for up to
 * CONFIG.receiptWaitMs.  Then the cost document, the receipt's two lines,
 * filed for the closing line to draw.  Each turn is stamped once (receiptKey); one
 * whose records never land is logged, and nothing stamped. */
async function stamp($: $, durationMs: number, prompt: string):
  Promise<void> {
  const where = await placesFor($)
  const deadline = (await $.clock.now()) + CONFIG.receiptWaitMs
  let got: { path: string; turns: Turn[] } | null = null
  let last = ''
  for (;;) {
    got = await turnsNow($, where)
    const turns = got?.turns ?? []
    const billed = newestBilled(turns) && (!prompt ||
      turns[receiptTurn(turns)].prompt_id === prompt)
    const key = billed ? turnKey(turns) : ''
    if (key && key === last) break
    const late = (await $.clock.now()) >= deadline
    if (late && key) break
    if (late) {
      const t = turns.at(-1)
      await log($, 'no receipt: the turn was not billed within ' +
        CONFIG.receiptWaitMs / 1000 + 's: ' + JSON.stringify(got ? [
          prompt.slice(0, 8), t ? [t.prompt_id.slice(0, 8), t.turn_index,
            t.calls, t.agent ?? null, t.compact ?? null] : null]
          : 'no transcript'))
      return
    }
    last = key
    await $.clock.sleep(CONFIG.receiptPollMs)
  }
  const key = receiptKey(await $.session.id(), turnKey(got!.turns))
  if (stamping.has(key) || await $.store.get(key) !== undefined) return
  stamping.add(key)
  try {
    const doc = await read($, status)
    const published = doc ? Number(doc.context_window) || 0 : 0
    const fig = withEngineDuration(await costDoc($, where, got!.path,
      got!.turns, published), durationMs)
    // 📦 🌿 from the band's last status document (decision 7).
    const ws = doc ? workspaceOf(doc as Dict, where.home) : null
    // 🤖 as the band drew it once the turn ended, from the same document.
    const st = await settingsOf($)
    const main = doc ? bandRows(st, doc as Dict,
      { home: where.home, rate: null, phase: 'done' }).main : null
    // Laid out as the band is, so the rows' columns are the band's.
    const lines = receiptLines(st, fig, bandCols || 80, CONFIG.hide, ws, true,
      main, CONFIG.stampUntil)
    await remember($, 'receipts', key, true)
    await remember($, 'receipts', receiptAt(durationMs), lines)
  } finally {
    stamping.delete(key)
  }
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
    noteMode($, 'UserPromptSubmit', e.permission_mode)
    await learn($, e).catch(() => {})
    return next(e)
  })
  on('classic.Stop', async ($, e, next) => {
    noteMode($, 'Stop', e.permission_mode)
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

  // The permission mode, from the events that carry it: a prompt and a
  // turn's end, above, and each tool call, so a mode cycled with shift+tab
  // is known by the next one.
  on('classic.PostToolUse', async ($, e, next) => {
    noteMode($, 'PostToolUse', e.permission_mode)
    return next(e)
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
    turnRunning = true
    await update($, held, () => false)
    const tr = (await read($, status))?.transcript as Dict | undefined
    pending = { text: e.text, before: tr?.prompt_id ?? '' }
    await refresh($)
    return result
  })

  // A turn ends: the band again, its 🎤 row now the turn just done, and
  // the receipt stamped once the transcript bills the turn.  The stamp is
  // not awaited: it waits on Claude Code's own write, which comes after
  // this event, for longer than a handler's budget, whose clock runs on
  // through a sleep; it goes on after the handler returns, as the tick
  // does.  The refresh reads the prompt the turn opened with, which the
  // stamp bills and no later one.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    await start($, 'turn.complete')
    if (!e.agentId) {
      turnRunning = false
      // The band keeps the turn's 🎤 and 🎮 until its receipt is stamped,
      // and a second more, so the two lines are never missing from both
      // (asked 2026-10-19).
      await update($, held, () => true)
    }
    await refresh($)
    if (e.agentId) return result
    const tr = (await read($, status))?.transcript as Dict | undefined
    const prompt = typeof tr?.prompt_id === 'string' ? tr.prompt_id : ''
    void stamp($, e.durationMs, prompt)
      .catch((err) => log($, 'no receipt', err))
      .finally(async () => {
        await $.clock.sleep(CONFIG.receiptHoldMs)
        await update($, held, () => false)
      })
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const doc = await read($, status)
    if (e.props.hasSurvey || doc === null) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    bandCols = e.props.bodyColumns + 5
    // At no indent, as the receipt's rows are (asked 2026-10-19).
    const lines = bandLines(await settingsOf($),
      at(doc as Dict, await read($, clockNow)), bandCols, CONFIG.hide,
      { home: await home($), rate: await read($, rate),
        phase: e.props.isWorking || await read($, held) ? 'running' : 'done',
        stampUntil: CONFIG.stampUntil })
    // Between turns the receipt carries the rows, and the band has none.
    if (!lines.length) return next(e)
    // No margin: Claude Code draws its `[-]` on the band's first row, and
    // on a blank top row it stood alone.  A bottom margin of -1, into the
    // blank row above the prompt's border, hid the band's last row under
    // the border instead (tried live 2026-10-19).
    return (
      <Box flexDirection="column">
        {lines.map((l, i) => line(Text, l, 'band' + i))}
      </Box>
    )
  })

  // Claude Code's closing line, `✻ <word> for <duration>`, drawn as the
  // turn's receipt: 🔺🔖 its tag beside 🎤, then 📅 🕐 beside 🎮, dim, on
  // the band's columns, once stamped (decided 2026-10-19: a `$.ui.log` line came with
  // Claude Code's `⏺ usage-band:` before it and a blank row after).  Until
  // then one blank row: a Box one row high around a space, rather than an
  // empty Text, which Ink measures as no row at all.
  on('ui.render', { component: 'TurnDuration' }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    await read($, filed)
    const got = (await $.store.get(receiptAt(e.props.durationMs))) as
      Span[][] | undefined
    if (got) {
      // A blank row above, so the receipt stands apart from the answer,
      // and one under its tag line (asked 2026-10-19), which goes with the
      // tag line under the hide path `name.tag`.
      return (
        <Box flexDirection="column" marginTop={1}
          marginBottom={tagsHidden(CONFIG.hide) ? 0 : 1}>
          {got.map((l, i) => line(Text, l, 'receipt' + i))}
        </Box>
      )
    }
    return (
      <Box height={1}>
        <Text> </Text>
      </Box>
    )
  })

  // The footer under the prompt, `-- INSERT -- ⏵⏵ auto mode on …`, with
  // the 💳 row at its right end (decided 2026-10-19): a dim tail after
  // Claude Code's own line, which keeps its pills live (footerTail).
  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    // A change of mode draws the line first with the mode's words in it:
    // the mode as of now, which the transcript has only at the next record.
    hintMode = modeOfHint(e.props.hint) ?? hintMode
    const mode = hintMode ?? permissionMode
    const doc = await read($, status)
    if (doc === null) return next(e)
    const st = await settingsOf($)
    // The band's width before the viewport's: the viewport read 10 columns
    // wider than the terminal drew, pushing the 🕐 off the row (seen live
    // 2026-10-20), and the band's is where its rows end.
    const cols = bandCols || (e.viewport?.columns ?? 80)
    const text = footerTail(st, at(doc as Dict, await read($, clockNow)),
      CONFIG.hide, e.props.hint, cols, mode, await home($))
    const tail = CONFIG.footerRuler && text ? footerRuler(st, text, cols)
      : text
    // What the padding was worked out from, each time it changes, so a
    // tail drawn too wide can be checked against the line it was given.
    const seen = JSON.stringify([e.props.hint, mode ?? null, bandCols,
      e.viewport?.columns ?? null, tail.length])
    if (seen !== hintSeen) {
      hintSeen = seen
      void log($, 'footer: ' + seen)
    }
    return tail ? next({ ...e, props: { ...e.props, tail } }) : next(e)
  })

  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const row = await next(e)
    if (e.props.origin.kind !== 'composer' || tagsHidden(CONFIG.hide)) {
      return row
    }
    await read($, filed)
    const tag = (await $.store.get(startKey(e.props.text))) as
      Span[] | undefined
    if (!tag) return row
    const { Box, Text } = $.ui.resolve(e)
    // On a line of its own under the prompt, at no indent, so its 🔻🔖
    // stacks with the receipt's 🔺🔖 line, also at none (decided
    // 2026-10-19; beside a short prompt it could not stack).
    return (
      <Box flexDirection="column">
        {row}
        {line(Text, tag, 'tag', true)}
      </Box>
    )
  })
}

