// The phased workflow editor's state: the loaded view, the open phase and selection, folded groups and messages; and
// its layout: the graph laid out in the chosen direction, the box positions as moved and whether they are saved.
import { useCallback, useEffect, useMemo, useState } from "react";

import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import { message } from "./phasedEditorActions";
import { buildPhasedGraph } from "./phasedGraphBuild";
import { defaultDirection, layoutPhasedGraph, mergedPositions, type LayoutDirection } from "./phasedGraphLayout";
import { type PhasedGraph, type Point } from "./phasedGraphTypes";
import { foldGraph } from "./phasedGroups";
import { phasedViewPath, type PhasedView } from "./phasedWorkflowModel";

const samePositions = (a: Map<string, Point>, b: Map<string, Point>) =>
  a.size === b.size && [...a].every(([id, point]) => {
    const other = b.get(id);
    return Boolean(other) && Math.round(other!.x) === Math.round(point.x) && Math.round(other!.y) === Math.round(point.y);
  });

export function usePhasedEditorState(flowId: string, readJson: ReadJsonFn) {
  const [view, setView] = useState<PhasedView | null>(null);
  const [openPhase, setOpenPhase] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Groups shown folded into one box (this view only; folding moves nothing and is not saved).
  const [folded, setFolded] = useState<ReadonlySet<string>>(() => new Set());
  const [legendOpen, setLegendOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setView(await readJson<PhasedView>(phasedViewPath(flowId)));
      setProblem(null);
    } catch (error) {
      setProblem(message(error, "The workflow could not be loaded."));
    }
  }, [flowId, readJson]);
  useEffect(() => {
    void load();
  }, [load]);
  return {
    view, setView, openPhase, setOpenPhase, selectedId, setSelectedId, folded, setFolded, legendOpen, setLegendOpen, busy,
    setBusy, problem, setProblem, notice, setNotice, load,
  };
}

// Folded groups are laid out as one box each, so they leave no hole; their boxes stand where the group does.
function foldedLayout(graph: PhasedGraph, folded: ReadonlySet<string>, direction: LayoutDirection) {
  const laidOut = layoutPhasedGraph(foldGraph(graph, folded), direction);
  for (const group of graph.groups) {
    const at = folded.has(group.id) ? laidOut.positions.get(group.id) : undefined;
    if (at) group.members.forEach((id) => laidOut.positions.set(id, at));
  }
  return laidOut;
}

export function usePhasedLayout(
  view: PhasedView | null, folded: ReadonlySet<string>, onDirtyChange: ((dirty: boolean) => void) | undefined,
) {
  const graph = useMemo(() => buildPhasedGraph(view ?? { nodes: [], edges: [] }), [view]);
  // Left to right or top to bottom: the saved choice, else by length; switching here is a view only.
  const [chosenDirection, setChosenDirection] = useState<LayoutDirection | null>(null);
  const depth = useMemo(() => layoutPhasedGraph(graph).layers, [graph]);
  const direction = chosenDirection ?? defaultDirection(view?.layout?.direction, depth);
  const layout = useMemo(() => foldedLayout(graph, folded, direction), [graph, folded, direction]);
  const saved = useMemo(() => mergedPositions(layout.positions, view?.layout?.positions), [layout, view]);
  const [positions, setPositions] = useState<Map<string, Point>>(saved);
  useEffect(() => setPositions(saved), [saved]);
  const unsavedLayout = !samePositions(positions, saved);
  const arranged = samePositions(positions, layout.positions);
  useEffect(() => {
    onDirtyChange?.(unsavedLayout);
  }, [unsavedLayout, onDirtyChange]);

  const onMove = useCallback((moves: Array<[string, Point]>) => {
    setPositions((current) => {
      const next = new Map(current);
      for (const [id, point] of moves) next.set(id, { x: Math.round(point.x), y: Math.round(point.y) });
      return next;
    });
  }, []);
  return { graph, setChosenDirection, direction, layout, saved, positions, setPositions, unsavedLayout, arranged, onMove };
}
