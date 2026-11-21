import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkChangeUnit } from "../work/workPullRequestTypes";
import type { WorkCodingReviewEvent } from "../work/workCodingReviewTypes";

// Explicit review decisions. A decision covers one exact plan version and one whole active
// Change Unit, or the whole Work Item when it has no active units; it is never a file comment and it
// is not bound to a pull-request commit. The server checks the same scope again before writing.

export type ReviewDecision = "approved" | "changes_requested" | "rejected";

export const REVIEW_DECISION_OPTIONS: Array<{ value: ReviewDecision; label: string }> = [
  { value: "approved", label: "Approve" },
  { value: "changes_requested", label: "Request changes" },
  { value: "rejected", label: "Reject" },
];

export const WHOLE_ITEM_SUBJECT = "__work_item__";

// `marker` is the displayed unit state (its serialized updated_at); the server refuses a decision
// when the unit changed since then. The whole Work Item has no marker.
export type ReviewDecisionSubject = { value: string; label: string; changeUnitId: string | null; marker: string | null };

type ReviewableUnit = WorkChangeUnit & { updated_at?: string | null };

const SUPERSEDED_UNIT_STATUS = "superseded";

export function activeChangeUnits(units: WorkChangeUnit[]): WorkChangeUnit[] {
  return units.filter((unit) => unit.status !== SUPERSEDED_UNIT_STATUS);
}

// Active units are the subjects; without any, the only subject is the whole Work Item.
export function reviewDecisionSubjects(units: WorkChangeUnit[]): ReviewDecisionSubject[] {
  const active = activeChangeUnits(units);
  if (active.length === 0) return [{ value: WHOLE_ITEM_SUBJECT, label: "Whole Work Item", changeUnitId: null, marker: null }];
  return active.map((unit: ReviewableUnit) => ({
    value: unit.id,
    label: `Change Unit ${unit.repository_name} · ${unit.branch_name}`,
    changeUnitId: unit.id,
    marker: typeof unit.updated_at === "string" && unit.updated_at ? unit.updated_at : null,
  }));
}

export type ReviewDecisionPayload = {
  event_type: "review_decision";
  decision: ReviewDecision;
  change_plan_id: string;
  expected_plan_version: number;
  change_unit_id: string | null;
  expected_change_unit_marker: string | null;
  file_path: string;
  body: string;
  metadata: Record<string, unknown>;
};

// The request body, built from the plan and subject the reviewer actually sees; null when incomplete.
export function buildReviewDecisionPayload({
  plan,
  subject,
  decision,
  note,
}: {
  plan: Pick<WorkChangePlan, "id" | "version"> | null;
  subject: ReviewDecisionSubject | null;
  decision: ReviewDecision | "";
  note: string;
}): ReviewDecisionPayload | null {
  if (!plan || !subject || !decision) return null;
  // A unit decision needs the displayed unit state; without it nothing is sent.
  if (subject.changeUnitId && !subject.marker) return null;
  return {
    event_type: "review_decision",
    decision,
    change_plan_id: plan.id,
    expected_plan_version: plan.version,
    change_unit_id: subject.changeUnitId,
    expected_change_unit_marker: subject.changeUnitId ? subject.marker : null,
    file_path: "",
    body: note.trim(),
    metadata: { source: "coding_review_decision_panel" },
  };
}

export type RecordedReviewDecision = {
  id: string;
  decision: ReviewDecision;
  changeUnitId: string | null;
  // The reviewer label the server recorded with the decision (bounded), never the raw user id.
  reviewer: string;
  createdAt: string | null;
};

const REVIEWER_LABEL_LIMIT = 120;

// Explicit decisions recorded for this plan version (the server-owned record), newest first.
export function decisionsForPlan(events: WorkCodingReviewEvent[], planId: string | null): RecordedReviewDecision[] {
  if (!planId) return [];
  const decisions: RecordedReviewDecision[] = [];
  for (const event of events) {
    const record = event.metadata && typeof event.metadata === "object"
      ? (event.metadata as Record<string, unknown>).review_decision_record
      : null;
    if (!record || typeof record !== "object" || Array.isArray(record)) continue;
    const fields = record as Record<string, unknown>;
    const decision = fields.decision;
    if (fields.change_plan_id !== planId || !REVIEW_DECISION_OPTIONS.some((option) => option.value === decision)) continue;
    decisions.push({
      id: event.id,
      decision: decision as ReviewDecision,
      changeUnitId: typeof fields.change_unit_id === "string" ? fields.change_unit_id : null,
      reviewer: typeof fields.actor_label === "string" && fields.actor_label.trim()
        ? fields.actor_label.trim().slice(0, REVIEWER_LABEL_LIMIT)
        : "Reviewer",
      createdAt: event.created_at ?? null,
    });
  }
  return decisions.sort((left, right) => String(right.createdAt || "").localeCompare(String(left.createdAt || "")));
}

export function decisionLabel(decision: ReviewDecision): string {
  return REVIEW_DECISION_OPTIONS.find((option) => option.value === decision)?.label ?? decision;
}
