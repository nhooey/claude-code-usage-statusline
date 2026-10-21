// The usage band: the usage line's grid drawn in Claude Code's own screen.
//
// agents/plans/_implemented/redesign.md has the design, and docs/layout.md
// what is drawn.  Three places are drawn:
//
//   AbovePrompt   the band, bandLines over the last status document, at the
//                 body's width plus the five columns the gutter takes, a
//                 blank row above it;
//   TurnDuration  the turn's closing line: the turn's receipt, blank until
//                 it is stamped;
//   UserMessage   under a prompt typed at the composer, its turn's tag;
//                 and a message another agent sent, folded, as that
//                 agent's task and the message's first line.
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
import { hexOf } from '../src/spans.ts'
import type { Span } from '../src/spans.ts'
import type { Turn } from '../src/claude_records.ts'
import { ROW_NAMES, accountLine, bandRows, bandScoped, footerRuler,
  footerTail, modeOfHint, workspaceOf }
  from '../src/band.ts'
import type { RowsLive } from '../src/band.ts'
import {
  billedNothing, newestBilled, receiptScoped, startLine, tagsHidden, turnKey,
  withEngineDuration,
} from '../src/receipt.ts'
import type { TurnEnd } from '../src/receipt.ts'
import type { Options } from '../src/options_spec.ts'
import { candidates, firstLine, lastReply, messageBlock, messageSpans, saidBy, soleSender,
  taskOf } from '../src/agent_message.ts'
import type { AgentLike, MessageLike } from '../src/agent_message.ts'
import { sha256Hex } from '../src/sha256.ts'
import type { Dict } from '../src/py.ts'
import { CONFIG } from './config.ts'
import { costDoc, folderAgents, folderReplies, options, permissionModeOf,
  placesOf, readConfig, seen, statusDoc, steps, transcriptPath, turnsNow }
  from './edges.ts'
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
// Bumped by each read of the configuration files that changes the
// options, so every drawing that reads it draws again with them.
const configured = atom({ plugin: 'usage-band', key: 'configured' } as const,
  0)

/** The store's key for a start line: its prompt's text. */
export const startKey = (text: string) =>
  'start:' + sha256Hex(text).slice(0, 32)

let places: Places | null = null
let st: Settings | null = null
// The options `st` was made under.
let stKey = ''

async function placesFor($: $): Promise<Places> {
  places ??= await placesOf($)
  return places
}

/** The settings the rows are drawn under, made again when the options
 * they take have changed. */
async function settingsOf($: $): Promise<Settings> {
  const o = options()
  // right-edge: derived from live-place, 2 under the footer line, where
  // there is no [-], and 5 above the prompt, where the band's [-] stands.
  const key = JSON.stringify([o.markSpacing, o.subscriptDecimals,
    o.rightEdge])
  if (st && key === stKey) return st
  const env: { [k: string]: string | undefined } = {}
  // The variables formatting.settings reads for the terminal's profile.
  env.TMUX = await $.env.get('TMUX')
  env.TERMINAL_EMULATOR = await $.env.get('TERMINAL_EMULATOR')
  env.TERM_PROGRAM = await $.env.get('TERM_PROGRAM')
  // And the ones it reads for the colour level Claude Code draws at, from
  // the same process environment Claude Code read it from
  // (spans.COLOUR_VARS).
  env.FORCE_COLOR = await $.env.get('FORCE_COLOR')
  env.NO_COLOR = await $.env.get('NO_COLOR')
  env.TERM = await $.env.get('TERM')
  env.COLORTERM = await $.env.get('COLORTERM')
  env.TERM_PROGRAM_VERSION = await $.env.get('TERM_PROGRAM_VERSION')
  env.CLAUDE_CODE_TMUX_TRUECOLOR = await $.env.get('CLAUDE_CODE_TMUX_TRUECOLOR')
  st = settings(env as Env, o.markSpacing, o.subscriptDecimals, o.rightEdge)
  stKey = key
  return st
}

/** When each of the band's rows is drawn, from the options' rows. */
function liveOf(o: Options): RowsLive {
  return { turn: o.rows.turn.live, agent: o.rows.agent.live,
    session: o.rows.session.live }
}

/** Whether the turn's tag lines are drawn, 🔻🔖 under the prompt and the
 * receipt's 🔺🔖: rows.tag.transcript, and not the hide path `name.tag`. */
