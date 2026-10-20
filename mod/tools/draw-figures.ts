// Draw a figures document as the band, the receipt or the start line, to
// look at the grid's rows from real figures in a terminal.
//
//   node mod/tools/draw-figures.ts FILE [--cols N] [--part PART]
//        [--phase running|done] [--hide PATH ...] [--rate N]
//        [--home DIR] [--workspace STATUS_FILE]
//        [--sticky ROW,...] [--plain]
//
// FILE is a figures document, such as one of tests/fixtures/figures/.
// A status document draws the band (--part band, the default) or the
// start line (--part start); a cost document draws the receipt.  The
// receipt's 📦 🌿 come from --workspace, a status document standing for
// the band's last one, as the mod keeps it.  --rate is the 🛫 the mod
// would pass, in tokens a second.  --home stands for HOME, "${HOME}" by
// default, which is what the fixtures' paths are written under.
// --sticky names the rows, of turn, agent and session, that stay on the
// band once a turn ends, the mod's CONFIG.sticky: the band's done phase
// draws those, and the receipt the rest; 🤖 on the receipt comes from
// --workspace.
//
// The clock is drawn in the document's `clock.tz`, as the edge would set
// it, and the terminal's profile is read from the environment.
import { readFileSync } from "node:fs";
import { settings, stripAnsi } from "../src/formatting.ts";
import { join } from "../src/spans.ts";
import type { Span } from "../src/spans.ts";
import { pyRstrip } from "../src/py.ts";
import type { Dict } from "../src/py.ts";
import { ROW_NAMES, bandLines, bandRows, workspaceOf } from "../src/band.ts";
import type { Phase, RowName } from "../src/band.ts";
import { receiptLines, startLine } from "../src/receipt.ts";

const USAGE = "usage: draw-figures.ts FILE [--cols N] " +
  "[--part {band,receipt,start}] [--phase {running,done}] [--hide PATH] " +
  "[--rate N] [--home DIR] [--workspace STATUS_FILE] " +
  "[--sticky {turn,agent,session},...] [--plain]";

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
  else if (a.startsWith("--")) fail("unrecognized arguments: " + a);
  else file = a;
}
if (!file) fail("the figures document is required");
if (!Number.isInteger(cols) || cols <= 0) fail("--cols takes a width");
if (!["running", "done"].includes(phase)) fail("--phase: invalid choice");
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
const st = settings(process.env);

let lines: Span[][];
if (part === "band") {
  lines = bandLines(st, fig, cols, hide, { home, rate, phase, sticky });
} else if (part === "start") {
  lines = [startLine(fig, hide)];
} else if (part === "receipt") {
  const status = wsFile ? read(wsFile) : null;
  const ws = status ? workspaceOf(status, home) : null;
  const main = status
    ? bandRows(st, status, { home, rate: null, phase: "done" }).main : null;
  lines = receiptLines(st, fig, cols, hide, ws, false, main, sticky);
} else {
  fail("--part: invalid choice: '" + part + "'");
}
const text = lines.map((l) => pyRstrip(join(l))).join("\n");
process.stdout.write((plain ? stripAnsi(text) : text) + "\n");
