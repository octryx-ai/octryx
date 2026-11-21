// Phased workflow graph: boxes, arrows, badges and groups built from the editor payload.
import type { PhasedEdge, PhasedView } from "./phasedWorkflowModel";
import type { BoxBadge, GraphArrow, GraphBox, GraphGroup, PhasedGraph } from "./phasedGraphTypes";
import {
  boxSubtitle,
  edgeLabel,
  edgeTone,
  FAMILY_LABELS,
  GOOD_OUTCOMES,
  HUMAN_KINDS,
  isErrorEnd,
  KIND_LABELS,
  nodeFamily,
  repeats,
  shortTitle,
  SUCCESS_WHENS,
  whenWords,
} from "./phasedGraphWords";

// What an exit into the error path is said as: "on failure", "on stopped", "on declined"; "then" for an exit that
// is taken whatever the result.
function exitCondition(whens: Array<string | null>): string {
  const said = [...new Set(whens.filter((when): when is string => Boolean(when)))];
  if (!said.length || said.some((when) => SUCCESS_WHENS.has(when))) return "then";
  return `on ${said.map((when) => (when === "failed" ? "failure" : whenWords(when))).join(" or ")}`;
}

function badgeOf(arrow: GraphArrow, edges: PhasedEdge[], target: GraphBox): BoxBadge {
  const whens = edges.filter((edge) => arrow.edgeIds.includes(edge.id)).map((edge) => edge.when);
  const short = shortTitle(target);
  const edgeIds = [...arrow.edgeIds];
  const when = whens[0] ?? null;
  if (arrow.loop) {
    const limit = arrow.maxIterations ? ` (max ${arrow.maxIterations})` : "";
    const route = whens.filter(Boolean).map((when) => whenWords(when)).join(" or ") || "again";
    const times = arrow.maxIterations ? `, at most ${arrow.maxIterations} ${arrow.maxIterations === 1 ? "time" : "times"}` : "";
    return {
      tone: "loop", label: `↻ back to ${short}${limit}`, target: arrow.target, edgeIds, when,
      title: `${arrow.title ? `${arrow.title}: ` : ""}${route} → back to ${target.title}${times}`,
    };
  }
  const condition = exitCondition(whens);
  return { tone: "failure", label: `${condition} → ${short}`, target: arrow.target, edgeIds, when, title: `${condition} → ${target.title}` };
}

// The boxes a phase owns: the checks, confirmations and questions that follow it one after the other, each reached
// only from the box before it. A group has the phase and at least one more box.
const GROUP_SEEDS = new Set(["phase", "review"]);
const GROUP_MEMBERS = new Set(["gate", "user_confirmation", "user_conversation", "approval"]);

export function phaseGroups(boxes: GraphBox[], arrows: GraphArrow[]): GraphGroup[] {
  const drawn = new Set(boxes.filter((box) => !box.offPath).map((box) => box.id));
  // The way forward only: a loop back (now drawn as its own arrow) never splits or joins a group.
  const ways = arrows.filter((arrow) => !arrow.badge && !arrow.loop && !arrow.aside && arrow.source !== arrow.target
    && drawn.has(arrow.source) && drawn.has(arrow.target));
  const next = (id: string) => [...new Set(ways.filter((arrow) => arrow.source === id).map((arrow) => arrow.target))];
  const before = (id: string) => [...new Set(ways.filter((arrow) => arrow.target === id).map((arrow) => arrow.source))];
  const byId = new Map(boxes.map((box) => [box.id, box]));
  const grouped = new Set<string>();
  const groups: GraphGroup[] = [];
  for (const box of boxes) {
    if (!drawn.has(box.id) || !GROUP_SEEDS.has(box.kind) || grouped.has(box.id)) continue;
    const members = [box.id];
    for (let tail = box.id; ;) {
      const [follower, ...more] = next(tail);
      const candidate = follower ? byId.get(follower) : undefined;
      if (!candidate || more.length || !GROUP_MEMBERS.has(candidate.kind) || grouped.has(candidate.id)
        || members.includes(candidate.id) || before(candidate.id).some((id) => id !== tail)) break;
      members.push(candidate.id);
      tail = candidate.id;
    }
    if (members.length < 2) continue;
    members.forEach((id) => grouped.add(id));
    groups.push({ id: `group:${box.id}`, title: box.title, family: box.family, members, kind: "phase" });
  }
  const order = new Map(boxes.map((box, index) => [box.id, index]));
  return [...groups, ...stepGroups(boxes, ways, grouped)].sort((a, b) => order.get(a.members[0])! - order.get(b.members[0])!);
}

