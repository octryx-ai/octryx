import type { AdminProjectAccessPayload, AdminProjectAccessAssignment, AdminProjectGroupAccessAssignment, AdminProjectRoleAccessAssignment } from "../../types/projectQualityTypes.access";

// Draft rows and payload mapping for the workspace Access section. The PUT
// payload shape (assignments / group_assignments / role_assignments, each with
// project_roles) is unchanged.
export const PROJECT_ROLE_OPTIONS = ["owner", "member", "viewer"] as const;

// Effects as enforced today: viewer is limited to read-only tools
// (tool_access_policy READ_ONLY_PROJECT_ROLES); owner may also author
// workspace knowledge (knowledge/access/authorization AUTHOR_PROJECT_ROLES).
export const PROJECT_ROLE_HINTS: Record<string, string> = {
  owner: "Member rights plus editing workspace knowledge",
  member: "Uses the tools allowed in this workspace",
  viewer: "Read-only tools only",
};

export const DEFAULT_PROJECT_ROLE = "member";

export type AccessDraft = { key: string; user_id: string; project_roles: string[] };
export type GroupAccessDraft = { key: string; group_id: string; project_roles: string[] };
export type RoleAccessDraft = { key: string; role_id: string; project_roles: string[] };

export type AccessDrafts = {
  direct: AccessDraft[];
  groups: GroupAccessDraft[];
  roles: RoleAccessDraft[];
};

export function normalizeProjectRoles(rawRoles: string[] | undefined, fallback: string): string[] {
  const uniqueRoles = Array.isArray(rawRoles)
    ? [...new Set(rawRoles.map((role) => role?.trim().toLowerCase()).filter(Boolean))]
    : [];
  return uniqueRoles.length ? uniqueRoles : [fallback];
}

export function newDraftKey(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function rolesOf(assignment: { project_roles?: string[]; project_role?: string }): string[] {
  return normalizeProjectRoles(
    assignment.project_roles,
    assignment.project_role || DEFAULT_PROJECT_ROLE,
  );
}

export function draftsFromPayload(payload: AdminProjectAccessPayload): AccessDrafts {
  return {
    direct: payload.assignments.map((assignment: AdminProjectAccessAssignment) => ({
      key: assignment.user_id,
      user_id: assignment.user_id,
      project_roles: rolesOf(assignment),
    })),
    groups: payload.group_assignments.map((assignment: AdminProjectGroupAccessAssignment) => ({
      key: assignment.group_id,
      group_id: assignment.group_id,
      project_roles: rolesOf(assignment),
    })),
    roles: payload.role_assignments.map((assignment: AdminProjectRoleAccessAssignment) => ({
      key: assignment.role_id,
      role_id: assignment.role_id,
      project_roles: rolesOf(assignment),
    })),
  };
}

function rolesOrDefault(roles: string[]): string[] {
  return roles.length ? roles : [DEFAULT_PROJECT_ROLE];
}

export function accessSavePayload(drafts: AccessDrafts) {
  return {
    assignments: drafts.direct
      .filter((row) => row.user_id)
      .map((row) => ({ user_id: row.user_id, project_roles: rolesOrDefault(row.project_roles) })),
    group_assignments: drafts.groups
      .filter((row) => row.group_id)
      .map((row) => ({ group_id: row.group_id, project_roles: rolesOrDefault(row.project_roles) })),
    role_assignments: drafts.roles
      .filter((row) => row.role_id)
      .map((row) => ({ role_id: row.role_id, project_roles: rolesOrDefault(row.project_roles) })),
  };
}

export function toggleProjectRole(current: string[], role: string, checked: boolean): string[] {
  if (checked) return current.includes(role) ? current : [...current, role];
  return current.filter((item) => item !== role);
}
