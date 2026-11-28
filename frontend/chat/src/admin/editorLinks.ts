// A link never grants or reveals anything: each editor still does its normal authorized load.
// The workflow the Workflows designer opens.
export const PHASED_PARAM = "phased";

function readParam(search: string, name: string): string {
  try {
    return (new URLSearchParams(search).get(name) || "").trim();
  } catch {
    return "";
  }
}

export function flowEditorHref(flowId: string): string {
  return `/chat?area=workflows&tab=workflowDesigner&view=canvas&${PHASED_PARAM}=${encodeURIComponent(flowId)}`;
}

export const PROMPT_SCOPE_PARAM = "prompt_scope";

export function readPromptScopeFromSearch(search: string): string {
  return readParam(search, PROMPT_SCOPE_PARAM);
}

export function promptTextsHref(scope: string): string {
  const params = new URLSearchParams({ area: "admin", tab: "promptCatalog" });
  params.set(PROMPT_SCOPE_PARAM, scope);
  return `/chat?${params.toString()}`;
}