// A run of platform steps (actions and waits) one after the other, each with a single way on: one group, named by
// where it stands ("Preparation" before the first agent phase, "Wrap-up" after the last). An action with its own
// branching stays a box of its own.
const STEP_KINDS = new Set(["platform_action", "watch"]);

function stepGroups(boxes: GraphBox[], ways: GraphArrow[], grouped: Set<string>): GraphGroup[] {
  const next = (id: string) => [...new Set(ways.filter((arrow) => arrow.source === id).map((arrow) => arrow.target))];
  const before = (id: string) => [...new Set(ways.filter((arrow) => arrow.target === id).map((arrow) => arrow.source))];
  const byId = new Map(boxes.map((box) => [box.id, box]));
  const reach = (id: string, step: (id: string) => string[]) => {
    const seen = new Set<string>();
    const stack = [id];
    while (stack.length) for (const other of step(stack.pop()!)) if (!seen.has(other)) { seen.add(other); stack.push(other); }
    return seen;
  };
  const agentIn = (ids: Set<string>) => [...ids].some((id) => GROUP_SEEDS.has(byId.get(id)?.kind ?? ""));
  const single = (box: GraphBox | undefined) => Boolean(box && STEP_KINDS.has(box.kind) && !box.offPath && !box.aside
    && !grouped.has(box.id) && next(box.id).length <= 1);
  const groups: GraphGroup[] = [];
  for (const box of boxes) {
    const into = before(box.id);
    // Not the head of its run: the box before it would take it in.
    if (!single(box) || (into.length === 1 && single(byId.get(into[0])) && next(into[0]).length === 1)) continue;
    const members = [box.id];
    for (let tail = box.id; ;) {
      const [follower] = next(tail);
      const candidate = follower ? byId.get(follower) : undefined;
      if (!single(candidate) || members.includes(candidate!.id) || before(candidate!.id).some((id) => id !== tail)) break;
      members.push(candidate!.id);
      tail = candidate!.id;
    }
    if (members.length < 2) continue;
    members.forEach((id) => grouped.add(id));
    const title = !agentIn(reach(box.id, before)) ? "Preparation" : !agentIn(reach(members.at(-1)!, next)) ? "Wrap-up" : "Platform steps";
    groups.push({ id: `steps:${box.id}`, title, family: "action", members, kind: "steps" });
  }
  return groups;
}

export type BuildOptions = {
  // A person edits the workflow: every box and every arrow is drawn (each edge its own arrow).
  editing?: boolean;
};

type PhasedNode = PhasedView["nodes"][number];

function graphBoxes(nodes: PhasedNode[], errorEnds: Set<string>): GraphBox[] {
  return nodes.map((node) => {
    const family = nodeFamily(node.kind);
    const kindLabel = KIND_LABELS[node.kind] ?? FAMILY_LABELS[family];
    const title = node.title || node.id;
    const subtitle = boxSubtitle(node);
    return {
      id: node.id,
      kind: node.kind,
      family,
      kindLabel,
      kindLine: repeats(kindLabel, title) ? "" : kindLabel,
      title,
      subtitle: subtitle && !repeats(subtitle, title, kindLabel) ? subtitle : "",
      errorPath: node.kind === "pause" || errorEnds.has(node.id),
      goodEnd: node.kind === "outcome" && GOOD_OUTCOMES.has(node.outcome ?? "done"),
      offPath: false,
      aside: false,
      badges: [],
    };
  });
}

