// State of one sidebar thread group: open parents, group open, row menu, inline rename, long press and paging.
import { useEffect, useMemo, useRef, useState } from "react";

import type { ThreadGroup, ThreadSummary } from "../chatThreadTypes";
import { sectionThreads } from "./threadTime";
import { countThreadTree, threadTreeContainsSelected, type ThreadActionHandler } from "./threadGroupRowHandlers";

export function useThreadGroupSectionState(group: ThreadGroup, onDraftSelect: (() => void) | undefined) {
  const [expandedParents, setExpandedParents] = useState<
    Record<string, boolean>
  >({});
  const [groupOpen, setGroupOpen] = useState(
    () =>
      Boolean(onDraftSelect) ||
      group.sessions.some((thread) => threadTreeContainsSelected(thread)),
  );
  const [openMenuThreadId, setOpenMenuThreadId] = useState<string | null>(null);
  const [renamingThreadId, setRenamingThreadId] = useState<string | null>(null);
  const menuTriggers = useRef<Record<string, HTMLButtonElement | null>>({});
  // Long-press on touch starts selection with the row; the click that follows must not toggle it off.
  const longPress = useRef<{ timer: number | null; fired: boolean }>({ timer: null, fired: false });
  const [loadingMore, setLoadingMore] = useState(false);
  const groupThreadCount = useMemo(
    () => group.totalThreadCount ?? countThreadTree(group.sessions),
    [group.sessions, group.totalThreadCount],
  );
  const sections = useMemo(() => sectionThreads(group.sessions), [group.sessions]);

  useEffect(() => {
    let hasSelectedThread = false;
    setExpandedParents((current) => {
      const next = { ...current };
      for (const thread of group.sessions) {
        if (threadTreeContainsSelected(thread)) {
          next[thread.id] = true;
          hasSelectedThread = true;
        }
      }
      return next;
    });
    if (hasSelectedThread) {
      setGroupOpen(true);
    }
  }, [group.sessions]);

  const hasDraft = Boolean(onDraftSelect);
  useEffect(() => {
    if (hasDraft) {
      setGroupOpen(true);
    }
  }, [hasDraft]);

  useEffect(() => {
    if (!openMenuThreadId) {
      return;
    }
    const close = () => setOpenMenuThreadId(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [openMenuThreadId]);

  return {
    expandedParents, setExpandedParents, groupOpen, setGroupOpen, openMenuThreadId, setOpenMenuThreadId,
    renamingThreadId, setRenamingThreadId, menuTriggers, longPress, loadingMore, setLoadingMore, groupThreadCount,
    sections,
  };
}

type GroupState = ReturnType<typeof useThreadGroupSectionState>;

// Opening a parent row, running a row menu action, and loading the next page of the group.
export function createThreadGroupActions(state: GroupState, onLoadMore: (() => void | Promise<void>) | undefined) {
  const { setExpandedParents, setOpenMenuThreadId, loadingMore, setLoadingMore } = state;
  const toggleParent = (threadId: string) => {
    setExpandedParents((current) => ({
      ...current,
      [threadId]: !current[threadId],
    }));
  };

  const runAction = async (
    thread: ThreadSummary,
    action: ThreadActionHandler,
  ) => {
    setOpenMenuThreadId(null);
    await action(thread);
  };

  const handleLoadMore = async () => {
    if (!onLoadMore || loadingMore) {
      return;
    }
    setLoadingMore(true);
    try {
      await onLoadMore();
    } finally {
      setLoadingMore(false);
    }
  };
  return { toggleParent, runAction, handleLoadMore };
}
