import { readJson } from "../../admin/utils/adminPanelHelpers";

// GET /octryx-claude/version (public): the answer is parsed by octryxInstallModel.readOctryxInstall.
export function loadOctryxInstall(workspaceId: string | null): Promise<unknown> {
  const query = workspaceId ? `?workspace=${encodeURIComponent(workspaceId)}` : "";
  return readJson<unknown>(`/octryx-claude/version${query}`);
}
