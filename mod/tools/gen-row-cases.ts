// Write the row builders' shared cases, tests/fixtures/rows/, from
// src/band.ts and src/receipt.ts.
//
//   node mod/tools/gen-row-cases.ts
//
// Like the grid's cases (gen-grid-cases.ts), these are written by the
// TypeScript, where the builders are built first; mod/test/rows.test.ts
// runs every case and fails when this generator's output differs from what
// is committed, so regenerating and reading the diff is the only way to
// change them.
//
// The inputs are the committed figures documents, tests/fixtures/figures/,
// by id (`<suite>/<case>`).  Documents whose text is the same are one
// input, under the first id, with the others in `same`.  One file per
// terminal profile, profiles whose cases come out the same sharing one.
// Each holds:
//
//   settings  the profiles, each with the environment it is read from
//   band      one case a line: a status document (`doc`, and `same`) drawn
//             at `cols` under `hide` in `phase` with the mod's 🛫, `rate`,
//             and, where the case has them, only the rows `places` (the
//             defaults file's rows.*.place) puts in `place`; above the
//             prompt, where the case has them, the band's tree with the
//             subagents of the panel corpus's case `agents`, the main
//             thread's progress update `progress` and the cap `cap`;
//             `rows`, each row's spans top to bottom, and `lines`, the
//             same joined with their escape codes
//   receipt   one case a line: a cost document drawn at `cols` under
//             `hide`; its lines as spans, `rows`, and joined, `lines`
//   start     one case a line: a status document's start line, as `spans`
//             and as `line`
//   account   one case a line: a status document's 💳 row drawn at `cols`
//             under `hide`, `indent` blanks in, as `row` and as `line`;
//             the last ones one document at widths that shed its pieces
//
// Each document's clock is drawn in its own `clock.tz`.  A span is written
// as the grid's cases write one.
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync }
  from "node:fs";
import { dirname, join as pathJoin } from "node:path";
import { fileURLToPath } from "node:url";
import { settings } from "../src/formatting.ts";
import type { Settings } from "../src/formatting.ts";
import { join } from "../src/spans.ts";
import type { Span } from "../src/spans.ts";
import type { Dict } from "../src/py.ts";
import { accountLine, bandLines } from "../src/band.ts";
import type { Phase, Place, RowsPlace } from "../src/band.ts";
import { DEFAULTS_REL, parseDefaults } from "../src/config.ts";
import type { Rows } from "../src/config.ts";
import { receiptLines, startLine } from "../src/receipt.ts";
import { PROFILES, spanJson } from "./gen-grid-cases.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
export const OUT = pathJoin(HERE, "..", "..", "tests", "fixtures", "rows");
export const FIGURES = pathJoin(HERE, "..", "..", "tests", "fixtures",
  "figures");
const COLS = [200, 155, 120, 80];
// Each scope's figures hidden, a group on every row, a label piece, and a
// whole scope with a label part of another, at one width.
const HIDES: readonly (readonly string[])[] = [
  ["*.work", "*.state.rate", "main.state.inbox"],
  ["session.tokens", "*.clock.time"],
  ["turn", "main.name", "*.plan"],
];
const HIDE_COLS = 155;
// A document with every piece of the 💳 row, 🔀 and 🎨 among them, drawn at
// widths that shed them one by one.
const SHED_DOC = "status/04-pr-and-style@196";
// The 🛫 the mod would pass, at one width: the documents carry the counts
// it works one out from, never the rate itself.
const RATE = 220, RATE_COLS = 200;
// Where the defaults file puts each of the band's rows, and the width the
// cases by place are drawn at.
const DEFAULT_ROWS = parseDefaults(DEFAULTS_REL, readFileSync(
  pathJoin(HERE, "..", DEFAULTS_REL), "utf8")).rows as Rows;
export const PLACES: RowsPlace = Object.fromEntries(
  (["turn", "agent", "session"] as const).map((r) =>
    [r, DEFAULT_ROWS[r].place as Place]));
const PLACE_COLS = 155;

/** The documents of `suite`, by id, deduplicated by text: [id, the ids
 * with the same text, the document]. */
export function documents(suite: string): [string, string[], Dict][] {
  const byText = new Map<string, string[]>();
  for (const f of readdirSync(pathJoin(FIGURES, suite)).sort()) {
    if (!f.endsWith(".json")) continue;
    const text = readFileSync(pathJoin(FIGURES, suite, f), "utf8");
    byText.set(text, [...(byText.get(text) ?? []),
      suite + "/" + f.slice(0, -5)]);
  }
  return [...byText].map(([text, ids]) =>
    [ids[0], ids.slice(1), JSON.parse(text) as Dict]);
}

/** A document by id. */
export function document(id: string): Dict {
  return JSON.parse(readFileSync(pathJoin(FIGURES, id + ".json"), "utf8"));
}

