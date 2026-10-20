// The main transcript's two folds saved as text, so a reload reads on
// from where they stopped: main_fold.py's port, written byte for byte as
// it writes them.  spec/state.jsonc's "main-fold" row names the files and
// the format; agents/plans/saved-running-totals.md has the design.
//
// What never changes once folded is a log, one JSON array a line, tagged
// with what it adds to, in parts of at most part_bytes of UTF-8: a part
// only grows, and every part but the last is never written again.  The
// rest is a head, written after the parts, which names the parts, how many
// entries each holds, the byte offset folded to and the transcript's check
// digests.  Until a head is written the one before it reads true, since
// its counts take a prefix of each part.  Heads go to two slots in turn,
// each with a sequence number, as $.fs.write can be read torn.
import type {
  EtaState, OwnPart, Pending, Rec, Span, TranscriptFold, TurnBuild,
  TurnsFold,
} from "./claude_records.ts";
import {
  foldTranscript, foldTurns, newTranscriptFold, newTurnsFold,
} from "./claude_records.ts";
import { sha256Hex } from "./sha256.ts";
import { STATE_KINDS } from "./state_spec.ts";

const ROW = STATE_KINDS["main-fold"];
export const MAIN_FOLD_FORMAT = ROW.format;
/** At most this many bytes of UTF-8 a part, except a single entry longer
 * than that; and no head longer is saved. */
export const FOLD_PART_BYTES = ROW.part_bytes;
/** The bytes a head's check digests are taken over. */
export const FOLD_CHECK_BYTES = ROW.check_bytes;
/** The two slots a head is written to in turn. */
export const HEAD_SLOTS = ["head-a.cache", "head-b.cache"] as const;

export function partName(i: number): string {
  return `part-${i}.cache`;
}

/** Both folds of the main transcript, fed the same records. */
export type MainFold = { tr: TranscriptFold; tu: TurnsFold };

export function newMainFold(): MainFold {
  return { tr: newTranscriptFold(), tu: newTurnsFold() };
}

export function foldMain(f: MainFold, r: Rec): void {
  foldTranscript(f.tr, r);
  foldTurns(f.tu, r);
}

/** What a saved fold says of the transcript it was folded from: the byte
 * offset folded to, a whole line's end, and the sha256 of the first
 * FOLD_CHECK_BYTES and of the FOLD_CHECK_BYTES before the offset. */
export type FoldMeta = { offset: number; first: string; tail: string };

/** foldMeta's digests over the transcript's `bytes`, from its start up to
 * `offset` at least. */
export function foldMeta(bytes: Uint8Array, offset: number): FoldMeta {
  return { offset,
    first: sha256Hex(bytes.subarray(0, Math.min(FOLD_CHECK_BYTES, offset))),
    tail: sha256Hex(bytes.subarray(Math.max(0, offset - FOLD_CHECK_BYTES),
      offset)) };
}

/** What a save has written of a fold, for the next to write only what is
 * new: the parts' entry counts, the last part's text, how many of each
 * list's entries are logged, and the maps as logged. */
export interface SaveMark {
  seq: number;
  counts: number[];
  last: string;
  lastBytes: number;
  logged: Record<string, number>;
  ends: Map<string, number>;
  uends: Map<string, number>;
  pids: Map<unknown, number>;
}

export function newSaveMark(): SaveMark {
  return { seq: 0, counts: [], last: "", lastBytes: 0, logged: {},
    ends: new Map(), uends: new Map(), pids: new Map() };
}

/** The bytes `s` takes as UTF-8.  JSON.stringify escapes a lone
 * surrogate, so every one met here is half of a pair. */
export function utf8Bytes(s: string): number {
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c < 0x80) n += 1;
    else if (c < 0x800) n += 2;
    else if (c >= 0xd800 && c < 0xdc00) {
      n += 4;
      i++;
    } else n += 3;
  }
  return n;
}

const j = JSON.stringify;

function turnJson(t: TurnBuild): unknown {
  return { ts: t.ts, text: t.text, fresh: t.fresh, cw: t.cw, cr: t.cr,
    out: t.out, ctx: t.ctx, n: t.n, usd: t.usd, an: t.an, aids: t.aids,
    t0: t.t0, t1: t.t1, parts: t.parts, tools: t.tools, waits: t.waits,
    am: t.am, at: t.at, pid: t.pid, tidx: t.tidx, la: t.la, lr: t.lr,
    eta: t.eta, dur: t.dur ?? null, compact: t.compact ?? null };
}

