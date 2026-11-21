// Types for the entity knowledge-graph explorer (gold layer).

// "extracted": Graphiti facts; the others are the deterministic structured layers.
export type GraphLayer = "manual" | "configuration" | "operations" | "extracted";

export type EntityGraphNode = {
  id: string;
  node_type: string;
  display_name: string;
  description: string;
  degree: number;
  trust_level: string;
  // True for a node that matched the query itself (not one shown as a match's neighbour).
  matched?: boolean;
  layer?: GraphLayer;
};

export type GraphEvidence = {
  citation?: string;
  cite_as?: string;
  evidence_key?: string;
  source_title?: string;
  source_url?: string | null;
  section?: string | null;
  // A manual page or a file line the citation opens at (structured layers).
  page?: number | null;
  line?: number | null;
  source_id?: string;
  revision_id?: string;
};

export type GraphState = "ok" | "not_extracted" | "no_matches" | "needs_configuration" |
  "unavailable" | "unauthorized" | "timeout" | "contract_violation";

export type EntityGraphEdge = GraphEvidence & {
  id: string;
  source: string;
  target: string;
  edge_type: string;
  description: string;
  layer?: GraphLayer;
  // Every span a structured edge rests on (both ends of a comparison, for instance).
  citations?: GraphEvidence[];
};

export type EntityGraphStats = {
  shown_nodes: number;
  shown_edges: number;
  total_nodes: number | null;
  total_edges: number | null;
  total_claims: number | null;
  total_communities: number | null;
  // Null without a query; the number of matched nodes shown with one.
  matched_nodes?: number | null;
  match_limit?: number;
  // "project": totals cover the selected workspace plus instance-global entities; "instance": everything.
  scope?: "project" | "instance";
  counts_scope?: "visible";
  node_types: Record<string, number>;
  edge_types: Record<string, number>;
  layers?: Partial<Record<GraphLayer, number>>;
  // Per store: null when that store was not read or did not answer.
  totals_by_store?: Record<string, { nodes: number; edges: number } | null>;
};

export type EntityGraphPayload = {
  // "workspace_graph": extracted plus structured layers; "extracted_graph": the extracted graph alone.
  store: "extracted_graph" | "workspace_graph";
  workspace_id: string;
  state: GraphState;
  truncated: boolean;
  nodes: EntityGraphNode[];
  edges: EntityGraphEdge[];
  // Null without a query; the matched node ids (possibly none) with one.
  match_ids?: string[] | null;
  stats: EntityGraphStats;
  layer_states?: { extracted: string; structured: string };
  // How the window was read; "expand" answers are additive (only what is new to the view).
  mode?: "overview" | "query" | "focus" | "expand";
  additive?: boolean;
  expand_node_id?: string;
};

export type EntityNodeClaim = GraphEvidence & {
  claim_type: string;
  statement: string;
  valid_from_label: string | null;
  valid_until_label: string | null;
};

export type EntityNodeRelation = GraphEvidence & {
  edge_type: string;
  direction: "in" | "out";
  peer_id: string;
  peer_name: string;
  peer_type: string;
  description: string;
};

export type EntityNodeDetail = {
  state?: GraphState;
  store?: "extracted_graph" | "workspace_graph";
  workspace_id?: string;
  truncated?: boolean;
  id: string;
  node_type: string;
  display_name: string;
  description: string;
  trust_level: string;
  status: string;
  properties: Record<string, unknown>;
  source_refs: string[];
  aliases: string[];
  claims: EntityNodeClaim[];
  relations: EntityNodeRelation[];
};
