// The coding session start request: plans one change unit per repository, then generates the change plan.
import { generateWorkItemChangePlan, planWorkItemChangeUnits } from "../work/workChangePlanApi";
import type { WorkItem } from "../work/workItemTypes";
import { defaultIntent } from "./codingStartCandidates";

export async function createCodingSessionPlan({
  selectedItem,
  repositories,
  branchHints,
  plannedFiles,
  validationCommands,
  intent,
  rollbackPlan,
}: {
  selectedItem: WorkItem;
  repositories: string[];
  branchHints: string[];
  plannedFiles: string[];
  validationCommands: string[];
  intent: string;
  rollbackPlan: string;
}) {
  await planWorkItemChangeUnits({
    workItemId: selectedItem.id,
    units: repositories.map((repositoryName, index) => ({
      repository_name: repositoryName,
      branch_name: branchHints[index] || "",
      expected_paths: plannedFiles,
      validation_commands: validationCommands,
      scope: selectedItem.title,
      status: "planned",
      dependency_order: index + 1,
    })),
  });
  await generateWorkItemChangePlan({
    workItemId: selectedItem.id,
    title: `${selectedItem.source_key} Coding Session Plan`,
    understoodRequest: intent.trim() || defaultIntent(selectedItem),
    validationPlan: validationCommands,
    rollbackPlan: rollbackPlan.trim(),
    traceRefs: [
      {
        source: "coding_session_start_ui",
        work_item_id: selectedItem.id,
        source_key: selectedItem.source_key,
        repository_scope: repositories,
        branch_hints: branchHints,
        planned_files: plannedFiles,
      },
    ],
  });
}
