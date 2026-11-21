// The graph explorer's state hooks: the request, the view's search, focus and filters; loading the graph; the
// selected entity's details; and focusing on an entity with a trail back.
import { useCallback, useEffect, useRef, useState } from "react";
import { readJson } from "../../utils/adminPanelHelpers";
import { preloadGraphCanvas } from "./EntityGraphCanvas";
import type { EntityGraphPayload, EntityNodeDetail, GraphLayer } from "./entityGraphTypes";
import { acceptsGraphPayload, GRAPH_LAYERS, graphExplorerUrl } from "./entityGraphPresentation";
import { cutTrail, pushContext, type GraphContext } from "./entityGraphFocusTrail";
import type { GraphAdditions } from "./useEntityGraphView";

// The API's largest window; the clustered canvas reads it, so the graph opens with it.
const DEFAULT_MAX_NODES = 150;
export const NO_ADDITIONS: GraphAdditions = { nodes: [], edges: [], positions: new Map() };

export function useEntityGraphState(sharedQuery: string | undefined, selectName: string) {
  const requestEpoch = useRef(0);
  // "Show in graph" for an entity: the graph first searches its name, then centres on the exact match
  // (its neighbourhood) instead of showing the general top entities.
  // "Show in graph" also puts the name into the shared search field; a term that is that very name still centres.
  const centring = useRef(!sharedQuery || sharedQuery.trim().toLowerCase() === selectName.trim().toLowerCase()
    ? selectName.trim() : "");
  const detailEpoch = useRef(0);
  const [payload, setPayload] = useState<EntityGraphPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState(sharedQuery ?? "");
  const [activeQuery, setActiveQuery] = useState(sharedQuery || centring.current);
  const [focusNodeId, setFocusNodeId] = useState("");
  const [focusName, setFocusName] = useState("");
  const [trail, setTrail] = useState<GraphContext[]>([]);
  // The entity to reopen once a restored context has loaded (Back keeps the reader where it was).
  const reopenId = useRef("");
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set());
  const [maxNodes, setMaxNodes] = useState(DEFAULT_MAX_NODES);
  const [listOpen, setListOpen] = useState(false);
  const [showNoise, setShowNoise] = useState(false);
  const [layers, setLayers] = useState<GraphLayer[]>(GRAPH_LAYERS.map((layer) => layer.id));
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<EntityNodeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  // Additive Expand: entities and relationships added to this view, with their own positions.
  const [additions, setAdditions] = useState<GraphAdditions>(NO_ADDITIONS);
  const [freshIds, setFreshIds] = useState<Set<string>>(new Set());
  const [expandNote, setExpandNote] = useState("");
  const noteTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(noteTimer.current), []);

  // Fetch the drawing code while the graph is requested, not after it arrived (see EntityGraphCanvas).
  useEffect(() => {
    if (typeof window !== "undefined" && typeof window.ResizeObserver === "function") void preloadGraphCanvas?.();
  }, []);
  return {
    requestEpoch, centring, detailEpoch, payload, setPayload, loading, setLoading, error, setError, query, setQuery, activeQuery,
    setActiveQuery, focusNodeId, setFocusNodeId, focusName, setFocusName, trail, setTrail, reopenId, hiddenTypes, setHiddenTypes,
    hiddenKinds, setHiddenKinds, maxNodes, setMaxNodes, listOpen, setListOpen, showNoise, setShowNoise, layers, setLayers,
    selectedId, setSelectedId, detail, setDetail, detailLoading, setDetailLoading, additions, setAdditions, freshIds, setFreshIds,
    expandNote, setExpandNote, noteTimer,
  };
}

export type EntityGraphState = ReturnType<typeof useEntityGraphState>;

