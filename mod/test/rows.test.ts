// The row builders against their shared cases, tests/fixtures/rows/, which
// tools/gen-row-cases.ts writes from them.  As with the grid's cases, each
// is replayed from its document and options, and the generator's output
// must be what is committed, so a change to a builder shows up as a change
// to the cases, made by regenerating them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join as pathJoin } from "node:path";
import { settings, stripAnsi, visWidth } from "../src/formatting.ts";
import type { Env } from "../src/formatting.ts";
import { join, width } from "../src/spans.ts";
import { RIGHT_EDGE } from "../src/spec.ts";
import type { Span } from "../src/spans.ts";
import type { Dict } from "../src/py.ts";
import { draw } from "../src/grid.ts";
import { panelLayout } from "../src/claude_subagent_render.ts";
import {
  FOOTER_GAP, FOOTER_JOIN, MODE_PILLS, TAIL_CUT, accountLine, accountText, footerParts, modeOfHint, bandLines, bandRows, fixedKeys, footerTail,
  phaseRows,
  workspaceOf,
} from "../src/band.ts";
import { receiptLines, receiptTurn, startLine } from "../src/receipt.ts";
import { decodeTurn } from "../src/claude_cost.ts";
import { spanFrom, spanJson } from "../tools/gen-grid-cases.ts";
import {
  FIGURES, HOME, OUT, document, drawBand, drawReceipt, drawStart, generate,
  inZone,
} from "../tools/gen-row-cases.ts";
import type { BandCase, ReceiptCase } from "../tools/gen-row-cases.ts";

type Same = { same: string[] };
type File = { settings: { profiles: { [name: string]: Env } };
  band: (BandCase & Same & { rows: unknown[][][]; lines: string[] })[];
  receipt: (ReceiptCase & Same & { rows: unknown[][][]; lines: string[] })[];
  start: { doc: string; same: string[]; spans: unknown[][];
    line: string }[] };

const files = readdirSync(OUT).filter((f) => f.endsWith(".json")).sort();

test("the committed cases are the generator's", () => {
  const want = generate();
  assert.deepEqual(files, [...want.keys()].sort());
  for (const f of files) {
    assert.ok(readFileSync(pathJoin(OUT, f), "utf8") === want.get(f),
      f + " differs: run node mod/tools/gen-row-cases.ts and read the diff");
  }
});

/** The text of a committed document. */
const text = (id: string): string =>
  readFileSync(pathJoin(FIGURES, id + ".json"), "utf8");

/** Spans as the cases write them, and their joined line. */
function same(got: readonly Span[], want: readonly unknown[][],
  line: string, where: string): void {
  assert.deepEqual(got.map(spanJson), want, where);
  assert.equal(join(got), line, where);
  assert.equal(join(want.map(spanFrom)), line, where);
}

for (const f of files) {
  const data = JSON.parse(readFileSync(pathJoin(OUT, f), "utf8")) as File;
  for (const [profile, env] of Object.entries(data.settings.profiles)) {
    const st = settings(env);
    test(`${f} under ${profile}: band`, () => {
      for (const c of data.band) {
        const where = JSON.stringify([c.doc, c.cols, c.hide, c.phase]);
        const rows = drawBand(st, document(c.doc), c);
        assert.equal(rows.length, c.rows.length, where);
        rows.forEach((r, i) => same(r, c.rows[i], c.lines[i], where));
      }
    });
    test(`${f} under ${profile}: receipt`, () => {
      for (const c of data.receipt) {
        const where = JSON.stringify([c.doc, c.cols, c.hide, c.workspace]);
        const got = drawReceipt(st, document(c.doc), c);
        assert.equal(got.length, c.rows.length, where);
        got.forEach((r, i) => same(r, c.rows[i], c.lines[i], where));
      }
    });
    test(`${f} under ${profile}: start`, () => {
      for (const c of data.start) {
        same(drawStart(document(c.doc)), c.spans, c.line, c.doc);
      }
    });
  }
}

test("a case's `same` documents are its document, byte for byte", () => {
  const data = JSON.parse(readFileSync(pathJoin(OUT, files[0]), "utf8")) as
    File;
  for (const c of [...data.start, ...data.receipt]) {
    for (const id of c.same) assert.equal(text(id), text(c.doc), id);
  }
});

