import { sourceLabel } from "./incident/workSourceModel";
import type { WorkItem } from "./workItemTypes";

// What is out of the ordinary on a Work Item. Pure: no React.
//
// A card and the detail show one status (the source's) and, beside it, badges only for exceptions: something
// blocks it, an agent may start it, the agent's work needs a review, the sync went wrong, or its status is not
// mapped. The normal states ("Human only", "unchanged", the workflow state the column already names) get none.

export type WorkException = { key: string; label: string; tone: "attention" | "danger" | "running" };

const SYNC_PROBLEMS: Record<string, string> = {
  removed_from_source_filter: "Removed from the Jira filter",
  conflict: "Sync conflict",
  "sync-error": "Sync failed",
  failed: "Sync failed",
};

// Finished items: nothing blocks them and no agent starts them, even while the automation eligibility still
// lists its reasons (a Done item never reads "Blocked").
const CLOSED_STATES = new Set(["done", "closed", "cancelled", "canceled"]);

export function workItemExceptions(item: WorkItem): WorkException[] {
  const exceptions: WorkException[] = [];
  const eligibility = item.automation_eligibility;
  const state = String(item.work_state || "").trim().toLowerCase();
  const open = !CLOSED_STATES.has(state);
  const blocked = open
    && (state === "blocked" || eligibility?.mode === "blocked" || (eligibility?.blocking_reasons.length ?? 0) > 0);
  if (blocked) exceptions.push({ key: "blocked", label: "Blocked", tone: "attention" });
  if (state === "rejected") exceptions.push({ key: "rejected", label: "Rejected", tone: "danger" });
  if (open && !blocked && eligibility?.requested && eligibility.can_start) {
    exceptions.push(eligibility.mode === "needs_review"
      ? { key: "review", label: "Agent may start · review", tone: "attention" }
      : { key: "agent", label: "Agent may start", tone: "running" });
  }
  const sync = SYNC_PROBLEMS[String(item.sync_state || "").trim().toLowerCase()];
  if (sync) exceptions.push({ key: "sync", label: sync, tone: "attention" });
  if (item.status_mapping?.source === "unmapped") exceptions.push({ key: "unmapped", label: "Status not mapped", tone: "attention" });
  return exceptions;
}

/** The one badge a list row shows: the first exception, or none. */
export function firstException(item: WorkItem): WorkException | null {
  return workItemExceptions(item)[0] ?? null;
}

const words = (value: string | null | undefined) => String(value || "").trim().replaceAll("_", " ");

/** The detail's status line: "Jira: In Progress · development · Priority High" (empty parts left out). */
export function workItemDetailStatus(item: WorkItem): string {
  const source = sourceLabel(item.source_type);
  const status = words(item.source_status);
  return [
    status ? `${source}: ${status}` : `No ${source} status`,
    words(item.work_state),
    item.priority ? `Priority ${words(item.priority)}` : "",
  ].filter(Boolean).join(" · ");
}
