// The files both ports keep in the state directory, named as state.py's
// state_name and state_path name them, from spec/state.jsonc's table.
import { pyJoin } from "./claude_records.ts";
import { sha256Hex } from "./sha256.ts";
import { STATE_KINDS } from "./state_spec.ts";

export type StateKind = keyof typeof STATE_KINDS;

/** The kind's prefix, the sha256 of its format and the key's parts joined
 * by NULs, and its suffix.  Throws for the wrong number of parts, where the
 * Python raises. */
export function stateName(kind: StateKind, ...key: string[]): string {
  const row = STATE_KINDS[kind];
  if (key.length !== row.key.length) {
    throw new TypeError(`${kind} takes ${row.key.length} key parts`);
  }
  return row.prefix +
    sha256Hex([String(row.format), ...key].join("\0")) + row.suffix;
}

/** stateName's file in the state directory `dir`. */
export function statePath(dir: string, kind: StateKind,
  ...key: string[]): string {
  return pyJoin(dir, stateName(kind, ...key));
}
