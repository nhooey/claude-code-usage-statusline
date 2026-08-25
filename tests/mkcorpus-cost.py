#!/usr/bin/env python3
"""Write the synthetic transcripts golden-cost.sh renders.

    python3 ~/.claude/tests/mkcorpus-cost.py DIRECTORY

Generated on every run rather than kept on disk, so the fixtures cannot drift
away from the generator: what the goldens describe is provably this file's
output.  A change here shows up as a golden diff, which is where a change to a
fixture belongs.

WHY SYNTHETIC.  The differential test this replaces took real transcripts on
its command line — `difftest-cost.sh TRANSCRIPT [TRANSCRIPT...]` — and had no
corpus of its own at all.  That is fine for comparing two programs, which
agree or disagree on whatever they are handed; it cannot produce a golden,
because the input is different every time it is run and belongs to whoever ran
it.  Real transcripts are also the wrong thing to copy into a test directory:
they are megabytes of somebody's actual conversation.

Every record here is the minimum shape the reader recognises, and each case
exists for one branch of it.  Timestamps are fixed and sit before pin-env.sh's
PIN_NOW, so every duration the rows report is a stable positive.
"""
import json
import os
import sys

T0 = "2026-08-16T01:%02d:%02dZ"          # all stamps, ~80 minutes before PIN_NOW


def ts(minute, second=0):
    return T0 % (minute, second)


def prompt(minute, text):
    """A record opens_turn() accepts: typed, external, plain-string content."""
    return {"type": "user", "userType": "external", "promptSource": "typed",
            "timestamp": ts(minute), "message": {"content": text}}


def answer(minute, rid, fresh, cw, cr, out, sidechain=False):
    """An assistant record carrying billed usage.

    requestId is what dedups repeats, so it has to be distinct per record and
    stable across runs — hence a passed-in string rather than a counter.
    """
    return {"type": "assistant", "requestId": rid, "timestamp": ts(minute),
            "isSidechain": sidechain,
            "message": {"id": rid, "usage": {
                "input_tokens": fresh,
                "cache_creation_input_tokens": cw,
                "cache_read_input_tokens": cr,
                "output_tokens": out}}}


def wake(minute, text, meta=True):
    """A message DELIVERED to an idle session, which opens a turn like a prompt.

    `promptSource: "system"` is the whole of what marks one, and it is the only
    thing that can: a task notification opens with '<' exactly as a tool result
    does, and a peer message is flagged isMeta exactly as a system reminder is.
    Both shapes are here for that reason — `meta=False` is the task
    notification's, which the '<' rule alone would refuse.
    """
    return {"type": "user", "userType": "external", "promptSource": "system",
            "isMeta": meta, "timestamp": ts(minute),
            "message": {"content": text}}


PEER = ('Another Claude session sent a message:\n'
        '<cross-session-message from="uds:/tmp/cc-socks/54251.sock"'
        ' from-name="%s" from-mode="prompting">\n%s\n'
        '</cross-session-message>')

TASK = ('<task-notification>\n<task-id>%s</task-id>\n'
        '<status>completed</status>\n</task-notification>')


