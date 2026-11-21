// The Work items filter bar's choices, read from the loaded items.
import type { WorkItem } from "./workItemTypes";
import { uniqueSorted, workItemSprintLabel } from "./workUtils";
import { assigneeFilterOptions } from "./workPeople";
import { sourceFilterOptions } from "./incident/workSourceModel";

export function workFilterOptions(items: WorkItem[]) {
  return {
    sourceTypes: sourceFilterOptions(items).values,
    sourceProjects: uniqueSorted(items.map((item) => item.source_project_key)),
    sourceStatuses: uniqueSorted(items.map((item) => item.source_status)),
    workStates: uniqueSorted(items.map((item) => item.work_state)),
    syncStates: uniqueSorted(items.map((item) => item.sync_state)),
    assignees: assigneeFilterOptions(items).values,
    labels: uniqueSorted(items.flatMap((item) => item.labels || [])),
    fixVersions: uniqueSorted(items.flatMap((item) => item.fix_versions || [])),
    sprints: uniqueSorted(items.map(workItemSprintLabel)),
  };
}
