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
//             at `cols` under `hide` in `phase` with the mod's 🛫, `rate`;
//             `rows`, each row's spans top to bottom, and `lines`, the
//             same joined with their escape codes
//   receipt   one case a line: a cost document drawn at `cols` under
//             `hide`, its 📦 🌿 from the status document `workspace` (or
//             none); its two lines as spans, `rows`, and joined,
//             `lines`
//   start     one case a line: a status document's start line, as `spans`
//             and as `line`
//
// HOME is "${HOME}", the placeholder the documents' paths are written
// under, and each document's clock is drawn in its own `clock.tz`.  A span
// is written as the grid's cases write one.
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync }
  from "node:fs";
import { dirname, join as pathJoin } from "node:path";
import { fileURLToPath } from "node:url";
import { settings } from "../src/formatting.ts";
import type { Settings } from "../src/formatting.ts";
import { join } from "../src/spans.ts";
import type { Span } from "../src/spans.ts";
import type { Dict } from "../src/py.ts";
import { bandLines, workspaceOf } from "../src/band.ts";
import type { Phase } from "../src/band.ts";
import { receiptLines, startLine } from "../src/receipt.ts";
import { PROFILES, spanJson } from "./gen-grid-cases.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
export const OUT = pathJoin(HERE, "..", "..", "tests", "fixtures", "rows");
export const FIGURES = pathJoin(HERE, "..", "..", "tests", "fixtures",
  "figures");

export const HOME = "${HOME}";
const COLS = [200, 155, 120, 80];
// Each scope's figures hidden, a group on every row, label pieces, and a
// whole scope with a label part of another, at one width.
const HIDES: readonly (readonly string[])[] = [
  ["*.work", "*.state.rate"], ["session.workspace", "*.clock.time"],
  ["turn", "main.chat", "*.plan"],
];
const HIDE_COLS = 155;
// The 🛫 the mod would pass, at one width: the documents carry the counts
// it works one out from, never the rate itself.
const RATE = 220, RATE_COLS = 200;
// The status document standing for the band's last, whose 📦 🌿 the receipt
// draws.
export const WORKSPACE = "status/01-baseline@196";

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
  phase: Phase; rate: number | null };
export type ReceiptCase = { doc: string; cols: number; hide: string[];
  workspace: string | null };

/** The band case's rows. */
export function drawBand(st: Settings, fig: Dict, c: BandCase): Span[][] {
  return inZone(fig, () => bandLines(st, fig, c.cols, c.hide,
    { home: HOME, rate: c.rate, phase: c.phase }));
}

/** The receipt case's lines. */
export function drawReceipt(st: Settings, fig: Dict, c: ReceiptCase):
  Span[][] {
  const ws = c.workspace === null ? null
    : workspaceOf(document(c.workspace), HOME);
  return inZone(fig, () => receiptLines(st, fig, c.cols, c.hide, ws));
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
  return out;
}

/** Every receipt case of one document. */
function receiptCases(doc: string): ReceiptCase[] {
  const out: ReceiptCase[] = COLS.map((cols) =>
    ({ doc, cols, hide: [], workspace: WORKSPACE }));
  for (const hide of HIDES) {
    out.push({ doc, cols: HIDE_COLS, hide: [...hide], workspace: WORKSPACE });
  }
  out.push({ doc, cols: HIDE_COLS, hide: [], workspace: null });
  return out;
}

const rowsJson = (rows: Span[][]): unknown[][] =>
  rows.map((r) => r.map(spanJson));

/** The cases under one profile's settings, as the file's text after its
 * settings line. */
function cases(st: Settings): string {
  const band: string[] = [], receipt: string[] = [], start: string[] = [];
  for (const [id, same, fig] of documents("status")) {
    for (const c of bandCases(id)) {
      const rows = drawBand(st, fig, c);
      band.push(JSON.stringify({ ...c, same, rows: rowsJson(rows),
        lines: rows.map((r) => join(r)) }));
    }
    const s = drawStart(fig);
    start.push(JSON.stringify({ doc: id, same, spans: s.map(spanJson),
      line: join(s) }));
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
  return [list("band", band), list("receipt", receipt), list("start", start)]
    .join(",\n") + "}\n";
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
      `${j.receipt.length} receipt and ${j.start.length} start cases\n`);
  }
}
