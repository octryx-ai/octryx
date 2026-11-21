// The confirm dialog of a bulk Archive or Delete: the breakdown per Workspace, the notes that matter and the buttons.
import { useEffect, useRef, type KeyboardEvent, type RefObject } from "react";

import type { ThreadBulkResult } from "./threadBulkActions";
import { plural } from "./threadBulkText";
import type { ThreadBulkDialog } from "./threadBulkTypes";
import { InfoIcon, UndoIcon, WarnIcon } from "./threadSidebarIcons";
import type { ThreadBulkController } from "./useThreadBulk";

function Note({ tone, icon, children }: { tone?: "warn" | "danger"; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className={`thread-bulk-dialog__note ${tone ? `thread-bulk-dialog__note--${tone}` : ""}`}>
      {icon}
      <span>{children}</span>
    </div>
  );
}

// Tab and Shift-Tab stay inside the dialog.
function trapFocus(event: KeyboardEvent<HTMLDivElement>) {
  if (event.key !== "Tab") {
    return;
  }
  const focusable = Array.from(
    event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"),
  );
  if (!focusable.length) {
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function PreviewNotes({ dialog, preview, isDelete }: { dialog: ThreadBulkDialog; preview: ThreadBulkResult; isDelete: boolean }) {
  return (
    <>
      {dialog.notLoaded ? (
        <Note icon={<InfoIcon />}>
          {dialog.notLoaded} of them are not loaded in the list. The server resolves the selection as
          of the moment you chose “Select all”; chats created later are not included.
        </Note>
      ) : null}
      {preview.subChats ? (
        <Note icon={<InfoIcon />}>
          Includes {plural(preview.subChats, "sub-chat", "sub-chats")};{" "}
          {preview.subChats === 1 ? "it goes with its" : "they go with their"} parent.
        </Note>
      ) : null}
      {preview.running ? (
        <Note tone="warn" icon={<WarnIcon />}>
          {plural(preview.running, "running chat is", "running chats are")}{" "}
          {isDelete
            ? "stopped before deletion."
            : `skipped. Stop ${preview.running === 1 ? "it" : "them"} first to archive.`}
        </Note>
      ) : null}
      {isDelete ? (
        <Note tone="danger" icon={<WarnIcon />}>
          Deleting removes messages, files and traces. This cannot be undone. Audit records stay.
        </Note>
      ) : (
        <Note icon={<UndoIcon />}>
          You can undo right after, and restore archived chats any time from “Archived chats”.
        </Note>
      )}
    </>
  );
}

function DialogBody({ dialog, isDelete, total }: { dialog: ThreadBulkDialog; isDelete: boolean; total: number }) {
  const preview = dialog.preview;
  return (
    <div className="thread-bulk-dialog__body" id="thread-bulk-dialog-body">
      {preview ? (
        <>
          <div className="thread-bulk-dialog__breakdown">
            {preview.byProject.map((row) => (
              <div key={row.projectId || "none"}>
                <span>{row.projectName}</span>
                <span>{row.count}</span>
              </div>
            ))}
            <div>
              <span>Total</span>
              <span>{total}</span>
            </div>
          </div>
          <PreviewNotes dialog={dialog} preview={preview} isDelete={isDelete} />
        </>
      ) : dialog.error ? null : (
        <p className="thread-bulk-dialog__pending">Checking the selection…</p>
      )}
      {dialog.error ? (
        <Note tone="danger" icon={<WarnIcon />}>
          {dialog.error}
        </Note>
      ) : null}
    </div>
  );
}

function DialogFooter({ threadBulk, dialog, verb, affected, isDelete, cancelRef, confirmRef }: {
  threadBulk: ThreadBulkController;
  dialog: ThreadBulkDialog;
  verb: string;
  affected: number;
  isDelete: boolean;
  cancelRef: RefObject<HTMLButtonElement>;
  confirmRef: RefObject<HTMLButtonElement>;
}) {
  return (
    <footer>
      <button
        ref={cancelRef}
        type="button"
        className="admin-panel__action-btn"
        disabled={dialog.running}
        onClick={threadBulk.closeDialog}
      >
        Cancel
      </button>
      <button
        ref={confirmRef}
        type="button"
        className={`admin-panel__action-btn ${isDelete ? "admin-panel__action-btn--danger-solid" : "admin-panel__action-btn--primary"}`}
        disabled={!dialog.preview || !affected || dialog.running}
        onClick={() => void threadBulk.confirmDialog()}
      >
        {dialog.running ? `${verb === "Delete" ? "Deleting" : "Archiving"}…` : `${verb} ${plural(affected, "chat", "chats")}`}
      </button>
    </footer>
  );
}

export function ThreadBulkDialogView({ threadBulk }: { threadBulk: ThreadBulkController }) {
  const dialog = threadBulk.dialog;
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const isDelete = dialog?.action === "delete";
  const ready = Boolean(dialog?.preview);

  useEffect(() => {
    // Delete starts on the safe button; Archive on the confirm button once the numbers are in.
    (isDelete || !ready ? cancelRef : confirmRef).current?.focus();
  }, [isDelete, ready]);

  if (!dialog) {
    return null;
  }
  const preview = dialog.preview;
  const verb = isDelete ? "Delete" : "Archive";
  const total = preview ? preview.byProject.reduce((sum, row) => sum + row.count, 0) : 0;
  const affected = preview?.affectedIds.length ?? 0;
  return (
    <div
      className="thread-bulk-dialog__backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget && !dialog.running) {
          threadBulk.closeDialog();
        }
      }}
    >
      <div
        className="thread-bulk-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="thread-bulk-dialog-title"
        aria-describedby="thread-bulk-dialog-body"
        onKeyDown={trapFocus}
      >
        <header>
          <h2 id="thread-bulk-dialog-title">
            {preview ? `${verb} ${plural(total, "chat", "chats")}?` : `${verb} chats?`}
          </h2>
        </header>
        <DialogBody dialog={dialog} isDelete={isDelete} total={total} />
        <DialogFooter threadBulk={threadBulk} dialog={dialog} verb={verb} affected={affected} isDelete={isDelete}
          cancelRef={cancelRef} confirmRef={confirmRef} />
      </div>
    </div>
  );
}
