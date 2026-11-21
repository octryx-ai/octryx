// Deep links to the existing canonical editors: the workflow editor in the Workflow library and the
// prompt editor. Each editor reads its own parameter once on mount; opening still goes through that
// editor's normal authorized load, so a link never grants or reveals anything.
export const FLOW_ID_PARAM = "flow_id";
// Opens Flow Builder's create drawer once; never creates anything by itself.
export const NEW_FLOW_PARAM = "new_flow";
export const WORKSPACE_ID_PARAM = "workspace_id";

function readParam(search: string, name: string): string {
  try {
    return (new URLSearchParams(search).get(name) || "").trim();
  } catch {
    return "";
  }
}

export function readFlowIdFromSearch(search: string): string {
  return readParam(search, FLOW_ID_PARAM);
}

export function flowEditorHref(flowId: string): string {
  return `/chat?area=workflows&tab=workflowList&view=canvas&${FLOW_ID_PARAM}=${encodeURIComponent(flowId)}`;
}

// "Create a workflow for this workspace" from Workspace settings: Flow Builder opens its
// normal create drawer with this workspace preselected; the user still names the workflow and
// confirms Create. The workspace is checked there against the user's available workspaces.
export function flowBuilderCreateHref(workspaceId: string): string {
  const params = new URLSearchParams({ area: "workflows", tab: "workflowList", view: "canvas" });
  params.set(WORKSPACE_ID_PARAM, workspaceId);
  params.set(NEW_FLOW_PARAM, "1");
  return `/chat?${params.toString()}`;
}

// "Texts of this workflow": the prompt editor opens on the run texts with this scope chosen
// (`workflow:<flow key>` or `workspace:<id>`). The server still decides what the user may see and write.
export const PROMPT_SCOPE_PARAM = "prompt_scope";

export function readPromptScopeFromSearch(search: string): string {
  return readParam(search, PROMPT_SCOPE_PARAM);
}

export function promptTextsHref(scope: string): string {
  const params = new URLSearchParams({ area: "admin", tab: "promptCatalog" });
  params.set(PROMPT_SCOPE_PARAM, scope);
  return `/chat?${params.toString()}`;
}
