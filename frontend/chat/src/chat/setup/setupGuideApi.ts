import { readJson } from "../../admin/utils/adminPanelHelpers";
import { readSetupStatus, type SetupStatus } from "./setupGuideModel";
import { prefetch, takePrefetched } from "../startupPrefetch";

function setupStatusPath(workspaceId: string | null): string {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return `/api/v1/admin/setup/onboarding${query}`;
}

/** Starts the setup status read with the bundle (startupRequests.ts); loadSetupStatus takes it. */
export function prefetchSetupStatus(workspaceId: string | null): void {
  const path = setupStatusPath(workspaceId);
  prefetch(path, () => readJson<unknown>(path));
}

/** The setup status for the platform and one Workspace; null for people who may not read it (not admins). */
export async function loadSetupStatus(workspaceId: string | null): Promise<SetupStatus | null> {
  const path = setupStatusPath(workspaceId);
  try {
    return readSetupStatus(await (takePrefetched<unknown>(path) ?? readJson<unknown>(path)));
  } catch (error) {
    if ((error as { status?: number })?.status === 403) return null;
    throw error;
  }
}
