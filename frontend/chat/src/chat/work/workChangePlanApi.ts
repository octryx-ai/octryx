// Work API calls for change units, reviewer choice and change plans.
import { readJson } from "../../admin/utils/adminPanelHelpers";
import type { WorkChangePlan, WorkChangePlanDecision } from "./workChangePlanTypes";
import type { WorkChangeUnit, WorkReviewerOverride, WorkReviewerRecommendationPayload } from "./workPullRequestTypes";

export async function loadWorkItemChangeUnits(workItemId: string): Promise<WorkChangeUnit[]> {
  const payload = await readJson<{ items: WorkChangeUnit[] }>(
    `/api/v1/secure-work/work-items/${workItemId}/change-units`,
  );
  return payload.items || [];
}

export async function planWorkItemChangeUnits({
  workItemId,
  units,
}: {
  workItemId: string;
  units: Array<Record<string, unknown>>;
}): Promise<WorkChangeUnit[]> {
  const payload = await readJson<{ items: WorkChangeUnit[] }>(
    `/api/v1/secure-work/work-items/${workItemId}/change-units/plan`,
    {
      method: "POST",
      body: JSON.stringify({ units, replace_existing: true }),
    },
  );
  return payload.items || [];
}

export async function loadReviewerRecommendations(workItemId: string): Promise<WorkReviewerRecommendationPayload> {
  return readJson<WorkReviewerRecommendationPayload>(
    `/api/v1/secure-work/work-items/${workItemId}/reviewer-recommendations`,
  );
}

export async function applyReviewerOverride({
  workItemId,
  selectedUserId,
  selectedReviewer,
  reason,
  changeUnitId,
  evidence,
}: {
  workItemId: string;
  selectedUserId?: string | null;
  selectedReviewer?: string;
  reason: string;
  changeUnitId?: string | null;
  evidence?: Record<string, unknown>;
}): Promise<WorkReviewerOverride> {
  return readJson<WorkReviewerOverride>(
    `/api/v1/secure-work/work-items/${workItemId}/reviewer-overrides`,
    {
      method: "POST",
      body: JSON.stringify({
        selected_user_id: selectedUserId,
        selected_reviewer: selectedReviewer,
        reason,
        change_unit_id: changeUnitId,
        evidence: evidence || {},
      }),
    },
  );
}

export async function loadWorkItemChangePlans(workItemId: string): Promise<WorkChangePlan[]> {
  const payload = await readJson<{ items: WorkChangePlan[] }>(
    `/api/v1/secure-work/work-items/${workItemId}/change-plans`,
  );
  return payload.items || [];
}

export async function generateWorkItemChangePlan({
  workItemId,
  workflowId,
  targetState,
  title,
  understoodRequest,
  assumptions,
  openQuestions,
  validationPlan,
  rollbackPlan,
  traceRefs,
}: {
  workItemId: string;
  workflowId?: string | null;
  targetState?: string;
  title?: string;
  understoodRequest?: string;
  assumptions?: string[];
  openQuestions?: string[];
  validationPlan?: string[];
  rollbackPlan?: string;
  traceRefs?: Array<Record<string, unknown>>;
}): Promise<WorkChangePlan> {
  return readJson<WorkChangePlan>(
    `/api/v1/secure-work/work-items/${workItemId}/change-plans/generate`,
    {
      method: "POST",
      body: JSON.stringify({
        workflow_id: workflowId,
        target_state: targetState || "ready_for_review",
        title,
        understood_request: understoodRequest,
        assumptions: assumptions || [],
        open_questions: openQuestions || [],
        validation_plan: validationPlan || [],
        rollback_plan: rollbackPlan,
        trace_refs: traceRefs || [],
      }),
    },
  );
}

export async function generateWorkItemLlmWorkPlan({
  workItemId,
  workflowId,
  targetState,
  approvalBaseUrl,
}: {
  workItemId: string;
  workflowId?: string | null;
  targetState?: string;
  approvalBaseUrl?: string;
}): Promise<WorkChangePlan> {
  return readJson<WorkChangePlan>(
    `/api/v1/secure-work/work-items/${workItemId}/work-plans/generate`,
    {
      method: "POST",
      body: JSON.stringify({
        workflow_id: workflowId,
        target_state: targetState || "ready_for_review",
        approval_base_url: approvalBaseUrl,
      }),
    },
  );
}

// Answers to the exact plan version's open questions; the result is the revised version.
export async function answerWorkPlanClarifications({
  changePlanId,
  expectedLatestVersion,
  answers,
}: {
  changePlanId: string;
  expectedLatestVersion: number;
  answers: Array<{ question_index: number; question: string; answer: string }>;
}): Promise<WorkChangePlan> {
  return readJson<WorkChangePlan>(
    `/api/v1/secure-work/change-plans/${encodeURIComponent(changePlanId)}/clarification-answers`,
    {
      method: "POST",
      body: JSON.stringify({ expected_latest_version: expectedLatestVersion, answers }),
    },
  );
}

export async function decideWorkChangePlan({
  changePlanId,
  action,
  reason,
  requiredChanges,
  workflowId,
  targetState,
}: {
  changePlanId: string;
  action: WorkChangePlanDecision["action"];
  reason: string;
  requiredChanges?: string[];
  workflowId?: string | null;
  targetState?: string;
}): Promise<{ plan: WorkChangePlan; decision: WorkChangePlanDecision }> {
  return readJson<{ plan: WorkChangePlan; decision: WorkChangePlanDecision }>(
    `/api/v1/secure-work/change-plans/${changePlanId}/decision`,
    {
      method: "POST",
      body: JSON.stringify({
        action,
        reason,
        required_changes: requiredChanges || [],
        workflow_id: workflowId,
        target_state: targetState,
        evidence: { source: "work_detail_ui" },
      }),
    },
  );
}