/** Draw `fig` with its clock in its own zone, as the edge sets it. */
export function inZone<T>(fig: Dict, f: () => T): T {
  const tz = (fig.clock as Dict).tz as string | null;
  const was = process.env.TZ;
  process.env.TZ = tz ?? "UTC";
  try {
    return f();
  } finally {
    if (was === undefined) delete process.env.TZ;
    else process.env.TZ = was;
  }
}

export type BandCase = { doc: string; cols: number; hide: string[];
  phase: Phase; rate: number | null; place?: Place; places?: RowsPlace;
  agents?: string; progress?: string; cap?: number };

/** The panel's corpus, tests/fixtures/panel/corpus.json: its cases' tasks
 * are the band's tree's subagents (corpusAgents). */
const CORPUS = pathJoin(HERE, "..", "..", "tests", "fixtures", "panel",
  "corpus.json");

/** A status document's `agents` with the subagents of the corpus case
 * `id` ("" for none), each task's `label` standing for its latest progress
 * update and none for its activity, and `main` the main thread's.  The
 * corpus's clock is the figures documents'. */
export function corpusAgents(id: string, main: string): Dict {
  if (!id) return { tasks: [], main_progress: main };
  const corpus = JSON.parse(readFileSync(CORPUS, "utf8")) as Dict;
  const got = (corpus.cases as Dict[]).find((c) => c.id === id);
  if (!got) throw new Error("no corpus case " + JSON.stringify(id));
  return { main_progress: main, tasks: ((got.input as Dict).tasks as Dict[])
    .map((t) => ({ task: { ...t.task as Dict, label: "" }, usage: t.usage,
      meta: t.meta, shares: t.shares,
      progress: String((t.task as Dict).label ?? "") })) };
}
export type ReceiptCase = { doc: string; cols: number; hide: string[] };
export type AccountCase = { doc: string; cols: number; hide: string[];
  indent: number };

/** The account case's row, as the 💳 row under the footer line or above
 * the prompt draws it; none under the hide path `account`. */
export function drawAccount(st: Settings, fig: Dict, c: AccountCase):
  Span[] {
  return inZone(fig, () => accountLine(st, fig, c.hide, c.cols, "",
    c.indent));
}

/** The band case's rows: with `agents` or `progress`, the document's
 * `agents` from the corpus (corpusAgents), drawn in the tree under `cap`. */
export function drawBand(st: Settings, fig0: Dict, c: BandCase): Span[][] {
  const fig = c.agents !== undefined || c.progress !== undefined
    ? { ...fig0, agents: corpusAgents(c.agents ?? "", c.progress ?? "") }
    : fig0;
  return inZone(fig, () => bandLines(st, fig, c.cols, c.hide,
    { rate: c.rate, phase: c.phase, place: c.place, places: c.places,
      cap: c.cap }));
}

/** The band's tree with subagents, on TREE_DOC: each case of the corpus
 * that has some, at each width, with the main thread's progress update;
 * one under a cap that folds siblings into `… N more`; one that hides the
 * progress updates; and once between turns. */
function treeCases(): BandCase[] {
  const base = { doc: TREE_DOC, hide: [] as string[], phase: "running" as
    Phase, rate: RATE, place: "above" as Place, places: PLACES,
    progress: TREE_PROGRESS };
  const out: BandCase[] = [];
  for (const agents of TREE_AGENTS) {
    for (const cols of [236, ...COLS]) out.push({ ...base, cols, agents });
  }
  out.push({ ...base, cols: 200, agents: TREE_AGENTS[0], cap: 3 });
  out.push({ ...base, cols: 200, agents: TREE_AGENTS[0], cap: 0 });
  out.push({ ...base, cols: 200, agents: TREE_AGENTS[1],
    hide: ["*.chat.progress"] });
  out.push({ ...base, cols: 200, agents: TREE_AGENTS[1], phase: "done" });
  return out;
}

// The tree's cases: a document, the corpus cases whose tasks are its
// subagents, and the main thread's progress update.
const TREE_DOC = "status/01-baseline@196";
const TREE_AGENTS = ["01-mixed@220", "03-tree@220", "02-parked@220"];
const TREE_PROGRESS = "Checking the binary for subagentStatusLine, then " +
  "the changelog for a hook that replaces it";

/** The receipt case's lines. */
export function drawReceipt(st: Settings, fig: Dict, c: ReceiptCase):
  Span[][] {
  return inZone(fig, () => receiptLines(st, fig, c.cols, c.hide));
}

/** The start line. */
export function drawStart(fig: Dict): Span[] {
  return inZone(fig, () => startLine(fig));
}

