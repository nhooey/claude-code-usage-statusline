// The redesigned grid: one scope per row, one column per metric.
//
// agents/plans/redesign.md has the design.  Every row of the band, the
// receipt and the agent panel draws the columns of GRID_CELLS in one order;
// a row with nothing for a column leaves it blank, so the columns hold.  On
// a narrow terminal a row's label sheds its ranked parts, then is cut, and
// past LABEL_MIN columns whole columns drop from every row at once, in
// DROP_ORDER.  `--hide` paths remove columns and label parts.
//
// The grid knows nothing about how a cell was drawn.  A row is plain data,
// its label's pieces and its cells as spans, so the band, the receipt and
// the panel can hand it their own, and the shared cases under
// tests/fixtures/grid/ can carry a row as JSON.  The rules' constants are
// spec.ts's; the widths that depend on the terminal profile come from the
// Settings, as claude_subagent_render.ts computes them.  Nothing here joins
// spans into escape codes: that is the printing's job.
import {
  CHROME_DEPTH, DROP_ORDER, E_PCT, GRID_CELLS, GRID_SCOPES, LABEL_MIN,
  PANEL_CHROME, RIGHT_EDGE, VAL_W, VAL2_W,
} from "./spec.ts";
import { padVal, seg, visWidth } from "./formatting.ts";
import type { Settings } from "./formatting.ts";
import { cut, span, spans, width } from "./spans.ts";
import type { Span } from "./spans.ts";
import {
  A_CLOCK_W, A_LIMIT_W, A_LIMIT_WEEK_W, A_RATE_W, A_SPLIT_W,
  aCtxW, aDiffW, aEtaW,
} from "./claude_subagent_render.ts";

/** A part of a row's label, with the path --hide names it by, under the
 * row's scope.  A piece with a `drop` rank leaves the label whole, lowest
 * rank first, before the label is cut short; 0 is only ever cut. */
export type Piece = {
  readonly path: string;
  readonly spans: readonly Span[];
  readonly drop: number;
};

/** One row: its scope (GRID_SCOPES), how deep in the agent panel it sits
 * (absent for a row outside the panel), its label, and its cells by
 * GRID_CELLS key.  A key that is missing is a column the row has nothing
 * for; one that is present is drawn, even as no spans. */
export type Row = {
  readonly scope: string;
  readonly depth?: number;
  readonly label: readonly Piece[];
  readonly cells: { readonly [key: string]: readonly Span[] };
};

/** The cell's own width under `st`, gap aside: GRID_CELLS names a fixed
 * number or the rule the width is computed by, since the terminal profile
 * widens 🧩, 🧠 and 💰 by a column. */
export function cellWidth(st: Settings, rule: number | string): number {
  if (typeof rule === "number") return rule;
  switch (rule) {
    case "A_RATE_W": return A_RATE_W;
    case "COST_W": return visWidth(st.sCost, st.widths) + 4;
    case "A_CTX_W": return aCtxW(st);
    case "TOK_W": return visWidth(st.sTok, st.widths) + VAL_W + VAL2_W;
    case "A_CLOCK_W": return A_CLOCK_W;
    case "A_ETA_W": return aEtaW(st);
    case "A_SPLIT_W": return A_SPLIT_W;
    case "A_LIMIT_W": return A_LIMIT_W;
    case "A_LIMIT_WEEK_W": return A_LIMIT_WEEK_W;
    case "A_DIFF_W": return aDiffW(st);
  }
  throw new Error("no width rule " + rule);
}

/** fnmatch.fnmatchcase(name, pat): `*`, `?` and `[...]` with `!` for
 * not, the rest literal. */
