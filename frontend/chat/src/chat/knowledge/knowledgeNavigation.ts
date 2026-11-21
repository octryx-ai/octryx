// Moves between Knowledge pages keep the user's workspace intent: before a page switch the current
// URL carries the selected workspace_id, which useActiveWorkspace reads first on the next page.

import { hrefWithWorkspace } from "../activeWorkspace";

export function workspaceScopedHref(href: string, workspaceId: string): string {
  return workspaceId ? hrefWithWorkspace(href, workspaceId) : href;
}

export function keepWorkspaceInUrl(workspaceId: string): void {
  if (typeof window === "undefined" || !workspaceId) return;
  const next = workspaceScopedHref(window.location.href, workspaceId);
  if (next !== window.location.href) window.history.replaceState(window.history.state, "", next);
}
