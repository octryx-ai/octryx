// Info, description and danger-zone sections of the role editor side panel.
import type { ReactNode } from "react";

import type { AdminRoleRow } from "./identityTypes";

type RoleSectionProps = { role: AdminRoleRow; roleLoading: string | null };

function RoleInfoItem({ label, children, valueClass }: { label: string; children: ReactNode; valueClass: string }) {
  return (
    <div className="role-edit-panel__info-item">
      <span className="role-edit-panel__info-key">{label}</span>
      <span className={valueClass}>{children}</span>
    </div>
  );
}

export function RoleInfoSection({ role, permissionCount }: { role: AdminRoleRow; permissionCount: number }) {
  const assignedUsers = Array.isArray(role.assigned_users) ? role.assigned_users : [];
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">Info</p>
      <div className="role-edit-panel__info-grid">
        <RoleInfoItem label="Type" valueClass={`admin-panel__badge${role.is_core ? "" : " admin-panel__badge--active"}`}>
          {role.is_core ? "core" : "custom"}
        </RoleInfoItem>
        <RoleInfoItem label="Assigned users" valueClass="role-edit-panel__info-val">{role.user_count}</RoleInfoItem>
        <RoleInfoItem label="Active permissions" valueClass="role-edit-panel__info-val">{permissionCount}</RoleInfoItem>
      </div>
      {assignedUsers.length > 0 && (
        <div className="role-edit-panel__users">
          <p className="user-edit-panel__section-label" style={{ marginBottom: "0.45rem" }}>
            Assigned users
          </p>
          {assignedUsers.map((u) => (
            <div key={u.id} className="role-edit-panel__user-row">
              <strong>{u.username}</strong>
              <span>{u.email}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function RoleDescriptionSection({ role, roleLoading, onSaveDescription }: RoleSectionProps & {
  onSaveDescription: (role: AdminRoleRow, description: string) => void;
}) {
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">Description</p>
      <div className="user-edit-panel__row">
        <input
          className="user-edit-panel__select"
          defaultValue={role.description}
          placeholder="Short description of this role's purpose"
          onBlur={(e) => onSaveDescription(role, e.target.value)}
          key={role.id}
        />
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={(e) => {
            const input = e.currentTarget.previousElementSibling as HTMLInputElement;
            onSaveDescription(role, input.value);
          }}
          disabled={roleLoading === `update:${role.id}`}
        >
          {roleLoading === `update:${role.id}` ? "Saving…" : "Save"}
        </button>
      </div>
    </section>
  );
}

export function RoleDangerZone({ role, roleLoading, onDelete }: RoleSectionProps & { onDelete: (role: AdminRoleRow) => void }) {
  const canDelete = !role.is_core && role.user_count === 0;
  return (
    <section className="user-edit-panel__section">
      <p className="user-edit-panel__section-label">Danger zone</p>
      {role.user_count > 0 ? (
        <p className="admin-panel__hint">
          This role has {role.user_count} assigned user
          {role.user_count === 1 ? "" : "s"} and cannot be deleted.
          Remove all assignments first.
        </p>
      ) : (
        <button
          type="button"
          className="admin-panel__danger-btn"
          onClick={() => onDelete(role)}
          disabled={!canDelete || roleLoading === `delete:${role.id}`}
        >
          {roleLoading === `delete:${role.id}` ? "Deleting…" : "Delete role"}
        </button>
      )}
    </section>
  );
}
