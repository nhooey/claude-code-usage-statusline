// The calibration: each plan window's cost, scanned from every project's
// transcripts and kept in the window-costs cache the Python shares, with
// the scan moved off the render and only changed files read again.
import type { EngineInterface } from 'claude-code'

import { pyJoin } from '../src/claude_records.ts'
import { statePath } from '../src/state.ts'
import {
  _calibCacheText, _calibrationCacheName, _calibrationOf, _idKey,
  _readingMoved, nextTicks, _pricedRecord, _windowCostsFiles, _windowCostsOf,
  _windowCostsText, _windowsKey, _windowStarts, CALIB_SWEEP_EVERY_S,
  CALIB_SWEPT, CALIB_TTL, COST_TAIL_BYTES, FOLD_DIR, OLD_COSTS_DONE,
  oldWindowCosts, staleCalibrations, staleFoldFiles,
} from '../src/claude_calib.ts'
import type {
  Calib, CostKept, Priced, Snapshot,
} from '../src/claude_calib.ts'
import { pyJsonLoads } from '../src/sources.ts'
import { sha256Hex } from '../src/sha256.ts'
import { isDict, pyGet } from '../src/py.ts'
import type { Dict } from '../src/py.ts'
import {
  agentWalk, fileSize, listDir, readRange, readTextVia, RM_AT_ONCE, runVia,
  writeText,
} from './engine.ts'
import type { Listed, Places } from './engine.ts'

type $ = EngineInterface

const costs = new Map<string, CostKept>()
let costsRead = false
/** Whether `costs` holds what the window-cost cache does not yet. */
let costsMoved = false
let scanning = false
/** When this load last swept the calibration caches, in Unix seconds. */
let swept = 0
/** Whether this load has looked for the old window-cost caches. */
let oldCostsChecked = false

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
  const path = pyJoin(places.stateDir, _calibrationCacheName(snap))
  let cached: Dict | null = null
  let fresh = false
  // The cache whatever its windows, and its age: what a scan's steps are
  // carried from.
  let prev: Dict | null = null
  let prevAge: number | null = null
  try {
    const st = await $.fs.stat(path)
    const d = pyJsonLoads(await readTextVia($, path))
    if (isDict(d)) {
      prev = d
      prevAge = now - st.mtimeMs / 1000
    }
    if (isDict(d) && (!('windows' in d) ||
        (d.windows === windows && 'sess_pct' in d))) {
      cached = d
      // A reading that moved since the scan is a step to note: due now.
      fresh = st.mtimeMs / 1000 > now - CALIB_TTL && !_readingMoved(snap, d)
    }
  } catch {
    // No scan for these windows yet.
  }
  if (now - swept > CALIB_SWEEP_EVERY_S) {
    swept = now
    void sweepCalibrationsVia($, places, now).catch(() => {})
  }
  if (!oldCostsChecked) {
    oldCostsChecked = true
    void removeOldCostsVia($, places).catch(() => {})
  }
  if (!fresh && !scanning && (ss !== null || ws !== null)) {
    scanning = true
    void scanWindows($, places, snap, windows, path, prev, prevAge)
      .catch(() => {})
      .finally(() => {
        scanning = false
      })
  }
  return _calibrationOf(snap, cached, null)
}

/** _sweep_calibrations through `$`: the calibration caches untouched for
 * CALIB_MAX_AGE_S, and the folds' directories none of whose files was
 * written for as long, removed at most once a day between this and the
 * Python, by the marker both stamp.  `$.fs` cannot remove a file, so `rm`
 * does, handed only names staleCalibrations and staleFoldFiles matched,
 * under the state directory, and `rmdir` then each fold directory, which
 * leaves one that holds anything else. */
