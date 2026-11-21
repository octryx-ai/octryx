import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import "./codingGovernance.css";

// Shared building blocks for the Coding governance editors: right-side edit
// drawer (design guide 9.11), collapsed "Advanced (JSON)" group with inline
// validation, labelled fields with helper text, catalog empty state, KPI tiles.

export function GovernanceDrawer({
  eyebrow,
  title,
  submitLabel,
  saving,
  savingLabel = "Saving...",
  error,
  dirty = false,
  extraActions,
  onSubmit,
  onClose,
  children,
}: {
  eyebrow: string;
  title: string;
  submitLabel: string;
  saving: boolean;
  savingLabel?: string;
  error: string | null;
  dirty?: boolean;
  extraActions?: ReactNode;
  onSubmit: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  const requestClose = () => {
    if (!dirty || window.confirm("Discard unsaved changes?")) onClose();
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <div
      className="user-edit-panel__backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(event) => {
        if (event.target === event.currentTarget) requestClose();
      }}
    >
      <aside className="user-edit-panel coding-gov-drawer">
        <div className="user-edit-panel__header">
          <div>
            <p className="user-edit-panel__header-label">{eyebrow}</p>
            <h2 className="user-edit-panel__header-name">{title}</h2>
          </div>
          <button type="button" className="user-edit-panel__close" onClick={requestClose} aria-label="Close">
            <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor"
              strokeWidth="1.8" strokeLinecap="round"><path d="M5 5l10 10M15 5L5 15" /></svg>
          </button>
        </div>
        <form className="coding-gov-drawer__form" onSubmit={submit} noValidate>
          <div className="user-edit-panel__body coding-gov-drawer__body">{children}</div>
          <div className="coding-gov-drawer__footer">
            {error ? <div className="work-area__error" role="alert">{error}</div> : null}
            <div className="coding-gov-drawer__actions">
              <button type="button" className="work-area__button" onClick={requestClose}>
                Cancel
              </button>
              {extraActions}
              <button type="submit" className="work-area__button work-area__button--primary" disabled={saving}>
                {saving ? savingLabel : submitLabel}
              </button>
            </div>
          </div>
        </form>
      </aside>
    </div>
  );
}

export function DrawerSection({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="user-edit-panel__section coding-gov-section">
      {title ? <p className="user-edit-panel__section-label">{title}</p> : null}
      {children}
    </section>
  );
}

export function AdvancedJson({ hasError, intro, children }: { hasError: boolean; intro: string; children: ReactNode }) {
  const [open, setOpen] = useState(hasError);
  useEffect(() => {
    if (hasError) setOpen(true);
  }, [hasError]);
  return (
    <details className="coding-gov-advanced" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        Advanced (JSON){hasError ? <span className="coding-gov-advanced__flag">Needs a fix</span> : null}
      </summary>
      <p className="coding-gov-help">{intro}</p>
      {children}
    </details>
  );
}

export function CatalogEmpty({ eyebrow, title, body, actionLabel, onAction }: {
  eyebrow: string;
  title: string;
  body: string;
  actionLabel: string;
  onAction: () => void;
}) {
  return (
    <div className="work-empty">
      <div className="work-empty__eyebrow">{eyebrow}</div>
      <h2>{title}</h2>
      <p>{body}</p>
      <button type="button" className="work-area__button work-area__button--primary" onClick={onAction}>
        {actionLabel}
      </button>
    </div>
  );
}

export function CatalogHeader({ eyebrow, title, intro, children }: {
  eyebrow: string;
  title: string;
  intro: string;
  children?: ReactNode;
}) {
  return (
    <header className="coding-gov-header">
      <div>
        <div className="work-area__eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
        <p className="coding-gov-intro">{intro}</p>
      </div>
      {children ? <div className="coding-gov-header__actions">{children}</div> : null}
    </header>
  );
}

export function GovernanceMetrics({ tiles }: { tiles: Array<{ label: string; value: number; meta: string }> }) {
  return (
    <div className="work-area__summary coding-area__summary">
      {tiles.map((tile) => (
        <div key={tile.label} className="work-area__metric">
          <span>{tile.label}</span>
          <strong>{tile.value}</strong>
          <small>{tile.meta}</small>
        </div>
      ))}
    </div>
  );
}

export function DisabledReason({ reason }: { reason: string | null }) {
  return reason ? <small className="coding-gov-help coding-gov-reason">{reason}</small> : null;
}
