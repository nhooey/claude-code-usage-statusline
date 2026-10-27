// A probe, to be removed once read: whether the engine's own rate-limit
// readings carry tenths of a point, which would make the weekly limit's
// figure far more precise than one divided by a whole-point reading.  The
// OAuth usage endpoint reads whole points only, so it is not asked.  Each
// session.measure whose rateLimits differ from the last logged goes to
// usage-band.log.
import type { EngineInterface, SessionRateLimit } from 'claude-code'

import { log } from './log.ts'

type $ = EngineInterface

let last = ''

/** Logs `limits` when they differ from the last logged. */
export async function probeUsage($: $,
  limits: readonly SessionRateLimit[]): Promise<void> {
  const now = JSON.stringify(limits)
  if (now === last) return
  last = now
  await log($, `usage probe: engine ${now}`)
}
