// The mod's edges: the two documents built from what it reads through
// `$`, the status document the band draws and the cost document the
// receipt is stamped from.
//
// The src/ ports are pure where the plan says (figures from records, spans
// from figures), and their Node edges live in src/*_node.ts, which the mod
// never imports.  The mod's versions of those are the modules beside this
// one: engine.ts (files, processes and where things are), transcripts.ts
// (the main transcript's folds and the agents'), usage.ts (the usage
// source and the credits), calibration.ts (the window costs) and
// configuration.ts (the configuration files).  What they read this hands
// to src/claude.ts's statusFigures and costFigures, which are the Python's
// status_figures and cost_figures past their reads.
//
// The reads keep what they have read in memory between documents, as the
// Python keeps its agent cache and cost cache on disk: a transcript is only
// ever appended to, so each document reads only the bytes past the last
// complete line it parsed before.
import type { EngineInterface } from 'claude-code'

import {
  agentRecordsOf, EMPTY_TRANSCRIPT, pyJoin, readPayload, transcriptFinish,
} from '../src/claude_records.ts'
import type {
  AgentEta, AgentRec, Payload, Transcript, Turn,
} from '../src/claude_records.ts'
import { drawnCredits } from '../src/credits.ts'
import { seedLimitsSnapshot } from '../src/claude_calib.ts'
import {
  baseLimits, costFigures, detectGit, sessionRate, statusFigures, windowFor,
} from '../src/claude.ts'
import type { RateSample } from '../src/claude.ts'
import type { Dict } from '../src/py.ts'
import { log } from './log.ts'
import {
  fileSize, found, listDir, readRange, runVia, steps, timed,
} from './engine.ts'
import type { Places } from './engine.ts'
import { agentReadings, foldOf, turnsVia } from './transcripts.ts'
import { creditsVia, preparedVia } from './usage.ts'
import { calibrationVia } from './calibration.ts'
import { options } from './configuration.ts'

type $ = EngineInterface

/** What the session tells the mod that the status line's payload carries
 * and `$.session` does not, as handlers learn it: the model's effort, from
 * a turn's step. */
export type Seen = { effort: string }

export const seen: Seen = { effort: '' }
let samples: RateSample[] = []

// ════════════════════════════════════════════════════════════════════════════
// The documents.
// ════════════════════════════════════════════════════════════════════════════

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

/** The transcript's path: the file named for the session's id in one of
 * the projects directory's folders, '' where there is none.  The path is
 * kept for that id, and looked for again once the id moves on or the file
 * is gone from there: a session that leaves a worktree has its transcript
 * moved to the main checkout's folder. */
export async function transcriptPath($: $, places: Places):
  Promise<string> {
  const id = await $.session.id()
  let moved = ''
  if (found.path && found.session === id) {
    if (await fileSize($, found.path) !== null) return found.path
    moved = found.path
    found.path = ''
  }
  for (const p of await listDir($, places.projectsDir)) {
    if (p.kind !== 'dir') continue
    const path = pyJoin(pyJoin(places.projectsDir, p.name), id + '.jsonl')
    if (await fileSize($, path) !== null) {
      found.session = id
      found.path = path
      if (moved) await log($, 'transcript moved: ' + moved + ' -> ' + path)
      return path
    }
  }
  if (moved) await log($, 'transcript moved: ' + moved + ' -> none')
  return ''
}

/** The permission mode the transcript's newest record names, from its
 * last MODE_TAIL bytes: each prompt's record carries `permissionMode`.
 * undefined where none of them names one. */
export async function permissionModeOf($: $, path: string):
  Promise<string | undefined> {
  const size = await fileSize($, path)
  if (!size) return undefined
  const bytes = await readRange($, path, Math.max(0, size - MODE_TAIL), size)
  const text = new TextDecoder().decode(bytes)
  const all = [...text.matchAll(/"permissionMode":"(\w+)"/g)]
  return all.length ? all[all.length - 1][1] : undefined
}

// How far back from the transcript's end permissionModeOf looks.
const MODE_TAIL = 256 * 1024

/** detect_git through `$.process.run`, in the session's directory. */
async function gitVia($: $, cwd: string) {
  return detectGit(async (args) => {
    try {
      const r = await runVia($, ['git', '--no-optional-locks', ...args],
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
  for (const k of Object.keys(steps)) delete steps[k]
  const now = (await $.clock.now()) / 1000
  const path = await transcriptPath($, places)
  const { raw, payload } = await payloadOf($, path)
  let tr: Transcript = EMPTY_TRANSCRIPT
  let turns: Turn[] | null = null
  const fold = path ? await timed($, 'records', () => foldOf($, path)) : null
  if (path && fold) {
    const readings = await timed($, 'agents', () => agentReadings($, path))
    const etas: AgentEta[] = []
    const agents: AgentRec[] = agentRecordsOf(readings, null, etas)
    // A tool call still running counts to now: this is a live session.
    tr = await timed($, 'sum', async () =>
      transcriptFinish(fold.tr, agents, etas, now))
    turns = await timed($, 'turns', () =>
      turnsVia($, places, path, fold.tu, readings))
  }
  const prepared = await timed($, 'usage', () => preparedVia($, places, raw,
    payload.session_id, payload.model_id || payload.model, now))
  const o = options()
  const credits = o === null ? {} : await timed($, 'credits', () =>
    creditsVia($, places, now, o.account, o.credits.command))
  const snap = seedLimitsSnapshot(baseLimits(prepared), prepared.reading)
  const calib = await timed($, 'calib', () =>
    calibrationVia($, places, snap, now))
  // Decision 1: the main thread's own tokens, sampled in memory.
  const tokens = tr.own_tok_up === null ? null
    : tr.own_tok_up + tr.own_tok_down
  const [kept, rate] = sessionRate(samples, tokens, now)
  samples = kept
  const doc = statusFigures({ payload, transcript: tr, turns,
    git: await timed($, 'git', () => gitVia($, payload.current_dir)),
    prepared, snap, calib, now,
    tz: localZone(), rate })
  // The mod's alone, and only when there are some: the credits the 💳
  // row draws, by the option.
  const drawn = o === null ? [] : drawnCredits(credits.credits, o.credits,
    now)
  return drawn.length ? { ...doc, credits: { drawn,
    original: o!.credits.original } } : doc
}

/** The session's turns as read_turns makes them from the transcript as it
 * stands, with the transcript's path; null with no transcript found.  No
 * settling wait: the receipt's stamp polls this until the newest prompt's
 * turn is billed. */
export async function turnsNow($: $, places: Places):
  Promise<{ path: string; turns: Turn[] } | null> {
  const path = await transcriptPath($, places)
  const fold = path ? await foldOf($, path) : null
  if (!path || !fold) return null
  return { path, turns: await turnsVia($, places, path, fold.tu,
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