test("the band's columns do not move with the phase or the figures", () => {
  const st = settings({});
  const keys = fixedKeys(st, 155, []);
  for (const id of ["status/01-baseline@196", "status/03-no-transcript@196",
    "status/18-agents@196"]) {
    const fig = document(id);
    for (const phase of ["running", "done"] as const) {
      const rows = inZone(fig, () => phaseRows(bandRows(st, fig,
        { home: HOME, rate: null, phase }), phase));
      for (const r of rows) {
        // Every row is drawn on the same keys to the same right edge, so
        // each column starts where the others' do.
        const drawn = draw(st, r, keys, 155, []);
        assert.equal(width(drawn, st.widths), 155 - RIGHT_EDGE, id);
      }
    }
  }
});

test("each row's live and transcript pick the band's rows and the receipt's",
  () => {
    const st = settings({});
    const status = document("status/01-baseline@196");
    const cost = document("cost/09-agents@196");
    const opts = { home: HOME, rate: null, phase: "done" as const };
    const main = inZone(status, () => bandRows(st, status, opts).main);
    const marks = (lines: Span[][]) => lines.map((l) =>
      Array.from(stripAnsi(join(l)))[0]);
    // live by row, the rows stamped, then what the receipt, the band
    // while a turn runs and the band once it ends draw.
    for (const [live, stamped, stamp, running, done] of [
      [{}, ["turn", "agent", "session"], ["🎤", "🤖", "🎮"],
        ["🎤", "🤖", "🎮"], []],
      // The options' defaults.
      [{ agent: "always", session: "always" }, ["turn"], ["🎤"],
        ["🎤", "🤖", "🎮"], ["🤖", "🎮"]],
      // Kept live and stamped too.
      [{ turn: "always", agent: "always", session: "always" },
        ["turn", "agent", "session"], ["🎤", "🤖", "🎮"],
        ["🎤", "🤖", "🎮"], ["🎤", "🤖", "🎮"]],
      // Live while running only, and stamped nowhere.
      [{ session: "running" }, ["turn"], ["🎤"], ["🎤", "🤖", "🎮"], []],
      // In the transcript only.
      [{ turn: "never", agent: "never" }, ["turn", "agent"], ["🎤", "🤖"],
        ["🎮"], []],
      [{ turn: "always", session: "always" }, ["agent"], ["🤖"],
        ["🎤", "🤖", "🎮"], ["🎤", "🎮"]],
    ] as const) {
      const name = JSON.stringify([live, stamped]);
      const receipt = inZone(cost, () => receiptLines(st, cost, 196, [],
        null, false, main, stamped));
      // The rows, then a blank row and the 🔺🔖 tag line.
      assert.deepEqual(marks(receipt).slice(0, -2), stamp, name);
      assert.equal(marks(receipt).at(-2), " ", name);
      for (const [phase, want] of [["running", running], ["done", done]] as
        const) {
        const band = inZone(status, () => bandLines(st, status, 196, [],
          { ...opts, phase, live }));
        assert.deepEqual(marks(band), want, name + " " + phase);
      }
    }
    // The tag line, its blank row with it, left out without `tags`.
    const untagged = inZone(cost, () => receiptLines(st, cost, 196, [],
      null, false, main, ["turn"], 0, false));
    assert.deepEqual(marks(untagged), ["🎤"]);
  });

test("name.tag hides both tag lines and the receipt's blank row", () => {
  const st = settings({});
  const status = document("status/01-baseline@196");
  const cost = document("cost/09-agents@196");
  assert.ok(startLine(status).length > 0);
  assert.deepEqual(startLine(status, ["name.tag"]), []);
  const all = inZone(cost, () => receiptLines(st, cost, 196, [], null));
  const less = inZone(cost, () => receiptLines(st, cost, 196, ["name.tag"],
    null));
  // The blank row and the 🔺🔖 line go; the rows stay.
  assert.deepEqual(less, all.slice(0, -2));
});

test("the receipt bills the cost line's turn", () => {
  const fig = document("cost/09-agents@196");
  const turns = (fig.turns as { [k: string]: unknown }[]).map(decodeTurn);
  const i = receiptTurn(turns);
  assert.ok(turns[i].calls && !turns[i].agent && !turns[i].compact);
  assert.equal(i, turns.length - 1);
  assert.equal(receiptTurn([]), -1);
});

test("the 💳 account's own row ends where the band's rows end, in colour", () => {
  const st = settings({});
  const fig = document("status/01-baseline@196");
  const row = inZone(fig, () => accountLine(st, fig, [], 196));
  const text = join(row.map((s) => ({ ...s, colour: null, dim: false,
    bold: false, bg: null })));
  assert.equal(width(row, st.widths), 196 - RIGHT_EDGE);
  // The same text as the footer's tail, its parts FOOTER_GAP apart.
  const plain = inZone(fig, () => accountText(st, fig, []));
  assert.equal(text.trim(), footerParts(plain).join(" ".repeat(FOOTER_GAP)));
  assert.ok(row.some((s) => s.colour), "no colour kept");
  assert.deepEqual(inZone(fig, () => accountLine(st, fig, ["account"], 196)),
    []);
});

