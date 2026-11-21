// The phased canvas's React Flow nodes and edges, built from the graph, the folded groups and the selection.
import { useCallback, useEffect, useMemo, useState } from "react";
import { applyNodeChanges, type Edge, type NodeChange } from "@xyflow/react";
import { boxHeight, type PhasedGraph, type Point } from "./phasedGraphTypes";
import { drawnArrows } from "./phasedGraphBuild";
import { type GraphLayout } from "./phasedGraphLayout";
import { foldArrows, foldedBox } from "./phasedGroups";
import type { ArrowData, CanvasEditing, CanvasNode } from "./phasedCanvasTypes";
import { arrowEdges, canvasNodes, dragMoves, groupPlacements, liveBoxPositions } from "./phasedCanvasElementsModel";

type PhasedCanvasElementsInput = {
  graph: PhasedGraph;
  layout: GraphLayout;
  positions: Map<string, Point>;
  folded: ReadonlySet<string>;
  onFold: (groupId: string, fold: boolean) => void;
  editable: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onMove: (moves: Array<[string, Point]>) => void;
  onOpenPhase: (id: string) => void;
  edit?: CanvasEditing;
  editing: boolean;
  lr: boolean;
  hovered: string | null;
};

export function usePhasedCanvasElements(input: PhasedCanvasElementsInput) {
  const { graph, layout, positions, folded, selectedId, onMove, edit, editing, hovered } = input;
  const { drawn, placements, heights, nodes, onNodesChange } = useCanvasNodes(input);

  const live = useMemo(() => liveBoxPositions(nodes), [nodes]);
  const arrows = useMemo(() => foldArrows(drawnArrows(graph), graph.groups, folded), [graph, folded]);
  const focusOn = useMemo(() => new Set([...(edit ? edit.selectedIds : selectedId ? [selectedId] : []), ...(hovered ? [hovered] : [])]), [edit, selectedId, hovered]);
  const edges = useMemo<Edge<ArrowData>[]>(
    () => arrowEdges({ arrows, live, layout, heights, editing, edit, focusOn }),
    [arrows, live, layout, heights, editing, edit, focusOn],
  );

  const onDragStop = useCallback((dragged: CanvasNode[]) => {
    const moves = dragMoves(dragged, placements, folded, positions);
    if (moves.length) onMove(moves);
  }, [placements, folded, positions, onMove]);

  return { drawn, placements, nodes, onNodesChange, edges, onDragStop };
}

// The boxes and group frames as React Flow nodes, kept in state so a drag moves them before the move is saved.
function useCanvasNodes({
  graph, layout, positions, folded, onFold, editable, selectedId, onSelect, onOpenPhase, edit, editing, lr,
}: PhasedCanvasElementsInput) {
  const drawn = useMemo(() => graph.boxes.filter((box) => !box.offPath), [graph]);
  const placements = useMemo(() => groupPlacements(graph, positions, layout), [graph, positions, layout]);
  const groupOf = useMemo(() => new Map(graph.groups.flatMap((group) => group.members.map((id) => [id, group.id] as const))), [graph]);
  const foldedBoxes = useMemo(() => new Map(graph.groups.filter((group) => folded.has(group.id))
    .map((group) => [group.id, foldedBox(group, graph)])), [graph, folded]);
  // Box heights including the folded groups' boxes.
  const heights = useMemo(() => {
    const all = new Map(layout.heights);
    foldedBoxes.forEach((box, id) => all.set(id, boxHeight(box)));
    return all;
  }, [layout, foldedBoxes]);
  const isSelected = useCallback((id: string) => (edit ? edit.selectedIds.has(id) : id === selectedId), [edit, selectedId]);
  const onBadge = useCallback((target: string, edgeIds: string[]) => {
    if (edit && edgeIds[0]) edit.onSelectEdge(edgeIds[0]);
    else onSelect(target);
  }, [edit, onSelect]);

  const toNodes = useCallback((): CanvasNode[] => canvasNodes({
    drawn, positions, placements, foldedBoxes, groupOf, folded, heights, isSelected, editable, editing, edit, lr, onOpenPhase, onBadge, onFold,
  }), [drawn, positions, placements, foldedBoxes, groupOf, folded, heights, isSelected, editable, editing, edit, lr, onOpenPhase, onBadge, onFold]);
  const [nodes, setNodes] = useState<CanvasNode[]>(toNodes);
  useEffect(() => setNodes(toNodes()), [toNodes]);
  // Selection is the editor's (and the read-only panel's): React Flow's own select changes are not applied.
  const onNodesChange = useCallback(
    (changes: NodeChange<CanvasNode>[]) => setNodes((current) => applyNodeChanges(changes.filter((change) => change.type !== "select"), current)),
    [],
  );
  return { drawn, placements, heights, nodes, onNodesChange };
}
