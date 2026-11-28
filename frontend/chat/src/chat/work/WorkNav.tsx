import type { WorkNavKey } from "./workTypes";

// `purpose` is one sentence; more belongs in help/work/<page>.md.
export type WorkNavItem = { key: WorkNavKey; label: string; section: string; purpose: string };

export const WORK_NAV_ITEMS: WorkNavItem[] = [
  { key: "runs", label: "Runs", section: "Delivery", purpose: "What waits for you, then every run with its step, result and cost." },
  { key: "epics", label: "Epics", section: "Delivery", purpose: "An epic's stories by progress: done, in review, in progress, open." },
  { key: "board", label: "Work items", section: "Plan", purpose: "The Workspace's work items, from intake to done." },
  { key: "changePlans", label: "Plans", section: "Delivery", purpose: "Change plans for work items, and the ones waiting for review." },
  { key: "intake", label: "Intake", section: "Configure", purpose: "Which items flow into Work, when, and how their states map." },
  { key: "writeback", label: "Jira write-back", section: "Configure", purpose: "What Work writes back to Jira when an item changes state." },
];

export function workNavItem(key: WorkNavKey): WorkNavItem {
  return WORK_NAV_ITEMS.find((item) => item.key === key) ?? WORK_NAV_ITEMS[0];
}

