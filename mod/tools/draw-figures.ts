// Draw a figures document as the band, the account row, the rows above
// the prompt or under the footer line, the receipt or the start line, to
// look at the grid's rows from real figures in a terminal.
//
//   node mod/tools/draw-figures.ts FILE [--cols N] [--part PART]
//        [--phase running|done] [--hide PATH ...] [--rate N]
//        [--home DIR] [--status STATUS_FILE]
//        [--rows JSON] [--right-edge N] [--inset N]
//        [--hint TEXT] [--plain]
//
// FILE is a figures document, such as one of tests/fixtures/figures/.
// A status document draws the band's 🎤 🤖 🎮 rows wherever they are
// placed (--part band, the default), the 💳 account row (--part
// account), the start line (--part start), what the mod draws above the
// prompt (--part above): the rows whose rows.<row>.place is "above", the
// account row first where it is one of them, each indented --inset
// columns; or what it draws under
// Claude Code's footer line (--part footer): --hint, standing for Claude
// Code's own line, then the rows whose place is "footer", the account
// row first where it is one of them, each after --inset blanks, the
// columns Claude Code's container stands in; or, with account-place
// "tail" (--part tail), the account as the tail of that line, after
// Claude Code's " · ".  --inset also draws the band (but for the rows
// above the prompt) and the account row that much narrower, as the mod
// does under the footer line, and the receipt's 🎤 🤖 🎮 rows that far in
// and that much narrower, as the mod stamps them to stack on those;
// --right-edge is the columns every row ends short of the terminal's
// edge, RIGHT_EDGE by default.  The mod's own are --inset 2 (hint-inset)
// and --right-edge 5 (right-edge, derived from the default places).  A
// cost document
// draws the receipt.  --rate is the 🛫 the mod would pass, in tokens a
// second.  --home stands for HOME, "${HOME}" by default, which is what
// the fixtures' paths are written under.
// --rows is a rows table as a configuration file sets it, such as
// '{"agent": {"transcript": true}}', merged field by field over the
// defaults file's (mod/defaults/config.jsonc): each row's place picks the
// part it is drawn in, its live when the band draws it (the done phase
// draws those "always"), and its transcript whether the receipt stamps
// it; 🤖 on the receipt comes from --status, a status document standing
// for the band's last one, as the mod keeps it.
//
// The clock is drawn in the document's `clock.tz`, as the edge would set
// it, and the terminal's profile is read from the environment.
import { readFileSync } from "node:fs";
import { dirname, join as pathJoin } from "node:path";
import { fileURLToPath } from "node:url";
import { settings, stripAnsi } from "../src/formatting.ts";
import { join, span } from "../src/spans.ts";
import type { Span } from "../src/spans.ts";
import { pyRstrip } from "../src/py.ts";
import type { Dict } from "../src/py.ts";
import {
  FOOTER_JOIN, ROW_NAMES, accountLine, bandLines, bandRows, footerTail,
} from "../src/band.ts";
import type { Live, Phase, Place } from "../src/band.ts";
import { receiptLines, startLine } from "../src/receipt.ts";
import { RIGHT_EDGE } from "../src/spec.ts";
import { DEFAULTS_REL, parseDefaults } from "../src/config.ts";
import type { Rows } from "../src/config.ts";
import { OPTIONS } from "../src/options_spec.ts";

const USAGE = "usage: draw-figures.ts FILE [--cols N] " +
  "[--part {band,account,above,footer,tail,receipt,start}] " +
  "[--phase {running,done}] " +
  "[--hide PATH] [--rate N] [--home DIR] [--status STATUS_FILE] " +
  "[--rows JSON] [--right-edge N] [--inset N] " +
  "[--hint TEXT] [--plain]";

function fail(msg: string): never {
  process.stderr.write(USAGE + "\ndraw-figures.ts: error: " + msg + "\n");
  process.exit(2);
}

function read(path: string): Dict {
  return JSON.parse(readFileSync(path, "utf8")) as Dict;
}

const argv = process.argv.slice(2);
let file = "", cols = 160, part = "", phase: Phase = "running";
let rate: number | null = null, home = "${HOME}", statusFile = "", plain = false;
let rowsArg = "";
let rightEdge = RIGHT_EDGE, inset = 0;
let hint = "-- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle)";
const hide: string[] = [];
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  const next = (): string => i + 1 < argv.length ? argv[++i]
    : fail("argument " + a + ": expected one argument");
  if (a === "-h" || a === "--help") {
    process.stdout.write(USAGE + "\n");
    process.exit(0);
  } else if (a === "--plain") plain = true;
  else if (a === "--cols") cols = Number(next());
  else if (a === "--part") part = next();
  else if (a === "--phase") phase = next() as Phase;
  else if (a === "--hide") hide.push(next());
  else if (a === "--rows") rowsArg = next();
  else if (a === "--rate") rate = Number(next());
  else if (a === "--home") home = next();
  else if (a === "--status") statusFile = next();
  else if (a === "--right-edge") rightEdge = Number(next());
  else if (a === "--inset") inset = Number(next());
  else if (a === "--hint") hint = next();
  else if (a.startsWith("--")) fail("unrecognized arguments: " + a);
  else file = a;
}
if (!file) fail("the figures document is required");
if (!Number.isInteger(cols) || cols <= 0) fail("--cols takes a width");
if (!["running", "done"].includes(phase)) fail("--phase: invalid choice");
if (!Number.isInteger(rightEdge) || rightEdge < 0) fail("--right-edge takes a width");
if (!Number.isInteger(inset) || inset < 0) fail("--inset takes a width");

