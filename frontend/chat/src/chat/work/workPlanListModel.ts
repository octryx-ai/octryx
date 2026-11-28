import type { WorkChangePlanListQuery } from "./workPlanListTypes";
import { PLAN_STATUS_ORDER as STATUS_ORDER, planStatusLabel } from "./planStatus";

// The review queue is the backend's queue=review; statuses are never mapped to queue membership here.
export type WorkPlanListMode = "plans" | "reviews";

export type WorkPlanListFilter = {
  status: string;
  showSuperseded: boolean;
};

export const DEFAULT_PLAN_LIST_FILTER: WorkPlanListFilter = { status: "", showSuperseded: false };

export function planListQuery(mode: WorkPlanListMode, filter: WorkPlanListFilter, cursor?: string | null): WorkChangePlanListQuery {
  if (mode === "reviews") return { queue: "review", cursor };
  const status = filter.status === "superseded" && !filter.showSuperseded ? "" : filter.status;
  return { statuses: status ? [status] : [], includeSuperseded: filter.showSuperseded, cursor };
}

export function planStatusChips(counts: Record<string, number>): Array<{ status: string; label: string; count: number }> {
  const known = STATUS_ORDER.filter((status) => status in counts);
  const other = Object.keys(counts).filter((status) => !STATUS_ORDER.includes(status)).sort();
  return [...known, ...other].map((status) => ({ status, label: planStatusLabel(status), count: counts[status] ?? 0 }));
}

export function planTotal(counts: Record<string, number>): number {
  return Object.values(counts).reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0);
}

export function reviewDemandText(counts: Record<string, number>): string {
  const waiting = counts.ready_for_review ?? 0;
  if (waiting === 0) return "No Change Plan is waiting for a reviewer decision.";
  return `${waiting} Change Plan${waiting === 1 ? " is" : "s are"} waiting for a reviewer decision.`;
}

export type WorkPlanEmptyState = { title: string; body: string; openWorkItems?: boolean };

export function planListEmptyState(mode: WorkPlanListMode, filter: WorkPlanListFilter): WorkPlanEmptyState {
  if (mode === "reviews") {
    return {
      title: "No Change Plan is waiting for review.",
      body: "Plans appear here when they are ready for a reviewer's decision.",
    };
  }
  if (filter.status) {
    return {
      title: `No Change Plans with status “${planStatusLabel(filter.status)}”.`,
      body: "Choose another status, or show all Change Plans.",
    };
  }
  return { title: "No plans yet.", body: "Plans are created from a work item.", openWorkItems: true };
}

export function errorMessage(err: unknown, fallback: string): string {
  const message = err && typeof err === "object" && "message" in err ? (err as { message?: unknown }).message : null;
  return typeof message === "string" && message ? message : fallback;
}
