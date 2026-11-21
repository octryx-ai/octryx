import { stringifyLimitField } from "../projectsTab/projectConnectorLimitCodec";
import type { Binding } from "./connectionTypes";

// "Spaces / Projects this connection serves" (bound_scopes) on the connection Overview, and what applies while the
// connection binds none. The backend's rules (services/connections/writes.py, named_connections/resolver.py):
// - bound_scopes is a list of at most 100 keys in the binding's case; PUT replaces it as a whole.
// - A bound connection serves exactly its keys in every Workspace it is available in (each with the Workspace's own
//   rule for that key, if any); a run for one of them uses it.
// - An unbound connection is the Workspace's default for the connector; what it may read is the Workspace's allowed
//   list (Workspace settings › Connector settings), or the global list when the Workspace has none. Binding the first
//   key ends that: other keys are no longer read through it.
// - An existing entry from per-connector setup keeps at least one bound key.

export const MAX_BOUND_KEYS = 100;

/** "shop, docs\nOPS" → ["SHOP", "DOCS", "OPS"]: the keys as the server keeps them (binding case, no duplicates). */
export function parseBoundKeys(text: string, binding: Pick<Binding, "upper"> | null): string[] {
  const keys = text.split(/[\s,;]+/).map((part) => part.trim()).filter(Boolean)
    .map((key) => (binding?.upper === false ? key : key.toUpperCase()));
  return Array.from(new Set(keys));
}

export const formatBoundKeys = (keys: string[]) => keys.join(", ");

/** A problem the server would refuse, in words, before saving; "" when the keys are fine. */
export function boundKeysProblem(keys: string[], binding: Binding): string {
  const noun = binding.label.toLowerCase();
  if (keys.length > MAX_BOUND_KEYS) return `Up to ${MAX_BOUND_KEYS} ${binding.plural.toLowerCase()}; remove ${keys.length - MAX_BOUND_KEYS}.`;
  if (binding.pattern) {
    const rule = new RegExp(`^(?:${binding.pattern})$`);
    const wrong = keys.find((key) => !rule.test(key));
    if (wrong) return `"${wrong}" is not a ${noun} key (letters, digits and _).`;
  }
  return "";
}

/** The server's refusal at bound_scopes, in words. */
export function boundScopesErrorText(message: string, binding: Binding | null): string {
  const plural = (binding?.plural ?? "Keys").toLowerCase();
  if (/keeps at least one key/.test(message)) {
    return `This connection served agent tools before Connections existed and keeps at least one ${binding?.label.toLowerCase() ?? "key"}. Add one before removing the last.`;
  }
  if (/at most/.test(message)) return `Up to ${MAX_BOUND_KEYS} ${plural}.`;
  if (/not a valid/.test(message)) return `One of the ${plural} is not a valid key (letters, digits and _).`;
  return message;
}

export const boundHint = (binding: Binding) =>
  `Runs that use one of these keys use this connection. Empty: not bound; the Workspace's allowed ${binding.plural.toLowerCase()} apply.`;

export const perWorkspaceLine = (binding: Binding) =>
  `Which ${binding.plural.toLowerCase()} this connection may read is set per Workspace: Workspace settings › Connector settings › Allowed ${binding.plural.toLowerCase()}.`;

/** What an empty allowed list means for this type (the descriptor's serves_unlisted). */
export const emptyListText = (binding: Binding) =>
  (binding.servesUnlisted ? `every ${binding.label.toLowerCase()}` : `no ${binding.label.toLowerCase()}`);

// ---- what applies while unbound: each Workspace's allowed list, else the global one ------------------------

export type WorkspaceAllowlist = { workspace: { id: string; name: string }; own: string[] | null };
export type UnboundToday = { workspaces: WorkspaceAllowlist[]; global: string[] };

const keysOf = (field: string, value: unknown) => stringifyLimitField(field, value).split("\n").filter(Boolean);

type Rec = Record<string, unknown>;
const rec = (value: unknown): Rec | null => (value && typeof value === "object" && !Array.isArray(value) ? value as Rec : null);

/**
 * The Workspaces' allowed keys from one batch read, GET /admin/chat/api/panel/connectors/{connector}/workspace-limits
 * ({limit_fields, inherited_limits, workspaces: [{project_id, project_limits}]}). Workspaces the answer leaves out
 * (unknown, or somebody else's private one) are left out here too. Null when the answer is not that shape.
 */
export function readWorkspaceLimits(
  payload: unknown, field: string, workspaces: Array<{ id: string; name: string }>,
): UnboundToday | null {
  const body = rec(payload);
  if (!body || !Array.isArray(body.workspaces)) return null;
  const byId = new Map(workspaces.map((workspace) => [workspace.id, workspace]));
  const rows: WorkspaceAllowlist[] = [];
  for (const row of body.workspaces.map(rec)) {
    const workspace = byId.get(String(row?.project_id ?? ""));
    if (!workspace) continue;
    const own = rec(row?.project_limits)?.[field];
    rows.push({ workspace, own: own === undefined ? null : keysOf(field, own) });
  }
  return { workspaces: rows, global: keysOf(field, rec(body.inherited_limits)?.[field]) };
}

const listText = (keys: string[], binding: Binding) => (keys.length ? keys.join(", ") : `${emptyListText(binding)} (empty)`);

/** "Today, unbound: Shop → SHOP, DOCS; Ops → global list; global → DOCS". */
export function unboundTodayText(today: UnboundToday, binding: Binding): string {
  const parts = today.workspaces.map((row) => `${row.workspace.name} → ${row.own === null ? "global list" : listText(row.own, binding)}`);
  return `Today, unbound: ${[...parts, `global → ${listText(today.global, binding)}`].join("; ")}`;
}

/** The keys some Workspace reads through this connection today that the new bound keys leave out. */
export function keysLeftOut(today: UnboundToday | null, bound: string[]): string[] {
  if (!today) return [];
  const listed = today.workspaces.flatMap((row) => row.own ?? today.global);
  return Array.from(new Set(listed.map((key) => key.toUpperCase()))).filter((key) => !bound.includes(key)).sort();
}

/** True when this save binds the first keys of an unbound connection (asks first: it changes what other runs read). */
export const bindsFirstKeys = (before: string[], after: string[]) => before.length === 0 && after.length > 0;

/** The in-page confirmation's body for binding the first keys. */
export function firstBindingText(binding: Binding, bound: string[], leftOut: string[]): string[] {
  const plural = binding.plural.toLowerCase();
  return [
    `Binding keys changes which runs use this connection. After saving it serves only ${bound.join(", ")}, in every Workspace it is available in, and is no longer the Workspaces' unbound default.`,
    `Runs for other ${plural} no longer use it: they use the Workspace's own connector settings, or stop when those have no address. Workspaces that rely on it unbound keep their allowed ${plural} only if their keys are bound too.`,
    ...(leftOut.length ? [`No longer read through this connection: ${leftOut.join(", ")}.`] : []),
  ];
}

/** True when this save removes the last keys: the bound keys are then no longer read through this connection. */
export const unbindsAll = (before: string[], after: string[]) => before.length > 0 && after.length === 0;

/** The in-page confirmation's body for removing the last keys. */
export function unbindText(binding: Binding, before: string[]): string[] {
  const plural = binding.plural.toLowerCase();
  return [
    `Runs for ${before.join(", ")} no longer use this connection: they use another connection that serves them, or the Workspace's own connector settings.`,
    `Unbound, this connection reads only the Workspace's allowed ${plural}, and only while it is the only unbound connection of its type there.`,
  ];
}
