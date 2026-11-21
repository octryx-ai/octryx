// Graph review data of the Engineering Knowledge review queue: node types, filter options and label helpers.
export type GraphSourceRef = {
  source_type?: string;
  source_ref?: string;
  title?: string;
  url?: string;
  observed_at?: string;
};

export type GraphNode = {
  id: string;
  node_type: string;
  node_key: string;
  display_name: string;
  summary: string;
  status: string;
  scope_type: string;
  scope_id?: string | null;
  trust_level: string;
  classification: string;
  properties: Record<string, unknown>;
  source_refs: GraphSourceRef[];
  related_edges?: Array<{
    id: string;
    edge_type: string;
    direction: string;
    related_node?: GraphNode | null;
  }>;
  updated_at?: string | null;
};

export type GraphReviewPayload = {
  items: GraphNode[];
  total: number;
  stats: {
    status_counts?: Record<string, number>;
    trust_counts?: Record<string, number>;
  };
};

export const STATUS_OPTIONS = ["", "active", "draft", "rejected", "retracted", "expired", "stale"];
export const TRUST_OPTIONS = ["", "bronze", "silver", "gold", "official", "verified", "untrusted"];
export const CLASSIFICATION_OPTIONS = ["", "public", "internal", "confidential", "restricted", "secret"];
export const VALIDITY_OPTIONS = ["", "valid", "expired"];

export function optionLabel(value: string): string {
  return value ? value.replaceAll("_", " ") : "All";
}

export function sourceRefLabel(source: GraphSourceRef): string {
  return [source.source_type, source.source_ref].filter(Boolean).join(" · ") || "Evidence";
}

export function lifecycleField(node: GraphNode, key: string): string {
  const lifecycle = node.properties?.lifecycle;
  if (!lifecycle || typeof lifecycle !== "object") return "";
  const value = (lifecycle as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
}
