// Agents & workflows → Workflows: the workflows that run in phases, with class, scope and use. Pure parsing; the
// page renders it.
export const WORKFLOWS_OVERVIEW_PATH = "/api/v1/phased-workflows/overview";

// When a listed workflow last changed (its latest version) and who saved that version; null when unknown.
export type LastChange = { updatedAt: string | null; updatedBy: string | null };

// One workflow, as the list shows it.
export type FlowWorkflowRow = {
  flowId: string;
  key: string;
  title: string;
  description: string;
  capabilityClass: string;
  nodeCount: number;
  // A flow kept for testing the platform (backend overview_flows.is_test_flow); hidden unless "Show test flows".
  testFlow: boolean;
  // Switched on (new runs can start it); an optional shipped workflow starts off. A row without `is_active`: on.
  isActive: boolean;
  scope: string;
  projectId: string | null;
  used: number;
  status: string;
  version: number;
  versionStatus: string;
} & LastChange;

export type WorkflowsOverview = { flows: FlowWorkflowRow[]; usageWindowDays: number };

type Json = Record<string, unknown>;

const record = (value: unknown): Json => (value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : {});
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown): string => (typeof value === "string" ? value : value == null ? "" : String(value));
const lastChange = (row: Json): LastChange => ({ updatedAt: text(row.updated_at) || null, updatedBy: text(row.updated_by) || null });

export function readFlowWorkflowRow(raw: unknown): FlowWorkflowRow {
  const row = record(raw);
  return {
    flowId: text(row.flow_id),
    key: text(row.key),
    title: text(row.title),
    description: text(row.description),
    capabilityClass: text(row.capability_class),
    nodeCount: Number(row.node_count) || 0,
    testFlow: row.test_flow === true,
    isActive: row.is_active !== false,
    scope: text(row.scope) || "Global",
    projectId: text(row.project_id) || null,
    used: Number(row.used) || 0,
    status: text(row.status),
    version: Number(row.version) || 0,
    versionStatus: text(row.version_status),
    ...lastChange(row),
  };
}

export function readWorkflowsOverview(raw: unknown): WorkflowsOverview {
  const body = record(raw);
  return {
    flows: list(body.flows).map(readFlowWorkflowRow),
    usageWindowDays: Number(body.usage_window_days) || 30,
  };
}

export type ScopeFilter = "all" | "global" | "workspace";

export function statusLabel(row: Pick<FlowWorkflowRow, "status" | "version">): string {
  const version = row.version ? ` v${row.version}` : "";
  if (row.status === "published") return `Published${version}`;
  if (row.status === "retired") return "Retired";
  if (row.status === "archived") return "Archived";
  return `Draft${version}`;
}

// Check results: one row per checked turn, in platform chat or at octryx-claude's Stop.
export const CHECK_RESULTS_PATH = "/api/v1/workflow-checks/results";

export type CheckOutcome = { type: string; outcome: string; blocking: boolean; description: string; detail: string };

export type CheckResultRow = {
  id: string;
  sessionId: string | null;
  workflowKey: string;
  runtime: string;
  state: string;
  results: CheckOutcome[];
  createdAt: string;
};

const RUNTIME_LABELS: Record<string, string> = {
  octryx_claude: "octryx-claude",
  replay: "Replay",
  canvas: "Canvas",
};
const STATE_LABELS: Record<string, string> = { passed: "Passed", not_verified: "Not verified", stop_blocked: "Stop blocked" };

function readCheckResult(raw: unknown): CheckResultRow {
  const row = record(raw);
  return {
    id: text(row.id),
    sessionId: text(row.session_id) || null,
    workflowKey: text(row.workflow_key),
    runtime: text(row.runtime),
    state: text(row.state),
    results: list(row.results).map((item) => {
      const check = record(item);
      return {
        type: text(check.type),
        outcome: text(check.outcome),
        blocking: check.blocking === true,
        description: text(check.description),
        detail: text(check.detail),
      };
    }),
    createdAt: text(row.created_at),
  };
}

export function readCheckResults(raw: unknown): CheckResultRow[] {
  return list(record(raw).results).map(readCheckResult);
}

export const runtimeLabel = (runtime: string): string => RUNTIME_LABELS[runtime] ?? runtime;
export const checkStateLabel = (state: string): string => STATE_LABELS[state] ?? state;

// The first failed blocking check (else the first failed one), as the table's "Failed check" cell.
export function failedCheckLabel(row: CheckResultRow): string {
  const failed = row.results.filter((check) => check.outcome === "failed");
  const first = failed.find((check) => check.blocking) ?? failed[0];
  return first ? first.description || first.type : "";
}

/** Switches a workflow on or off (platform admins; backend flow_activation): only new starts change. */
export const flowActivePath = (flowId: string) => `/api/v1/flows/${encodeURIComponent(flowId)}/active`;
export const ACTIVE_SWITCH_HINT = "A workflow that is off cannot be started; runs already going keep running.";
