// Carries workspace_id across page switches; useActiveWorkspace reads it first.

import { hrefWithWorkspace } from "../activeWorkspace";

export function workspaceScopedHref(href: string, workspaceId: string): string {
  return workspaceId ? hrefWithWorkspace(href, workspaceId) : href;
}

export function keepWorkspaceInUrl(workspaceId: string): void {
  if (typeof window === "undefined" || !workspaceId) return;
  const next = workspaceScopedHref(window.location.href, workspaceId);
  if (next !== window.location.href) window.history.replaceState(window.history.state, "", next);
}
