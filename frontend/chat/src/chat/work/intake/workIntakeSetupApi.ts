import { readJson } from "../../../admin/utils/adminPanelHelpers";
import type { IntakeDiscovery, IntakeDraft } from "./workIntakeDraft";
import { draftPayload } from "./workIntakeDraft";

const base = (workspaceId: string) => `/api/v1/secure-work/workspaces/${encodeURIComponent(workspaceId)}/intake`;
const one = (workspaceId: string, intakeId: string) => `${base(workspaceId)}/${encodeURIComponent(intakeId)}`;

export function loadIntakeFields(workspaceId: string, sourceType: string, connectionId: string): Promise<IntakeDiscovery> {
  const query = new URLSearchParams({ source_type: sourceType, connection_id: connectionId });
  return readJson<IntakeDiscovery>(`${base(workspaceId)}/fields?${query.toString()}`);
}

export function countIntakeMatches(workspaceId: string, draft: IntakeDraft): Promise<{ count: number | null; reason?: string | null }> {
  return readJson(`${base(workspaceId)}/count`, { method: "POST", body: JSON.stringify({
    source_type: draft.source_type, connection_id: draft.connection_id, what: draft.what }) });
}

export function loadIntakeDraft(workspaceId: string, intakeId: string): Promise<IntakeDraft> {
  return readJson<IntakeDraft>(one(workspaceId, intakeId));
}

export function saveIntakeDraft(workspaceId: string, draft: IntakeDraft): Promise<IntakeDraft> {
  return draft.id
    ? readJson<IntakeDraft>(one(workspaceId, draft.id), { method: "PUT", body: JSON.stringify(draftPayload(draft)) })
    : readJson<IntakeDraft>(base(workspaceId), { method: "POST", body: JSON.stringify(draftPayload(draft)) });
}

export function previewIntake(workspaceId: string, intakeId: string): Promise<Record<string, unknown>> {
  return readJson(`${one(workspaceId, intakeId)}/preview`, { method: "POST" });
}

export function enableIntake(workspaceId: string, intakeId: string): Promise<Record<string, unknown>> {
  return readJson(`${one(workspaceId, intakeId)}/enable`, { method: "POST" });
}

export function disableIntake(workspaceId: string, intakeId: string): Promise<IntakeDraft> {
  return readJson(`${one(workspaceId, intakeId)}/disable`, { method: "POST" });
}

/** Custom REST: one page of the draft's list operation mapped to Work items; nothing is stored (`POST …/sample`). */
export function sampleIntake(workspaceId: string, draft: IntakeDraft): Promise<Record<string, unknown>> {
  return readJson(`${base(workspaceId)}/sample`, { method: "POST", body: JSON.stringify(draftPayload(draft)) });
}
