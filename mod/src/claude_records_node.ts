// The Node edges of claude_records.ts: its readers that take a path.
//
// claude_records.ts is pure, so the mod, which runs with no Node, can
// import it and feed it what its own handlers read through `$`.  These are
// the same readers over node:fs, for the tests, the tools and anything
// else run by Node; each keeps its Python name, as the pure core does.
// Everything claude_records.ts exports is exported from here too, so a
// Node caller imports one module.
import * as fs from "node:fs";
import {
  _agentDir, _agentStatePath, _agentCachePath, _readAgentBytes, _recordsOf,
  AGENT_CACHE_SETTLE_S, agentLabelOf, agentOffsetsOf, agentRecordsOf, cmpStr,
  cmpTuple,
  INBOX_MARKS, inboxDelivery, markedRecordsOf, pyJoin, pyJsonDumps,
  queuedSend, recordEqual, SEND_QUEUED_MARK, transcriptOf, tsEpoch, turnsOf,
  _settled, SETTLE_POLL_S, SETTLE_S,
} from "./claude_records.ts";
import type {
  AgentCache, AgentEta, AgentReading, AgentRec, Rec, Transcript, Turn,
} from "./claude_records.ts";
import { isDict, pyGet, pyOr } from "./py.ts";

export * from "./claude_records.ts";

const AGENT_NAME = /^agent-.*\.jsonl$/s;

type Kept = AgentReading & { readonly stamp: readonly [number, string] };

/** Yield parsed JSONL records, skipping any line that will not parse.
 *
 * A transcript is appended to live, so the last line can be a partial
 * write.  Skipping is the only reasonable response; failing would blank the
 * row for whichever frame caught the file mid-append. */
export function _records(path: string): Rec[] {
  let data: Uint8Array;
  try {
    data = fs.readFileSync(path);
  } catch {
    return [];
  }
  return _recordsOf(data);
}

/** Every agent transcript of this session, sorted so the walk is stable.
 *
 * Two depths and no others, measured over 2,134 files on 2026-09-11:
 * `subagents/agent-<id>.jsonl` for the Agent tool, forks, and agents that
 * agents spawned; `subagents/workflows/wf_<id>/agent-<id>.jsonl` for a
 * workflow's agents.  The workflow's `journal.jsonl` carries no usage and
 * is not matched.  Walked as the Python's recursive glob walks: hidden
 * names are skipped, and a directory is entered through a symlink. */
export function agentFiles(transcript: string): string[] {
  const d = _agentDir(transcript);
  if (!d || !isDir(d)) return [];
  const out: string[] = [];
  const walk = (dir: string): void => {
    let names: string[];
    try {
      names = fs.readdirSync(dir);
    } catch {
      return;
    }
    for (const name of names) {
      if (name.startsWith(".")) continue;
      const p = pyJoin(dir, name);
      if (AGENT_NAME.test(name)) out.push(p);
      if (isDir(p)) walk(p);
    }
  };
  walk(d);
  return out.sort(cmpStr);
}

