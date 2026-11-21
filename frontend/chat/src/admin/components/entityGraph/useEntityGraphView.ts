// Derived view state of the entity graph panel: layout, visible nodes and edges, legend and search matches.
import { useCallback, useMemo } from "react";
import { egoLayout, layoutGraph } from "./kgLayout";
import { assignTypeSlots, legendItems, withTypes } from "./kgView";
import { groupOfAdded, LOOSE_GROUP, needsStructureGroups, SMALL_GROUPS, structureGroups, type Grouping } from "./kgCommunities";
import type { Additions } from "./kgExpand";
import { matchBases, matchedIds } from "./entityGraphMatches";
import type { EntityGraphEdge, EntityGraphNode, EntityGraphPayload } from "./entityGraphTypes";
import { onlyNoise, withoutNoise } from "./entityGraphNoise";

// Up to this many entities a neighbourhood reads best as a star (two rings); more fall back to the clusters.
const MAX_STAR = 49;
export type GraphAdditions = Additions<EntityGraphNode, EntityGraphEdge>;

type LayoutInput = {
  payload: EntityGraphPayload | null;
  additions: GraphAdditions;
  showNoise: boolean;
  focusNodeId: string;
  onlyType: string;
  hiddenTypes: Set<string>;
};

export function useEntityGraphLayout({ payload, additions, showNoise, focusNodeId, onlyType, hiddenTypes }: LayoutInput) {
  // What this view loaded, without structure nodes and literal values (Advanced shows them). The layout is computed
  // once per answer from these; the legend only hides types and an Expand only adds, so nothing already drawn moves.
  const keepNode = useCallback((nodes: EntityGraphNode[]) => withoutNoise(nodes, { showNoise, keepId: focusNodeId })
    .filter((node) => !onlyType || node.node_type === onlyType), [showNoise, focusNodeId, onlyType]);
  // Nothing but documents and chapters (nothing extracted yet): show them rather than an empty "all hidden" view.
  const noiseOnly = useMemo(() => !showNoise && onlyNoise(payload?.nodes || []), [payload, showNoise]);
  const baseNodes = useMemo(() => (noiseOnly
    ? (payload?.nodes || []).filter((node) => !onlyType || node.node_type === onlyType)
    : keepNode(payload?.nodes || [])), [payload, keepNode, noiseOnly, onlyType]);
  const baseEdges = useMemo(() => {
    const ids = new Set(baseNodes.map((node) => node.id));
    return (payload?.edges || []).filter((edge) => ids.has(edge.source) && ids.has(edge.target));
  }, [payload, baseNodes]);
  // Without entity types (or with one only), colours and clusters show groups from the graph's structure.
  const grouping = useMemo(() => (needsStructureGroups(baseNodes) ? structureGroups(baseNodes, baseEdges) : null),
    [baseNodes, baseEdges]);
  const viewBase = useMemo(() => (grouping
    ? baseNodes.map((node) => ({ ...node, node_type: grouping.groupOf.get(node.id) ?? LOOSE_GROUP })) : baseNodes),
  [baseNodes, grouping]);
  // A neighbourhood (focus) is drawn as a star around its entity; everything else in type clusters.
  const baseLayout = useMemo(() => {
    const centre = focusNodeId ? viewBase.find((node) => node.id === focusNodeId) : undefined;
    if (centre && viewBase.length <= MAX_STAR) {
      return { nodes: egoLayout(centre, viewBase.filter((node) => node.id !== centre.id)), clusters: [] };
    }
    return layoutGraph(viewBase, baseEdges, grouping ? { ring: LOOSE_GROUP, airy: true } : {});
  }, [viewBase, baseEdges, focusNodeId, grouping]);
  const basePositions = baseLayout.nodes;
  // Each type cluster carries its name on the canvas, so types beyond the eight colours stay readable.
  const clusterLabels = useMemo(() => baseLayout.clusters.filter((cluster) => !hiddenTypes.has(cluster.type)),
    [baseLayout, hiddenTypes]);
  // A new layout or a legend filter fits the canvas again; an Expand keeps the viewport.
  const viewKey = useMemo(() => `${baseNodes.map((node) => node.id).join("|")}#${Array.from(hiddenTypes).sort().join("|")}`,
    [baseNodes, hiddenTypes]);
  const loadedNodes = useMemo(() => {
    if (!additions.nodes.length) return viewBase;
    const added = keepNode(additions.nodes);
    const edges = (payload?.edges || []).concat(additions.edges);
    return viewBase.concat(grouping
      ? added.map((node) => ({ ...node, node_type: groupOfAdded(node.id, edges, grouping.groupOf) })) : added);
  }, [viewBase, additions, keepNode, grouping, payload]);
  const loadedIds = useMemo(() => new Set(loadedNodes.map((node) => node.id)), [loadedNodes]);
  const loadedEdges = useMemo(
    () => (payload?.edges || []).concat(additions.edges).filter((edge) => loadedIds.has(edge.source) && loadedIds.has(edge.target)),
    [payload, additions, loadedIds],
  );
  const positions = useMemo(() => {
    if (!additions.positions.size) return basePositions;
    const merged = new Map(basePositions);
    additions.positions.forEach((at, id) => { if (!merged.has(id)) merged.set(id, at); });
    return merged;
  }, [basePositions, additions]);
  return { noiseOnly, baseNodes, grouping, positions, clusterLabels, viewKey, loadedNodes, loadedEdges };
}

