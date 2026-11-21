import type { FormEvent } from "react";

import { AdminHeaderActions } from "../AdminHeaderSlot";
import { AdminIdentityRoleCatalog } from "./AdminIdentityRoleCatalog";
import { AdminRoleEditPanel } from "./AdminRoleEditPanel";
import { IdentityCreatePanel } from "./IdentityCreatePanel";

import "./identityPages.css";
import type { AdminRolePermission, AdminRoleRow } from "./identityTypes";

type AdminRolesPanelProps = {
  roles: AdminRoleRow[];
  permissionCatalog: AdminRolePermission[];
  roleName: string;
  roleDescription: string;
  roleLoading: string | null;
  roleError: string | null;
  editingRole: AdminRoleRow | null;
  showCreateRole: boolean;
  setRoleName: (value: string) => void;
  setRoleDescription: (value: string) => void;
  setShowCreateRole: (value: boolean | ((value: boolean) => boolean)) => void;
  onCreateRole: (event: FormEvent) => void;
  onLoadRoles: () => void;
  onEditRole: (role: AdminRoleRow) => void;
  onCloseEditPanel: () => void;
  onDeleteRole: (role: AdminRoleRow) => void;
  onUpdateRoleDescription: (role: AdminRoleRow, description: string) => void;
  onUpdateRolePermissions: (
    role: AdminRoleRow,
    permissions: AdminRolePermission[],
  ) => void;
};

export function AdminRolesPanel({
  roles,
  permissionCatalog,
  roleName,
  roleDescription,
  roleLoading,
  roleError,
  editingRole,
  showCreateRole,
  setRoleName,
  setRoleDescription,
  setShowCreateRole,
  onCreateRole,
  onLoadRoles,
  onEditRole,
  onCloseEditPanel,
  onDeleteRole,
  onUpdateRoleDescription,
  onUpdateRolePermissions,
}: AdminRolesPanelProps) {
  return (
    <div className="admin-users">
      <AdminHeaderActions>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => setShowCreateRole(true)}
          data-testid="role-create-open"
        >
          + New role
        </button>
      </AdminHeaderActions>
      <div className="admin-panel__section-header">
        <span>Role catalog ({roles.length})</span>
      </div>

      {roleError && !showCreateRole ? <div className="admin-panel__error">{roleError}</div> : null}

      {showCreateRole ? (
        <IdentityCreatePanel title="New role" section="Role" formId="admin-role-create-form" submitLabel="Create role"
          busyLabel="Creating…" busy={roleLoading === "create"} error={roleError} onSubmit={onCreateRole}
          onClose={() => setShowCreateRole(false)} testId="role-create-panel">
          <RoleCreateFields roleName={roleName} roleDescription={roleDescription} setRoleName={setRoleName}
            setRoleDescription={setRoleDescription} />
        </IdentityCreatePanel>
      ) : null}

      <AdminIdentityRoleCatalog roles={roles} onEditRole={onEditRole} />

      {editingRole ? (
        <RoleEditor role={editingRole} permissionCatalog={permissionCatalog} roleLoading={roleLoading} onCloseEditPanel={onCloseEditPanel}
          onDeleteRole={onDeleteRole} onUpdateRoleDescription={onUpdateRoleDescription} onUpdateRolePermissions={onUpdateRolePermissions} />
      ) : null}
    </div>
  );
}

// The new role's name (lowercase key) and its one-line description.
function RoleCreateFields({ roleName, roleDescription, setRoleName, setRoleDescription }: {
  roleName: string;
  roleDescription: string;
  setRoleName: (value: string) => void;
  setRoleDescription: (value: string) => void;
}) {
  return (
    <>
      <label className="admin-panel__field">
        <span>
          Role name <span className="admin-users__form-required" aria-hidden="true">*</span>
        </span>
        <input
          value={roleName}
          onChange={(e) => setRoleName(e.target.value)}
          required
          pattern="[a-z0-9_\-]+"
          title="Lowercase letters, digits, hyphens and underscores only"
        />
        <span className="admin-users__form-help">
          Lowercase letters, digits, hyphens and underscores.
        </span>
      </label>
      <label className="admin-panel__field">
        <span>Description</span>
        <input
          value={roleDescription}
          onChange={(e) => setRoleDescription(e.target.value)}
        />
        <span className="admin-users__form-help">
          One line on what this role allows.
        </span>
      </label>
    </>
  );
}

// The open role's edit panel; deleting the role also closes it.
function RoleEditor({ role, permissionCatalog, roleLoading, onCloseEditPanel, onDeleteRole, onUpdateRoleDescription, onUpdateRolePermissions }: {
  role: AdminRoleRow;
  permissionCatalog: AdminRolePermission[];
  roleLoading: string | null;
  onCloseEditPanel: () => void;
  onDeleteRole: (role: AdminRoleRow) => void;
  onUpdateRoleDescription: AdminRolesPanelProps["onUpdateRoleDescription"];
  onUpdateRolePermissions: AdminRolesPanelProps["onUpdateRolePermissions"];
}) {
  return (
    <AdminRoleEditPanel
      role={role}
      permissionCatalog={permissionCatalog}
      roleLoading={roleLoading}
      onClose={onCloseEditPanel}
      onSaveDescription={(role, desc) =>
        onUpdateRoleDescription(role, desc)
      }
      onSavePermissions={(role, perms) =>
        onUpdateRolePermissions(role, perms)
      }
      onDelete={(role) => {
        onDeleteRole(role);
        onCloseEditPanel();
      }}
    />
  );
}
