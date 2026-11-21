import type { WorkNavKey } from "./workTypes";

// Specific empty states per Work view: what the view is for
// and the next step, instead of one generic Jira message everywhere.
export type WorkEmptyAction = "connectJira" | "openSyncSettings" | "openWorkItems";
export type WorkEmptyContent = {
  eyebrow: string;
  title: string;
  body: string;
  actions: Array<{ label: string; action: WorkEmptyAction }>;
};

export function workEmptyStateFor(nav: WorkNavKey, hasIntakes: boolean, hasItems: boolean): WorkEmptyContent {
  if (!hasIntakes && !hasItems) {
    return {
      eyebrow: "Get started",
      title: "Connect Jira and create an intake to fill Work.",
      body: "Work imports issues from Jira through an intake.",
      actions: [
        { label: "Connect Jira", action: "connectJira" },
        { label: "Create intake", action: "openSyncSettings" },
      ],
    };
  }
  if (hasItems) {
    return {
      eyebrow: "No matching work",
      title: "No work items match the current filters.",
      body: "Reset the filters, or open Intake to check which items the Workspace's intakes import.",
      actions: [{ label: "Open Intake", action: "openSyncSettings" }],
    };
  }
  // Change Plans and Plan reviews have their own empty states (workPlanListModel.ts).
  return {
    eyebrow: "Work items",
    title: "The intake has not imported any work items yet.",
    body: "Run a preview in Intake to see which items match, then enable the intake.",
    actions: [{ label: "Open Intake", action: "openSyncSettings" }],
  };
}
