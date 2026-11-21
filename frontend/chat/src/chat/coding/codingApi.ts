import { readJson } from "../../admin/utils/adminPanelHelpers";
import { loadRepositoryProfiles, loadWorkItems } from "../work/workApi";
import { loadCodingPipelineTrace, loadCodingAuditReport, loadCodingReviewEvents, loadWorkItemCicdFindings, loadWorkItemCicdPipelineTraces } from "../work/workCodingApi";
import { loadReviewerRecommendations, loadWorkItemChangePlans, loadWorkItemChangeUnits } from "../work/workChangePlanApi";
import { loadWorkItemStateEvents } from "../work/workTransitionApi";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkChangeUnit, WorkReviewerRecommendationPayload } from "../work/workPullRequestTypes";
import type { WorkItem } from "../work/workItemTypes";
import type { WorkRepositoryProfile } from "../work/workCodingPipelineTypes";
import type { WorkStateEvent } from "../work/workSyncWorkflowTypes";
import type { CodingSessionDetailData, WorkCodingObservability } from "./codingTypes";
import type { CodingAgentChatSession, CodingAgentExecutionResult } from "./codingTypes";

export type CodingSessionCandidate = {
  work_item: WorkItem;
  change_plans: WorkChangePlan[];
  change_units: WorkChangeUnit[];
  state_events: WorkStateEvent[];
  agent_sessions?: CodingAgentChatSession[];
  // The item's pull requests from work_pull_requests (the one PR source).
  pull_requests?: Array<{ pr_url?: string | null }>;
  // The coding audit's reviewer verdict for this item; read only through codingReviewSummary.ts.
  review_summary?: unknown;
};

/** The coding sessions of one Workspace; without a Workspace, every one the caller may see. */
export async function loadCodingWorkspaceData(projectId?: string | null): Promise<{
  items: WorkItem[];
  sessionCandidates: CodingSessionCandidate[];
  repositoryProfiles: WorkRepositoryProfile[];
}> {
  const [candidatePayload, repositoryProfiles] = await Promise.all([
    readJson<{ items: CodingSessionCandidate[] }>(
      `/api/v1/secure-work/coding-sessions?${new URLSearchParams({ limit: "1000", ...(projectId ? { project_id: projectId } : {}) })}`,
    ),
    loadRepositoryProfiles(),
  ]);
  const sessionCandidates = candidatePayload.items || [];
  return { items: sessionCandidates.map((entry) => entry.work_item), sessionCandidates, repositoryProfiles };
}

export async function loadCodingSessionDetail(
  workItemId: string,
): Promise<CodingSessionDetailData> {
  const [
    workItems,
    changePlans,
    changeUnits,
    reviewerPayload,
    stateEvents,
    pipelineTrace,
    reviewEventsPayload,
    auditReport,
    cicdPipelineTraces,
    cicdFindings,
    observability,
  ] = await Promise.all([
    loadWorkItems(),
    loadWorkItemChangePlans(workItemId),
    loadWorkItemChangeUnits(workItemId),
    loadReviewerRecommendations(workItemId).catch(() => null),
    loadWorkItemStateEvents(workItemId),
    loadCodingPipelineTrace(workItemId).catch(() => null),
    loadCodingReviewEvents(workItemId).catch(() => null),
    loadCodingAuditReport(workItemId).catch(() => null),
    loadWorkItemCicdPipelineTraces(workItemId).catch(() => null),
    loadWorkItemCicdFindings(workItemId).catch(() => null),
    loadWorkItemCodingObservability(workItemId).catch(() => null),
  ]);
  return {
    workItem: workItems.find((item) => item.id === workItemId) || null,
    changePlans,
    changeUnits,
    reviewerPayload,
    stateEvents,
    pipelineTrace,
    reviewEventsPayload,
    auditReport,
    cicdPipelineTraces,
    cicdFindings,
    observability,
  };
}

export async function loadWorkItemCodingObservability(
  workItemId: string,
): Promise<WorkCodingObservability> {
  return readJson<WorkCodingObservability>(
    `/api/v1/secure-work/work-items/${workItemId}/coding-observability`,
  );
}

export async function startCodingAgentExecution(
  workItemId: string,
  payload: {
    change_plan_id?: string;
    change_unit_ids?: string[];
    config_id?: string;
    operator_note?: string;
    restart_from_scratch?: boolean;
    restart_reason?: string;
  },
): Promise<CodingAgentExecutionResult> {
  return readJson<CodingAgentExecutionResult>(`/api/v1/secure-work/work-items/${workItemId}/coding-agent/start`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
