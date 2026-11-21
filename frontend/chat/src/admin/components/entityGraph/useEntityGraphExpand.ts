// Additive Expand of the entity graph panel: loads what is new around an entity and places it beside it.
import { useCallback, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { readJson } from "../../utils/adminPanelHelpers";
import type { Placed } from "./kgLayout";
import { currentIdsParam, EXPAND_MAX_NODES, mergeAdditions, placeAround } from "./kgExpand";
import type { EntityGraphPayload, GraphLayer } from "./entityGraphTypes";
import { acceptsGraphPayload, graphExpandUrl } from "./entityGraphPresentation";
import type { GraphAdditions } from "./useEntityGraphView";

// How long new entities from an Expand stay highlighted.
export const FRESH_MS = 4000;

type ExpandInput = {
  projectId: string;
  payload: EntityGraphPayload | null;
  additions: GraphAdditions;
  positions: Map<string, Placed>;
  selectedId: string;
  layers: GraphLayer[];
  nameOf: (nodeId: string) => string;
  requestEpoch: MutableRefObject<number>;
  noteTimer: MutableRefObject<number>;
  setExpandNote: (note: string) => void;
  setAdditions: Dispatch<SetStateAction<GraphAdditions>>;
  setFreshIds: (ids: Set<string>) => void;
  setError: (error: string) => void;
};

export function useEntityGraphExpand({ projectId, payload, additions, positions, selectedId, layers, nameOf, requestEpoch,
  noteTimer, setExpandNote, setAdditions, setFreshIds, setError }: ExpandInput) {
  // Expand adds what is new around an entity to this view; it never replaces the view. The ids the view
  // shows go along (over the server's limit: the selection, the entity, its neighbours and the hubs first).
  const expandEpoch = useRef(0);
  return useCallback(async (nodeId: string) => {
    const centre = positions.get(nodeId);
    if (!payload || !centre) return;
    const epoch = ++expandEpoch.current;
    const base = requestEpoch.current;
    const shownNodes = (payload.nodes || []).concat(additions.nodes);
    const shownEdges = (payload.edges || []).concat(additions.edges);
    const around = shownEdges.flatMap((edge) => (edge.source === nodeId ? [edge.target] : edge.target === nodeId ? [edge.source] : []));
    const hubs = [...shownNodes].sort((a, b) => b.degree - a.degree).map((node) => node.id);
    const ids = currentIdsParam(shownNodes.map((node) => node.id), [selectedId, nodeId, ...around, ...hubs]);
    const name = nameOf(nodeId) || "this entity";
    const say = (text: string, ms = FRESH_MS + 1000) => {
      setExpandNote(text);
      window.clearTimeout(noteTimer.current);
      if (ms) noteTimer.current = window.setTimeout(() => setExpandNote(""), ms);
    };
    say(`Expanding ${name}…`, 0);
    try {
      const data = await readJson<EntityGraphPayload>(graphExpandUrl(projectId, nodeId, ids, EXPAND_MAX_NODES, layers));
      if (epoch !== expandEpoch.current || base !== requestEpoch.current) return;
      if (!acceptsGraphPayload(data, projectId)) throw new Error("The graph response does not match this workspace.");
      const known = new Set(shownNodes.map((node) => node.id));
      const fresh = data.state === "ok" ? data.nodes.filter((node) => !known.has(node.id)) : [];
      if (!fresh.length) { say(`Nothing new around ${name}`); return; }
      const placed = placeAround(centre, fresh, Array.from(positions.values()));
      setAdditions((previous) => mergeAdditions({ nodes: payload.nodes, edges: payload.edges }, previous,
        { nodes: fresh, edges: data.edges }, placed));
      setFreshIds(new Set(fresh.map((node) => node.id)));
      say(`${fresh.length} new around ${name}${data.truncated ? " · expand again for more" : ""}`);
      window.setTimeout(() => { if (epoch === expandEpoch.current) setFreshIds(new Set()); }, FRESH_MS);
    } catch (err) {
      if (epoch === expandEpoch.current) { say(""); setError(err instanceof Error ? err.message : "Could not expand this entity."); }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload, additions, positions, selectedId, nameOf, projectId, layers]);
}