test("rows inset under the footer line stack on the agent panel's columns", () => {
  // Claude Code draws the footer line's container hint-inset columns
  // in; drawn at the full width there, every cell of the band stood that
  // many columns right of the panel's (seen live 2026-10-20).  At the
  // default edge, and at 0, where the band under the footer line and the
  // panel under --right-edge 0 take the [-]'s columns back (asked
  // 2026-10-20).
  for (const edge of [RIGHT_EDGE, 0]) {
    const st = settings({}, true, false, edge);
    const fig = document("status/18-agents@196");
    const hide = ["*.plan.five_hour", "*.context.share", "*.tokens.cache"];
    const plain = (r: readonly Span[]): string => stripAnsi(join(r));
    /** The terminal column each of `marks` starts at in `line`. */
    const at = (line: string): number[] =>
      ["💰", "🧩", "⌛", "🚦", "🪫"].map((m) => {
        const i = line.lastIndexOf(m);
        assert.ok(i >= 0, m + " missing from " + line);
        return visWidth(line.slice(0, i), st.widths);
      });
    for (const cols of [120, 160, 196]) {
      const opts = { home: HOME, rate: null, phase: "running" as const };
      const [pcols, keys] = panelLayout(st, cols, hide);
      assert.deepEqual(keys, fixedKeys(st, cols, hide), String(cols));
      // The agent panel's row, `  ◯ ` chrome and all, at no indent.
      const main = inZone(fig, () => bandRows(st, fig, opts)).main;
      const panel = plain(draw(st, { ...main, scope: "agent", depth: 1 },
        keys, pcols, hide));
      for (const inset of [0, 2]) {
        const band = inZone(fig, () => bandLines(st, fig, cols, hide,
          { ...opts, inset }));
        for (const row of band) {
          const line = " ".repeat(inset) + plain(row);
          assert.equal(visWidth(line, st.widths), cols - edge,
            [edge, cols, inset, line].join(" "));
        }
        const line = " ".repeat(inset) + plain(band[1]);
        assert.deepEqual(at(line), at(panel),
          [edge, cols, inset, line].join(" "));
        // The 💳 row ends where they do, on a terminal wide enough for it.
        if (cols < 160) continue;
        const acct = " ".repeat(inset) + plain(inZone(fig, () =>
          accountLine(st, fig, hide, cols - inset)));
        assert.equal(visWidth(acct, st.widths), cols - edge,
          [edge, cols, inset, acct].join(" "));
      }
    }
  }
});

