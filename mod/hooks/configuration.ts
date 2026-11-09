// The configuration files: found, read and merged over the defaults the way
// the Python merges them, looked at again on the tick, and a fault in one
// noticed once in the transcript.
import type { EngineInterface } from 'claude-code'

import { utf8 } from '../src/py.ts'
import {
  DEFAULTS_REL, DefaultsError, FILE_LAYERS, MOD_LAYER, abspath,
  find as findConfig, load as loadConfig, merge as mergeConfig, optionsOf,
  readDefaults,
} from '../src/config.ts'
import type {
  ConfigEnv, ConfigFs, Defaults, Found, Layer, Merged, Rows,
} from '../src/config.ts'
import { OPTIONS } from '../src/options_spec.ts'
import type { Options } from '../src/options_spec.ts'
import { LOG_NAME } from '../src/modlog.ts'
import { SETTINGS } from './config.ts'
import { log } from './log.ts'
import { found, fromBase64, readBytesVia } from './engine.ts'

type $ = EngineInterface

/** `$.fs` as src/config.ts's walk reaches it: a stat or a read that fails
 * is null, and a file is read as bytes and decoded strictly with its
 * byte-order mark kept, as the Python's open(…, encoding="utf-8") reads
 * it, so a file the panel finds unreadable or not JSON the band does too. */
function configFs($: $): ConfigFs {
  return {
    stat: async (path) => {
      try {
        const s = await $.fs.stat(path)
        return { kind: s.kind, size: s.size, mtimeMs: s.mtimeMs }
      } catch {
        return null
      }
    },
    read: async (path) => {
      try {
        const { base64 } = await readBytesVia($, path)
        return utf8(fromBase64(base64), true, true)
      } catch {
        return null
      }
    },
    realPath: async (path) =>
      (await $.fs.stat(path, { resolve: true }).catch(() => undefined))
        ?.realPath ?? null,
  }
}

/** The configuration files of the session's project and the user, read,
 * checked and merged over the defaults (config-merge.md, "Reading them in
 * the mod").  The walk starts at the session's root, and a usage source a
 * file names is checked as Claude's panel checks it. */
export async function configVia($: $): Promise<Found> {
  const [start, env] = await configWhere($)
  return loadConfig(start, env, configFs($), await defaultsVia($), 'claude')
}

/** The defaults file in the mod's folder, where the plugin carries it. */
function defaultsPath($: $): string {
  return $.plugin.root + '/' + DEFAULTS_REL
}

// The defaults file as this load of the mod first read it whole, and its
// modification time then; null until it reads whole.
let loadedDefaults: { defaults: Defaults; mtimeMs: number | null } | null =
  null
// The modification time last logged as differing from loadedDefaults'.
let defaultsMovedAt: number | null = null

/** The defaults file, strictly read: a DefaultsError while it is wrong.
 * Read once per load of the mod: the code and the defaults it was written
 * for come from one checkout, so a change on disk, a merge that reshapes
 * the file among them, waits for the next `/reload-plugins`, and is
 * logged once per modification time.  Until it first reads whole, it is
 * read again each time, so a file fixed applies without a reload. */
export async function defaultsVia($: $): Promise<Defaults> {
  const fs = configFs($)
  const path = defaultsPath($)
  const mtimeMs = (await fs.stat(path))?.mtimeMs ?? null
  if (loadedDefaults === null) {
    loadedDefaults = { defaults: await readDefaults(path, fs), mtimeMs }
  } else if (mtimeMs !== loadedDefaults.mtimeMs &&
             mtimeMs !== defaultsMovedAt) {
    defaultsMovedAt = mtimeMs
    await log($, 'config: the defaults file changed on disk; the mod ' +
      'keeps the one it loaded until /reload-plugins: ' + path)
  }
  return loadedDefaults.defaults
}

/** Where the walk starts, the session's root, and the variables it
 * reads. */
