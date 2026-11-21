import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import "./settingsDrawer.css";

// Right-side drawer (design guide 9.11): slides in from the right over a
// backdrop, is a labelled modal dialog, and closes on Escape or a backdrop
// click. "edit" = 28rem create/edit form, "detail" = 38rem read view,
// "workspace" = the wide workspace settings drawer with its own section nav.
type SettingsDrawerProps = {
  eyebrow: string;
  title: string;
  size: "edit" | "detail" | "workspace";
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  headerActions?: ReactNode;
};

// The dialog's focus and Escape: it takes the focus when it opens, closes on Escape, and gives the focus back to what
// had it when it closes.
function useDrawerDialog(onClose: () => void) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Captured during the first render, before any autoFocus inside the drawer.
  const [returnFocusTo] = useState(() =>
    typeof document === "undefined" ? null : (document.activeElement as HTMLElement | null),
  );

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.contains(document.activeElement)) {
      dialog.focus();
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        onCloseRef.current();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusTo?.focus?.();
    };
  }, [returnFocusTo]);

  return dialogRef;
}

export function SettingsDrawer({
  eyebrow,
  title,
  size,
  onClose,
  children,
  footer,
  headerActions,
}: SettingsDrawerProps) {
  const titleId = useId();
  const dialogRef = useDrawerDialog(onClose);

  return (
    <div
      className="settings-drawer__backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className={`settings-drawer settings-drawer--${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className="settings-drawer__header">
          <div className="settings-drawer__heading">
            <p className="settings-drawer__eyebrow">{eyebrow}</p>
            <h2 id={titleId} className="settings-drawer__title">
              {title}
            </h2>
          </div>
          <div className="settings-drawer__header-actions">
            {headerActions}
            <button
              type="button"
              className="settings-drawer__close"
              onClick={onClose}
              aria-label="Close"
            >
              <svg viewBox="0 0 20 20" aria-hidden="true" width="14" height="14">
                <path d="M5 5L15 15M15 5L5 15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </header>
        <div className="settings-drawer__body">{children}</div>
        {footer ? <footer className="settings-drawer__footer">{footer}</footer> : null}
      </div>
    </div>
  );
}
