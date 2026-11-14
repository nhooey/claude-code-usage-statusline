// The transcripts: the main transcript's two folds, kept between documents
// and saved to disk so a reload reads on from them, and each agent's file,
// folded the same way, with its label and its last reply.  A transcript is
// only ever appended to, so each document reads only the bytes past the
// last complete line folded before.
import type { EngineInterface } from 'claude-code'

import {
  _agentDir, _agentStatePath, _recordsOf, agentLabelOf, agentOffsetsOf,
  agentReadingOf, agentRecordsOf, cmpStr, foldAgentBytes, foldAgentRecord,
  newAgentFold, pyJoin, transcriptFoldWith, turnsFinish, turnsFoldWith,
} from '../src/claude_records.ts'
import type {
  AgentFold, AgentReading, Turn, TurnsFold,
} from '../src/claude_records.ts'
import {
  FOLD_CHECK_BYTES, FOLD_PART_BYTES, foldHeadOf, foldMain, foldOfSaved,
  foldWrites, HEAD_SLOTS, newMainFold, partName,
} from '../src/main_fold.ts'
import type { FoldMeta, MainFold, SaveMark } from '../src/main_fold.ts'
import {
  agentFoldText, FOLD_CHECK_BYTES as AGENT_CHECK_BYTES, foldCandidates,
  foldDir as agentFoldDir, slotNames, tailDigest,
} from '../src/agent_fold.ts'
import { statePath } from '../src/state.ts'
import {
  agentOfMeta, lastReply, repliesOfLines,
} from '../src/agent_message.ts'
import type { AgentLike } from '../src/agent_message.ts'
import { sha256Hex } from '../src/sha256.ts'
import type { Dict } from '../src/py.ts'
import { CONFIG } from './config.ts'
import { log } from './log.ts'
import {
  agentWalk, encoder, fileSize, listDir, placesOf, readRange, readText,
  RM_AT_ONCE, runVia, steps, timed,
} from './engine.ts'
import type { Listed, Places } from './engine.ts'

type $ = EngineInterface

/** An agent file's fold as this load keeps it: the file's size and mtime
 * it was read at, the fold, its reading, and the sequence number of the
 * last save of it (agent_fold.ts), which the next save goes after. */
type AgentKept = {
  stamp: string; fold: AgentFold; reading: AgentReading; seq: number
}

const agentKept = new Map<string, AgentKept>()
const agentLabels = new Map<string, [string, string]>()

// ════════════════════════════════════════════════════════════════════════════
// The transcripts.
// ════════════════════════════════════════════════════════════════════════════

/** The main transcript's two folds as they stand, kept between documents:
 * folded to the last complete line, with the bytes after it, since a live
 * transcript's last line can be half written, folded on a copy each time.
 * A reload reads on from the state saved under the contract
 * (src/main_fold.ts), else from the start; and the state is saved again at
 * most once per CONFIG.foldSaveMs.  A stretch of AGENT_LINES_MIN or more
 * past what is folded is folded by the worker (foldWorker) into the saved
 * state, which is then read back; where the worker cannot run, the mod
 * folds it itself, FOLD_PIECE at a time.  A file that shrank is folded
 * again from the start.  null where there is no file. */
