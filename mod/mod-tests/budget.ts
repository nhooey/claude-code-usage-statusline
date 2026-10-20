// The harness's `test`, with a time budget for a test that hangs, not for
// one that runs slow.
//
// The kit fails a test that outlasts 5000 ms of wall time.  The tests
// here are CPU-bound: they parse fixture transcripts, some of them
// megabytes, through the mod and again through src/ for what it should
// have drawn, and nothing in them waits on real time (the clock is
// mock.clock's).  Their wall time is their CPU time over the share of a
// CPU they get, and tests/all.sh runs every suite at once, beside
// whatever else the machine runs: there a test of 2 s alone took over
// 5 s, and failed on time alone, then passed on its own.  So each test
// here gets BUDGET_MS unless it names its own, which still ends a test
// that is stuck.
import { test as kitTest } from 'claude-code/testing'
import type { TestRest } from 'claude-code/testing'

export const BUDGET_MS = 60_000

/** `test` from the kit, its budget BUDGET_MS where it names none. */
export function test(name: string, ...rest: TestRest): void {
  if (rest.length === 1) {
    kitTest(name, { timeoutMs: BUDGET_MS }, rest[0])
  } else {
    kitTest(name, { timeoutMs: BUDGET_MS, ...rest[0] }, rest[1])
  }
}
