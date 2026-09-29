---
name: coding-agent-usage-line-report-eta
description: Report a running ETA while working on any task expected to take more than about a minute, as the main agent or as a subagent. Use it at the start of such a task. coding-agent-usage-line reads the report from the transcript and draws it on the agent's row in the agent panel, and on the status line, as a countdown and a progress bar.
---

# Report an ETA

Say how long your task has left by writing this line on its own, outside any
code block or quote:

    ⛳ skills/coding-agent-usage-line-report-eta: ETA <number><s|m|h>

For example, a task with about four minutes to go gets a line with `ETA 4m`.

- The number is the wall-clock time LEFT on your whole task, not the total.
  It counts tool runs and waits as well as your own work.
- It is your own conceptual estimate, from your plan. If the plan has you
  waiting on subagents, or starting more of them once the current ones are
  done, count that time as you expect it to go.
- Don't collect your subagents' reported ETAs and add them up or copy them,
  unless you are told to `recurse` (below). They report their own, and the
  display already makes sure your row never finishes before any subagent it
  is waiting on. Your number only has to say what your plan says.
- Write it once you have a plan, again after each milestone, and whenever
  your estimate changes by a quarter or more.
- Write one last line with an ETA of 0s when you finish.
- If you end your turn to wait on background work, put the line in that
  last message. A turn that ends without one reads as finished.
- Never write the line for any other reason, and don't explain it.

## When told to `recurse`

`recurse` asks for one ETA covering you and every agent under you:

1. If you have subagents, send each running one this message, word for
   word, and nothing in place of it:

       Call your Skill tool with skill `coding-agent-usage-line-report-eta`
       and args `recurse`, and follow it. Write the ETA line in your own
       reply, then send me the same number.

   Never paraphrase the steps into the message: a subagent that gets a
   summary follows the summary, and one that writes its line only inside
   a message to you never updates its own row. The Skill tool loads the
   same text a `/coding-agent-usage-line-report-eta recurse` typed in the
   subagent's own pane would.
2. Wait for every reply. A message reaches a subagent only when its
   current tool call returns, so one inside a long command answers after
   the command. Wait up to 5 minutes; for a subagent that has not replied
   by then, use the last ETA it sent you, or your own estimate of it where
   it has sent none, and say which subagents those were.
3. Estimate your own remaining work in two parts: what runs alongside your
   subagents, and what can only start once they finish. Your subagents
   and your parallel work overlap, so take the longest of them; then add
   the work that waits on them:

       aggregate = max(your parallel work, each subagent's ETA)
                 + your work after they finish

   Where only some subagents gate later work, add that work after the
   ones it waits on, and take the longest path through the whole plan.
4. Write the aggregate as your ETA line in your own reply. If you have a
   parent agent, also send it the same number; the message is in addition
   to your own line, never in place of it.

## How it is read

The line is read from your own messages only: a line inside a message you
send another agent is not read. It needs nothing else: no tool call, no
file. Between reports the display counts your last estimate down by
itself, and if you run past it, it says by how much.