/** Every band case of one document. */
function bandCases(doc: string): BandCase[] {
  const out: BandCase[] = [];
  for (const cols of COLS) {
    for (const phase of ["running", "done"] as const) {
      out.push({ doc, cols, hide: [], phase, rate: null });
    }
  }
  for (const hide of HIDES) {
    out.push({ doc, cols: HIDE_COLS, hide: [...hide], phase: "running",
      rate: null });
  }
  out.push({ doc, cols: RATE_COLS, hide: [], phase: "running", rate: RATE });
  for (const place of ["above", "footer"] as const) {
    out.push({ doc, cols: PLACE_COLS, hide: [], phase: "running", rate: null,
      place, places: PLACES });
  }
  return out;
}

/** Every account case of one document: at each width and hiding the band
 * cases take, and once indented, as above the prompt. */
function accountCases(doc: string): AccountCase[] {
  return [...COLS.map((cols) => ({ doc, cols, hide: [], indent: 0 })),
    ...HIDES.map((hide) => ({ doc, cols: HIDE_COLS, hide: [...hide],
      indent: 0 })),
    { doc, cols: HIDE_COLS, hide: [], indent: 2 }];
}

/** The account cases of SHED_DOC, from wide enough for every piece down
 * to too narrow for any but the cut 💳, a piece shed at each step. */
function shedCases(): AccountCase[] {
  const out: AccountCase[] = [];
  for (let cols = 200; cols >= 30; cols -= 10) {
    out.push({ doc: SHED_DOC, cols, hide: [], indent: 0 });
  }
  return out;
}

/** Every receipt case of one document. */
function receiptCases(doc: string): ReceiptCase[] {
  const out: ReceiptCase[] = COLS.map((cols) => ({ doc, cols, hide: [] }));
  for (const hide of HIDES) {
    out.push({ doc, cols: HIDE_COLS, hide: [...hide] });
  }
  return out;
}

const rowsJson = (rows: Span[][]): unknown[][] =>
  rows.map((r) => r.map(spanJson));

/** The cases under one profile's settings, as the file's text after its
 * settings line. */
function cases(st: Settings): string {
  const band: string[] = [], receipt: string[] = [], start: string[] = [];
  const account: string[] = [];
  const accountCase = (c: AccountCase, fig: Dict, same: string[]): string => {
    const row = drawAccount(st, fig, c);
    return JSON.stringify({ ...c, same, row: row.map(spanJson),
      line: join(row) });
  };
  for (const [id, same, fig] of documents("status")) {
    for (const c of bandCases(id)) {
      const rows = drawBand(st, fig, c);
      band.push(JSON.stringify({ ...c, same, rows: rowsJson(rows),
        lines: rows.map((r) => join(r)) }));
    }
    for (const c of accountCases(id)) account.push(accountCase(c, fig, same));
    const s = drawStart(fig);
    start.push(JSON.stringify({ doc: id, same, spans: s.map(spanJson),
      line: join(s) }));
  }
  for (const c of shedCases()) {
    account.push(accountCase(c, document(c.doc), []));
  }
  for (const c of treeCases()) {
    const rows = drawBand(st, document(c.doc), c);
    band.push(JSON.stringify({ ...c, same: [], rows: rowsJson(rows),
      lines: rows.map((r) => join(r)) }));
  }
  for (const [id, same, fig] of documents("cost")) {
    for (const c of receiptCases(id)) {
      const got = drawReceipt(st, fig, c);
      receipt.push(JSON.stringify({ ...c, same, rows: rowsJson(got),
        lines: got.map((r) => join(r)) }));
    }
  }
  const list = (name: string, lines: string[]): string =>
    ' "' + name + '": [\n' + lines.map((l) => "  " + l).join(",\n") +
    "\n ]";
  return [list("band", band), list("receipt", receipt), list("start", start),
    list("account", account)].join(",\n") + "}\n";
}

/** Every file, by name; see gen-grid-cases.ts's generate. */
export function generate(): Map<string, string> {
  const groups = new Map<string, string[]>();
  for (const name of Object.keys(PROFILES)) {
    const body = cases(settings(PROFILES[name]));
    groups.set(body, [...(groups.get(body) ?? []), name]);
  }
  return new Map([...groups].map(([body, names]) => [
    names.join("-") + ".json",
    '{"settings": ' + JSON.stringify({ profiles: Object.fromEntries(
      names.map((n) => [n, PROFILES[n]])) }) + ",\n" + body]));
}

if (import.meta.main) {
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
  for (const [name, text] of generate()) {
    writeFileSync(pathJoin(OUT, name), text);
    const j = JSON.parse(text);
    process.stdout.write(`rows/${name.padEnd(22)} ${j.band.length} band, ` +
      `${j.receipt.length} receipt, ${j.start.length} start and ` +
      `${j.account.length} account cases\n`);
  }
}
