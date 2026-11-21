import type { EntityGraphPayload, GraphLayer } from "./entityGraphTypes";

export const GRAPH_LAYERS: Array<{ id: GraphLayer; label: string }> = [
  { id: "manual", label: "Manual" },
  { id: "configuration", label: "Configuration" },
  { id: "operations", label: "Operations" },
  { id: "extracted", label: "Extracted" },
];

export function graphExplorerUrl(workspaceId: string, query: string, focus: string, maxNodes: number,
  layers: GraphLayer[] = []) {
  if (!workspaceId) throw new Error("Choose a workspace to explore its graph.");
  const params = new URLSearchParams({ max_nodes: String(maxNodes) });
  if (query) params.set("query", query);
  if (focus) params.set("focus_node_id", focus);
  // Every layer is the server default; only a narrower selection is sent.
  if (layers.length && layers.length < GRAPH_LAYERS.length) params.set("layers", layers.join(","));
  return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/knowledge/graph/explorer?${params}`;
}

/** Additive Expand: only what is new around `nodeId`; never sent together with focus_node_id (422). */
export function graphExpandUrl(workspaceId: string, nodeId: string, currentIds: string, maxNodes: number,
  layers: GraphLayer[] = []) {
  if (!workspaceId) throw new Error("Choose a workspace to explore its graph.");
  const params = new URLSearchParams({ expand_node_id: nodeId, max_nodes: String(maxNodes) });
  if (currentIds) params.set("current_node_ids", currentIds);
  if (layers.length && layers.length < GRAPH_LAYERS.length) params.set("layers", layers.join(","));
  return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/knowledge/graph/explorer?${params}`;
}

export function graphNotice(payload: EntityGraphPayload | null, visibleCount: number, query: string, focus = "") {
  if (!payload) return null;
  switch (payload.state) {
    case "needs_configuration": return {title:"Graph needs configuration", text:"Ask your administrator to configure the knowledge graph for this workspace.", reset:false};
    case "unavailable": case "timeout": case "unauthorized": case "contract_violation":
      return {title:"Graph could not be loaded", text:"The knowledge graph service could not return an authorized result. Retry or ask your administrator to check its configuration.", reset:false};
    case "no_matches":
      if (!query && !focus) return {title:"No accessible relationships in this view", text:"Open Documents to check source processing. Repository functions and code links are available in Repository explorer.", reset:false};
      return {title:"No matching entities", text:`No authorized matches were found for ${query ? `“${query}”` : "this selection"} in the searched graph window. Clear the search or try a different term.`, reset:true};
    case "not_extracted": return {title:"No extracted relationships available", text:"Check source processing, product and version in Documents. An administrator with knowledge authoring access can extract relationships under Admin › Knowledge › Changes; ask your workspace owner if you need help. Uploading alone does not create the graph.", reset:false};
    case "ok":
      if (payload.nodes.length && !visibleCount) return {title:"All entities are hidden", text:"Show all entity types to restore this graph.", reset:true};
      if (!payload.nodes.length) return {title:"No relationships available in this view", text:"Open Documents to inspect source processing, or Repository explorer to explore code links.", reset:false};
      return null;
    default: return {title:"Graph response not recognized", text:"Reload the graph. Contact your administrator if the response remains unavailable.", reset:false};
  }
}

export function graphDestination(workspaceId: string, destination: "documents" | "repositories") {
  const params = new URLSearchParams(destination === "documents"
    ? {area:"knowledge",tab:"knowledgeSources"} : {area:"coding",coding_view:"repositories"});
  if (workspaceId) params.set("workspace_id", workspaceId);
  return `/chat?${params}`;
}

// The type filter only helps when there is more than one type. A single "entity" type means the
// extraction did not classify entities, which is stated instead of showing a one-chip filter.
export type TypeLegend = { kind: "filter"; types: Array<[string, number]> } | { kind: "note"; text: string } | null;

export function typeLegend(nodeTypes: Record<string, number> | undefined): TypeLegend {
  const types = Object.entries(nodeTypes ?? {}).filter(([, count]) => count > 0);
  if (!types.length) return null;
  if (types.length > 1) return { kind: "filter", types };
  const [[nodeType, count]] = types;
  if (nodeType === "entity") return { kind: "note", text: "Entity types are not classified for this workspace." };
  return { kind: "note", text: `All ${count} ${count === 1 ? "entity" : "entities"} shown are of type ${nodeType}.` };
}

// At least one layer stays selected; the order is the fixed layer order.
export function toggleGraphLayer(selected: GraphLayer[], layer: GraphLayer): GraphLayer[] {
  const next = selected.includes(layer) ? selected.filter((item) => item !== layer) : [...selected, layer];
  return next.length ? GRAPH_LAYERS.map((item) => item.id).filter((id) => next.includes(id)) : selected;
}

export function acceptsGraphPayload(payload: EntityGraphPayload, workspaceId: string): boolean {
  return (payload.store === "workspace_graph" || payload.store === "extracted_graph") && payload.workspace_id === workspaceId;
}
