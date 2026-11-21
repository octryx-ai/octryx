// Admin › Connections. One connection = type + access + where it
// is available + its uses (Knowledge, Tickets, Agent tools, Repositories). Every field name the page relies on is
// read here; the page never computes the effective
// value (the server's effective() does).
import type { StatusTone } from "../../../layout/StatusLabel";
import { humanize, scheduleText } from "./connectionTypes";

export type WorkspaceRef = { id: string; name: string };
export type ConnectionState = "ok" | "failing" | "untested" | "disabled";
export type ToolLevel = "off" | "read" | "write";
export type AvailableIn = "all" | "selected";

export type ConnectionRow = {
  id: string; type: string; name: string; state: ConnectionState; stateReason: string;
  lastTestedAt: string | null; availableIn: AvailableIn; workspaces: WorkspaceRef[];
  uses: { knowledge: boolean; tickets: boolean; agentTools: ToolLevel };
  owner: { kind: "platform" | "workspace"; workspace: WorkspaceRef | null }; canEdit: boolean;
  deviationCount: number; problemsCount: number;
};

// `values` holds the non-secret access fields as the server sends them in access.fields (keyed like the type's
// access_fields; bools as "true"/"false", lists joined with ", "); `secrets` says per secret field whether one is
// stored (access.secrets). A secret value is never read back.
export type Access = { baseUrl: string; auth: string; account: string; secretSet: boolean; values: Record<string, string>;
  secrets: Record<string, boolean> };
export type KnowledgeUse = { enabled: boolean; scope: unknown; schedule: string; scheduleCron: string; lastSyncAt: string | null;
  lastSyncState: string; items: number | null };
export type Intake = { id: string; name: string; workspace: WorkspaceRef | null; enabled: boolean; schedule: string;
  scheduleCron: string; lastSyncAt: string | null; lastSyncStatus: string };
export type TicketsUse = { enabled: boolean; filter: string; schedule: string; scheduleCron: string;
  statusMap: Array<{ source: string; ours: string }>;
  // Write-back belongs to the Workspace's work item workflow (422 write_back_on_workflow): shown here, never sent.
  writeBack: { enabled: boolean; transitions: Array<{ ours: string; source: string }> };
  // The intakes behind this use: each row has its own "Sync now".
  intakes: Intake[] };
export type AgentToolsUse = { level: ToolLevel; tools: Array<{ name: string; level: ToolLevel }> };
export type Repository = { name: string; build: string; test: string; owners: string[]; branchRule: string };
// canEdit: deviations[].can_edit — whether this person may reset this workspace's deviation (platform admins, and
// the workspace's own admin for its own deviation); null when the server does not say, then the connection's.
export type Deviation = { workspace: WorkspaceRef; fields: Record<string, unknown>; canEdit: boolean | null };
// code: the fixed code when the server sends one (tooltip); message: the sentence, or a bare code (errorSentence).
export type RecentError = { at: string | null; use: string; message: string; code: string };

export type ConnectionDetail = Omit<ConnectionRow, "uses" | "deviationCount" | "problemsCount"> & {
  access: Access;
  // The keys this connection serves (bound_scopes); [] = not bound.
  boundScopes: string[];
  knowledge: KnowledgeUse | null; tickets: TicketsUse | null; agentTools: AgentToolsUse | null;
  repositories: Repository[]; deviations: Deviation[]; recentErrors: RecentError[];
};

export type TestResult = { state: ConnectionState; stateReason: string; testedAt: string | null;
  checks: Array<{ use: string; ok: boolean; message: string }> };

type Rec = Record<string, unknown>;
const rec = (value: unknown): Rec | null => (value && typeof value === "object" && !Array.isArray(value) ? value as Rec : null);
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** One access field value as the form edits it (text). */
function fieldText(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (Array.isArray(value)) return value.map(String).join(", ");
  return null;
}

const STATES: ConnectionState[] = ["ok", "failing", "untested", "disabled"];
const LEVELS: ToolLevel[] = ["off", "read", "write"];
const state = (value: unknown): ConnectionState => (STATES.includes(value as ConnectionState) ? value as ConnectionState : "untested");
const level = (value: unknown): ToolLevel => (LEVELS.includes(value as ToolLevel) ? value as ToolLevel : "off");

