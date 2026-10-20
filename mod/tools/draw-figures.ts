// Draw a figures document as the band, the account row, the rows under
// the footer line, the receipt or the start line, to look at the grid's
// rows from real figures in a terminal.
//
//   node mod/tools/draw-figures.ts FILE [--cols N] [--part PART]
//        [--phase running|done] [--hide PATH ...] [--rate N]
//        [--home DIR] [--workspace STATUS_FILE]
//        [--sticky ROW,...] [--right-edge N] [--inset N]
//        [--hint TEXT] [--plain]
//
// FILE is a figures document, such as one of tests/fixtures/figures/.
// A status document draws the band (--part band, the default), the 💳
// account row (--part account), the start line (--part start), or what
// the mod draws under Claude Code's footer line with live-place
// "footer" (--part footer): --hint, standing for Claude Code's own line,
// then the account row and the band's rows, each after --inset blanks,
// the columns Claude Code's container stands in; or, with
// account-place "tail" (--part tail), the account as the tail of
// that line, after Claude Code's " · ".  --inset also draws the
// band and the account row that much narrower, as the mod does under the
// footer line, and the receipt's 🎤 🤖 🎮 rows that far in and that much
// narrower, as the mod stamps them to stack on those; --right-edge is the
// columns every row ends short of the terminal's edge, RIGHT_EDGE by
// default.  The mod's own, with live-place "footer", are --inset 2
// (hint-inset) and --right-edge 2 (right-edge, derived).  A cost document
// draws the receipt.  The
// receipt's 📦 🌿 come from --workspace, a status document standing for
// the band's last one, as the mod keeps it.  --rate is the 🛫 the mod
// would pass, in tokens a second.  --home stands for HOME, "${HOME}" by
// default, which is what the fixtures' paths are written under.
// --sticky names the rows, of turn, agent and session, that stay on the
// band once a turn ends, as `rows.<row>` `{"live": "always",
// "transcript": false}` in the mod's options: the band's done phase draws
// those, and the receipt the rest; 🤖 on the receipt comes from
// --workspace.
//
// The clock is drawn in the document's `clock.tz`, as the edge would set
// it, and the terminal's profile is read from the environment.
import { readFileSync } from "node:fs";
import { settings, stripAnsi } from "../src/formatting.ts";
import { join, span } from "../src/spans.ts";
import type { Span } from "../src/spans.ts";
import { pyRstrip } from "../src/py.ts";
import type { Dict } from "../src/py.ts";
import {
  FOOTER_JOIN, ROW_NAMES, accountLine, bandLines, bandRows, footerTail,
  workspaceOf,
} from "../src/band.ts";
import type { Phase, RowName } from "../src/band.ts";
import { receiptLines, startLine } from "../src/receipt.ts";
import { RIGHT_EDGE } from "../src/spec.ts";

const USAGE = "usage: draw-figures.ts FILE [--cols N] " +
  "[--part {band,account,footer,tail,receipt,start}] " +
  "[--phase {running,done}] " +
  "[--hide PATH] [--rate N] [--home DIR] [--workspace STATUS_FILE] " +
  "[--sticky {turn,agent,session},...] [--right-edge N] [--inset N] " +
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
let rate: number | null = null, home = "${HOME}", wsFile = "", plain = false;
let sticky: RowName[] = [];
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
  else if (a === "--sticky") sticky = next().split(",").filter(Boolean) as RowName[];
  else if (a === "--rate") rate = Number(next());
  else if (a === "--home") home = next();
  else if (a === "--workspace") wsFile = next();
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
if (!sticky.every((r) => ROW_NAMES.includes(r))) fail("--sticky: invalid choice");

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

const live = Object.fromEntries(sticky.map((r) => [r, "always"]));
const stamped = ROW_NAMES.filter((r) => !sticky.includes(r));
const band = (): Span[][] =>
  bandLines(st, fig, cols, hide, { home, rate, phase, live, inset });
const account = (): Span[][] => {
  const row = accountLine(st, fig, hide, cols - inset, home);
  return row.length ? [row] : [];
};
let lines: Span[][];
if (part === "band") {
  lines = band();
} else if (part === "account") {
  lines = account();
} else if (part === "footer") {
  const lead = [span(" ".repeat(inset))];
  lines = [[span(hint)], ...account(), ...band()]
    .map((l) => inset ? [...lead, ...l] : l);
} else if (part === "tail") {
  // Claude Code's line two blanks in, as footerTail reckons it; --hint
  // holds the mode's pill whole, so none is counted apart.
  const tail = footerTail(st, fig, hide, hint, cols, undefined, home);
  lines = [[span("  " + hint + (tail ? FOOTER_JOIN + tail : ""))]];
} else if (part === "start") {
  lines = [startLine(fig, hide)];
} else if (part === "receipt") {
  const status = wsFile ? read(wsFile) : null;
  const ws = status ? workspaceOf(status, home) : null;
  const main = status
    ? bandRows(st, status, { home, rate: null, phase: "done" }).main : null;
  lines = receiptLines(st, fig, cols, hide, ws, false, main, stamped, inset);
} else {
  fail("--part: invalid choice: '" + part + "'");
}
// In the set Claude Code would draw this terminal's rows in.
const text = lines.map((l) => pyRstrip(join(l, false, false, st.truecolor)))
  .join("\n");
process.stdout.write((plain ? stripAnsi(text) : text) + "\n");
