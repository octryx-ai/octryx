// The workflow designer's state hooks: the undoable draft and its name, the catalog, the selection, the chart's
// layout and the problems, and the changes made through the toolbar, the box menu and the keyboard.
import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { ReadJsonFn } from "../../../../hooks/useAdminTabLoader.types";
import { BOX_HEIGHT, BOX_WIDTH, LAYER_GAP, type Point } from "../phasedGraphTypes";
import { buildPhasedGraph } from "../phasedGraphBuild";
import { defaultDirection, layoutPhasedGraph } from "../phasedGraphLayout";
import { foldGraph } from "../phasedGroups";
import { designerCatalogPath, type PhasedView } from "../phasedWorkflowModel";
import { chartGroups, EMPTY_CATALOG, message } from "./designerEditorHelpers";
import { liveIssues, mergedIssues } from "./issues";
import { addNode, connect } from "./modelEditing";
import { chartView, fromDefinition, savedDirection } from "./modelDefinition";
import { commit, startHistory, type History } from "./modelHistory";
import { freeRoutes, routeChoices, type DesignGroup, type DesignModel } from "./modelCore";
import { type Clipboard } from "./modelClipboard";
import type { DesignerCatalog, NodeKind } from "./types";

type Shown = { positions: Map<string, Point>; folded: boolean };

// The draft as an undoable history, its name, and whether either differs from the stored version.
export function useDesignerDraft(view: PhasedView, onDirtyChange?: (dirty: boolean) => void) {
  const saved = useMemo(() => fromDefinition(view.definition ?? {}), [view]);
  const [history, setHistory] = useState<History>(() => startHistory(saved));
  useEffect(() => setHistory(startHistory(saved)), [saved]);
  const model = history.present;
  const [title, setTitle] = useState(view.title);
  useEffect(() => setTitle(view.title), [view]);
  const named = title.trim();
  const dirty = model !== saved || (named !== "" && named !== view.title);
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  return { history, setHistory, model, title, setTitle, named, dirty };
}

// The agents, tools and checks the boxes can use, and the editor's messages and busy flag.
export function useDesignerCatalog(readJson: ReadJsonFn, view: PhasedView) {
  const [catalog, setCatalog] = useState<DesignerCatalog>(EMPTY_CATALOG);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    readJson<DesignerCatalog>(designerCatalogPath(view.project_id))
      .then((loaded) => { if (live) setCatalog(loaded); })
      .catch((error) => { if (live) setProblem(message(error, "The lists of agents, tools and checks could not be loaded.")); });
    return () => { live = false; };
  }, [readJson, view.project_id]);
  return { catalog, problem, setProblem, notice, setNotice, busy, setBusy };
}

// What is selected, folded, copied and open, and the one way every change goes into the history.
export function useDesignerSelection(setHistory: Dispatch<SetStateAction<History>>) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const [edgeId, setEdgeId] = useState<string | null>(null);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ id: string; connect: boolean } | null>(null);
  const [folded, setFolded] = useState<ReadonlySet<string>>(() => new Set());
  const [clip, setClip] = useState<Clipboard | null>(null);
  const [focus, setFocus] = useState<{ id: string; nonce: number } | null>(null);
  const [legendOpen, setLegendOpen] = useState(false);
  const [issuesOpen, setIssuesOpen] = useState(false);

  // Where every box is drawn now; a change of the structure pins the boxes the automatic layout placed, so nothing
  // jumps when an arrow or a box is added (not while groups are folded: their boxes share one spot then).
  const shownRef = useRef<Shown>({ positions: new Map(), folded: false });
  const change = useCallback((update: (current: DesignModel) => DesignModel, key?: string) => {
    setHistory((current) => {
      let next = update(current.present);
      const shown = shownRef.current;
      if (!shown.folded && (next.nodes !== current.present.nodes || next.edges !== current.present.edges)) {
        const missing = [...shown.positions].filter(([id]) => !(id in next.positions) && next.nodes.some((node) => node.id === id));
        if (missing.length) next = { ...next, positions: { ...Object.fromEntries(missing.map(([id, point]) => [id, { x: Math.round(point.x), y: Math.round(point.y) }])), ...next.positions } };
      }
      return commit(current, next, key);
    });
  }, [setHistory]);
  const selectOnly = useCallback((ids: string[]) => {
    setSelected(new Set(ids));
    setEdgeId(null);
    setGroupId(null);
    setMenu(null);
  }, []);
  return {
    selected, setSelected, edgeId, setEdgeId, groupId, setGroupId, menu, setMenu, folded, setFolded, clip, setClip, focus,
    setFocus, legendOpen, setLegendOpen, issuesOpen, setIssuesOpen, shownRef, change, selectOnly,
  };
}

