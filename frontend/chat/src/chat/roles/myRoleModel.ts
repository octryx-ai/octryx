// A person's roles in a Workspace, as the chat and the phone show them (roles contract §2 "Effective permission",
// §3.3, §4, §5; board 8). Plain functions over the API's answers, so the presentation is testable without
// a browser:
//   GET /api/v1/work-roles/workspaces/{ws}/me -> EffectivePermission (every member)
//   GET /api/v1/work-roles/workspaces/{ws}    -> { settings, roles, assignments, members_without_role, can_edit } (admins)

export type RoleVia = { kind: string; value?: string; label?: string };
export type EffectiveRole = { id: string; key: string; name: string; trusted: boolean; via: RoleVia[] };

export type EffectivePermission = {
  workspaceId: string;
  enforced: boolean;
  platformAdmin: boolean;
  roles: EffectiveRole[];
  functions: string[];
  writeConnections: "all" | string[];
  trusted: boolean;
  emptyReason: string | null;
};

export type RoleSubject = { kind: string; label: string; value?: string };
export type RoleAssignment = {
  id: string;
  roleId: string;
  roleName: string;
  subject: RoleSubject;
  members: number | null;
  active: boolean;
};
export type WorkspaceRoles = {
  roleBasedTools: boolean;
  assignments: RoleAssignment[];
  membersWithoutRole: string[];
  trustedRoleIds: Set<string>;
  canEdit: boolean;
};

/** §4: the empty-state text when the API sends none. */
export const EMPTY_REASON_EN =
  "You have no role in this Workspace, so no tools are available. A Workspace admin can assign one (Workspace › Roles).";
/** The badge a trusted role carries wherever it appears (BRIEF-ROLES "Trusted role"). */
export const TRUSTED_BADGE = "Trusted · no plan confirmation";
export const WHO_ASSIGNS_ROLES = "Workspace admin";

// §7 seed functions; a custom function without a known name reads as its key in words, never the raw slug.
const FUNCTION_NAMES: Record<string, string> = {
  read: "Chat & knowledge",
  work_items: "Work items",
  delivery: "Delivery",
  steer_runs: "Start runs",
  approve_tools: "Approve tools",
  decide_as_po: "Decide as product owner",
  workspace_settings: "Workspace settings",
  assign_roles: "Assign roles",
  global_settings: "Global settings",
};

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

function words(key: string): string {
  const flat = key.replace(/[_-]+/g, " ").trim();
  return flat ? flat.charAt(0).toUpperCase() + flat.slice(1) : "";
}

export function functionName(key: string): string {
  return FUNCTION_NAMES[key] ?? words(key);
}

function readVia(raw: unknown): RoleVia | null {
  const item = record(raw);
  const kind = text(item?.kind);
  if (!kind) return null;
  return { kind, value: text(item?.value) || undefined, label: text(item?.label) || undefined };
}

export function readEffectivePermission(raw: unknown): EffectivePermission | null {
  const body = record(raw);
  if (!body) return null;
  const roles = list(body.roles)
    .map((entry) => {
      const role = record(entry);
      const name = text(role?.name);
      if (!role || !name) return null;
      return {
        id: text(role.id),
        key: text(role.key),
        name,
        trusted: role.trusted === true,
        via: list(role.via).map(readVia).filter((via): via is RoleVia => via !== null),
      };
    })
    .filter((role): role is EffectiveRole => role !== null);
  const connections = body.write_connections;
  return {
    workspaceId: text(body.workspace_id),
    enforced: body.enforced === true,
    platformAdmin: body.platform_admin === true,
    roles,
    functions: list(body.functions).map(text).filter(Boolean),
    writeConnections: Array.isArray(connections) ? connections.map(text).filter(Boolean) : "all",
    trusted: body.trusted === true || roles.some((role) => role.trusted),
    emptyReason: text(body.empty_reason) || null,
  };
}

/** How a role reaches the person, in words ("Assigned to you", "Through the SSO group eng-developers"). */
export function viaText(via: RoleVia): string {
  const name = via.label || via.value || "";
  switch (via.kind) {
    case "user":
      return "Assigned to you";
    case "group":
      return name ? `Through the group ${name}` : "Through a group";
    case "sso_group":
      return name ? `Through the SSO group ${name}` : "Through an SSO group";
    case "sso_role":
      return name ? `Through the SSO role ${name}` : "Through an SSO role";
    default:
      return name ? `Through ${name}` : "";
  }
}

export function viaSummary(role: EffectiveRole): string {
  return role.via.map(viaText).filter(Boolean).join(" · ");
}

/** The write connections in words (§2: "all" or the ids of the named connections). */
export function writeConnectionsText(permission: EffectivePermission): string {
  if (permission.writeConnections === "all") return "Every connection of the Workspace";
  const count = permission.writeConnections.length;
  if (!count) return "None";
  return count === 1 ? "1 named connection" : `${count} named connections`;
}

export type RoleChatNotice =
  | { kind: "empty"; text: string; workspace: string; hint: string }
  | { kind: "trusted"; text: string; roles: string };

/** Chat writes are confirmed once per task through a write plan; a trusted role skips that plan
 * (everything inside a confirmed plan's scope runs, no per-call exceptions). */
export const TRUSTED_EFFECT =
  "your chat writes run without a plan confirmation.";

export function trustedNoticeText(roleNames: string[]): string {
  return roleNames.length ? `Trusted role (${roleNames.join(", ")}): ${TRUSTED_EFFECT}` : `Trusted role: ${TRUSTED_EFFECT}`;
}

/**
 * What the chat shows above the composer for the person's roles in its Workspace: the empty state (switch on, no
 * role; the chat still answers without tools), else the trusted notice, else nothing. Platform admins are never
 * filtered, so they see neither.
 */