function turnOf(o: any): TurnBuild {
  const t: TurnBuild = { ts: o.ts, text: o.text, fresh: o.fresh, cw: o.cw,
    cr: o.cr, out: o.out, ctx: o.ctx, n: o.n, usd: o.usd, an: o.an,
    aids: o.aids, t0: o.t0, t1: o.t1, parts: o.parts, tools: o.tools,
    waits: o.waits, am: o.am, at: o.at, pid: o.pid, tidx: o.tidx, la: o.la,
    lr: o.lr, eta: o.eta };
  if (o.dur !== null) t.dur = o.dur;
  if (o.compact !== null) t.compact = o.compact;
  return t;
}

/** How many of `tr.parts` are final: those before an open compaction's. */
function closedParts(tr: TranscriptFold): number {
  return tr.compacting ?? tr.parts.length;
}

/** The entries `f` holds past what `mark` logged, each as its line's text,
 * in the order the tags are listed; and the logged counts and maps they
 * bring `mark` to. */
function newEntries(f: MainFold, mark: SaveMark):
  { lines: string[]; logged: Record<string, number>;
    ends: Map<string, number>; uends: Map<string, number>;
    pids: Map<unknown, number> } {
  const lines: string[] = [];
  const logged = { ...mark.logged };
  const from = (tag: string, items: Iterable<unknown>, upto: number,
    entry: (x: any) => unknown[]) => {
    let i = 0;
    const done = logged[tag] ?? 0;
    for (const x of items) {
      if (i >= upto) break;
      if (i++ >= done) lines.push(j(entry(x)));
    }
    logged[tag] = Math.max(done, Math.min(i, upto));
  };
  const changed = <K>(tag: string, now: Map<K, number>,
    was: Map<K, number>): Map<K, number> => {
    for (const [k, v] of now) {
      if (was.get(k) !== v) lines.push(j([tag, k, v]));
    }
    return new Map(now);
  };
  const { tr, tu } = f;
  from("r", tr.reqs, Infinity, (k) => ["r", k]);
  from("w", tr.wrote, Infinity, (k) => ["w", k]);
  const ends = changed("e", tr.ends, mark.ends);
  from("s", tr.spans, Infinity, (s: Span) => ["s", s[0], s[1]]);
  from("t", tr.tools, Infinity, (s: Span) => ["t", s[0], s[1]]);
  from("b", tr.blocked, Infinity, (s: Span) => ["b", s[0], s[1]]);
  from("p", tr.parts, closedParts(tr), (p: OwnPart) => ["p", p[0], p[1]]);
  from("S", tu.seen, Infinity, (k) => ["S", k]);
  from("W", tu.wrote, Infinity, (k) => ["W", k]);
  const uends = changed("E", tu.ends, mark.uends);
  const pids = changed("P", tu.byPid, mark.pids);
  from("T", tu.turns, Math.max(0, tu.turns.length - 1),
    (t: TurnBuild) => ["T", turnJson(t)]);
  return { lines, logged, ends, uends, pids };
}

function pendingJson(p: Pending): unknown[] {
  return [...p].map(([id, [t, name]]) => [id, t, name]);
}

/** The head's text: everything not in the log. */
function headText(f: MainFold, meta: FoldMeta, counts: readonly number[],
  seq: number): string {
  const { tr, tu } = f;
  const open = closedParts(tr);
  const e = tr.etaState;
  return j({ format: MAIN_FOLD_FORMAT, seq, offset: meta.offset,
    first: meta.first, tail: meta.tail, counts,
    tr: { fresh: tr.fresh, cwrite: tr.cwrite, cread: tr.cread,
      down: tr.down, parts: tr.parts.slice(open),
      compacting: tr.compacting, opener: tr.opener, own_est: tr.ownEst,
      ctx: tr.ctx, first_ctx: tr.firstCtx, ctx_est: tr.ctxEst,
      user_ts: tr.userTs, user_text: tr.userText, asst_ts: tr.asstTs,
      asst_text: tr.asstText, pending: pendingJson(tr.pending),
      first: tr.first, open_at: tr.openAt, prev: tr.prev,
      eta: [e[0], e[1], e[2], e[3]], queued: tr.queued,
      compactions: tr.compactions, background: [...tr.background],
      idle_at: tr.idleAt, last_seen: tr.lastSeen,
      opened: [tr.opened.pid, tr.opened.tidx], added: tr.added,
      removed: tr.removed },
    tu: { settled: tu.settled, last_stop: tu.lastStop,
      pending: pendingJson(tu.pending),
      open: tu.turns.length ? turnJson(tu.turns[tu.turns.length - 1])
        : null } });
}

