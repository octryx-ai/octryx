import { selectedThreadCount } from "./threadSelection";
import type { ThreadBulkArgs } from "./threadBulkTypes";
import { useThreadBulkDialogOpen, useThreadBulkSelection, useThreadBulkState } from "./threadBulkHooks";
import { useThreadBulkEscape, useThreadBulkResults } from "./threadBulkResultHooks";

export function useThreadBulk({
  readJson,
  loadState,
  canDeleteThreads,
  threadSearchQuery,
  selectedSessionId,
  newThreadSearch,
  forgetThreads,
}: ThreadBulkArgs) {
  const state = useThreadBulkState(threadSearchQuery);
  const { bulkMode, selection, searchOffers, dialog, setDialog, toast, setToast, query } = state;
  const { enter, exit, clear, toggle, selectAll, groupCheck, selectScope, clearScope } = useThreadBulkSelection(state, readJson);
  const { openDialog, deleteOne, closeDialog } = useThreadBulkDialogOpen(selection, setDialog, { canDeleteThreads, readJson });
  const { confirmDialog, archiveOne, undo, restore, dismissToast } = useThreadBulkResults({
    readJson, loadState, selectedSessionId, newThreadSearch, forgetThreads, dialog, setDialog, toast, setToast, exit,
  });
  useThreadBulkEscape(bulkMode, dialog, setDialog, exit);

  return {
    bulkMode,
    selection,
    selectedCount: selectedThreadCount(selection),
    query,
    searchOffers,
    enter,
    exit,
    clear,
    toggle,
    selectAll,
    groupCheck,
    selectScope,
    clearScope,
    dialog,
    openDialog,
    deleteOne,
    closeDialog,
    confirmDialog,
    toast,
    undo,
    restore,
    dismissToast,
    archiveOne,
    canDeleteThreads,
  };
}

export type ThreadBulkController = ReturnType<typeof useThreadBulk>;
