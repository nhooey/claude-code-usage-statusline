#!/usr/bin/env python3
"""Write the synthetic corpus golden.sh renders.

    python3 tests/mkcorpus-status.py DIRECTORY

Both halves of it: the transcripts the reader walks, and the status-line
payloads that point at them.  Generated on every run rather than kept on
disk, so a fixture cannot drift away from its generator -- what the goldens
describe is provably this file's output, and a change here shows up as a
golden diff, which is where a change to a fixture belongs.

WHY SYNTHETIC, AND WHY THIS EXISTS AT ALL.  The status corpus used to point
at one real 8.7 MB finished session under ~/.claude/projects/, and eleven of
its fourteen payloads read it.  Every token figure, every chat row and the
whole elapsed group came out of somebody's actual conversation, so the tests
could not move into this repo with the program -- and golden.sh had to carry
a guard that recorded the file's SIZE beside the goldens, because if it were
ever pruned, truncated or resumed, eleven goldens would fail at once and the
diff would blame the program.  The corpus below replaces both: it is small,
it is nobody's conversation, and it is rebuilt from this file every run, so
there is nothing left to guard.

The paths it writes into payloads are derived from the running user's home
rather than hard-coded, and the readout collapses that prefix to "~" before
it prints -- so the goldens carry no username and are the same on any
machine.  Nothing here has to exist on disk: current_dir is a display string
and a project name, not a directory anyone opens.

WHAT EACH RECORD IS FOR.  Every record is the minimum shape the reader
recognises, and the transcript is built to reach the branches a single
recorded session reached by accident and could not be asked to reach again:
a sidechain request that must NOT set the context reading, an interrupted
request whose usage is all zero and must not win the last-write, and a
repeated requestId that must be counted once.  Timestamps are offsets BEFORE
pin-env.sh's PIN_NOW, so every duration the rows report is a stable positive
and the two figures the elapsed row splits -- time answering against time
waiting -- are chosen rather than inherited.
"""
import json
import os
import sys
import time

# pin-env.sh's PIN_NOW, 2026-08-16 02:23:20 UTC.  Repeated rather than
# imported because this file is run by a shell script that has already
# exported it; if the two ever disagree the durations go negative and every
# golden says so at once, which is a loud enough failure.
PIN_NOW = 1786847000

# The session's whole span, and how much of it was spent answering.  Both are
# READINGS on the ⌛ row -- Σ 9.3h against 🤖 3.8h and 👤 5.5h -- so they are
# picked to be three visibly different numbers rather than three that could be
# confused for each other if the row ever lost a field.
AGE_S = 33480          # 9.3h: the first record's distance before PIN_NOW