/** The defaults file's rows table with --rows over it, field by field. */
function rowsOf(arg: string): Rows {
  const path = pathJoin(dirname(fileURLToPath(import.meta.url)), "..",
    DEFAULTS_REL);
  const rows = structuredClone(
    parseDefaults(path, readFileSync(path, "utf8")).rows as Rows);
  if (!arg) return rows;
  let got: unknown;
  try {
    got = JSON.parse(arg);
  } catch {
    fail("--rows takes a JSON object");
  }
  if (typeof got !== "object" || got === null || Array.isArray(got)) {
    fail("--rows takes a JSON object");
  }
  const fields = OPTIONS.rows.fields as { readonly [f: string]:
    { readonly type: string; readonly items?: readonly string[] } };
  for (const [row, rec] of Object.entries(got as Dict)) {
    if (!(row in rows)) fail("--rows: no row " + JSON.stringify(row));
    for (const [field, v] of Object.entries(rec as Dict)) {
      const f = fields[field];
      const ok = f !== undefined && (f.type === "bool"
        ? typeof v === "boolean" : (f.items ?? []).includes(v as string));
      if (!ok) {
        fail("--rows: " + row + "." + field + " cannot be " +
          JSON.stringify(v));
      }
      rows[row][field] = v as string | boolean;
    }
  }
  return rows;
}
const rows = rowsOf(rowsArg);

const fig = read(file);
const mode = fig.mode as string;
part ||= mode === "cost" ? "receipt" : "band";
if ((part === "receipt") !== (mode === "cost")) {
  fail("--part " + part + " needs a " +
    (part === "receipt" ? "cost" : "status") + " document");
}
const tz = (fig.clock as Dict).tz as string | null;
if (tz) process.env.TZ = tz;
const st = settings(process.env, true, false, rightEdge);

const live = Object.fromEntries(ROW_NAMES.map((r) =>
  [r, rows[r].live as Live]));
const places = Object.fromEntries(ROW_NAMES.map((r) =>
  [r, rows[r].place as Place]));
const stamped = ROW_NAMES.filter((r) => rows[r].transcript);
// Above the prompt the band starts at the terminal's left edge, so its
// rows are indented --inset columns rather than drawn narrower.
const band = (place?: Place): Span[][] =>
  bandLines(st, fig, cols, hide, place === "above"
    ? { rate, phase, live, place, places, indent: inset }
    : { rate, phase, live, place, places, inset });
const account = (place?: Place): Span[][] => {
  const row = place === "above"
    ? accountLine(st, fig, hide, cols, home, inset)
    : accountLine(st, fig, hide, cols - inset, home);
  return row.length ? [row] : [];
};
// The account row where `place` is its place and the phase draws it.
const accountIn = (place: Place): Span[][] =>
  rows.account.place === place && (rows.account.live === "always" ||
    (rows.account.live === "running" && phase === "running"))
    ? account(place) : [];
let lines: Span[][];
if (part === "band") {
  lines = band();
} else if (part === "account") {
  lines = account();
} else if (part === "above") {
  lines = [...accountIn("above"), ...band("above")];
} else if (part === "footer") {
  const lead = [span(" ".repeat(inset))];
  lines = [[span(hint)], ...accountIn("footer"), ...band("footer")]
    .map((l) => inset ? [...lead, ...l] : l);
} else if (part === "tail") {
  // Claude Code's line two blanks in, as footerTail reckons it; --hint
  // holds the mode's pill whole, so none is counted apart.
  const tail = footerTail(st, fig, hide, hint, cols, undefined, home);
  lines = [[span("  " + hint + (tail ? FOOTER_JOIN + tail : ""))]];
} else if (part === "start") {
  lines = [startLine(fig, hide)];
} else if (part === "receipt") {
  const status = statusFile ? read(statusFile) : null;
  const main = status
    ? bandRows(st, status, { rate: null, phase: "done" }).main : null;
  lines = receiptLines(st, fig, cols, hide, false, main, stamped, inset);
} else {
  fail("--part: invalid choice: '" + part + "'");
}
// In the set Claude Code would draw this terminal's rows in.
const text = lines.map((l) => pyRstrip(join(l, false, false, st.truecolor)))
  .join("\n");
process.stdout.write((plain ? stripAnsi(text) : text) + "\n");
