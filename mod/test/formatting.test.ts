// formatting.ts against formatting.py, case by case.
//
// tests/fixtures/gen/formatting.py runs the Python under each terminal
// environment, mark spacing and subscript setting, and writes each call's
// inputs and result under tests/fixtures/formatting/; this builds the same
// Settings from the same environment and flags, runs the same call through
// the TypeScript and compares.  A call the Python raises on is {"raises":
// true}, and the TypeScript must throw.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import * as fm from "../src/formatting.ts";
import type { Env, Settings } from "../src/formatting.ts";
import * as sp from "../src/spans.ts";
import { TRUE_COLOURS } from "../src/spec.ts";
import { enc, revive } from "./formatting_codec.ts";

const DIR = path.join(import.meta.dirname, "..", "..", "tests", "fixtures",
  "formatting");

type Case = { [k: string]: any };

const RAISES = { raises: true };

function attempt(fn: () => unknown): unknown {
  try {
    return enc(fn());
  } catch {
    return RAISES;
  }
}

function load(name: string): Case {
  return JSON.parse(fs.readFileSync(path.join(DIR, name + ".json"),
    "utf-8"));
}

const SETTINGS = load("settings");
const ENVS: { [name: string]: Env } = SETTINGS.envs;

const built = new Map<string, Settings>();
function settingsFor(cfg: [string, boolean, boolean]): Settings {
  const key = cfg.join("/");
  let st = built.get(key);
  if (!st) {
    st = fm.settings(ENVS[cfg[0]], cfg[1], cfg[2]);
    built.set(key, st);
  }
  return st;
}

test("settings: every environment, spacing and subscript setting", () => {
  for (const c of SETTINGS.configs) {
    const st = fm.settings(ENVS[c.env], c.spacing, c.subscript);
    const { env, spacing, subscript, ...want } = c;
    const got = enc({ ...st, widths: { ...st.widths } });
    assert.deepEqual(got, want, `${env} ${spacing} ${subscript}`);
  }
});

test("settings: the constants and the colour escapes", () => {
  const k = SETTINGS.constants;
  const got: { [name: string]: unknown } = {};
  for (const name of Object.keys(k)) {
    got[name] = enc((fm as any)[name] ?? (sp as any)[name]);
  }
  assert.deepEqual(got, k);
  for (const [name, esc] of Object.entries(SETTINGS.escapes)) {
    assert.equal(sp.escape(name), esc, name);
  }
  for (const [name, esc] of Object.entries(SETTINGS.trueEscapes)) {
    assert.equal(sp.escape(name, true), esc, name);
  }
});

// Each Python function by name, called with the case's arguments as the
// Python was: settings first where the port takes them.
const FNS: { [fn: string]: (st: Settings, a: any[]) => unknown } = {
  reset_dim: (_st, a) => fm.resetDim(a[0]),
  mag_dim: (_st, a) => fm.magDim(a[0], a[1]),
  share_dims: (_st, a) => fm.shareDims(a[0], a[1]),
  cache_dims: (_st, a) => fm.cacheDims(a[0], a[1]),
  cache_color: (_st, a) => fm.cacheColor(a[0]),
  pct2: (_st, a) => fm.pct2(a[0]),
  pct: (_st, a) => fm.pct(a[0]),
  short_model: (_st, a) => fm.shortModel(a[0], a[1]),
  strip_ansi: (_st, a) => fm.stripAnsi(a[0]),
  fit_head: (_st, a) => fm.fitHead(a[0], a[1]),
  fit_path: (_st, a) => fm.fitPath(a[0], a[1]),
  seg_gap: (_st, a) => fm.segGap(a[0]),
  term_profile: (_st, a) => fm.termProfile(a[0]),
  colour_level: (_st, a) => sp.colourLevel(a[0]),
  widths_for: (_st, a) => {
    const w = fm.widthsFor(a[0]);
    return [w.narrow, w.icons, w.clusters, w.wide];
  },
  vis_width: (st, a) => fm.visWidth(a[0], st.widths),
  fit_cols: (st, a) => fm.fitCols(st, a[0], a[1]),
  trunc: (st, a) => fm.trunc(st, a[0], a[1]),
  pad_val: (st, a) => fm.padVal(st, a[0], a[1], a[2]),
  seg: (st, a) => fm.seg(st, a[0], a[1], a[2]),
  pair: (st, a) => fm.pair(st, a[0], a[1], a[2], a[3]),
  rules_on: (st, a) => fm.rulesOn(st, a[0]),
  grid_row: (st, a) => fm.gridRow(st, a[0], a[1], a[2]),
  sub_dec: (st, a) => fm.subDec(st, a[0]),
  dec_align: (st, a) => fm.decAlign(st, a[0], a[1], a[2], a[3]),
  humanize: (st, a) => fm.humanize(st, a[0]),
  rate_fig: (st, a) => fm.rateFig(st, a[0]),
  money_fmt: (st, a) => fm.moneyFmt(st, a[0]),
  money_fig: (st, a) => fm.moneyFig(st, a[0]),
  money_cell: (st, a) => fm.moneyCell(st, a[0]),
  signed: (st, a) => fm.signed(st, a[0]),
  plan_pct: (st, a) => fm.planPct(st, a[0], a[1]),
  limit_pct: (st, a) => fm.limitPct(st, a[0], a[1]),
  dur_fmt: (st, a) => fm.durFmt(st, a[0], a[1]),
  signed_pct: (st, a) => fm.signedPct(st, a[0], a[1]),
  elapsed_short: (st, a) => fm.elapsedShort(st, a[0], a[1]),
  short_dur: (st, a) => fm.shortDur(st, a[0], a[1]),
};

