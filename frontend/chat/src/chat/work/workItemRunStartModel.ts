import type { RuntimeTargetChoices, RuntimeTargetOption } from "../workflowRun/runtimeTargetModel";

// Starting a workflow run from a Work Item. Pure: no React.
//
// "Start run" is the primary action; while it cannot start, it is disabled, neutral and says why. The run
// location's sentence stands below its select, so the select's label is never cut. Repository, branch and the
// run limits are rare choices and live under "Advanced".

/** Why "Start run" cannot be pressed now; null when it can. */
export function startRunBlockedReason(workflowKey: string, busy: boolean, projectId: string | null | undefined): string | null {
  if (busy) return "Starting…";
  // A workflow run needs a Workspace (the server refuses it with `workspace_required`).
  if (!projectId) return "This Work item has no Workspace: move it to a Workspace to start a run";
  if (!workflowKey) return "Choose a workflow first";
  return null;
}

/** The run location the select shows: the person's choice, else the server's default. */
export function chosenTarget(targets: RuntimeTargetChoices, targetKey: string): RuntimeTargetOption | null {
  const key = targetKey || targets.default;
  return targets.options.find((option) => option.key === key) ?? null;
}

/** The sentence below the run location: the server's help, or what an offline device means. */
export function targetHelp(option: RuntimeTargetOption | null): string {
  if (!option) return "";
  const help = typeof option.help === "string" ? option.help.trim() : "";
  if (help) return help;
  if (option.target.kind === "device" && option.online === false) return "This device is offline; the run waits for it.";
  return "";
}

/** Whether "Advanced" opens by itself: only when one of its fields already holds a value. */
export function advancedOpen(repository: string, branch: string, limits: string): boolean {
  return Boolean(repository.trim() || branch.trim() || limits.trim());
}

export const ADVANCED_FIELDS = {
  repository: {
    label: "Repository",
    hint: "Leave empty to use the item's or the Workspace's repository.",
    placeholder: "e.g. bitbucket:TEAM/payments-api",
  },
  branch: {
    label: "Branch to review",
    hint: "Only for Review & PR workflows.",
    placeholder: "e.g. feature/PROJ-123-login-fix",
  },
  loopLimit: {
    label: "Rounds per loop",
    hint: "How often a loop may repeat in runs of this item. Leave empty for the workflow's own limit.",
    placeholder: "e.g. 3",
  },
  costBudget: {
    label: "Cost budget (USD)",
    hint: "A run of this item pauses when its model cost reaches this amount. Leave empty for the workflow's own budget.",
    placeholder: "e.g. 5",
  },
} as const;
