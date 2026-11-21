import { roleDescription, rolePermissionsLabel } from "./identityPresentation";
import type { AdminRoleRow } from "./identityTypes";

function EditIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 13.75V16h2.25L14.9 7.35l-2.25-2.25L4 13.75Z" />
    </svg>
  );
}

type AdminIdentityRoleCatalogProps = {
  roles: AdminRoleRow[];
  onEditRole: (role: AdminRoleRow) => void;
};

export function AdminIdentityRoleCatalog({
  roles,
  onEditRole,
}: AdminIdentityRoleCatalogProps) {
  return (
    <table className="admin-panel__table admin-users__role-table">
      <thead>
        <tr>
          <th>Role</th>
          <th>Description</th>
          <th>Users</th>
          <th>Permissions</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {roles.map((role) => {
          const description = roleDescription(role);
          return (
            <tr key={role.id}>
              <td>
                <div className="role-catalog__name-cell">
                  <strong>{role.name}</strong>
                  <span
                    className={`admin-panel__badge${role.is_core ? " admin-panel__badge--inactive" : " admin-panel__badge--active"}`}
                  >
                    {role.is_core ? "Built-in" : "Custom"}
                  </span>
                </div>
              </td>
              <td className="admin-panel__cell--muted">
                {description || "No description"}
              </td>
              <td className="admin-panel__cell--muted">
                {role.user_count} user{role.user_count === 1 ? "" : "s"}
              </td>
              <td className="admin-panel__cell--muted">
                {rolePermissionsLabel(role)}
              </td>
              <td>
                <button
                  type="button"
                  className="admin-users__row-btn"
                  title={`Edit role ${role.name}`}
                  aria-label={`Edit role ${role.name}`}
                  onClick={() => onEditRole(role)}
                >
                  <EditIcon />
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