export async function foldOf($: $, path: string): Promise<MainFold | null> {
  const size = await fileSize($, path)
  if (size === null) {
    folded.delete(path)
    return null
  }
  const { stateDir } = await placesOf($)
  if (!cutsDropped) {
    cutsDropped = true
    void dropCuts($, stateDir).catch(() => {})
  }
  const dir = mainFoldDir(stateDir, path)
  let got = folded.get(path)
  if (got && size < got.offset) got = undefined
  let ran = false
  if (!got) {
    // A reload: where the saved state is far behind, or there is none,
    // the worker brings it up first, so it is read once.
    if (size - await savedOffset($, dir, size) >= AGENT_LINES_MIN) {
      ran = await foldWorker($, path, dir, size)
    }
    got = await timed($, 'load', () => loadFold($, stateDir, path, size))
    folded.set(path, got)
  }
  if (!ran && size - got.offset >= AGENT_LINES_MIN && !foldWorkerFailed) {
    // Saved as it stands, for the worker to read on from, and read back.
    await saveMainFold($, stateDir, path, got, size, true)
    if (got.savedTo === got.offset && await foldWorker($, path, dir, size)) {
      const back = await timed($, 'load', () =>
        loadFold($, stateDir, path, size))
      if (back.offset >= got.offset) {
        got = back
        folded.set(path, got)
      } else {
        // What is saved is no longer what the mark says: started over.
        got.mark = null
      }
    }
  }
  // Whatever the worker left, a piece of FOLD_PIECE at a time: only where
  // it failed is that more than a megabyte, but then it can be the whole
  // transcript, and read in one piece a 157 MB transcript crashes the hooks
  // worker.
  let data: Uint8Array = new Uint8Array(0)
  let want = FOLD_PIECE
  try {
    for (;;) {
      const end = Math.min(size, got.offset + want)
      data = await readRange($, path, got.offset, end, size)
      if (end === size) break
      const nl = data.lastIndexOf(10)
      if (nl < 0) {
        // One line longer than a piece: the piece grows to hold it.
        want *= 2
        continue
      }
      await foldLines($, got, data.subarray(0, nl + 1))
      steps.foldPieces = ((steps.foldPieces as number) || 0) + 1
      want = FOLD_PIECE
    }
  } catch {
    await saveMainFold($, stateDir, path, got, size)
    return got.fold
  }
  const nl = data.lastIndexOf(10)
  if (nl >= 0) await foldLines($, got, data.subarray(0, nl + 1))
  await saveMainFold($, stateDir, path, got, size)
  const rest = data.subarray(nl + 1)
  if (!rest.length) return got.fold
  const tail = _recordsOf(rest)
  return { tr: transcriptFoldWith(got.fold.tr, tail),
    tu: turnsFoldWith(got.fold.tu, tail) }
}

/** The bytes foldOf reads past the worker at a time. */
const FOLD_PIECE = 8 * 1024 * 1024

/** `got`'s folds read on over `lines`, the whole lines from its offset. */
async function foldLines($: $, got: Folded, lines: Uint8Array):
  Promise<void> {
  const f = got.fold
  await timed($, 'fold', async () => {
    for (const r of _recordsOf(lines)) foldMain(f, r)
  })
  got.offset += lines.length
}

/** What foldOf keeps of a transcript: its folds to `offset`, a whole
 * line's end; the mark the last save left, null for none since the folds
 * were started over; when it was saved, and to where. */
type Folded = { fold: MainFold; offset: number; mark: SaveMark | null;
  savedAt: number; savedTo: number }

const folded = new Map<string, Folded>()
// Logged once a process: a head too big to save.
let headTooBig = false

/** Where a transcript's folds are saved: the contract's directory, with
 * the heads and parts inside. */
function mainFoldDir(stateDir: string, transcript: string): string {
  return statePath(stateDir, 'main-fold', transcript)
}

/** The check digests of `path`, `size` long, folded to `offset`, as
 * foldMeta takes them over the whole file. */
async function metaOf($: $, path: string, offset: number, size: number):
  Promise<FoldMeta> {
  const first = await readRange($, path, 0,
    Math.min(FOLD_CHECK_BYTES, offset), size)
  const tail = await readRange($, path,
    Math.max(0, offset - FOLD_CHECK_BYTES), offset, size)
  return { offset, first: sha256Hex(first), tail: sha256Hex(tail) }
}

/** The offset of the newest saved head within a file `size` long, 0 for
 * none: as far as a reload could read on from, unchecked. */
async function savedOffset($: $, dir: string, size: number):
  Promise<number> {
  let best = 0
  for (const slot of HEAD_SLOTS) {
    const h = foldHeadOf(await readText($, pyJoin(dir, slot)))
    if (h && h.meta.offset <= size) best = Math.max(best, h.meta.offset)
  }
  return best
}

let foldWorkerFailed = false

/** Bring the fold saved in `dir` up to `path`'s last whole line before
 * `end`, through scripts/agent_lines.py's fold mode: it loads the state,
 * folds the lines past it and saves it back as saveMainFold would, so
 * neither the transcript nor its records pass through the hooks worker or
 * the 4 MiB the engine keeps of a process's output.  False where Python
 * fails, logged once, and from then on, for foldOf to fold the bytes
 * itself: always so for a copy of mod/ on its own (a GitHub install, a dev
 * mod), which has no package beside it for the worker to import. */