// The chart drawn from the model: its graph, the groups a person made, the direction and every box's position.
export function useDesignerChart(model: DesignModel, folded: ReadonlySet<string>, shownRef: MutableRefObject<Shown>) {
  const chart = useMemo(() => chartView(model), [model]);
  const baseGraph = useMemo(() => buildPhasedGraph(chart, { editing: true }), [chart]);
  // While drawing, only the groups a person made are drawn (the automatic ones would reframe with every arrow).
  const graph = useMemo(() => ({
    ...baseGraph, groups: chartGroups(model.groups ?? [], new Set(model.nodes.map((node) => node.id))),
  }), [baseGraph, model]);
  const currentGroups = useMemo<DesignGroup[]>(() => graph.groups.map((group) => ({ id: group.id, label: group.title, members: [...group.members] })), [graph]);
  const depth = useMemo(() => layoutPhasedGraph(graph).layers, [graph]);
  const direction = defaultDirection(savedDirection(model), depth);
  const layout = useMemo(() => layoutPhasedGraph(foldGraph(graph, folded), direction), [graph, folded, direction]);
  const positions = useMemo(() => {
    const merged = new Map(layout.positions);
    for (const group of graph.groups) {
      const at = folded.has(group.id) ? layout.positions.get(group.id) : undefined;
      if (at) group.members.forEach((id) => merged.set(id, at));
    }
    for (const [id, point] of Object.entries(model.positions)) merged.set(id, point);
    return merged;
  }, [layout, graph, folded, model.positions]);
  shownRef.current = { positions, folded: folded.size > 0 };
  return { graph, currentGroups, direction, layout, positions };
}

// The problems: those the designer sees live, merged with the server's report.
export function useDesignerIssues(model: DesignModel, catalog: DesignerCatalog, view: PhasedView) {
  const live = useMemo(() => liveIssues(model, catalog), [model, catalog]);
  return useMemo(() => mergedIssues(live, view.validation_report.errors, model), [live, view, model]);
}

type ChangeArgs = {
  model: DesignModel;
  catalog: DesignerCatalog;
  chart: ReturnType<typeof useDesignerChart>;
  selection: ReturnType<typeof useDesignerSelection>;
  setProblem: (problem: string | null) => void;
};

// Adding a box at a free spot (or where it was dropped) and connecting two boxes.
export function useDesignerAddConnect({ model, catalog, chart, selection, setProblem }: ChangeArgs) {
  const { positions, direction, layout } = chart;
  const { change, selectOnly, setFocus, setSelected, setEdgeId, setMenu } = selection;
  const freeSpot = useCallback((): Point => {
    const points = [...positions.entries()];
    if (!points.length) return { x: 0, y: 0 };
    if (direction === "lr") {
      const right = Math.max(...points.map(([, point]) => point.x + BOX_WIDTH));
      return { x: right + 72, y: Math.min(...points.map(([, point]) => point.y)) };
    }
    const bottom = Math.max(...points.map(([id, point]) => point.y + (layout.heights.get(id) ?? BOX_HEIGHT)));
    return { x: Math.min(...points.map(([, point]) => point.x)), y: bottom + LAYER_GAP };
  }, [positions, direction, layout]);
  const addBox = useCallback((kind: NodeKind, at?: Point) => {
    const result = addNode(model, kind, at ?? freeSpot(), { positions, direction });
    change(() => result.model);
    selectOnly([result.id]);
    if (!at) setFocus({ id: result.id, nonce: Date.now() });
  }, [model, change, freeSpot, selectOnly, positions, direction, setFocus]);
  const connectBoxes = useCallback((source: string, target: string) => {
    const choices = routeChoices(model, source, catalog);
    const when = choices === null ? null : freeRoutes(model, source, catalog)?.[0] ?? null;
    const result = connect(model, source, target, when, catalog);
    if (result.problem || !result.edgeId) {
      setProblem(result.problem ?? "These boxes cannot be connected.");
      return;
    }
    setProblem(null);
    change(() => result.model);
    // Several results: the arrow's panel opens, so the person sees for which result it is taken.
    if (choices !== null) {
      setSelected(new Set());
      setEdgeId(result.edgeId);
    }
    setMenu(null);
  }, [model, catalog, change, setProblem, setSelected, setEdgeId, setMenu]);
  return { addBox, connectBoxes };
}
