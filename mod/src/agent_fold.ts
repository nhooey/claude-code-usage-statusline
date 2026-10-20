// Each agent transcript's fold saved as text, so a read goes on from where
// the last one stopped: agent_fold.py's port, written byte for byte as it
// writes them.  spec/state.jsonc's "agent-fold" row names the files and the
// format; agents/plans/saved-running-totals.md has the design.
//
// A fold is claude_records.ts's AgentFold, saved whole as one JSON object
// to one of two slots in turn, each with a sequence number, since
// $.fs.write truncates and then writes, and a reader can see the file
// torn.  A reader takes the newer slot that parses and still fits the
// file, and else the other.
import type { AgentFold, AgentRaw } from "./claude_records.ts";
import { newAgentFold, pyJoin } from "./claude_records.ts";
import { sha256Hex } from "./sha256.ts";
import { stateName } from "./state.ts";
import { STATE_KINDS } from "./state_spec.ts";

const ROW = STATE_KINDS["agent-fold"];
export const AGENT_FOLD_FORMAT = ROW.format;
/** The bytes before a fold's offset that its check digest is taken over. */
export const FOLD_CHECK_BYTES = ROW.check_bytes;
/** The two slots a fold is written to in turn, after its path's digest. */
export const SLOTS = ["-a.cache", "-b.cache"] as const;
const SEQ = /^\{"format":(\d+),"seq":(\d+),/;

/** The directory a session's agent folds are saved in, under the state
 * directory `stateDir`. */
export function foldDir(stateDir: string, transcript: string): string {
  return pyJoin(stateDir, stateName("agent-fold", transcript));
}

/** The two files agent file `path`'s fold is saved to in turn. */
export function slotNames(path: string): [string, string] {
  const digest = sha256Hex(path);
  return [digest + SLOTS[0], digest + SLOTS[1]];
}

/** The check digest of a fold at an offset: the sha256 of `data`, the
 * FOLD_CHECK_BYTES of the file before it, or all of them where the offset
 * is closer to the start. */
export function tailDigest(data: Uint8Array): string {
  return sha256Hex(data);
}

/** `f` as the text a save writes, with its sequence number and check
 * digest, byte for byte as agent_fold.fold_text writes it. */
export function agentFoldText(f: AgentFold, seq: number, tail: string):
  string {
  const e = f.etaState;
  return JSON.stringify({
    format: AGENT_FOLD_FORMAT, seq, pos: f.pos, tail, pid: f.pid,
    eta: [e[0], e[1], e[2], e[3]], span: f.spanState, work: f.work,
    pending: [...f.pending].map(([k, [t, name]]) => [k, t, name]),
    tools: f.tools, waiting: f.waiting, recs: f.recs, wrote: [...f.wrote],
    added: f.added, removed: f.removed, compactions: f.compactions,
    last_seen: f.lastSeen, api_error: f.apiError, cwd: f.cwd,
    blocks: f.blocks, background: [...f.background], effort: f.effort,
  });
}

/** A fold's text read back, as [seq, tail, fold], or null for text that
 * will not parse, is of another format, or is not a fold. */
export function agentFoldOf(text: string | null):
  [number, string, AgentFold] | null {
  if (!text) return null;
  try {
    // Read back as agentFoldText wrote it: the format says its shape.
    const o = JSON.parse(text) as any;
    if (o === null || typeof o !== "object" ||
      o.format !== AGENT_FOLD_FORMAT || !Number.isInteger(o.seq) ||
      !Number.isInteger(o.pos)) {
      return null;
    }
    const recs = o.recs as AgentRaw[];
    const f: AgentFold = { ...newAgentFold(), pid: o.pid,
      etaState: [o.eta[0], Boolean(o.eta[1]), o.eta[2], o.eta[3]],
      spanState: [o.span[0], o.span[1]], work: o.work,
      pending: new Map(o.pending.map(
        ([k, t, name]: [string, number, string]) => [k, [t, name]])),
      tools: o.tools, waiting: o.waiting, recs, wrote: new Set(o.wrote),
      added: o.added, removed: o.removed, pos: o.pos,
      compactions: o.compactions, lastSeen: o.last_seen,
      apiError: Boolean(o.api_error), cwd: o.cwd, blocks: o.blocks,
      background: new Map(o.background), effort: o.effort,
      keys: new Set(recs.map((r) => r[7])) };
    return [o.seq, o.tail, f];
  } catch {
    return null;
  }
}

/** The sequence number a slot's text starts with, without parsing the
 * rest; -1 for none. */
function seqOf(text: string | null): number {
  const m = SEQ.exec(text ?? "");
  return m ? Number(m[2]) : -1;
}

/** What agent_fold.load chooses from: the folds the slots' `texts` hold,
 * newest first, each as agentFoldOf reads it, and the highest sequence
 * number either slot starts with, which a fold started over saves after,
 * so its save goes to the slot after that one.  The first fold whose
 * offset and check digest still fit the file is the one to read on. */
export function foldCandidates(texts: readonly (string | null)[]):
  { folds: [number, string, AgentFold][]; newest: number } {
  const folds: [number, string, AgentFold][] = [];
  for (const text of [...texts].sort((a, b) => seqOf(b) - seqOf(a))) {
    const got = agentFoldOf(text);
    if (got !== null) folds.push(got);
  }
  return { folds, newest: Math.max(0, ...texts.map(seqOf)) };
}
