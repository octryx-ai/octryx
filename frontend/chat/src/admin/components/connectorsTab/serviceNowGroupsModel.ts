import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";

// The ServiceNow connector's record limit (follow-ups C and 2): assignment groups, services and how they
// combine. Pure: no requests, no React.
//
// Backend (services/servicenow_record_limit.py): `servicenow_assignment_groups` and `servicenow_services` are lists of
// names or sys_ids (32 hex characters); empty or absent means no condition on that field. At most 50 entries, each
// non-empty and at most 100 characters, without '^', ',', control characters or "javascript:"; duplicates count
// case-insensitively. `servicenow_filter_mode`: "all" (default; group AND service) or "any" (at least one list
// matches; never a record outside both lists). Names match case-insensitively with whitespace collapsed. The same
// rules hold for the intake's `assignment_groups`/`services` overrides, which may only narrow the connector's lists.
// The admin draft is Record<string, string>: each list is kept there as a JSON array (as the draft's prefill does).
//
// Known values (read-only suggestions): GET /admin/chat/api/panel/connectors/servicenow/limit-values (platform admin,
// the global connection, no limit) and GET /api/v1/secure-work/servicenow-intake/{project_id}/limit-values (Workspace
// admin, inside the connector's limit) -> {table, scanned, assignment_groups: [{name, count}], services: [...]}.

export const GROUPS_FIELD = "servicenow_assignment_groups";
export const SERVICES_FIELD = "servicenow_services";
export const MODE_FIELD = "servicenow_filter_mode";
export const LIMIT_FIELDS = [GROUPS_FIELD, SERVICES_FIELD, MODE_FIELD] as const;
export const FILTER_MODES = ["all", "any"] as const;
export type FilterMode = (typeof FILTER_MODES)[number];
export const MAX_GROUPS = 50;
export const MAX_GROUP_CHARS = 100;
export const GROUPS_HELP =
  "Only incidents, changes and records of these assignment groups are read (chat, Knowledge MCP, source sync, intake). " +
  "Names or sys_ids. Empty: no limit.";
export const SERVICES_HELP =
  "Only records of these services are read (Table API: business_service; Scripted REST: service). Names or sys_ids. " +
  "Empty: no limit.";
export const MODE_HELP: Record<FilterMode, string> = {
  all: "Both must match: a record of one of the groups AND one of the services.",
  any: "Either may match: a record of one of the groups OR one of the services (never one outside both lists).",
};

export type LimitNoun = "group" | "service";
export type KnownValue = { name: string; count: number };
export type KnownValues = { groups: KnownValue[]; services: KnownValue[]; scanned: number };

// eslint-disable-next-line no-control-regex
const FORBIDDEN = /[\^,\u0000-\u001f\u007f]|javascript:/i;

const textList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string" && entry.trim() !== "").map((entry) => entry.trim()) : [];

/** One entry as the backend stores it: whitespace runs collapsed to one space. */
export function normalizeGroup(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ");
}

/** Why `entry` cannot be added to `current`, or null. */
export function groupEntryProblem(entry: string, current: readonly string[], noun: LimitNoun = "group"): string | null {
  const group = normalizeGroup(entry);
  if (!group) return `Enter a ${noun} name or sys_id.`;
  if (entry.trim().length > MAX_GROUP_CHARS) return `A ${noun} has at most ${MAX_GROUP_CHARS} characters.`;
  if (FORBIDDEN.test(group)) return `A ${noun} must not contain ^, a comma, control characters or "javascript:".`;
  if (current.some((existing) => existing.toLowerCase() === group.toLowerCase())) return `This ${noun} is already in the list.`;
  if (current.length >= MAX_GROUPS) return `At most ${MAX_GROUPS} ${noun}s.`;
  return null;
}

/** `current` with `entry` added, or the reason it is not. */
export function addGroup(current: readonly string[], entry: string, noun: LimitNoun = "group"): { groups: string[]; problem: string | null } {
  const problem = groupEntryProblem(entry, current, noun);
  return problem ? { groups: [...current], problem } : { groups: [...current, normalizeGroup(entry)], problem: null };
}

export function removeGroup(current: readonly string[], index: number): string[] {
  return current.filter((_, at) => at !== index);
}