type VisibilityInput = {
  payload: EntityGraphPayload | null;
  additions: GraphAdditions;
  grouping: Grouping | null;
  loadedNodes: EntityGraphNode[];
  loadedEdges: EntityGraphEdge[];
  hiddenTypes: Set<string>;
  hiddenKinds: Set<string>;
  selectedId: string;
};

export function useEntityGraphVisibility({ payload, additions, grouping, loadedNodes, loadedEdges, hiddenTypes, hiddenKinds,
  selectedId }: VisibilityInput) {
  const slots = useMemo(() => {
    if (grouping) {
      // Named groups get the colours; "Loosely connected" and "Smaller groups" stay neutral.
      const sizes: Record<string, number> = {};
      for (const group of grouping.groups) if (group.label !== LOOSE_GROUP && group.label !== SMALL_GROUPS) sizes[group.label] = group.size;
      const map = assignTypeSlots(sizes);
      map.set(LOOSE_GROUP, 0);
      map.set(SMALL_GROUPS, 0);
      return map;
    }
    return withTypes(assignTypeSlots(payload?.stats?.node_types), additions.nodes.map((node) => node.node_type));
  }, [payload, additions, grouping]);
  const visibleNodes = useMemo(() => loadedNodes.filter((node) => !hiddenTypes.has(node.node_type)), [loadedNodes, hiddenTypes]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => loadedEdges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target) && !hiddenKinds.has(edge.edge_type)),
    [loadedEdges, visibleIds, hiddenKinds],
  );
  const kinds = useMemo(() => {
    const counts = new Map<string, number>();
    for (const edge of loadedEdges) counts.set(edge.edge_type, (counts.get(edge.edge_type) ?? 0) + 1);
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [loadedEdges]);
  const neighborIds = useMemo(() => {
    if (!selectedId) return new Set<string>();
    const ids = new Set<string>();
    for (const edge of visibleEdges) {
      if (edge.source === selectedId) ids.add(edge.target);
      if (edge.target === selectedId) ids.add(edge.source);
    }
    return ids;
  }, [selectedId, visibleEdges]);
  return { slots, visibleNodes, visibleIds, visibleEdges, kinds, neighborIds };
}

type LegendInput = {
  payload: EntityGraphPayload | null;
  grouping: Grouping | null;
  loadedNodes: EntityGraphNode[];
  visibleNodes: EntityGraphNode[];
  visibleIds: Set<string>;
  hiddenTypes: Set<string>;
  slots: Map<string, number>;
  activeQuery: string;
};

export function useEntityGraphLegend({ payload, grouping, loadedNodes, visibleNodes, visibleIds, hiddenTypes, slots,
  activeQuery }: LegendInput) {
  // Groups: the catch-all groups go last in the legend, whatever their size.
  // The loosely connected ring: fitted around, not into; its lines drawn faint.
  const ringIds = useMemo(() => new Set(loadedNodes.filter((node) => grouping && node.node_type === LOOSE_GROUP).map((node) => node.id)),
    [loadedNodes, grouping]);
  const fitIds = useMemo(() => (ringIds.size ? visibleNodes.filter((node) => !ringIds.has(node.id)).map((node) => node.id) : undefined),
    [ringIds, visibleNodes]);
  const legend = useMemo(() => {
    const items = legendItems(loadedNodes, hiddenTypes, slots);
    const last = (type: string) => Number(type === SMALL_GROUPS) + 2 * Number(type === LOOSE_GROUP);
    return grouping ? items.sort((a, b) => last(a.type) - last(b.type)) : items;
  }, [loadedNodes, hiddenTypes, slots, grouping]);
  const matches = useMemo(() => matchedIds(payload), [payload]);
  const bases = useMemo(() => {
    const all = matchBases(payload, activeQuery);
    return new Map(Array.from(all).filter(([id]) => visibleIds.has(id)));
  }, [payload, activeQuery, visibleIds]);
  return { ringIds, fitIds, legend, matches, bases };
}
