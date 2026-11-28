import { useCallback, useEffect, useRef, useState } from "react";

import type { ThreadGroup } from "../chatThreadTypes";
import { appendThreadGroupPage, removeThreadsFromGroups } from "./threadGroupPages";

type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

const SEARCH_DEBOUNCE_MS = 250;

export function useThreadSearch({ readJson, query }: { readJson: ReadJsonFn; query: string }) {
  const [result, setResult] = useState<{ query: string; groups: ThreadGroup[] } | null>(null);
  const latest = useRef("");
  const normalized = query.trim();

  useEffect(() => {
    latest.current = normalized;
    if (!normalized) {
      setResult(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void readJson<{ query: string; groups: ThreadGroup[] }>(
        `/chat/api/thread-groups/search?${new URLSearchParams({ q: normalized }).toString()}`,
      )
        .then((payload) => {
          if (latest.current === normalized) {
            setResult({ query: normalized, groups: payload.groups ?? [] });
          }
        })
        .catch(() => undefined);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [normalized, readJson]);

  const loadMore = useCallback(
    async (group: ThreadGroup) => {
      const params = new URLSearchParams({
        project_id: group.projectId ?? "",
        q: normalized,
        offset: String(group.nextOffset ?? group.sessions.length),
        limit: String(group.pageSize ?? 20),
      });
      const page = await readJson<ThreadGroup>(`/chat/api/thread-groups?${params.toString()}`);
      setResult((current) =>
        current && current.query === normalized
          ? { ...current, groups: appendThreadGroupPage(current.groups, page) }
          : current,
      );
    },
    [normalized, readJson],
  );

  const forget = useCallback((ids: string[]) => {
    setResult((current) => (current ? { ...current, groups: removeThreadsFromGroups(current.groups, ids) } : current));
  }, []);

  return {
    groups: result && result.query === normalized ? result.groups : null,
    loadMore,
    forget,
  };
}
