// Guided Action authoring: the guided task type, which path an Action opens in, and the agents usable in a workspace.
import type { PanelAgentRow, PanelTaskRow } from "../taskTypes";

export const GUIDED_TASK_TYPE = "agent_run";

export type WorkspaceOption = { id: string; name: string; is_active?: boolean };

// ---- which path an Action opens in ---------------------------------------------------------------

export type ActionPath =
  | { kind: "guided" }
  | { kind: "advanced"; reason: string };

/** New Actions are guided. An existing one is guided only when it is exactly a single agent run in a known workspace. */
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

// ---- workspace and agent ----------------------------------------------------------------------

/**
 * Active agents usable in the workspace: explicitly global ones and the workspace's own. The agent
 * list sends a global agent's workspace as "" (agent_definition_payload.py) and the agent catalog as
 * null (agent_catalog_policy.py); a missing or non-string value is not read as global. The Reviewer
 * never runs from an Action: only a workflow run's review node runs it.
 */
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

/**
 * Whether the agent row authors an instruction of its own (goal, system or output prompt, or an
 * enabled step's instructions), mirroring the runtime admission. Only meaningful for the
 * content a run actually executes; see `instructionCheck`.
 */
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

