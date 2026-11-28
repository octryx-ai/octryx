// The seat's API equivalent is a column apart, never summed into the API cost.
import { NO_SEAT, readSeat, type SeatFigures } from "../../../chat/cost/seatEquivalent";
import { costText } from "./operationsWords";

export const COST_GROUPS = ["workflow", "work_item", "run", "person", "workspace"] as const;
export type CostGroup = (typeof COST_GROUPS)[number];

export const GROUP_TABS: { key: CostGroup; label: string }[] = [
  { key: "workflow", label: "Workflow" },
  { key: "work_item", label: "Work item" },
  { key: "run", label: "Run" },
  { key: "person", label: "Person" },
  { key: "workspace", label: "Workspace" },
];

export const PERIODS = [7, 30, 90] as const;
export const PERIOD_TABS = PERIODS.map((days) => ({ key: String(days), label: `${days} days` }));

export type CostRow = {
  key: string;
  label: string;
  runs: number;
  delivered: number;
  pullRequests: number;
  costUsd: number;
  costPerDeliveredUsd: number | null;
  seat: SeatFigures;
};

export type CostReport = { days: number; from: string | null; to: string | null; group: CostGroup; totals: CostRow; rows: CostRow[] };

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const num = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);
const perDelivered = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

export function isCostGroup(value: string): value is CostGroup {
  return (COST_GROUPS as readonly string[]).includes(value);
}

export function workflowWords(key: string): string {
  const words = key.replace(/[-_]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

const NONE: Record<CostGroup, string> = {
  workflow: "No workflow",
  work_item: "No work item",
  run: "Run",
  person: "Nobody named",
  workspace: "No Workspace",
};

function rowOf(value: unknown, group: CostGroup): CostRow | null {
  const item = record(value);
  if (!item) return null;
  const key = text(item.key);
  const none = !key || key === "-";
  const label = none ? NONE[group] : group === "workflow" ? workflowWords(text(item.label) || key) : text(item.label) || key;
  return {
    key: none ? "" : key,
    label,
    runs: num(item.runs),
    delivered: num(item.delivered),
    pullRequests: num(item.pull_requests),
    costUsd: num(item.cost_usd),
    costPerDeliveredUsd: perDelivered(item.cost_per_delivered_usd),
    seat: readSeat(item, "seat_api_equivalent_usd", "seat_unpriced_calls"),
  };
}

export function readCosts(payload: unknown, asked: CostGroup): CostReport {
  const body = record(payload);
  const window = record(body?.window);
  const group = isCostGroup(text(body?.group)) ? (text(body?.group) as CostGroup) : asked;
  const rows = (Array.isArray(body?.groups) ? body.groups : [])
    .map((row) => rowOf(row, group))
    .filter((row): row is CostRow => row !== null)
    .sort((a, b) => b.costUsd - a.costUsd);
  const totals = rowOf({ key: "total", label: "Total", ...(record(body?.totals) ?? {}) }, group)
    ?? { key: "total", label: "Total", runs: 0, delivered: 0, pullRequests: 0, costUsd: 0, costPerDeliveredUsd: null, seat: NO_SEAT };
  return {
    days: num(window?.days) || 0,
    from: text(window?.from) || null,
    to: text(window?.to) || null,
    group,
    totals: { ...totals, key: "total", label: "Total" },
    rows,
  };
}

/** "—" when nothing was delivered, never 0 or infinity. */
export function perDeliveredText(row: Pick<CostRow, "delivered" | "costPerDeliveredUsd">): string {
  return row.delivered > 0 && row.costPerDeliveredUsd !== null ? costText(row.costPerDeliveredUsd) : "—";
}

export function costCell(usd: number): string {
  return costText(usd) || "$0.00";
}

export function deliveredText(row: Pick<CostRow, "runs" | "delivered">): string {
  return `${row.delivered} of ${row.runs}`;
}

export type CostLink = { kind: "run"; runId: string } | { kind: "href"; href: string } | null;

export function rowLink(group: CostGroup, row: Pick<CostRow, "key">, workspaceId = ""): CostLink {
  if (!row.key || row.key === "total") return null;
  if (group === "run") return { kind: "run", runId: row.key };
  if (group === "work_item") {
    const params = new URLSearchParams({ area: "work", work_item_id: row.key });
    if (workspaceId) params.set("workspace_id", workspaceId);
    return { kind: "href", href: `/chat?${params.toString()}` };
  }
  return null;
}

export function mainSessionOf(payload: unknown): string {
  const run = record(record(payload)?.run);
  const sessions = Array.isArray(run?.sessions) ? run.sessions.map(record).filter(Boolean) as Record<string, unknown>[] : [];
  const main = sessions.filter((item) => item.role === "main").pop() ?? sessions[0];
  return main ? text(main.session_id) : "";
}

export function periodText(report: Pick<CostReport, "days">): string {
  return `Runs started in the last ${report.days} days, sorted by API cost. A seat call costs the platform nothing; `
    + "its column shows what it would cost via the API at list price, apart from the API cost.";
}