test("the footer's tail ends on the 💳 account details where the band's rows end", () => {
  const st = settings({});
  const fig = document("status/01-baseline@196");
  const hint = "-- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle)";
  const text = inZone(fig, () => accountText(st, fig, []));
  assert.ok(text.includes("💳"), text);
  // The workspace first, 📦 🌿 📁, as 🎮's label draws it.
  assert.ok(text.startsWith("📦") && text.indexOf("📁") < text.indexOf("💳"),
    text);
  assert.ok(!inZone(fig, () => accountText(st, fig, ["account.workspace"]))
    .includes("📦"));
  const tail = inZone(fig, () => footerTail(st, fig, [], hint, 240));
  // The workspace, 💳 and 📅 🕐, FOOTER_GAP apart where the row has room,
  // each run of spaces one space and blanks, since Claude Code draws a run
  // of them as one.
  const blanked = (t: string) =>
    t.replace(/ {2,}/g, (r) => " " + "\u2800".repeat(r.length - 1));
  const parts = footerParts(text);
  assert.equal(parts.length, 3, text);
  const kept = blanked(parts.join(" ".repeat(FOOTER_GAP)));
  assert.ok(tail.endsWith(kept) && !/  /.test(tail), tail);
  // Two blanks in, the hint, Claude Code's " · ", then the tail: to the
  // band's right edge, padded with blanks no trim takes.
  assert.equal(2 + visWidth(hint, st.widths) +
    visWidth(FOOTER_JOIN, st.widths) + visWidth(tail, st.widths),
  240 - RIGHT_EDGE - TAIL_CUT);
  // The mode's pill, left out of the hint, is drawn before it all the same.
  const bare = "-- INSERT -- 2 shells";
  const auto = inZone(fig, () => footerTail(st, fig, [], bare, 240, "auto"));
  assert.equal(2 + visWidth(MODE_PILLS.auto + FOOTER_JOIN + bare, st.widths) +
    visWidth(FOOTER_JOIN, st.widths) + visWidth(auto, st.widths),
  240 - RIGHT_EDGE - TAIL_CUT);
  // Before "(shift+tab to cycle)" the pill is drawn with one space.
  const cyc = "-- INSERT -- (shift+tab to cycle)";
  const cycTail = inZone(fig, () => footerTail(st, fig, [], cyc, 240, "auto"));
  assert.equal(2 + visWidth("-- INSERT -- " + MODE_PILLS.auto +
    " (shift+tab to cycle)", st.widths) + visWidth(FOOTER_JOIN, st.widths) +
    visWidth(cycTail, st.widths), 240 - RIGHT_EDGE - TAIL_CUT);
  // Each shape the hint was seen in, by what the footer drew for it.
  const drawn: [string, string, string][] = [
    ["-- INSERT -- (shift+tab to cycle)", "plan",
      "-- INSERT -- ⏸ plan mode on (shift+tab to cycle)"],
    ["-- INSERT -- plan mode on (shift+tab to cycle)", "plan",
      "-- INSERT -- ⏸ plan mode on (shift+tab to cycle)"],
    ["-- INSERT --", "default", "-- INSERT -- ⏸ manual mode on"],
    ["-- INSERT -- manual mode on", "default", "-- INSERT -- ⏸ manual mode on"],
    ["-- INSERT -- 2 shells", "acceptEdits",
      "-- INSERT -- ⏵⏵ accept edits on · 2 shells"],
  ];
  for (const [h, mode, line] of drawn) {
    const t = inZone(fig, () => footerTail(st, fig, [], h, 240, mode));
    assert.equal(2 + visWidth(line + FOOTER_JOIN, st.widths) +
      visWidth(t, st.widths), 240 - RIGHT_EDGE - TAIL_CUT, h);
  }
  // The words are the mode turned off; the one turned on is the next.
  assert.equal(modeOfHint("-- INSERT -- accept edits on (shift+tab to cycle)"),
    "plan");
  assert.equal(modeOfHint("-- INSERT -- auto mode on (shift+tab to cycle)"),
    "default");
  assert.equal(modeOfHint("-- INSERT -- (shift+tab to cycle)"), undefined);
  assert.equal(tail.trimStart(), tail);
  // Too narrow a row: the gaps down to one, and the " · " alone parts the
  // two.
  assert.equal(inZone(fig, () => footerTail(st, fig, [], hint, 40)),
    blanked(parts.join(" ")));
  assert.equal(inZone(fig, () => footerTail(st, fig, ["account"], hint, 240)),
    "");
  // 🔋 hidden in every row takes its 🔜 with it, and leaves 🪫's.
  const no5h = inZone(fig, () => accountText(st, fig, ["*.plan.five_hour"]));
  assert.ok(!no5h.includes("🔋") && no5h.includes("🪫"), no5h);
  assert.equal(no5h.split("🔜").length, text.split("🔜").length - 1, no5h);
});

test("a hidden context.share leaves 🧠's size and drops its ٪", () => {
  const st = settings({});
  const fig = document("status/01-baseline@196");
  const opts = { home: HOME, rate: null, phase: "running" as const };
  const ctx = (hide: string[]) => inZone(fig, () =>
    bandLines(st, fig, 196, hide, opts)).map((l) => join(l));
  const all = ctx([]);
  const less = ctx(["*.context.share"]);
  // 🎤's growth and 🤖's size both lose their ٪; the columns stay put.
  for (const i of [0, 1]) {
    assert.match(all[i], /🧠[^🧩]*٪/);
    assert.doesNotMatch(less[i], /🧠[^🧩]*٪/);
    const col = (s: string) =>
      visWidth(stripAnsi(s.slice(0, s.indexOf("🧩"))), st.widths);
    assert.equal(col(less[i]), col(all[i]));
  }
});