function isDir(p: string): boolean {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

/** agentRecordsOf over this session's agent files, read here; see
 * _agentFileReadings for `cache`. */
export function agentRecords(transcript: string,
  seen: Set<unknown> | null = null,
  etas: (readonly [number | null, number | null])[] | null = null,
  cache: AgentCache | null = null): AgentRec[] {
  return agentRecordsOf(_agentFileReadings(transcript, cache), seen, etas);
}

/** _readAgentBytes off the file, or null for a file that will not open. */
export function _readAgentFile(path: string): AgentReading | null {
  try {
    return _readAgentBytes(fs.readFileSync(path));
  } catch {
    return null;
  }
}

/** _readAgentFile for every agent file, in agentFiles' order, from the
 * cache where a file has not changed since it was kept.
 *
 * Without it, every render parsed every agent file the session ever ran: a
 * session with 611 of them, 768 MB, took six seconds a render.  A finished
 * agent's file never changes, so a render reads only the files that grew.
 * A reading is current while the file's size and mtime match the ones
 * stamped when it was read.  The cache is written back only when a reading
 * was added or a file went away.  With no `cache`, every file is read. */
export function _agentFileReadings(transcript: string,
  cache: AgentCache | null = null): [string, AgentReading][] {
  const paths = agentFiles(transcript);
  if (paths.length === 0) return [];
  const cpath = cache ? _agentCachePath(transcript, cache.stateDir) : "";
  let kept: Record<string, Kept> = {};
  if (cache) {
    try {
      const d = JSON.parse(fs.readFileSync(cpath, "utf-8"));
      if (isDict(d) && d.version === cache.version) {
        kept = (pyOr(d.files, {}) as Record<string, Kept>);
      }
    } catch {
      // No cache yet, or one that will not parse: read everything.
    }
  }
  const settled = cache ? cache.now - AGENT_CACHE_SETTLE_S : 0;
  const out: [string, AgentReading][] = [];
  const keep: Record<string, Kept> = {};
  let dirty = false;
  for (const path of paths) {
    let st: fs.BigIntStats;
    try {
      st = fs.statSync(path, { bigint: true });
    } catch {
      continue;
    }
    const stamp: [number, string] = [Number(st.size), String(st.mtimeNs)];
    let got: AgentReading | null = Object.hasOwn(kept, path)
      ? kept[path] : null;
    if (isDict(got) && recordEqual((got as unknown as Kept).stamp, stamp)) {
      const { recs, work, tools, waiting, eta } = got;
      got = { recs, work, tools, waiting, eta };
      keep[path] = kept[path];
    } else {
      // Stamped before the read: a file that grows during it comes back
      // with a newer stamp next time, and is read again.
      got = _readAgentFile(path);
      if (got === null) continue;
      if (cache && Number(st.mtimeNs) / 1e9 < settled) {
        keep[path] = { ...got, stamp };
        dirty = true;
      }
    }
    out.push([path, got]);
  }
  const same = (a: object, b: object) =>
    recordEqual(Object.keys(a).sort(), Object.keys(b).sort());
  if (cache && (dirty || !same(kept, keep))) {
    writeAtomic(cpath, JSON.stringify({ version: cache.version,
      files: keep }));
  }
  return out;
}

/** Write `text` to `path` through a temporary file renamed over it, private
 * to the user, as the Python does; a failure leaves the old file.  True
 * when it was written. */
export function writeAtomic(path: string, text: string): boolean {
  const tmp = `${path}.${process.pid}`;
  const slash = path.lastIndexOf("/");
  try {
    if (slash >= 0) {
      fs.mkdirSync(path.slice(0, slash) || "/",
        { recursive: true, mode: 0o700 });
    }
    fs.writeFileSync(tmp, text);
    fs.chmodSync(tmp, 0o600);
    fs.renameSync(tmp, path);
    return true;
  } catch {
    // Unwritable state is a slower next render, not a failure.
    return false;
  }
}

/** The byte offset the last Stop reported each agent file up to, or null
 * when no Stop has written one for this session.  See _foldAgents for what
 * the distinction buys.  A value must be an int, and Python's bool is one. */
export function agentOffsets(transcript: string,
  stateDir: string): Map<string, number> | null {
  try {
    return agentOffsetsOf(fs.readFileSync(
      _agentStatePath(transcript, stateDir), "utf-8"));
  } catch {
    return null;
  }
}

/** Record, after a Stop has rendered, how far into each agent file the
 * records it folded in reached.
 *
 * Written from the records themselves rather than from the files' sizes,
 * so that what is stored is exactly what was reported.  Files with no
 * billed record yet are absent, and absent reads as 0.  `held` is what
 * readTurns held back from a still-running agent, {path: the first such
 * record's offset}: the extent stops short of them. */
export function publishAgentOffsets(transcript: string,
  agents: readonly AgentRec[], held: ReadonlyMap<string, number> | null,
  stateDir: string): void {
  held = held ?? new Map();
  const ext = new Map<string, number>();
  for (const a of agents) {
    if (a.offset >= (held.get(a.path) ?? a.offset + 1)) continue;
    if (a.offset > (ext.get(a.path) ?? 0)) ext.set(a.path, a.offset);
  }
  writeAtomic(_agentStatePath(transcript, stateDir), pyJsonDumps(ext));
}

/** An agent file's id and name: the id off `agent-<id>.jsonl`, and the
 * description its `.meta.json` sidecar gives, else its agentType, else
 * "". */
export function agentLabel(path: string): [string, string] {
  let meta: Uint8Array | null = null;
  try {
    meta = fs.readFileSync(path.slice(0, -".jsonl".length) + ".meta.json");
  } catch {
    // No sidecar: the id alone.
  }
  return agentLabelOf(path, meta);
}

/** markedRecordsOf over the file at `path`; [] if it will not open. */
export function markedRecords(path: string,
  marks: readonly Uint8Array[]): Rec[] {
  try {
    return markedRecordsOf(fs.readFileSync(path), marks);
  } catch {
    return [];
  }
}

/** (epoch, target id) for each message this file queued for an agent. */
export function inboxSends(path: string): [number, string][] {
  const out: [number, string][] = [];
  for (const r of markedRecords(path, [SEND_QUEUED_MARK])) {
    const t = tsEpoch(pyOr(pyGet(r, "timestamp"), "")), target = queuedSend(r);
    if (t !== null && target) out.push([t, target]);
  }
  return out;
}

/** The epoch of each SendMessage delivery in this agent's file. */
export function inboxDeliveries(path: string): number[] {
  return markedRecords(path, INBOX_MARKS).filter(inboxDelivery)
    .map((r) => tsEpoch(pyOr(pyGet(r, "timestamp"), "")))
    .filter((t): t is number => t !== null);
}

/** How many messages wait in each agent's inbox: {agent id: count}.
 *
 * `files` is every transcript that can send — the main thread's and each
 * agent's — and `targets` maps each agent on the panel to its own file.
 * The two ends are matched by time, not by text: a send raises the count,
 * a delivery lowers it, and the count never goes below zero.  `since`, the
 * earliest any target started, skips every file last written before it. */
export function inboxCounts(files: readonly string[],
  targets: ReadonlyMap<string, string>,
  since: number | null = null): Map<string, number> {
  const sent = new Map<string, number[]>();
  for (const f of files) {
    try {
      if (since !== null &&
        Number(fs.statSync(f, { bigint: true }).mtimeNs) / 1e9 < since) {
        continue;
      }
    } catch {
      continue;
    }
    for (const [t, target] of inboxSends(f)) {
      if (targets.has(target)) {
        if (!sent.has(target)) sent.set(target, []);
        sent.get(target)!.push(t);
      }
    }
  }
  const out = new Map<string, number>();
  for (const [aid, times] of sent) {
    // A send and its delivery stamped alike: the send first.
    const events: [number, number, number][] = [
      ...times.map((t): [number, number, number] => [t, 0, 1]),
      ...inboxDeliveries(targets.get(aid)!)
        .map((t): [number, number, number] => [t, 1, -1])];
    events.sort(cmpTuple);
    let n = 0;
    for (const [, , step] of events) n = Math.max(0, n + step);
    if (n) out.set(aid, n);
  }
  return out;
}

/** transcriptOf over the file at `path`.  `agents` is agentRecords'
 * reading of the files beside it, or null to read them here, taking their
 * ETAs off the same walk. */
export function readTranscript(path: string,
  agents: readonly AgentRec[] | null = null,
  agent_etas: readonly AgentEta[] = [], now: number | null = null,
  cache: AgentCache | null = null): Transcript {
  const records = _records(path);
  if (agents === null) {
    const own: AgentEta[] = [];
    agents = agentRecords(path, null, own, cache);
    agent_etas = [...agent_etas, ...own];
  }
  return transcriptOf(records, agents, agent_etas, now);
}

/** turnsOf over the file at `path`, with the agent files beside it and the
 * offsets the last Stop stored under `stateDir`. */
export function readTurns(path: string,
  agents: readonly AgentRec[] | null = null,
  held: Map<string, number> | null = null, stateDir: string | null = null,
  cache: AgentCache | null = null): Turn[] {
  return turnsOf(_records(path),
    (seen) => agents ?? agentRecords(path, seen, null, cache),
    stateDir === null ? null : agentOffsets(path, stateDir), held,
    agentLabel);
}

/** readTurns, having waited for the turn being reported to be written.
 *
 * The transcript is NOT flushed in step with the Stop hook: the records the
 * turn just produced can still be missing when it reads, and a turn with no
 * usage record looks like a prompt never answered.  Waiting is the only
 * stateless fix; the file's size gates the re-read, so a wait that spans
 * the whole budget parses it once.  Asynchronous here: the mod's handlers
 * must not block its event loop. */
export async function readTurnsSettled(path: string, budget = SETTLE_S,
  poll = SETTLE_POLL_S, agents: readonly AgentRec[] | null = null,
  held: Map<string, number> | null = null, stateDir: string | null = null,
  cache: AgentCache | null = null): Promise<Turn[]> {
  let turns = readTurns(path, agents, held, stateDir, cache);
  if (!budget || _settled(turns)) return turns;
  const deadline = performance.now() + budget * 1000;
  let size: number;
  try {
    size = fs.statSync(path).size;
  } catch {
    return turns;
  }
  while (performance.now() < deadline) {
    await new Promise((ok) => setTimeout(ok, poll * 1000));
    let grown: number;
    try {
      grown = fs.statSync(path).size;
    } catch {
      break;
    }
    if (grown === size) continue;
    size = grown;
    held?.clear();
    turns = readTurns(path, agents, held, stateDir, cache);
    if (_settled(turns)) break;
  }
  return turns;
}
