import type { CodingNavKey } from "../coding/CodingAreaNav";
import { workViewOf } from "./workNavRedirects";
import type { WorkNavKey } from "./workTypes";

// One Work area: Work and Coding describe one path, ticket → plan → code →
// pull request, so they share one menu. Each entry still opens its page in the component that owns it (`host`);
// moving between a Work page and a Coding page switches the host, the person sees one area.
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
  // Review: the repository explorer is a Work page like the others (it is also a segment of Admin ›
  // Connections, which opens it here).
  { host: "coding", key: "repositories", label: "Repositories", group: "Deliver" },
  // Jira write-back is an entry of Admin › Connections. Coding rules join the one Rules page later; until then they
  // stay here.
  { host: "coding", key: "rules", label: "Coding rules", group: "Configure" },
  { host: "work", key: "intake", label: "Intake", group: "Configure" },
];

/** The address field that opens an entry's page in its host: a Work page by the name `workViewOf` writes (Plans is
 * `plans`, not its key `changePlans`, which the Work address would not know and would open Runs instead). */
export function entryViewParam(entry: WorkAreaEntry): { name: "work_view" | "coding_view"; value: string } {
  return entry.host === "work"
    ? { name: "work_view", value: workViewOf({ nav: entry.key, itemsMode: "board", plansTab: "all" }) }
    : { name: "coding_view", value: entry.key };
}

/** The menu label of the page a host shows, e.g. "Coding sessions" for Coding's `sessions`. */
export function workAreaLabel(host: WorkAreaHost, key: string): string {
  return WORK_AREA_ENTRIES.find((entry) => entry.host === host && entry.key === key)?.label ?? key;
}

/** The menu group of the page a host shows, e.g. "Deliver". */
export function workAreaGroup(host: WorkAreaHost, key: string): string {
  return WORK_AREA_ENTRIES.find((entry) => entry.host === host && entry.key === key)?.group ?? "";
}
