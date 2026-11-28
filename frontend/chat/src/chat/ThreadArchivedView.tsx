import { useCallback, useEffect, useState } from "react";

import type { ThreadSummary } from "../chatThreadTypes";
import { readJson } from "./chatApiClient";
import { ThreadChevronIcon } from "./threadSidebarIcons";
import { threadTimeLabel } from "./threadTime";

type ArchivedPage = { total: number; threads: ThreadSummary[]; nextOffset: number; hasMore: boolean };

export function ThreadArchivedView({
  onBack,
  onRestore,
}: {
  onBack: () => void;
  onRestore: (ids: string[]) => Promise<{ affectedIds: string[] }>;
}) {
  const [page, setPage] = useState<ArchivedPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<string | null>(null);

  const load = useCallback(async (offset: number) => {
    try {
      const next = await readJson<ArchivedPage>(`/chat/api/threads/archived?offset=${offset}&limit=50`);
      setPage((current) =>
        current && offset > 0 ? { ...next, threads: [...current.threads, ...next.threads] } : next,
      );
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load archived chats");
    }
  }, []);

  useEffect(() => {
    void load(0);
  }, [load]);

  const restore = async (thread: ThreadSummary) => {
    setRestoring(thread.id);
    try {
      const result = await onRestore([thread.id]);
      setPage((current) =>
        current
          ? {
              ...current,
              total: Math.max(0, current.total - result.affectedIds.length),
              threads: current.threads.filter((row) => !result.affectedIds.includes(row.id)),
            }
          : current,
      );
    } finally {
      setRestoring(null);
    }
  };

  return (
    <section className="thread-archived" aria-label="Archived chats">
      <div className="thread-archived__head">
        <button type="button" className="icon-button sidebar__icon-btn" aria-label="Back to chats" onClick={onBack}>
          <span className="thread-archived__back">
            <ThreadChevronIcon open={false} />
          </span>
        </button>
        <strong>Archived chats</strong>
        {page ? <span className="thread-group__title-meta">{page.total}</span> : null}
      </div>
      {error ? <div className="sidebar__empty">{error}</div> : null}
      {page && !page.threads.length ? <div className="sidebar__empty">No archived chats.</div> : null}
      {page?.threads.map((thread) => (
        <div key={thread.id} className="thread-archived__row">
          <span className="thread-card__title-text">{thread.title}</span>
          <span className="thread-card__time">{threadTimeLabel(thread.lastActivityAt ?? thread.startedAt)}</span>
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={restoring === thread.id}
            onClick={() => void restore(thread)}
          >
            {restoring === thread.id ? "Restoring…" : "Restore"}
          </button>
        </div>
      ))}
      {page?.hasMore ? (
        <button type="button" className="thread-group__load-more" onClick={() => void load(page.nextOffset)}>
          Show more · {page.total - page.threads.length} not shown
        </button>
      ) : null}
    </section>
  );
}
