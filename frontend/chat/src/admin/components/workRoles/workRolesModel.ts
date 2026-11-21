// Presentation of work roles (board 8): badge texts, the role × function matrix, assignment rows, the
// members-without-role text, the audit sentence and the error mapping. Pure, so unit tests cover it.
import type { StatusTone } from "../../../layout/StatusLabel";
import type {
  Assignment,
  AssignmentSubject,
  AuditEvent,
  CatalogTool,
  MemberRef,
  Risk,
  SubjectKind,
  ToolCatalog,
  ViaEntry,
  WorkFunction,
  WorkRole,
} from "./workRolesTypes";

export const TRUSTED_BADGE = "Trusted · no plan confirmation";
export const NO_ROLE_TEXT =
  "You have no role in this Workspace, so no tools are available. A Workspace admin can assign one (Workspace › Roles).";
export const CONFLICT_TEXT = "Someone changed this meanwhile; reloaded.";
// Contract §6, in one line next to the command rule fields.
export const COMMAND_LAYERING_TEXT =
  "Checked on top of the Workspace's Command safety: its always-blocked commands still win. A deny here refuses, an " +
  "allow admits a command the strict shell would refuse; over all of a person's roles, deny wins over allow.";
// Built-in Workspace admin keeps these (409 role_keeps_function).
export const KEPT_FUNCTIONS: Record<string, string[]> = { workspace_admin: ["assign_roles", "workspace_settings"] };

export type Badge = { label: string; tone: StatusTone; title?: string };

/** The badges of a role, in the order they are shown: origin, trusted, inactive. */
export function roleBadges(role: Pick<WorkRole, "built_in" | "trusted" | "is_active">): Badge[] {
  const badges: Badge[] = [{ label: role.built_in ? "Built-in" : "Custom", tone: "neutral" }];
  if (role.trusted) badges.push({ label: TRUSTED_BADGE, tone: "attention", title: "Chat writes of its holders run without confirming a write plan." });
  if (!role.is_active) badges.push({ label: "Inactive", tone: "neutral" });
  return badges;
}

export type MatrixRow = { role: WorkRole; cells: boolean[]; muted: boolean };

// The seeds in the order a person reads them (contract §7, board 8): from "may chat" to "may change everything".
// The server lists by key; custom functions and roles follow the seeds, by name.
const FUNCTION_ORDER = ["read", "work_items", "delivery", "steer_runs", "approve_tools", "decide_as_po", "workspace_settings",
  "assign_roles", "global_settings"];
const ROLE_ORDER = ["workspace_admin", "product_manager", "engineer", "sre", "incident_lead", "support_agent", "agile_lead",
  "doc_owner", "viewer"];
const seedRank = (order: string[], key: string) => { const i = order.indexOf(key); return i < 0 ? order.length : i; };

/** Functions in reading order: the seeds first in their fixed order, then custom ones by name. */
export function orderFunctions<T extends Pick<WorkFunction, "key" | "name">>(functions: T[]): T[] {
  return [...functions].sort((a, b) =>
    seedRank(FUNCTION_ORDER, a.key) - seedRank(FUNCTION_ORDER, b.key) || a.name.localeCompare(b.name));
}

/** One row per role with one cell per function (in the functions' order); active roles first, built-in before custom. */
export function matrixRows(roles: WorkRole[], functions: WorkFunction[]): MatrixRow[] {
  const rank = (role: WorkRole) => (role.is_active ? 0 : 2) + (role.built_in ? 0 : 1);
  const columns = orderFunctions(functions);
  return [...roles]
    .sort((a, b) => rank(a) - rank(b) || seedRank(ROLE_ORDER, a.key) - seedRank(ROLE_ORDER, b.key) || a.name.localeCompare(b.name))
    .map((role) => ({
      role,
      cells: columns.map((fn) => role.function_keys.includes(fn.key)),
      muted: !role.is_active,
    }));
}

/** Function names for keys, in the given order; a key the catalog does not know stays as it is. */
export function functionNames(keys: string[], functions: Pick<WorkFunction, "key" | "name">[]): string[] {
  return keys.map((key) => functions.find((fn) => fn.key === key)?.name || key);
}

export function scopeText(workspaceId: string | null, workspaces: Array<{ id: string; name: string }>): string {
  if (!workspaceId) return "All Workspaces";
  return `Only ${workspaces.find((ws) => ws.id === workspaceId)?.name || "one Workspace"}`;
}

const listNames = (names: string[], max = 5) =>
  names.length <= max ? names.join(", ") : `${names.slice(0, max).join(", ")} and ${names.length - max} more`;