function fnmatch(name: string, pat: string): boolean {
  let re = "";
  const cps = Array.from(pat);
  for (let i = 0; i < cps.length; i++) {
    const c = cps[i];
    if (c === "*") re += "[\\s\\S]*";
    else if (c === "?") re += "[\\s\\S]";
    else if (c === "[") {
      let j = i + 1;
      if (cps[j] === "!") j++;
      if (cps[j] === "]") j++;
      while (j < cps.length && cps[j] !== "]") j++;
      if (j >= cps.length) {
        re += "\\[";
        continue;
      }
      let body = cps.slice(i + 1, j).join("").replace(/\\/g, "\\\\");
      if (body[0] === "!") body = "^" + body.slice(1);
      else if (body[0] === "^") body = "\\" + body;
      re += "[" + body + "]";
      i = j;
    } else re += c.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
  }
  return new RegExp("^(?:" + re + ")$", "u").test(name);
}

/** Whether a pattern names `path` or a path above it: "turn.time" hides
 * "turn.time.eta", and "*" stands for any one part. */
export function hidden(patterns: readonly string[], path: string): boolean {
  const parts = path.split(".");
  return patterns.some((p) => {
    const want = p.split(".");
    return want.length <= parts.length &&
      want.every((w, i) => fnmatch(parts[i], w));
  });
}

/** What Claude Code draws before a panel row: PANEL_CHROME columns at
 * depth 1, blanks then the pointer, and two more blanks per level below
 * it.  A row outside the panel has none. */
export function chrome(depth: number | undefined): Span[] {
  if (depth === undefined) return [];
  return [span(" ".repeat(PANEL_CHROME - 2 + 2 * (depth - 1)) + "◯ ", null,
    true)];
}

/** The row's label in `room` columns: the ranked pieces leave first,
 * lowest rank first, then what is left is cut, keeping its colours. */
export function labelText(st: Settings, row: Row,
  patterns: readonly string[], room: number): Span[] {
  let pieces = row.label.filter((p) =>
    !hidden(patterns, row.scope + "." + p.path));
  const ranks = [...new Set(pieces.map((p) => p.drop).filter((d) => d))]
    .sort((a, b) => a - b);
  const all = (): Span[] => pieces.flatMap((p) => p.spans);
  for (const rank of ranks) {
    if (width(all(), st.widths) <= room) break;
    pieces = pieces.filter((p) => p.drop !== rank);
  }
  const out = all();
  return width(out, st.widths) > room ? cut(out, room, st.widths) : out;
}

/** Whether the row draws column `key`: it has a figure for it, and no
 * pattern hides it on the row's scope. */
function shows(row: Row, key: string, path: string,
  patterns: readonly string[]): boolean {
  return Object.hasOwn(row.cells, key) &&
    !hidden(patterns, row.scope + "." + path);
}

/** Whether the patterns hide 🧠's ٪ share of the window on every scope,
 * so its column can give the share's room back. */
function shareGone(patterns: readonly string[]): boolean {
  return GRID_SCOPES.every((s) => hidden(patterns, s + ".context.share"));
}

/** The columns 🧠's size takes without its share: the mark, then three
 * digits and a unit, "🧠316k", with no blank between (asked 2026-10-19). */
const CTX_SIZE_W = 4;

/** A column's width under `patterns`: 🧠's, where every scope hides its
 * share, only its mark and CTX_SIZE_W (asked 2026-10-19). */
function colWidth(st: Settings, c: { key: string; width: number | string },
  patterns: readonly string[]): number {
  return c.key === "ctx" && shareGone(patterns)
    ? visWidth(st.sCtx.trimEnd(), st.widths) + CTX_SIZE_W
    : cellWidth(st, c.width);
}

/** 🧠's size squeezed into `room`: a growth's "+" goes, then an
 * estimate's "~", then a figure's one decimal, rounded half up, "-1.5k" to
 * "-2k". */
function squeeze(st: Settings, text: string, room: number): string {
  let t = text.replace(/^\+/, "");
  if (visWidth(t, st.widths) > room) t = t.replace(/^~/, "");
  const m = /^(-?)(\d+\.\d)(\D*)$/.exec(t);
  if (visWidth(t, st.widths) > room && m) {
    t = m[1] + String(Math.floor(Number(m[2]) + 0.5)) + m[3];
  }
  return t;
}

