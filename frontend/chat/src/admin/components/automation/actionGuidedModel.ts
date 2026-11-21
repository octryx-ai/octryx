// Guided "Run an agent" authoring for Actions. Pure: no requests, no React.
//
// Contracts used as they exist (no new ones):
// - create accepts `project_id`, `task_type`, `agent_type` (a shipped run-mode key) and `config`;
// - the scheduler's agent branch reads `config.agent_definition_id`, `config.prompt` (sent as the run's
//   request) and `config.capability_class` (read_only | change | deliver; nothing declared runs read_only);
// - GET /admin/chat/api/panel/agents/{id}/designer-document answers which content a run executes
//   (`execution: {mode, published_revision_number}`, plus the newest `revision`).
// The scheduler stays the runtime authority; this model only refuses to submit what it cannot
// show to be runnable, and never fills an unknown value with a default.

import type { PermissionModeChoice } from "./permissionModeCatalog";
import type { PanelAgentRow } from "../taskTypes";

import type { ExecutionView, InstructionCheck } from "./actionGuidedExecution";
import type { GuidedConfigView } from "./actionGuidedConfig";

// ---- the submit gate --------------------------------------------------------------------------

export type GuidedSubmission = {
  canSubmit: boolean;
  blocker: string | null;
  /** Sent on create only; an existing Action's workspace is not changed. */
  projectId: string | null;
  agentType: string;
  /** Sent only when set (see actionDispatchBinding.ts); omitted keeps the stored binding. */
  dispatchBinding?: "agent_definition";
};

export function guidedSubmission({
  isNew,
  workspaceId,
  agent,
  agentAvailable,
  modeChoice,
  execution,
  config,
  instruction,
}: {
  isNew: boolean;
  workspaceId: string;
  agent: PanelAgentRow | null;
  agentAvailable: boolean;
  modeChoice: PermissionModeChoice;
  execution: ExecutionView;
  config: GuidedConfigView;
  /** From `instructionCheck`, for a runnable execution only. */
  instruction?: InstructionCheck | null;
}): GuidedSubmission {
  const agentType = agent?.agentType?.trim() || "";
  const blocked = (blocker: string): GuidedSubmission => ({
    canSubmit: false,
    blocker,
    projectId: isNew ? workspaceId || null : null,
    agentType,
  });
  if (!workspaceId) return blocked("Choose the workspace this action runs in.");
  if (!agent) return blocked("Choose the agent this action runs.");
  if (!agentAvailable) {
    return blocked(
      "The chosen agent is not active or not available in this workspace. Choose another agent.",
    );
  }
  if (!agentType)
    return blocked(
      "This agent has no run mode. Set one on the agent's page first.",
    );
  if (!modeChoice.canSubmit) {
    return blocked(
      modeChoice.state === "invalid_stored"
        ? `The agent's run mode "${agentType}" no longer exists, so the action cannot be saved. Change it on the agent's page.`
        : modeChoice.message || "Run modes are not available.",
    );
  }
  if (!execution.runnable) return blocked(execution.text);
  if (config.error) return blocked(`${config.error} Fix it under Advanced.`);
  if (config.promptInvalid)
    return blocked(
      'The saved instruction is not text. Fix "prompt" under Advanced.',
    );
  if (config.capabilityInvalid) {
    return blocked(
      `The saved capability_class ${config.capabilityInvalid} is not one of read_only, change or deliver.`,
    );
  }
  if (config.reserved.length) {
    return blocked(
      `Remove ${config.reserved.map((key) => `"${key}"`).join(" and ")} from Config (JSON).`,
    );
  }
  if (!config.prompt.trim() && instruction?.state === "missing") {
    return blocked(
      instruction.source === "published"
        ? "The published revision of this agent has no instructions of its own (goal, prompts or steps), so its runs would be refused. Add an instruction for each run."
        : "This agent has no instructions of its own (goal, prompts or steps), so its runs would be refused. Add an instruction for each run.",
    );
  }
  return {
    canSubmit: true,
    blocker: null,
    projectId: isNew ? workspaceId : null,
    agentType,
  };
}