async function configWhere($: $): Promise<[string, ConfigEnv]> {
  const env: ConfigEnv = {
    HOME: await $.env.get('HOME'),
    XDG_CONFIG_HOME: await $.env.get('XDG_CONFIG_HOME'),
    CODING_AGENT_USAGE_LINE_CONFIG_DIR:
      await $.env.get('CODING_AGENT_USAGE_LINE_CONFIG_DIR'),
  }
  return [await $.session.root().catch(() => $.session.cwd()), env]
}

/** The mod's own settings as a layer under the files (MOD_LAYER). */
const MOD_SETTINGS: Layer = { name: MOD_LAYER, path: 'mod/hooks/config.ts',
  mtimeMs: 0, values: SETTINGS }

/** The files `found` gave over the mod's settings and `defaults`; with no
 * files, the mod's settings over the defaults. */
export function mergedOf(found: Found | null, defaults: Defaults): Merged {
  return mergeConfig([...found?.layers ?? [], MOD_SETTINGS],
    found?.options.warnings ?? [], defaults)
}

/** The options with no configuration file: the mod's settings over
 * `defaults`. */
export const unconfigured = (defaults: Defaults): Options =>
  optionsOf(mergedOf(null, defaults))

// What the last read of the configuration files found; null before one.
let configFound: Found | null = null
// The options merged from it, and what the files were when it was read;
// null before the first read, and while the defaults file is wrong.
let merged: Merged | null = null
let current: Options | null = null
// Why the defaults file cannot be used, as the last read found; null when
// it read whole.
export let defaultsFault: string | null = null
let configStamp = ''
// The read under way, which a second caller waits on rather than reading
// again beside it.
let configReading: Promise<boolean> | null = null
// The files a notice has been shown for, each at a modification time.
const noticed = new Set<string>()

/** The last read of the configuration files, or null before one. */
export const configNow = (): Found | null => configFound

/** The options the mod draws with, as the last read merged them: the
 * files, then the mod's settings (hooks/config.ts, SETTINGS), then the
 * defaults file, with right-edge derived from rows.*.place where none set
 * it.  Null before the first read, and while the defaults file is wrong:
 * there is nothing to draw with then, and each drawing leaves Claude
 * Code's own (config-merge.md, Decided 18). */
export const options = (): Options | null => current

/** The options, read first where no read has been made yet: a drawing can
 * come before any event that reads them.  Null while the defaults file is
 * wrong. */
export async function optionsFor($: $): Promise<Options | null> {
  if (current === null && defaultsFault === null) {
    await readConfig($).catch((err) => log($, 'config', err))
  }
  return current
}

/** Why the defaults file cannot be used, which the footer draws in place
 * of the rows; null while it reads whole. */
export const defaultsError = (): string | null => defaultsFault

/** What the files are, as one string: the defaults file's modification
 * time, where the walk starts, then each layer's path and its
 * modification time, "-" for none.  The walk's stats alone, no read: a
 * new root, a file come, gone or written each change it. */
async function stampOf($: $, start: string, env: ConfigEnv):
  Promise<string> {
  const fs = configFs($)
  const { paths } = await findConfig(start, env, fs)
  const parts = [`${(await fs.stat(defaultsPath($)))?.mtimeMs ?? '-'}`,
    abspath(start)]
  for (const name of FILE_LAYERS) {
    const path = paths[name]
    const st = path === null ? null : await fs.stat(path)
    parts.push(`${path ?? '-'}@${st?.mtimeMs ?? '-'}`)
  }
  return JSON.stringify(parts)
}

/** Reads the configuration files again where they have changed since the
 * last read, or the session's root has moved, and on the first call:
 * true when the options it merged differ from the last.  Each read logs
 * the files and what each gave, and every warning; a read that changes
 * the options logs them, each that a layer above the defaults gave, with
 * its layer; a file with warnings shows one notice in the transcript per
 * modification time.  One read at a time. */
export async function readConfig($: $): Promise<boolean> {
  configReading ??= reread($).finally(() => {
    configReading = null
  })
  return configReading
}