/** The row's figure for column `key`, `w` wide: 🧠's without the ٪ share
 * of the window that ends it, where a pattern hides `context.share` on the
 * row's scope: the mark, no blank, and the size squeezed and set flush
 * right, so the sizes of the rows stack. */
function figure(st: Settings, row: Row, key: string, w: number,
  patterns: readonly string[]): readonly Span[] {
  const f = row.cells[key];
  if (key !== "ctx" || !f.length ||
    !hidden(patterns, row.scope + ".context.share")) return f;
  const [mark, ...rest] = f[f.length - 1].text.trimEnd().endsWith(E_PCT)
    ? f.slice(0, -1) : f;
  const head = mark.text.trimEnd();
  const room = w - visWidth(head, st.widths);
  const text = squeeze(st, rest.map((s) => s.text).join("").trim(), room);
  const style = rest.find((s) => s.text.trim()) ?? mark;
  return [{ ...mark, text: head }, { ...style,
    text: padVal(st, room, text) }];
}

/** The columns every row draws, after --hide and the narrow-window drop,
 * as GRID_CELLS keys in order.
 *
 * With `fixed`, `rows` is every row the design can draw, and the chrome is
 * kept for CHROME_DEPTH levels of nesting whether any agent runs or not:
 * the columns then follow from the width and --hide alone, so the mod and
 * each panel row's process reach them apart.  Without it they follow from
 * the rows drawn, and move when a nested agent appears. */
export function layout(st: Settings, rows: readonly Row[], cols: number,
  patterns: readonly string[], fixed = true): string[] {
  const keys = GRID_CELLS.filter((c) =>
    rows.some((r) => shows(r, c.key, c.hide, patterns))).map((c) => c.key);
  const room = new Map(GRID_CELLS.map((c) =>
    [c.key, colWidth(st, c, patterns) + c.gap]));
  const lead = fixed ? width(chrome(CHROME_DEPTH), st.widths)
    : Math.max(0, ...rows.map((r) => width(chrome(r.depth), st.widths)));
  for (const k of DROP_ORDER) {
    const used = keys.reduce((n, c) => n + room.get(c)!, 0);
    if (cols - RIGHT_EDGE - lead - used >= LABEL_MIN) break;
    const i = keys.indexOf(k);
    if (i >= 0) keys.splice(i, 1);
  }
  return keys;
}

/** One row on the columns `keys`.  With `spill`, the label runs on over
 * the row's own leading blank columns, up to its first figure, instead of
 * stopping where the first column starts.  Every row ends RIGHT_EDGE
 * columns short of the terminal's edge, and never runs past that: a label
 * with no room draws nothing, not even a `…`, and a row whose chrome and
 * cells are wider than the terminal leaves, at a width too narrow for the
 * drop to help, is cut there like a label. */
export function draw(st: Settings, row: Row, keys: readonly string[],
  cols: number, patterns: readonly string[], spill = true): Span[] {
  const cells: [number, Span[] | null][] = [];
  for (const c of GRID_CELLS) {
    if (!keys.includes(c.key)) continue;
    const w = colWidth(st, c, patterns);
    cells.push([c.gap + w, shows(row, c.key, c.hide, patterns)
      ? [span(" ".repeat(c.gap)),
        ...seg(st, w, spans(figure(st, row, c.key, w, patterns)))]
      : null]);
  }
  const head = chrome(row.depth);
  const end = cols - RIGHT_EDGE;
  let room = end - width(head, st.widths) -
    cells.reduce((n, [w]) => n + w, 0);
  while (spill && cells.length && cells[0][1] === null) {
    room += cells.shift()![0];
  }
  const right = cells.flatMap(([w, c]) => c ?? [span(" ".repeat(w))]);
  const out = [...head, ...seg(st, room, labelText(st, row, patterns, room)),
    ...right];
  return width(out, st.widths) > end ? cut(out, end, st.widths) : out;
}
