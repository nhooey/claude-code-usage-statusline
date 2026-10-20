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
  agentFoldText, FOLD_CHECK_BYTES, foldCandidates, foldDir, slotNames,
  tailDigest,
} from "./agent_fold.ts";
import {
  _agentDir, _agentStatePath, _readAgentBytes, _recordsOf, agentLabelOf,
  agentOffsetsOf, agentReadingOf, agentRecordsOf, cmpStr,
  copyAgentFold, foldAgentBytes, inboxDeliveriesOf, inboxSendsOf,
  inboxTally, markedRecordsOf, newAgentFold, pyJoin, pyJsonDumps,
  transcriptOf, turnsOf, _settled, SETTLE_POLL_S, SETTLE_S,
} from "./claude_records.ts";
import {
  foldInboxEntry, INBOX_CHECK_BYTES, INBOX_SLOTS, inboxFoldDir,
  inboxFoldLoad, inboxFoldText, inboxTailDigest, newInboxEntry,
} from "./inbox_fold.ts";
import type { InboxEntry } from "./inbox_fold.ts";
import type {
  AgentEta, AgentFold, AgentReading, AgentRec, Rec, Transcript, Turn,
} from "./claude_records.ts";
import { pyGet, pyOr } from "./py.ts";

export * from "./claude_records.ts";

const AGENT_NAME = /^agent-.*\.jsonl$/s;

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
 * _agentFileReadings for `stateDir`. */
export function agentRecords(transcript: string,
  seen: Set<unknown> | null = null,
  etas: AgentEta[] | null = null,
  stateDir: string | null = null): AgentRec[] {
  return agentRecordsOf(_agentFileReadings(transcript, stateDir), seen, etas);
}

/** _readAgentBytes off the file, or null for a file that will not open. */
export function _readAgentFile(path: string): AgentReading | null {
  try {
    return _readAgentBytes(fs.readFileSync(path));
  } catch {
    return null;
  }
}

/** Agent file `path`'s fold, read on from the one saved for it in `dir`
 * to the file's end, and saved back where it folded anything:
 * agent_fold.fold_file's port.  A saved fold is read only where the file
 * still holds the bytes it was folded from, its offset within the file and
 * the digest of the bytes before it the same.  A last line with no newline
 * yet is folded on a copy, which is returned and not saved.  null for a
 * file that will not open. */
export function agentFoldFile(dir: string, path: string): AgentFold | null {
  let fd: number;
  try {
    fd = fs.openSync(path, "r");
  } catch {
    return null;
  }
  const names = slotNames(path);
  let fold: AgentFold, seq: number, start: number, data: Uint8Array;
  let whole: number, tail = "";
  try {
    const size = fs.fstatSync(fd).size;
    const tailAt = (pos: number): string => {
      const lo = Math.max(0, pos - FOLD_CHECK_BYTES);
      const buf = new Uint8Array(pos - lo);
      fs.readSync(fd, buf, 0, buf.length, lo);
      return tailDigest(buf);
    };
    const { folds, newest } = foldCandidates(names.map((n) => {
      try {
        return fs.readFileSync(pyJoin(dir, n), "utf-8");
      } catch {
        return null;
      }
    }));
    const got = folds.find(([, t, f]) => f.pos <= size && tailAt(f.pos) === t);
    [fold, seq] = got ? [got[2], got[0]] : [newAgentFold(), newest];
    start = fold.pos;
    data = new Uint8Array(size - start);
    fs.readSync(fd, data, 0, data.length, start);
    whole = data.lastIndexOf(10) + 1;
    foldAgentBytes(fold, data.subarray(0, whole));
    if (fold.pos > start) tail = tailAt(fold.pos);
  } finally {
    fs.closeSync(fd);
  }
  if (fold.pos > start) {
    writeAtomic(pyJoin(dir, names[(seq + 1) % 2]),
      agentFoldText(fold, seq + 1, tail));
  }
  if (whole === data.length) return fold;
  const out = copyAgentFold(fold);
  foldAgentBytes(out, data.subarray(whole), true);
  return out;
}

