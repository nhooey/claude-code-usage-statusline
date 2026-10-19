// The mod's log: what it started and what failed, so a live test can say
// why something did not draw.
//
// The handlers catch what fails, so that a read gone wrong leaves the last
// drawing up rather than failing the engine's event; this is where what
// they caught goes.  Each line goes two ways:
//
//   Claude Code's debug log, through `$.ui.log(…, { to: 'debug' })`, which
//   is written when Claude Code runs with `--debug` or `--debug-file
//   <path>`, beside the engine's own lines about the mod's hooks;
//
//   `usage-band.log` in the status line's state directory, always: the
//   last LOG_KEPT lines from every session, each naming its session, as
//   src/modlog.ts lays them out.
//
// A line is never allowed to fail its caller: a log that cannot be written
// is a log with a line missing.
import type { EngineInterface } from 'claude-code'

import { placesOf } from './edges.ts'
import { LOG_KEPT, LOG_NAME, describe, logAppended, logLine }
  from '../src/modlog.ts'

type $ = EngineInterface

export { LOG_KEPT, LOG_NAME, describe }

// One write at a time, so a burst of lines keeps its order.
let writing: Promise<void> = Promise.resolve()

/** Logs `what`, with the error it is about if there is one. */
export async function log($: $, what: string, err?: unknown): Promise<void> {
  let line = what + (err === undefined ? '' : ': ' + describe(err))
  try {
    const id = await $.session.id().catch(() => '?')
    line = logLine(await $.clock.now(), id, what, err)
  } catch {
    // The line without its time.
  }
  try {
    $.ui.log('usage-band: ' + line, { to: 'debug' })
  } catch {
    // No debug log.
  }
  const done = writing.then(() => append($, line))
  writing = done.catch(() => {})
  await writing
}

/** The line added to the file: read afresh each time, so the lines other
 * sessions wrote since stay, and cut to the newest LOG_KEPT.  `$.fs` has
 * no append. */
async function append($: $, line: string): Promise<void> {
  try {
    const path = (await placesOf($)).stateDir + '/' + LOG_NAME
    let old = ''
    try {
      old = await $.fs.read(path)
    } catch {
      // No log yet.
    }
    await $.fs.write(path, logAppended(old, line))
  } catch {
    // Unwritable: the debug log has it.
  }
}
