// Routing by type after the triage, per Workspace (spec B/C §1). Pure: no requests, no React.
//
// Backend (workflow_runs/triage_routing.py, Project.config.triage_routing):
//   GET/PUT /api/v1/workflow-runs/triage-routing?project_id=… -> {project_id, routes, defaults, effective, source,
//   can_edit}. `routes` is the Workspace's own layer over `defaults` ({type: workflow_key | null}; null switches a type
//   off). PUT {routes} replaces that layer, so only what differs from the defaults is sent. A triage definition's
//   outcome node may carry its own `routing` block, which overrides this per run (no canvas editor for it yet).

export const TRIAGE_ROUTING_PATH = "/api/v1/workflow-runs/triage-routing";
export const NO_FOLLOW_UP = "";

export type RouteRow = { type: string; workflowKey: string };
export type TriageRouting = { rows: RouteRow[]; defaults: Record<string, string>; canEdit: boolean };

const TYPE = /^[a-z][a-z0-9_-]{0,39}$/;
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export const triageRoutingPath = (projectId: string) =>
  `${TRIAGE_ROUTING_PATH}?project_id=${encodeURIComponent(projectId)}`;

/** The effective routes as rows (a switched-off type shows "No follow-up"); null when the answer is not ours. */
export function readTriageRouting(payload: unknown): TriageRouting | null {
  if (!isRecord(payload) || !isRecord(payload.effective) || !isRecord(payload.defaults)) return null;
  const defaults = Object.fromEntries(Object.entries(payload.defaults)
    .filter((entry): entry is [string, string] => typeof entry[1] === "string"));
  const rows = Object.entries(payload.effective).map(([type, key]) => ({
    type,
    workflowKey: typeof key === "string" ? key : NO_FOLLOW_UP,
  }));
  return { rows, defaults, canEdit: payload.can_edit !== false };
}

/** Why the rows cannot be saved; null when they can. */
export function triageRoutingError(rows: RouteRow[]): string | null {
  const types = rows.map((row) => row.type.trim().toLowerCase());
  if (types.some((type) => !TYPE.test(type))) return "Name each type in lower case (letters, digits, - or _).";
  if (new Set(types).size !== types.length) return "Each type appears once.";
  if (rows.some((row) => row.workflowKey === "jira-intake-triage")) return "A type never routes back to the triage.";
  return null;
}

/** The Workspace layer to PUT: only what differs from the defaults; a removed default type is switched off. */
export function triageRoutingPayload(rows: RouteRow[], defaults: Record<string, string>): { routes: Record<string, string | null> } {
  const routes: Record<string, string | null> = {};
  for (const row of rows) {
    const type = row.type.trim().toLowerCase();
    const key = row.workflowKey.trim() || null;
    if (defaults[type] !== undefined && defaults[type] === key) continue;
    routes[type] = key;
  }
  for (const type of Object.keys(defaults)) {
    if (!rows.some((row) => row.type.trim().toLowerCase() === type)) routes[type] = null;
  }
  return { routes };
}
