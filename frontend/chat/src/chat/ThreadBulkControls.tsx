import { createPortal } from "react-dom";

import type { ThreadGroup } from "../chatThreadTypes";
import { ArchiveIcon, TrashIcon } from "./ChatShellIcons";
import { ThreadBulkDialogView } from "./threadBulkDialog";
import { plural } from "./threadBulkText";
import { CloseIcon, UndoIcon } from "./threadSidebarIcons";
import type { ThreadBulkController } from "./useThreadBulk";

/** Bulk-mode replacement of the "Chats" heading: exit, live count, hint, Clear. */
export function ThreadBulkHeader({
  threadBulk,
  visibleIds,
}: {
  threadBulk: ThreadBulkController;
  visibleIds: string[];
}) {
  const count = threadBulk.selectedCount;
  const visible = new Set(visibleIds);
  const hiddenBySearch = threadBulk.query
    ? Object.keys(threadBulk.selection.ids).filter((id) => !visible.has(id)).length
    : 0;
  return (
    <div className="sidebar__bulk-head">
      <button
        type="button"
        className="icon-button sidebar__icon-btn"
        aria-label="Exit selection (Esc)"
        title="Exit selection (Esc)"
        onClick={threadBulk.exit}
      >
        <CloseIcon />
      </button>
      <div className="sidebar__bulk-count" aria-live="polite">
        {count ? plural(count, "chat selected", "chats selected") : "Select chats"}
        <small>
          {hiddenBySearch
            ? `${hiddenBySearch} of them hidden by the search`
            : count
              ? "Shift-click selects a range"
              : "Click rows to select · Shift-click for a range"}
        </small>
      </div>
      {count ? (
        <button type="button" className="admin-panel__action-btn" onClick={threadBulk.clear}>
          Clear
        </button>
      ) : null}
    </div>
  );
}

/** Unloaded chats covered by the selected (search-free) scopes. */
function notLoadedCount(threadBulk: ThreadBulkController, groups: ThreadGroup[]) {
  return Object.values(threadBulk.selection.scopes).reduce((total, scope) => {
    if (scope.query) {
      return total;
    }
    const group = groups.find((candidate) => (candidate.projectId ?? "") === scope.projectId);
    return total + Math.max(0, scope.count - (group?.sessions.length ?? 0));
  }, 0);
}

export function ThreadBulkActionBar({
  threadBulk,
  groups,
}: {
  threadBulk: ThreadBulkController;
  groups: ThreadGroup[];
}) {
  const count = threadBulk.selectedCount;
  return (
    <div className="sidebar__bulk-bar" role="toolbar" aria-label="Selected chats">
      <button
        type="button"
        className="admin-panel__action-btn"
        disabled={!count}
        onClick={() => void threadBulk.openDialog("archive", notLoadedCount(threadBulk, groups))}
      >
        <ArchiveIcon />
        {count ? `Archive ${count}` : "Archive"}
      </button>
      {threadBulk.canDeleteThreads ? (
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--danger"
          disabled={!count}
          onClick={() => void threadBulk.openDialog("delete", notLoadedCount(threadBulk, groups))}
        >
          <TrashIcon />
          Delete
        </button>
      ) : null}
      <span className="sidebar__bulk-spacer" />
      <span className="sidebar__bulk-hint">Esc to exit</span>
    </div>
  );
}

export function ThreadBulkOverlays({ threadBulk }: { threadBulk: ThreadBulkController }) {
  const toast = threadBulk.toast;
  // Portalled: the sidebar clips its content, the dialog and the toast belong to the page.
  return createPortal(
    <>
      <ThreadBulkDialogView threadBulk={threadBulk} />
      {toast ? (
        <div className="thread-bulk-toast" role="status">
          <span>{toast.text}</span>
          {toast.undoIds.length ? (
            <>
              {/* Focus goes to Undo: the dialog that had it is gone, and Undo is the next likely step. */}
              <button
                type="button"
                className="admin-panel__action-btn"
                autoFocus
                onClick={() => void threadBulk.undo()}
              >
                <UndoIcon />
                Undo
              </button>
              <span className="thread-bulk-toast__timer">{toast.secondsLeft}s</span>
            </>
          ) : null}
        </div>
      ) : null}
    </>,
    document.body,
  );
}
