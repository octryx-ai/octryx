import { askReporterPath } from "../../../admin/components/securityControls/securityControlsModel";
import { readJson } from "../../../admin/utils/adminPanelHelpers";

// The incident and ServiceNow intake routes. Answers are parsed by the models; refusals keep their
// HTTP status and code on the error (readJson).

const item = (id: string) => `/api/v1/secure-work/work-items/${encodeURIComponent(id)}`;
// Backend routes/secure_work_servicenow.py: /servicenow-intake/{project_id}[/preview|/sync|/runs].
const intake = (projectId: string) => `/api/v1/secure-work/servicenow-intake/${encodeURIComponent(projectId)}`;
// Work-item analysis settings (Project.config.work_item_analysis) endpoint helper.
const analysisSettings = (projectId: string) => `/api/v1/secure-work/work-item-analysis-settings/${encodeURIComponent(projectId)}`;

export function loadAnalysis(workItemId: string): Promise<unknown> {
  return readJson<unknown>(`${item(workItemId)}/analysis`);
}

export function startAnalysis(workItemId: string): Promise<unknown> {
  return readJson<unknown>(`${item(workItemId)}/analyze`, { method: "POST", body: JSON.stringify({}) });
}

// A person posts the reporter questions an automatic analysis only proposed (no body).
export function askReporter(workItemId: string, analysisId: string): Promise<unknown> {
  return readJson<unknown>(askReporterPath(workItemId, analysisId), { method: "POST" });
}

// Section C: without `confirm` the server only answers what would be sent (needs_confirmation); with it, it posts.
const worknoteBody = (noteAt: string | null, confirm: boolean) => JSON.stringify({ ...(noteAt ? { note_at: noteAt } : {}), confirm });

export function previewWorknote(workItemId: string, noteAt: string | null): Promise<unknown> {
  return readJson<unknown>(`${item(workItemId)}/servicenow-worknote`, { method: "POST", body: worknoteBody(noteAt, false) });
}

export function sendWorknote(workItemId: string, noteAt: string | null): Promise<unknown> {
  return readJson<unknown>(`${item(workItemId)}/servicenow-worknote`, { method: "POST", body: worknoteBody(noteAt, true) });
}

export function loadServiceNowIntake(projectId: string): Promise<unknown> {
  return readJson<unknown>(intake(projectId));
}

/** The groups and services of the Workspace's recent records, inside the connector's limit (admin; suggestions). */
export const serviceNowLimitValuesUrl = (projectId: string) => `${intake(projectId)}/limit-values`;

export function previewServiceNowIntake(projectId: string): Promise<unknown> {
  return readJson<unknown>(`${intake(projectId)}/preview`, { method: "POST", body: JSON.stringify({}) });
}

export function syncServiceNowIntake(projectId: string): Promise<unknown> {
  return readJson<unknown>(`${intake(projectId)}/sync`, { method: "POST", body: JSON.stringify({}) });
}

export function loadServiceNowIntakeRuns(projectId: string): Promise<unknown> {
  return readJson<unknown>(`${intake(projectId)}/runs`);
}

export function loadAnalysisSettings(projectId: string): Promise<unknown> {
  return readJson<unknown>(analysisSettings(projectId));
}

export function saveAnalysisSettings(projectId: string, settings: Record<string, unknown>): Promise<unknown> {
  return readJson<unknown>(analysisSettings(projectId), { method: "PUT", body: JSON.stringify(settings) });
}