function workspace(value: unknown): WorkspaceRef | null {
  const row = rec(value);
  return row && str(row.id) ? { id: str(row.id), name: str(row.name) || str(row.id) } : null;
}
const workspaces = (value: unknown): WorkspaceRef[] => list(value).map(workspace).filter((ref): ref is WorkspaceRef => ref !== null);

function base(row: Rec) {
  const owner = rec(row.owner);
  return {
    id: str(row.id), type: str(row.type), name: str(row.name) || str(row.id),
    state: state(row.state), stateReason: str(row.state_reason), lastTestedAt: str(row.last_tested_at) || null,
    availableIn: (row.available_in === "all" ? "all" : "selected") as AvailableIn, workspaces: workspaces(row.workspaces),
    owner: { kind: (owner?.kind === "workspace" ? "workspace" : "platform") as "platform" | "workspace", workspace: workspace(owner?.workspace) },
    // A server that does not say otherwise answers a platform admin, who may edit.
    canEdit: row.can_edit !== false,
  };
}

export function readConnectionList(payload: unknown): ConnectionRow[] {
  return list(rec(payload)?.connections).map((entry) => {
    const row = rec(entry);
    if (!row || !str(row.id)) return null;
    const uses = rec(row.uses);
    return { ...base(row),
      uses: { knowledge: uses?.knowledge === true, tickets: uses?.tickets === true, agentTools: level(uses?.agent_tools) },
      deviationCount: num(row.deviation_count) ?? 0, problemsCount: num(row.problems_count) ?? 0 };
  }).filter((row): row is ConnectionRow => row !== null);
}

export function readConnectionDetail(payload: unknown): ConnectionDetail | null {
  const row = rec(payload);
  if (!row || !str(row.id)) return null;
  const access = rec(row.access), uses = rec(row.uses);
  const knowledge = rec(uses?.knowledge), tickets = rec(uses?.tickets), tools = rec(uses?.agent_tools);
  const writeBack = rec(tickets?.write_back);
  return { ...base(row),
    access: { baseUrl: str(access?.base_url), auth: str(access?.auth), account: str(access?.account), secretSet: access?.secret_set === true,
      values: Object.fromEntries(Object.entries(rec(access?.fields) ?? {})
        .map(([key, value]) => [key, fieldText(value)] as const).filter((entry): entry is [string, string] => entry[1] !== null)),
      secrets: Object.fromEntries(Object.entries(rec(access?.secrets) ?? {}).map(([key, value]) => [key, value === true])) },
    boundScopes: list(row.bound_scopes).map(str).filter(Boolean),
    knowledge: knowledge ? { enabled: knowledge.enabled === true, scope: knowledge.scope ?? null, schedule: str(knowledge.schedule),
      scheduleCron: str(knowledge.schedule_cron), lastSyncAt: str(knowledge.last_sync_at) || null, lastSyncState: str(knowledge.last_sync_state), items: num(knowledge.items) } : null,
    tickets: tickets ? { enabled: tickets.enabled === true, filter: str(tickets.filter), schedule: str(tickets.schedule),
      scheduleCron: str(tickets.schedule_cron), statusMap: list(tickets.status_map).map((entry) => ({ source: str(rec(entry)?.source), ours: str(rec(entry)?.ours) })),
      writeBack: { enabled: writeBack?.enabled === true,
        transitions: list(writeBack?.transitions).map((entry) => ({ ours: str(rec(entry)?.ours), source: str(rec(entry)?.source) })) },
      intakes: list(tickets.intakes).map((entry) => {
        const intake = rec(entry);
        return intake && str(intake.intake_id) ? { id: str(intake.intake_id), name: str(intake.name), workspace: workspace(intake.workspace),
          enabled: intake.enabled !== false, schedule: str(intake.schedule), scheduleCron: str(intake.schedule_cron),
          lastSyncAt: str(intake.last_sync_at) || null, lastSyncStatus: str(intake.last_sync_status) } : null;
      }).filter((intake): intake is Intake => intake !== null) } : null,
    agentTools: tools ? { level: level(tools.level),
      tools: list(tools.tools).map((entry) => ({ name: str(rec(entry)?.name), level: level(rec(entry)?.level) })).filter((tool) => tool.name) } : null,
    repositories: list(uses?.repositories).map((entry) => {
      const repo = rec(entry) ?? {};
      return { name: str(repo.name), build: str(repo.build), test: str(repo.test),
        owners: list(repo.owners).map(str).filter(Boolean), branchRule: str(repo.branch_rule) };
    }).filter((repo) => repo.name),
    deviations: list(row.deviations).map((entry) => {
      const deviation = rec(entry), ref = workspace(deviation?.workspace);
      const canEdit = deviation?.can_edit;
      return ref ? { workspace: ref, fields: rec(deviation?.fields) ?? {}, canEdit: typeof canEdit === "boolean" ? canEdit : null } : null;
    }).filter((deviation): deviation is Deviation => deviation !== null),
    recentErrors: list(row.recent_errors).map((entry) => ({ at: str(rec(entry)?.at) || null, use: str(rec(entry)?.use),
      message: str(rec(entry)?.message), code: str(rec(entry)?.code) })).filter((error) => error.message || error.code),
  };
}

