import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";

// Mirrors backend servicenow_record_limit.py; the string draft keeps each list as a JSON array.

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

export function normalizeGroup(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ");
}

export function groupEntryProblem(entry: string, current: readonly string[], noun: LimitNoun = "group"): string | null {
  const group = normalizeGroup(entry);
  if (!group) return `Enter a ${noun} name or sys_id.`;
  if (entry.trim().length > MAX_GROUP_CHARS) return `A ${noun} has at most ${MAX_GROUP_CHARS} characters.`;
  if (FORBIDDEN.test(group)) return `A ${noun} must not contain ^, a comma, control characters or "javascript:".`;
  if (current.some((existing) => existing.toLowerCase() === group.toLowerCase())) return `This ${noun} is already in the list.`;
  if (current.length >= MAX_GROUPS) return `At most ${MAX_GROUPS} ${noun}s.`;
  return null;
}

export function addGroup(current: readonly string[], entry: string, noun: LimitNoun = "group"): { groups: string[]; problem: string | null } {
  const problem = groupEntryProblem(entry, current, noun);
  return problem ? { groups: [...current], problem } : { groups: [...current, normalizeGroup(entry)], problem: null };
}

export function removeGroup(current: readonly string[], index: number): string[] {
  return current.filter((_, at) => at !== index);
}

export function storedGroups(connector: Pick<AdminConnector, "public_fields">, field: string = GROUPS_FIELD): string[] {
  return textList(connector.public_fields?.[field]);
}

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

export function storedMode(connector: Pick<AdminConnector, "public_fields">): FilterMode {
  return connector.public_fields?.[MODE_FIELD] === "any" ? "any" : "all";
}

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

// [] clears stored entries; an empty list with nothing stored is omitted so an untouched save changes nothing.
export function serviceNowGroupsSaveFields(connector: AdminConnector, draft: Record<string, string>): Record<string, unknown> {
  const mode = draft[MODE_FIELD];
  return {
    ...listSaveFields(connector, draft, GROUPS_FIELD),
    ...listSaveFields(connector, draft, SERVICES_FIELD),
    ...((mode === "all" || mode === "any") && mode !== storedMode(connector) ? { [MODE_FIELD]: mode } : {}),
  };
}

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

export function suggestionsFor(known: readonly KnownValue[], current: readonly string[]): KnownValue[] {
  const taken = new Set(current.map((entry) => normalizeGroup(entry).toLowerCase()));
  return known.filter((entry) => !taken.has(normalizeGroup(entry.name).toLowerCase()));
}
