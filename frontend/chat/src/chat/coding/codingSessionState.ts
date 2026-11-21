// Coding session state, phase, tone, coding intent, evidence/blocker counts and next-step text.
import type {
  CodingAgentChatSession,
  CodingApprovalEvidence,
  CodingReviewSummary,
  CodingValidationEvidence,
  CodingSessionPhase,
  CodingSessionState,
  CodingSessionTone,
} from "./codingTypes";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkChangeUnit } from "../work/workPullRequestTypes";
import type { WorkItem } from "../work/workItemTypes";
import type { WorkStateEvent } from "../work/workSyncWorkflowTypes";
import { recordCount } from "./codingEvidenceModel";
import { planNextAction } from "./codingPlanLifecycle";
import { countValues, hasFailedEvidence, recordValue, type UnknownRecord } from "./codingSessionValues";

const DONE_STATES = new Set(["done", "closed", "resolved", "completed", "deployed"]);
const CANCELLED_STATES = new Set(["cancelled", "canceled", "rejected", "superseded"]);
const BLOCKED_STATES = new Set(["blocked", "failed", "error", "needs_clarification", "needs_remediation"]);
const REPLAN_STATES = new Set(["needs_replan", "needs-replan", "replan_required"]);
const HUMAN_REVIEW_STATES = new Set(["needs_human_review", "needs-human-review", "human_review_required"]);
const TEST_STATES = new Set(["testing", "validating", "validation", "qa"]);
// Source, state-event and execution states only. A Work Plan's own status is not one of them.
const REVIEW_STATES = new Set(["review", "ready_for_review", "review_ready", "in_review"]);
export function deriveCodingState({
  item,
  latestPlan,
  pullRequests,
  sourceFields,
  latestState,
  review,
}: {
  item: WorkItem;
  latestPlan: WorkChangePlan | null;
  pullRequests: string[];
  sourceFields: UnknownRecord | null;
  latestState: WorkStateEvent | null;
  review: CodingReviewSummary;
}): CodingSessionState {
  // The plan's status is deliberately not part of these values: a plan in review, with open
  // questions or rejected is planning, not delivery review, a blocked run or a cancelled item.
  const values = [
    latestState?.to_state,
    item.work_state,
    item.source_status,
    item.sync_state,
  ].map((value) => String(value || "").trim().toLowerCase());
  if (values.some((value) => CANCELLED_STATES.has(value))) {
    return "cancelled";
  }
  if (values.some((value) => DONE_STATES.has(value))) {
    return "completed";
  }
  if (values.some((value) => REPLAN_STATES.has(value)) || sourceFields?.requires_replan === true) {
    return "needs_replan";
  }
  if (
    values.some((value) => HUMAN_REVIEW_STATES.has(value)) ||
    sourceFields?.source_evidence_stale === true
  ) {
    return "needs_human_review";
  }
  if (hasFailedEvidence(item.source_fields) || values.some((value) => BLOCKED_STATES.has(value))) {
    return "blocked";
  }
  // A current negative work review (backend verdict for the latest plan) ranks exactly here: after
  // terminal, replan, human-review and execution-blocked states.
  if (values.includes("changes_requested") || review.status === "block") {
    return "changes_requested";
  }
  if (pullRequests.length > 0) {
    return "pr_open";
  }
  if (values.some((value) => TEST_STATES.has(value))) {
    return "testing";
  }
  if (values.some((value) => value.includes("implement"))) {
    return "implementing";
  }
  if (values.some((value) => REVIEW_STATES.has(value))) {
    return "review_ready";
  }
  if (latestPlan?.status === "approved") {
    return "approved";
  }
  if (latestPlan) {
    return "planned";
  }
  return "draft";
}

export function hasCodingIntent({
  item,
  sourceFields,
  latestPlan,
  repositories,
  branches,
  pullRequests,
  signalCount,
  agentSessions,
}: {
  item: WorkItem;
  sourceFields: UnknownRecord | null;
  latestPlan: WorkChangePlan | null;
  repositories: string[];
  branches: string[];
  pullRequests: string[];
  signalCount: number;
  agentSessions: CodingAgentChatSession[];
}): boolean {
  if (agentSessions.length > 0) {
    return true;
  }
  if (item.automation_eligibility?.requested) {
    return true;
  }
  if (latestPlan || repositories.length > 0 || branches.length > 0 || pullRequests.length > 0) {
    return true;
  }
  if (signalCount > 0) {
    return true;
  }
  return [
    sourceFields?.coding_session,
    sourceFields?.coding_pipeline,
    sourceFields?.execution_runs,
    sourceFields?.agent_runs,
    sourceFields?.code_changes,
    sourceFields?.review_feedback,
  ].some((value) => countValues(value) > 0);
}

