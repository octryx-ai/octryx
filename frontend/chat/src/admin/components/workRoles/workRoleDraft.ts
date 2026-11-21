// Role editor model: key slugs, the role draft, its problems, the write body and the Trusted confirmation.
import type { RoleDraft, WorkRole } from "./workRolesTypes";

// ---- Role editor ----------------------------------------------------------------------------------------------------

export function slugify(name: string): string {
  const slug = name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  return /^[a-z]/.test(slug) ? slug : slug ? `r_${slug}`.slice(0, 40) : "";
}

export const KEY_PATTERN = /^[a-z][a-z0-9_]{1,39}$/;

const lines = (text: string) => text.split("\n").map((line) => line.trim()).filter(Boolean);

export function roleDraft(role: WorkRole | null, workspaceId: string | null = null): RoleDraft {
  return {
    key: role?.key ?? "",
    name: role?.name ?? "",
    description: role?.description ?? "",
    workspace_id: role ? role.workspace_id : workspaceId,
    function_keys: role ? [...role.function_keys] : ["read"],
    delivery_connections: role?.delivery_connections ?? "all",
    connection_ids: role ? [...role.connection_ids] : [],
    allow: (role?.command_policy.allow ?? []).join("\n"),
    deny: (role?.command_policy.deny ?? []).join("\n"),
    is_active: role?.is_active ?? true,
  };
}

/** Problems that keep Save disabled, in the user's words. */
export function roleDraftProblems(draft: RoleDraft, creating: boolean): string[] {
  const problems: string[] = [];
  if (!draft.name.trim()) problems.push("Enter a name.");
  if (creating && !KEY_PATTERN.test(draft.key)) problems.push("The key starts with a letter and uses a–z, 0–9 and _ (2–40 characters).");
  if (draft.delivery_connections === "selected" && !draft.connection_ids.length) problems.push("Pick at least one connection, or allow all.");
  return problems;
}

/** The body of POST (creating) or PATCH (only what changed, with expected_version). */
export function roleWriteBody(draft: RoleDraft, role: WorkRole | null): Record<string, unknown> {
  const full: Record<string, unknown> = {
    name: draft.name.trim(),
    description: draft.description.trim(),
    function_keys: draft.function_keys,
    delivery_connections: draft.delivery_connections,
    connection_ids: draft.delivery_connections === "selected" ? draft.connection_ids : [],
    command_policy: { allow: lines(draft.allow), deny: lines(draft.deny) },
  };
  if (!role) return { key: draft.key, workspace_id: draft.workspace_id, ...full };
  const before: Record<string, unknown> = {
    name: role.name, description: role.description, function_keys: role.function_keys,
    delivery_connections: role.delivery_connections,
    connection_ids: role.delivery_connections === "selected" ? role.connection_ids : [],
    command_policy: { allow: role.command_policy.allow, deny: role.command_policy.deny },
  };
  const body: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(full)) if (JSON.stringify(value) !== JSON.stringify(before[key])) body[key] = value;
  if (draft.is_active !== role.is_active) body.is_active = draft.is_active;
  body.expected_version = role.version;
  return body;
}

/** What turning Trusted on or off changes, for the confirmation step. */
export function trustedConfirmText(on: boolean): string {
  return on
    ? "People with this role can write from the chat without confirming a plan first. Every change to this setting is logged."
    : "People with this role confirm a write plan again before the chat writes. Every change to this setting is logged.";
}
