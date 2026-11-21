// Create handoff into Flow Builder: `?new_flow=1&workspace_id=<id>` from Workspace settings
// opens the normal create drawer with that workspace preselected. Nothing is created by the link:
// the user still names the workflow and confirms Create, and the drawer's own check applies.
//
// - The workspace must be one of the user's available, active workspaces. Otherwise (an unknown or
//   inactive workspace, or an empty list after a failed chat bootstrap) the drawer opens with no
//   workspace chosen and says why; it never falls back to Global on its own and never waits.
// - The address is the request until the user settles it. The admin shell can mount Flow Builder
//   more than once for one navigation: every panel mount runs `loadTab`, which sets `loadingTab`
//   and makes AdminPanelContent replace the panel with "Loading…" until the load finishes, so a
//   panel that already mounted is unmounted and mounted again. A request consumed by the first
//   mount was lost with that instance. So every mount reads the
//   request again, and only `settle()` (Cancel or a created draft) removes `new_flow`; after that
//   a reload, Back or a remount does not reopen the drawer. `workspace_id` stays, since it is the
//   user's workspace context for other pages.
import { useCallback, useEffect } from "react";
import { NEW_FLOW_PARAM, WORKSPACE_ID_PARAM } from "../../editorLinks";

export type WorkspaceOption = { id: string; name: string; is_active?: boolean };

export type FlowCreateRequest = {
  // The workspace to preselect, or "" when the author has to choose.
  scope: string;
  // Why no workspace is preselected, shown in the drawer; null when there is nothing to explain.
  notice: string | null;
};

export const UNAVAILABLE_WORKSPACE_NOTICE =
  "You cannot currently use the workspace from the link, so none is preselected. Choose an available workspace or Global.";

function params(search: string): URLSearchParams | null {
  try {
    return new URLSearchParams(search);
  } catch {
    return null;
  }
}

// The create request a URL asks for, checked against the available workspaces; null when the URL
// does not ask to create a workflow.
export function resolveFlowCreateRequest(search: string, workspaces: WorkspaceOption[]): FlowCreateRequest | null {
  const query = params(search);
  if (!query || query.get(NEW_FLOW_PARAM) !== "1") return null;
  const workspaceId = (query.get(WORKSPACE_ID_PARAM) || "").trim();
  if (!workspaceId) return { scope: "", notice: null };
  const workspace = workspaces.find((item) => item.id === workspaceId);
  if (!workspace || workspace.is_active === false) return { scope: "", notice: UNAVAILABLE_WORKSPACE_NOTICE };
  return { scope: workspace.id, notice: null };
}

// The address without the `new_flow` request; null when there is nothing to remove.
export function urlWithoutCreateRequest(href: string): string | null {
  try {
    const url = new URL(href);
    if (!url.searchParams.has(NEW_FLOW_PARAM)) return null;
    url.searchParams.delete(NEW_FLOW_PARAM);
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

// Calls `onRequest` on every mount whose address carries a create request, and returns `settle`,
// which removes the request from the address once the user cancelled or created the draft.
export function useFlowCreateHandoff(workspaces: WorkspaceOption[], onRequest: (request: FlowCreateRequest) => void) {
  useEffect(() => {
    const request = resolveFlowCreateRequest(window.location.search, workspaces);
    if (request) onRequest(request);
    // Read on mount; a remount reads the still-open request again. The workspace list is loaded
    // before the admin area renders (an empty list is answered as unavailable, above).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return useCallback(() => {
    const next = urlWithoutCreateRequest(window.location.href);
    if (next !== null) window.history.replaceState(window.history.state, "", next);
  }, []);
}
