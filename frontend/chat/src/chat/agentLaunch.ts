// A new chat opened for one agent (Agents → "Test in chat" / judge
// J-E-005): the URL names the agent and the server confirms it as the selected,
// selectable (active, owned) agent. Only then is the agent an explicit choice
// that reaches the send request; a workspace default agent never is.
export function isExplicitAgentLaunch(
  search: string,
  isNewThread: boolean,
  selectedAgentId: string | null | undefined,
  selectableAgentIds: string[],
): boolean {
  if (!isNewThread) return false;
  let requested = "";
  try {
    requested = (new URLSearchParams(search).get("agent_id") || "").trim();
  } catch {
    return false;
  }
  return Boolean(requested) && requested === (selectedAgentId || "") && selectableAgentIds.includes(requested);
}