/** A save of `f`: the parts to write, by index, then the head and its
 * slot, and the mark the save brings `mark` to once all are written.  With
 * a fresh mark, the whole fold.  null where the head would be over
 * `headBytes`, which is not saved.  The sizes are the tests'. */
export function foldSave(f: MainFold, meta: FoldMeta,
  mark: SaveMark = newSaveMark(), partBytes: number = FOLD_PART_BYTES,
  headBytes: number = FOLD_PART_BYTES):
  { parts: [number, string][]; head: string; slot: string;
    mark: SaveMark } | null {
  const got = newEntries(f, mark);
  const counts = mark.counts.slice();
  let last = mark.last, lastBytes = mark.lastBytes;
  let at = counts.length - 1;
  const parts = new Map<number, string>();
  for (const line of got.lines) {
    const bytes = utf8Bytes(line) + 1;
    if (at < 0 || (counts[at] > 0 && lastBytes + bytes > partBytes)) {
      counts.push(0);
      at = counts.length - 1;
      last = "";
      lastBytes = 0;
    }
    last += line + "\n";
    lastBytes += bytes;
    counts[at] += 1;
    parts.set(at, last);
  }
  const seq = mark.seq + 1;
  const head = headText(f, meta, counts, seq);
  if (utf8Bytes(head) > headBytes) return null;
  return { parts: [...parts], head, slot: HEAD_SLOTS[seq % 2],
    mark: { seq, counts, last, lastBytes, logged: got.logged,
      ends: got.ends, uends: got.uends, pids: got.pids } };
}

/** The files a save of `f` writes, in order, as [name, text], and the mark
 * it brings `mark` to; null where the head is over its cap.  With no mark,
 * a fold started over, both heads are emptied first: $.fs.write truncates
 * and then writes, so neither could then read a part it was not written
 * beside.  Then the parts, then the head.  main_fold.py's fold_writes, the
 * worker's (scripts/agent_lines.py's fold mode), is the same list. */
export function foldWrites(f: MainFold, meta: FoldMeta,
  mark: SaveMark | null, partBytes: number = FOLD_PART_BYTES):
  { writes: [string, string][]; mark: SaveMark } | null {
  const save = foldSave(f, meta, mark ?? newSaveMark(), partBytes);
  if (!save) return null;
  const writes: [string, string][] = mark ? []
    : HEAD_SLOTS.map((s) => [s, ""] as [string, string]);
  for (const [i, t] of save.parts) writes.push([partName(i), t]);
  writes.push([save.slot, save.head]);
  return { writes, mark: save.mark };
}

/** A head's text read back, or null for one that will not parse, is of
 * another format, or is not a head. */
export function foldHeadOf(text: string | null):
  { seq: number; meta: FoldMeta; counts: number[]; head: any } | null {
  if (text === null) return null;
  try {
    const o = JSON.parse(text);
    if (o === null || typeof o !== "object" ||
      o.format !== MAIN_FOLD_FORMAT || typeof o.seq !== "number" ||
      typeof o.offset !== "number" || !Array.isArray(o.counts) ||
      typeof o.tr !== "object" || typeof o.tu !== "object") {
      return null;
    }
    return { seq: o.seq, meta: { offset: o.offset, first: o.first,
      tail: o.tail }, counts: o.counts, head: o };
  } catch {
    return null;
  }
}

/** The fold saved in the files `read` reads by name (null for none), from
 * the newest head whose parts read whole; null for none.  The mod reads
 * through `$`, which is asynchronous, and walks the same steps itself. */
