import type { AdminRolePermission, AdminRoleRow } from "./identityTypes";
import { CloseIcon, ShieldIcon } from "./adminRoleEditIcons";
import { RoleDangerZone, RoleDescriptionSection, RoleInfoSection } from "./adminRoleEditSections";

type AdminRoleEditPanelProps = {
  role: AdminRoleRow;
  permissionCatalog: AdminRolePermission[];
  roleLoading: string | null;
  onClose: () => void;
  onSaveDescription: (role: AdminRoleRow, description: string) => void;
  onSavePermissions: (
    role: AdminRoleRow,
    permissions: AdminRolePermission[],
  ) => void;
  onDelete: (role: AdminRoleRow) => void;
};

type RolePermissionsProps = {
  role: AdminRoleRow;
  permissions: AdminRolePermission[];
  permissionCatalog: AdminRolePermission[];
  roleLoading: string | null;
  onToggle: (permission: AdminRolePermission, checked: boolean) => void;
};

function PermissionChip({ perm, role, permissions, roleLoading, onToggle }: Omit<RolePermissionsProps, "permissionCatalog"> & {
  perm: AdminRolePermission;
}) {
  const checked = permissions.some(
    (p) => p.resource === perm.resource && p.action === perm.action,
  );
  return (
    <label
      className={`role-edit-panel__perm-chip${checked ? " role-edit-panel__perm-chip--on" : ""}${role.is_core ? " role-edit-panel__perm-chip--locked" : ""}`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={role.is_core || roleLoading === `permissions:${role.id}`}
        onChange={(e) => onToggle(perm, e.target.checked)}
      />
      {perm.action}
      {perm.enforced === false ? (
        <span className="admin-policy-chip admin-policy-chip--secondary" title="Can be granted, but no check in the platform reads it yet.">
          Not enforced yet
        </span>
      ) : null}
    </label>
  );
}

function RolePermissionsSection(props: RolePermissionsProps) {
  const { role, permissionCatalog, roleLoading } = props;
  const groupedPermissions = permissionCatalog.reduce<
    Record<string, AdminRolePermission[]>
  >((acc, p) => {
    acc[p.resource] = [...(acc[p.resource] ?? []), p];
    return acc;
  }, {});
  return (
    <section className="user-edit-panel__section">
      <div className="role-edit-panel__perm-header">
        <p className="user-edit-panel__section-label" style={{ margin: 0 }}>
          Permissions
        </p>
        {role.is_core && (
          <span className="role-edit-panel__locked-note">
            <ShieldIcon /> Core role — permissions are protected
          </span>
        )}
      </div>
      {roleLoading === `permissions:${role.id}` && (
        <p className="admin-panel__cell--muted" style={{ fontSize: "var(--ds-text-xs)", marginTop: "0.4rem" }}>
          Saving…
        </p>
      )}
      {permissionCatalog.some((perm) => perm.enforced === false) ? (
        <p className="admin-panel__hint">
          {permissionCatalog.filter((perm) => perm.enforced !== false).length} of {permissionCatalog.length} permissions
          are checked by the platform today; the ones marked <b>Not enforced yet</b> can be granted but have no effect yet.
        </p>
      ) : null}
      <div className="role-edit-panel__perm-groups">
        {Object.entries(groupedPermissions).map(([resource, resourcePerms]) => (
          <div key={resource} className="role-edit-panel__perm-group">
            <p className="role-edit-panel__perm-resource">{resource}</p>
            <div className="role-edit-panel__perm-actions">
              {resourcePerms.map((perm) => <PermissionChip key={`${perm.resource}:${perm.action}`} perm={perm} {...props} />)}
            </div>
          </div>
        ))}
        {permissionCatalog.length === 0 && (
          <p className="admin-panel__cell--muted" style={{ fontSize: "var(--ds-text-sm)" }}>
            No permissions defined in catalog.
          </p>
        )}
      </div>
    </section>
  );
}

export function AdminRoleEditPanel({
  role,
  permissionCatalog,
  roleLoading,
  onClose,
  onSaveDescription,
  onSavePermissions,
  onDelete,
}: AdminRoleEditPanelProps) {
  const permissions = Array.isArray(role.permissions) ? role.permissions : [];

  const togglePermission = (
    permission: AdminRolePermission,
    checked: boolean,
  ) => {
    const next = new Map(
      permissions.map((p) => [`${p.resource}:${p.action}`, p]),
    );
    const key = `${permission.resource}:${permission.action}`;
    if (checked) next.set(key, { resource: permission.resource, action: permission.action });
    else next.delete(key);
    onSavePermissions(
      role,
      Array.from(next.values()).sort((a, b) =>
        `${a.resource}:${a.action}`.localeCompare(`${b.resource}:${b.action}`),
      ),
    );
  };

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
            <p className="user-edit-panel__header-label">
              {role.is_core ? "Core role" : "Custom role"}
            </p>
            <h2 className="user-edit-panel__header-name">{role.name}</h2>
          </div>
          <button type="button" className="user-edit-panel__close" onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>

        <div className="user-edit-panel__body">
          <RoleInfoSection role={role} permissionCount={permissions.length} />
          <RoleDescriptionSection role={role} roleLoading={roleLoading} onSaveDescription={onSaveDescription} />
          <RolePermissionsSection role={role} permissions={permissions} permissionCatalog={permissionCatalog}
            roleLoading={roleLoading} onToggle={togglePermission} />
          {!role.is_core && <RoleDangerZone role={role} roleLoading={roleLoading} onDelete={onDelete} />}
        </div>
      </aside>
    </div>
  );
}
