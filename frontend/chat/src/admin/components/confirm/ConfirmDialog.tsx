import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import "./confirmDialog.css";

// The one confirm dialog for destructive admin actions: replaces window.confirm. A dialog
// can ask the user to type a name (removal of something other things may depend on) and shows the server's
// refusal in place instead of an alert().
type ConfirmDialogProps = {
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  tone?: "danger" | "neutral";
  // When set, the confirm button stays disabled until this text is typed (case-insensitive).
  typeToConfirm?: string;
  busy?: boolean;
  error?: string | null;
  confirmDisabled?: boolean;
  onConfirm: (typed: string) => void;
  onCancel: () => void;
};

export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  tone = "danger",
  typeToConfirm,
  busy = false,
  error = null,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const [typed, setTyped] = useState("");
  const typedOk = !typeToConfirm || typed.trim().toLowerCase() === typeToConfirm.trim().toLowerCase();

  // The latest onCancel without re-running the effect: callers pass a new function on every render, and a
  // re-run focused the dialog again after each keystroke, so a reason field kept only its first character.
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;

  // Focus once when the dialog opens; Escape cancels.
  useEffect(() => {
    dialogRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        cancelRef.current();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="confirm-dialog__backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}>
      <div ref={dialogRef} className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <h2 id={titleId} className="confirm-dialog__title">{title}</h2>
        {children ? <div className="confirm-dialog__body">{children}</div> : null}
        {typeToConfirm ? (
          <label className="admin-panel__field">
            <span>Type <b>{typeToConfirm}</b> to confirm</span>
            <input className="admin-panel__input" value={typed} autoComplete="off"
              onChange={(event) => setTyped(event.target.value)} />
          </label>
        ) : null}
        {error ? <p className="confirm-dialog__error" role="alert">{error}</p> : null}
        <div className="confirm-dialog__actions">
          <button type="button" className="admin-panel__action-btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button"
            className={tone === "danger" ? "admin-panel__danger-btn" : "admin-panel__action-btn admin-panel__action-btn--primary"}
            disabled={busy || !typedOk || confirmDisabled} onClick={() => onConfirm(typed)}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
