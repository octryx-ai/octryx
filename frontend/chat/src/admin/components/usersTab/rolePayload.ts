import type { AdminRoleRow } from "./identityTypes";

export function normalizeRoleRow(role: AdminRoleRow): AdminRoleRow {
  return {
    ...role,
    permissions: Array.isArray(role.permissions) ? role.permissions : [],
    assigned_users: Array.isArray(role.assigned_users)
      ? role.assigned_users
      : [],
  };
}
