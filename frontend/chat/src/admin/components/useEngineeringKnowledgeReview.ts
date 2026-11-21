// State and requests of the Engineering Knowledge review queue: the filters, the loaded facts, the selected fact and
// its review actions.
import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { readJson } from "../utils/adminPanelHelpers";
import type { GraphNode, GraphReviewPayload } from "./engineeringKnowledgeReviewModel";

const BASE = "/admin/chat/api/panel/engineering-knowledge/graph";

export function useReviewFilters() {
  const [query, setQuery] = useState("");
  const [nodeType, setNodeType] = useState("");
  const [status, setStatus] = useState("");
  const [trustLevel, setTrustLevel] = useState("");
  const [classification, setClassification] = useState("");
  const [source, setSource] = useState("");
  const [validity, setValidity] = useState("");
  return {
    query, setQuery, nodeType, setNodeType, status, setStatus, trustLevel, setTrustLevel,
    classification, setClassification, source, setSource, validity, setValidity,
  };
}

export type ReviewFilters = ReturnType<typeof useReviewFilters>;

type QueueSetters = {
  setLoading: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setPayload: Dispatch<SetStateAction<GraphReviewPayload | null>>;
  setSelected: Dispatch<SetStateAction<GraphNode | null>>;
  setBusyAction: Dispatch<SetStateAction<string>>;
};

// The request's query string: only the filters that are set, at most 50 facts.
function reviewSearchParams(filters: Omit<ReviewFilters, `set${string}`>) {
  const { classification, nodeType, query, source, status, trustLevel, validity } = filters;
  const params = new URLSearchParams();
  if (query.trim()) params.set("query", query.trim());
  if (nodeType.trim()) params.set("node_type", nodeType.trim());
  if (status) params.set("status", status);
  if (trustLevel) params.set("trust_level", trustLevel);
  if (classification) params.set("classification", classification);
  if (source.trim()) params.set("source", source.trim());
  if (validity) params.set("validity", validity);
  params.set("limit", "50");
  return params;
}

const errorText = (err: unknown) => (err instanceof Error ? err.message : String(err));

async function loadQueue(searchParams: URLSearchParams, setters: QueueSetters) {
  const { setLoading, setError, setPayload, setSelected } = setters;
  setLoading(true);
  setError(null);
  try {
    const result = await readJson<GraphReviewPayload>(
      `${BASE}/nodes?${searchParams.toString()}`,
    );
    setPayload(result);
    setSelected((current) => {
      if (!current) return result.items[0] || null;
      return result.items.find((item) => item.id === current.id) || result.items[0] || null;
    });
  } catch (err) {
    setError(errorText(err));
  } finally {
    setLoading(false);
  }
}

async function inspectNode(
  node: GraphNode,
  setError: Dispatch<SetStateAction<string | null>>,
  setSelected: Dispatch<SetStateAction<GraphNode | null>>,
) {
  setError(null);
  try {
    const params = new URLSearchParams({ scope_type: node.scope_type, include_related: "true" });
    if (node.scope_id) params.set("scope_id", node.scope_id);
    const detail = await readJson<GraphNode>(
      `${BASE}/entities/${node.id}?${params.toString()}`,
    );
    setSelected(detail);
  } catch (err) {
    setError(errorText(err));
  }
}

async function reviewNode(
  selected: GraphNode | null,
  setters: QueueSetters,
  load: () => Promise<void>,
  request: { action: string; reason: string; extra: Record<string, unknown> },
) {
  const { setBusyAction, setError, setSelected } = setters;
  const { action, reason, extra } = request;
  if (!selected) return;
  setBusyAction(action);
  setError(null);
  try {
    const detail = await readJson<GraphNode>(
      `${BASE}/nodes/${selected.id}/review`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, reason, ...extra }),
      },
    );
    setSelected(detail);
    await load();
  } catch (err) {
    setError(errorText(err));
  } finally {
    setBusyAction("");
  }
}

// The loaded facts, the selected one and the review requests; reloads whenever a filter changes.
export function useReviewQueue(filters: ReviewFilters) {
  const [payload, setPayload] = useState<GraphReviewPayload | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);

  const { classification, nodeType, query, source, status, trustLevel, validity } = filters;
  const searchParams = useMemo(
    () => reviewSearchParams({ classification, nodeType, query, source, status, trustLevel, validity }),
    [classification, nodeType, query, source, status, trustLevel, validity],
  );

  const load = useCallback(
    () => loadQueue(searchParams, { setLoading, setError, setPayload, setSelected, setBusyAction }),
    [searchParams],
  );

  const inspect = useCallback((node: GraphNode) => inspectNode(node, setError, setSelected), []);

  const review = useCallback(
    (action: string, reason: string, extra: Record<string, unknown> = {}) =>
      reviewNode(selected, { setLoading, setError, setPayload, setSelected, setBusyAction }, load, { action, reason, extra }),
    [load, selected],
  );

  useEffect(() => {
    void load();
  }, [load]);

  return { payload, selected, loading, busyAction, error, showHelp, setShowHelp, load, inspect, review };
}
