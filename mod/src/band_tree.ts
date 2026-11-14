// The band's tree of threads above the prompt.
//
// agents/plans/one-panel-port.md, "The band's tree", has the design.  🎮
// the session is the root, its label the workspace; 🎤 the turn and 🧵 the
// main thread are its children, in that order, and each subagent hangs
// under the thread that started it, in the order they started.  Every row
// is a row of the one grid (grid.ts): the hierarchy is in the label
// alone, as `├─` `╰─` `│` lines three columns a level, so every figure
// keeps its column on every row.
//
// Under 🧵 main, after its agents, `✅ N done` sums the subagents that
// finished in the turn.  Past the cap, the later siblings under one parent
// are summed on that parent's `… N more`, and every shown row's parents
// stay.  Both are folded rows: their agents are not drawn.  A row with
// children draws ⊟ in its tree line, or ⊞ where it is folded, and a
// folded agent counts every agent hidden under it with 👶🏻.
//
// Pure: the rows' figures come in built (band.ts), and the agents as the
// document's prepared tasks (subagent_tasks.ts).
import {
  E_FOLD_OPEN, E_FOLD_SHUT, E_MODE_DONE, E_MORE, E_PHASE_END, E_PHASE_PAUSE,
  E_PHASE_RUN, E_SESS, E_THREAD, E_TREE_BAR, E_TREE_DASH, E_TREE_LAST,
  E_TREE_MID, E_TURN, E_WEEK, E_SESSION, E_EFF_HIGH, E_IDLE, MAG_DUR_S,
} from "./spec.ts";
import { durFmt, magDim, padVal } from "./formatting.ts";
import type { Settings } from "./formatting.ts";
import { span, spans } from "./spans.ts";
import type { Span } from "./spans.ts";
import { pyFormatF } from "./py.ts";
import type { Dict } from "./py.ts";
import { squash } from "./claude_records.ts";
import { renderCost, renderTokens } from "./claude_render.ts";
import type { Limits } from "./claude_sources.ts";
import {
  agentCells, agentElapsed, agentLabel, agentState, inheritedEtas,
  parked, renderAgentCache, renderAgentDiff, renderAgentLimit, renderAgentRate,
  renderAgentSplit, renderInbox, runningParents, treeShape,
} from "./claude_subagent_render.ts";
import type { Eta } from "./claude_subagent_render.ts";
import { workspacePieces } from "./cells.ts";
import type { Workspace } from "./cells.ts";
import { preparedOf } from "./subagent_tasks.ts";
import type { TreeTask } from "./subagent_tasks.ts";
import { hidden } from "./grid.ts";
import type { Piece, Row } from "./grid.ts";

/** The subagents the tree draws: the document's prepared tasks, the plan
 * reading their shares are drawn under, the clock, and when the turn
 * opened, which `✅ N done` counts finishes from (null: no turn running,
 * and no `✅ N done`). */
export type TreeAgents = {
  readonly tasks: readonly TreeTask[];
  readonly limits: Limits;
  readonly now: number;
  readonly turnStart: number | null;
};

/** What the tree is drawn from.  The rows `session`, `main` and `turn` are
 * the band's, null where the place or the phase leaves one out; their
 * labels are drawn here again.  `mainPhase` and `turnPhase` are their
 * state circles, `mainInbox` the messages queued for the main thread,
 * `mainProgress` its latest progress update, drawn only while it works or
 * waits.  `cap` is the most subagent rows drawn, and `folded` the agents
 * whose children are folded under them. */
export type TreeInput = {
  readonly session: Row | null;
  readonly main: Row | null;
  readonly turn: Row | null;
  readonly workspace: Workspace | null;
  readonly mainPhase: string;
  readonly mainInbox: number;
  readonly mainProgress: string;
  readonly turnPhase: string;
  readonly agents: TreeAgents | null;
  readonly cap: number;
  readonly folded?: ReadonlySet<string>;
};

/** A row of the tree before its line is drawn: its row with the label
 * after the line, its children, and whether they are folded under it. */
type Node = {
  readonly row: Row;
  readonly kids: readonly Node[];
  readonly folded: boolean;
};

/** The progress update's piece: two blanks then the text, dimmed, under
 * the path `chat.progress`; none for no text. */
