import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkCodingAuditReport } from "../work/workCodingReviewTypes";
import type { CodingReviewSummary, CodingReviewVerdict } from "./codingTypes";

// A value counts only when complete and bound to the latest plan; anything else is unavailable, never zero blockers.

const VERDICTS: ReadonlySet<string> = new Set(["pass", "block", "review_required", "missing"]);
// The list's blocking means a negative review; the audit gate also blocks on missing.
const LIST_BLOCKING: ReadonlySet<string> = new Set(["block"]);
const AUDIT_GATE_BLOCKING: ReadonlySet<string> = new Set(["block", "missing"]);

export function unavailableReview(cause: Extract<CodingReviewSummary, { status: "unavailable" }>["cause"]): CodingReviewSummary {
  return { status: "unavailable", cause };
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function boundTo(status: string, planId: unknown, planVersion: unknown, latestPlan: WorkChangePlan | null): boolean {
  if (!latestPlan) return status === "missing" && planId == null && planVersion == null;
  return planId === latestPlan.id && planVersion === latestPlan.version;
}

function verdict(status: string, reason: string, latestPlan: WorkChangePlan | null): CodingReviewSummary {
  return {
    status: status as CodingReviewVerdict,
    reason,
    planId: latestPlan?.id ?? null,
    planVersion: latestPlan?.version ?? null,
  };
}

export function reviewSummaryFromCandidate(raw: unknown, latestPlan: WorkChangePlan | null): CodingReviewSummary {
  const summary = record(raw);
  if (!summary) return unavailableReview("not_loaded");
  const { status, reason, blocking, basis } = summary;
  if (basis !== "reviewer_approval" || typeof status !== "string" || !VERDICTS.has(status)) return unavailableReview("invalid");
  if (typeof reason !== "string" || blocking !== LIST_BLOCKING.has(status)) return unavailableReview("invalid");
  if (!boundTo(status, summary.plan_id, summary.plan_version, latestPlan)) return unavailableReview("invalid");
  return verdict(status, reason, latestPlan);
}

export function reviewSummaryFromAuditReport(report: WorkCodingAuditReport | null, latestPlan: WorkChangePlan | null): CodingReviewSummary {
  if (!report) return unavailableReview("not_loaded");
  const gates = Array.isArray(report.quality_gates) ? report.quality_gates : [];
  const matching = gates.filter((gate) => record(gate)?.key === "reviewer_approval");
  if (matching.length !== 1) return unavailableReview("invalid");
  const gate = matching[0];
  const evidence = record(gate.evidence);
  if (typeof gate.status !== "string" || !VERDICTS.has(gate.status) || typeof gate.reason !== "string" || !evidence) {
    return unavailableReview("invalid");
  }
  if (gate.blocking !== AUDIT_GATE_BLOCKING.has(gate.status)) return unavailableReview("invalid");
  if (!boundTo(gate.status, evidence.plan_id, evidence.plan_version, latestPlan)) return unavailableReview("invalid");
  return verdict(gate.status, gate.reason, latestPlan);
}

// An unavailable review may hide a blocker, so the count never reads as "no blockers".
export function blockerCountText(count: number, review: CodingReviewSummary, noun = true): string {
  const unknown = review.status === "unavailable";
  const blockers = count === 1 ? "blocker" : "blockers";
  if (noun) return unknown ? `${count} known ${blockers} (work review unknown)` : `${count} ${blockers}`;
  return unknown ? `${count} known (work review unknown)` : String(count);
}

export function reviewSummaryLabel(review: CodingReviewSummary): string {
  switch (review.status) {
    case "block":
      return "Work review: changes requested or rejected";
    case "pass":
      return "Work review: approved (not PR readiness)";
    case "review_required":
      return "Work review: incomplete";
    case "missing":
      return "Work review: no decision recorded";
    default:
      if (review.cause === "refreshing") return "Work review: updating after the new decision…";
      if (review.cause === "refresh_failed") return "Work review: unavailable, the update after the new decision failed";
      return "Work review: unavailable";
  }
}