/** The stored list of `field` (connector.public_fields); [] when none or not a list. */
export function storedGroups(connector: Pick<AdminConnector, "public_fields">, field: string = GROUPS_FIELD): string[] {
  return textList(connector.public_fields?.[field]);
}

/** The list being edited: the draft's JSON array, else the stored list. */
export function draftGroups(connector: Pick<AdminConnector, "public_fields">, draft: Record<string, string>, field: string = GROUPS_FIELD): string[] {
  const value = draft[field];
  if (value === undefined || value.trim() === "") return value === undefined ? storedGroups(connector, field) : [];
  try {
    return textList(JSON.parse(value));
  } catch {
    return storedGroups(connector, field);
  }
}

export const groupsDraftValue = (groups: readonly string[]) => JSON.stringify(groups);

/** The stored mode ("all" unless "any" is stored). */
export function storedMode(connector: Pick<AdminConnector, "public_fields">): FilterMode {
  return connector.public_fields?.[MODE_FIELD] === "any" ? "any" : "all";
}

/** The mode being edited: the draft's, else the stored one. */
export function draftMode(connector: Pick<AdminConnector, "public_fields">, draft: Record<string, string>): FilterMode {
  const value = draft[MODE_FIELD];
  return value === "any" || value === "all" ? value : storedMode(connector);
}

function listSaveFields(connector: AdminConnector, draft: Record<string, string>, field: string): Record<string, unknown> {
  if (draft[field] === undefined) return {};
  const groups = draftGroups(connector, draft, field);
  if (groups.length) return { [field]: groups };
  return storedGroups(connector, field).length ? { [field]: [] } : {};
}

/**
 * The limit part of the save body. Per list: the list when it has entries; [] when the admin removed every stored
 * entry; nothing when the list is empty and nothing is stored (an untouched save changes nothing). The mode only when
 * the admin changed it.
 */
export function serviceNowGroupsSaveFields(connector: AdminConnector, draft: Record<string, string>): Record<string, unknown> {
  const mode = draft[MODE_FIELD];
  return {
    ...listSaveFields(connector, draft, GROUPS_FIELD),
    ...listSaveFields(connector, draft, SERVICES_FIELD),
    ...((mode === "all" || mode === "any") && mode !== storedMode(connector) ? { [MODE_FIELD]: mode } : {}),
  };
}

/** How the limit reads in words, for both settings: null without any list. */
export function limitSummary(groups: readonly string[], services: readonly string[], mode: FilterMode): string | null {
  if (!groups.length && !services.length) return null;
  if (!groups.length) return `Only the services ${services.join(", ")}.`;
  if (!services.length) return `Only the assignment groups ${groups.join(", ")}.`;
  const join = mode === "any" ? "or" : "and";
  return `Only the assignment groups ${groups.join(", ")} ${join} the services ${services.join(", ")}.`;
}

const knownList = (value: unknown): KnownValue[] =>
  (Array.isArray(value) ? value : [])
    .filter((entry): entry is Record<string, unknown> => typeof entry === "object" && entry !== null)
    .map((entry) => ({ name: typeof entry.name === "string" ? entry.name.trim() : "", count: typeof entry.count === "number" ? entry.count : 0 }))
    .filter((entry) => entry.name !== "");

/** The known-values answer; null when it is not one. */
export function readKnownValues(payload: unknown): KnownValues | null {
  if (typeof payload !== "object" || payload === null) return null;
  const record = payload as Record<string, unknown>;
  if (!Array.isArray(record.assignment_groups) && !Array.isArray(record.services)) return null;
  return {
    groups: knownList(record.assignment_groups),
    services: knownList(record.services),
    scanned: typeof record.scanned === "number" ? record.scanned : 0,
  };
}

/** Suggestions not yet in `current` (case-insensitive), most frequent first, as "name" options. */
export function suggestionsFor(known: readonly KnownValue[], current: readonly string[]): KnownValue[] {
  const taken = new Set(current.map((entry) => normalizeGroup(entry).toLowerCase()));
  return known.filter((entry) => !taken.has(normalizeGroup(entry.name).toLowerCase()));
}