async function foldWorker($: $, path: string, dir: string, end: number):
  Promise<boolean> {
  if (foldWorkerFailed) return false
  const r = await timed($, 'worker', () => runVia($, ['/usr/bin/env',
    'python3', $.plugin.root + '/scripts/agent_lines.py', 'fold', path,
    String(end), dir], { timeoutMs: CONFIG.agentLinesTimeoutMs }))
  if (r.exitCode !== 0) {
    foldWorkerFailed = true
    void log($, 'fold worker: python3 exited ' + r.exitCode + ', folding ' +
      'the bytes instead: ' + r.stderr.slice(-300))
    return false
  }
  steps.workerTo = Number(r.stdout.trim())
  return true
}

/** The folds a reload starts from: the newest saved head whose transcript
 * still holds what it was folded from and whose parts read whole; else
 * nothing folded. */
async function loadFold($: $, stateDir: string, path: string, size: number):
  Promise<Folded> {
  const dir = mainFoldDir(stateDir, path)
  const heads = []
  for (const slot of HEAD_SLOTS) {
    const h = foldHeadOf(await readText($, pyJoin(dir, slot)))
    if (h) heads.push(h)
  }
  heads.sort((a, b) => b.seq - a.seq)
  const now = await $.clock.now()
  for (const got of heads) {
    if (got.meta.offset > size) continue
    try {
      const meta = await metaOf($, path, got.meta.offset, size)
      if (meta.first !== got.meta.first || meta.tail !== got.meta.tail) {
        continue
      }
    } catch {
      continue
    }
    const parts: (string | null)[] = []
    for (let i = 0; i < got.counts.length; i++) {
      parts.push(await readText($, pyJoin(dir, partName(i))))
    }
    const back = await timed($, 'parse', async () => foldOfSaved(got, parts))
    if (back) {
      steps.saved = got.meta.offset
      return { fold: back.fold, offset: got.meta.offset, mark: back.mark,
        savedAt: now, savedTo: got.meta.offset }
    }
  }
  return { fold: newMainFold(), offset: 0, mark: null, savedAt: -Infinity,
    savedTo: 0 }
}

/** Save `got` under the contract, at most once per CONFIG.foldSaveMs (or
 * `now`) and only once it reaches further, in foldWrites' order: the
 * parts first, then the head, in the slot the one before it is not in.
 * $.fs.write truncates and then writes, so a save started over first
 * empties both heads: neither could then read a part it was not written
 * beside. */
async function saveMainFold($: $, stateDir: string, path: string,
  got: Folded, size: number, now?: boolean): Promise<void> {
  const at = await $.clock.now()
  if (got.offset <= got.savedTo ||
    (!now && at - got.savedAt < CONFIG.foldSaveMs)) {
    return
  }
  got.savedAt = at
  const dir = mainFoldDir(stateDir, path)
  try {
    const meta = await metaOf($, path, got.offset, size)
    const save = foldWrites(got.fold, meta, got.mark)
    if (!save) {
      if (!headTooBig) {
        headTooBig = true
        void log($, 'main fold not saved: its head is over ' +
          FOLD_PART_BYTES + ' bytes')
      }
      return
    }
    for (const [name, text] of save.writes) {
      await $.fs.write(pyJoin(dir, name), text)
    }
    got.mark = save.mark
    got.savedTo = got.offset
  } catch (err) {
    // Started over next time: a part may be half written.
    got.mark = null
    void log($, 'main fold not saved', err)
  }
}

/** Where the mod once saved each session's transcript cut down to its
 * records (20 MB for one session), which nothing reads now that the folds
 * are saved: a directory of digests, each holding a head and its parts. */
const CUTS_DIR = 'claude-main-cuts-mod'
const CUT_DIR_NAME = /^[0-9a-f]{32}$/
const CUT_FILE_NAME = /^(?:head\.json|part-\d+\.jsonl)$/
// Tried once a load.
let cutsDropped = false

/** CUTS_DIR removed from the state directory.  `$.fs` removes nothing, so
 * `rm` does, handed only the names a cut was saved under, and `rmdir`
 * then each directory, which leaves one that holds anything else. */
export async function dropCuts($: $, stateDir: string): Promise<void> {
  await dropOldDir($, pyJoin(stateDir, CUTS_DIR), CUT_DIR_NAME,
    CUT_FILE_NAME)
}

/** Where the mod once saved each agent file's fold, keyed by its version,
 * before spec/state.jsonc's agent-fold kind: a directory per session, a
 * file per agent, each named by a digest cut to 32 digits. */
const OLD_AGENT_FOLDS_DIR = 'claude-agent-folds-mod'
const OLD_AGENT_FOLD_NAME = /^[0-9a-f]{32}\.json$/
// Tried once a load.
let oldAgentFoldsDropped = false

