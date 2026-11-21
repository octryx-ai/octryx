import { readJson } from "../../../admin/utils/adminPanelHelpers";
import type { IntakeOverview } from "./workIntakeTypes";

const base = (workspaceId: string) => `/api/v1/secure-work/workspaces/${encodeURIComponent(workspaceId)}/intake`;

export function loadIntakeOverview(workspaceId: string): Promise<IntakeOverview> {
  return readJson<IntakeOverview>(base(workspaceId));
}

export async function loadIntakeRuns(workspaceId: string, intakeId: string): Promise<unknown[]> {
  const payload = await readJson<{ runs?: unknown[] }>(`${base(workspaceId)}/${encodeURIComponent(intakeId)}/runs`);
  return Array.isArray(payload.runs) ? payload.runs : [];
}