async function sweepCalibrationsVia($: $, places: Places,
  now: number): Promise<void> {
  const marker = pyJoin(places.stateDir, CALIB_SWEPT)
  try {
    const st = await $.fs.stat(marker)
    if (now - st.mtimeMs / 1000 < CALIB_SWEEP_EVERY_S) return
  } catch {
    // Never swept.
  }
  if (!await writeText($, marker, '')) return
  const listed = await listDir($, places.stateDir)
  const stale = staleCalibrations(listed, now)
    .map((name) => pyJoin(places.stateDir, name))
  const dirs: string[] = []
  for (const e of listed) {
    if (e.kind !== 'dir' || !FOLD_DIR.test(e.name)) continue
    const dir = pyJoin(places.stateDir, e.name)
    const names = staleFoldFiles(await listDir($, dir), now)
    if (names === null) continue
    stale.push(...names.map((n) => pyJoin(dir, n)))
    dirs.push(dir)
  }
  for (let i = 0; i < stale.length; i += RM_AT_ONCE) {
    await runVia($, ['/bin/rm', '-f', '--',
      ...stale.slice(i, i + RM_AT_ONCE)], { timeoutMs: 15_000 })
  }
  if (dirs.length) {
    await runVia($, ['/bin/rmdir', '--', ...dirs], { timeoutMs: 15_000 })
  }
}

/** _remove_old_window_costs through `$`: the window-cost caches as they
 * were named before spec/state.jsonc's window-costs kind, removed once,
 * by the marker the Python writes too.  `rm` is handed only the names
 * oldWindowCosts matched, under the state directory. */
async function removeOldCostsVia($: $, places: Places): Promise<void> {
  const marker = pyJoin(places.stateDir, OLD_COSTS_DONE)
  if (await fileSize($, marker) !== null) return
  const old = oldWindowCosts(await listDir($, places.stateDir))
    .map((name) => pyJoin(places.stateDir, name))
  if (old.length) {
    const r = await runVia($, ['/bin/rm', '-f', '--', ...old],
      { timeoutMs: 15_000 })
    if (r.exitCode !== 0) return
  }
  await writeText($, marker, '')
}

/** A whole file written so no reader sees it torn: `$.fs.write` truncates
 * and then writes, and holds 4 MiB at most, so the text goes through the
 * shell's stdin to a temporary file beside `path`, renamed over it, as the
 * Python's os.replace does.  False where it could not be written. */
async function writeAtomicVia($: $, path: string, text: string):
  Promise<boolean> {
  try {
    const r = await runVia($, ['/bin/sh', '-c',
      'umask 077 && t="$1.$$" && cat > "$t" && mv -f -- "$t" "$1" ||' +
      ' { rm -f -- "$t"; exit 1; }', 'sh', path],
    { stdin: text, timeoutMs: 30_000 })
    return r.exitCode === 0
  } catch {
    return false
  }
}

/** _windowCosts through `$`, then the cache written as _writeCalibCache
 * writes it.  The files are listed with their mtimes first, so only the
 * ones _windowCostsOf would open are read. */
async function scanWindows($: $, places: Places, snap: Snapshot,
  windows: string, path: string, prev: Dict | null,
  prevAge: number | null): Promise<void> {
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
  const listed = new Map(files.map((f) => [f.path, f]))
  for (const p of wanted) recs.set(p, await pricedOf($, listed.get(p)!))
  const [sc, wc] = _windowCostsOf(ss, ws, paths,
    (p) => mtime.get(p) ?? null, (p) => recs.get(p) ?? [])
  await saveCosts($, places, new Set(wanted))
  const sp = pyGet(snap, 'session_pct'), wp = pyGet(snap, 'weekly_pct')
  await writeText($, path, _calibCacheText(windows, sc, wc, sp, wp,
    nextTicks(prev, windows, sc, wc, sp, wp, prevAge)))
}

/** The cost cache, once a load: each file's offset, the digest of the
 * bytes before it, and its priced records up to it, as _CostCache keeps
 * them, in the one file spec/state.jsonc's window-costs kind names, which
 * the Python reads and writes too.  Read in pieces past 4 MiB. */
