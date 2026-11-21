import { useEffect, useRef, useState } from "react";
import { workspaceKnowledgeApi } from "./workspaceKnowledgeApi";
import type { SearchResult } from "./workspaceKnowledgeTypes";

type SearchRequest = Record<string, unknown>;
type Search = (workspaceId: string, body: SearchRequest) => Promise<SearchResult>;
type SearchState = {
  generation: number;
  workspaceId: string;
  query: string;
  result: SearchResult | null;
  error: string | null;
  errorState: string | null;
  busy: boolean;
};

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const stateOf = (error: unknown) => {
  const state = (error as { state?: unknown } | null)?.state;
  return typeof state === "string" && state ? state : null;
};

// One search sends one request: the hybrid search runs the keyword stage itself, and a second, lexical-only request
// in parallel would only queue behind it on a busy server and delay the full result (and the short answer that
// waits for it).
// A response belongs to the submitted query and workspace, never to a later search.
export function useKnowledgeSearch(workspaceId: string, search: Search = workspaceKnowledgeApi.search) {
  const generation = useRef(0);
  const [state, setState] = useState<SearchState>({
    generation: 0, workspaceId, query: "", result: null, error: null, errorState: null, busy: false,
  });

  useEffect(() => () => { generation.current += 1; }, [workspaceId]);

  const submit = async (body: SearchRequest) => {
    const query = typeof body.query_text === "string" ? body.query_text.trim() : "";
    if (!workspaceId || !query) return;
    const requestGeneration = ++generation.current;
    const mine = () => generation.current === requestGeneration;
    const base = { generation: requestGeneration, workspaceId, query };
    setState({ ...base, result: null, error: null, errorState: null, busy: true });
    try {
      const result = await search(workspaceId, { ...body, query_text: query });
      if (mine()) setState({ ...base, result, error: null, errorState: null, busy: false });
    } catch (error) {
      if (mine()) setState({ ...base, result: null, error: message(error), errorState: stateOf(error), busy: false });
    }
  };

  const current = state.workspaceId === workspaceId && state.generation === generation.current;
  return {
    submit,
    query: current ? state.query : "",
    result: current ? state.result : null,
    error: current ? state.error : null,
    errorState: current ? state.errorState : null,
    busy: current && state.busy,
  };
}
