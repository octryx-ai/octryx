// A phase's group on the flow chart. Pure: the frame around the group's boxes where they
// stand now, the one box a folded group shows, and the arrows with folded groups standing in for their boxes.
// Folding is a view only: it never moves a box, so a hand-made layout stays as it is.
import { BOX_HEIGHT, BOX_WIDTH, GROUP_HEAD, GROUP_PAD, type BoxBadge, type GraphArrow, type GraphBox, type GraphGroup, type PhasedGraph, type Point } from "./phasedGraphTypes";

export type Frame = { x: number; y: number; width: number; height: number };

// A group's frame around its boxes where they stand now (moved boxes included): the header above, a margin around.
export function groupFrame(members: string[], positions: Map<string, Point>, heights: Map<string, number>): Frame | null {
  const placed = members.filter((id) => positions.has(id));
  if (!placed.length) return null;
  const left = Math.min(...placed.map((id) => positions.get(id)!.x));
  const top = Math.min(...placed.map((id) => positions.get(id)!.y));
  const right = Math.max(...placed.map((id) => positions.get(id)!.x + BOX_WIDTH));
  const bottom = Math.max(...placed.map((id) => positions.get(id)!.y + (heights.get(id) ?? BOX_HEIGHT)));
  return { x: left - GROUP_PAD, y: top - GROUP_HEAD, width: right - left + 2 * GROUP_PAD, height: bottom - top + GROUP_HEAD + GROUP_PAD };
}

// A folded group as one box: the phase's title, how many boxes it holds, the others' titles and every badge of its
// boxes that leads out of it (a loop inside it reads "↻ repeats").
export function foldedBox(group: GraphGroup, graph: PhasedGraph): GraphBox {
  const members = group.members.map((id) => graph.boxes.find((box) => box.id === id)!);
  const badges: BoxBadge[] = [];
  for (const badge of members.flatMap((box) => box.badges)) {
    const inside = group.members.includes(badge.target);
    const label = inside ? badge.label.replace(/^↻ back to .*?( \(max \d+\))?$/, "↻ repeats$1") : badge.label;
    if (!badges.some((item) => item.label === label)) badges.push({ ...badge, label });
  }
  // A loop drawn inside the group disappears with the fold: the folded box says it repeats instead.
  for (const arrow of graph.arrows) {
    if (!arrow.loop || arrow.badge || !group.members.includes(arrow.source) || !group.members.includes(arrow.target)) continue;
    const label = `↻ repeats${arrow.maxIterations ? ` (max ${arrow.maxIterations})` : ""}`;
    if (badges.some((item) => item.label === label)) continue;
    badges.unshift({ tone: "loop", label, target: arrow.target, title: arrow.title || label, edgeIds: [...arrow.edgeIds],
      when: arrow.when });
  }
  const count = group.kind === "steps" ? `${members.length} steps` : `${members.length} boxes`;
  return {
    id: group.id,
    kind: "group",
    family: group.family,
    kindLabel: "Group",
    kindLine: `Group · ${count}`,
    title: group.title,
    // A phase's group names the phase; a run of steps or a hand-made group lists all its boxes.
    subtitle: (group.kind === "phase" || !group.kind ? members.slice(1) : members).map((box) => box.title).join(" · "),
    errorPath: false,
    goodEnd: false,
    offPath: false,
    aside: false,
    badges,
  };
}

/**
 * The graph with each folded group as one box (standing where its first box stands in the order) and its arrows
 * ending there: what the automatic layout lays out, so a folded group leaves no hole.
 */
export function foldGraph(graph: PhasedGraph, folded: ReadonlySet<string>): PhasedGraph {
  const closed = graph.groups.filter((group) => folded.has(group.id));
  if (!closed.length) return graph;
  const owner = new Map<string, GraphGroup>();
  for (const group of closed) group.members.forEach((id) => owner.set(id, group));
  const boxes: GraphBox[] = [];
  for (const box of graph.boxes) {
    const group = owner.get(box.id);
    if (!group) boxes.push(box);
    else if (group.members[0] === box.id) boxes.push(foldedBox(group, graph));
  }
  return {
    boxes,
    arrows: foldArrows(graph.arrows, closed, folded),
    groups: graph.groups.filter((group) => !folded.has(group.id)),
  };
}

// The drawn arrows with the folded groups standing in for their boxes: an arrow inside a folded group disappears,
// one into or out of it ends at the group's box; two that become the same are one.
export function foldArrows(arrows: GraphArrow[], groups: GraphGroup[], folded: ReadonlySet<string>): GraphArrow[] {
  const owner = new Map<string, string>();
  for (const group of groups) if (folded.has(group.id)) group.members.forEach((id) => owner.set(id, group.id));
  if (!owner.size) return arrows;
  const result: GraphArrow[] = [];
  const seen = new Map<string, GraphArrow>();
  for (const arrow of arrows) {
    const source = owner.get(arrow.source) ?? arrow.source;
    const target = owner.get(arrow.target) ?? arrow.target;
    if (source === target) continue;
    const key = `${source}->${target}`;
    const existing = seen.get(key);
    if (existing) {
      if (arrow.label && !existing.label.split(" or ").includes(arrow.label)) {
        existing.label = existing.label ? `${existing.label} or ${arrow.label}` : arrow.label;
      }
      if (existing.tone !== arrow.tone) existing.tone = "neutral";
      continue;
    }
    const next = { ...arrow, source, target, edgeIds: [...arrow.edgeIds] };
    seen.set(key, next);
    result.push(next);
  }
  return result;
}