function progressPiece(text: string): Piece[] {
  const t = squash(text).trim();
  return t ? [{ path: "chat.progress",
    spans: [span("  "), span(t, null, true)], drop: 0 }] : [];
}

/** A thread's head, its kind glyph and its state circle in two columns,
 * then a blank, under `name.kind`. */
function headPiece(st: Settings, kind: string, phase: string): Piece {
  return { path: "name.kind",
    spans: [span(kind), span(padVal(st, 2, phase, true)), span(" ")],
    drop: 0 };
}

/** The tree's line before a row: for each level above it a bar, or blanks
 * under a last child, then its branch, `├` or `╰` and `─`, or ⊟ or ⊞ for a
 * row with children, opened or folded; the root's ⊟ alone.  `lasts` says,
 * for each level from the root's children down to the row's own, whether
 * that level's row is the last of its siblings. */
function treeLine(lasts: readonly boolean[], kids: boolean,
  folded: boolean): string {
  const mark = kids ? (folded ? E_FOLD_SHUT : E_FOLD_OPEN) : E_TREE_DASH;
  if (!lasts.length) return kids ? mark + " " : "";
  const bars = lasts.slice(0, -1).map((l) => l ? "   " : E_TREE_BAR + "  ");
  return bars.join("") + (lasts.at(-1) ? E_TREE_LAST : E_TREE_MID) + mark +
    " ";
}

/** The rows of `nodes`, top to bottom, each with its tree line as the
 * first piece of its label, under the path `tree`, dim. */
function walk(nodes: readonly Node[], lasts: readonly boolean[],
  out: Row[]): void {
  nodes.forEach((n, i) => drawNode(n, [...lasts, i === nodes.length - 1],
    out));
}

/** `n`'s row with its tree line, `lasts` as treeLine reads it, then its
 * children's where they are not folded under it. */
function drawNode(n: Node, lasts: readonly boolean[], out: Row[]): void {
  const line = treeLine(lasts, n.kids.length > 0 || n.folded, n.folded);
  out.push({ ...n.row, left: true, label: [
    ...(line ? [{ path: "tree", spans: [span(line, null, true)], drop: 0 }]
      : []),
    ...n.row.label] });
  if (!n.folded) walk(n.kids, lasts, out);
}

/** The tree's rows, top to bottom, under `hide`: 🎮, then 🎤, then 🧵 and
 * its subagents, `… N more` and `✅ N done`.  Without 🎮 its children
 * stand at the top; without 🧵 the subagents hang from the root. */
export function treeRows(st: Settings, inp: TreeInput,
  hide: readonly string[]): Row[] {
  const agents = inp.agents !== null && !hidden(hide, "agent")
    ? agentNodes(st, inp.agents, inp.cap, inp.folded ?? new Set()) : [];
  const top: Node[] = [];
  if (inp.turn) {
    top.push({ folded: false, kids: [], row: { ...inp.turn, label: [
      headPiece(st, E_TURN, inp.turnPhase),
      { path: "name.label", spans: [span("turn", "F_BLU")], drop: 0 }] } });
  }
  if (inp.main) {
    top.push({ folded: false, kids: agents, row: { ...inp.main, label: [
      headPiece(st, E_THREAD, inp.mainPhase),
      ...(inp.mainInbox ? [{ path: "state.inbox",
        spans: [...renderInbox(inp.mainInbox), span(" ")], drop: 0 }] : []),
      { path: "name.label", spans: [span("main", "F_BLU")], drop: 0 },
      ...(inp.mainPhase === E_PHASE_END ? []
        : progressPiece(inp.mainProgress))] } });
  } else top.push(...agents);
  const out: Row[] = [];
  if (inp.session) {
    const ws = workspacePieces(inp.workspace).filter((p) =>
      ["workspace.project", "workspace.branch", "workspace.pr"]
        .includes(p.path));
    drawNode({ folded: false, kids: top, row: { ...inp.session, label: [
      { path: "name.label", spans: [span(E_SESSION + " ")], drop: 0 },
      ...ws] } }, [], out);
  } else {
    for (const n of top) drawNode(n, [], out);
  }
  return out;
}

/** Whether a task has ended: failed, killed, or completed and waiting on
 * nothing (parked says what a completed agent can still wait on). */