def tool_result(minute):
    """A turn that ended on a tool result.  It is `type: user` like a prompt,
    and what keeps it out of opens_turn() is that its content is a LIST."""
    return {"type": "user", "userType": "external", "timestamp": ts(minute),
            "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


def boundary(minute, pre, ms, trigger="auto"):
    return {"type": "system", "subtype": "compact_boundary",
            "timestamp": ts(minute),
            "compactMetadata": {"trigger": trigger, "preTokens": pre,
                                "postTokens": 8737, "durationMs": ms}}


def summary(minute, chars):
    """What the summariser wrote, which is the one figure the boundary's own
    metadata does not carry.  Estimated from its length at SUMMARY_CPT."""
    return {"type": "user", "userType": "external", "isCompactSummary": True,
            "timestamp": ts(minute), "message": {"content": "s" * chars}}


def stop(minute):
    """The transcript's own mark that a Stop hook ran.  It is what makes the
    window this run reports start where the last one stopped."""
    return {"type": "system", "subtype": "stop_hook_summary",
            "timestamp": ts(minute), "isSidechain": False}


CASES = {
    # Three answered prompts, each larger than the last, with a Stop between
    # them.  The ordinary case: one prompt row and a totals row.
    "01-plain": [
        prompt(10, "Explain the width table."),
        answer(11, "req-a1", 12, 2400, 40000, 900),
        answer(12, "req-a2", 3, 0, 43000, 1500),
        stop(13),
        prompt(20, "Now do the same for the escape table."),
        answer(21, "req-b1", 8, 1800, 61000, 2100),
        stop(22),
        prompt(30, "And the one after that, please."),
        answer(31, "req-c1", 5, 900, 78000, 3400),
    ],

    # An automatic compaction: no prompt in front of it, so it gets a turn of
    # its own and the 🤏 label.  The prompt after it reports the drop across
    # the boundary as a large negative Δctx, which is the single most useful
    # figure either row prints.
    "02-compaction": [
        prompt(10, "A long conversation up to here."),
        answer(11, "req-d1", 10, 3000, 289000, 1200),
        stop(12),
        boundary(15, 292645, 41000),
        summary(16, 16201),
        prompt(20, "Carrying on after the compaction."),
        answer(21, "req-e1", 6, 1100, 95691, 800),
    ],

    # One prompt, and therefore no previous reading to subtract: the first
    # turn of a transcript reports no Δctx rather than reporting its own
    # absolute size as though it were growth.
    "03-single-turn": [
        prompt(10, "The only thing anyone said."),
        answer(11, "req-f1", 20, 5000, 12000, 640),
    ],

    # A turn whose last record is a tool result.  It ends at the result, not
    # at the last billed request, so the elapsed figure has to count it.
    "04-tool-result": [
        prompt(10, "Run the probe and tell me what it said."),
        answer(11, "req-g1", 7, 1500, 33000, 450),
        tool_result(14),
    ],

    # Sidechain records are billed but are NOT a reading of this window, so
    # they must add to the token sums and leave ctx alone.  The turn's ctx is
    # 41,012 from the main record, not 900,000 from the sidechain.
    "05-sidechain": [
        prompt(10, "Delegate something."),
        answer(11, "req-h1", 12, 1000, 40000, 700),
        answer(12, "req-h2", 4, 6000, 894000, 2000, sidechain=True),
    ],

    # An interrupted request writes every usage field zero.  Taking that as
    # the reading wipes the real one captured seconds earlier and blanks the
    # turn's 🧠 cell entirely.
    "06-interrupted": [
        prompt(10, "Start something and then type over it."),
        answer(11, "req-i1", 9, 2200, 51000, 1100),
        answer(12, "req-i2", 0, 0, 0, 0),
    ],

    # Nothing at all.  The hook must print a bare "{}" and disturb no turn.
    "07-empty": [],

    # Turns nobody typed.  A session another session woke, which is the case
    # the reader could not see at all: with the wake messages refused, the
    # first turn here had no prompt to belong to and was DROPPED — its four
    # requests reported by no row and counted in no total — and the hook
    # printed "(no prompts recorded yet)" against a session that had been
    # working for twenty minutes.  Measured in the transcript that prompted
    # this: 74 of 87 requests and 15.7M of cache-read, gone.
    #
    # Four shapes, in the order they occur here:
    #
    #   * a peer message with no typed prompt anywhere before it, which is
    #     what makes the turn undroppable rather than merely mislabelled;
    #   * a typed prompt, so the wake turns are not the only ones and the
    #     totals row has something to be a total OF;
    #   * two peer messages delivered in one batch.  Only the second carries
    #     requests, and the first must not be what the 💬 row reports;
    #   * a task notification, which opens with '<' and is therefore the case
    #     that proves promptSource — not the shape checks — is what admits it.
    "08-woken": [
        wake(5, PEER % ("claude-code-39", "Have a look at the width table.")),
        answer(6, "req-j1", 9, 2600, 44000, 1300),
        stop(7),
        prompt(10, "And now one I typed myself."),
        answer(11, "req-j2", 4, 1200, 52000, 1800),
        stop(12),
        wake(20, PEER % ("Market", "First of two, delivered together.")),
        wake(20, PEER % ("Market", "Second of two, and this one is answered.")),
        answer(21, "req-j3", 6, 1500, 67000, 2200),
        wake(30, TASK % "b1s1s9729", meta=False),
        answer(31, "req-j4", 11, 800, 71000, 950),
    ],
}


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for name, records in sorted(CASES.items()):
        path = os.path.join(out_dir, name + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
