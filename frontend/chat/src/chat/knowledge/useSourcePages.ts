import { useCallback, useEffect, useRef, useState } from "react";
import type { KnowledgeSource, SourceListing } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";

export type SourcePageRequest = (
  workspaceId: string,
  page: { limit?: number; cursor?: string | null; query?: string },
) => Promise<SourceListing>;

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}

// Cursor-paged Documents list (judge J-C-001/J-C-002). Every first-page load
// opens a new scope (workspace, query or refresh); a late first page, next
// page, error or finally from an older scope is ignored, so it can never append
// rows or a cursor of a previous query to the current results.
export function useSourcePages(
  workspaceId: string,
  query: string,
  refresh: number,
  request: SourcePageRequest,
  pageSize: number,
) {
  const scope = useRef(0);
  const [listing, setListing] = useState<SourceListing | null>(null);
  const [loaded, setLoaded] = useState<KnowledgeSource[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const scopeRef = scope;
    const current = ++scopeRef.current;
    setListing(null); setLoaded([]); setLoadingMore(false); setError(null);
    request(workspaceId, { limit: pageSize, query }).then(
      (result) => {
        if (scopeRef.current !== current) return;
        setListing(result); setLoaded(result.sources);
      },
      (failure: unknown) => { if (scopeRef.current === current) setError(message(failure)); },
    );
    return () => { scopeRef.current++; };
  }, [workspaceId, query, refresh, request, pageSize]);

  const loadMore = useCallback(async () => {
    const cursor = listing?.next_cursor;
    if (!cursor || loadingMore) return;
    const current = scope.current;
    setLoadingMore(true);
    try {
      const next = await request(workspaceId, { limit: pageSize, cursor, query });
      if (scope.current !== current) return;
      setListing(next);
      setLoaded((rows) => [...rows, ...next.sources.filter((item) => !rows.some((seen) => seen.source_id === item.source_id))]);
    } catch (failure) {
      if (scope.current === current) setError(message(failure));
    } finally {
      if (scope.current === current) setLoadingMore(false);
    }
  }, [listing, loadingMore, request, workspaceId, pageSize, query]);

  return { listing, loaded, loadingMore, error, loadMore, hasMore: Boolean(listing?.next_cursor) };
}
