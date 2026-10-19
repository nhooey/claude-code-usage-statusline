// Write the grid's shared cases, tests/fixtures/grid/, from src/grid.ts.
//
//   node mod/tools/gen-grid-cases.ts
//
// Unlike the rest of tests/fixtures/, these are written by the TypeScript:
// the redesigned grid is built here first, and the Python cells the agent
// panel keeps are brought to it after, checked against these cases.
// mod/test/grid.test.ts runs every case and fails when this generator's
// output differs from what is committed, so regenerating is the only way
// to change them.
//
// One file per terminal profile, since the profile widens 🧩, 🧠 and 💰 by a
// column; profiles whose cases come out the same share one.  Each holds:
//
//   settings  the profiles, each with the environment it is read from
//   rows      the mockup's sample rows, by id, as plain data: each row's
//             scope, depth, label pieces (path, spans, drop rank) and
//             cells (spans by GRID_CELLS key).  The grid takes these and
//             nothing else, so a port lays them out without the renderers.
//   layout    one case a line: the rows laid out (`rows`, by id), `cols`,
//             `hide`, `fixed`, and the `keys` layout() keeps
//   draw      one case a line: a row (`row`, by id) drawn on `keys` at
//             `cols` with `hide` and `spill`, and what draw() makes of it,
//             as `spans` and as `line`, the spans joined with their escape
//             codes
//
// A span is written as an array, [text] for plain text and [text, colour,
// dim, bold, bg] otherwise, trailing defaults left off.
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join as pathJoin } from "node:path";
import { fileURLToPath } from "node:url";
import { settings } from "../src/formatting.ts";
import type { Env, Settings } from "../src/formatting.ts";
import { join } from "../src/spans.ts";
import type { Span } from "../src/spans.ts";
import { draw, hidden, layout } from "../src/grid.ts";
import type { Row } from "../src/grid.ts";
import { sample, runningMain } from "./layout-mockup.ts";

export const OUT = pathJoin(dirname(fileURLToPath(import.meta.url)), "..",
  "..", "tests", "fixtures", "grid");

/** Each profile, by the environment it is read from. */
export const PROFILES: { readonly [name: string]: Env } = {
  unknown: {},
  jediterm: { TERMINAL_EMULATOR: "JetBrains-JediTerm" },
  iterm: { TERM_PROGRAM: "iTerm.app" },
  tmux: { TMUX: "/tmp/tmux-501/default,1,0" },
};

// Down past the drop: at 11 columns a row nested two deep has no room for
// its label, and at 6 its chrome alone runs past the right edge.
const COLS = [200, 160, 150, 125, 100, 80, 60, 40, 20, 11, 6];
// Hide sets that reach each rule: a whole scope, a group on every row, one
// metric on one row, label pieces, a column hidden on some rows only.
const HIDES: readonly (readonly string[])[] = [
  [], ["account"], ["*.work"], ["turn.time.eta"],
  ["session.workspace", "*.clock.time"], ["*.state.rate"],
  ["*.plan", "main", "agent.chat"], ["session", "turn.chat", "agent.time"],
];

/** A span as the cases write it; see the header. */
export function spanJson(s: Span): unknown[] {
  const out: unknown[] = [s.text, s.colour, s.dim, s.bold, s.bg];
  while (out.length > 1 &&
    (out[out.length - 1] === null || out[out.length - 1] === false)) {
    out.pop();
  }
  return out;
}

/** A span read back from the cases. */
export function spanFrom(a: readonly unknown[]): Span {
  return { text: a[0] as string, colour: (a[1] ?? null) as string | null,
    dim: Boolean(a[2]), bold: Boolean(a[3]), bg: (a[4] ?? null) as string | null };
}

function rowJson(r: Row): unknown {
  const out: { [k: string]: unknown } = { scope: r.scope };
  if (r.depth !== undefined) out.depth = r.depth;
  out.label = r.label.map((p) =>
    ({ path: p.path, spans: p.spans.map(spanJson), drop: p.drop }));
  out.cells = Object.fromEntries(Object.entries(r.cells)
    .map(([k, v]) => [k, v.map(spanJson)]));
  return out;
}