async function reread($: $): Promise<boolean> {
  const [start, env] = await configWhere($)
  // Taken before the read: a file written between the two is read again
  // next time, rather than missed.
  const stamp = await stampOf($, start, env)
  const first = configStamp === ''
  if (!first && stamp === configStamp) return false
  let defaults: Defaults
  try {
    defaults = await defaultsVia($)
  } catch (err) {
    if (!(err instanceof DefaultsError)) throw err
    configStamp = stamp
    // Nothing is drawn from a wrong defaults file: the footer draws the
    // error, and the log and the transcript say it once.
    const changed = defaultsFault !== err.message || current !== null
    if (defaultsFault !== err.message) {
      await log($, 'config: the defaults file is wrong: ' + err.message)
      try {
        // Claude Code puts the plugin's name, "usage-band: ", in front.
        $.ui.log(`the defaults file is wrong: ${err.message}`)
      } catch (e) {
        await log($, 'config: no notice', e)
      }
    }
    defaultsFault = err.message
    configFound = null
    merged = null
    current = null
    return changed
  }
  const found = await loadConfig(start, env, configFs($), defaults, 'claude')
  const was = defaultsFault
  defaultsFault = null
  configStamp = stamp
  configFound = found
  const files = found.layers.map((l) =>
    `${l.name} ${l.path} (${Object.keys(l.values).join(', ')})`)
  await log($, `config from ${found.start}: ` +
    (files.length ? files.join('; ') : 'no files'))
  for (const w of found.options.warnings) await log($, 'config: ' + w)
  await notice($, found)
  const next = mergedOf(found, defaults)
  const changed = was !== null || merged === null ||
    JSON.stringify([next.values, next.layers, next.fields]) !==
    JSON.stringify([merged.values, merged.layers, merged.fields])
  merged = next
  current = optionsOf(next)
  if (changed) await log($, 'config options: ' + optionsTable(next))
  return changed
}

/** Each option the mod reads, and each table field, that a layer above
 * the defaults gave, `name value (layer)`, "; " between them, in the
 * spec's order; "defaults" for none. */
export function optionsTable(m: Merged): string {
  const out: string[] = []
  for (const [name, option] of Object.entries(OPTIONS)) {
    const layer = m.layers[name]
    const value = m.values[name]
    if (layer === 'default' ||
        !(option.ports as readonly string[]).includes('mod')) continue
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      for (const [row, rec] of Object.entries(value as Rows)) {
        for (const [field, v] of Object.entries(rec)) {
          const by = m.fields[`${name}.${row}.${field}`]
          if (by) out.push(`${name}.${row}.${field} ${JSON.stringify(v)} (${by})`)
        }
      }
      continue
    }
    out.push(`${name} ${JSON.stringify(value)} (${layer})`)
  }
  return out.length ? out.join('; ') : 'defaults'
}

/** One line in the transcript for each file with warnings, the first of
 * them and how many more, once per file and modification time: seen the
 * first time, not on every read (config-merge.md, "Unknown keys and bad
 * values").  Not a toast: a toast takes the footer's line, hiding the 💳
 * at its end.  `$.ui.notice` is a line under a tool call's dialog, which
 * a file's read has none of. */
async function notice($: $, found: Found): Promise<void> {
  const fs = configFs($)
  for (const name of FILE_LAYERS) {
    const path = found.paths[name]
    if (path === null) continue
    const said = found.options.warnings.filter((w) =>
      w.startsWith(path + ': '))
    if (!said.length) continue
    const key = `${path}@${(await fs.stat(path))?.mtimeMs ?? '-'}`
    if (noticed.has(key)) continue
    noticed.add(key)
    const more = said.length > 1
      ? ` (and ${said.length - 1} more in ${LOG_NAME})` : ''
    try {
      // Claude Code puts the plugin's name, "usage-band: ", in front.
      $.ui.log(`config ${said[0]}${more}`)
    } catch (err) {
      await log($, 'config: no notice', err)
    }
  }
}
