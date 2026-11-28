import { readJson } from "../../admin/utils/adminPanelHelpers";
import type { WorkItem } from "./workItemTypes";

export type WorkItemCloseResult = {
  closed: boolean;
  mode: "source_transition" | "local_only" | "already_closed" | string;
  source_key?: string;
  work_state?: string;
  source_status?: string | null;
  write_back?: { enabled?: boolean; reason?: string | null } | null;
  jira?: { transition_name?: string | null; resulting_status?: string | null; comment_posted?: boolean } | null;
};

const CLOSE_REFUSALS: Record<string, string> = {
  transition_not_available: "Jira offers no transition to a done status for this item, so it was not closed.",
  scope_not_allowed: "Write-back may not change this item's project, so it was not closed.",
  write_back_not_configured: "Write-back to the source is not set up, so it was not closed there.",
  write_back_failed: "The source refused the change, so the item was not closed.",
};

export function sourceName(item: Pick<WorkItem, "source_type">): string {
  return String(item.source_type || "").trim().toLowerCase() === "servicenow" ? "ServiceNow" : "Jira";
}

/** null when this server does not tell before the close. */
export function writeBackKnown(item: WorkItem): boolean | null {
  const extra = item as WorkItem & { close_mode?: unknown; write_back?: { enabled?: unknown } | null };
  if (extra.close_mode === "source_transition") return true;
  if (extra.close_mode === "local_only") return false;
  const value = extra.write_back?.enabled;
  return typeof value === "boolean" ? value : null;
}

export function closeWhereText(item: WorkItem): string {
  const source = sourceName(item);
  const writeBack = writeBackKnown(item);
  if (writeBack === true) return `Closes ${item.source_key} in ${source}.`;
  if (writeBack === false) return `Closes ${item.source_key} here only; ${source} is not changed.`;
  return `Closes ${item.source_key} in ${source} when write-back is set up for it; otherwise here only, and ${source} is not changed.`;
}

export function closeResultText(item: Pick<WorkItem, "source_key" | "source_type">, result: WorkItemCloseResult): string {
  const key = result.source_key || item.source_key;
  const source = sourceName(item);
  if (result.mode === "already_closed") return `${key} was already closed.`;
  if (result.mode === "source_transition") {
    const status = result.jira?.resulting_status || result.source_status;
    return status ? `${key} closed in ${source} (now "${status}").` : `${key} closed in ${source}.`;
  }
  return `${key} closed here; ${source} was not changed.`;
}

export function closeRefusalText(failure: unknown): string {
  const code = (failure as { code?: unknown } | null)?.code;
  if (typeof code === "string" && CLOSE_REFUSALS[code]) return CLOSE_REFUSALS[code];
  return failure instanceof Error && failure.message ? failure.message : "The item could not be closed.";
}

export function isClosedItem(item: Pick<WorkItem, "work_state">): boolean {
  return ["done", "closed", "cancelled", "canceled"].includes(String(item.work_state || "").toLowerCase());
}

export async function closeWorkItem(workItemId: string, reason: string): Promise<WorkItemCloseResult> {
  return readJson<WorkItemCloseResult>(`/api/v1/secure-work/work-items/${encodeURIComponent(workItemId)}/close`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });
}