export function readTestResult(payload: unknown): TestResult {
  const row = rec(payload) ?? {};
  return { state: state(row.state), stateReason: str(row.state_reason), testedAt: str(row.tested_at) || null,
    checks: list(row.checks).map((entry) => ({ use: str(rec(entry)?.use), ok: rec(entry)?.ok === true, message: str(rec(entry)?.message) })) };
}

// ---- words ---------------------------------------------------------------------------------------------------

const STATE_WORDS: Record<ConnectionState, { label: string; tone: StatusTone }> = {
  ok: { label: "Working", tone: "neutral" },
  failing: { label: "Failing", tone: "problem" },
  untested: { label: "Not tested", tone: "attention" },
  disabled: { label: "Off", tone: "neutral" },
};
export const stateWord = (value: ConnectionState) => STATE_WORDS[value];

export function availableInText(availableIn: AvailableIn, refs: WorkspaceRef[]): string {
  if (availableIn === "all") return "All workspaces";
  if (refs.length === 0) return "No workspace";
  return refs.length <= 2 ? refs.map((ref) => ref.name).join(", ") : `${refs.length} workspaces`;
}

export function usesText(uses: ConnectionRow["uses"]): string {
  const parts = [uses.knowledge ? "Knowledge" : "", uses.tickets ? "Tickets" : "", uses.agentTools !== "off" ? `Tools: ${uses.agentTools}` : ""];
  return parts.filter(Boolean).join(" · ") || "—";
}

/** Whether this person may reset a workspace's deviation: its can_edit, else the connection's. */
export const canResetDeviation = (detail: ConnectionDetail, deviation: Deviation) => deviation.canEdit ?? detail.canEdit;

/** One readable line for a deviation's fields, e.g. "Knowledge scope: BRD-sub · Tickets schedule: Off". */
export function deviationText(fields: Record<string, unknown>): string {
  const flat: string[] = [];
  const walk = (prefix: string, value: unknown) => {
    const row = rec(value);
    if (row) Object.entries(row).forEach(([key, inner]) => walk(prefix ? `${prefix} ${key}` : key, inner));
    else flat.push(`${humanize(prefix.replace(/\./g, " ").replace(/agent_tools/, "tools"))}: ${Array.isArray(value) ? value.join(", ") : scheduleText(String(value))}`);
  };
  Object.entries(fields).forEach(([key, value]) => walk(key, value));
  return flat.join(" · ") || "—";
}

/** The scope of a use as one line ("Projects: BRD, OPS"); the raw value stays in the tooltip. */
export function scopeText(scope: unknown): string {
  const row = rec(scope);
  if (!row) return typeof scope === "string" && scope ? scope : "Everything the connection can read";
  return Object.entries(row).map(([key, value]) => `${humanize(key)}: ${Array.isArray(value) ? value.join(", ") : String(value)}`).join(" · ") || "Everything the connection can read";
}

