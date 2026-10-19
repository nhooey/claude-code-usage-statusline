import type { EngineInterface, Register } from 'claude-code'

// The mockup draws every row; this mod only puts them where the design
// would.  Plain text: the question is widths, not colour.
const MOCKUP = '/Users/nhooey/git/github/nhooey/claude-code-usage-statusline/mod/tools/layout-mockup.ts'

async function rows($: EngineInterface, part: string, cols: number, phase = 'running') {
  const r = await $.process.run(['node', MOCKUP, '--plain', '--part', part,
                                 '--phase', phase, '--cols', String(cols)])
  return r.stdout.replace(/\n+$/, '').split('\n')
}

// A row of ticks every ten columns, as wide as the body, so where the
// cells end can be read against it.
function ruler(cols: number) {
  let s = ''
  for (let i = 1; i <= cols; i++) s += i % 10 === 0 ? String((i / 10) % 10) : i % 5 === 0 ? ':' : '.'
  return s
}

// A duration as Claude Code's closing line writes it: "5s", "4m 2s", "1h 3m".
function span(ms: number) {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

export const register: Register = on => {
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const body = e.props.bodyColumns
    const lines = await rows($, 'band', body + 5)
    return (
      <Box flexDirection="column">
        <Text dimColor>{ruler(body)}</Text>
        {lines.map((l, i) => <Text key={String(i)} wrap="truncate-end">{l}</Text>)}
      </Box>
    )
  })

  // Drawn whole rather than around next(e): the engine's line is a
  // full-width row, so text set beside it lands at the right edge.
  on('ui.render', { component: 'TurnDuration' }, async ($, e, _next) => {
    const { Box, Text } = $.ui.resolve(e)
    const cols = e.viewport?.columns ?? 150
    const [head, ...rest] = await rows($, 'receipt', cols, 'done')
    return (
      <Box flexDirection="column">
        <Text dimColor>{`✻ ${e.props.word} for ${span(e.props.durationMs)} · ${head}`}</Text>
        {rest.map((l, i) => <Text key={String(i)} wrap="truncate-end">{l}</Text>)}
      </Box>
    )
  })

  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const row = await next(e)
    if (e.props.origin.kind !== 'composer') return row
    const { Box, Text } = $.ui.resolve(e)
    const [tag] = await rows($, 'start', 150)
    return (
      <Box flexDirection="column">
        {row}
        <Text dimColor>{'  ' + tag}</Text>
      </Box>
    )
  })
}