/** The line next to the "Role-based tools" switch, and the confirmation text before turning it on. */
export function membersWithoutRoleText(members: MemberRef[], enforced = false): string {
  if (!members.length) return "Every member has a role.";
  const n = members.length;
  const verb = enforced ? (n === 1 ? "has" : "have") : "will have";
  return `${n === 1 ? "This member" : `These ${n} members`} ${verb} no tools: ${listNames(members.map((m) => m.label))}.`;
}

export function subjectKindLabel(subject: Pick<AssignmentSubject, "kind">, providerName?: string | null): string {
  const base: Record<SubjectKind, string> = { user: "Person", group: "Workspace group", sso_group: "SSO group", sso_role: "SSO role" };
  const label = base[subject.kind];
  return providerName && (subject.kind === "sso_group" || subject.kind === "sso_role") ? `${label} · ${providerName}` : label;
}

export function subjectKey(subject: AssignmentSubject): string {
  switch (subject.kind) {
    case "user": return `user:${subject.user_id}`;
    case "group": return `group:${subject.group_id}`;
    default: return `${subject.kind}:${subject.provider_id ?? "*"}:${subject.value}`;
  }
}

export function subjectLabel(subject: AssignmentSubject): string {
  if (subject.label) return subject.label;
  return subject.kind === "user" ? subject.user_id : subject.kind === "group" ? subject.group_id : subject.value;
}

export function membersText(subject: AssignmentSubject, members: number): string {
  const people = `${members} ${members === 1 ? "person" : "people"}`;
  return subject.kind === "sso_group" || subject.kind === "sso_role" ? `${people} · from sign-in` : people;
}

export type AssignmentRow = {
  key: string;
  subject: AssignmentSubject;
  assignments: Assignment[];
  members: number;
};

/** Active assignments grouped by who they reach: one row per subject with all its roles. */
export function assignmentRows(assignments: Assignment[]): AssignmentRow[] {
  const order: SubjectKind[] = ["sso_group", "sso_role", "group", "user"];
  const rows = new Map<string, AssignmentRow>();
  for (const assignment of assignments) {
    if (!assignment.is_active) continue;
    const key = subjectKey(assignment.subject);
    const row = rows.get(key) ?? { key, subject: assignment.subject, assignments: [], members: 0 };
    row.assignments.push(assignment);
    row.members = Math.max(row.members, assignment.members);
    rows.set(key, row);
  }
  return [...rows.values()].sort((a, b) =>
    order.indexOf(a.subject.kind) - order.indexOf(b.subject.kind) || subjectLabel(a.subject).localeCompare(subjectLabel(b.subject)));
}

/** How a role reaches a person ("directly", "via SSO group eng-developers"). */
export function viaText(via: ViaEntry): string {
  if (via.kind === "user") return "directly";
  const name = via.label || via.value || "";
  return `via ${subjectKindLabel({ kind: via.kind })} ${name}`.trim();
}

export function writeConnectionsText(value: "all" | string[], connections: Array<{ id: string; name: string }>): string {
  if (value === "all") return "All connections";
  if (!value.length) return "No connection";
  return value.map((id) => connections.find((c) => c.id === id)?.name || "Unknown connection").join(", ");
}

// ---- Errors ---------------------------------------------------------------------------------------------------------

export type ErrorView = { message: string; setting: string | null; whoCanChange: string | null; conflict: boolean };

/** What a failed call shows: the API's message plus `setting` / `who_can_change` verbatim; a version conflict says so. */
export function errorView(error: unknown, fallback = "The change could not be saved."): ErrorView {
  const err = (error ?? {}) as { code?: string | null; message?: string; detail?: Record<string, unknown> };
  const detail = err.detail ?? {};
  const code = err.code ?? (typeof detail.code === "string" ? detail.code : null);
  const str = (value: unknown) => (typeof value === "string" && value.trim() ? value : null);
  if (code === "version_conflict") return { message: CONFLICT_TEXT, setting: null, whoCanChange: null, conflict: true };
  return {
    message: str(detail.message) ?? str(err.message) ?? fallback,
    setting: str(detail.setting),
    whoCanChange: str(detail.who_can_change),
    conflict: false,
  };
}

// ---- Tool sets ------------------------------------------------------------------------------------------------------

export const RISK_LABEL: Record<Risk, string> = { read: "Read", write: "Write", admin: "Admin" };
export const RISKS: Risk[] = ["read", "write", "admin"];

export type ToolGroupView = { key: string; label: string; risks: Array<{ risk: Risk; tools: CatalogTool[] }> };

