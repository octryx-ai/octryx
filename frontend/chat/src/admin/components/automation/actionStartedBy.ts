// What starts an Action, in words (schedulers, inbound webhooks, Work intake). Pure: no React.
import type { PanelTaskRow } from "../taskTypes";

export function startedByLine(task: Pick<PanelTaskRow, "managed_by_work" | "started_by">): string {
  if (task.managed_by_work) return "Started by Work → Intake (managed there)";
  const starts = task.started_by ?? [];
  if (!starts.length) return "Started only with Run now";
  const named = starts.map((start) => {
    const kind = start.kind === "webhook" ? "webhook" : "schedule";
    return `${kind} ${start.name} (${start.when}${start.active === "no" ? ", paused" : ""})`;
  });
  return `Started by ${named.join(", ")}`;
}

// The same in a few words for the Actions table (the long sentence pushed Name to 90 px and cut
// "Last run" off); the full sentence stays the cell's tooltip.
export function startedByShort(task: Pick<PanelTaskRow, "managed_by_work" | "started_by">): string {
  if (task.managed_by_work) return "Work › Intake";
  const starts = task.started_by ?? [];
  if (!starts.length) return "Run now only";
  const [first] = starts;
  const kind = first.kind === "webhook" ? "Webhook" : "Schedule";
  const more = starts.length > 1 ? ` +${starts.length - 1}` : "";
  return `${kind} · ${first.name}${first.active === "no" ? " (paused)" : ""}${more}`;
}

const ACTION_TYPE_LABELS: Record<string, string> = {
  agent_run: "Agent run",
  custom: "Custom",
  secure_work_jira_sync: "Jira intake sync",
  secure_work_servicenow_sync: "ServiceNow intake sync",
};

// An Action's type in words (agent_run → "Agent run"); a type this list does not know reads as its words.
export function actionTypeLabel(type: string | null | undefined): string {
  const key = String(type ?? "").trim();
  if (!key) return "—";
  if (ACTION_TYPE_LABELS[key]) return ACTION_TYPE_LABELS[key];
  const words = key.replace(/^secure_work_/, "work ").replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