export function roleChatNotice(permission: EffectivePermission | null, workspaceName: string): RoleChatNotice | null {
  if (!permission || permission.platformAdmin) return null;
  if (permission.enforced && (permission.emptyReason || !permission.roles.length)) {
    return {
      kind: "empty",
      text: permission.emptyReason || EMPTY_REASON_EN,
      workspace: workspaceName,
      hint: `Who can assign roles: a ${WHO_ASSIGNS_ROLES} of ${workspaceName || "this Workspace"}.`,
    };
  }
  if (permission.trusted) {
    const trusted = permission.roles.filter((role) => role.trusted).map((role) => role.name);
    return { kind: "trusted", text: trustedNoticeText(trusted), roles: trusted.join(", ") };
  }
  return null;
}

/** "Your role: Developer" for the chat header; empty when the switch is off or nothing applies. */
export function roleHeaderText(permission: EffectivePermission | null): string {
  if (!permission || !permission.enforced || permission.platformAdmin || !permission.roles.length) return "";
  const names = permission.roles.map((role) => role.name);
  return `${names.length === 1 ? "Your role" : "Your roles"}: ${names.join(", ")}`;
}

// ── Refusals (§4) ──────────────────────────────────────────────────────────────────────────────────────────────

export const ROLE_REFUSAL_CODES = ["role_tool_not_granted", "role_connection_not_granted", "po_function_required"] as const;
export type RoleRefusal = { code: string; message: string; setting: string; whoCanChange: string };

const FALLBACK_MESSAGES: Record<string, string> = {
  role_tool_not_granted: "This tool is not part of your roles in this Workspace.",
  role_connection_not_granted: "Your roles may not write through this connection.",
  po_function_required: "This decision needs the function Decide as product owner.",
};

function refusalFrom(body: Record<string, unknown> | null): RoleRefusal | null {
  const code = text(body?.code);
  if (!body || !(ROLE_REFUSAL_CODES as readonly string[]).includes(code)) return null;
  return {
    code,
    message: text(body.message) || FALLBACK_MESSAGES[code],
    setting: text(body.setting),
    whoCanChange: text(body.who_can_change),
  };
}

function parsed(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed.startsWith("{")) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

/**
 * A role refusal carried by a tool result: `{code, …}`, `{detail: {code, …}}` or `{error: {code, …}}`, as an object
 * or a JSON string. Only the structured code counts; prose is never parsed.
 */
export function readRoleRefusal(result: unknown): RoleRefusal | null {
  const body = record(parsed(result));
  if (!body) return null;
  return refusalFrom(body) ?? refusalFrom(record(parsed(body.detail))) ?? refusalFrom(record(parsed(body.error)));
}

/** The refusal as one calm sentence plus the setting and who can change it, verbatim. */
export function roleRefusalText(refusal: RoleRefusal): string {
  const parts = [refusal.message.replace(/\s+/g, " ").trim()];
  if (refusal.setting) parts.push(`Setting: ${refusal.setting}.`);
  if (refusal.whoCanChange) parts.push(`Who can change it: ${refusal.whoCanChange}.`);
  return parts.join(" ");
}

// ── A Workspace's assignments (admins, read-only on the phone) ───────────────────────────────────────────────────

const SUBJECT_KINDS: Record<string, string> = {
  user: "Person",
  group: "Group",
  sso_group: "SSO group",
  sso_role: "SSO role",
};

export function subjectKindText(kind: string): string {
  return SUBJECT_KINDS[kind] ?? "";
}

export function readWorkspaceRoles(raw: unknown): WorkspaceRoles | null {
  const body = record(raw);
  if (!body) return null;
  const settings = record(body.settings);
  const roles = list(body.roles).map(record).filter((role): role is Record<string, unknown> => role !== null);
  const roleNames = new Map(roles.map((role) => [text(role.id), text(role.name)]));
  const assignments = list(body.assignments)
    .map((entry): RoleAssignment | null => {
      const item = record(entry);
      const subject = record(item?.subject);
      if (!item || !subject) return null;
      const roleId = text(item.role_id);
      const members = item.members;
      return {
        id: text(item.id),
        roleId,
        roleName: text(item.role_name) || roleNames.get(roleId) || "",
        subject: {
          kind: text(subject.kind),
          label: text(subject.label) || text(subject.value),
          value: text(subject.value) || undefined,
        },
        members: typeof members === "number" && Number.isFinite(members) ? members : null,
        active: item.is_active !== false,
      };
    })
    .filter((item): item is RoleAssignment => item !== null && Boolean(item.roleName) && Boolean(item.subject.label));
  return {
    roleBasedTools: settings?.role_based_tools === true,
    assignments,
    membersWithoutRole: list(body.members_without_role)
      .map((entry) => text(record(entry)?.label))
      .filter(Boolean),
    trustedRoleIds: new Set(roles.filter((role) => role.trusted === true).map((role) => text(role.id))),
    canEdit: body.can_edit === true,
  };
}

/** "Role-based tools: on" / "off", with what the state means. */
export function switchText(roles: WorkspaceRoles): { label: string; detail: string } {
  return roles.roleBasedTools
    ? { label: "On", detail: "Tools follow each person's roles. Without a role a person has no tools." }
    : { label: "Off", detail: "Roles are kept but not applied: everyone has the Workspace's tools." };
}

/** "These 2 members will have no tools: Anna Keller, Ben Roth" (§3.3). */
export function membersWithoutRoleText(names: string[], switchOn: boolean): string {
  if (!names.length) return "";
  const one = names.length === 1;
  const who = one ? "This member" : `These ${names.length} members`;
  const verb = switchOn ? (one ? "has" : "have") : "will have";
  return `${who} ${verb} no tools: ${names.join(", ")}`;
}