export function foldLoad(read: (name: string) => string | null):
  { fold: MainFold; meta: FoldMeta; mark: SaveMark } | null {
  const heads = HEAD_SLOTS.map((s) => foldHeadOf(read(s)))
    .filter((h) => h !== null).sort((a, b) => b.seq - a.seq);
  for (const got of heads) {
    const back = foldOfSaved(got, got.counts.map((_, i) => read(partName(i))));
    if (back !== null) return { ...back, meta: got.meta };
  }
  return null;
}

function pendingOf(xs: [string, number, string][]): Pending {
  return new Map(xs.map(([id, t, name]) => [id, [t, name] as const]));
}

/** The fold a head and its parts' texts hold, with the mark a save from
 * it starts at; null where a part is missing, torn or holds fewer entries
 * than the head names. */
export function foldOfSaved(
  got: { seq: number; counts: number[]; head: any },
  parts: readonly (string | null)[]):
  { fold: MainFold; mark: SaveMark } | null {
  const f = newMainFold();
  const { tr, tu } = f;
  const logged: Record<string, number> = {};
  let last = "";
  try {
    for (const [i, n] of got.counts.entries()) {
      const text = parts[i];
      if (text === null || text === undefined) return null;
      const lines = text.split("\n");
      if (lines.length - 1 < n) return null;
      last = lines.slice(0, n).map((l) => l + "\n").join("");
      for (const l of lines.slice(0, n)) {
        const e = JSON.parse(l);
        logged[e[0]] = (logged[e[0]] ?? 0) + 1;
        switch (e[0]) {
          case "r": tr.reqs.add(e[1]); break;
          case "w": tr.wrote.add(e[1]); break;
          case "e": tr.ends.set(e[1], e[2]); break;
          case "s": tr.spans.push([e[1], e[2]]); break;
          case "t": tr.tools.push([e[1], e[2]]); break;
          case "b": tr.blocked.push([e[1], e[2]]); break;
          case "p": tr.parts.push([e[1], e[2]]); break;
          case "S": tu.seen.add(e[1]); break;
          case "W": tu.wrote.add(e[1]); break;
          case "E": tu.ends.set(e[1], e[2]); break;
          case "P": tu.byPid.set(e[1], e[2]); break;
          case "T": tu.turns.push(turnOf(e[1])); break;
          default: return null;
        }
      }
    }
    // The maps' logged counts are what the next save compares against,
    // not tallies of their entries.
    delete logged.e;
    delete logged.E;
    delete logged.P;
    const h = got.head.tr, u = got.head.tu;
    tr.fresh = h.fresh;
    tr.cwrite = h.cwrite;
    tr.cread = h.cread;
    tr.down = h.down;
    tr.parts.push(...h.parts);
    tr.compacting = h.compacting;
    tr.opener = h.opener;
    tr.ownEst = h.own_est;
    tr.ctx = h.ctx;
    tr.firstCtx = h.first_ctx;
    tr.ctxEst = h.ctx_est;
    tr.userTs = h.user_ts;
    tr.userText = h.user_text;
    tr.asstTs = h.asst_ts;
    tr.asstText = h.asst_text;
    for (const [k, v] of pendingOf(h.pending)) tr.pending.set(k, v);
    tr.first = h.first;
    tr.openAt = h.open_at;
    tr.prev = h.prev;
    const eta: EtaState = h.eta;
    tr.etaState[0] = eta[0];
    tr.etaState[1] = eta[1];
    tr.etaState[2] = eta[2];
    tr.etaState[3] = eta[3];
    tr.queued = h.queued;
    tr.compactions = h.compactions;
    for (const [k, v] of h.background) tr.background.set(k, v);
    tr.idleAt = h.idle_at;
    tr.lastSeen = h.last_seen;
    tr.opened = { pid: h.opened[0], tidx: h.opened[1] };
    tr.added = h.added;
    tr.removed = h.removed;
    tu.settled = u.settled;
    tu.lastStop = u.last_stop;
    for (const [k, v] of pendingOf(u.pending)) tu.pending.set(k, v);
    if (u.open !== null) tu.turns.push(turnOf(u.open));
  } catch {
    return null;
  }
  return { fold: f, mark: { seq: got.seq, counts: got.counts.slice(), last,
    lastBytes: utf8Bytes(last), logged, ends: new Map(tr.ends),
    uends: new Map(tu.ends), pids: new Map(tu.byPid) } };
}
