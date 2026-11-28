// Write-back belongs to the Workspace's work item workflow (422 write_back_on_workflow), so it is never sent.
import type { AvailableIn, ConnectionDetail, ToolLevel } from "./connectionsModel";
import { formatBoundKeys, parseBoundKeys } from "./boundScopes";
import { splitValues, type AccessField, type Binding } from "./connectionTypes";

export type Pair = { source: string; ours: string };

export type ConnectionDraft = {
  name: string; access: Record<string, string>; secrets: Record<string, string>;
  availableIn: AvailableIn; workspaceIds: string[];
  boundScopes: string;
  knowledgeEnabled: boolean; knowledgeSchedule: string; knowledgeCron: string; knowledgeScopeKey: string; knowledgeScope: string;
  ticketsEnabled: boolean; ticketsSchedule: string; ticketsCron: string; ticketsFilter: string; statusMap: Pair[];
  toolLevel: ToolLevel;
};

type Rec = Record<string, unknown>;
const rec = (value: unknown): Rec | null => (value && typeof value === "object" && !Array.isArray(value) ? value as Rec : null);
const str = (value: unknown): string => (typeof value === "string" ? value : "");

function scopeValues(scope: unknown, key: string): string {
  const value = rec(scope)?.[key];
  return Array.isArray(value) ? value.map(String).join(", ") : typeof value === "string" ? value : "";
}

export function draftOf(detail: ConnectionDetail, scopeKey = ""): ConnectionDraft {
  return {
    name: detail.name, access: { ...detail.access.values }, secrets: {},
    availableIn: detail.availableIn, workspaceIds: detail.workspaces.map((ref) => ref.id),
    boundScopes: formatBoundKeys(detail.boundScopes),
    knowledgeEnabled: detail.knowledge?.enabled ?? false, knowledgeSchedule: detail.knowledge?.schedule ?? "",
    knowledgeCron: detail.knowledge?.scheduleCron ?? "",
    knowledgeScopeKey: scopeKey, knowledgeScope: scopeKey ? scopeValues(detail.knowledge?.scope, scopeKey) : "",
    ticketsEnabled: detail.tickets?.enabled ?? false, ticketsSchedule: detail.tickets?.schedule ?? "",
    ticketsCron: detail.tickets?.scheduleCron ?? "",
    ticketsFilter: detail.tickets?.filter ?? "",
    statusMap: (detail.tickets?.statusMap ?? []).map((row) => ({ ...row })),
    toolLevel: detail.agentTools?.level ?? "off",
  };
}

const clean = (rows: Pair[]) => rows.map((row) => ({ source: row.source.trim(), ours: row.ours.trim() }))
  .filter((row) => row.source || row.ours);
const samePairs = (left: Pair[], right: Pair[]) => JSON.stringify(clean(left)) === JSON.stringify(clean(right));
const sameSet = (left: string[], right: string[]) => left.length === right.length && left.every((id) => right.includes(id));

function scheduleChanges(target: Rec, schedule: string, cron: string, nextSchedule: string, nextCron: string) {
  if (nextSchedule !== schedule) target.schedule = nextSchedule;
  if (nextSchedule === "custom" && (nextSchedule !== schedule || nextCron.trim() !== cron.trim())) {
    target.schedule = "custom";
    target.schedule_cron = nextCron.trim();
  }
}

export function accessValueOf(field: AccessField | undefined, text: string): unknown {
  if (field?.kind === "bool") return text === "true";
  if (field?.kind === "list") return splitValues(text);
  if (field?.kind === "int" && /^\d+$/.test(text.trim())) return Number(text.trim());
  return text.trim();
}

