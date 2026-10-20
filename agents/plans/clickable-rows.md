# Clickable rows: from a figure to its place in the transcript

A proposal; step 1 built, its live trial pending (asked 2026-10-20: "Can we make the Turn/Agent
messages clickable so they go to that part in the transcript?").

## Why

The band's 🎤 and 🤖 rows, the receipt's rows and an agent's message row
each stand for a place in the transcript: the prompt that began the turn,
the reply that ended it, the agent that sent the message. Today they only
say so; a press could take you there.

## What the engine gives

- **`<Button onPress>`** from `$.ui.resolve(e)`: any drawn row can be
  pressed, by a click or by Enter under the focus.
- **`$.ui.scroll({ to: { requestId }, block })`**: brings a render
  instance into view. A transcript row moves only while the call answers
  the person's own input, which a press is.
- **`$.ui.view({ agentId })`**: puts an agent's transcript in the main
  view, as a pick from the tasks list does; `$.ui.view({})` goes back.

## The design

| Row | A press | Target |
|---|---|---|
| 🎤 in the band, and in a receipt | scroll to the prompt that began the turn | the `UserMessage` render instance of that prompt |
| 🤖 in the band, and in a receipt | scroll to the turn's last reply | the `AssistantMessage` render instance of that reply |
| `› 🤖📨` an agent's message, folded or unfolded | open that agent's transcript | `$.ui.view({ agentId })` of the agent senderOf found |
| an agent row's name, if the panel's rows ever move into the mod | the same | the same |

The mod learns each target's `requestId` as Claude Code draws it: the
`UserMessage` hook already keys a composer prompt by `startKey(text)` for
its 🔻🔖 tag; it records the instance's `requestId` beside it, and an
`AssistantMessage` hook records the last reply's per turn. Both live in
`$.state`, bounded like the start lines (`startsKept`).

## What only a live trial settles

1. Whether a `Button` works under the footer line (`PromptHint`) and in a
   `UserMessage` row, not only in the band above the prompt and in panes.
2. Whether `$.ui.scroll` reaches a row scrolled far back, or only rows the
   transcript still holds drawn.
3. Whether clicks reach Claude Code through tmux's mouse mode at all, or
   only Enter under the focus does.

## The build order

1. **The trial.** The 🎤 row and the agent message row become Buttons; a
   press logs what it would do and does it (`$.ui.scroll` to the prompt,
   `$.ui.view` for the agent); a mod test presses each. The user clicks
   them live and reports what moves. Nothing else changes.

   **Status 2026-10-20: built; the live trial is the user's.** As built:
   - The band's 🎤 row under the footer line (`PromptHint`) is a `plain`
     Button with no hotkey around the row's Text, so it looks as before.
     A press calls `$.ui.scroll({ to: { requestId }, block: 'start' })`
     for the composer prompt the last main-thread turn opened with (the
     prompt drawn last where no turn has opened since the load). Each
     composer `UserMessage` draw records its `requestId` under
     `startKey(text)` in a module map, bounded by `startsKept`; with
     none recorded the press logs `press 🎤: no prompt drawn to scroll to`.
   - The agent message row, folded and every row unfolded, is the same
     plain Button where senderOf found the agent; a press calls
     `$.ui.view({ agentId })`. With the sender unknown the row is a plain
     Text, as before, and does not press.
   - Each press logs the call and its answer to `usage-band.log`:
     `press 🎤: $.ui.scroll({...}) -> {}` or `-> {"deny":"…"}`, `threw`
     with the error; `press 🤖📨 "<task>": $.ui.view({"agentId":"…"})
     -> …`.
   - The test kit has no `$.ui.scroll` for a transcript row (it resolves
     the call to a site itself and answers `no implementation`), so the
     mod test checks the call the press made from the log line;
     `$.ui.view` is answered by a test hook and checked directly.
   - The band above the prompt (`bandPlace: 'above'`) is not pressable.
2. **The targets.** The `requestId`s recorded as above; 🎤 and 🤖 in the
   band and in the receipt pressable; a press on a target no longer
   drawn says so once in the log and does nothing.
3. **Docs.** `docs/layout.md` says which rows press and where to.

Step 1 decides whether steps 2 and 3 go ahead as written.

## Files

`mod/hooks/register.tsx` (the row drawing, `line()`, the `UserMessage`
hooks, the receipt stamp), `mod/src/agent_message.ts`, `mod/mod-tests/`,
`docs/layout.md`. `register.tsx` is rewritten by the configuration plan's
step 6 (every `CONFIG.x`); see [the schedule](_schedule.md).
