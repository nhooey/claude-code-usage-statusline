// The Node edges of claude_sources.ts: the tracker's store, read through
// its plist or `defaults export`, and prepareClaudeReading with Node's
// cache and collectors as its defaults.
//
// claude_sources.ts is pure, so the mod, which runs with no Node, can
// import it; the mod reads the store through `$` in its own handlers.
// Everything claude_sources.ts exports is exported from here too, so a
// Node caller imports one module.
import * as fs from "node:fs";
import { spawn } from "node:child_process";
import {
  configAccountOf, plistLoads, prepareClaudeReading as prepareWith,
  trackerReading,
} from "./claude_sources.ts";
import type { PreparedClaudeReading } from "./claude_sources.ts";
import { expandUser, fetchSource, fileStore } from "./sources_node.ts";
import type { AccountOf, Dict, Env, Fetch, Store } from "./sources.ts";

export * from "./claude_sources.ts";

// Collect once and return the canonical and legacy-safe forms, with the
// cache, the collectors and the environment defaulting to the real ones.
export async function prepareClaudeReading(
    spec: string | null, account: string, period: string, context: unknown,
    now: number, env: Env = process.env, store: Store = fileStore(env),
    fetch: Fetch = fetchSource(env),
    configAccount: AccountOf = () => configAccountId(env)):
    Promise<PreparedClaudeReading> {
  return prepareWith(spec, account, period, context, now, env, store, fetch,
                     configAccount);
}

const configAccounts = new Map<string, [string, string]>();

// claude.config_account_id: Claude Code's signed-in account, hashed, from
// its global config, kept against the file's mtime and size.
export function configAccountId(env: Env): string {
  const dir = env.CLAUDE_CONFIG_DIR;
  const path = dir ? expandUser(dir) + "/.claude.json"
    : expandUser("~/.claude.json");
  let stamp: string;
  try {
    const st = fs.statSync(path, { bigint: true });
    stamp = st.mtimeNs + "/" + st.size;
  } catch {
    return "";
  }
  const hit = configAccounts.get(path);
  if (hit && hit[0] === stamp) return hit[1];
  let text: string;
  try { text = fs.readFileSync(path, "utf8"); } catch { return ""; }
  const answer = configAccountOf(text);
  configAccounts.set(path, [stamp, answer]);
  return answer;
}


// Claude Usage Tracker, the macOS menu-bar app, which polls Anthropic on
// its own schedule and keeps the answer in its UserDefaults.  Read through
// `defaults export` rather than by opening the .plist, because a running
// app's preferences live in cfprefsd and reach the file when cfprefsd
// feels like it.  CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST names an
// exported store to read instead.
export class ClaudeUsageTrackerSource {
  static readonly DOMAIN = "HamedElfayome.Claude-Usage";
  static readonly PLIST =
    "~/Library/Preferences/HamedElfayome.Claude-Usage.plist";
  static readonly ENV = "CODING_AGENT_USAGE_LINE_CLAUDE_TRACKER_PLIST";

  env: Env;

  constructor(env: Env) {
    this.env = env;
  }

  available(): boolean {
    if (this.env[ClaudeUsageTrackerSource.ENV]) return true;
    // The file is the cheap test: `defaults export` on an unknown domain
    // succeeds and prints an empty dict.
    try {
      return process.platform === "darwin" && fs.statSync(
        expandUser(ClaudeUsageTrackerSource.PLIST)).isFile();
    } catch {
      return false;
    }
  }

  async store(): Promise<unknown> {
    const path = this.env[ClaudeUsageTrackerSource.ENV];
    if (path) return plistLoads(fs.readFileSync(expandUser(path)));
    const out = await defaultsExport(ClaudeUsageTrackerSource.DOMAIN, 15);
    return out.length ? plistLoads(out) : {};
  }

  async read(): Promise<Dict> {
    try {
      return trackerReading(await this.store());
    } catch {
      return {};
    }
  }
}

function defaultsExport(domain: string, timeout: number): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const proc = spawn("defaults", ["export", domain, "-"],
                       { stdio: ["ignore", "pipe", "ignore"],
                         timeout: timeout * 1000 });
    const chunks: Buffer[] = [];
    proc.stdout.on("data", (c: Buffer) => chunks.push(c));
    proc.on("error", reject);
    proc.on("close", (_code: number | null, signal: string | null) => {
      if (signal) reject(new Error("defaults export timed out"));
      else resolve(Buffer.concat(chunks));
    });
  });
}

// The figures sources.claude_usage_tracker reads, or null when the app is
// not there.  The override file's errors propagate, to be no reading at
// all; a failed `defaults export` is an empty store, as read() has it.
export async function readTracker(env: Env): Promise<Dict | null> {
  const source = new ClaudeUsageTrackerSource(env);
  if (env[ClaudeUsageTrackerSource.ENV]) {
    return trackerReading(await source.store());
  }
  if (!source.available()) return null;
  return source.read();
}