test("📁 draws the project's root as 📦", () => {
  const fig = document("status/01-baseline@196");
  const at = (dir: string, git: Dict) => workspaceOf({ ...fig,
    git: { ...(fig.git as Dict), in_git: true, ...git },
    payload: { ...(fig.payload as Dict), current_dir: dir } }, "/home/u").dir;
  const repo = { toplevel: "/home/u/repo", main_root: "/home/u/repo" };
  assert.equal(at("/home/u/repo", repo), "~/📦");
  assert.equal(at("/home/u/repo/mod", repo), "~/📦/mod");
  assert.equal(at("/home/u/repository", repo), "~/repository");
  assert.equal(at("/srv/repo/mod", { toplevel: "/srv/repo",
    main_root: "/srv/repo" }), "/srv/📦/mod");
  // A worktree's paths are the main checkout's project, under its root.
  assert.equal(at("/home/u/repo/.claude/worktrees/w/mod",
    { toplevel: "/home/u/repo/.claude/worktrees/w", main_root: "/home/u/repo" }),
  "~/📦/.claude/worktrees/w/mod");
});

test("🎤's ⛳ is the turn's own report alone; 🤖's takes a live agent's", () => {
  const st = settings({});
  const fig = document("status/01-baseline@196");
  const opts = { home: HOME, rate: null, phase: "running" as const };
  const now = ((fig.clock as Dict).now as number);
  const text = (spans: readonly Span[] | undefined) =>
    (spans ?? []).map((s) => s.text).join("");
  const at = (eta: number[]) => {
    const f = { ...fig, transcript: { ...(fig.transcript as Dict), eta,
      agent_etas: [[now + 600, now]] } };
    return inZone(f, () => bandRows(st, f, opts));
  };
  const none = at([]);
  assert.equal(text(none.turn.cells.eta), "");
  assert.match(text(none.main.cells.eta), /^⛳ +10m$/);
  const own = at([now - 60, 180]);
  assert.match(text(own.turn.cells.eta), /^⛳ +2m$/);
  assert.match(text(own.main.cells.eta), /^⛳ +10m$/);
});

test("⛳ stops at the turn's end, and a sign-off at zero is not drawn idle",
  () => {
    const st = settings({});
    const fig = document("status/01-baseline@196");
    const opts = { home: HOME, rate: null, phase: "done" as const };
    const now = ((fig.clock as Dict).now as number);
    const text = (spans: readonly Span[] | undefined) =>
      (spans ?? []).map((s) => s.text).join("");
    const at = (eta: number[], idle_at: number) => {
      const f = { ...fig, transcript: { ...(fig.transcript as Dict), eta,
        agent_etas: [], idle_at } };
      return inZone(f, () => bandRows(st, f, opts));
    };
    // Estimated 2m at now-10m, idle since now-5m: 3m over, not 8m.
    const over = at([now - 600, 120], now - 300);
    assert.match(text(over.turn.cells.eta), /^⛳ +\+3m$/);
    assert.match(text(over.main.cells.eta), /^⛳ +\+3m$/);
    const signed = at([now - 600, 0], now - 590);
    assert.equal(text(signed.turn.cells.eta), "");
    assert.equal(text(signed.main.cells.eta), "");
    // Still answering, a sign-off's overrun counts on.
    const busy = at([now - 600, 0], 0);
    assert.match(text(busy.turn.cells.eta), /^⛳ +\+10m$/);
  });

test("🎤 carries the model and 🛫, and a running tool's time in 🛫's column", () => {
  const st = settings({});
  const fig = document("status/01-baseline@196");
  const opts = { home: HOME, rate: 1500, phase: "running" as const };
  const text = (spans: readonly Span[] | undefined) =>
    (spans ?? []).map((s) => s.text).join("");
  const rows = inZone(fig, () => bandRows(st, fig, opts));
  assert.ok(text(rows.turn.cells.model).length > 0);
  // Three columns of figure, its decimal among them, then the unit.
  assert.match(text(rows.turn.cells.rate), /^🛫 [ \d.]{3}[kM ]$/);
  // 🤖 has blank model and 🛫 columns, so its reply ends at the model's,
  // and while it answers, 🤖 and how long in 🛫's.
  assert.equal(text(rows.main.cells.model), "");
  assert.match(text(rows.main.cells.rate), /^(🤖 +\S+)?$/);
  assert.ok(!rows.main.label.some((p) => p.path === "chat.doing"));
  // A tool running for 90 seconds: 🔧 and its time where the rate was, and
  // not on 🤖's label.
  const now = ((fig.clock as Dict).now as number);
  const tooled = { ...fig, transcript: { ...(fig.transcript as Dict),
    tool_at: now - 90 } };
  const t = inZone(tooled, () => bandRows(st, tooled, opts));
  assert.match(text(t.turn.cells.rate), /^🔧 +1\.5m$/);
  assert.ok(!t.main.label.some((p) => p.path === "chat.doing"));
});