def iso(before):
    """A timestamp `before` seconds earlier than PIN_NOW."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(PIN_NOW - before))


def prompt(before, text):
    """A record opens_turn() accepts: typed, external, plain-string content."""
    return {"type": "user", "userType": "external", "promptSource": "typed",
            "timestamp": iso(before), "message": {"content": text}}


def answer(before, rid, fresh, cw, cr, out, text=None, sidechain=False):
    """An assistant record carrying billed usage, and optionally text.

    requestId is what dedups a repeat, so it has to be distinct per record and
    stable across runs -- hence a passed-in string rather than a counter.
    """
    blocks = [{"type": "text", "text": text}] if text is not None else []
    return {"type": "assistant", "requestId": rid, "timestamp": iso(before),
            "isSidechain": sidechain,
            "message": {"id": rid, "content": blocks, "usage": {
                "input_tokens": fresh,
                "cache_creation_input_tokens": cw,
                "cache_read_input_tokens": cr,
                "output_tokens": out}}}


def tool_result(before):
    """Work inside a turn that is not a prompt: it extends the turn's span and
    opens nothing.  Content opening with '<' is exactly what a wake message
    looks like, which is why promptSource and not shape is the prompt test."""
    return {"type": "user", "userType": "external", "timestamp": iso(before),
            "message": {"content": "<tool_use_result>ok</tool_use_result>"}}


# The two chat rows, which are the only free text on the readout and the only
# thing on it that gets CUT rather than reserved.
#
# The prompt is long enough to be truncated at all six widths, so fit_cols is
# exercised on every case rather than on the wide ones only.  The reply opens
# on two short lines, because squash turns a newline into ¶ and that is a
# glyph the row has to measure like any other -- and carries one wide emoji
# and one CJK character, which are the two ways a single code point can take
# two columns.  A row that measures those correctly and cuts them at the wrong
# place still lands in the golden as a visible difference.
USER_TEXT = ("Why does the elapsed row report two durations when the session "
             "age is one number, and which of them is the one I should be "
             "reading when the window is about to reset?")
ASST_TEXT = ("Two figures, because one of them is not a duration you spent.\n"
             "\n"
             "The session age is wall clock 🧩 and the other is 時間 answered.")


def main_session():
    """The transcript eleven of the payloads read.

    Four turns across 9.3 hours, with the gaps between them the point: a turn
    runs from the prompt that opens it to the last record before the next
    prompt, so what is summed here is 3.8h of answering inside a session that
    has existed for 9.3.  The two figures together are what the row is for.

    140 requests at a realistic size rather than a handful at an unrealistic
    one.  The reader only sums, so a dozen records carrying seven million
    cache reads each would produce the same totals and would be a fixture no
    session could ever have written.
    """
    recs = []
    # (turn start, seconds answering, requests) -- sums to 13800s = 3.8h.
    turns = ((AGE_S, 7200, 40), (19800, 1800, 15),
             (12600, 4500, 60), (480, 300, 24))
    n = 0
    for ti, (start, span, calls) in enumerate(turns):
        last = ti == len(turns) - 1
        recs.append(prompt(start, USER_TEXT if last else
                           "Turn %d, whose text no row ever shows." % (ti + 1)))
        for i in range(calls):
            # Spread the requests evenly across the turn's span, so the last
            # record of a turn lands on its end and the span the reader
            # measures is the span named above.
            at = start - int(span * (i + 1) / float(calls))
            n += 1
            recs.append(answer(at, "req-%03d" % n, 3, 1800, 155000, 6000))
            if i == 0:
                recs.append(tool_result(at))
        if ti == 1:
            # The same requestId twice.  Claude Code writes a repeat when a
            # request is retried, and counting it twice would inflate every
            # figure on the readout by whatever the retry cost.
            recs.append(answer(start - span, "req-%03d" % n, 3, 1800,
                               155000, 6000))

    # The last three records, and the order is the whole point of them.
    #
    # The context reading is the last NON-SIDECHAIN request with usage, so a
    # subagent's own context must not land here -- it would make the main
    # thread's occupancy jump around as subagents come and go -- and neither
    # must an interrupted request, whose usage is recorded as all zero and
    # which would blank the 🧠 cell for the rest of the session.  Both come
    # AFTER the record that should win, so a reader that takes the last of
    # anything rather than the last of the right thing fails here.
    recs.append(answer(200, "req-ctx", 2, 2900, 112000, 4200, ASST_TEXT))
    recs.append(answer(190, "req-sub", 4, 900, 480000, 3100, sidechain=True))
    recs.append(answer(180, "req-int", 0, 0, 0, 0))
    return recs


def cache_session(read, write):
    """A short session whose only job is one cache-hit rate.

    The 🎯 cell tiers at 80 and 50 and the recorded corpus only ever showed it
    at 98, so two of its three colours had no case at all.  Nothing else here
    is interesting, and it is deliberately short: a fixture that exists for one
    figure should not also be a second opinion on the figures above.
    """
    return [prompt(3600, "Something cheap."),
            answer(3000, "req-c1", 400, write, read, 900, "Done."),
            answer(2400, "req-c2", 400, write, read, 900)]


def rounding_boundary_session():
    """A session whose ▾ total lands one step below a round million.

    999,600 output tokens, which humanize wrote as "1000k" until 2026-09-08 --
    five characters in a four-character field, and a thousand thousands where
    the eye expects a million.  The band is only 500 wide out of a million, so
    no corpus built from plausible round numbers was ever going to land in it;
    it took a live readout to find, and it takes a fixture aimed at it to keep.

    The figures either side are deliberately unremarkable.  This exists for one
    cell and should not also be a second opinion on the ones around it.
    """
    return [prompt(3600, "Something long."),
            answer(3000, "req-b1", 1000, 20000, 300000, 500000, "Done."),
            answer(2400, "req-b2", 1000, 20000, 300000, 499600)]


def agent_session():
    """A session with a fork, whose spend lives in a file BESIDE the
    transcript -- `agents/subagents/agent-fork1.jsonl`, written by main()
    from AGENT_FILES -- and not in it.  The fork's tokens must reach 🧩 and
    🎯; its context must not reach 🧠, which is the main thread's 41,012
    and not the fork's 84,000.  The main record carries the turn's promptId
    on its tool result, which is how the fork's records find their turn.
    """
    return [dict(prompt(3600, "Fork off and read the two exhibits."),
                 promptId="p-fork"),
            answer(3000, "req-m1", 12, 1000, 40000, 700, "Done."),
            dict(tool_result(2400), promptId="p-fork")]


AGENT_FILES = {
    "agents": {
        "agent-fork1.jsonl": [
            {"type": "user", "isSidechain": True, "promptId": "p-fork",
             "timestamp": iso(2900), "message": {"content": "read them"}},
            dict(answer(2800, "req-fk1", 40, 6000, 80000, 2000),
                 isSidechain=True),
            dict(answer(2700, "req-fk2", 10, 2000, 84000, 1500),
                 isSidechain=True),
        ],
    },
}


TRANSCRIPTS = {
    "main": main_session(),
    # A fork's spend beside the transcript; see the builder.
    "agents": agent_session(),
    # The ▾ field one step under a round million; see the builder.
    "rounding-boundary": rounding_boundary_session(),
    # ~70٪ read: the amber tier.
    "cache-warn": cache_session(46000, 19000),
    # ~40٪ read: the red one.
    "cache-crit": cache_session(30000, 44500),
    # A file that exists and holds nothing, which is a different state from a
    # file that is not there -- one renders as a session with no usage yet,
    # the other as no transcript at all.
    "empty": [],
}


def payloads(corpus):
    """The fourteen status-line payloads, as a base and what each case moves.

    Written out in full rather than diffed at read time, because a payload is
    the input a reader is handed and a test that assembles its own input from
    fragments is testing the assembler.
    """
    home = os.path.expanduser("~")
    # Under the home directory on purpose: the readout collapses that prefix
    # to "~", so the golden holds no username.  It does not have to exist.
    cwd = os.path.join(home, "src", "statusline-fixture", "deep", "tree")
    main = os.path.join(corpus, "main.jsonl")
    base = {
        "session_id": "f1xture0-0000-4000-8000-00000000c0de",
        "transcript_path": main,
        "cwd": cwd,
        "effort": {"level": "high"},
        "model": {"id": "claude-opus-5[1m]",
                  "display_name": "Opus 5 (1M context)"},
        "workspace": {"current_dir": cwd, "project_dir": cwd,
                      "added_dirs": []},
        "version": "2.1.233",
        "output_style": {"name": "default"},
        "cost": {"total_cost_usd": 114.63436755000001,
                 "total_duration_ms": 20696166,
                 "total_api_duration_ms": 10592313,
                 "total_lines_added": 3443,
                 "total_lines_removed": 214},
        "context_window": {"context_window_size": 1000000},
        "exceeds_200k_tokens": True,
        "thinking": {"enabled": True},
        # PIN_NOW + 400s and PIN_NOW + 1.9 days: near enough for the 🔋
        # countdown to read in minutes and far enough for 🪫 to read in days,
        # which is the pair that proves short_dur picks a unit rather than a
        # scale.
        "rate_limits": {
            "five_hour": {"used_percentage": 15, "resets_at": PIN_NOW + 400},
            "seven_day": {"used_percentage": 87,
                          "resets_at": PIN_NOW + 167800}},
    }

    def case(**over):
        d = json.loads(json.dumps(base))
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                d[k].update(v)
            elif v is None:
                d.pop(k, None)
            else:
                d[k] = v
        return d

    out = {
        "01-baseline": case(),
        # No rate_limits at all: the payload stops being the source and
        # limits_snapshot has to choose between the plan cache and the app.
        "02-no-limits": case(rate_limits=None),
        # A path that is not there, which is not the same as a path that is
        # there and empty.
        "03-no-transcript": case(transcript_path="/nonexistent/x.jsonl"),
        # The two segments of column 1, which are the two that can be absent.
        "04-pr-and-style": case(output_style={"name": "explanatory"},
                                pr={"number": 4211}),
        "05-haiku-max": case(
            model={"id": "claude-haiku-4-5", "display_name": "Haiku 4.5"},
            effort={"level": "max"},
            context_window={"context_window_size": 200000}),
        # Nothing added, nothing removed, and a cost under a dollar.
        "06-zero-cost": case(cost={"total_cost_usd": 0.4,
                                   "total_duration_ms": None,
                                   "total_api_duration_ms": None,
                                   "total_lines_added": 0,
                                   "total_lines_removed": 0}),
        "07-big-numbers": case(cost={"total_cost_usd": 1234.56,
                                     "total_lines_added": 99999}),
        "08-limits-critical": case(rate_limits={
            "five_hour": {"used_percentage": 97, "resets_at": PIN_NOW + 400},
            "seven_day": {"used_percentage": 99,
                          "resets_at": PIN_NOW + 167800}}),
        # No session id: nothing to publish the context window under, and
        # nothing for the cost line to read back.
        "09-no-session-id": case(session_id=""),
        # Every field absent at once.  The readout has to render something
        # for a payload that says nothing, and this is the case that says
        # what.
        "10-empty-payload": {},
        "11-sonnet-200k": case(
            model={"id": "claude-sonnet-4-6", "display_name": "Sonnet 4.6"},
            context_window={"context_window_size": 200000}),
        # The one path with no home prefix to collapse and no name to trim.
        "12-root-cwd": case(workspace={"current_dir": "/",
                                       "project_dir": "/"}),
        "13-empty-transcript": case(
            transcript_path=os.path.join(corpus, "empty.jsonl")),
        "14-limits-full": case(rate_limits={
            "five_hour": {"used_percentage": 100, "resets_at": PIN_NOW + 400},
            "seven_day": {"used_percentage": 100,
                          "resets_at": PIN_NOW + 167800}}),
        # The two 🎯 tiers the recorded corpus never reached.
        "15-cache-warn": case(
            transcript_path=os.path.join(corpus, "cache-warn.jsonl")),
        "16-cache-crit": case(
            transcript_path=os.path.join(corpus, "cache-crit.jsonl")),
        # The unit ladder's rounding cut, which no other payload reaches.
        "17-rounding-boundary": case(
            transcript_path=os.path.join(corpus, "rounding-boundary.jsonl")),
        # A fork's spend in a file beside the transcript: 🧩 and 🎯 count it,
        # 🧠 does not, and the 🔋/🪫 session shares are priced with it.
        "18-agents": case(
            transcript_path=os.path.join(corpus, "agents.jsonl")),
    }
    # The cost fields of 06 are dropped, not set to None; case() cannot spell
    # that inside a nested dict, so it is done here.
    for k in ("total_duration_ms", "total_api_duration_ms"):
        out["06-zero-cost"]["cost"].pop(k, None)
    return out


def main(out_dir):
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    for name, recs in TRANSCRIPTS.items():
        with open(os.path.join(out_dir, name + ".jsonl"), "w") as fh:
            for r in recs:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
    for name, files in AGENT_FILES.items():
        for rel, recs in files.items():
            path = os.path.join(out_dir, name, "subagents", rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                for r in recs:
                    fh.write(json.dumps(r, sort_keys=True) + "\n")
            with open(path[:-len(".jsonl")] + ".meta.json", "w") as fh:
                json.dump({"agentType": "fork", "isFork": True,
                           "spawnDepth": 1}, fh)
    for name, pay in payloads(out_dir).items():
        with open(os.path.join(out_dir, name + ".json"), "w") as fh:
            json.dump(pay, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
