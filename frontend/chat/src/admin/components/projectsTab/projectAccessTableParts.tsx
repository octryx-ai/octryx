// Shared parts of the Workspace access tables: the card around a table, the Remove button and the row props.
import type { ReactNode } from "react";

type AccessCardProps = {
  title: string;
  badge: string;
  description: string;
  addLabel: string;
  onAdd: () => void;
  children: ReactNode;
};

export function AccessCard({ title, badge, description, addLabel, onAdd, children }: AccessCardProps) {
  return (
    <section className="project-access__card">
      <div className="project-access__card-header">
        <div>
          <div className="project-access__card-title">
            <strong>{title}</strong>
            <span className="admin-panel__badge admin-panel__badge--inactive">{badge}</span>
          </div>
          <p className="admin-panel__hint">{description}</p>
        </div>
        <button type="button" className="admin-panel__action-btn" onClick={onAdd}>
          {addLabel}
        </button>
      </div>
      <div className="admin-panel__table-wrap">{children}</div>
    </section>
  );
}

export function RemoveButton({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className="admin-panel__danger-btn"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
    >
      Remove
    </button>
  );
}

export type RowsProps<T> = {
  rows: T[];
  onUpdate: (key: string, patch: Partial<T>) => void;
  onRemove: (key: string) => void;
  onAdd: () => void;
};
