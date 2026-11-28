export type ComplianceRecord = {
  id: string;
  created_at: string | null;
  event_type: string;
  outcome: string | null;
  workspace: { id: string; name: string | null } | null;
  actor: { id: string; display_name: string | null } | null;
  actor_role: string | null;
  resource_type: string;
  resource_id: string | null;
  resource_name: string | null;
  details: Record<string, unknown>;
  hidden_field_count: number;
  classification_level: string | null;
  request_id: string | null;
  session_id: string | null;
};

export type ComplianceRecordPage = { records: ComplianceRecord[]; next_cursor: string | null };

export type ComplianceFilterOptions = {
  event_types: string[];
  workspaces: Array<{ id: string; name: string }>;
  platform_admin: boolean;
};

export type ComplianceFilters = { workspaceId: string; eventType: string; from: string; to: string };

export const EMPTY_FILTERS: ComplianceFilters = { workspaceId: "", eventType: "", from: "", to: "" };

// Dates are picked as local calendar days; "to" includes the whole day, so it ends at the next midnight.
export function complianceQuery(filters: ComplianceFilters, cursor: string | null, limit = 50): string {
  const search = new URLSearchParams({ limit: String(limit) });
  if (filters.workspaceId) search.set("workspace_id", filters.workspaceId);
  if (filters.eventType) search.set("event_type", filters.eventType);
  if (filters.from) search.set("since", localDayStart(filters.from).toISOString());
  if (filters.to) {
    const end = localDayStart(filters.to);
    end.setDate(end.getDate() + 1);
    search.set("until", end.toISOString());
  }
  if (cursor) search.set("cursor", cursor);
  return search.toString();
}

function localDayStart(day: string): Date {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date);
}

export function eventTypeLabel(eventType: string): string {
  const words = eventType.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function outcomeTone(outcome: string | null): "active" | "attention" | "danger" | "neutral" {
  if (outcome === "approved" || outcome === "allowed") return "active";
  if (outcome === "rejected" || outcome === "blocked") return "danger";
  if (outcome === "escalated" || outcome === "redacted") return "attention";
  return "neutral";
}

export function resourceLabel(record: ComplianceRecord): string {
  return record.resource_name || record.resource_id || record.resource_type;
}

export type DetailEntry = { key: string; value: string };

export function detailEntries(details: Record<string, unknown>): DetailEntry[] {
  return Object.entries(details ?? {}).map(([key, value]) => ({
    key,
    value: typeof value === "string" ? value : JSON.stringify(value),
  }));
}

export function hiddenFieldsText(count: number): string | null {
  if (!count) return null;
  return `${count} ${count === 1 ? "more field" : "more fields"} hidden`;
}
