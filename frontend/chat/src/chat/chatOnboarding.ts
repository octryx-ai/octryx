// First-use content of an empty chat (judge): what the
// assistant can do here, what it needs, and starter requests that only fill
// the composer — nothing is sent without the user.
export type ChatStarter = { label: string; prompt: string };

// Every starter works on text the user pastes. No starter implies document, repository or
// connector retrieval: the chat has no authoritative signal that a turn can retrieve sources.
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
  // An inactive or unavailable agent gets no starter that suggests it will answer.
  return agentAvailability === "inactive" || agentAvailability === "unavailable"
    ? []
    : CHAT_STARTERS;
}

// The persistent composer notice for a requested agent that the next message does not use.
// It names the reason and what sending actually does; an unavailable agent is never named.
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

// Guidance for an agent declared text-only ("none"): no workspace sources, no Knowledge link.
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

// Labels the chat shows when no workspace is chosen: "Global" (admins may chat without one) and the
// composer pill's "Project required" / "No project" for everyone else. None of them is a workspace.
const NO_WORKSPACE_LABELS = new Set([
  "",
  "global",
  "no project",
  "project required",
]);

function isNoWorkspaceLabel(name: string): boolean {
  return NO_WORKSPACE_LABELS.has(name.trim().toLowerCase());
}

// With `projectId` the selected id decides (a workspace may itself be named "Global"); without it
// the label is read, and the no-workspace labels are never shown as a workspace name.
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
  // A selected id whose name has not loaded reads as "this workspace", never "Project required".
  const shown =
    isNoWorkspaceLabel(name) && name.toLowerCase() !== "global"
      ? "this workspace"
      : name;
  return `The assistant can use what ${shown} provides — its documents, repositories and connected tools, where they exist and you may access them. When an answer uses sources, they open from “Sources” under it.`;
}

// The workspace part of the chat header: the selected workspace, "Global" for an admin chat without
// one, and otherwise a plain "No workspace selected" instead of the composer pill's wording.
export function headerWorkspaceLabel(label: string): string {
  const name = (label || "").trim();
  if (name.toLowerCase() === "global") return name;
  return isNoWorkspaceLabel(name) ? "No workspace selected" : name;
}

// Knowledge → Documents for the chat's workspace, so the user's scope carries
// over instead of a workspace remembered elsewhere (judge B2 review).
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

// "Auto · AWS Bedrock / anthropic.claude-…-v1:0" → "Auto · AWS Bedrock"; the full
// identifier stays available in the run details.
export function shortRuntimeLabel(label: string): string {
  const value = (label || "").trim();
  const slash = value.indexOf(" / ");
  return slash > 0 ? value.slice(0, slash) : value;
}
