import { stringifyLimitField } from "../projectsTab/projectConnectorLimitCodec";
import type { Binding } from "./connectionTypes";

export const MAX_BOUND_KEYS = 100;

export function parseBoundKeys(text: string, binding: Pick<Binding, "upper"> | null): string[] {
  const keys = text.split(/[\s,;]+/).map((part) => part.trim()).filter(Boolean)
    .map((key) => (binding?.upper === false ? key : key.toUpperCase()));
  return Array.from(new Set(keys));
}

export const formatBoundKeys = (keys: string[]) => keys.join(", ");

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

export const emptyListText = (binding: Binding) =>
  (binding.servesUnlisted ? `every ${binding.label.toLowerCase()}` : `no ${binding.label.toLowerCase()}`);

export type WorkspaceAllowlist = { workspace: { id: string; name: string }; own: string[] | null };
export type UnboundToday = { workspaces: WorkspaceAllowlist[]; global: string[] };

const keysOf = (field: string, value: unknown) => stringifyLimitField(field, value).split("\n").filter(Boolean);

type Rec = Record<string, unknown>;
const rec = (value: unknown): Rec | null => (value && typeof value === "object" && !Array.isArray(value) ? value as Rec : null);

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

export function unboundTodayText(today: UnboundToday, binding: Binding): string {
  const parts = today.workspaces.map((row) => `${row.workspace.name} → ${row.own === null ? "global list" : listText(row.own, binding)}`);
  return `Today, unbound: ${[...parts, `global → ${listText(today.global, binding)}`].join("; ")}`;
}

export function keysLeftOut(today: UnboundToday | null, bound: string[]): string[] {
  if (!today) return [];
  const listed = today.workspaces.flatMap((row) => row.own ?? today.global);
  return Array.from(new Set(listed.map((key) => key.toUpperCase()))).filter((key) => !bound.includes(key)).sort();
}

export const bindsFirstKeys = (before: string[], after: string[]) => before.length === 0 && after.length > 0;

export function firstBindingText(binding: Binding, bound: string[], leftOut: string[]): string[] {
  const plural = binding.plural.toLowerCase();
  return [
    `Binding keys changes which runs use this connection. After saving it serves only ${bound.join(", ")}, in every Workspace it is available in, and is no longer the Workspaces' unbound default.`,
    `Runs for other ${plural} no longer use it: they use the Workspace's own connector settings, or stop when those have no address. Workspaces that rely on it unbound keep their allowed ${plural} only if their keys are bound too.`,
    ...(leftOut.length ? [`No longer read through this connection: ${leftOut.join(", ")}.`] : []),
  ];
}

export const unbindsAll = (before: string[], after: string[]) => before.length > 0 && after.length === 0;

export function unbindText(binding: Binding, before: string[]): string[] {
  const plural = binding.plural.toLowerCase();
  return [
    `Runs for ${before.join(", ")} no longer use this connection: they use another connection that serves them, or the Workspace's own connector settings.`,
    `Unbound, this connection reads only the Workspace's allowed ${plural}, and only while it is the only unbound connection of its type there.`,
  ];
}
