// The phased canvas's React Flow elements as pure functions: the group placements, the nodes (groups before their
// boxes), the arrows and the moves a drag reports. usePhasedCanvasElements calls these inside its memos and callbacks.
import type { Edge, Node } from "@xyflow/react";
import { boxHeight, BOX_WIDTH, type GraphBox, type PhasedGraph, type Point } from "./phasedGraphTypes";
import { type GraphLayout } from "./phasedGraphLayout";
import { foldArrows, groupFrame } from "./phasedGroups";
import { arrowRoutes, labelPoint, loopLabelPoint, roundedPath } from "./phasedRoutes";
import { shift, type ArrowData, type BoxData, type CanvasEditing, type CanvasNode, type Placement } from "./phasedCanvasTypes";

export function groupPlacements(graph: PhasedGraph, positions: Map<string, Point>, layout: GraphLayout): Map<string, Placement> {
  return new Map(graph.groups.flatMap((group): Array<[string, Placement]> => {
    const frame = groupFrame(group.members, positions, layout.heights);
    if (!frame) return [];
    return [[group.id, { group, frame, corner: { x: Math.min(...group.members.map((id) => positions.get(id)?.x ?? Infinity)), y: Math.min(...group.members.map((id) => positions.get(id)?.y ?? Infinity)) } }]];
  }));
}

export type NodeInput = {
  drawn: GraphBox[];
  positions: Map<string, Point>;
  placements: Map<string, Placement>;
  foldedBoxes: Map<string, GraphBox>;
  groupOf: Map<string, string>;
  folded: ReadonlySet<string>;
  heights: Map<string, number>;
  isSelected: (id: string) => boolean;
  editable: boolean;
  editing: boolean;
  edit?: CanvasEditing;
  lr: boolean;
  onOpenPhase: (id: string) => void;
  onBadge: (target: string, edgeIds: string[]) => void;
  onFold: (groupId: string, fold: boolean) => void;
};

function boxNode(input: NodeInput, box: GraphBox, position: Point, extra: Partial<Node<BoxData>> = {}): Node<BoxData> {
  const { heights, lr, editing, onOpenPhase, onBadge, edit, isSelected, editable } = input;
  return {
    id: box.id,
    type: "phasedBox",
    position,
    data: {
      ...box,
      height: heights.get(box.id) ?? boxHeight(box),
      lr,
      editing,
      onOpen: box.kind === "phase" && !editing ? () => onOpenPhase(box.id) : undefined,
      onBadge,
      onMenu: edit ? () => edit.onMenu(box.id) : undefined,
    },
    selected: isSelected(box.id),
    draggable: editable,
    connectable: editing,
    ariaLabel: `${box.kindLabel}: ${box.title}`,
    width: BOX_WIDTH,
    height: heights.get(box.id) ?? boxHeight(box),
    ...extra,
  };
}

// A group is drawn as its frame, or as one box while it is folded.
function groupNode(input: NodeInput, id: string, { group, frame, corner }: Placement): CanvasNode {
  const { foldedBoxes, heights, lr, editing, onBadge, onFold, isSelected, edit, editable } = input;
  const box = foldedBoxes.get(id);
  if (box) {
    return boxNode(input, box, corner, {
      data: { ...box, height: heights.get(id)!, lr, editing, onBadge, onUnfold: () => onFold(id, false) },
      selected: group.members.some(isSelected),
      connectable: false,
      ariaLabel: `Group: ${group.title}`,
    });
  }
  return {
    id,
    type: "phasedGroup",
    position: { x: frame.x, y: frame.y },
    data: { title: group.title, count: group.members.length, kind: group.kind, onFold: () => onFold(id, true),
      onEdit: edit ? () => edit.onEditGroup(id) : undefined },
    width: frame.width,
    height: frame.height,
    style: { width: frame.width, height: frame.height },
    draggable: editable,
    selectable: false,
    connectable: false,
    ariaLabel: `Group: ${group.title}`,
  };
}

export function canvasNodes(input: NodeInput): CanvasNode[] {
  const { drawn, positions, placements, groupOf, folded } = input;
  const result: CanvasNode[] = [];
  // Parents before their children (React Flow's rule).
  for (const [id, placement] of placements) result.push(groupNode(input, id, placement));
  for (const box of drawn) {
    const position = positions.get(box.id) ?? { x: 0, y: 0 };
    const owner = groupOf.get(box.id);
    const placement = owner ? placements.get(owner) : undefined;
    if (owner && folded.has(owner)) continue;
    result.push(placement
      ? boxNode(input, box, { x: position.x - placement.frame.x, y: position.y - placement.frame.y }, { parentId: owner })
      : boxNode(input, box, position));
  }
  return result;
}

// Arrows follow the boxes while they are dragged (a box in a group stands relative to the group's frame).
export function liveBoxPositions(nodes: CanvasNode[]): Map<string, Point> {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  return new Map(nodes.filter((node) => node.type === "phasedBox").map((node) => {
    const parent = node.parentId ? byId.get(node.parentId) : undefined;
    return [node.id, parent ? shift(node.position, parent.position) : node.position];
  }));
}

type EdgeInput = {
  arrows: ReturnType<typeof foldArrows>;
  live: Map<string, Point>;
  layout: GraphLayout;
  heights: Map<string, number>;
  editing: boolean;
  edit?: CanvasEditing;
  focusOn: Set<string>;
};

export function arrowEdges({ arrows, live, layout, heights, editing, edit, focusOn }: EdgeInput): Edge<ArrowData>[] {
  const routes = arrowRoutes(arrows, live, layout, heights);
  return arrows.flatMap((arrow) => {
    const corners = routes.get(arrow.id);
    // A thin arrow of the error path shows while one of its boxes is selected or hovered (always while editing).
    if (!corners || (arrow.aside && !editing && !focusOn.has(arrow.source) && !focusOn.has(arrow.target))) return [];
    const edgeId = arrow.edgeIds[0] ?? arrow.id;
    return [{
      id: arrow.id,
      source: arrow.source,
      target: arrow.target,
      type: "phasedArrow",
      selectable: editing,
      focusable: false,
      data: {
        d: roundedPath(corners), label: arrow.label, at: loopLabelPoint(arrow, corners) ?? labelPoint(corners), tone: arrow.tone, title: arrow.title,
        aside: arrow.aside, editing, selected: edit?.selectedEdgeId === edgeId, source: arrow.source, target: arrow.target,
        when: arrow.when,
        onSelect: edit ? () => edit.onSelectEdge(edgeId) : undefined,
      },
    }];
  });
}

// A drag ends: boxes report where they stand; a group (frame or folded box) moves all its boxes by its own move.
export function dragMoves(
  dragged: CanvasNode[],
  placements: Map<string, Placement>,
  folded: ReadonlySet<string>,
  positions: Map<string, Point>,
): Array<[string, Point]> {
  const moves: Array<[string, Point]> = [];
  for (const node of dragged) {
    const placement = placements.get(node.id);
    if (placement) {
      const from = folded.has(node.id) ? placement.corner : { x: placement.frame.x, y: placement.frame.y };
      const by = { x: node.position.x - from.x, y: node.position.y - from.y };
      placement.group.members.forEach((id) => moves.push([id, shift(positions.get(id) ?? { x: 0, y: 0 }, by)]));
    } else {
      const parent = node.parentId ? placements.get(node.parentId) : undefined;
      moves.push([node.id, parent ? shift(node.position, parent.frame) : node.position]);
    }
  }
  return moves;
}