/** The catalog grouped by connector, then risk; empty risks are left out. */
export function toolGroups(catalog: ToolCatalog): ToolGroupView[] {
  return catalog.groups
    .map((group) => ({
      key: group.connector ?? "platform",
      label: group.label,
      risks: RISKS.map((risk) => ({ risk, tools: group.risks[risk] ?? [] })).filter((entry) => entry.tools.length > 0),
    }))
    .filter((group) => group.risks.length > 0);
}

/** Entries that are not a catalog tool and not an offered selector: globs and selectors the user added. */
export function extraEntries(entries: string[], catalog: ToolCatalog): string[] {
  const known = new Set<string>([
    ...catalog.groups.flatMap((group) => RISKS.flatMap((risk) => (group.risks[risk] ?? []).map((tool) => tool.name))),
    ...catalog.selectors.map((selector) => selector.entry),
  ]);
  return entries.filter((entry) => !known.has(entry));
}

export function toggleEntry(entries: string[], entry: string, on: boolean): string[] {
  const without = entries.filter((item) => item !== entry);
  return on ? [...without, entry] : without;
}

export function unknownEntriesText(unknown: string[]): string | null {
  if (!unknown.length) return null;
  const n = unknown.length;
  return `${n === 1 ? "1 entry matches" : `${n} entries match`} no tool today: ${listNames(unknown, 8)}. ` +
    `${n === 1 ? "It is" : "They are"} kept, because a tool may arrive later.`;
}

// ---- Audit ----------------------------------------------------------------------------------------------------------

const onOff = (value: unknown) => (value ? "on" : "off");

/** The action in words ("turned Trusted on for Product owner"). */
export function auditSentence(event: Pick<AuditEvent, "action" | "target_label" | "after">): string {
  const target = event.target_label || "an item";
  const after = event.after ?? {};
  switch (event.action) {
    case "function.created": return `created the function ${target}`;
    case "function.updated": return `changed the function ${target}`;
    case "function.tools_changed": return `changed the tools of ${target}`;
    case "function.deleted": return `deleted the function ${target}`;
    case "role.created": return `created the role ${target}`;
    case "role.updated":
      if ("is_active" in after && Object.keys(after).length === 1) return `${after.is_active ? "activated" : "deactivated"} the role ${target}`;
      return `changed the role ${target}`;
    case "role.trusted_changed": return `turned Trusted ${onOff(after.trusted)} for ${target}`;
    case "role.deleted": return `deleted the role ${target}`;
    case "assignment.created": return `assigned ${target}`;
    case "assignment.activated": return `activated the assignment ${target}`;
    case "assignment.revoked": return `revoked ${target}`;
    case "settings.role_based_tools_changed": return `turned Role-based tools ${onOff(after.role_based_tools)} in ${target}`;
    case "sso_mapping.changed": return `changed the SSO mapping of ${target}`;
    default: return `changed ${target}`;
  }
}

const FIELD_LABEL: Record<string, string> = {
  name: "Name", description: "Description", trusted: "Trusted", is_active: "Active", function_keys: "Functions",
  delivery_connections: "Write connections", connection_ids: "Connections", command_policy: "Command rules",
  role_based_tools: "Role-based tools", groups_claim: "Groups claim", roles_claim: "Roles claim", tools: "Tools",
};

function valueText(key: string, value: unknown, functions: Pick<WorkFunction, "key" | "name">[]): string {
  if (value === null || value === undefined || value === "") return "none";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (key === "function_keys" && Array.isArray(value)) return functionNames(value.map(String), functions).join(", ") || "none";
  if (key === "delivery_connections") return value === "all" ? "all connections" : "selected connections";
  if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : "none";
  if (typeof value === "object") {
    const policy = value as { allow?: unknown[]; deny?: unknown[] };
    if (Array.isArray(policy.allow) || Array.isArray(policy.deny)) return `allow ${policy.allow?.length ?? 0}, deny ${policy.deny?.length ?? 0}`;
    return "changed";
  }
  return String(value);
}

/** Before → after per changed field, in words. */
export function auditChanges(event: Pick<AuditEvent, "before" | "after">, functions: Pick<WorkFunction, "key" | "name">[] = []): string[] {
  const before = event.before ?? {};
  const after = event.after ?? {};
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  return keys
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map((key) => {
      const label = FIELD_LABEL[key] ?? key.replace(/_/g, " ");
      if (!(key in before)) return `${label}: ${valueText(key, after[key], functions)}`;
      return `${label}: ${valueText(key, before[key], functions)} → ${valueText(key, after[key], functions)}`;
    });
}