/** A row read back from the cases. */
export function rowFrom(j: unknown): Row {
  const r = j as { scope: string; depth?: number;
    label: { path: string; spans: unknown[][]; drop: number }[];
    cells: { [k: string]: unknown[][] } };
  return { scope: r.scope, ...(r.depth === undefined ? {} : { depth: r.depth }),
    label: r.label.map((p) =>
      ({ path: p.path, spans: p.spans.map(spanFrom), drop: p.drop })),
    cells: Object.fromEntries(Object.entries(r.cells)
      .map(([k, v]) => [k, v.map(spanFrom)])) };
}

/** The sample rows by id: every row the mockup can draw. */
function rows(st: Settings): Map<string, Row> {
  const s = sample(st);
  return new Map<string, Row>([
    ["account", s.account], ["turn", s.turn], ["main", s.main],
    ["main.running", runningMain(s.main)], ["session", s.session],
    ["receipt.turn", s.receipt[0]], ["receipt.session", s.receipt[1]],
    ["agent.1", s.agents[0]], ["agent.2", s.agents[1]],
  ]);
}

/** The cases under one profile's settings, as the file's text after its
 * settings line. */
function cases(st: Settings): string {
  const table = rows(st);
  const scope = (id: string): string => table.get(id)!.scope;
  const layouts: string[] = [], draws: string[] = [];
  const seen = new Set<string>();
  for (const cols of COLS) {
    for (const hide of HIDES) {
      const shown = (ids: string[]): string[] =>
        ids.filter((id) => !hidden(hide, scope(id)));
      const band = shown(["account", "turn", "main", "session"]);
      const receipt = shown(["receipt.turn", "receipt.session"]);
      const agents = shown(["agent.1", "agent.2"]);
      // The mockup's two grids: every row the design can draw, or the rows
      // drawn with agents to each depth.
      const sets: [boolean, string[], string[]][] = [
        [true, [...band, ...receipt, ...agents], agents],
        ...[0, 1, 2].map((d): [boolean, string[], string[]] => {
          const a = agents.filter((id) => table.get(id)!.depth! <= d);
          return [false, [...band, ...receipt, ...a], a];
        }),
      ];
      for (const [fixed, ids, drawnAgents] of sets) {
        if (!ids.length) continue;
        const key = JSON.stringify([cols, hide, fixed, ids]);
        if (seen.has(key)) continue;
        seen.add(key);
        const keys = layout(st, ids.map((id) => table.get(id)!), cols, hide,
          fixed);
        layouts.push(JSON.stringify({ cols, hide, fixed, rows: ids, keys }));
        const drawn = [...band, ...(band.includes("main")
          ? ["main.running"] : []), ...receipt, ...drawnAgents];
        for (const id of drawn) {
          for (const spill of [true, false]) {
            const dk = JSON.stringify([id, keys, cols, hide, spill]);
            if (seen.has(dk)) continue;
            seen.add(dk);
            const out = draw(st, table.get(id)!, keys, cols, hide, spill);
            draws.push(JSON.stringify({ row: id, keys, cols, hide, spill,
              spans: out.map(spanJson), line: join(out) }));
          }
        }
      }
    }
  }
  const rowLines = [...table].map(([id, r]) =>
    "  " + JSON.stringify(id) + ": " + JSON.stringify(rowJson(r)));
  return ' "rows": {\n' + rowLines.join(",\n") +
    '\n },\n "layout": [\n' + layouts.map((l) => "  " + l).join(",\n") +
    '\n ],\n "draw": [\n' + draws.map((l) => "  " + l).join(",\n") +
    "\n ]}\n";
}

/** Every file, by name.  Profiles whose cases come out the same share a
 * file, named for them all, which says so: the profiles differ only in
 * glyphs the sample rows do not draw. */
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
    process.stdout.write(`grid/${name.padEnd(22)} ${j.layout.length} layout` +
      ` and ${j.draw.length} draw cases\n`);
  }
}
