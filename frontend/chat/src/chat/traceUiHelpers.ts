// Tool event grouping and summaries for the trace UI.
import type { ToolEvent } from "../chatThreadTypes";
import { extractExecutionEvent, formatDurationMs, humanizeToolName } from "./traceToolEventValues";

export function groupToolEvents(events: ToolEvent[]) {
  const groups: Array<{
    key: string;
    toolName: string;
    status: string;
    statuses: string[];
    events: ToolEvent[];
  }> = [];
  for (const event of events) {
    const previous = groups[groups.length - 1];
    const normalizedStatus = String(event.status || "")
      .trim()
      .toLowerCase();
    const key = event.toolName;
    if (previous && previous.key === key) {
      previous.events.push(event);
      if (!previous.statuses.includes(normalizedStatus)) {
        previous.statuses.push(normalizedStatus);
      }
      previous.status =
        previous.statuses.length === 1
          ? previous.statuses[0]
          : previous.statuses.includes("running")
            ? "running"
            : "mixed";
      continue;
    }
    groups.push({
      key,
      toolName: event.toolName,
      status: normalizedStatus || "pending",
      statuses: normalizedStatus ? [normalizedStatus] : [],
      events: [event],
    });
  }
  return groups;
}

export function summarizeToolGroup(events: ToolEvent[]) {
  const explicitSummary = events
    .map((event) => summarizeToolEvent(event))
    .find((value) => value.trim());
  if (explicitSummary) {
    return explicitSummary;
  }
  const toolNames = Array.from(
    new Set(
      events.map((event) => humanizeToolName(event.toolName)).filter(Boolean),
    ),
  );
  if (!toolNames.length) {
    return `${events.length} step${events.length === 1 ? "" : "s"}`;
  }
  if (toolNames.length === 1) {
    return `${events.length} ${toolNames[0]} step${events.length === 1 ? "" : "s"}`;
  }
  return `${events.length} steps across ${toolNames.slice(0, 2).join(" + ")}${toolNames.length > 2 ? "..." : ""}`;
}

export function countToolArtifacts(events: ToolEvent[]) {
  return events.reduce(
    (total, event) => total + (event.artifacts?.length ?? 0),
    0,
  );
}

export function summarizeToolEventMeta(event: ToolEvent) {
  const parts = [event.status];
  const executionEvent = extractExecutionEvent(event);
  const kind = String(executionEvent?.kind || "").trim();
  const executionStatus = String(executionEvent?.status || "").trim();
  if (kind || executionStatus) {
    parts.push([kind, executionStatus].filter(Boolean).join(": "));
  }
  const exitCode = executionEvent?.exit_code;
  if (typeof exitCode === "number") {
    parts.push(`exit ${exitCode}`);
  }
  const durationLabel = formatDurationMs(event.durationMs);
  if (durationLabel) {
    parts.push(durationLabel);
  }
  if (event.artifacts?.length) {
    parts.push(
      `${event.artifacts.length} output${event.artifacts.length === 1 ? "" : "s"}`,
    );
  }
  return parts;
}

function resolvePreviewSource(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const preview = record.preview;
  if (!preview || typeof preview !== "object" || Array.isArray(preview)) {
    return record;
  }
  const compactResult = (preview as Record<string, unknown>).compact_result;
  if (
    !compactResult ||
    typeof compactResult !== "object" ||
    Array.isArray(compactResult)
  ) {
    return record;
  }
  return compactResult as Record<string, unknown>;
}

export function summarizeToolEvent(event: ToolEvent) {
  const source = resolvePreviewSource(event.result);
  if (!source) {
    return "";
  }
  const directSummaryKeys = [
    "summary",
    "message",
    "title",
    "change_description",
    "reason",
    "status_message",
  ];
  for (const key of directSummaryKeys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  const path = typeof source.path === "string" ? source.path.trim() : "";
  if (path) {
    return path;
  }
  const stdout = typeof source.stdout === "string" ? source.stdout.trim() : "";
  if (stdout) {
    return stdout.split("\n")[0];
  }
  const stderr = typeof source.stderr === "string" ? source.stderr.trim() : "";
  if (stderr) {
    return stderr.split("\n")[0];
  }
  const changed = typeof source.changed === "number" ? source.changed : null;
  const created = typeof source.created === "number" ? source.created : null;
  const removed = typeof source.removed === "number" ? source.removed : null;
  if (changed !== null || created !== null || removed !== null) {
    return [
      created !== null ? `${created} created` : "",
      changed !== null ? `${changed} changed` : "",
      removed !== null ? `${removed} removed` : "",
    ]
      .filter(Boolean)
      .join(" · ");
  }
  return "";
}