export function codingRecordedEvidenceCount({
  sourceFields,
  pullRequests,
  validation,
  approvals,
  stateEvents,
}: {
  sourceFields: UnknownRecord | null;
  pullRequests: string[];
  validation: CodingValidationEvidence;
  approvals: CodingApprovalEvidence;
  stateEvents: WorkStateEvent[];
}): number {
  return (
    pullRequests.length +
    (validation.results.recorded ?? 0) +
    (approvals.recorded ?? 0) +
    stateEvents.length +
    // Only well-formed records in explicit lists; object keys or bare values are never records.
    recordCount(sourceFields?.pipeline_runs) +
    recordCount(sourceFields?.ci_runs) +
    recordCount(sourceFields?.execution_runs) +
    recordCount(sourceFields?.audit_timeline)
  );
}

export function codingBlockerCount({
  item,
  latestPlan,
  sourceFields,
  stateEvents,
}: {
  item: WorkItem;
  latestPlan: WorkChangePlan | null;
  sourceFields: UnknownRecord | null;
  stateEvents: WorkStateEvent[];
}): number {
  return (
    countValues(sourceFields?.blockers) +
    countValues(sourceFields?.open_questions) +
    countValues(latestPlan?.open_questions) +
    stateEvents.reduce((total, event) => total + countValues(recordValue(event.conflict)?.blockers), 0) +
    (item.automation_eligibility?.blocking_reasons.length || 0)
  );
}

export function phaseForState(state: CodingSessionState, latestPlan: WorkChangePlan | null): CodingSessionPhase {
  if (["blocked", "needs_human_review", "needs_replan", "changes_requested"].includes(state)) return "blocked";
  if (state === "completed" || state === "cancelled") return "completed";
  if (state === "testing") return "validating";
  if (state === "pr_open" || state === "review_ready") return "reviewing";
  if (state === "implementing") return "implementing";
  if (state === "approved") return "ready_to_implement";
  if (latestPlan || state === "planned") return "planning";
  return "ready_to_plan";
}

export function nextActionForSession({
  phase,
  latestPlan,
  repositories,
  branches,
  pullRequests,
  blockerCount,
}: {
  phase: CodingSessionPhase;
  latestPlan: WorkChangePlan | null;
  repositories: string[];
  branches: string[];
  pullRequests: string[];
  blockerCount: number;
}): string {
  // Blockers beyond the plan's own questions come first; the plan's questions are its next step.
  if (blockerCount - countValues(latestPlan?.open_questions) > 0) return "Resolve blockers or ask for clarification";
  const planAction = phase === "planning" ? planNextAction(latestPlan) : null;
  if (planAction) return planAction;
  if (blockerCount > 0) return "Resolve blockers or ask for clarification";
  if (phase === "ready_to_plan") return "Create a change plan and select repositories";
  if (phase === "planning" && !latestPlan) return "Capture implementation plan";
  if (phase === "planning" && repositories.length === 0) return "Assign repository profile";
  if (phase === "ready_to_implement" && branches.length === 0) return "Create governed branch/workspace";
  if (phase === "implementing") return "Apply code changes and stream progress";
  if (phase === "validating") return "Run required checks and collect evidence";
  if (phase === "reviewing" && pullRequests.length === 0) return "Prepare pull request or review package";
  if (phase === "reviewing") return "Review PR and handle feedback";
  if (phase === "completed") return "Audit final evidence";
  return "Inspect session evidence";
}

/**
 * What an ended (completed or cancelled) session left behind, in one line: its plan, its changes and its pull
 * requests, or that no change was made. Read from the records the session carries, never from intent.
 */
export function sessionOutcome({
  state,
  latestPlan,
  changeUnits,
  agentSessions,
  pullRequests,
}: {
  state: "completed" | "cancelled";
  latestPlan: WorkChangePlan | null;
  changeUnits: WorkChangeUnit[];
  agentSessions: CodingAgentChatSession[];
  pullRequests: string[];
}): string {
  const ended = state === "completed" ? "Completed" : "Cancelled";
  const prs = pullRequests.length;
  const changed = prs > 0 || changeUnits.length > 0 || agentSessions.length > 0;
  if (!latestPlan && !changed) return `${ended}. No change was made in this session.`;
  const parts = [
    latestPlan ? `plan v${latestPlan.version}` : "",
    prs ? `${prs} pull request${prs === 1 ? "" : "s"}` : changed ? "changes recorded, no pull request" : "no code change",
  ].filter(Boolean);
  return `${ended} · ${parts.join(" · ")}`;
}

export function toneForState(state: CodingSessionState): CodingSessionTone {
  if (["blocked", "cancelled", "changes_requested"].includes(state)) {
    return state === "blocked" ? "danger" : "attention";
  }
  if (["needs_replan", "needs_human_review"].includes(state)) {
    return "attention";
  }
  if (["implementing", "testing", "pr_open"].includes(state)) {
    return "running";
  }
  if (["completed", "approved", "review_ready"].includes(state)) {
    return "active";
  }
  return "neutral";
}

export function labelForState(state: CodingSessionState): string {
  return state.replaceAll("_", " ");
}
