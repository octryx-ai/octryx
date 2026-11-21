// Pure formatting helpers for run traces (status badges, compact values, approvals, plans).
import type { FlowNodeRunTrace } from "./flowRunTypes";

export function prettyTraceJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function recordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

export function toolResultsFromOutput(value: unknown): Record<string, unknown>[] {
  return recordList(asRecord(value).tools);
}

export function planStepsFromRunPlan(value: unknown): Record<string, unknown>[] {
  return recordList(asRecord(value).steps);
}

export function statusClass(status: string): string {
  if (status === "completed") return "flow-builder__badge--ok";
  if (status === "failed") return "flow-builder__badge--danger";
  if (status === "paused") return "flow-builder__badge--warning";
  if (status === "skipped") return "flow-builder__badge--neutral";
  return "flow-builder__badge--draft";
}

export function compactValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (typeof value === "object") return Object.keys(value as Record<string, unknown>).slice(0, 4).join(", ") || "{}";
  return String(value);
}

export function evidenceLabel(value: unknown): string {
  const summary = asRecord(value);
  const count = summary.evidence_count ?? summary.count ?? summary.total_matches ?? summary.total;
  if (typeof count === "number") return `${count} evidence`;
  if (typeof count === "string" && count.trim()) return `${count} evidence`;
  const completedTools = summary.completed_tools;
  if (typeof completedTools === "number") return `${completedTools} tool call${completedTools === 1 ? "" : "s"}`;
  const resultKeys = summary.result_keys;
  if (Array.isArray(resultKeys) && resultKeys.length) return "metadata";
  return compactValue(value);
}

export function approvalIdFromNodeRun(nodeRun: FlowNodeRunTrace | null): string | null {
  const value = asRecord(nodeRun?.output).approval_id;
  if (typeof value === "string" && value) return value;
  const traceValue = nodeRun?.trace_refs?.approval_id;
  return typeof traceValue === "string" && traceValue ? traceValue : null;
}

export function compactToolExample(value: unknown): string {
  const example = asRecord(value);
  const title =
    example.title || example.summary || example.key || example.id || example.url || example.repository || "Evidence item";
  const status = example.status ? ` · ${String(example.status)}` : "";
  const source = example.source || example.space_key || example.author;
  return `${String(title)}${source ? ` · ${String(source)}` : ""}${status}`;
}
