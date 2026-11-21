// Work roles (board 8): functions with tool sets, roles made of
// functions, per-Workspace assignments and the effective permission. Distinct from the platform RBAC roles
// (Admin › People & sign-in › Platform access).

export type CommandPolicy = { allow: string[]; deny: string[] };

export type WorkFunction = {
  id: string;
  key: string;
  name: string;
  description: string;
  workspace_id: string | null;
  built_in: boolean;
  tools: string[];
  tools_version: number;
  version: number;
  role_keys: string[];
};

export type WorkRole = {
  id: string;
  key: string;
  name: string;
  description: string;
  workspace_id: string | null;
  built_in: boolean;
  is_active: boolean;
  function_keys: string[];
  delivery_connections: "all" | "selected";
  connection_ids: string[];
  trusted: boolean;
  trusted_changed_by: string | null;
  trusted_changed_at: string | null;
  command_policy: CommandPolicy;
  version: number;
  assignment_count: number;
};

export type AssignmentSubject =
  | { kind: "user"; user_id: string; label?: string }
  | { kind: "group"; group_id: string; label?: string }
  | { kind: "sso_group"; value: string; provider_id: string | null; label?: string }
  | { kind: "sso_role"; value: string; provider_id: string | null; label?: string };

export type SubjectKind = AssignmentSubject["kind"];

export type Assignment = {
  id: string;
  workspace_id: string;
  role_id: string;
  role_key: string;
  role_name: string;
  subject: AssignmentSubject;
  members: number;
  is_active: boolean;
  version: number;
};

export type WorkspaceRolesSettings = {
  role_based_tools: boolean;
  version: number;
  updated_by: string | null;
  updated_at: string | null;
};

export type MemberRef = { user_id: string; label: string };

export type WorkspaceRoles = {
  workspace_id: string;
  settings: WorkspaceRolesSettings;
  roles: WorkRole[];
  assignments: Assignment[];
  members_without_role: MemberRef[];
  can_edit: boolean;
};

export type ViaEntry = { kind: SubjectKind; value?: string; label?: string };

export type EffectivePermission = {
  workspace_id: string;
  user_id: string;
  enforced: boolean;
  platform_admin: boolean;
  roles: Array<{ id: string; key: string; name: string; trusted: boolean; via: ViaEntry[] }>;
  functions: string[];
  tools: string[];
  tool_entries: string[];
  write_connections: "all" | string[];
  trusted: boolean;
  command_policy: CommandPolicy;
  empty_reason: string | null;
};

export type SsoProvider = {
  id: string;
  name: string;
  groups_claim: string;
  roles_claim: string;
  known_groups: string[];
  known_roles: string[];
};

export type MyClaims = { groups: string[]; roles: string[]; signed_in_at: string | null };

export type AuditEvent = {
  id: string;
  at: string;
  actor: { user_id: string | null; label: string };
  action: string;
  workspace_id: string | null;
  target_type: string;
  target_id: string | null;
  target_label: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
};

export type AuditPage = { events: AuditEvent[]; next_before: string | null };

export type Risk = "read" | "write" | "admin";

export type CatalogTool = { name: string; description: string; in_set: boolean };

export type ToolCatalog = {
  groups: Array<{ connector: string | null; label: string; risks: Partial<Record<Risk, CatalogTool[]>> }>;
  selectors: Array<{ entry: string; label: string }>;
  unknown_entries: string[];
};

export type RoleDraft = {
  key: string;
  name: string;
  description: string;
  workspace_id: string | null;
  function_keys: string[];
  delivery_connections: "all" | "selected";
  connection_ids: string[];
  allow: string;
  deny: string;
  is_active: boolean;
};
