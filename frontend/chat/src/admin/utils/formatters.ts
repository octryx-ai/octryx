import { formatDateTime as formatCanonicalDateTime, formatRelative } from "./dateTime";
import type { RuntimeOption } from "../../chatOptionTypes";
import type { SelectedSession } from "../../chatThreadTypes";

const THINKING_OPTIONS = [
  { value: "off", label: "Off" },
  { value: "light", label: "Light" },
  { value: "deep", label: "Deep" },
];

export function formatRelativeMeta(option: RuntimeOption | undefined) {
  if (!option) {
    return "Auto";
  }
  return option.label;
}

export function getRuntimePillLabel(option: RuntimeOption | undefined) {
  if (!option) {
    return "Auto";
  }
  return option.label;
}

export function getProjectPillLabel(projectName: string) {
  return projectName === "No project" ? "Global" : projectName;
}

export function getThinkingPillLabel(thinkingLevel: string) {
  return (
    THINKING_OPTIONS.find((option) => option.value === thinkingLevel)?.label ||
    "Light"
  );
}

export function getSessionStatusLabel(
  session: SelectedSession | null,
  isRunning: boolean,
) {
  const runStatus = String(session?.runStatus || "")
    .trim()
    .toLowerCase();
  const runReason = String(session?.runCompletionReason || "")
    .trim()
    .toLowerCase();
  if (!session) {
    return "Ready";
  }
  if (
    isRunning ||
    runStatus === "in_progress" ||
    session.status === "running"
  ) {
    return "Running";
  }
  if (
    runStatus === "awaiting_approval" ||
    session.status === "pending_approval"
  ) {
    return "Approval needed";
  }
  if (runReason === "human_input_required") {
    return "Needs input";
  }
  if (runStatus === "failed") {
    return "Failed";
  }
  if (runStatus === "stopped" || session.stopReason === "user_cancelled") {
    return "Stopped";
  }
  if (runStatus === "completed") {
    if (runReason === "no_changes_needed") {
      return "Done (no changes)";
    }
    return "Done";
  }
  return "Ready";
}

export function getThreadLifecycleLabel(session: SelectedSession | null) {
  const status = String(session?.status || "")
    .trim()
    .toLowerCase();
  if (!session) {
    return "Ready";
  }
  if (status === "running") {
    return "Running";
  }
  if (status === "pending_approval") {
    return "Approval needed";
  }
  if (status === "archived") {
    return "Archived";
  }
  if (status === "error") {
    return "Error";
  }
  if (status === "stopped" || session.stopReason === "user_cancelled") {
    return "Stopped";
  }
  if (status === "completed") {
    return "Completed";
  }
  return "Active";
}

export function getAgentModeLabel(agentType?: string | null) {
  const normalized = String(agentType || "")
    .trim()
    .toLowerCase();
  if (!normalized) {
    return "Diagnosis";
  }
  return normalized
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

// Dates and times follow the UI's one format (dateTime.ts): user locale, 24 h, numeric date.
export function formatShortDateTime(value: string | null) {
  return formatCanonicalDateTime(value, "");
}

export function formatDateTime(value: string | null | undefined) {
  return formatCanonicalDateTime(value, "—");
}

export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const precision = unitIndex === 0 ? 0 : size >= 10 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[unitIndex]}`;
}

export function formatRelativeTime(value: string | null) {
  // A server time without a zone is UTC (serverTime.ts); an unreadable one shows nothing.
  return formatRelative(value, "");
}

export function formatDateInputValue(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function buildRelativeDateRange(days: number) {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - Math.max(0, days - 1));
  return {
    dateFrom: formatDateInputValue(start),
    dateTo: formatDateInputValue(end),
  };
}

export function formatDurationMs(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) {
    return "—";
  }
  if (value >= 10000) {
    return `${(value / 1000).toFixed(1)} s`;
  }
  return `${Math.round(value)} ms`;
}

export function formatConnectorHealthStatus(status: string | null | undefined) {
  switch ((status || "").toLowerCase()) {
    case "ok":
      return "Healthy";
    case "error":
      return "Unhealthy";
    case "no_test":
      return "No test available";
    default:
      return "Unknown";
  }
}

export function connectorHealthStatusClass(status: string | null | undefined) {
  switch ((status || "").toLowerCase()) {
    case "ok":
      return "connector-card__meta-badge--ok";
    case "error":
      return "connector-card__meta-badge--error";
    default:
      return "connector-card__meta-badge--muted";
  }
}

export function codeRepoBackendBadgeClass(
  ready: boolean,
  mode: string | null | undefined,
) {
  if (ready) {
    return "connector-card__meta-badge--ok";
  }
  if ((mode || "").toLowerCase() === "disabled") {
    return "connector-card__meta-badge--muted";
  }
  return "connector-card__meta-badge--error";
}

export function summarizeTaskError(value: string) {
  const firstLine = value
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);
  if (!firstLine) {
    return "Action failed";
  }
  return firstLine.length > 120 ? `${firstLine.slice(0, 117)}...` : firstLine;
}