async function readCosts($: $, places: Places): Promise<void> {
  if (costsRead) return
  costsRead = true
  const path = statePath(places.stateDir, 'window-costs')
  const st = await $.fs.stat(path).catch(() => null)
  if (st?.kind !== 'file') return
  let files: Record<string, CostKept> | null = null
  try {
    // ASCII, as both ports write it.
    files = _windowCostsFiles(new TextDecoder()
      .decode(await readRange($, path, 0, st.size)))
  } catch {
    // Unreadable: read everything.
  }
  if (files) costsWrittenAt = st.mtimeMs
  for (const [k, v] of Object.entries(files ?? {})) costs.set(k, v)
}

/** When the window-cost cache this load read was written, in ms; null
 * where it read none. */
let costsWrittenAt: number | null = null

/** The cost cache written back, keeping only the files this scan read:
 * the others have aged out of both windows. */
async function saveCosts($: $, places: Places,
  keep: ReadonlySet<string>): Promise<void> {
  // Nothing read on and nothing aged out: the file holds this already.
  if (!costsMoved && [...costs.keys()].every((k) => keep.has(k))) return
  costsMoved = false
  const files: Record<string, CostKept> = {}
  for (const [k, v] of costs) if (keep.has(k)) files[k] = v
  let text: string
  try {
    text = _windowCostsText(files)
  } catch {
    return
  }
  // Unwritable: the next load scans again.
  await writeAtomicVia($, statePath(places.stateDir, 'window-costs'), text)
}

/** What pricedOf gave for each file this load, under the size and mtime
 * the listing gave it at: a file listed again with both the same is not
 * read again, so a scan with nothing written costs a listing. */
const pricedKept = new Map<string, { stamp: string; out: Priced[] }>()

/** _CostCache.records through `$`: the file's priced records, read past
 * the offset kept for it when the bytes before it are unchanged.  One read
 * from COST_TAIL_BYTES before that offset gives both the digest checked
 * and the one kept, since `$.fs` reads no range: a file of FS_READ_MAX or
 * less is read whole whatever the range. */
async function pricedOf($: $, f: Listed): Promise<Priced[]> {
  const path = f.path
  const stamp = f.size + ':' + f.mtimeMs
  const was = pricedKept.get(path)
  if (was && was.stamp === stamp) return was.out
  const size = await fileSize($, path)
  if (size === null) return []
  let got = costs.get(path)
  if (got && got.off > size) got = undefined
  // Read to its end when the cache was written, and not written since:
  // nothing to check or read on, so a load's first scan reads no file
  // the cache already holds whole.
  if (got && got.off === size && costsWrittenAt !== null &&
      f.mtimeMs < costsWrittenAt) {
    pricedKept.set(path, { stamp, out: got.recs })
    return got.recs
  }
  let lo = got ? Math.max(0, got.off - COST_TAIL_BYTES) : 0
  let data: Uint8Array
  try {
    data = await readRange($, path, lo, size)
    if (got && sha256Hex(data.subarray(0, got.off - lo)) !== got.tail) {
      got = undefined
      if (lo > 0) data = await readRange($, path, lo = 0, size)
    }
  } catch {
    return got?.recs ?? []
  }
  let off = got?.off ?? 0, recs = got?.recs ?? []
  const seenIds = new Set(recs.map(([, k]) => _idKey(k)))
  const body = data.subarray(off - lo)
  const fresh: Priced[] = []
  let partial: Priced | null = null
  let s = 0
  for (;;) {
    const e = body.indexOf(10, s)
    if (e < 0) {
      if (s < body.length) partial = _pricedRecord(body.subarray(s))
      break
    }
    const rec = _pricedRecord(body.subarray(s, e + 1))
    s = e + 1
    if (rec === null) continue
    const key = _idKey(rec[1])
    if (seenIds.has(key)) continue
    seenIds.add(key)
    fresh.push(rec)
  }
  off += s
  recs = [...recs, ...fresh]
  const tail = sha256Hex(data.subarray(Math.max(0, off - COST_TAIL_BYTES) - lo,
    off - lo))
  costs.set(path, { off, tail, recs })
  costsMoved = true
  const out =partial !== null && !seenIds.has(_idKey(partial[1]))
    ? [...recs, partial] : recs
  pricedKept.set(path, { stamp, out })
  return out
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
