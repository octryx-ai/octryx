import type { StatusTone } from "../../layout/StatusLabel";
import { workStateKey, workStateLabel } from "./workBoardColumns";
import type { WorkItem } from "./workItemTypes";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";

// Never the source's raw status: a localized Jira instance uses its own word for it.

const TONES: Record<string, StatusTone> = {
  blocked: "problem",
  rejected: "problem",
  changes_requested: "attention",
  clarification: "attention",
  plan_review: "attention",
  planning: "info",
  development: "info",
  validation: "info",
};

export function ourStateLabel(item: Pick<WorkItem, "work_state">, workflows: WorkWorkflowDefinition[] = []): string {
  return workStateLabel(item.work_state, workflows);
}

export function ourStateTone(item: Pick<WorkItem, "work_state">): StatusTone {
  return TONES[workStateKey(item.work_state)] ?? "neutral";
}
