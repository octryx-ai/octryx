export type ChatStarter = { label: string; prompt: string };

// No starter implies retrieval: the chat has no authoritative signal that a turn can retrieve sources.
export const CHAT_STARTERS: ChatStarter[] = [
  {
    label: "Summarize pasted text",
    prompt: "Summarize the text I paste below in five bullet points:\n\n",
  },
  {
    label: "Compare two pasted versions",
    prompt:
      "Compare the two versions I paste below and list what changed:\n\nVersion A:\n\nVersion B:\n",
  },
  {
    label: "Plan from my notes",
    prompt:
      "Draft a step-by-step plan with open questions from the notes I paste below:\n\n",
  },
];

export function chatStartersFor(agentAvailability: string): ChatStarter[] {
  return agentAvailability === "inactive" || agentAvailability === "unavailable"
    ? []
    : CHAT_STARTERS;
}

export function unusedLaunchAgentNotice(
  agent: { name: string | null; reason: string },
): string {
  const name = agent.name || "The requested agent";
  const reasons: Record<string, string> = {
    inactive: `${name} is inactive, so it is not selected for this chat.`,
    unavailable:
      "The requested agent is not available to you, so it is not selected for this chat.",
    not_in_list: `${name} is not in this workspace's agent list, so it is not selected for this chat.`,
    not_selected: `${name} is not selected for this chat.`,
  };
  const reason =
    reasons[agent.reason] ??
    "The requested agent is not selected for this chat.";
  return `${reason} Sending uses this workspace's standard routing.`;
}

export const TEXT_ONLY_AGENT_HINT =
  "This agent works only with what you write in the chat: it cannot open documents, repositories or connected tools. Paste the text it should work with.";

export function agentAvailabilityNotice(
  agentAvailability: string,
  agentName: string,
): string {
  if (agentAvailability === "inactive") {
    return `${agentName || "This chat's agent"} is inactive. It must be activated again before it takes new requests.`;
  }
  if (agentAvailability === "unavailable") {
    return "The agent of this chat is no longer available to you. Start a new chat or choose another agent.";
  }
  return "";
}

const NO_WORKSPACE_LABELS = new Set([
  "",
  "global",
  "no project",
  "project required",
]);

function isNoWorkspaceLabel(name: string): boolean {
  return NO_WORKSPACE_LABELS.has(name.trim().toLowerCase());
}

// The selected id decides: a workspace may itself be named "Global".
export function workspaceHint(
  projectName: string,
  projectId?: string | null,
): string {
  const name = (projectName || "").trim();
  const selected =
    projectId === undefined ? !isNoWorkspaceLabel(name) : Boolean(projectId);
  if (!selected && name.toLowerCase() === "global") {
    return "No workspace is selected. Choose one in the composer when the answer should use that workspace's documents, repositories or connected tools; without one, only capabilities allowed for Global chats are available.";
  }
  if (!selected) {
    return "No workspace is selected. Choose one in the composer so the assistant can use that workspace's documents, repositories and connected tools.";
  }
  const shown =
    isNoWorkspaceLabel(name) && name.toLowerCase() !== "global"
      ? "this workspace"
      : name;
  return `The assistant can use what ${shown} provides — its documents, repositories and connected tools, where they exist and you may access them. When an answer uses sources, they open from “Sources” under it.`;
}

export function headerWorkspaceLabel(label: string): string {
  const name = (label || "").trim();
  if (name.toLowerCase() === "global") return name;
  return isNoWorkspaceLabel(name) ? "No workspace selected" : name;
}

// Carries the chat's workspace over instead of one remembered elsewhere.
export function knowledgeDocumentsHref(
  projectId: string | null | undefined,
): string {
  const params = new URLSearchParams({
    area: "knowledge",
    tab: "knowledgeSources",
  });
  if (projectId) params.set("workspace_id", projectId);
  return `/chat?${params.toString()}`;
}

export function shortRuntimeLabel(label: string): string {
  const value = (label || "").trim();
  const slash = value.indexOf(" / ");
  return slash > 0 ? value.slice(0, slash) : value;
}