function ended(t: Dict, u: Dict, busy: ReadonlySet<string>): boolean {
  const s = String(t.status ?? "");
  if (s === "failed" || s === "killed") return true;
  return s === "completed" && !parked(s, u.eta, busy.has(String(t.id)),
    u.background);
}

/** The subagents as the tree's nodes under 🧵 main: each live agent under
 * the agent that started it (treeShape, which steps over a finished
 * ancestor), in the order they started; an ended agent only where a live
 * one hangs under it.  At most `cap` agent rows, in the tree's order: the
 * siblings past it are summed on their parent's `… N more`.  Then `✅ N
 * done`, the agents that ended since the turn opened. */
function agentNodes(st: Settings, a: TreeAgents, cap: number,
  folded: ReadonlySet<string>): Node[] {
  const prepared = preparedOf(a.tasks);
  const shape = treeShape(prepared);
  const busy = runningParents(prepared);
  const etas = inheritedEtas(prepared);
  const byId = new Map(a.tasks.map((t) => [String(t.task.id), t]));
  const kidsOf = new Map<string, string[]>();
  for (const [id, [parent]] of shape) {
    if (!kidsOf.has(parent)) kidsOf.set(parent, []);
    kidsOf.get(parent)!.push(id);
  }
  const start = (id: string): number =>
    Number(byId.get(id)!.task.startTime ?? Infinity);
  for (const ids of kidsOf.values()) {
    ids.sort((x, y) => start(x) - start(y) || (x < y ? -1 : x > y ? 1 : 0));
  }
  const isEnded = (id: string): boolean => {
    const t = byId.get(id)!;
    return ended(t.task, t.usage, busy);
  };
  const liveMemo = new Map<string, boolean>();
  const live = (id: string): boolean => {
    if (!liveMemo.has(id)) {
      liveMemo.set(id, false);
      liveMemo.set(id, !isEnded(id) ||
        (kidsOf.get(id) ?? []).some((k) => live(k)));
    }
    return liveMemo.get(id)!;
  };
  const shownKids = (id: string): string[] =>
    (kidsOf.get(id) ?? []).filter(live);
  const under = (id: string): string[] =>
    shownKids(id).flatMap((k) => [k, ...under(k)]);
  // 👶🏻 on a folded row: every agent hidden under it.
  const hiddenUnder = new Map<string, number>();
  for (const id of folded) {
    if (byId.has(id) && live(id)) hiddenUnder.set(id, under(id).length);
  }
  const agentRow = (id: string): Row => {
    const t = byId.get(id)!;
    const waitingOn = busy.has(id);
    const eta: Eta | false = etas.has(id) ? etas.get(id)! : false;
    const [phase] = agentState(String(t.task.status ?? ""), t.usage,
      waitingOn);
    const working = phase === E_PHASE_RUN || phase === E_PHASE_PAUSE;
    return { scope: "agent",
      label: [...agentLabel(st, t.task, t.usage, t.meta, waitingOn,
        hiddenUnder.get(id) ?? 0, 0, null, true),
      ...(working ? progressPiece(t.progress) : [])],
      cells: agentCells(st, t.task, t.usage, t.meta, t.shares, a.limits,
        a.now, eta, waitingOn) };
  };
  let budget = cap;
  const place = (parent: string): Node[] => {
    const ids = shownKids(parent);
    const out: Node[] = [];
    for (let i = 0; i < ids.length; i++) {
      if (budget <= 0) {
        const rest = ids.slice(i).flatMap((k) => [k, ...under(k)]);
        out.push(groupNode(st, a, rest.map((k) => byId.get(k)!),
          E_MORE + " " + rest.length + " more", "more"));
        break;
      }
      budget -= 1;
      const id = ids[i];
      const shut = folded.has(id) && shownKids(id).length > 0;
      out.push({ row: agentRow(id), folded: shut,
        kids: shut ? [] : place(id) });
    }
    return out;
  };
  const nodes = place("");
  if (a.turnStart !== null) {
    const done = [...byId.keys()].filter((id) => !live(id) && (() => {
      const u = byId.get(id)!.usage;
      const end = (u.last_seen ?? u.last_epoch) as number | null;
      return end !== null && end >= a.turnStart!;
    })());
    if (done.length) {
      nodes.push(groupNode(st, a, done.map((k) => byId.get(k)!),
        E_MODE_DONE + " " + done.length + " done", "done"));
    }
  }
  return nodes;
}

