// The Node edges of sources.ts: the cache files, running a command and
// reading the tracker, over node:fs and node:child_process.
//
// sources.ts is pure, so the mod, which runs with no Node, can import it;
// the mod does the same I/O through `$` in its own handlers.  Everything
// sources.ts exports is exported from here too, so a Node caller imports
// one module.
import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as nodeOs from "node:os";
import * as nodePath from "node:path";
import { readTracker } from "./claude_sources_node.ts";
import { isDict, pyGet, pyTruthy } from "./py.ts";
import {
  cacheName, commandInput, commandOutput, identity, pyFloat, pyJsonDumps,
  pyJsonLoads, pyStr, trackerV1,
} from "./sources.ts";
import type { Dict, Env, Fetch, Reading, Store } from "./sources.ts";

export * from "./sources.ts";
// ════════════════════════════════════════════════════════════════════════════
// The edges: the cache files, the command, the tracker.
// ════════════════════════════════════════════════════════════════════════════

export function expandUser(path: string): string {
  if (path === "~" || path.startsWith("~/")) {
    return nodeOs.homedir() + path.slice(1);
  }
  return path;
}

// state.py's directory.  The same files Python writes, under the same
// names, so the band and the status line share one cache and one cadence:
// the tracker is read once a minute between them, not once each.
export function stateDir(env: Env): string {
  let path = env.CODING_AGENT_USAGE_LINE_STATE_DIR ?? "";
  if (!path) {
    const base = env.XDG_STATE_HOME ||
      nodePath.join(nodeOs.homedir(), ".local", "state");
    path = nodePath.join(base, "coding-agent-usage-line");
  }
  try { fs.mkdirSync(path, { recursive: true, mode: 0o700 }); } catch { /**/ }
  try { fs.chmodSync(path, 0o700); } catch { /**/ }
  return path;
}

function readJson(path: string): Dict {
  try {
    const value = pyJsonLoads(fs.readFileSync(path, "utf8"));
    return isDict(value) ? value : {};
  } catch {
    return {};
  }
}

export function fileStore(env: Env): Store {
  const dir = () => stateDir(env);
  return {
    load(agent, source, account, periodStart) {
      const value = readJson(nodePath.join(dir(),
        cacheName(agent, source, account, periodStart)));
      const expected = identity([agent, source, account, periodStart]);
      const actual = identity([value.agent, value.source, value.account_name,
                               value.period_start]);
      return expected.join("\0") === actual.join("\0") ? value : {};
    },
    save(agent, source, account, periodStart, value) {
      const stored: Dict = { ...value, agent: String(agent),
                             source: String(source),
                             account_name: String(account),
                             period_start: String(periodStart) };
      const target = nodePath.join(dir(),
        cacheName(agent, source, account, periodStart));
      const tmp = nodePath.join(nodePath.dirname(target),
        ".tmp-" + process.pid + "-" + Math.random().toString(36).slice(2));
      try {
        fs.writeFileSync(tmp, pyJsonDumps(stored, true), { mode: 0o600 });
        fs.renameSync(tmp, target);
        fs.chmodSync(target, 0o600);
      } catch { /* an unwritable cache is a cache miss next time */ }
      try { fs.unlinkSync(tmp); } catch { /**/ }
    },
    findCompatible(agent, account, periodStart) {
      let newest: Dict = {};
      let names: string[];
      try { names = fs.readdirSync(dir()); } catch { return newest; }
      for (const name of names) {
        if (!name.endsWith(".json") || name.startsWith("reported-")) continue;
        const value = readJson(nodePath.join(dir(), name));
        if (value.agent !== agent || value.account_name !== account ||
            pyStr(pyGet(value, "period_start")) !== pyStr(periodStart)) {
          continue;
        }
        const mine = pyFloat(pyGet(value, "as_of"));
        const theirs = pyFloat(pyGet(newest, "as_of", -1));
        const newer = mine === null || theirs === null
          ? !pyTruthy(newest) : mine > theirs;
        if (newer) newest = value;
      }
      return newest;
    },
  };
}

// Run exactly one path (or bash fallback), passing no secrets or text.
export async function commandReading(path: string, context: unknown,
                                     timeout = 5): Promise<Reading> {
  path = nodePath.resolve(path);
  try {
    if (!fs.statSync(path).isFile()) return {};
  } catch {
    return {};
  }
  let executable = true;
  try { fs.accessSync(path, fs.constants.X_OK); } catch { executable = false; }
  const [cmd, args] = executable ? [path, []] : ["bash", [path]];
  return new Promise((resolve) => {
    // Its own process group, so a timeout takes its children with it.
    const proc = spawn(cmd, args, { stdio: ["pipe", "pipe", "ignore"],
                                    detached: true });
    const chunks: Buffer[] = [];
    let size = 0, settled = false;
    const kill = () => {
      try { process.kill(-proc.pid!, "SIGKILL"); } catch { /**/ }
    };
    const finish = (value: Reading) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    const timer = setTimeout(() => { kill(); finish({}); },
                             Math.max(10, timeout * 1000));
    proc.on("error", () => finish({}));
    proc.stdin.on("error", () => { /* a command need not read its input */ });
    proc.stdout.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > 1024 * 1024) { kill(); finish({}); return; }
      chunks.push(chunk);
    });
    proc.on("close", (code: number | null) => {
      finish(code === 0 ? commandOutput(Buffer.concat(chunks)) : {});
    });
    proc.stdin.end(commandInput(context));
  });
}

// The tracker's store, through the override file or `defaults export`.
// Malformed or missing, it is no reading.
export async function claudeUsageTracker(env: Env): Promise<Reading> {
  try {
    const raw = await readTracker(env);
    return raw === null ? {} : trackerV1(raw);
  } catch {
    return {};
  }
}

// The collectors this port has.  The others are no reading.
export function fetchSource(env: Env): Fetch {
  return async (selected, context) => {
    if (selected.startsWith("cmd:")) {
      return commandReading(selected.slice(4), context);
    }
    if (selected === "claude-usage-tracker") return claudeUsageTracker(env);
    return {};
  };
}