function tagsShown(o: Options): boolean {
  return o.rows.tag.transcript && !tagsHidden(o.hide)
}

/** How far in the band's rows' container stands: hint-inset under the
 * footer line, none above the prompt. */
function insetOf(o: Options): number {
  return o.livePlace === 'footer' ? o.hintInset : 0
}

/** The configuration files read again where they have changed, or the
 * session's root has moved: a change draws everything again under the
 * new options, and reads the figures again, whose source or account may
 * be what changed. */
async function reconfigure($: $): Promise<void> {
  if (!await readConfig($)) return
  await update($, configured, (n) => n + 1)
  void refresh($).catch((err) => log($, 'refresh', err))
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
 * toast at most once per slowToastMs under the option slow-toast, so a slow
 * read is seen as it happens (asked 2026-10-19: the mod times itself and
 * warns when it is slow).  Off by default: the toast took the footer's
 * line, hiding the 💳 account at its right end (seen live 2026-10-20). */
async function slow($: $, ms: number): Promise<void> {
  const parts = Object.entries(steps).map(([k, v]) => `${k} ${v}`)
  const text = `slow read: ${Math.round(ms)}ms (${parts.join(', ')})`
  await log($, text)
  const now = await $.clock.now()
  if (options().slowToast && now - toastAt >= CONFIG.slowToastMs) {
    toastAt = now
    $.ui.toast(text)
  }
}
// The prompt a turn opened with, until the transcript holds its record:
// its text, which the start line is filed under, and the tag that stood
// before it, which the new one must differ from.
let pending: { text: string; before: unknown; filed?: string } | null =
  null
// The promptId the running turn opened with, once a document showed its
// record (fileStart); "" until then.  The receipt bills this turn: read
// after turn.complete instead, the newest prompt can be one written as the
// turn ended, a task notification's (seen live 2026-10-20).
let opened = ''

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
 * filed under the prompt's text for its UserMessage to find.  A record
 * with no turn index is filed and the prompt kept pending, so a later
 * record that has one files over it: a task notification queued while
 * idle is written just before the prompt that opens the turn, with no
 * turnPosition of its own, and the turn bills the prompt (seen live
 * 2026-10-21: the tag read `1f2a3772` with no #, and the receipt waited
 * on that id while the turn billed `abfeacea #366`). */
async function fileStart($: $, doc: Dict): Promise<void> {
  const tr = doc.transcript as Dict | undefined
  if (!pending || !tr?.prompt_id || tr.prompt_id === pending.before) return
  if (typeof tr.prompt_id !== 'string' || tr.prompt_id === pending.filed) {
    return
  }
  opened = tr.prompt_id
  // Filed whether or not the tag lines are drawn: the UserMessage that
  // draws it asks the options (tagsShown), so a change shows or hides it.
  const spans = startLine(doc)
  const text = pending.text
  if (tr.turn_index === null || tr.turn_index === undefined) {
    pending = { ...pending, filed: tr.prompt_id }
  } else {
    pending = null
  }
  if (spans.length) await remember($, 'starts', startKey(text), spans)
}

// Reads the figures again every tickMs while idle, and every
// tickRunningMs while a turn runs, spaced by readSpacing times the last
// read's length.  It looks each clockMs, so a turn that starts mid-wait
// gets the faster pace at once.  Every tickMs it looks at the
// configuration files too, a stat of each, and reads them again where one
// has changed or the session's root has moved (reconfigure): the engine
// has no file-watch event for a mod.
async function tick($: $, mine: number) {
  let configAt = await $.clock.now()
  while ((await read($, generation)) === mine) {
    await $.clock.sleep(CONFIG.clockMs)
    if ((await read($, generation)) !== mine) return
    const now = await $.clock.now()
    if (now - configAt >= CONFIG.tickMs) {
      configAt = now
      await reconfigure($).catch((err) => log($, 'config', err))
    }
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
    // The configuration files, at each load; until they are read the
    // options are the mod's settings and the defaults.
    void reconfigure($).catch((err) => log($, 'config', err))
    const mine = (await read($, generation)) + 1
    await update($, generation, () => mine)
    void tick($, mine).catch((err) => log($, 'tick stopped', err))
    void clock($, mine).catch((err) => log($, 'clock stopped', err))
  } catch (err) {
    await log($, 'no tick', err)
  }
}

/** Keep `key` in the store under `index`, the newest last, dropping the
 * oldest past the option starts-kept so the store stays small. */
async function remember($: $, index: string, key: string, value: unknown) {
  await $.store.set(key, value)
  const keys = ((await $.store.get(index)) as string[] | undefined) ?? []
  const kept = [...keys.filter((k) => k !== key), key]
  for (const old of kept.splice(0, Math.max(0,
    kept.length - options().startsKept))) {
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

/** A receipt as filed under receiptAt: its lines, each with its scope, and
 * `turn`, startKey of the prompt its turn opened with, so a press on its
 * 🎤 or 🤖 goes to that turn's prompt or reply and not the latest's.  A
 * receipt filed as bare lines draws with no row pressable. */
type FiledReceipt = { rows: { scope: string; spans: Span[] }[]; turn: string }

/** Stamps the receipt of the turn that opened with `prompt` (its id, ""
 * for any) into the transcript, its presses going to `turn`'s targets
 * (FiledReceipt).  Claude Code writes a turn's assistant
 * records only after its Stop hooks have run, after turn.complete, so the
 * transcript is read every CONFIG.receiptPollMs until the newest prompt's
 * turn is billed and two reads agree on what it billed, for up to
 * CONFIG.receiptWaitMs.  Then the cost document, the receipt's two lines,
 * filed for the closing line to draw.  Each turn is stamped once (receiptKey); one
 * whose records never land is logged, and nothing stamped.  One that billed
 * nothing, as `end` (how turn.complete says it ended) or the transcript
 * tells (billedNothing), is logged in a line as soon as that is known, and
 * nothing stamped. */
async function stamp($: $, durationMs: number, prompt: string, turn: string,
  end: TurnEnd | null = null): Promise<void> {
  const where = await placesFor($)
  const deadline = (await $.clock.now()) + CONFIG.receiptWaitMs
  let got: { path: string; turns: Turn[] } | null = null
  let last = ''
  for (;;) {
    got = await turnsNow($, where)
    const turns = got?.turns ?? []
    const billed = newestBilled(turns, prompt)
    const none = billed ? '' : billedNothing(turns, prompt, end)
    if (none) {
      await log($, 'no receipt: the turn billed nothing (' + none + '): ' +
        (prompt.slice(0, 8) || 'no prompt'))
      return
    }
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
    // Laid out as the band is, at its width, edge and inset, so the rows
    // stack on the band's: under the footer line, the band's rows are
    // hint-inset columns in, and so are the receipt's (asked 2026-10-20).
    // The rows whose rows.<row>.transcript is true, and the tag line
    // under rows.tag.transcript.
    const o = options()
    const stamped = ROW_NAMES.filter((r) => o.rows[r].transcript)
    const rows = receiptScoped(st, fig, bandCols || 80, o.hide, ws,
      true, main, stamped, insetOf(o), tagsShown(o))
    await remember($, 'receipts', key, true)
    await remember($, 'receipts', receiptAt(durationMs),
      { rows, turn } satisfies FiledReceipt)
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
  // The true set where Claude Code draws true colour: given the 256 set
  // there, chalk would draw it as given, and the softer true colours are
  // the ones chosen to be seen.  Given the true set at 256, chalk would
  // round it onto entries nobody chose (see spec/layout.jsonc).
  const truecolor = st?.truecolor ?? false
  const style = (s: Span) => {
    const p: Record<string, string | boolean> = {}
    if (s.colour) p.color = hexOf(s.colour, truecolor)
    if (s.bg) p.backgroundColor = hexOf(s.bg, truecolor)
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

/** A row drawn as a Button around its Text, pressable by a click or Enter
 * under the focus, and looking as the row did: `plain`, so no `[ ]`
 * chrome, and no hotkey (agents/plans/_implemented/clickable-rows.md). */
function pressable(Button: any, Text: any, spans: readonly Span[],
  key: string, onPress: () => Promise<void>): RenderElement {
  return (
    <Button key={key} plain onPress={() => onPress()}>
      {line(Text, spans, key + '.text')}
    </Button>
  )
}

// The composer prompts' render instances, by startKey of the prompt's
// text: the `requestId` each UserMessage draw saw, so a press on 🎤 can
// scroll to it.  The oldest dropped past starts-kept, as the start
// lines are.  A module variable: a render hook may not write state.
const promptIds = new Map<string, string>()
// startKey of the prompt the last main-thread turn opened with: whose
// row 🎤 stands for.
let turnPrompt = ''

function notePrompt(text: string, requestId: string): void {
  const key = startKey(text)
  if (promptIds.get(key) === requestId) return
  promptIds.delete(key)
  promptIds.set(key, requestId)
  while (promptIds.size > options().startsKept) {
    promptIds.delete(promptIds.keys().next().value!)
  }
}

/** startKey of the prompt the band's 🎤 and 🤖 stand for: the last
 * main-thread turn's, or where no turn has opened since the module loaded,
 * the prompt drawn last. */
const bandTurn = () => turnPrompt || ([...promptIds.keys()].pop() ?? '')

// The main thread's replies, by startKey of the prompt their turn opened
// with: the `requestId` of the reply block drawn last while that turn ran,
// so a press on 🤖 can scroll to it.  A block counts the first time it is
// drawn, and only from the turn's start until its receipt is stamped (or
// given up on): one drawn again (a scroll, a resize) or between turns (a
// reload drawing the transcript back) says nothing of which turn it
// ended.  The render envelope names no agent, so a block of an agent's
// transcript first drawn in the main view while a main turn runs would be
// taken for the turn's.  Bounded as promptIds is.
const replyIds = new Map<string, string>()
// startKey of the turn whose replies are being drawn, "" between turns.
let repliesTurn = ''
// The reply blocks drawn since the load, so a second drawing is known; the
// oldest dropped past repliesKept.
const repliesSeen = new Set<string>()
const repliesKept = 2000

function noteReply(requestId: string): void {
  if (repliesSeen.has(requestId)) return
  repliesSeen.add(requestId)
  if (repliesSeen.size > repliesKept) {
    repliesSeen.delete(repliesSeen.values().next().value!)
  }
  if (!repliesTurn) return
  replyIds.delete(repliesTurn)
  replyIds.set(repliesTurn, requestId)
  while (replyIds.size > options().startsKept) {
    replyIds.delete(replyIds.keys().next().value!)
  }
}

// The presses that found no target, by row and turn: each said once.
const missed = new Set<string>()

/** A press on 🎤 (`what` the prompt) or 🤖 (the reply) of the turn that
 * opened with `turn`: its target, `requestId`, scrolled to the top of the
 * transcript's window.  With none recorded, never drawn since the load or
 * dropped past starts-kept, it says so in the log once per row and turn
 * and does nothing.  What it did and what came back goes to the log, so a
 * live click can be read back. */
async function pressTo($: $, row: '🎤' | '🤖', what: string, turn: string,
  requestId: string | undefined): Promise<void> {
  if (!requestId) {
    const seen = row + turn
    if (missed.has(seen)) return
    if (missed.size > repliesKept) missed.clear()
    missed.add(seen)
    await log($, `press ${row}: no ${what} drawn to scroll to`)
    return
  }
  const args = { to: { requestId }, block: 'start' } as const
  const call = '$.ui.scroll(' + JSON.stringify(args) + ')'
  try {
    await log($, `press ${row}: ${call} -> ` +
      JSON.stringify(await $.ui.scroll(args)))
  } catch (err) {
    await log($, `press ${row}: ${call} threw`, err)
  }
}

/** A press on 🎤 of the turn that opened with `turn`: its prompt. */
const pressTurn = ($: $, turn: string) =>
  pressTo($, '🎤', 'prompt', turn, promptIds.get(turn))

/** A press on 🤖 of the turn that opened with `turn`: its last reply. */
const pressReply = ($: $, turn: string) =>
  pressTo($, '🤖', 'reply', turn, replyIds.get(turn))

/** A row of the band's or a receipt's, of `scope`, for the turn `turn()`
 * names as a press comes: 🎤 and 🤖 pressable, to that turn's prompt and
 * reply (docs/layout.md, "Pressing a row"), the rest plain. */
function scopedRow($: $, Button: any, Text: any, scope: string,
  spans: readonly Span[], key: string, turn: () => string): RenderElement {
  if (scope === 'turn') {
    return pressable(Button, Text, spans, key, () => pressTurn($, turn()))
  }
  if (scope === 'main') {
    return pressable(Button, Text, spans, key, () => pressReply($, turn()))
  }
  return line(Text, spans, key)
}


/** The band's rows as they stand, at bandCols, each with its scope: of 🎤,
 * 🤖 and 🎮, those rows.<row>.live draws while a turn runs, and those it
 * keeps once it ends; none without a status document.  `inset` is how far
 * in from the terminal's left edge the container they are drawn in
 * starts. */
async function bandNow($: $, isWorking: boolean, inset = 0):
  Promise<{ scope: string; spans: Span[] }[]> {
  const doc = await read($, status)
  if (doc === null) return []
  const o = options()
  // At no indent, as the receipt's rows are (asked 2026-10-19).
  return bandScoped(await settingsOf($),
    at(doc as Dict, await read($, clockNow)), bandCols || 80, o.hide,
    { home: await home($), rate: await read($, rate),
      phase: isWorking || await read($, held) ? 'running' : 'done',
      live: liveOf(o), inset })
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

// The session's agents as `$.agent.list()` last gave them, and when, in
// ms; 0 for never, or for a list an agent's start or end has made stale.
// A module variable, not `$.state`: a render hook may not write state, and
// the row that reads it is drawn afresh with each draw of the transcript.
let agentList: readonly AgentLike[] = []
let agentListAt = 0
let agentListing: Promise<readonly AgentLike[]> | null = null

/** The session's agents, listed again only once CONFIG.agentListMs has
 * passed since the last list, or an agent started or ended since: a
 * message row is drawn on every draw, and one list stands for them all.
 * Draws that come while a list is out wait on that one.  A list that
 * fails is logged and counts as none, so the row names the sender as
 * Claude Code did. */
async function agentsNow($: $): Promise<readonly AgentLike[]> {
  const now = await $.clock.now()
  if (agentListAt && now - agentListAt < CONFIG.agentListMs) return agentList
  agentListing ??= (async () => {
    try {
      agentList = await $.agent.list()
    } catch (err) {
      await log($, 'no agent list', err)
      agentList = []
    }
    agentListAt = await $.clock.now()
    return agentList
  })().finally(() => {
    agentListing = null
  })
  return agentListing
}

/** An agent has started or ended: the next message row lists them again,
 * and a message no reply held is looked for again, in case its sender is
 * the agent just come or its reply the one just written. */
function agentsChanged(): void {
  agentListAt = 0
  for (const [text, agent] of senders) {
    if (!agent) senders.delete(text)
  }
}

// The sender of each message its words have been looked for by, keyed by
// its text, null where no one reply held it; the oldest dropped past
// CONFIG.agentSenderMemo.  A module variable, as the agent list is.  A
// message never changes, so a sender once found is its sender for good.
const senders = new Map<string, AgentLike | null>()
// The lookups out, so draws that come while one is out wait on it.
const sending = new Map<string, Promise<AgentLike | null>>()

// The senders found, as the store keeps them for a reload, which starts
// `senders` over: a finished agent may be gone from the list and its
// reply from the folder's tail by then.  Under SENDERS_KEY, each keyed by
// keptKey, the oldest dropped past CONFIG.agentSenderMemo.  A sender not
// found is not kept, so a later load may find it.  `$.store`, not
// `$.state`: a render hook may not write state.
const SENDERS_KEY = 'agent-senders'
let kept: Promise<Record<string, AgentLike>> | null = null

/** The store's key for the sender of `text` in session `session`. */
const keptKey = (session: string, text: string) =>
  sha256Hex(session + '\n' + text).slice(0, 32)

/** The senders the store keeps, read once per load; none where it will
 * not read. */
function keptSenders($: $): Promise<Record<string, AgentLike>> {
  kept ??= $.store.get(SENDERS_KEY).then(
    (got) => got && typeof got === 'object'
      ? { ...got as Record<string, AgentLike> } : {},
    async (err) => {
      await log($, 'no kept senders', err)
      return {}
    })
  return kept
}

/** Keep `agent` as the sender under `key`, for a reload to find; only what
 * the row reads of it. */
async function keepSender($: $, key: string, agent: AgentLike) {
  const all = await keptSenders($)
  delete all[key]
  all[key] = { id: agent.id, type: agent.type,
    description: agent.description, status: agent.status,
    ...agent.name !== undefined ? { name: agent.name } : {} }
  const keys = Object.keys(all)
  for (const old of keys.slice(0, Math.max(0,
    keys.length - CONFIG.agentSenderMemo))) {
    delete all[old]
  }
  await $.store.set(SENDERS_KEY, all)
    .catch((err) => log($, 'sender not kept', err))
}

/** The one agent of the session's `subagents/` folder named or typed
 * `from` whose last reply there holds `head` (edges.ts folderAgents,
 * folderReplies); null where none or several do.  For a sender gone from
 * the agent list: an agent finished a while, or one the list did not
 * settle. */
async function folderSender($: $, from: string, head: string):
  Promise<AgentLike | null> {
  if (!head) return null
  const path = await transcriptPath($, await placesFor($))
  if (!path) return null
  const among = (await folderAgents($, path))
    .filter((a) => a.name === from || a.type === from)
  return saidBy(head, await folderReplies($, path, among))
}

/** The sender of `text` as `from` by the words of its message, kept under
 * `key` where found: the one of `agents` whose conversation's last reply
 * holds its first line, else folderSender's. */
async function lookFor($: $, from: string, text: string,
  agents: readonly AgentLike[], key: string): Promise<AgentLike | null> {
  const among = candidates(from, agents).filter((a) => a.id)
  const replies = await Promise.all(among.map(async (a) => {
    try {
      const got = await $.session.messages({ agentId: a.id! })
      return [a, Array.isArray(got)
        ? lastReply(got as readonly MessageLike[]) : ''] as const
    } catch (err) {
      await log($, 'no messages for ' + a.id, err)
      return [a, ''] as const
    }
  }))
  const head = firstLine(text)
  const found = saidBy(head, replies) ??
    await folderSender($, from, head).catch(async (err) => {
      await log($, 'no folder sender', err)
      return null
    })
  if (found) await keepSender($, key, found)
  return found
}

/** The agent that sent `text` as `from`: the one agent of that name or
 * type, with no read; else the one a load before this one found, as the
 * store keeps it; else the one of them whose last reply holds the
 * message's first line (agent_message.ts), each candidate's conversation
 * read once per message; else the one of the session's `subagents/`
 * folder whose reply there holds it (folderSender); null where none finds
 * one.  A read that fails is logged and counts as no reply. */
async function senderOf($: $, from: string, text: string,
  agents: readonly AgentLike[]): Promise<AgentLike | null> {
  const sole = soleSender(from, agents)
  if (sole) return sole
  if (senders.has(text)) return senders.get(text)!
  let lookup = sending.get(text)
  if (!lookup) {
    lookup = (async () => {
      const key = keptKey(await $.session.id().catch(() => ''), text)
      const found = (await keptSenders($))[key] ??
        await lookFor($, from, text, agents, key)
      senders.set(text, found)
      while (senders.size > CONFIG.agentSenderMemo) {
        senders.delete(senders.keys().next().value!)
      }
      return found
    })().finally(() => {
      sending.delete(text)
    })
    sending.set(text, lookup)
  }
  return lookup
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
  // The reads are not awaited: a session with many agents read for 34s
  // after a reload (seen live 2026-10-20), its parsing the hook's own time,
  // past the engine's 10s budget for a hook.
  // A session's start may be in another project: its configuration files
  // are looked at again (reconfigure), as the tick looks at them.
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    // The terminal's variables are read again, the colour level's with
    // them: settingsOf otherwise keeps what it read until an option moves.
    st = null
    await start($, 'session.start')
    void reconfigure($).catch((err) => log($, 'config', err))
    void refresh($).catch((err) => log($, 'refresh', err))
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
    if (e.agentId) {
      agentsChanged()
      return result
    }
    turnRunning = true
    await update($, held, () => false)
    const tr = (await read($, status))?.transcript as Dict | undefined
    pending = { text: e.text, before: tr?.prompt_id ?? '' }
    opened = ''
    turnPrompt = startKey(e.text)
    repliesTurn = turnPrompt
    void refresh($).catch((err) => log($, 'refresh', err))
    return result
  })

  // A turn ends: the band again, its 🎤 row now the turn just done, and
  // the receipt stamped once the transcript bills the turn.  Neither the
  // read nor the stamp is awaited: the stamp waits on Claude Code's own write, which comes after
  // this event, for longer than a handler's budget, whose clock runs on
  // through a sleep; it goes on after the handler returns, as the tick
  // does.  The stamp bills the prompt the turn opened with and no later
  // one: as a document showed it while the turn ran, else as the refresh
  // reads it, for a turn too short for any read to have seen it.
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
    if (e.agentId) {
      agentsChanged()
      void refresh($).catch((err) => log($, 'refresh', err))
      return result
    }
    const seen = opened
    opened = ''
    // The turn its receipt's 🎤 and 🤖 press to, as the band's did.
    const turn = bandTurn()
    void (async () => {
      await refresh($)
      const tr = (await read($, status))?.transcript as Dict | undefined
      const prompt = seen ||
        (typeof tr?.prompt_id === 'string' ? tr.prompt_id : '')
      await stamp($, e.durationMs, prompt, turn,
        { reason: e.isAborted ? 'aborted' : e.reason,
          usage: e.usage !== undefined })
    })()
      .catch((err) => log($, 'no receipt', err))
      .finally(async () => {
        // Its last reply is drawn by the time its records are in the
        // transcript: a block first drawn after that is another's.
        if (repliesTurn === turn) repliesTurn = ''
        await $.clock.sleep(CONFIG.receiptHoldMs)
        await update($, held, () => false)
      })
    return result
  })

  // Each drawing below reads `configured`, so a change of the options
  // draws it again.

  // The band above the prompt, where live-place puts it there.  Its
  // width is taken either way: the footer and the receipt are laid out at
  // it.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    bandCols = e.props.bodyColumns + 5
    await read($, configured)
    if (options().livePlace !== 'above' || e.props.hasSurvey) return next(e)
    const lines = await bandNow($, e.props.isWorking)
    // Between turns the receipt carries the rows, and the band has none.
    if (!lines.length) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    // No margin: Claude Code draws its `[-]` on the band's first row, and
    // on a blank top row it stood alone.  A bottom margin of -1, into the
    // blank row above the prompt's border, hid the band's last row under
    // the border instead (tried live 2026-10-19).
    return (
      <Box flexDirection="column">
        {lines.map((l, i) => line(Text, l.spans, 'band' + i))}
      </Box>
    )
  })

  // Claude Code's closing line, `✻ <word> for <duration>`, drawn as the
  // turn's receipt: 🔺🔖 its tag beside 🎤, then 📅 🕐 beside 🎮, dim, on
  // the band's columns, once stamped (decided 2026-10-19: a `$.ui.log` line came with
  // Claude Code's `⏺ usage-band:` before it and a blank row after).  Until
  // then one blank row: a Box one row high around a space, rather than an
  // empty Text, which Ink measures as no row at all.
  //
  // Its 🎤 and 🤖 press to its own turn's prompt and last reply, which
  // the receipt was filed with (FiledReceipt), not the latest turn's.
  on('ui.render', { component: 'TurnDuration' }, async ($, e) => {
    const { Box, Button, Text } = $.ui.resolve(e)
    await read($, filed)
    await read($, configured)
    const got = (await $.store.get(receiptAt(e.props.durationMs))) as
      FiledReceipt | Span[][] | undefined
    const rows = Array.isArray(got)
      ? got.map((spans) => ({ scope: '', spans })) : got?.rows ?? []
    const turn = Array.isArray(got) ? '' : got?.turn ?? ''
    if (rows.length) {
      // A blank row above, so the receipt stands apart from the answer,
      // and one under its tag line (asked 2026-10-19), which goes with the
      // tag line (tagsShown).
      return (
        <Box flexDirection="column" marginTop={1}
          marginBottom={tagsShown(options()) ? 1 : 0}>
          {rows.map((l, i) => scopedRow($, Button, Text, l.scope, l.spans,
            'receipt' + i, () => turn))}
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
    // A change of mode draws the line first with the words of the mode it
    // turned off, so the one now on is known before the transcript has it.
    hintMode = modeOfHint(e.props.hint) ?? hintMode
    const mode = hintMode ?? permissionMode
    const doc = await read($, status)
    if (doc === null) return next(e)
    await read($, configured)
    const o = options()
    const st = await settingsOf($)
    // The band's width before the viewport's: the viewport read 10 columns
    // wider than the terminal drew, pushing the 🕐 off the row (seen live
    // 2026-10-20), and the band's is where its rows end.
    const cols = bandCols || (e.viewport?.columns ?? 80)
    const fig = at(doc as Dict, await read($, clockNow))
    // The 💳 account, where rows.account.live draws it now: "running"
    // while a turn runs, as the band's rows are.
    const live = o.rows.account.live
    const accounted = live === 'always' || (live === 'running' &&
      (e.props.isWorking || await read($, held)))
    const text = accounted && o.accountPlace === 'tail' ? footerTail(st, fig,
      o.hide, e.props.hint, cols, mode, await home($)) : ''
    const tail = o.footerRuler && text ? footerRuler(st, text, cols)
      : text
    // What the padding was worked out from, each time it changes, so a
    // tail drawn too wide can be checked against the line it was given.
    const seen = JSON.stringify([e.props.hint, mode ?? null, bandCols,
      e.viewport?.columns ?? null, tail.length])
    if (seen !== hintSeen) {
      hintSeen = seen
      void log($, 'footer: ' + seen)
    }
    const row = await (tail ? next({ ...e, props: { ...e.props, tail } })
      : next(e))
    // The 💳 account and the band's rows under the footer line, in their
    // colours: Claude Code's own line first, from next(e), so its pills
    // stay live, and a node beside it in a column goes on the row below it
    // (seen live 2026-10-20).  Claude Code draws the line's container
    // hint-inset columns in, so the rows are drawn that much narrower on
    // the panel's columns: drawn at the full width, each cell stood that
    // many columns right of the agent panel's, and the 💳 row ended past
    // the grid (seen live 2026-10-20).
    const inset = o.hintInset
    const account = accounted && o.accountPlace === 'row'
      ? accountLine(st, fig, o.hide, cols - inset, await home($)) : []
    const lines = [...account.length ? [{ scope: 'account', spans: account }]
      : [], ...o.livePlace === 'footer'
      ? await bandNow($, e.props.isWorking, inset) : []]
    if (!lines.length) return row
    const { Box, Button, Text } = $.ui.resolve(e)
    // 🎤 and 🤖 are pressable: they scroll to the prompt that opened the
    // turn and to its last reply (scopedRow).  A blank row parts them
    // from the footer line (asked 2026-10-21).
    return (
      <Box flexDirection="column" marginBottom={o.hintTuck ? -1 : 0}>
        {row}
        <Box height={1}><Text> </Text></Box>
        {lines.map((l, i) => scopedRow($, Button, Text, l.scope, l.spans,
          'band' + i, bandTurn))}
      </Box>
    )
  })

  // A reply block, drawn as Claude Code draws it: its instance noted for a
  // press on 🤖 to scroll to (noteReply).
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    noteReply(e.requestId)
    return next(e)
  })

  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const row = await next(e)
    if (e.props.origin.kind !== 'composer') return row
    // Its instance, for a press on 🎤 to scroll to (pressTurn).
    notePrompt(e.props.text, e.requestId)
    await read($, configured)
    if (!tagsShown(options())) return row
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

  // A message another agent sent, folded: Claude Code's `› Message from
  // @general-purpose (ctrl+o to expand)` drawn as the agent's task and the
  // message's first line, the task bold and the rest dim
  // (agent-message-row; agent_message.ts has how the agent is found,
  // senderOf what that reads).  A tree, not a rewritten `text`: folded,
  // Claude Code draws the sender's name and not the text, so a new text
  // would change nothing there.  The tree is the row's own look as far as
  // a tree can give it, one line led by `›`.  Unfolded (ctrl+o, or a
  // surface that draws every row in full), the same row over the whole
  // message, wrapped, on the same green (asked 2026-10-20: Claude Code's
  // own named the agent's type, in its own colour).  On every other row,
  // Claude Code's own.
  //
  // Not pressable: a click on the row is Claude Code's, which expands the
  // message and collapses it again, as on its own row.  A Button here took
  // that click (asked 2026-10-21), and no call a press can make toggles a
  // row (`isExpanded` is read-only), so the row is plain Text.
  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const from = e.props.from
    if (!from) return next(e)
    await read($, configured)
    if (!options().agentMessageRow) return next(e)
    const sender = await senderOf($, from.name, e.props.text,
      await agentsNow($))
    const label = taskOf(sender, from.name)
    // The band's width before the viewport's, as the footer takes it: the
    // viewport has read wider than the terminal drew (seen live
    // 2026-10-20).  Ending where the band's rows and the receipt's end,
    // right-edge short of the edge (asked 2026-10-20: it ran to the edge).
    // Should the row stand in from the edge, the Text's truncate-end cuts
    // what the ellipsis did not.
    const cols = (bandCols || (e.viewport?.columns ?? 80)) -
      options().rightEdge
    const st = await settingsOf($)
    const { Box, Text } = $.ui.resolve(e)
    if (e.props.isExpanded) {
      return (
        <Box flexDirection="column">
          {messageBlock(st, label, e.props.text, cols).map((l, i) =>
            line(Text, l, 'agentMessage' + i))}
        </Box>
      )
    }
    return line(Text, messageSpans(st, label, e.props.text, cols),
      'agentMessage')
  })
}

