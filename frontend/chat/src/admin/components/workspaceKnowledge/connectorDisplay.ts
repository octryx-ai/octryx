// Source Sync connector display: kind labels, schedule intervals, times and the listing cursor in words.
import { formatApiTime } from "./apiTime";
import { REST_KIND } from "./rest/restSourceForm";
import type { SyncCursor } from "./connectorTypes";

export const KIND_LABEL: Record<string, string> = {
  confluence: "Confluence",
  jira: "Jira",
  servicenow: "ServiceNow",
  git_repository: "Git repository",
  kubernetes: "Kubernetes inventory",
  [REST_KIND]: "REST API",
};

// "15 min", "6 h", "1 d 12 h": a schedule interval in minutes, in the largest whole units.
export function intervalText(minutes: number): string {
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  const parts = [days ? `${days} d` : "", hours ? `${hours} h` : "", rest ? `${rest} min` : ""].filter(Boolean);
  return parts.join(" ") || "0 min";
}

export function formatTime(value: string | null | undefined): string {
  return formatApiTime(value);
}

export function cursorText(cursor: SyncCursor): string {
  if (cursor.pass_started_at) return `Pass ${cursor.pass_number} open since ${formatTime(cursor.pass_started_at)}; the next run resumes it`;
  if (cursor.completed_passes) return `${cursor.completed_passes} full pass${cursor.completed_passes === 1 ? "" : "es"}, last ${formatTime(cursor.last_completed_at)}`;
  return "No pass yet";
}
