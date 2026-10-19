// claude_render.ts against claude_render.py, cell by cell.
//
// The status goldens (claude_render.test.ts) draw under one terminal
// profile and one zone.  tests/fixtures/gen/render.py runs each cell, and
// render_status over hand-made records, under every profile, both mark
// spacings and the subscripts, and writes each call's inputs and result
// under tests/fixtures/render/; this builds the same Settings, runs the
// same call through the TypeScript and compares.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import * as cr from "../src/claude_render.ts";
import * as fm from "../src/formatting.ts";
import type { Env, Settings } from "../src/formatting.ts";
import { enc, revive as reviveSpans } from "./formatting_codec.ts";

const FIXTURES = path.join(import.meta.dirname, "..", "..", "tests",
  "fixtures");

type Case = { [k: string]: any };

function load(dir: string, name: string): Case {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, dir, name + ".json"),
    "utf-8"));
}

/** formatting_codec's revive, and a NamedTuple, {"rec": fields}, as the
 * record of its fields. */
function revive(v: any): any {
  if (Array.isArray(v)) return v.map(revive);
  if (v !== null && typeof v === "object" && Object.keys(v).length === 1 &&
    "rec" in v) {
    return Object.fromEntries(Object.entries(v.rec).map(([k, x]) =>
      [k, revive(x)]));
  }
  if (v !== null && typeof v === "object" && !("span" in v) &&
    !("$float" in v)) {
    return Object.fromEntries(Object.entries(v).map(([k, x]) =>
      [k, revive(x)]));
  }
  return reviveSpans(v);
}

const ENVS: { [name: string]: Env } = load("formatting", "settings").envs;

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

/** Runs `body` with TZ restored after, as the zone cases change it. */
function keepingTz(body: () => void): void {
  const saved = process.env.TZ;
  try {
    body();
  } finally {
    if (saved === undefined) delete process.env.TZ;
    else process.env.TZ = saved;
  }
}

// Each Python function by name, called with the case's arguments as the
// Python was: settings first where the port takes them.
const FNS: { [fn: string]: (st: Settings, a: any[]) => unknown } = {
  render_tokens: (st, a) => cr.renderTokens(st, a[0], a[1], a[2]),
  main_doing: (_st, a) => cr.mainDoing(a[0]),
  render_rate_cache: (st, a) =>
    cr.renderRateCache(st, a[0], a[1], a[2], a[3]),
  render_ctx: (st, a) => cr.renderCtx(st, a[0], a[1], a[2]),
  render_cost: (st, a) => cr.renderCost(st, a[0], a[1]),
  render_model_cost: (st, a) => cr.renderModelCost(st, a[0], a[1], a[2]),
  render_limit: (st, a) => cr.renderLimit(st, a[0], a[1], a[2], a[3],
    a[4], a[5], a[6], a[7], a[8], a[9]),
  render_cache_share: (st, a) => cr.renderCacheShare(st, a[0], a[1], a[2],
    a[3], a[4], a[5]),
  render_diff: (st, a) => cr.renderDiff(st, a[0], a[1]),
  render_pr: (st, a) => cr.renderPr(st, a[0]),
  model_label: (_st, a) => cr.modelLabel(a[0]),
  model_spec: (_st, a) => cr.modelSpec(a[0]),
  render_model: (st, a) => cr.renderModel(st, a[0], a[1]),
  effort_glyph: (_st, a) => cr.effortGlyph(a[0]),
  render_queue: (st, a) => cr.renderQueue(st, a[0], a[1]),
  render_style: (_st, a) => cr.renderStyle(a[0]),
  render_time: (st, a) => cr.renderTime(st, a[0]),
  render_date: (st, a) => cr.renderDate(st, a[0]),
  eta_reading: (_st, a) => cr.etaReading(a[0], a[1], a[2], a[3], a[4]),
  inherit_eta: (_st, a) => cr.inheritEta(a[0], a[1], a[2]),
  eta_fig: (st, a) => cr.etaFig(st, a[0], a[1], a[2], a[3]),
  render_elapsed: (st, a) => cr.renderElapsed(st, a[0], a[1], a[2], a[3],
    a[4], a[5], a[6], a[7]),
  allocate_left: (_st, a) => cr.allocateLeft(a[0], a[1], a[2], a[3]),
  render_thread_background: (st, a) =>
    cr.renderThreadBackground(st, a[0], a[1]),
  render_where_group: (_st, a) =>
    cr.renderWhereGroup(a[0], a[1], a[2], a[3], a[4]),
  project_name: (_st, a) => cr.projectName(a[0], a[1]),
  chat_row: (st, a) => cr.chatRow(st, a[0], a[1], a[2], a[3], a[4], a[5]),
  render_chat_rows: (st, a) => cr.renderChatRows(st, a[0], a[1], a[2], a[3]),
  drawn_line: (_st, a) => cr.drawnLine(a[0], a[1]),
};

/** fn's result as the generator writes it, or the mark of a throw. */
function attempt(fn: () => unknown): unknown {
  try {
    return enc(fn());
  } catch {
    return { raises: true };
  }
}

test("cells: every renderer over its awkward inputs", () => {
  const counts = new Map<string, number>();
  keepingTz(() => {
    for (const c of load("render", "cells").cases) {
      const st = settingsFor(c.cfg);
      if (c.tz) process.env.TZ = c.tz;
      const call = FNS[c.fn];
      assert.ok(call, "no port of " + c.fn);
      const got = attempt(() => call(st, revive(c.args)));
      assert.deepEqual(got, c.out,
        `${c.fn}${JSON.stringify(c.args)} under ${c.cfg} ${c.tz ?? ""}`);
      counts.set(c.fn, (counts.get(c.fn) ?? 0) + 1);
    }
  });
  for (const fn of Object.keys(FNS)) assert.ok(counts.get(fn), fn);
});

test("render_status: hand-made records at each width and profile", () => {
  const doc = load("render", "status");
  const recs = revive(doc.records);
  keepingTz(() => {
    for (const c of doc.cases) {
      process.env.TZ = c.tz;
      const r = recs[c.name];
      const got = attempt(() => cr.renderStatus(settingsFor(c.cfg), r.pay,
        r.tr, r.git, r.lim, c.cols, doc.now, c.rules, r.ctx_window, r.rate,
        r.cache, doc.home));
      assert.equal(got, c.out,
        `${c.name} at ${c.cols} under ${c.cfg} ${c.tz} rules ${c.rules}`);
    }
  });
});