// Exits of one node to the same target and of the same kind are one arrow: "succeeded or failed".
function graphArrows(edges: PhasedEdge[], byId: Map<string, PhasedNode>, errorEnds: Set<string>, editing: boolean): GraphArrow[] {
  const arrows: GraphArrow[] = [];
  const grouped = new Map<string, GraphArrow>();
  for (const edge of edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
    const loop = edge.kind === "loop";
    const tone = edgeTone(edge, byId.get(edge.target));
    const key = editing ? edge.id : `${edge.source}->${edge.target}:${loop ? "loop" : "next"}`;
    const existing = grouped.get(key);
    if (existing) {
      existing.edgeIds.push(edge.id);
      const label = edgeLabel(edge);
      if (label && !existing.label.split(" or ").includes(label)) {
        existing.label = existing.label ? `${existing.label} or ${label}` : label;
      }
      if (existing.tone !== tone) existing.tone = loop ? "loop" : "neutral";
      continue;
    }
    const arrow: GraphArrow = {
      id: edge.id,
      edgeIds: [edge.id],
      source: edge.source,
      target: edge.target,
      label: edgeLabel(edge),
      when: edge.when,
      tone,
      loop,
      maxIterations: edge.max_iterations,
      title: edge.title,
      badge: !loop && !editing && errorEnds.has(edge.target),
      aside: false,
    };
    grouped.set(key, arrow);
    arrows.push(arrow);
  }
  return arrows;
}

// While editing every exit stays its own arrow (each one is selected and changed alone), but exits of one box to the
// same target lie on top of each other: each says all of them ("confirmed or changes asked"), not only the top one.
function joinStackedLabels(arrows: GraphArrow[]): void {
  const together = new Map<string, GraphArrow[]>();
  for (const arrow of arrows) {
    const pair = `${arrow.source}->${arrow.target}:${arrow.loop ? "loop" : "next"}`;
    together.set(pair, [...(together.get(pair) ?? []), arrow]);
  }
  for (const same of together.values()) {
    if (same.length < 2) continue;
    const label = [...new Set(same.map((arrow) => arrow.label).filter(Boolean))].join(" or ");
    for (const arrow of same) arrow.label = label;
  }
}

// The error path: the pause, the ends reached only through failures, and a box every way into which comes from
// there. Its ends and its automatic steps are not drawn (badges lead to them); a box where a person decides is.
function placeErrorPath(boxes: GraphBox[], arrows: GraphArrow[], edges: PhasedEdge[], errorEnds: Set<string>, editing: boolean): void {
  const boxById = new Map(boxes.map((box) => [box.id, box]));
  const side = new Set(boxes.filter((box) => box.errorPath).map((box) => box.id));
  for (let changed = true; changed;) {
    changed = false;
    for (const box of boxes) {
      if (side.has(box.id)) continue;
      const into = arrows.filter((arrow) => !arrow.loop && arrow.target === box.id && arrow.source !== box.id);
      if (into.length && into.every((arrow) => side.has(arrow.source))) {
        side.add(box.id);
        changed = true;
      }
    }
  }
  for (const box of boxes) {
    const hidden = side.has(box.id) && (errorEnds.has(box.id) || !HUMAN_KINDS.has(box.kind));
    box.offPath = !editing && hidden;
    box.aside = side.has(box.id) && !box.offPath;
  }
  for (const arrow of arrows) {
    if (!editing && !arrow.loop && boxById.get(arrow.target)!.offPath) arrow.badge = true;
    arrow.aside = !arrow.badge && (boxById.get(arrow.source)!.aside || boxById.get(arrow.target)!.aside);
  }
  for (const arrow of arrows) {
    const source = boxById.get(arrow.source)!;
    if (arrow.badge && !source.offPath) source.badges.push(badgeOf(arrow, edges, boxById.get(arrow.target)!));
  }
  for (const box of boxes) box.badges.sort((a, b) => (a.tone === b.tone ? 0 : a.tone === "loop" ? -1 : 1));
}

export function buildPhasedGraph(view: Pick<PhasedView, "nodes" | "edges">, options: BuildOptions = {}): PhasedGraph {
  const editing = Boolean(options.editing);
  const byId = new Map(view.nodes.map((node) => [node.id, node]));
  const errorEnds = new Set(view.nodes.filter((node) => isErrorEnd(node, view.edges, byId)).map((node) => node.id));
  const boxes = graphBoxes(view.nodes, errorEnds);
  const arrows = graphArrows(view.edges, byId, errorEnds, editing);
  if (editing) joinStackedLabels(arrows);
  placeErrorPath(boxes, arrows, view.edges, errorEnds, editing);
  return { boxes, arrows, groups: phaseGroups(boxes, arrows) };
}

// The arrows the canvas draws: the way forward between drawn boxes.
export function drawnArrows(graph: PhasedGraph): GraphArrow[] {
  const off = new Set(graph.boxes.filter((box) => box.offPath).map((box) => box.id));
  return graph.arrows.filter((arrow) => !arrow.badge && !off.has(arrow.source) && !off.has(arrow.target));
}