/** A folded row that sums `tasks`: `… N more` past the cap, or `✅ N
 * done`.  Its 🛫 column says 🏃 and how many of them run, or ✅ and how
 * long since the last of them ended; 💰 🧩 💾 and the plan's shares are
 * their sums, 🎯 their cache rates weighed by their ▴, ⌛ their ages
 * summed and 🤖 🔧 🚦 their split of it, as proportions of themselves, as
 * 🎮's agent-seconds are.  No model, 🧠 or ⛳: they are each agent's
 * own. */
function groupNode(st: Settings, a: TreeAgents, tasks: readonly TreeTask[],
  name: string, kind: "more" | "done"): Node {
  const num = (v: unknown): number => typeof v === "number" ? v : 0;
  const billed = tasks.filter((t) => (t.usage.parts as unknown[]).length);
  const sum = (f: (t: TreeTask) => number, of = tasks): number =>
    of.reduce((n, t) => n + f(t), 0);
  const cells: { [key: string]: Span[] } = {};
  if (kind === "more") {
    cells.rate = renderAgentRate(st, tasks.filter((t) =>
      t.task.status === "running").length, E_EFF_HIGH);
  } else {
    const ends = tasks.map((t) => num(t.usage.last_seen ?? t.usage.last_epoch))
      .filter((e) => e);
    if (ends.length) {
      const secs = Math.max(0, a.now - Math.max(...ends));
      cells.rate = [span(E_MODE_DONE + " "),
        span(padVal(st, 4, durFmt(st, secs)), "F_PRW")];
    }
  }
  if (billed.length) {
    cells.cost = renderCost(st, pyFormatF(sum((t) => num(t.usage.cost),
      billed), 4));
    const up = sum((t) => num(t.usage.tok_up), billed);
    cells.tok = renderTokens(st, up, sum((t) => num(t.usage.tok_down),
      billed));
    const weighed = billed.filter((t) => num(t.usage.cache_pct) >= 0);
    const w = sum((t) => num(t.usage.tok_up), weighed);
    if (w > 0) {
      cells.cache = renderAgentCache(st, Math.trunc(sum((t) =>
        num(t.usage.cache_pct) * num(t.usage.tok_up), weighed) / w));
    }
    const diff = renderAgentDiff(st, {
      lines_added: sum((t) => num(t.usage.lines_added), billed),
      lines_removed: sum((t) => num(t.usage.lines_removed), billed) });
    if (diff.length) cells.diff = diff;
    const share = (k: "sess" | "week"): number | null =>
      billed.some((t) => t.shares[k] === null) ? null
        : sum((t) => t.shares[k] ?? 0, billed);
    cells.five = renderAgentLimit(st, E_SESS, a.limits.session_pct,
      share("sess"), "F_LIM_SESS");
    cells.week = renderAgentLimit(st, E_WEEK, a.limits.weekly_pct,
      share("week"), "F_LIM_WEEK", true, false, 4);
  }
  const ages = tasks.map((t) => {
    const u = t.usage;
    const work = u.work as [number, number][];
    const firsts = [...work.slice(0, 1).map((w) => w[0]),
      ...(u.open_at !== null ? [u.open_at as number] : [])];
    const live = t.task.status === "running";
    const end = live ? null : (u.last_epoch ?? (work.length
      ? Math.max(...work.map((w) => w[1])) : null)) as number | null;
    return agentElapsed(t.task.startTime, a.now, end,
      firsts.length ? Math.min(...firsts) : null);
  }).filter((x): x is number => x !== null);
  if (ages.length) {
    const age = ages.reduce((n, x) => n + x, 0);
    cells.clock = [span(E_IDLE), span(padVal(st, 4, durFmt(st, age)),
      "F_PRW", magDim(age, MAG_DUR_S))];
    const timed = tasks.filter((t) => t.usage.model_s !== null);
    if (timed.length) {
      cells.split = renderAgentSplit(age, sum((t) => num(t.usage.model_s),
        timed), sum((t) => num(t.usage.tool_s), timed));
    }
  }
  for (const k of Object.keys(cells)) if (!cells[k].length) delete cells[k];
  return { folded: true, kids: [], row: { scope: "agent", cells,
    label: [{ path: "name.label", spans: spans(span(name, "F_BLU")),
      drop: 0 }] } };
}
