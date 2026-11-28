// A workspace default agent is never an explicit choice that reaches the send request.
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
