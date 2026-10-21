// The defaults file in the harness, which has no file system: its text as
// tools/gen-mod-fixtures.ts carries it, read as the mod reads it, and
// answered where the mod looks for it, `$.plugin.root` + DEFAULTS_REL.
import { DEFAULTS_TEXT } from './fixtures.gen.ts'
import { DEFAULTS_REL, parseDefaults } from '../src/config.ts'

export { DEFAULTS_TEXT }

/** The shipped defaults, every option by name. */
export const DEFAULTS = parseDefaults(DEFAULTS_REL, DEFAULTS_TEXT)

/** Whether `path` is the defaults file the mod reads, under its folder. */
export const isDefaults = (path: string): boolean =>
  path.endsWith('/' + DEFAULTS_REL)
