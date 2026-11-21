// One Workflows list with both execution kinds: workflows that run in phases and workflows that run as a flow
// (flow graphs). Pure: the list rows, the kind filter and the page's address (the list, or one open workflow on the
// canvas).
import { formatExactTime, formatRelative, timeOf } from "../../../utils/dateTime";
import { FLOW_ID_PARAM, NEW_FLOW_PARAM } from "../../../editorLinks";
import { statusLabel, type FlowWorkflowRow, type ScopeFilter, type WorkflowsOverview } from "./workflowsModel";

export type WorkflowKind = "flow" | "phased";
export type KindFilter = "all" | WorkflowKind;

export const KIND_LABELS: Record<WorkflowKind, string> = {
  flow: "Runs as a flow",
  phased: "Runs in phases",
};

export type ListedWorkflow = { kind: WorkflowKind; id: string; key: string; title: string; row: FlowWorkflowRow };

export function listedWorkflows(overview: WorkflowsOverview): ListedWorkflow[] {
  return overview.flows.map((row): ListedWorkflow => ({ kind: row.executionKind, id: row.flowId, key: row.key, title: row.title, row }));
}

export type ListFilter = {
  query: string;
  capability: string;
  scope: ScopeFilter;
  kind: KindFilter;
  // Smoke / test / validation flows stay hidden unless asked for.
  showTestFlows?: boolean;
};

export function filterListed(items: ListedWorkflow[], filter: ListFilter): ListedWorkflow[] {
  const needle = filter.query.trim().toLowerCase();
  return items.filter((item) => {
    if (filter.kind !== "all" && item.kind !== filter.kind) return false;
    const row = item.row;
    if (row.testFlow && !filter.showTestFlows) return false;
    if (filter.capability && row.capabilityClass !== filter.capability) return false;
    if (filter.scope === "global" && row.projectId) return false;
    if (filter.scope === "workspace" && !row.projectId) return false;
    return !needle || [row.key, row.title, row.description].some((value) => value.toLowerCase().includes(needle));
  });
}

export const listedStatusLabel = (item: ListedWorkflow): string => statusLabel(item.row);

const DAY = 24 * 60 * 60 * 1000;

// How long ago, always in one form: "3 h ago", "25 d ago", "4 mo ago", "2 y ago"; the exact date is the tooltip.
export function ageLabel(value: string | null | undefined, now: number = Date.now()): string {
  const time = timeOf(value ?? null);
  if (time === null) return "—";
  const days = Math.floor((now - time) / DAY);
  if (days < 7) return formatRelative(time, "—", now);
  if (days < 60) return `${days} d ago`;
  if (days < 730) return `${Math.floor(days / 30)} mo ago`;
  return `${Math.floor(days / 365)} y ago`;
}

// The "Last changed" cell ("3 h ago", "25 d ago") with the exact moment as its tooltip; "—" when unknown.
export function lastChangedLabel(item: ListedWorkflow, now: number = Date.now()): { text: string; title: string } {
  return { text: ageLabel(item.row.updatedAt, now), title: formatExactTime(item.row.updatedAt) };
}

// --- The page address: the list (`view=table`, the entry) or one open workflow on the canvas (`view=canvas` and
// its id). A flow uses `flow_id`, a workflow that runs in phases uses `phased`. ---

export const VIEW_PARAM = "view";
export const PHASED_PARAM = "phased";
export type WorkflowsListView = "table" | "canvas";
export type OpenWorkflow = { kind: WorkflowKind; id: string } | null;

// The list is the entry; the canvas only for an address that opens a workflow or creates one (`view=canvas` alone
// lands on the list).
export function readListView(search: string): WorkflowsListView {
  const creating = new URLSearchParams(search).get(NEW_FLOW_PARAM) === "1";
  return readOpenWorkflow(search) || creating ? "canvas" : "table";
}

export function readOpenWorkflow(search: string): OpenWorkflow {
  const params = new URLSearchParams(search);
  const flowId = (params.get(FLOW_ID_PARAM) ?? "").trim();
  if (flowId) return { kind: "flow", id: flowId };
  const phasedId = (params.get(PHASED_PARAM) ?? "").trim();
  return phasedId ? { kind: "phased", id: phasedId } : null;
}

// The address for a view and open workflow; other parameters (area, tab, workspace) stay.
export function listUrl(href: string, view: WorkflowsListView, open: OpenWorkflow): string {
  const url = new URL(href);
  url.searchParams.set(VIEW_PARAM, view);
  url.searchParams.delete(FLOW_ID_PARAM);
  url.searchParams.delete(PHASED_PARAM);
  const param = { flow: FLOW_ID_PARAM, phased: PHASED_PARAM } as const;
  if (open) url.searchParams.set(param[open.kind], open.id);
  return `${url.pathname}${url.search}${url.hash}`;
}

// Leaving a workflow with unsaved edits (another workflow, a new workflow, "← All workflows") waits for the page's
// ConfirmDialog: a clean editor leaves at once, a dirty one returns the action to run once confirmed.
export function requestLeave(dirty: boolean, action: () => void): (() => void) | null {
  if (!dirty) {
    action();
    return null;
  }
  return action;
}
