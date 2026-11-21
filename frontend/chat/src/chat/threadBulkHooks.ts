// Parts of the thread bulk-action hook, each a contiguous run of hooks called in the original order.
import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";

import { fetchThreadGroupCount, previewThreadBulkAction } from "./threadBulkActions";
import {
  clearGroup,
  dropScopes,
  EMPTY_THREAD_SELECTION,
  groupCheckState,
  rangeThreadRefs,
  selectGroupScope,
  selectThreads,
  toggleGroupVisible,
  toggleThread,
  type ThreadRef,
  type ThreadSelection,
} from "./threadSelection";
import type { ThreadBulkArgs, ThreadBulkDialog, ThreadBulkToast } from "./threadBulkTypes";

export const UNDO_SECONDS = 10;

type Setter<T> = Dispatch<SetStateAction<T>>;

export function useThreadBulkState(threadSearchQuery: string) {
  const [bulkMode, setBulkMode] = useState(false);
  const [selection, setSelection] = useState<ThreadSelection>(EMPTY_THREAD_SELECTION);
  const [anchorId, setAnchorId] = useState<string | null>(null);
  const [searchOffers, setSearchOffers] = useState<Record<string, number>>({});
  const [dialog, setDialog] = useState<ThreadBulkDialog | null>(null);
  const [toast, setToast] = useState<ThreadBulkToast | null>(null);
  const query = threadSearchQuery.trim();
  const queryRef = useRef(query);

  // A scope belongs to one query: a new search drops the scopes (explicit ids stay).
  useEffect(() => {
    if (queryRef.current === query) {
      return;
    }
    queryRef.current = query;
    setSelection((current) => dropScopes(current));
    setSearchOffers({});
  }, [query]);

  useEffect(() => {
    if (!toast) {
      return;
    }
    const timer = window.setTimeout(() => {
      setToast((current) =>
        current && current.secondsLeft > 1 ? { ...current, secondsLeft: current.secondsLeft - 1 } : null,
      );
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  return {
    bulkMode, setBulkMode, selection, setSelection, anchorId, setAnchorId,
    searchOffers, setSearchOffers, dialog, setDialog, toast, setToast, query,
  };
}

type BulkState = ReturnType<typeof useThreadBulkState>;

function useThreadBulkModeActions({ setBulkMode, setSelection, setAnchorId, setSearchOffers, setDialog }: BulkState) {
  const enter = useCallback((thread?: ThreadRef) => {
    setBulkMode(true);
    setSelection(thread ? toggleThread(EMPTY_THREAD_SELECTION, thread) : EMPTY_THREAD_SELECTION);
    setAnchorId(thread?.id ?? null);
  }, [setAnchorId, setBulkMode, setSelection]);

  const exit = useCallback(() => {
    setBulkMode(false);
    setSelection(EMPTY_THREAD_SELECTION);
    setAnchorId(null);
    setSearchOffers({});
    setDialog(null);
  }, [setAnchorId, setBulkMode, setDialog, setSearchOffers, setSelection]);

  const clear = useCallback(() => {
    setSelection(EMPTY_THREAD_SELECTION);
    setAnchorId(null);
  }, [setAnchorId, setSelection]);

  return { enter, exit, clear };
}

export function useThreadBulkSelection(state: BulkState, readJson: ThreadBulkArgs["readJson"]) {
  const { enter, exit, clear } = useThreadBulkModeActions(state);
  const { anchorId, setAnchorId, selection, setSelection, setSearchOffers, query } = state;

  const toggle = useCallback(
    (thread: ThreadRef, shift: boolean, ordered: ThreadRef[]) => {
      setSelection((current) =>
        shift && anchorId ? selectThreads(current, rangeThreadRefs(ordered, anchorId, thread.id)) : toggleThread(current, thread),
      );
      setAnchorId(thread.id);
    },
    [anchorId, setAnchorId, setSelection],
  );

  const selectAll = useCallback((ordered: ThreadRef[]) => {
    setSelection((current) => selectThreads(current, ordered));
  }, [setSelection]);

  const groupCheck = useCallback(
    (projectId: string, visibleIds: string[]) => {
      const next = toggleGroupVisible(selection, projectId, visibleIds);
      setSelection(next);
      if (query && groupCheckState(next, projectId, visibleIds) === "visible") {
        void fetchThreadGroupCount(readJson, projectId, query)
          .then(({ count }) => setSearchOffers((current) => ({ ...current, [projectId]: count })))
          .catch(() => undefined);
      }
    },
    [query, readJson, selection, setSearchOffers, setSelection],
  );

  const selectScope = useCallback(
    async (projectId: string) => {
      const { count, asOf } = await fetchThreadGroupCount(readJson, projectId, query);
      setSelection((current) => selectGroupScope(current, { projectId, query, asOf, count }));
    },
    [query, readJson, setSelection],
  );

  const clearScope = useCallback((projectId: string) => {
    setSelection((current) => clearGroup(current, projectId));
  }, [setSelection]);

  return { enter, exit, clear, toggle, selectAll, groupCheck, selectScope, clearScope };
}

export function useThreadBulkDialogOpen(
  selection: ThreadSelection,
  setDialog: Setter<ThreadBulkDialog | null>,
  { canDeleteThreads, readJson }: Pick<ThreadBulkArgs, "canDeleteThreads" | "readJson">,
) {
  const openDialogFor = useCallback(
    async (action: ThreadBulkDialog["action"], target: ThreadSelection, notLoaded: number) => {
      if (action === "delete" && !canDeleteThreads) {
        return;
      }
      const opened: ThreadBulkDialog = { action, selection: target, notLoaded, preview: null, error: null, running: false };
      setDialog(opened);
      try {
        const preview = await previewThreadBulkAction(readJson, target, action);
        setDialog((current) => (current?.selection === target ? { ...current, preview } : current));
      } catch (error) {
        const message = error instanceof Error ? error.message : "Could not check the selection";
        setDialog((current) => (current?.selection === target ? { ...current, error: message } : current));
      }
    },
    [canDeleteThreads, readJson, setDialog],
  );

  /** `notLoaded`: chats of the selected scopes that the list has not loaded (dialog note). */
  const openDialog = useCallback(
    (action: ThreadBulkDialog["action"], notLoaded = 0) => openDialogFor(action, selection, notLoaded),
    [openDialogFor, selection],
  );

  /** Row menu "Delete…": the same confirm dialog for one chat. */
  const deleteOne = useCallback(
    (thread: ThreadRef) => openDialogFor("delete", toggleThread(EMPTY_THREAD_SELECTION, thread), 0),
    [openDialogFor],
  );

  const closeDialog = useCallback(() => setDialog(null), [setDialog]);

  return { openDialog, deleteOne, closeDialog };
}
