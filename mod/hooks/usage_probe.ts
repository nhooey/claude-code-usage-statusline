// A probe, to be removed once read: how precise the OAuth usage endpoint's
// readings are, beside the engine's own, so the weekly limit's figure can
// take whichever source is finer.  Once per load of the mod, it fetches
// /api/oauth/usage with the session's own credential, which the engine
// sets and sends only to a first-party host, and logs the raw body and the
// engine's rateLimits of the same moment to usage-band.log.
import type { EngineInterface } from 'claude-code'

import { log } from './log.ts'

type $ = EngineInterface

const URL = 'https://api.anthropic.com/api/oauth/usage'

let probed = false

/** Logs one reading of the endpoint and the engine's, once per load. */
export async function probeUsage($: $): Promise<void> {
  if (probed) return
  probed = true
  const auth = await $.session.authorize()
  if (!auth) {
    await log($, 'usage probe: no first-party credential')
    return
  }
  const engine = (await $.session.usage()).rateLimits
  const r = await $.http.fetch(URL, { auth: auth.handle,
    headers: { 'anthropic-beta': 'oauth-2025-04-20' } })
  await log($, `usage probe: oauth ${r.status} ${r.text.slice(0, 2000)}`)
  await log($, `usage probe: engine ${JSON.stringify(engine)}`)
}