/** Where write-back is changed: the Workspace's work item workflow (write_back_on_workflow), today Work › write-back. */
export const writeBackHrefFor = (workspaceId: string) =>
  `/chat?area=work&work_view=writeback${workspaceId ? `&workspace_id=${encodeURIComponent(workspaceId)}` : ""}`;

/** The answer to a delete as one sentence; a connection still in use lists where (409 connection_in_use). */
export function deleteResultText(status: number, payload: unknown): { ok: boolean; text: string } {
  if (status >= 200 && status < 300) return { ok: true, text: "The connection was deleted." };
  const detail = rec(rec(payload)?.detail);
  if (str(detail?.code) === "connection_in_use") {
    const where = list(detail?.uses).map((entry) => {
      const use = rec(entry);
      return use ? `${humanize(str(use.use))}: ${str(use.name) || str(use.id)}` : "";
    }).filter(Boolean);
    return { ok: false, text: `Still used${where.length ? ` by ${where.join(", ")}` : ""}; remove or move these uses first.` };
  }
  if (status === 403) return { ok: false, text: "You may not delete this connection." };
  if (status === 404) return { ok: false, text: "This connection no longer exists." };
  return { ok: false, text: str(detail?.message) || "The connection could not be deleted." };
}

/**
 * Where "needs approval" is set today: Rules › Tool & approval policies. The one rule list filtered to a connection
 * (?tab=adminRules&connection=<id>) waits for the server's central rules.
 */
export const rulesHrefFor = (_connectionId: string) => "/chat?area=admin&tab=policies";

/** The result of an intake's "Sync now" as one sentence. */
export function intakeSyncText(status: number, payload: unknown): string {
  if (status >= 200 && status < 300) {
    const summary = rec(rec(payload)?.summary);
    const changed = num(summary?.created) ?? num(summary?.updated);
    return str(rec(payload)?.state) === "running" || changed === null ? "Sync started." : `Synced: ${changed} items changed.`;
  }
  const code = str(rec(rec(payload)?.detail)?.code) || str(rec(payload)?.detail);
  if (status === 409 || code === "intake_not_enabled") return "This intake is switched off; switch it on first.";
  if (status === 403) return "You may not sync this intake.";
  if (status === 404) return "This intake no longer exists.";
  if (status === 502) return "The source did not answer; try again later.";
  return "The sync could not be started.";
}

// ---- address -------------------------------------------------------------------------------------------------

export function readConnectionAddress(search: string): { id: string; page: boolean } {
  const params = new URLSearchParams(search);
  return { id: params.get("connection") || "", page: params.get("connection_view") === "page" };
}

export function connectionAddress(search: string, id: string, page = false): string {
  const params = new URLSearchParams(search);
  if (id) params.set("connection", id); else params.delete("connection");
  if (id && page) params.set("connection_view", "page"); else params.delete("connection_view");
  const query = params.toString();
  return query ? `?${query}` : "";
}

/**
 * The address of the connector settings page for one type: `?connector=<type>` opens
 * that connector there; the open connection is dropped so returning to Connections does not reopen its panel.
 */
export function connectorSettingsAddress(search: string, type: string): string {
  const params = new URLSearchParams(search);
  params.delete("connection");
  params.delete("connection_view");
  if (type) params.set("connector", type); else params.delete("connector");
  const query = params.toString();
  return query ? `?${query}` : "";
}

// Words that keep their capitals in a tool name.
const TOOL_WORD_CASE: Record<string, string> = { pr: "PR", prs: "PRs", url: "URL", id: "ID", ids: "IDs", api: "API", jql: "JQL", cql: "CQL" };

/**
 * A tool's function name in words, without the connection's own type:
 * add_bitbucket_pull_request_comment on a Bitbucket connection → "Add pull request comment".
 */
export function connectionToolLabel(name: string, type: string): string {
  const own = type.toLowerCase();
  const words = name.split(/[_\s-]+/).filter((word) => word && word.toLowerCase() !== own);
  if (!words.length) return name;
  const text = words.map((word) => TOOL_WORD_CASE[word.toLowerCase()] ?? word.toLowerCase()).join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
