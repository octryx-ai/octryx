import { SYNC_MODE_DRY_RUN, SYNC_MODE_EXECUTE } from "../syncNames";
import type { IntakeSummary } from "./workIntakeTypes";

// The Sync of one intake source (backend): `how.sync_mode` is the source's own write-back mode,
// "dry_run_only" | "execute", or null to follow the Workspace workflow. The overview sends the own value and the one
// in force (`effective_sync_mode`: the own value, else the workflow's, else none = nothing is written). Pure: no React.

export type IntakeSyncMode = typeof SYNC_MODE_DRY_RUN | typeof SYNC_MODE_EXECUTE | null;

/** The select's value for "follow the workflow" (a select option cannot hold null). */
export const FOLLOW_WORKFLOW = "";

/** A mode in words, short; an unset mode writes nothing (only `execute` writes). */
export function syncModeWords(mode: string | null | undefined): string {
  if (mode === SYNC_MODE_EXECUTE) return "execute";
  if (mode === SYNC_MODE_DRY_RUN) return "dry run only";
  return "no mode set, nothing is written";
}

/** The select's options; `workflowMode` is the workflow's mode now (undefined while it is being read). */
export function syncChoices(workflowMode: string | null | undefined): Array<{ value: string; label: string }> {
  const now = workflowMode === undefined ? "reading…" : syncModeWords(workflowMode);
  return [
    { value: FOLLOW_WORKFLOW, label: `Follow the Workspace workflow (now: ${now})` },
    { value: SYNC_MODE_DRY_RUN, label: "Dry run only (preview write-backs, write nothing)" },
    { value: SYNC_MODE_EXECUTE, label: "Execute (write back; each write still needs a person's confirmation)" },
  ];
}

/** The select's value for a draft's mode, and back. */
export const syncSelectValue = (mode: string | null | undefined): string =>
  mode === SYNC_MODE_DRY_RUN || mode === SYNC_MODE_EXECUTE ? mode : FOLLOW_WORKFLOW;
export const syncModeOfSelect = (value: string): IntakeSyncMode =>
  value === SYNC_MODE_DRY_RUN || value === SYNC_MODE_EXECUTE ? value : null;

/** The Workspace workflow's mode as every intake of the overview carries it (`workflow_sync_mode`). `undefined` when
 * the Workspace has no intake yet (the caller then reads the workflows itself). */
export function workflowModeOf(intakes: Array<Pick<IntakeSummary, "workflow_sync_mode">>): string | null | undefined {
  return intakes.length ? intakes[0].workflow_sync_mode : undefined;
}

/** The overview card's Sync: the mode in force, and whether this source sets one that differs from the workflow's
 * (an own value equal to the workflow's reads as following it). */
export function cardSyncLabel(
  intake: Pick<IntakeSummary, "sync_mode" | "effective_sync_mode" | "workflow_sync_mode">,
): { text: string; own: boolean } {
  const effective = syncModeWords(intake.effective_sync_mode);
  const own = Boolean(intake.sync_mode) && intake.sync_mode !== intake.workflow_sync_mode;
  return { text: effective.charAt(0).toUpperCase() + effective.slice(1), own };
}

/** The refusal of `how.sync_mode` (422) in words at the field. */
export const SYNC_MODE_REFUSAL = "Pick one of the Sync choices: follow the workflow, dry run only, or execute.";
