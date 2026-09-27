---
name: coding-agent-usage-line-report-eta
description: Report a running ETA while working on any task expected to take more than about a minute, as the main agent or as a subagent. Use it at the start of such a task. coding-agent-usage-line reads the report from the transcript and draws it on the agent's row in the agent panel, and on the status line, as a countdown and a progress bar.
---

# Report an ETA

Say how long your task has left by writing this line on its own, outside any
code block or quote:

    🏁 skills/coding-agent-usage-line-report-eta: ETA <number><s|m|h>

For example, a task with about four minutes to go gets a line with `ETA 4m`.

- The number is the wall-clock time LEFT on your whole task, not the total.
  It counts tool runs and waits as well as your own work.
- It is your own conceptual estimate, from your plan. If the plan has you
  waiting on subagents, or starting more of them once the current ones are
  done, count that time as you expect it to go.
- Don't collect your subagents' reported ETAs and add them up or copy them.
  They report their own, and the display already makes sure your row never
  finishes before any subagent it is waiting on. Your number only has to
  say what your plan says.
- Write it once you have a plan, again after each milestone, and whenever
  your estimate changes by a quarter or more.
- Write one last line with an ETA of 0s when you finish.
- If you end your turn to wait on background work, put the line in that
  last message. A turn that ends without one reads as finished.
- Never write the line for any other reason, and don't explain it.

The line is read from your own messages only. It needs nothing else: no tool
call, no file. Between reports the display counts your last estimate down by
itself, and if you run past it, it says by how much.
