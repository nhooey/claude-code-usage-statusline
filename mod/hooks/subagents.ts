// The subagents the band's tree draws, read through `$`: each agent of
// `$.agent.list()` and each agent file of the session's `subagents/`
// folder whose last record is in the turn, with its sidecar, its fold
// (transcripts.ts, which agentReadings has just read on), the branch of a
// worktree it works in apart from the session's, and its latest progress
// update, off its transcript's tail.  src/subagent_tasks.ts works them out
// as the renderer's prepared tasks.  The document carries them as
// `agents`, with the main thread's own progress update.
import type { EngineInterface } from 'claude-code'

import { _agentDir, agentLabelId } from '../src/claude_records.ts'
import type { Transcript } from '../src/claude_records.ts'
import type { Calib, Snapshot } from '../src/claude_calib.ts'
import { ctxWindowFor } from '../src/claude.ts'
import { progressOf, treeTasks } from '../src/subagent_tasks.ts'
import type { AgentInput, ListedAgent } from '../src/subagent_tasks.ts'
import type { Dict } from '../src/py.ts'
import { agentsNow } from './senders.ts'
import { agentFiles, agentFolds, sidecarOf } from './transcripts.ts'
import { fileSize, readRange, readText } from './engine.ts'

type $ = EngineInterface

/** The document's `agents`: the tasks the tree draws and the main
 * thread's progress update, off `transcript`, the session's, whose folded
 * figures are `tr`; `cwd` is the session's directory, for the agents'
 * branches. */
export async function agentsDoc($: $, transcript: string, tr: Transcript,
  cwd: string, now: number, calib: Calib | null, snap: Snapshot | null):
  Promise<Dict> {
  const listed = (await agentsNow($)) as readonly ListedAgent[]
  const byId = new Map(listed.filter((a) => a.id).map((a) => [a.id, a]))
  const files = await agentFiles($, transcript)
  const folds = agentFolds(files.map((f) => f.path))
  const dir = _agentDir(transcript)
  const pathOf = new Map<string, string>()
  for (const f of files) pathOf.set(agentLabelId(f.path), f.path)
  // An agent the list has let go is drawn only where its file's last
  // record is in the turn, for `✅ N done`; a workflow's agents, which the
  // list never has, not at all.
  const ids = new Set(byId.keys())
  for (const [id, path] of pathOf) {
    const seen = folds.get(path)?.lastSeen ?? null
    if (!byId.has(id) && !path.slice(dir.length).includes('/workflows/') &&
      tr.turn_s && seen !== null && seen >= tr.turn_s) ids.add(id)
  }
  const sessionRoot = (await gitHead($, cwd))[0]
  const inputs: AgentInput[] = []
  for (const id of ids) {
    const path = pathOf.get(id) ?? ''
    const fold = path ? folds.get(path) ?? null : null
    const listedAgent = byId.get(id) ?? null
    const live = listedAgent !== null &&
      !['failed', 'killed'].includes(listedAgent.status ?? '')
    inputs.push({
      id, listed: listedAgent, fold,
      meta: path ? await sidecarOf($, path) : null,
      inbox: 0,
      branch: fold?.cwd ? await branchApart($, fold.cwd, sessionRoot) : '',
      // Drawn only for a thread that works or waits, which the tree
      // tells from its state; an agent the list has let go has ended.
      progress: path && live ? await progressAt($, path) : '',
    })
  }
  return {
    tasks: treeTasks(inputs, now, (m) => ctxWindowFor('', m), calib, snap),
    main_progress: tr.turn_s && !tr.idle_at
      ? await progressAt($, transcript) : '',
  }
}

/** Each transcript's progress update as last read: the offset its whole
 * lines were read to and the update; a file read again reads on from
 * there, PROGRESS_TAIL at most. */
const progressKept = new Map<string, { pos: number; text: string }>()

/** The most of a transcript's end read for its progress update. */
const PROGRESS_TAIL = 64 * 1024

/** The latest progress update of the transcript at `path` (progressOf),
 * read on from where the last read of it stopped; "" where there is none
 * or it will not read. */
async function progressAt($: $, path: string): Promise<string> {
  try {
    const size = await fileSize($, path)
    if (!size) return ''
    const kept = progressKept.get(path)
    if (kept && size < kept.pos) progressKept.delete(path)
    const was = progressKept.get(path) ?? { pos: 0, text: '' }
    if (was.pos === size) return was.text
    const from = Math.max(was.pos, size - PROGRESS_TAIL)
    const data = await readRange($, path, from, size, size)
    const whole = data.lastIndexOf(10) + 1
    const text = progressOf(new TextDecoder().decode(data.subarray(0, whole)),
      from > was.pos) || was.text
    progressKept.set(path, { pos: from + whole, text })
    return text
  } catch {
    return ''
  }
}

/** The branch an agent working in `cwd` is on, where that is another
 * checkout than the session's, whose root is `sessionRoot`: claude.py's
 * worktree_branch.  "" where the two share a checkout, or either is in
 * none. */
async function branchApart($: $, cwd: string, sessionRoot: string):
  Promise<string> {
  const [root, branch] = await gitHead($, cwd)
  return root && root !== sessionRoot ? branch : ''
}

/** `[root, branch]` of the git checkout holding `path`, off its files
 * alone, as claude.py's git_head reads them: a `.git` directory, or a
 * `gitdir:` file in a linked worktree, and HEAD beside it; a detached HEAD
 * is its commit's first seven digits.  `['', '']` outside a checkout. */
export async function gitHead($: $, path: string): Promise<[string, string]> {
  let d = path.replace(/\/+$/, '')
  while (d) {
    const dot = d + '/.git'
    const kind = await $.fs.stat(dot).then((s) => s.kind, () => null)
    let gitdir = ''
    if (kind === 'dir') gitdir = dot
    else if (kind === 'file') {
      const line = ((await readText($, dot)) ?? '').split('\n')[0].trim()
      if (!line.startsWith('gitdir:')) return ['', '']
      const to = line.slice('gitdir:'.length).trim()
      gitdir = to.startsWith('/') ? to : d + '/' + to
    } else {
      const up = d.slice(0, d.lastIndexOf('/'))
      d = up === d ? '' : up
      continue
    }
    const head = ((await readText($, gitdir + '/HEAD')) ?? '').split('\n')[0]
      .trim()
    if (!head) return ['', '']
    const ref = 'ref: refs/heads/'
    return [d, head.startsWith(ref) ? head.slice(ref.length) : head.slice(0, 7)]
  }
  return ['', '']
}