const VALUES = load("values");

test("values: every function over its awkward inputs", () => {
  const counts = new Map<string, number>();
  const savedTz = process.env.TZ;
  try {
    for (const c of VALUES.cases) {
      const st = settingsFor(c.cfg ?? ["unknown", true, false]);
      if (c.tz) process.env.TZ = c.tz;
      const call = FNS[c.fn];
      assert.ok(call, "no port of " + c.fn);
      const got = attempt(() => call(st, revive(c.args)));
      assert.deepEqual(got, c.out,
        `${c.fn}${JSON.stringify(c.args)} under ${c.cfg} ${c.tz ?? ""}`);
      counts.set(c.fn, (counts.get(c.fn) ?? 0) + 1);
    }
  } finally {
    if (savedTz === undefined) delete process.env.TZ;
    else process.env.TZ = savedTz;
  }
  // Every function the generator wrote cases for has some.
  for (const fn of Object.keys(FNS)) assert.ok(counts.get(fn), fn);
});

test("term_cols: the walk over scripted process tables", () => {
  for (const s of VALUES.term_cols) {
    const ps = (pid: number): string | null => {
      const out = s.ps[String(pid)];
      return out === undefined ? null : out;
    };
    const winsize = (p: string): number | null => s.winsize[p] ?? null;
    assert.equal(fm.termCols(s.ppid, ps, winsize), s.out,
      JSON.stringify(s));
  }
});

// Under tmux's limited mode, and wherever the level is in doubt, every
// colour drawn is the 256 set's: an xterm entry that Claude Code's
// rounding to 256 colours gives back as it was (tools/gen-spec.py's
// palette), in the panel's escapes and in the mod's Text colours alike.
const CUBE = [0, 95, 135, 175, 215, 255];
const xterm = (i: number): number[] => i >= 232
  ? [8 + 10 * (i - 232), 8 + 10 * (i - 232), 8 + 10 * (i - 232)]
  : [CUBE[Math.floor((i - 16) / 36)], CUBE[Math.floor((i - 16) / 6) % 6],
    CUBE[(i - 16) % 6]];
const ansi256 = ([r, g, b]: number[]): number => r === g && g === b
  ? (r < 8 ? 16 : r > 248 ? 231 : Math.round((r - 8) / 247 * 24) + 232)
  : 16 + 36 * Math.round(r / 255 * 5) + 6 * Math.round(g / 255 * 5) +
    Math.round(b / 255 * 5);
const ROUND_TRIP = new Set(Array.from({ length: 240 }, (_, k) => k + 16)
  .filter((i) => ansi256(xterm(i)) === i).map((i) => xterm(i).join(",")));
const NAMES = Object.keys(TRUE_COLOURS).sort();
const ALL = NAMES.map((n) => n.startsWith("B_")
  ? sp.span(n, null, false, false, n) : sp.span(n, n));
const LIMITED: Env[] = [
  { TMUX: "/tmp/tmux-501/default,1,0", TERM: "screen-256color" },
  { TMUX: "/tmp/tmux-501/default,1,0", TERM: "tmux-256color",
    COLORTERM: "truecolor" },
  { TMUX: "/tmp/tmux-501/default,1,0", TERM: "xterm-kitty" },
  {}, { TERM: "weird" }, { TERM: "xterm-256color", FORCE_COLOR: "x" },
];

test("tmux's limited mode and any doubt draw the 256 set", () => {
  assert.equal(ROUND_TRIP.size, 80);
  for (const env of LIMITED) {
    const st = fm.settings(env);
    assert.equal(st.truecolor, false, JSON.stringify(env));
    const codes = [...sp.join(ALL, false, false, st.truecolor)
      .matchAll(/\x1b\[(?:[0-9;]*;)?[34]8;2;(\d+);(\d+);(\d+)m/g)];
    assert.equal(codes.length, ALL.length);
    for (const m of codes) {
      assert.ok(ROUND_TRIP.has([m[1], m[2], m[3]].join(",")),
        JSON.stringify(env) + " " + m[0].slice(1));
    }
    for (const n of NAMES) {
      const hex = sp.hexOf(n, st.truecolor);
      const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
      assert.ok(ROUND_TRIP.has(rgb.join(",")), JSON.stringify(env) + n + hex);
    }
  }
  const lifted = fm.settings({ TMUX: "/tmp/t,1,0", COLORTERM: "truecolor",
    CLAUDE_CODE_TMUX_TRUECOLOR: "1" });
  assert.equal(lifted.truecolor, true);
  assert.equal(sp.hexOf("F_RED", true), "#ff5a5a");
});