// Loads the graph for the current search, focus, window and layers; a newer request always wins.
export function useEntityGraphLoad(g: EntityGraphState, projectId: string, sharedQuery: string | undefined) {
  const { requestEpoch, detailEpoch, centring, activeQuery, focusNodeId, maxNodes, layers, setSelectedId, setDetail,
    setDetailLoading, setPayload, setAdditions, setFreshIds, setExpandNote, setLoading, setError, setFocusNodeId, setFocusName,
    setTrail, setQuery, setActiveQuery } = g;
  const loadGraph = useCallback(async () => {
    const epoch = ++requestEpoch.current;
    ++detailEpoch.current;
    setSelectedId("");
    setDetail(null);
    setDetailLoading(false);
    setPayload(null);
    setAdditions(NO_ADDITIONS);
    setFreshIds(new Set());
    setExpandNote("");
    setLoading(true);
    setError("");
    try {
      const data = await readJson<EntityGraphPayload>(
        graphExplorerUrl(projectId, activeQuery, focusNodeId, maxNodes, layers));
      if (epoch !== requestEpoch.current) return;
      if (!acceptsGraphPayload(data, projectId)) throw new Error("The graph response does not match this workspace.");
      setPayload(data);
    } catch (err) {
      if (epoch === requestEpoch.current) setError(err instanceof Error ? err.message : "Failed to load graph");
    } finally {
      if (epoch === requestEpoch.current) setLoading(false);
    }
  }, [projectId, activeQuery, focusNodeId, maxNodes, layers, requestEpoch, detailEpoch, setSelectedId, setDetail, setDetailLoading,
    setPayload, setAdditions, setFreshIds, setExpandNote, setLoading, setError]);

  useEffect(() => {
    if (sharedQuery === undefined) return;
    setFocusNodeId(""); setFocusName(""); setTrail([]);
    setQuery(sharedQuery); setActiveQuery(sharedQuery || centring.current);
  }, [sharedQuery, centring, setFocusNodeId, setFocusName, setTrail, setQuery, setActiveQuery]);

  useEffect(() => {
    const requests = requestEpoch;
    const details = detailEpoch;
    void loadGraph();
    return () => { ++requests.current; ++details.current; };
  }, [loadGraph, requestEpoch, detailEpoch]);
  return loadGraph;
}

// Opens and closes the selected entity's details.
export function useEntityGraphDetail(g: EntityGraphState, projectId: string, onSelectedName?: (name: string) => void) {
  const { detailEpoch, setSelectedId, setDetail, setDetailLoading, setError } = g;
  const openDetail = useCallback(async (nodeId: string) => {
    const epoch = ++detailEpoch.current;
    setSelectedId(nodeId);
    setDetail(null);
    setDetailLoading(true);
    try {
      const data = await readJson<EntityNodeDetail>(
        `/api/v1/workspaces/${encodeURIComponent(projectId)}/knowledge/graph/explorer/nodes/${encodeURIComponent(nodeId)}`,
      );
      if (epoch !== detailEpoch.current) return;
      if (data.state !== "ok" || data.workspace_id !== projectId) throw new Error("Node details are currently unavailable.");
      setDetail(data);
      onSelectedName?.(data.display_name);
    } catch (err) {
      if (epoch === detailEpoch.current) setError(err instanceof Error ? err.message : "Could not load node details.");
    } finally {
      if (epoch === detailEpoch.current) setDetailLoading(false);
    }
  }, [projectId, onSelectedName, detailEpoch, setSelectedId, setDetail, setDetailLoading, setError]);

  const closeDetail = useCallback(() => {
    ++detailEpoch.current;
    setSelectedId("");
    setDetail(null);
    setDetailLoading(false);
    onSelectedName?.("");
  }, [onSelectedName, detailEpoch, setSelectedId, setDetail, setDetailLoading]);
  return { openDetail, closeDetail };
}

// An entity's name, focusing the view on an entity, and going back along the focus trail.
export function useEntityGraphFocus(g: EntityGraphState) {
  const { payload, additions, detail, activeQuery, focusNodeId, focusName, selectedId, trail, reopenId, setTrail, setActiveQuery,
    setQuery, setFocusName, setFocusNodeId } = g;
  const nameOf = useCallback((nodeId: string) =>
    payload?.nodes.find((node) => node.id === nodeId)?.display_name
    || additions.nodes.find((node) => node.id === nodeId)?.display_name
    || (detail?.id === nodeId ? detail.display_name : "")
    || detail?.relations.find((relation) => relation.peer_id === nodeId)?.peer_name || "", [payload, additions, detail]);

  const focusOn = useCallback(
    (nodeId: string) => {
      setTrail((previous) => pushContext(previous, { query: activeQuery, focusNodeId, focusName, selectedId }));
      setActiveQuery("");
      setQuery("");
      setFocusName(nameOf(nodeId));
      setFocusNodeId(nodeId);
      reopenId.current = nodeId;
    },
    [activeQuery, focusNodeId, focusName, selectedId, nameOf, reopenId, setTrail, setActiveQuery, setQuery, setFocusName, setFocusNodeId],
  );

  const goBack = (index: number) => {
    const step = cutTrail(trail, index);
    if (!step) return;
    setTrail(step.trail);
    setActiveQuery(step.previous.query);
    setQuery(step.previous.query);
    setFocusNodeId(step.previous.focusNodeId);
    setFocusName(step.previous.focusName);
    reopenId.current = step.previous.selectedId;
  };
  return { nameOf, focusOn, goBack };
}
