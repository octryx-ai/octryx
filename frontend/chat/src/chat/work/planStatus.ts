// Shared Work Plan status vocabulary: every Work and Coding view reads its
// labels, order and final states from here.

export const PLAN_STATUS = {
  draft: "draft",
  readyForReview: "ready_for_review",
  needsClarification: "needs_clarification",
  approved: "approved",
  rejected: "rejected",
  superseded: "superseded",
} as const;

export type PlanStatus = (typeof PLAN_STATUS)[keyof typeof PLAN_STATUS];

/** The order statuses are listed in (the review queue first). */
export const PLAN_STATUS_ORDER: readonly string[] = [
  PLAN_STATUS.readyForReview,
  PLAN_STATUS.needsClarification,
  PLAN_STATUS.draft,
  PLAN_STATUS.approved,
  PLAN_STATUS.rejected,
  PLAN_STATUS.superseded,
];

/** A plan in one of these states is decided; it offers no further decision. */
export const FINAL_PLAN_STATUSES: ReadonlySet<string> = new Set([PLAN_STATUS.approved, PLAN_STATUS.rejected, PLAN_STATUS.superseded]);

const LABELS: Record<string, string> = {
  [PLAN_STATUS.readyForReview]: "Waiting for review",
  [PLAN_STATUS.needsClarification]: "Needs clarification · waiting on author",
  [PLAN_STATUS.draft]: "Draft",
  [PLAN_STATUS.approved]: "Approved",
  [PLAN_STATUS.rejected]: "Rejected",
  [PLAN_STATUS.superseded]: "Superseded",
};

export function planStatusLabel(status: string): string {
  return LABELS[status] ?? (status ? status.replaceAll("_", " ") : "No status");
}
