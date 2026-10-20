// The agent panel's inbox counts, read on from a saved fold: inbox_fold.py's
// port, written byte for byte as it writes them.  spec/state.jsonc's
// "inbox-fold" row names the directory and the format;
// agents/plans/_implemented/saved-running-totals.md has the design, and
// inbox_fold.py's docstring the text:
//
//   {"format":N,"seq":S,"files":[[PATH,POS,MTIME,TAIL,SENDS,GOT],...]}
//
// The whole session's fold, written to one of two slots in turn, each with
// a sequence number, since $.fs.write truncates and then writes and a
// reader can see the file torn.  The readers that take a path are
// claude_records_node.ts's inboxFoldCounts.
import {
  cmpStr, inboxDeliveriesOf, inboxSendsOf, pyJoin,
} from "./claude_records.ts";
import { sha256Hex } from "./sha256.ts";
import { stateName } from "./state.ts";
import { STATE_KINDS } from "./state_spec.ts";

const ROW = STATE_KINDS["inbox-fold"];
export const INBOX_FOLD_FORMAT = ROW.format;
/** The bytes before an entry's offset that its check digest is taken
 * over. */
export const INBOX_CHECK_BYTES = ROW.check_bytes;
/** The two slots the fold is written to in turn, in its directory. */
export const INBOX_SLOTS = ["inbox-a.cache", "inbox-b.cache"] as const;
const SEQ = /^\{"format":(\d+),"seq":(\d+),/;

/** One file's fold: the offset its whole lines are folded to, its mtime in
 * nanoseconds when they were, the check digest before the offset, its
 * sends as [epoch, agent id] and its deliveries' epochs. */
export type InboxEntry = {
  pos: number; mtime: string; tail: string;
  sends: [number, string][]; got: number[];
};

/** The check digest of an entry at an offset: the sha256 of `data`, the
 * INBOX_CHECK_BYTES of the file before it, or all of them where the offset
 * is closer to the start. */
export function inboxTailDigest(data: Uint8Array): string {
  return sha256Hex(data);
}

export function newInboxEntry(): InboxEntry {
  return { pos: 0, mtime: "", tail: inboxTailDigest(new Uint8Array(0)),
    sends: [], got: [] };
}

/** The directory a session's inbox fold is saved in, under the state
 * directory `stateDir`. */
export function inboxFoldDir(stateDir: string, transcript: string): string {
  return pyJoin(stateDir, stateName("inbox-fold", transcript));
}

/** Fold `data`, the whole lines of a file from `e.pos` on, into `e`;
 * `main` for the session's own transcript, whose deliveries are not
 * folded (inbox_fold.fold_entry has why). */
export function foldInboxEntry(e: InboxEntry, data: Uint8Array,
  main = false): void {
  e.sends.push(...inboxSendsOf(data));
  if (!main) e.got.push(...inboxDeliveriesOf(data));
  e.pos += data.length;
}

/** `e`, the fold of file `path`, as the fold's text writes it. */
export function inboxEntryText(path: string, e: InboxEntry): string {
  return JSON.stringify([path, e.pos, e.mtime, e.tail, e.sends, e.got]);
}

/** The session's fold as the text a save writes, with its sequence
 * number, byte for byte as inbox_fold.fold_text writes it. */
export function inboxFoldText(entries: ReadonlyMap<string, InboxEntry>,
  seq: number): string {
  return `{"format":${INBOX_FOLD_FORMAT},"seq":${seq},"files":[` +
    [...entries.keys()].sort(cmpStr)
      .map((p) => inboxEntryText(p, entries.get(p)!)).join(",") + "]}";
}

/** A fold's text read back, as [seq, entries], or null for text that will
 * not parse, is of another format, or is not a fold. */
export function inboxFoldOf(text: string | null):
  [number, Map<string, InboxEntry>] | null {
  if (!text) return null;
  try {
    // Read back as inboxFoldText wrote it: the format says its shape.
    const o = JSON.parse(text) as any;
    if (o === null || typeof o !== "object" ||
      o.format !== INBOX_FOLD_FORMAT || !Number.isInteger(o.seq)) {
      return null;
    }
    const entries = new Map<string, InboxEntry>();
    for (const [path, pos, mtime, tail, sends, got] of o.files) {
      if (!Number.isInteger(pos) || typeof path !== "string") return null;
      entries.set(path, { pos, mtime: String(mtime), tail: String(tail),
        sends: sends.map(([t, aid]: [number, string]) => [t, String(aid)]),
        got: [...got] });
    }
    return [o.seq, entries];
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

/** inbox_fold.load: the fold the newest of the slots' `texts` that reads
 * back holds, and its sequence number; for none, no entries and the
 * highest sequence number either slot starts with. */
export function inboxFoldLoad(texts: readonly (string | null)[]):
  [Map<string, InboxEntry>, number] {
  for (const text of [...texts].sort((a, b) => seqOf(b) - seqOf(a))) {
    const got = inboxFoldOf(text);
    if (got !== null) return [got[1], got[0]];
  }
  return [new Map(), Math.max(0, ...texts.map(seqOf))];
}