/** _readAgentFile for every agent file, in agentFiles' order, each read on
 * from the fold saved for it under `stateDir` (agent_fold.ts), so a render
 * reads only what was appended since the last.  Without it, every render
 * parsed every agent file the session ever ran: a session with 611 of
 * them, 768 MB, took six seconds a render.  With no `stateDir`, every file
 * is read whole and nothing is saved. */
export function _agentFileReadings(transcript: string,
  stateDir: string | null = null): [string, AgentReading][] {
  const out: [string, AgentReading][] = [];
  const dir = stateDir === null ? "" : foldDir(stateDir, transcript);
  for (const path of agentFiles(transcript)) {
    const got = stateDir === null ? _readAgentFile(path)
      : agentFoldFile(dir, path);
    if (got === null) continue;
    out.push([path, stateDir === null ? got as AgentReading
      : agentReadingOf(got as AgentFold)]);
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

/** The bytes of the file at `path`, or none where it will not open. */
function fileBytes(path: string): Uint8Array {
  try {
    return fs.readFileSync(path);
  } catch {
    return new Uint8Array(0);
  }
}

/** (epoch, target id) for each message this file queued for an agent. */
export function inboxSends(path: string): [number, string][] {
  return inboxSendsOf(fileBytes(path));
}

/** The epoch of each SendMessage delivery in this agent's file. */
export function inboxDeliveries(path: string): number[] {
  return inboxDeliveriesOf(fileBytes(path));
}

/** A file's mtime in seconds, as the Python's os.path.getmtime gives it. */
function mtimeS(path: string): number {
  return Number(fs.statSync(path, { bigint: true }).mtimeNs) / 1e9;
}

/** How many messages wait in each agent's inbox: {agent id: count}.
 *
 * `files` is every transcript that can send — the main thread's and each
 * agent's — and `targets` maps each agent on the panel to its own file.
 * The two ends are matched by time, not by text (inboxTally).  `since`,
 * the earliest any target started, skips every file last written before
 * it.  Every file is read whole; inboxFoldCounts reads on from a saved
 * fold instead, and must count the same. */
export function inboxCounts(files: readonly string[],
  targets: ReadonlyMap<string, string>,
  since: number | null = null): Map<string, number> {
  const sent = new Map<string, number[]>();
  for (const f of files) {
    try {
      if (since !== null && mtimeS(f) < since) continue;
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
  return inboxTally(sent, (aid) => inboxDeliveries(targets.get(aid)!));
}

/** File `path`'s entry in `entries`, read on to the file's end, and what
 * its last line, with no newline yet, holds: inbox_fold.read_on's port,
 * as [[entry, sends, deliveries] or null, whether `entries` changed]. */
function inboxReadOn(entries: Map<string, InboxEntry>, path: string,
  main: boolean): [[InboxEntry, [number, string][], number[]] | null,
    boolean] {
  let fd: number;
  try {
    fd = fs.openSync(path, "r");
  } catch {
    return [null, entries.delete(path)];
  }
  let e: InboxEntry, data: Uint8Array, whole: number;
  try {
    const st = fs.fstatSync(fd, { bigint: true });
    const size = Number(st.size), mtime = String(st.mtimeNs);
    const tailAt = (pos: number): string => {
      const lo = Math.max(0, pos - INBOX_CHECK_BYTES);
      const buf = new Uint8Array(pos - lo);
      fs.readSync(fd, buf, 0, buf.length, lo);
      return inboxTailDigest(buf);
    };
    const was = entries.get(path);
    if (was && was.pos === size && was.mtime === mtime) {
      return [[was, [], []], false];
    }
    e = was && was.pos <= size && tailAt(was.pos) === was.tail ? was
      : newInboxEntry();
    data = new Uint8Array(size - e.pos);
    fs.readSync(fd, data, 0, data.length, e.pos);
    whole = data.lastIndexOf(10) + 1;
    foldInboxEntry(e, data.subarray(0, whole), main);
    e.tail = tailAt(e.pos);
    e.mtime = mtime;
  } finally {
    fs.closeSync(fd);
  }
  entries.set(path, e);
  const rest = data.subarray(whole);
  if (!rest.length) return [[e, [], []], true];
  return [[e, inboxSendsOf(rest), main ? [] : inboxDeliveriesOf(rest)], true];
}

/** inboxCounts, read on from the fold saved for `transcript`'s session
 * under the state directory `stateDir`, and saved back where anything
 * moved: inbox_fold.counts' port, writing the same bytes. */
export function inboxFoldCounts(stateDir: string, transcript: string,
  files: readonly string[], targets: ReadonlyMap<string, string>,
  since: number | null = null): Map<string, number> {
  const dir = inboxFoldDir(stateDir, transcript);
  const [entries, seq] = inboxFoldLoad(INBOX_SLOTS.map((n) => {
    try {
      return fs.readFileSync(pyJoin(dir, n), "utf-8");
    } catch {
      return null;
    }
  }));
  let changed = false;
  const seen = new Map<string,
    [InboxEntry, [number, string][], number[]] | null>();
  const at = (path: string) => {
    if (!seen.has(path)) {
      const [got, moved] = inboxReadOn(entries, path, path === transcript);
      seen.set(path, got);
      changed = changed || moved;
    }
    return seen.get(path)!;
  };
  const sent = new Map<string, number[]>();
  for (const f of files) {
    try {
      if (since !== null && mtimeS(f) < since) continue;
    } catch {
      continue;
    }
    const got = at(f);
    if (got === null) continue;
    for (const [t, target] of [...got[0].sends, ...got[1]]) {
      if (targets.has(target)) {
        if (!sent.has(target)) sent.set(target, []);
        sent.get(target)!.push(t);
      }
    }
  }
  const out = inboxTally(sent, (aid) => {
    const p = targets.get(aid)!;
    // Its deliveries are not folded (foldInboxEntry): read whole.
    if (p === transcript) return inboxDeliveries(p);
    const got = at(p);
    return got === null ? [] : [...got[0].got, ...got[2]];
  });
  if (changed) {
    writeAtomic(pyJoin(dir, INBOX_SLOTS[(seq + 1) % 2]),
      inboxFoldText(entries, seq + 1));
  }
  return out;
}

/** transcriptOf over the file at `path`.  `agents` is agentRecords'
 * reading of the files beside it, or null to read them here, taking their
 * ETAs off the same walk, and reading on from their folds saved under
 * `stateDir` where it is not null. */
export function readTranscript(path: string,
  agents: readonly AgentRec[] | null = null,
  agent_etas: readonly AgentEta[] = [], now: number | null = null,
  stateDir: string | null = null): Transcript {
  const records = _records(path);
  if (agents === null) {
    const own: AgentEta[] = [];
    agents = agentRecords(path, null, own, stateDir);
    agent_etas = [...agent_etas, ...own];
  }
  return transcriptOf(records, agents, agent_etas, now);
}

/** turnsOf over the file at `path`, with the agent files beside it and the
 * offsets the last Stop stored under `stateDir`.  The agent files are read
 * on from their folds saved under `foldsIn` where it is not null. */
export function readTurns(path: string,
  agents: readonly AgentRec[] | null = null,
  held: Map<string, number> | null = null, stateDir: string | null = null,
  foldsIn: string | null = null): Turn[] {
  return turnsOf(_records(path),
    (seen) => agents ?? agentRecords(path, seen, null, foldsIn),
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
  foldsIn: string | null = null): Promise<Turn[]> {
  let turns = readTurns(path, agents, held, stateDir, foldsIn);
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
    turns = readTurns(path, agents, held, stateDir, foldsIn);
    if (_settled(turns)) break;
  }
  return turns;
}
