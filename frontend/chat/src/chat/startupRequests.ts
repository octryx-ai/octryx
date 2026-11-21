import { readUrlWorkspaceId, storedWorkspacePreferenceOf } from "./activeWorkspace";
import { prefetchAttention } from "./companion/companionApi";
import { prefetchSetupStatus } from "./setup/setupGuideApi";
import { readSetupViewer } from "./setup/useSetupProgress";

// The requests of the chat shell that need nothing from the bootstrap start with the bundle (startupPrefetch.ts):
// the attention list (no parameters) and, for the person who last saw the setup progress here as an admin, the
// setup status of their active Workspace (from the address or their stored choice, as useSetupProgress reads it).
export function startStartupRequests(): void {
  try {
    const path = typeof window === "undefined" ? "" : window.location.pathname;
    if (!path.startsWith("/chat") && !path.startsWith("/admin/chat")) return;
  } catch {
    return;
  }
  prefetchAttention();
  const viewer = readSetupViewer();
  if (viewer) prefetchSetupStatus(readUrlWorkspaceId() || storedWorkspacePreferenceOf(viewer) || null);
}