/** `top`, a directory of directories, removed: in each directory whose
 * name `dirName` matches, the files whose names `fileName` matches, by
 * `rm`, then `rmdir` each directory and `top`, which leaves one that holds
 * anything else. */
async function dropOldDir($: $, top: string, dirName: RegExp,
  fileName: RegExp): Promise<void> {
  try {
    if ((await $.fs.stat(top)).kind !== 'dir') return
  } catch {
    return
  }
  const files: string[] = []
  const dirs: string[] = []
  for (const d of await listDir($, top)) {
    if (d.kind !== 'dir' || !dirName.test(d.name)) continue
    const dir = pyJoin(top, d.name)
    for (const f of await listDir($, dir)) {
      if (f.kind === 'file' && fileName.test(f.name)) {
        files.push(pyJoin(dir, f.name))
      }
    }
    dirs.push(dir)
  }
  for (let i = 0; i < files.length; i += RM_AT_ONCE) {
    await runVia($, ['/bin/rm', '-f', '--',
      ...files.slice(i, i + RM_AT_ONCE)], { timeoutMs: 15_000 })
  }
  await runVia($, ['/bin/rmdir', '--', ...dirs, top],
    { timeoutMs: 15_000 })
}

/** agentFiles through `$.fs.list`, sorted so the walk is stable. */
export async function agentFiles($: $, transcript: string):
  Promise<Listed[]> {
  const out: Listed[] = []
  const d = _agentDir(transcript)
  if (d) await agentWalk($, d, out)
  return out.sort((a, b) => cmpStr(a.path, b.path))
}

const META_NAME = /^agent-(.+)\.meta\.json$/

// Each meta file's agent, by its path, once read: Claude Code writes an
// agent's task there at its start and keeps it.  null for one that would
// not read.
const metas = new Map<string, AgentLike | null>()

/** The session's agents as its `subagents/` folder holds them, the
 * session's transcript being `transcript`: one for each meta file
 * (agentOfMeta), finished or not, each file read once per load. */
export async function folderAgents($: $, transcript: string):
  Promise<AgentLike[]> {
  const dir = _agentDir(transcript)
  if (!dir) return []
  const out: AgentLike[] = []
  for (const e of await listDir($, dir)) {
    const id = META_NAME.exec(e.name)?.[1]
    if (e.kind !== 'file' || !id) continue
    const path = pyJoin(dir, e.name)
    if (!metas.has(path)) {
      const text = await readText($, path)
      let meta: unknown = null
      try {
        meta = text === null ? null : JSON.parse(text)
      } catch {
        meta = null
      }
      metas.set(path, agentOfMeta(id, meta))
    }
    const agent = metas.get(path)
    if (agent) out.push(agent)
  }
  return out.sort((a, b) => cmpStr(a.id ?? '', b.id ?? ''))
}

/** The agent's last reply (lastReply) as the end of its transcript beside
 * its meta file holds it, the last REPLY_TAIL bytes of it; '' where it
 * will not read.  A reply is written last, so its end holds it. */
async function folderReply($: $, transcript: string, id: string):
  Promise<string> {
  const path = pyJoin(_agentDir(transcript), 'agent-' + id + '.jsonl')
  try {
    const size = await fileSize($, path)
    if (!size) return ''
    const kept = folderReplyKept.get(path)
    if (kept && kept.size === size) return kept.reply
    const from = Math.max(0, size - REPLY_TAIL)
    const tail = await readRange($, path, from, size, size)
    const reply = lastReply(repliesOfLines(new TextDecoder().decode(tail),
      from > 0))
    folderReplyKept.set(path, { size, reply })
    return reply
  } catch {
    return ''
  }
}

// Each agent transcript's last reply (folderReply), by its path, with the
// size it was read at: a finished agent's file no longer grows, so each
// message row's lookup reads it once per load, not once per message.
const folderReplyKept = new Map<string, { size: number; reply: string }>()

// How far back from an agent transcript's end folderReply looks.
const REPLY_TAIL = 256 * 1024

/** Each of `agents`, of the folder folderAgents read, with its last reply
 * (folderReply), AGENT_READS_AT_ONCE read at a time. */
