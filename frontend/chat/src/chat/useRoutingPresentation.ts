import { useEffect, useMemo } from "react";

import type { ChatState } from "../types";
import type { SelectedSession } from "../chatThreadTypes";
import { getAgentModeLabel, getProjectPillLabel, getRuntimePillLabel, getThinkingPillLabel } from "./appHelpers";
import { getSessionStatusLabel, getThreadLifecycleLabel } from "./sessionStatusLabels";

type AgentOption = NonNullable<ChatState["agentOptions"]>[number];
type AgentGroup = NonNullable<ChatState["agentGroups"]>[number];

// Runtime and project pill labels of the composer and of the selected session.
function projectLabels(
  chatState: ChatState | null,
  selectedSession: SelectedSession | null,
  selectedRuntimeTargetId: string,
  selectedProjectId: string,
) {
  const runtimePillLabel = getRuntimePillLabel(
    chatState?.runtimeOptions.find(
      (option) => option.value === selectedRuntimeTargetId,
    ),
  );
  const selectedSessionRuntimePillLabel =
    selectedSession?.runtimeLabel ||
    getRuntimePillLabel(
      chatState?.runtimeOptions.find(
        (option) => option.value === selectedSession?.runtimeTargetId,
      ),
    );
  const currentUserIsAdmin = Boolean(
    chatState?.currentUser.roles.some(
      (role) => role.trim().toLowerCase() === "admin",
    ),
  );
  const projectName =
    (selectedProjectId
      ? chatState?.projects.find((project) => project.id === selectedProjectId)
          ?.name
      : currentUserIsAdmin
        ? "Global"
        : "") || "No project";
  const projectPillLabel = getProjectPillLabel(projectName);
  const selectedSessionProjectLabel = getProjectPillLabel(
    selectedSession?.projectName === "No project" && currentUserIsAdmin
      ? "Global"
      : selectedSession?.projectName || projectName,
  );
  return {
    runtimePillLabel,
    selectedSessionRuntimePillLabel,
    currentUserIsAdmin,
    projectPillLabel,
    selectedSessionProjectLabel,
  };
}

// Agent and agent group labels of the current selection.
function agentLabels(
  chatState: ChatState | null,
  options: { agentOptions: AgentOption[]; agentGroups: AgentGroup[] },
  selection: { selectedAgentId: string; selectedAgentGroupId: string },
) {
  const { agentOptions, agentGroups } = options;
  const { selectedAgentId, selectedAgentGroupId } = selection;
  const selectedAgentOption =
    agentOptions.find((agent) => agent.id === selectedAgentId) ?? null;
  const selectedAgentGroup =
    agentGroups.find(
      (group) =>
        group.id ===
        (selectedAgentGroupId || selectedAgentOption?.groupId || ""),
    ) ?? null;
  // The bootstrap name only belongs to the bootstrap's agent; never carry it to another selection.
  const agentName =
    selectedAgentOption?.name ||
    (chatState?.selectedAgentId === selectedAgentId
      ? chatState?.selectedAgentName
      : "") ||
    "";
  const agentPillLabel = agentName || "Auto agent";
  const agentGroupPillLabel = selectedAgentGroup?.name || "All groups";
  const canDeleteThreads =
    chatState?.currentUser.roles.includes("admin") ?? false;
  const filteredAgentOptions = selectedAgentGroupId
    ? agentOptions.filter((agent) => agent.groupId === selectedAgentGroupId)
    : agentOptions;
  return {
    agentName,
    agentPillLabel,
    agentGroupPillLabel,
    canDeleteThreads,
    filteredAgentOptions,
  };
}

// Agent modes and the status and mode labels of the selected session.
function modeLabels(
  chatState: ChatState | null,
  selectedSession: SelectedSession | null,
  selectedSessionIsRunning: boolean,
  selectedModeKey: string,
) {
  const availableAgentModes = chatState?.agentModes || [];
  const agentModeNameByKey = new Map(
    availableAgentModes.map((mode) => [mode.key, mode.name]),
  );
  const statusLabel = getSessionStatusLabel(
    selectedSession,
    selectedSessionIsRunning,
  );
  const threadStatusLabel = getThreadLifecycleLabel(selectedSession);
  const activeModeKey = selectedModeKey || selectedSession?.agentType;
  const modeLabel =
    agentModeNameByKey.get(String(activeModeKey || "")) ||
    getAgentModeLabel(activeModeKey);
  return { availableAgentModes, statusLabel, threadStatusLabel, modeLabel };
}

type RoutingPresentationArgs = {
  chatState: ChatState | null;
  selectedSession: SelectedSession | null;
  selectedRuntimeTargetId: string;
  selectedProjectId: string;
  selectedThinkingLevel: string;
  selectedAgentId: string;
  selectedAgentGroupId: string;
  selectedModeKey: string;
  selectedSessionIsRunning: boolean;
};

export function useRoutingPresentation({
  chatState,
  selectedSession,
  selectedRuntimeTargetId,
  selectedProjectId,
  selectedThinkingLevel,
  selectedAgentId,
  selectedAgentGroupId,
  selectedModeKey,
  selectedSessionIsRunning,
}: RoutingPresentationArgs) {
  const { currentUserIsAdmin, ...projectPills } = projectLabels(
    chatState,
    selectedSession,
    selectedRuntimeTargetId,
    selectedProjectId,
  );
  const thinkingPillLabel = getThinkingPillLabel(selectedThinkingLevel);
  const agentOptions = useMemo(
    () => chatState?.agentOptions ?? [],
    [chatState?.agentOptions],
  );
  const agentGroups = useMemo(
    () => chatState?.agentGroups ?? [],
    [chatState?.agentGroups],
  );
  const agentPills = agentLabels(
    chatState,
    { agentOptions, agentGroups },
    { selectedAgentId, selectedAgentGroupId },
  );
  const modes = modeLabels(chatState, selectedSession, selectedSessionIsRunning, selectedModeKey);

  return {
    ...projectPills,
    thinkingPillLabel,
    agentOptions,
    agentGroups,
    ...agentPills,
    allowGlobalProjectSelection: currentUserIsAdmin,
    ...modes,
  };
}
