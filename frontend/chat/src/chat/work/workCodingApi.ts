// Work API calls for coding pipelines, CI/CD traces and findings, coding review events and the coding audit.
import { readJson } from "../../admin/utils/adminPanelHelpers";
import type { WorkCicdFindingsPayload, WorkCicdPipelineTracesPayload } from "./workCicdTypes";
import type { WorkCodingPipelineConfig, WorkCodingPipelineTrace } from "./workCodingPipelineTypes";
import type { WorkCodingAuditEvent, WorkCodingAuditReport, WorkCodingReviewEvent, WorkCodingReviewEventsPayload } from "./workCodingReviewTypes";

export async function loadCodingPipelines(): Promise<WorkCodingPipelineConfig[]> {
  const payload = await readJson<{ items: WorkCodingPipelineConfig[] }>(
    "/api/v1/secure-work/coding-pipelines?include_inactive=true",
  );
  return payload.items || [];
}

export async function saveCodingPipeline(
  payload: Partial<WorkCodingPipelineConfig>,
): Promise<WorkCodingPipelineConfig> {
  const configId = payload.id;
  return readJson<WorkCodingPipelineConfig>(
    configId ? `/api/v1/secure-work/coding-pipelines/${configId}` : "/api/v1/secure-work/coding-pipelines",
    {
      method: configId ? "PUT" : "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function loadCodingPipelineTrace(workItemId: string): Promise<WorkCodingPipelineTrace> {
  return readJson<WorkCodingPipelineTrace>(`/api/v1/secure-work/work-items/${workItemId}/coding-pipeline`);
}

export async function loadWorkItemCicdPipelineTraces(workItemId: string): Promise<WorkCicdPipelineTracesPayload> {
  return readJson<WorkCicdPipelineTracesPayload>(
    `/api/v1/secure-work/work-items/${workItemId}/cicd-pipeline-traces`,
  );
}

export async function loadWorkItemCicdFindings(workItemId: string): Promise<WorkCicdFindingsPayload> {
  return readJson<WorkCicdFindingsPayload>(
    `/api/v1/secure-work/work-items/${workItemId}/cicd-findings`,
  );
}

export async function loadCodingReviewEvents(workItemId: string): Promise<WorkCodingReviewEventsPayload> {
  return readJson<WorkCodingReviewEventsPayload>(
    `/api/v1/secure-work/work-items/${workItemId}/coding-review-events`,
  );
}

export async function createCodingReviewEvent(
  workItemId: string,
  payload: Partial<WorkCodingReviewEvent> & {
    event_type: WorkCodingReviewEvent["event_type"];
    file_path: string;
    body: string;
    decision?: "approved" | "changes_requested" | "rejected";
    change_plan_id?: string;
    expected_plan_version?: number;
    expected_change_unit_marker?: string | null;
  },
): Promise<WorkCodingReviewEvent> {
  return readJson<WorkCodingReviewEvent>(
    `/api/v1/secure-work/work-items/${workItemId}/coding-review-events`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function loadCodingAuditReport(workItemId: string): Promise<WorkCodingAuditReport> {
  return readJson<WorkCodingAuditReport>(`/api/v1/secure-work/work-items/${workItemId}/coding-audit`);
}

export async function createCodingAuditEvent(
  workItemId: string,
  payload: Partial<WorkCodingAuditEvent> & {
    event_type: string;
    title: string;
  },
): Promise<WorkCodingAuditEvent> {
  return readJson<WorkCodingAuditEvent>(
    `/api/v1/secure-work/work-items/${workItemId}/coding-audit/events`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function evaluateCodingQualityGates(
  workItemId: string,
  payload: Record<string, unknown> = {},
): Promise<WorkCodingAuditReport> {
  return readJson<WorkCodingAuditReport>(
    `/api/v1/secure-work/work-items/${workItemId}/coding-quality-gates/evaluate`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
