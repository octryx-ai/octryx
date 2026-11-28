import { readUrlWorkspaceId, storedWorkspacePreferenceOf } from "./activeWorkspace";
import { prefetchAttention } from "./companion/companionApi";
import { prefetchSetupStatus } from "./setup/setupGuideApi";
import { readSetupViewer } from "./setup/useSetupProgress";

// These requests need nothing from the bootstrap, so they start with the bundle.
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