export async function folderReplies($: $, transcript: string,
  agents: readonly AgentLike[]): Promise<[AgentLike, string][]> {
  const out = new Map<AgentLike, string>()
  await atOnce(agents, AGENT_READS_AT_ONCE, async (a) => {
    out.set(a, a.id ? await folderReply($, transcript, a.id) : '')
  })
  return agents.map((a) => [a, out.get(a)!])
}

/** Each agent file's reading, each read from where the last read of it
 * stopped: in this load, or saved by an earlier one (savedFold), so a
 * reload reads none of it again.  An agent's file is only ever appended
 * to, and reading each whole, 2.7 GB over one session's 231 agents, leaves
 * the mod dead in that session.  A file that shrank was
 * rewritten, and is read from its start. */
export async function agentReadings($: $, transcript: string):
  Promise<[string, AgentReading][]> {
  const files = await agentFiles($, transcript)
  const stamp = (f: { size: number; mtimeMs: number }) =>
    f.size + ':' + f.mtimeMs
  const stale = files.filter((f) => agentKept.get(f.path)?.stamp !== stamp(f))
  const { stateDir } = await placesOf($)
  if (!oldAgentFoldsDropped) {
    oldAgentFoldsDropped = true
    void dropOldDir($, pyJoin(stateDir, OLD_AGENT_FOLDS_DIR), CUT_DIR_NAME,
      OLD_AGENT_FOLD_NAME).catch(() => {})
  }
  const dir = agentFoldDir(stateDir, transcript)
  await atOnce(stale, AGENT_READS_AT_ONCE, async (f) => {
    const kept = agentKept.get(f.path)
    let [fold, seq] = kept ? [kept.fold, kept.seq]
      : await savedFold($, dir, f.path, f.size)
    if (fold.pos > f.size) fold = newAgentFold()
    const from = fold.pos
    let tail: string
    try {
      if (f.size - fold.pos >= AGENT_LINES_MIN) {
        await agentLines($, f.path, fold, f.size)
      }
      // From the check bytes before the fold on, so the digest a save
      // takes is in hand.
      const lo = Math.max(0, fold.pos - AGENT_CHECK_BYTES)
      const data = await readRange($, f.path, lo, f.size)
      foldAgentBytes(fold, data.subarray(fold.pos - lo))
      tail = tailDigest(data.subarray(
        Math.max(0, fold.pos - AGENT_CHECK_BYTES) - lo, fold.pos - lo))
    } catch {
      agentKept.delete(f.path)
      return
    }
    if (fold.pos > from) seq = await saveFold($, dir, f.path, fold, seq, tail)
    agentKept.set(f.path, { stamp: stamp(f), fold,
      reading: agentReadingOf(fold), seq })
  })
  const out: [string, AgentReading][] = []
  for (const f of files) {
    const got = agentKept.get(f.path)
    if (!got) continue
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

/** An appended stretch this long or longer is read through
 * scripts/agent_lines.py, cut down to what the fold reads; a shorter one
 * as its bytes. */
const AGENT_LINES_MIN = 1024 * 1024
/** How many agent files are read at once. */
const AGENT_READS_AT_ONCE = 4

/** `f` over each of `items`, `n` at a time. */
async function atOnce<T>(items: readonly T[], n: number,
  f: (item: T) => Promise<void>): Promise<void> {
  let next = 0
  const lane = async () => {
    while (next < items.length) await f(items[next++])
  }
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, lane))
}

let agentLinesFailed = false

/** Fold `path`'s whole lines from `fold.pos` to `end` into `fold`, through
 * scripts/agent_lines.py: its parsing is the process's time, which no
 * hook's budget counts and which leaves the hooks worker free to draw.
 * Where Python fails, logged once, the bytes are read instead. */
async function agentLines($: $, path: string, fold: AgentFold, end: number):
  Promise<void> {
  if (agentLinesFailed) return
  while (fold.pos < end) {
    const r = await timed($, 'lines', () => runVia($, ['/usr/bin/env',
      'python3', $.plugin.root + '/scripts/agent_lines.py', path,
      String(fold.pos), String(end)],
      { timeoutMs: CONFIG.agentLinesTimeoutMs }))
    if (r.exitCode !== 0 || r.isStdoutTruncated) {
      agentLinesFailed = true
      void log($, 'agent lines: python3 exited ' + r.exitCode + ', reading ' +
        'the bytes instead: ' + r.stderr.slice(-300))
      return
    }
    const lines = r.stdout.split('\n')
    const stop = Number(lines[0])
    await timed($, 'parse', async () => {
      for (const l of lines.slice(1)) {
        if (!l) continue
        const tab = l.indexOf('\t')
        let rec: unknown = null
        try {
          rec = JSON.parse(l.slice(tab + 1))
        } catch {
          // Skipped, as the line itself is.
        }
        foldAgentRecord(fold, Number(l.slice(0, tab)), rec)
      }
    })
    if (fold.pos !== stop) throw new Error('agent lines out of step: ' + path)
    steps.linePieces = ((steps.linePieces as number) || 0) + 1
    if (stop >= end || lines.length <= 2) return
  }
}

