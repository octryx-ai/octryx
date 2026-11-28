import { SYNC_MODE_DRY_RUN, SYNC_MODE_EXECUTE } from "../syncNames";
import type { IntakeSummary } from "./workIntakeTypes";

export type IntakeSyncMode = typeof SYNC_MODE_DRY_RUN | typeof SYNC_MODE_EXECUTE | null;

// A select option cannot hold null.
export const FOLLOW_WORKFLOW = "";

export function syncModeWords(mode: string | null | undefined): string {
  if (mode === SYNC_MODE_EXECUTE) return "execute";
  if (mode === SYNC_MODE_DRY_RUN) return "dry run only";
  return "no mode set, nothing is written";
}

export function syncChoices(workflowMode: string | null | undefined): Array<{ value: string; label: string }> {
  const now = workflowMode === undefined ? "reading…" : syncModeWords(workflowMode);
  return [
    { value: FOLLOW_WORKFLOW, label: `Follow the Workspace workflow (now: ${now})` },
    { value: SYNC_MODE_DRY_RUN, label: "Dry run only (preview write-backs, write nothing)" },
    { value: SYNC_MODE_EXECUTE, label: "Execute (write back; each write still needs a person's confirmation)" },
  ];
}

export const syncSelectValue = (mode: string | null | undefined): string =>
  mode === SYNC_MODE_DRY_RUN || mode === SYNC_MODE_EXECUTE ? mode : FOLLOW_WORKFLOW;
export const syncModeOfSelect = (value: string): IntakeSyncMode =>
  value === SYNC_MODE_DRY_RUN || value === SYNC_MODE_EXECUTE ? value : null;

export function workflowModeOf(intakes: Array<Pick<IntakeSummary, "workflow_sync_mode">>): string | null | undefined {
  return intakes.length ? intakes[0].workflow_sync_mode : undefined;
}

// An own value equal to the workflow's reads as following it.
export function cardSyncLabel(
  intake: Pick<IntakeSummary, "sync_mode" | "effective_sync_mode" | "workflow_sync_mode">,
): { text: string; own: boolean } {
  const effective = syncModeWords(intake.effective_sync_mode);
  const own = Boolean(intake.sync_mode) && intake.sync_mode !== intake.workflow_sync_mode;
  return { text: effective.charAt(0).toUpperCase() + effective.slice(1), own };
}

export const SYNC_MODE_REFUSAL = "Pick one of the Sync choices: follow the workflow, dry run only, or execute.";
