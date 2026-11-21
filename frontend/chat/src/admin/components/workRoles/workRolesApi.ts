// The work-role endpoints as the admin pages call them (all under /api/v1/work-roles).
// readJson throws an Error carrying `status`, `code` and the structured `detail` (message, setting, who_can_change),
// which workRolesModel.errorView turns into what the page shows.
import { readJson } from "../../utils/adminPanelHelpers";
import { orderFunctions } from "./workRolesModel";
import type {
  Assignment,
  AssignmentSubject,
  AuditPage,
  CommandPolicy,
  EffectivePermission,
  MyClaims,
  SsoProvider,
  ToolCatalog,
  WorkFunction,
  WorkRole,
  WorkspaceRoles,
  WorkspaceRolesSettings,
} from "./workRolesTypes";

export const WORK_ROLES_BASE = "/api/v1/work-roles";

const enc = encodeURIComponent;
const query = (params: Record<string, string | number | null | undefined>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : "";
};
const send = <T>(path: string, method: string, body?: unknown) =>
  readJson<T>(`${WORK_ROLES_BASE}${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body) });

// Functions (§3.1)
export const listFunctions = (workspaceId?: string | null) =>
  readJson<{ functions: WorkFunction[] }>(`${WORK_ROLES_BASE}/functions${query({ workspace_id: workspaceId })}`).then((answer) => orderFunctions(answer.functions ?? []));
export const updateFunction = (id: string, body: { name?: string; description?: string; expected_version: number }) =>
  send<WorkFunction>(`/functions/${enc(id)}`, "PATCH", body);
export const saveFunctionTools = (id: string, tools: string[], expectedToolsVersion: number) =>
  send<WorkFunction>(`/functions/${enc(id)}/tools`, "PUT", { tools, expected_tools_version: expectedToolsVersion });
export const loadToolCatalog = (functionId: string) =>
  readJson<ToolCatalog>(`${WORK_ROLES_BASE}/tool-catalog${query({ function_id: functionId })}`);

// Roles (§3.2)
export const listRoles = (workspaceId?: string | null) =>
  readJson<{ roles: WorkRole[] }>(`${WORK_ROLES_BASE}/roles${query({ workspace_id: workspaceId })}`).then((answer) => answer.roles ?? []);
export const loadRole = (id: string) => readJson<WorkRole>(`${WORK_ROLES_BASE}/roles/${enc(id)}`);
export type RoleWrite = {
  key?: string;
  name?: string;
  description?: string;
  workspace_id?: string | null;
  function_keys?: string[];
  delivery_connections?: "all" | "selected";
  connection_ids?: string[];
  command_policy?: CommandPolicy;
  is_active?: boolean;
  expected_version?: number;
};
export const createRole = (body: RoleWrite) => send<WorkRole>("/roles", "POST", body);
export const updateRole = (id: string, body: RoleWrite) => send<WorkRole>(`/roles/${enc(id)}`, "PATCH", body);
export const setRoleTrusted = (id: string, trusted: boolean, reason: string, expectedVersion: number) =>
  send<WorkRole>(`/roles/${enc(id)}/trusted`, "PUT", { trusted, reason, expected_version: expectedVersion });
export const deleteRole = (id: string) => send<unknown>(`/roles/${enc(id)}`, "DELETE").catch((error: unknown) => {
  // 204 has no JSON body: readJson throws a SyntaxError (no status) reading it, which is success here.
  if (error instanceof SyntaxError) return null;
  throw error;
});

// A Workspace's roles page (§3.3)
const wsPath = (workspaceId: string) => `/workspaces/${enc(workspaceId)}`;
export const loadWorkspaceRoles = (workspaceId: string) => readJson<WorkspaceRoles>(`${WORK_ROLES_BASE}${wsPath(workspaceId)}`);
export const saveRoleBasedTools = (workspaceId: string, on: boolean, expectedVersion: number) =>
  send<WorkspaceRolesSettings>(`${wsPath(workspaceId)}/settings`, "PUT", { role_based_tools: on, expected_version: expectedVersion });
export const createAssignment = (workspaceId: string, roleId: string, subject: AssignmentSubject) => {
  // The subject is sent without its label (§3.3).
  const { label: _label, ...bare } = subject as AssignmentSubject & { label?: string };
  return send<Assignment>(`${wsPath(workspaceId)}/assignments`, "POST", { role_id: roleId, subject: bare });
};
export const revokeAssignment = (workspaceId: string, assignment: Pick<Assignment, "id" | "version">) =>
  send<Assignment>(`${wsPath(workspaceId)}/assignments/${enc(assignment.id)}`, "PATCH", { is_active: false, expected_version: assignment.version });
export const loadEffective = (workspaceId: string, userId: string) =>
  readJson<EffectivePermission>(`${WORK_ROLES_BASE}${wsPath(workspaceId)}/effective${query({ user_id: userId })}`);

// SSO mapping (§3.4)
export const listSsoProviders = () =>
  readJson<{ providers: SsoProvider[] }>(`${WORK_ROLES_BASE}/sso-mapping`).then((answer) => answer.providers ?? []);
export const saveSsoMapping = (providerId: string, groupsClaim: string, rolesClaim: string) =>
  send<SsoProvider>(`/sso-mapping/${enc(providerId)}`, "PUT", { groups_claim: groupsClaim, roles_claim: rolesClaim });
export const loadMyClaims = (providerId: string) => readJson<MyClaims>(`${WORK_ROLES_BASE}/sso-mapping/${enc(providerId)}/my-claims`);

// Audit (§3.5)
export const loadAudit = (filter: { workspace_id?: string; role_id?: string; function_id?: string; before?: string | null; limit?: number } = {}) =>
  readJson<AuditPage>(`${WORK_ROLES_BASE}/audit${query(filter)}`);
