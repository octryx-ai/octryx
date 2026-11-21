import type { AdminTab } from "../../types/adminPanelTypes.governance";

// Plain-language copy for the identity pages. Role semantics are unchanged:
// the backend treats the role named "admin" as full access by name
// (admin_access_service.is_global_admin); the other core roles only carry the
// permissions seeded in bootstrap.py.
const CORE_ROLE_SUMMARIES: Record<string, string> = {
  admin: "Full platform access (built-in). Permissions below are not needed.",
  operator: "Signs in, manages own API keys and may use operator tools in chat.",
  viewer: "Signs in and manages own API keys; workspace access comes from workspace roles.",
  technical: "Bot or integration account: reads own API keys, no interactive sign-in permission.",
};

export const BUILT_IN_ADMIN_PERMISSIONS_LABEL = "Full platform access (built-in)";

function isSeededDefaultDescription(roleName: string, description: string): boolean {
  const value = description.trim().toLowerCase();
  return !value || value === `default ${roleName.toLowerCase()} role`;
}

export function roleDescription(role: { name: string; description?: string | null; is_core?: boolean }): string {
  const description = String(role.description || "");
  const summary = CORE_ROLE_SUMMARIES[role.name];
  if (role.is_core && summary && isSeededDefaultDescription(role.name, description)) {
    return summary;
  }
  return description.trim();
}

export function rolePermissionsLabel(role: { name: string; permissions?: unknown[] | null }): string {
  if (role.name === "admin") {
    return BUILT_IN_ADMIN_PERMISSIONS_LABEL;
  }
  const count = Array.isArray(role.permissions) ? role.permissions.length : 0;
  return `${count} permission${count === 1 ? "" : "s"}`;
}

// Group "RLS attributes" are key/value pairs that the database tool exposes
// as group.rls.<key> filter tokens for members of the group.
export function dataAccessAttributesLabel(attributes: ReadonlyArray<{ key: string; value: string }>): string {
  if (!attributes.length) return "None";
  return attributes.map((attribute) => `${attribute.key} = ${attribute.value}`).join(", ");
}

export type AccessFix = { label: string; tab: AdminTab };

// Access check: link a blocked row to the page that can fix it.
export function accessFixForRow(row: {
  user: { is_active: boolean };
  effective: { can_use_chat: boolean; assigned_project_count: number };
}): AccessFix | null {
  if (!row.user.is_active || !row.effective.can_use_chat) {
    return { label: "Open user accounts", tab: "users" };
  }
  if (row.effective.assigned_project_count === 0) {
    return { label: "Open workspaces", tab: "projects" };
  }
  return null;
}
