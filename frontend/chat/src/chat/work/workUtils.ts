import { formatDateTime as formatCanonicalDateTime } from "../../admin/utils/dateTime";
import { sourceMatches } from "./incident/workSourceModel";
import type { WorkFilters } from "./workTypes";
import type { WorkItem } from "./workItemTypes";

export const EMPTY_WORK_FILTERS: WorkFilters = {
  search: "",
  sourceType: "",
  sourceProject: "",
  sourceStatuses: [],
  workState: "",
  syncState: "",
  assignees: [],
  labels: [],
  automationMode: "",
  fixVersions: [],
  sprints: [],
};

export const WORK_AUTOMATION_FILTERS = [
  { value: "octryx_requested", label: "Octryx requested" },
  { value: "can_start", label: "Can start" },
  { value: "needs_review", label: "Needs review" },
  { value: "direct", label: "Direct" },
  { value: "blocked", label: "Blocked" },
  { value: "human_only", label: "Human only" },
];

export function filterWorkItems(items: WorkItem[], filters: WorkFilters): WorkItem[] {
  const search = filters.search.trim().toLowerCase();
  return items.filter((item) => {
    if (!sourceMatches(item, filters.sourceType)) return false;
    if (filters.sourceProject && item.source_project_key !== filters.sourceProject) return false;
    if (filters.sourceStatuses.length > 0 && !filters.sourceStatuses.includes(item.source_status || "")) return false;
    if (filters.workState && item.work_state !== filters.workState) return false;
    if (filters.syncState && item.sync_state !== filters.syncState) return false;
    if (filters.assignees.length > 0 && !filters.assignees.includes(item.assignee || "")) return false;
    if (filters.labels.length > 0 && !filters.labels.some((label) => (item.labels || []).includes(label))) return false;
    if (filters.automationMode && !automationFilterMatches(item, filters.automationMode)) return false;
    if (filters.fixVersions.length > 0 && !filters.fixVersions.some((version) => (item.fix_versions || []).includes(version))) {
      return false;
    }
    if (filters.sprints.length > 0 && !filters.sprints.includes(workItemSprintLabel(item))) return false;
    if (!search) return true;
    return [
      item.source_key,
      item.title,
      item.assignee,
      // People are found by name too.
      item.assignee_display,
      item.reporter_display,
      item.source_project_key,
      item.source_status,
      workItemSprintLabel(item),
      ...(item.fix_versions || []),
      ...(item.labels || []),
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(search));
  });
}

export function workItemSprintLabel(item: WorkItem): string {
  const sprint = item.sprint || {};
  const name = String(sprint.name || "").trim();
  const id = String(sprint.id || "").trim();
  if (name && id) return `${name} (${id})`;
  return name || id;
}

export function automationFilterMatches(item: WorkItem, filter: string): boolean {
  const eligibility = item.automation_eligibility;
  if (!eligibility) return filter === "human_only";
  if (filter === "octryx_requested") return eligibility.requested;
  if (filter === "can_start") return eligibility.can_start;
  if (filter === "needs_review") return eligibility.can_start && eligibility.mode === "needs_review";
  if (filter === "direct") return eligibility.can_start && eligibility.mode === "direct";
  if (filter === "blocked") return eligibility.mode === "blocked" || eligibility.blocking_reasons.length > 0;
  if (filter === "human_only") return !eligibility.requested;
  return true;
}

export function automationBadgeValue(item: WorkItem): string {
  const eligibility = item.automation_eligibility;
  if (!eligibility?.requested) return "Human only";
  if (eligibility.mode === "blocked" || eligibility.blocking_reasons.length > 0) return "Octryx blocked";
  if (eligibility.mode === "direct") return "Octryx direct";
  if (eligibility.mode === "needs_review") return "Octryx review";
  return "Octryx requested";
}

export function uniqueSorted(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value)))).sort((a, b) =>
    a.localeCompare(b),
  );
}

export function formatDateTime(value?: string | null): string {
  // The UI's one date format (admin/utils/dateTime.ts); a server time without a zone is UTC.
  if (!value) return "Never";
  return formatCanonicalDateTime(value, value);
}

export function badgeTone(value?: string | null): string {
  const normalized = (value || "").toLowerCase();
  if (["done", "closed", "resolved", "active", "imported", "unchanged", "octryx direct"].includes(normalized)) return "active";
  if (["in progress", "in_progress", "running", "updated", "octryx requested"].includes(normalized)) return "running";
  if (["blocked", "removed_from_source_filter", "conflict", "sync-error", "octryx blocked", "octryx review"].includes(normalized)) return "attention";
  if (["failed", "error", "rejected"].includes(normalized)) return "danger";
  return "neutral";
}
