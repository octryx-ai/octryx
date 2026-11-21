// Result side of the thread bulk-action hook: confirm, archive, undo/restore and the Esc key.
import { useCallback, useEffect, type Dispatch, type SetStateAction } from "react";

import {
  bulkResultMessage,
  performThreadBulkAction,
  restoreThreads,
  type ThreadBulkResult,
} from "./threadBulkActions";
import { EMPTY_THREAD_SELECTION, toggleThread, type ThreadBulkAction, type ThreadRef } from "./threadSelection";
import type { ThreadBulkArgs, ThreadBulkDialog, ThreadBulkToast } from "./threadBulkTypes";
import { UNDO_SECONDS } from "./threadBulkHooks";

type Setter<T> = Dispatch<SetStateAction<T>>;

type ResultArgs = Omit<ThreadBulkArgs, "canDeleteThreads" | "threadSearchQuery"> & {
  dialog: ThreadBulkDialog | null;
  setDialog: Setter<ThreadBulkDialog | null>;
  toast: ThreadBulkToast | null;
  setToast: Setter<ThreadBulkToast | null>;
  exit: () => void;
};

export function useThreadBulkResults(args: ResultArgs) {
  const { readJson, loadState, selectedSessionId, newThreadSearch, forgetThreads, dialog, setDialog, toast, setToast, exit } = args;
  const showResult = useCallback((action: ThreadBulkAction, result: ThreadBulkResult) => {
    setToast({
      text: bulkResultMessage(action, result),
      undoIds: action === "archive" ? result.affectedIds : [],
      secondsLeft: UNDO_SECONDS,
    });
  }, [setToast]);

  const confirmDialog = useCallback(async () => {
    if (!dialog || dialog.running) {
      return;
    }
    setDialog({ ...dialog, running: true, error: null });
    try {
      const result = await performThreadBulkAction({
        readJson,
        loadState,
        selection: dialog.selection,
        action: dialog.action,
        selectedSessionId,
        newThreadSearch,
        forgetThreads,
      });
      exit();
      showResult(dialog.action, result);
    } catch (error) {
      const message = error instanceof Error ? error.message : "The action failed";
      setDialog((current) => (current ? { ...current, running: false, error: message } : current));
    }
  }, [dialog, exit, forgetThreads, loadState, newThreadSearch, readJson, selectedSessionId, setDialog, showResult]);

  const archiveOne = useCallback(
    async (thread: ThreadRef) => {
      const result = await performThreadBulkAction({
        readJson,
        loadState,
        selection: toggleThread(EMPTY_THREAD_SELECTION, thread),
        action: "archive",
        selectedSessionId,
        newThreadSearch,
        forgetThreads,
      });
      showResult("archive", result);
    },
    [forgetThreads, loadState, newThreadSearch, readJson, selectedSessionId, showResult],
  );

  const { undo, restore, dismissToast } = useThreadBulkRestore(readJson, loadState, toast, setToast, showResult);
  return { confirmDialog, archiveOne, undo, restore, dismissToast };
}

function useThreadBulkRestore(
  readJson: ThreadBulkArgs["readJson"],
  loadState: ThreadBulkArgs["loadState"],
  toast: ThreadBulkToast | null,
  setToast: Setter<ThreadBulkToast | null>,
  showResult: (action: ThreadBulkAction, result: ThreadBulkResult) => void,
) {
  const undo = useCallback(async () => {
    const ids = toast?.undoIds ?? [];
    setToast(null);
    if (!ids.length) {
      return;
    }
    const result = await restoreThreads({ readJson, loadState, ids });
    showResult("restore", result);
  }, [loadState, readJson, setToast, showResult, toast]);

  /** Restore from the archived view: one request, the list reloads once, the result is reported. */
  const restore = useCallback(
    async (ids: string[]) => {
      const result = await restoreThreads({ readJson, loadState, ids });
      showResult("restore", result);
      return result;
    },
    [loadState, readJson, showResult],
  );

  const dismissToast = useCallback(() => setToast(null), [setToast]);
  return { undo, restore, dismissToast };
}

// Esc closes the innermost layer: the dialog, then bulk mode.
export function useThreadBulkEscape(
  bulkMode: boolean,
  dialog: ThreadBulkDialog | null,
  setDialog: Setter<ThreadBulkDialog | null>,
  exit: () => void,
) {
  useEffect(() => {
    if (!bulkMode && !dialog) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      if (dialog) {
        if (!dialog.running) {
          setDialog(null);
        }
        return;
      }
      exit();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [bulkMode, dialog, exit, setDialog]);
}
