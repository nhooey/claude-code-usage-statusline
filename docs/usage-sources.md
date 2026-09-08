# Plan figures when the payload carries none

The two limit rows — 🔋 the 5-hour window, 🪫 the 7-day one — want a
whole-plan percentage and a reset time. Claude Code's status-line payload
carries both in `rate_limits`, and when it does, that is what is used, whole:
it is the API's own accounting, arriving with the render rather than through a
file. `load_limits` is all-or-nothing about it, so a payload that supplies
either figure supplies both rows or neither.

Two of the sixteen payload shapes in the corpus carry no such block, and the
`Stop` hook's payload never does. So there is a second channel, and something
has to fill it. That something is a **usage source**.

## The interface

A source is an object with a `name`, an `available()` and a `read()`.
`read()` returns a plain dict, may return `{}`, and is not required to know
anything about the readout. Everything else happens once, in
`normalise_reading()`:

* times become local `%Y-%m-%d %H:%M` stamps, from Unix epochs, Apple epochs
  or stamps, whichever the source had;
* percentages become numbers, or vanish;
* **any other key is dropped.**

The third is not tidiness. The reading is written to a file under `/tmp`, and
a source is an arbitrary program reading an arbitrary store — the built-in one
reads a record that also holds an OAuth account blob and an API session key,
three keys along from the figures it wants. A pass-through would put whatever
a source handed back into that file forever. A whitelist puts seven fields
there and cannot be talked into an eighth. `tests/usage-source.py` plants a
credential-shaped canary in its fixture and fails if it reaches either the
reading or the disk.

A reset time that is not at least five minutes in the future is dropped rather
than carried, because a countdown of zero reads as a window about to turn over
rather than as a reading nobody should trust. A reading with neither
percentage in it is not a reading and cannot overwrite a good one.

## The built-in source

[**Claude Usage Tracker**](https://github.com/hamed-elfayome/Claude-Usage-Tracker),
a macOS menu-bar app, is the one source shipped. It polls Anthropic on its own
schedule and keeps the answer in its UserDefaults store, which is the whole
appeal: no OAuth handling here, no network call, no token to keep. The figures
are already on disk and somebody else's program is responsible for them.

It is read through `defaults export` rather than by opening the `.plist`,
because a running app's preferences live in `cfprefsd` and reach the file when
`cfprefsd` feels like it — the app writes every 30 seconds and the file lagged
it by minutes in testing. `CLAUDE_USAGE_TRACKER_PLIST` overrides that with a
path to an exported store, which is how the tests drive it on a machine with
no app, and how a store copied off another machine can be read.

`activeProfileId` names the account record to read; `isSelectedForDisplay` is
the fallback and the first record is the fallback's fallback. Six fields are
taken from the `claudeUsage` object inside it and nothing else is touched.

## Anything else, in twenty lines

`--usage-source cmd:PATH` runs a program and reads JSON off its stdout. That
is the whole contract — print an object, exit 0 — and since
`normalise_reading()` accepts epochs or stamps and any subset of the fields, a
working source is about this long:

```sh
#!/bin/sh
printf '{"session_pct": %s, "weekly_pct": %s, "session_resets_at": %s}\n' \
    "$(your_thing --session)" "$(your_thing --week)" "$(your_thing --reset)"
```

It is run directly if it is executable and through `bash` if it is not, which
is the difference a fresh checkout of somebody's dotfiles makes. A source
worth shipping is a subclass of `UsageSource` added to `USAGE_SOURCES`, which
is what `auto` walks.

## What this replaced, and how it failed

Until 2026-09-08 this channel was a shell script **outside this repository**:
`~/.claude/usage-limits.sh`, wrapping `~/.claude/usage-now.sh`, wrapping
`defaults export`, wrapping a `python3` of its own. Three processes and two
files that were never installed with the program and were named nowhere in
this documentation, so a clone of this repository could not read a plan
figure at all and nothing on the readout said why.

It also broke without saying so. The app moved its snapshot history out of
UserDefaults into a file — the store still carries the
`usageHistoryMigratedToFiles_v1` marker of it — and the `usageHistory_<uuid>`
key both scripts keyed off stopped existing. The wrapper caught the failure,
printed `{}`, exited 0, and the fallback answered "no reading" for days. The
limit rows have a legitimate blank state, so what a reader saw was a plausible
readout.

That is the failure mode of a three-layer shell-out: every layer swallows, and
the last layer is not in the repository whose tests would have caught it. The
reading is now taken in-process, the schema it expects is a fixture in
`tests/usage-source.py`, and CI runs it.

One thing was lost with the scripts and is not coming back. The old store did
not publish the 5-hour reset at all — on a `sessionReset` snapshot,
`triggeringResetTime` was a copy of the snapshot's own timestamp — so the
wrapper derived the window from the most recent 0٪ → non-zero transition in
the snapshot history. The current schema publishes that reset directly and
correctly (measured 2026-09-08: 77 minutes ahead of the reading carrying it),
so the derivation is documented in `tracker_reading()` rather than ported.
Reviving it means reading the history file the app now keeps under
`~/Library/Application Support/Claude Usage/history/`; it does not mean
remembering what it did.

