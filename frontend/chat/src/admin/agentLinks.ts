// Canonical agent destination: Agents & workflows → Agents, with the
// agent's drawer opened from `agent_id`. Workflows and the visual
// step editor link here instead of offering their own agent management.
export const AGENT_ID_PARAM = "agent_id";

export function readAgentIdFromSearch(search: string): string {
  try {
    return new URLSearchParams(search).get(AGENT_ID_PARAM) || "";
  } catch {
    return "";
  }
}

export function withAgentId(href: string, agentId: string | null): string {
  const url = new URL(href);
  if (agentId) url.searchParams.set(AGENT_ID_PARAM, agentId);
  else url.searchParams.delete(AGENT_ID_PARAM);
  return url.toString();
}

export const AGENTS_PAGE_HREF = "/chat?area=workflows&tab=agents";

export function agentPageHref(agentId: string): string {
  return `${AGENTS_PAGE_HREF}&${AGENT_ID_PARAM}=${encodeURIComponent(agentId)}`;
}

export function writeAgentIdToUrl(agentId: string | null) {
  if (typeof window === "undefined") return;
  const next = withAgentId(window.location.href, agentId);
  if (next !== window.location.href) window.history.replaceState(window.history.state, "", next);
}
