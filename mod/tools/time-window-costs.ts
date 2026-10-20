// What the window-cost scan costs here in the Node port, cold and off its
// cache: the TypeScript's side of tools/time-window-costs.py, which has the
// whole story.
//
//   node mod/tools/time-window-costs.ts [--runs N]
//
// Not in CI: it reads ~/.claude/projects, which is private, against a
// scratch state directory, never the real one.
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import * as cc from "../src/claude_calib_node.ts";
import type { CalibEnv } from "../src/claude_calib_node.ts";

const at = process.argv.indexOf("--runs");
const runs = at >= 0 ? Number(process.argv[at + 1]) : 3;
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "window-costs-"));
const projectsDir = process.env.CODING_AGENT_USAGE_LINE_CLAUDE_PROJECTS_DIR ||
  path.join(process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude"),
    "projects");
const now = Date.now() / 1000;
// Naive local datetimes, as the Python's datetime.now() less the windows.
const local = now - new Date().getTimezoneOffset() * 60;
const ss = local - 5 * 3600, ws = local - 7 * 86400;
const env: CalibEnv = { projectsDir, stateDir: scratch, now };
try {
  let t = performance.now();
  const [sess, week] = cc._windowCosts(ss, ws, env);
  const cold = performance.now() - t;
  const hits: number[] = [];
  for (let i = 0; i < runs; i++) {
    t = performance.now();
    cc._windowCosts(ss, ws, env);
    hits.push(performance.now() - t);
  }
  const size = fs.readdirSync(scratch)
    .reduce((n, f) => n + fs.statSync(path.join(scratch, f)).size, 0);
  console.log(`node: cold ${cold.toFixed(0)} ms, cached ${
    hits.map((h) => h.toFixed(0)).join(" ")} ms, cache ${
    (size / 1e6).toFixed(2)} MB, sess $${sess.toFixed(2)}, week $${
    week.toFixed(2)}`);
} finally {
  fs.rmSync(scratch, { recursive: true, force: true });
}
