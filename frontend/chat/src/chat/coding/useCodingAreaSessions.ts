// The Coding page's session lists: the active queue, the search over it, the selected session and its shown detail.
import { useEffect, useMemo } from "react";

import { sessionInQueue, type CodingQueueKey } from "./codingQueuePresenter";
import type { useCodingAreaState } from "./useCodingAreaState";

export type CodingAreaState = ReturnType<typeof useCodingAreaState>;

export function useCodingAreaSessions(state: CodingAreaState, activeQueue: CodingQueueKey | null) {
  const { sessions, search, detail, reviewAudit, selectedId, setPinnedDetail, pinnedDetail, workItems } = state;
  const queueSessions = useMemo(
    () => (activeQueue ? sessions.filter((session) => sessionInQueue(session, activeQueue)) : []),
    [activeQueue, sessions],
  );
  const filteredSessions = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    if (!normalizedSearch) {
      return queueSessions;
    }
    return queueSessions.filter((session) =>
      [session.sourceKey, session.title, ...session.repositories, ...session.branches]
        .join(" ")
        .toLowerCase()
        .includes(normalizedSearch),
    );
  }, [queueSessions, search]);
  const selectedSession = sessions.find((session) => session.id === selectedId) || null;
  // The detail shows only the audit report read for this item.
  const shownDetail = useMemo(
    () => (detail ? { ...detail, auditReport: reviewAudit?.itemId === selectedId ? reviewAudit.report : null } : null),
    [detail, reviewAudit, selectedId],
  );
  // A selected item stays open when a new verdict moves it out of the current queue.
  useEffect(() => {
    if (activeQueue && selectedId && filteredSessions.some((session) => session.id === selectedId)) {
      setPinnedDetail({ queue: activeQueue, id: selectedId });
    }
  }, [activeQueue, selectedId, filteredSessions, setPinnedDetail]);
  const keepDetail = Boolean(
    selectedSession && pinnedDetail && pinnedDetail.queue === activeQueue && pinnedDetail.id === selectedSession.id,
  );
  const selectedWorkItem = workItems.find((item) => item.id === selectedId) || null;
  return { queueSessions, filteredSessions, selectedSession, shownDetail, keepDetail, selectedWorkItem };
}