export function changesOf(before: ConnectionDraft, after: ConnectionDraft, scope: unknown = null, fields: AccessField[] = [],
  binding: Binding | null = null): Rec {
  const body: Rec = {};
  if (after.name !== before.name) body.name = after.name.trim();
  const access: Rec = {};
  for (const [key, value] of Object.entries(after.access)) {
    if ((before.access[key] ?? "") !== value) access[key] = accessValueOf(fields.find((field) => field.key === key), value);
  }
  for (const [key, value] of Object.entries(after.secrets)) if (value.trim()) access[key] = value;
  if (Object.keys(access).length) body.access = access;
  if (after.availableIn !== before.availableIn || !sameSet(after.workspaceIds, before.workspaceIds)) {
    body.available_in = after.availableIn;
    body.workspaces = after.availableIn === "all" ? [] : after.workspaceIds;
  }
  if (binding) {
    const keys = parseBoundKeys(after.boundScopes, binding);
    if (formatBoundKeys(keys) !== formatBoundKeys(parseBoundKeys(before.boundScopes, binding))) body.bound_scopes = keys;
  }

  const uses: Rec = {};
  const knowledge: Rec = {};
  if (after.knowledgeEnabled !== before.knowledgeEnabled) knowledge.enabled = after.knowledgeEnabled;
  scheduleChanges(knowledge, before.knowledgeSchedule, before.knowledgeCron, after.knowledgeSchedule, after.knowledgeCron);
  if (after.knowledgeScopeKey && after.knowledgeScope !== before.knowledgeScope) {
    // The whole scope object replaces the stored one, so keys this page does not edit are copied in.
    knowledge.scope = { ...(rec(scope) ?? {}), [after.knowledgeScopeKey]: splitValues(after.knowledgeScope) };
  }
  if (Object.keys(knowledge).length) uses.knowledge = knowledge;

  const tickets: Rec = {};
  if (after.ticketsEnabled !== before.ticketsEnabled) tickets.enabled = after.ticketsEnabled;
  scheduleChanges(tickets, before.ticketsSchedule, before.ticketsCron, after.ticketsSchedule, after.ticketsCron);
  if (after.ticketsFilter !== before.ticketsFilter) tickets.filter = after.ticketsFilter.trim();
  if (!samePairs(after.statusMap, before.statusMap)) tickets.status_map = clean(after.statusMap);
  if (Object.keys(tickets).length) uses.tickets = tickets;

  if (after.toolLevel !== before.toolLevel) uses.agent_tools = { level: after.toolLevel };
  if (Object.keys(uses).length) body.uses = uses;
  return body;
}

const DEFAULT_MESSAGES: Record<string, string> = {
  deviation_not_narrower: "A workspace may only narrow this connection, not widen it.",
  scope_outside_connection: "This is outside what the connection may read.",
  schedule_cron_invalid: "Use five cron fields that run at most every 15 minutes, e.g. */30 * * * *.",
  status_unknown: "Choose one of our ticket states for each row.",
  use_not_linked: "This connection has no such use linked yet; set it up in the Workspace first.",
  use_spans_workspaces: "This use runs in several Workspaces; change it in each Workspace.",
  write_back_on_workflow: "Write-back is set in the Workspace's work item workflow, not here.",
  connection_name_taken: "Another connection already has this name.",
  connection_name_invalid: "Give the connection a name of up to the allowed length.",
  connection_type_unknown: "Choose one of the connection types.",
  platform_admin_required: "Only platform admins may change this.",
};

export function fieldErrorsOf(payload: unknown): { field: string; message: string; code: string } {
  const detail = rec(rec(payload)?.detail);
  const code = str(detail?.code);
  const fallback = DEFAULT_MESSAGES[code] ?? "This change was refused.";
  let field = str(detail?.field);
  if (!field && code === "scope_outside_connection") field = "uses.knowledge.scope";
  if (!field && code === "status_unknown") field = "uses.tickets.status_map";
  return { field, message: str(detail?.message) || (typeof rec(payload)?.detail === "string" ? str(rec(payload)?.detail) : fallback), code };
}

export type AccessValue = { values: Record<string, string>; secrets: Record<string, string> };

export function accessBodyOf(fields: AccessField[], value: AccessValue): Rec {
  const body: Rec = {};
  for (const [key, text] of Object.entries(value.values)) {
    if (text.trim()) body[key] = accessValueOf(fields.find((field) => field.key === key), text);
  }
  for (const [key, text] of Object.entries(value.secrets)) if (text.trim()) body[key] = text;
  return body;
}

export function missingAccess(fields: AccessField[], value: AccessValue, stored: Record<string, boolean> = {}): AccessField[] {
  return fields.filter((field) => field.required && field.kind !== "bool" && (field.secret
    ? !stored[field.key] && !(value.secrets[field.key] ?? "").trim()
    : !(value.values[field.key] ?? "").trim()));
}

export type PairLabels = { title: string; left: string; right: string; leftKey: keyof Pair; rightKey: keyof Pair; empty: string;
  leftPlaceholder: string; rightPlaceholder: string };

export const STATUS_MAP_LABELS: PairLabels = {
  title: "Status mapping", left: "In the source", right: "Here", leftKey: "source", rightKey: "ours",
  empty: "No status is mapped yet.", leftPlaceholder: "e.g. In Review", rightPlaceholder: "Choose a state",
};
export const WRITE_BACK_LABELS: PairLabels = {
  title: "Write back", left: "When here", right: "Move the source to", leftKey: "ours", rightKey: "source",
  empty: "No transition is set yet.", leftPlaceholder: "Choose a state", rightPlaceholder: "e.g. Done",
};
