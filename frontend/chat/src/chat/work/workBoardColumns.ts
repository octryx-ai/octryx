import type { WorkItem } from "./workItemTypes";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";

// The Work board's columns. Pure: no React.
//
// One column per workflow state, in order: the states of the active workflows (the default first), then the
// shared vocabulary (backend DEFAULT_WORKFLOW_STATES) for states no workflow lists. A state an item carries
// that is in neither (e.g. a custom configured mapping) gets its own column after
// them, so no item is ever hidden and every column counts exactly the cards it shows. A state key is never
// re-mapped to another column by guessing.

export const SHARED_WORK_STATES: { key: string; label: string }[] = [
  { key: "intake", label: "Intake" },
  { key: "clarification", label: "Clarification" },
  { key: "ready_for_plan", label: "Ready for plan" },
  { key: "planning", label: "Planning" },
  { key: "plan_review", label: "Plan review" },
  { key: "ready_for_development", label: "Ready for development" },
  { key: "development", label: "Development" },
  { key: "validation", label: "Validation" },
  { key: "review", label: "Review" },
  { key: "changes_requested", label: "Changes requested" },
  { key: "ready_to_merge", label: "Ready to merge" },
  { key: "done", label: "Done" },
  { key: "blocked", label: "Blocked" },
  { key: "rejected", label: "Rejected" },
];

export type WorkBoardColumn = {
  key: string;
  label: string;
  items: WorkItem[];
  /** A state no workflow and no shared vocabulary lists. */
  outsideVocabulary: boolean;
};

/** The state key an item is in: its work_state, normalised only in spelling (case, spaces, dashes). */
export function workStateKey(value: string | null | undefined): string {
  return String(value || "intake").trim().toLowerCase().replace(/[\s-]+/g, "_") || "intake";
}

function humanize(key: string): string {
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The human label of a state key: the active workflows' label, else the key in words (as the shared vocabulary's). */
export function workStateLabel(value: string | null | undefined, workflows: WorkWorkflowDefinition[] = []): string {
  const key = workStateKey(value);
  for (const workflow of workflows.filter((entry) => entry.is_active)) {
    const state = (workflow.states || []).find((entry) => workStateKey(entry.key) === key);
    if (state?.label) return state.label;
  }
  return humanize(key);
}

/** The "Work state" filter's option labels: each state key by its human label. */
export function workStateFilterLabels(states: string[], workflows: WorkWorkflowDefinition[] = []): Record<string, string> {
  return Object.fromEntries(states.map((state) => [state, workStateLabel(state, workflows)]));
}

export function workBoardColumns(
  items: WorkItem[],
  workflows: WorkWorkflowDefinition[] = [],
): WorkBoardColumn[] {
  const order: { key: string; label: string; outsideVocabulary: boolean }[] = [];
  const seen = new Set<string>();
  const add = (key: string, label: string, outsideVocabulary = false) => {
    if (!key || seen.has(key)) return;
    seen.add(key);
    order.push({ key, label, outsideVocabulary });
  };
  const active = workflows
    .filter((workflow) => workflow.is_active)
    .sort((left, right) => Number(right.is_default) - Number(left.is_default));
  for (const workflow of active) {
    for (const state of workflow.states || []) add(workStateKey(state.key), state.label || humanize(state.key));
  }
  for (const state of SHARED_WORK_STATES) add(state.key, state.label);
  const extra = Array.from(new Set(items.map((item) => workStateKey(item.work_state)).filter((key) => !seen.has(key)))).sort();
  for (const key of extra) add(key, humanize(key), true);
  return order.map((column) => ({
    ...column,
    items: items.filter((item) => workStateKey(item.work_state) === column.key),
  }));
}