/** The check digest of agent file `path`, `size` long, at `pos`. */
async function agentTail($: $, path: string, pos: number, size: number):
  Promise<string> {
  return tailDigest(await readRange($, path,
    Math.max(0, pos - AGENT_CHECK_BYTES), pos, size))
}

/** The fold saved in `dir` for agent file `path`, `size` long, and its
 * sequence number, as agent_fold.fold_file reads it: from the newer slot
 * whose offset is within the file and whose check digest still matches,
 * else the other; else a new fold, and the highest sequence number either
 * slot holds. */
async function savedFold($: $, dir: string, path: string, size: number):
  Promise<[AgentFold, number]> {
  const { folds, newest } = foldCandidates(await Promise.all(
    slotNames(path).map((n) => readText($, pyJoin(dir, n)))))
  for (const [seq, tail, fold] of folds) {
    try {
      if (fold.pos <= size &&
        await agentTail($, path, fold.pos, size) === tail) {
        return [fold, seq]
      }
    } catch {
      // A file that will not read is read again from its start.
    }
  }
  return [newAgentFold(), newest]
}

// When each file's fold was last saved: a live agent's at most once per
// CONFIG.foldSaveMs, a reload reading on from there.
const foldSaved = new Map<string, number>()

/** `fold` of agent file `path`, with `tail` its check digest, saved to
 * the slot after the one `seq` went to, at most once per
 * CONFIG.foldSaveMs: the sequence number it was saved under, else `seq`.
 * `$.fs.write` can be read torn, which is why there are two slots: a
 * reader falls back to the other. */
async function saveFold($: $, dir: string, path: string, fold: AgentFold,
  seq: number, tail: string): Promise<number> {
  const now = await $.clock.now()
  if (now - (foldSaved.get(path) ?? -Infinity) < CONFIG.foldSaveMs) return seq
  foldSaved.set(path, now)
  try {
    await $.fs.write(pyJoin(dir, slotNames(path)[(seq + 1) % 2]),
      agentFoldText(fold, seq + 1, tail))
    return seq + 1
  } catch (err) {
    void log($, 'agent fold not saved', err)
    return seq
  }
}

/** Each agent file's fold as the last agentReadings left it, by the
 * file's path: the band's tree reads each agent's figures off it
 * (hooks/subagents.ts).  The folds are this module's; a reader must not
 * change them. */
export function agentFolds(paths: readonly string[]): Map<string, AgentFold> {
  const out = new Map<string, AgentFold>()
  for (const p of paths) {
    const got = agentKept.get(p)
    if (got) out.set(p, got.fold)
  }
  return out
}

// Each sidecar's JSON, by its path, once read: Claude Code writes it at
// the agent's start and keeps it.  null for one that would not read.
const sidecars = new Map<string, Dict | null>()

/** The `.meta.json` sidecar beside agent file `path`, as JSON, read once
 * per load; null where there is none or it will not parse.  One not there
 * yet is asked for again next time. */
export async function sidecarOf($: $, path: string): Promise<Dict | null> {
  const meta = path.slice(0, -'.jsonl'.length) + '.meta.json'
  if (sidecars.has(meta)) return sidecars.get(meta)!
  const text = await readText($, meta)
  if (text === null) return null
  let got: Dict | null = null
  try {
    const d: unknown = JSON.parse(text)
    got = d && typeof d === 'object' && !Array.isArray(d) ? d as Dict : null
  } catch {
    got = null
  }
  sidecars.set(meta, got)
  return got
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

/** read_turns' finish over the turns' fold, with the agents' readings and
 * the published offsets. */
export async function turnsVia($: $, places: Places, path: string, fold: TurnsFold,
  readings: [string, AgentReading][]): Promise<Turn[]> {
  const offsets = await agentOffsets($, path, places.stateDir)
  return turnsFinish(fold, (s) => agentRecordsOf(readings, s, null),
    offsets, new Map(), labelOf)
}
