import type { StatusTone } from "../../layout/StatusLabel";
import { workStateKey, workStateLabel } from "./workBoardColumns";
import type { WorkItem } from "./workItemTypes";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";

// Our state of a Work Item in the user's words: cards and tables show it, never the source's raw status
// (a localized Jira instance uses its own word for it). The source's own status appears only on the detail's source tab.

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

/** The label of the item's state: the active workflows' label, else the key in words. */
export function ourStateLabel(item: Pick<WorkItem, "work_state">, workflows: WorkWorkflowDefinition[] = []): string {
  return workStateLabel(item.work_state, workflows);
}

/** The tone of our state: only states that ask for someone, fail or are under way are coloured. */
export function ourStateTone(item: Pick<WorkItem, "work_state">): StatusTone {
  return TONES[workStateKey(item.work_state)] ?? "neutral";
}
