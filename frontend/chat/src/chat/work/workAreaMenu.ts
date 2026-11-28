import type { CodingNavKey } from "../coding/CodingAreaNav";
import { workViewOf } from "./workNavRedirects";
import type { WorkNavKey } from "./workTypes";

// Work and Coding describe one path (ticket → plan → code → pull request), so they share one menu.
export type WorkAreaHost = "work" | "coding";
export type WorkAreaEntry =
  | { host: "work"; key: WorkNavKey; label: string; group: string }
  | { host: "coding"; key: CodingNavKey; label: string; group: string };

export const WORK_AREA_ENTRIES: WorkAreaEntry[] = [
  { host: "work", key: "board", label: "Work items", group: "Plan" },
  { host: "work", key: "changePlans", label: "Plans", group: "Plan" },
  { host: "work", key: "runs", label: "Runs", group: "Deliver" },
  { host: "work", key: "epics", label: "Epics", group: "Deliver" },
  { host: "coding", key: "sessions", label: "Coding sessions", group: "Deliver" },
  { host: "coding", key: "repositories", label: "Repositories", group: "Deliver" },
  { host: "coding", key: "rules", label: "Coding rules", group: "Configure" },
  { host: "work", key: "intake", label: "Intake", group: "Configure" },
];

/** Plans is `plans`, not its key `changePlans`, which the Work address would not know and would open Runs instead. */
export function entryViewParam(entry: WorkAreaEntry): { name: "work_view" | "coding_view"; value: string } {
  return entry.host === "work"
    ? { name: "work_view", value: workViewOf({ nav: entry.key, itemsMode: "board", plansTab: "all" }) }
    : { name: "coding_view", value: entry.key };
}

export function workAreaLabel(host: WorkAreaHost, key: string): string {
  return WORK_AREA_ENTRIES.find((entry) => entry.host === host && entry.key === key)?.label ?? key;
}

export function workAreaGroup(host: WorkAreaHost, key: string): string {
  return WORK_AREA_ENTRIES.find((entry) => entry.host === host && entry.key === key)?.group ?? "";
}
