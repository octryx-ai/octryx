import { useState, type FormEvent } from "react";

import { AdminIdentityGroupRlsEditor } from "./AdminIdentityGroupRlsEditor";
import type { AdminIdentityGroupRow } from "./identityTypes";
import { formatDate } from "../../utils/dateTime";

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    >
      <path d="M5 5 15 15M15 5 5 15" />
    </svg>
  );
}

type AdminGroupEditPanelProps = {
  group: AdminIdentityGroupRow;
  groupLoading: string | null;
  onClose: () => void;
  onUpdateGroup: (
    group: AdminIdentityGroupRow,
    payload: {
      description?: string;
      rls_attributes?: Array<{ key: string; value: string }>;
    },
  ) => void;
  onToggleGroup: (group: AdminIdentityGroupRow) => void;
  onDeleteGroup: (group: AdminIdentityGroupRow) => void;
};


// The group's facts: members, status, data access attributes and creation date.
function GroupInfoSection({ group }: { group: AdminIdentityGroupRow }) {
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">Info</p>
      <div className="role-edit-panel__info-grid">
        <div className="role-edit-panel__info-item">
          <span className="role-edit-panel__info-key">Members</span>
          <span className="role-edit-panel__info-val">
            {group.member_count}
          </span>
        </div>
        <div className="role-edit-panel__info-item">
          <span className="role-edit-panel__info-key">Status</span>
          <span
            className={`admin-panel__badge ${group.is_active ? "admin-panel__badge--active" : "admin-panel__badge--inactive"}`}
          >
            {group.is_active ? "Active" : "Inactive"}
          </span>
        </div>
        <div className="role-edit-panel__info-item">
          <span className="role-edit-panel__info-key">
            Data access attributes
          </span>
          <span className="role-edit-panel__info-val">
            {group.rls_attributes.length}
          </span>
        </div>
        <div className="role-edit-panel__info-item">
          <span className="role-edit-panel__info-key">Created</span>
          <span className="role-edit-panel__info-val">
            {group.created_at
              ? formatDate(group.created_at)
              : "—"}
          </span>
        </div>
      </div>
    </section>
  );
}

// Deactivate / reactivate, and delete (only a group without members).
function GroupStatusActions({ group, groupLoading, onToggleGroup, onDeleteGroup }: Pick<AdminGroupEditPanelProps, "group" | "groupLoading" | "onToggleGroup" | "onDeleteGroup">) {
  return (
    <>
      <section className="user-edit-panel__section">
        <div className="user-edit-panel__row">
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => onToggleGroup(group)}
            disabled={groupLoading === `toggle:${group.id}`}
          >
            {groupLoading === `toggle:${group.id}`
              ? "Saving…"
              : group.is_active
                ? "Deactivate"
                : "Reactivate"}
          </button>
        </div>
      </section>

      <section className="user-edit-panel__section">
        <p className="user-edit-panel__section-label">Danger zone</p>
        {group.member_count > 0 ? (
          <p className="admin-panel__hint">
            This group has {group.member_count} member
            {group.member_count === 1 ? "" : "s"} and cannot be deleted.
            Remove all members first.
          </p>
        ) : (
          <button
            type="button"
            className="admin-panel__danger-btn"
            onClick={() => onDeleteGroup(group)}
            disabled={groupLoading === `delete:${group.id}`}
          >
            {groupLoading === `delete:${group.id}`
              ? "Deleting…"
              : "Delete group"}
          </button>
        )}
      </section>
    </>
  );
}

// The description with its own Save; the typed text lives in the panel.
function GroupDescriptionSection({ group, groupLoading, description, setDescription, onUpdateGroup }: Pick<AdminGroupEditPanelProps, "group" | "groupLoading" | "onUpdateGroup"> & {
  description: string;
  setDescription: (value: string) => void;
}) {
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">Description</p>
      <div className="user-edit-panel__row">
        <input
          className="user-edit-panel__select"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What is this group for?"
        />
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => onUpdateGroup(group, { description })}
          disabled={groupLoading === `update:${group.id}`}
        >
          {groupLoading === `update:${group.id}` ? "Saving…" : "Save"}
        </button>
      </div>
    </section>
  );
}

export function AdminGroupEditPanel({
  group,
  groupLoading,
  onClose,
  onUpdateGroup,
  onToggleGroup,
  onDeleteGroup,
}: AdminGroupEditPanelProps) {
  const [description, setDescription] = useState(group.description ?? "");

  return (
    <div
      className="user-edit-panel__backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside className="user-edit-panel">
        <div className="user-edit-panel__header">
          <div>
            <p className="user-edit-panel__header-label">Edit group</p>
            <h2 className="user-edit-panel__header-name">{group.name}</h2>
          </div>
          <button
            type="button"
            className="user-edit-panel__close"
            onClick={onClose}
            aria-label="Close"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="user-edit-panel__body">
          <GroupInfoSection group={group} />

          <GroupDescriptionSection group={group} groupLoading={groupLoading} description={description} setDescription={setDescription}
            onUpdateGroup={onUpdateGroup} />

          <section className="user-edit-panel__section">
            <p className="user-edit-panel__section-label">Data access attributes</p>
            <AdminIdentityGroupRlsEditor
              group={group}
              loading={groupLoading === `rls:${group.id}`}
              onSave={(attributes) =>
                onUpdateGroup(group, { rls_attributes: attributes })
              }
            />
          </section>

          <GroupStatusActions group={group} groupLoading={groupLoading} onToggleGroup={onToggleGroup} onDeleteGroup={onDeleteGroup} />
        </div>
      </aside>
    </div>
  );
}
