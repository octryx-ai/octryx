import type {
  ComposerAgentOption,
  GroupedAgentPopup,
  GroupedAgentSelect,
} from "./composerShellTypes";

export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const precision = unitIndex === 0 ? 0 : size >= 10 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[unitIndex]}`;
}

export function getResumeComposerCopy(
  resumeState: string | null | undefined,
  isRunning: boolean,
) {
  if (!isRunning) {
    return null;
  }
  const normalized = String(resumeState || "")
    .trim()
    .toLowerCase();
  if (normalized === "approval_approved") {
    return "This thread is resuming after approval. The current turn is continuing from the approved step.";
  }
  if (normalized === "approval_rejected") {
    return "This thread is resuming after rejection. The rejected action will be avoided while the agent continues with a safer path.";
  }
  return null;
}

export function formatAgentOptionLabel(
  agent: Pick<ComposerAgentOption, "name" | "isPrimary">,
) {
  if (agent.isPrimary) {
    return `${agent.name} [Primary]`;
  }
  return agent.name;
}

export function buildGroupedAgentOptions(
  agents: ComposerAgentOption[],
  mentionQuery: string,
): GroupedAgentPopup[] {
  return Object.values(
    agents
      .filter((agent) => agent.name.toLowerCase().startsWith(mentionQuery))
      .slice(0, 12)
      .reduce<Record<string, GroupedAgentPopup>>((acc, agent) => {
        const key = agent.groupId || agent.groupName || "ungrouped";
        if (!acc[key]) {
          acc[key] = {
            label: agent.groupName?.trim() || "Other agents",
            agents: [],
          };
        }
        acc[key].agents.push(agent);
        return acc;
      }, {}),
  );
}

export function buildGroupedAgentSelectOptions(
  agents: ComposerAgentOption[],
): GroupedAgentSelect[] {
  return Object.values(
    agents.reduce<Record<string, GroupedAgentSelect>>((acc, agent) => {
      const key = agent.groupId || agent.groupName || "ungrouped";
      if (!acc[key]) {
        acc[key] = {
          label: agent.groupName?.trim() || "Other agents",
          agents: [],
        };
      }
      acc[key].agents.push({ id: agent.id, name: agent.name });
      return acc;
    }, {}),
  );
}
