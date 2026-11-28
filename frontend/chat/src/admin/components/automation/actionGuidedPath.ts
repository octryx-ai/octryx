import type { PanelAgentRow, PanelTaskRow } from "../taskTypes";

export const GUIDED_TASK_TYPE = "agent_run";

export type WorkspaceOption = { id: string; name: string; is_active?: boolean };

export type ActionPath =
  | { kind: "guided" }
  | { kind: "advanced"; reason: string };

export function actionPath(task: PanelTaskRow | null): ActionPath {
  if (!task) return { kind: "guided" };
  if (task.task_type !== GUIDED_TASK_TYPE) {
    return {
      kind: "advanced",
      reason: `This action has the type "${task.task_type}", which the guided form does not edit.`,
    };
  }
  if ((task.step_count ?? 0) > 0) {
    return {
      kind: "advanced",
      reason:
        "This action has steps. Its enabled steps run instead of a single agent turn, so it is edited here.",
    };
  }
  const agentId = task.config?.agent_definition_id;
  if (typeof agentId !== "string" || !agentId.trim()) {
    return {
      kind: "advanced",
      reason:
        "This action names no agent, so the guided form does not edit it.",
    };
  }
  if (typeof task.project_id !== "string" || !task.project_id) {
    return {
      kind: "advanced",
      reason:
        "The action's Workspace is not known, so it is edited here.",
    };
  }
  return { kind: "guided" };
}

// Global agents come with workspace "" (agent list) or null (catalog); the Reviewer never runs from an Action.
export function compatibleAgents(
  agents: PanelAgentRow[],
  workspaceId: string,
): PanelAgentRow[] {
  if (!workspaceId) return [];
  return agents.filter(
    (agent) =>
      agent.isActive === true &&
      agent.builtinKey !== "reviewer" &&
      (agent.projectId === "" ||
        agent.projectId === null ||
        agent.projectId === workspaceId),
  );
}

export function hasAuthoredInstruction(agent: PanelAgentRow): boolean {
  const filled = (value: unknown) =>
    typeof value === "string" && value.trim() !== "";
  return (
    filled(agent.goal) ||
    filled(agent.systemPrompt) ||
    filled(agent.outputPrompt) ||
    (agent.steps ?? []).some(
      (step) => step.isEnabled === true && filled(step.instructions),
    )
  );
}

