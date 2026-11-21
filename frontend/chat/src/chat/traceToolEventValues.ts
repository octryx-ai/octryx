// Tool event value readers: visible tool names, durations, dates, provenance, execution events and evidence badges.
import type { ToolEvent } from "../chatThreadTypes";
import { formatChatDateTime } from "./chatTimestamp";

const INTERNAL_TOOL_NAMES = new Set([
  "batch",
  "load_tool_artifact",
  "release_context",
]);

function normalizeToolName(value: string) {
  const stripped = String(value || "").replace(/<[^>]+>/g, " ");
  const match = stripped.match(/[A-Za-z_][A-Za-z0-9_]*/);
  return match ? match[0] : String(value || "").trim();
}

export function visibleToolEvents(events: ToolEvent[]) {
  return events
    .map((event) => ({
      ...event,
      toolName: normalizeToolName(event.toolName),
    }))
    .filter(
      (event) => event.toolName && !INTERNAL_TOOL_NAMES.has(event.toolName),
    );
}

export function humanizeToolName(value: string) {
  return normalizeToolName(value)
    .replace(/_/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function formatDurationMs(value: number | null | undefined) {
  const duration = Number(value || 0);
  if (!Number.isFinite(duration) || duration <= 0) {
    return null;
  }
  return duration >= 1000
    ? `${(duration / 1000).toFixed(duration >= 10_000 ? 0 : 1)} s`
    : `${Math.round(duration)} ms`;
}

export function formatDateTime(value: string | null | undefined) {
  return formatChatDateTime(value, value || "—");
}

export function formatTokenCount(value: number) {
  return new Intl.NumberFormat("de-CH").format(value);
}

export function extractToolProvenance(result: ToolEvent["result"]) {
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    return null;
  }
  const provenance = (result as Record<string, unknown>).provenance;
  if (
    !provenance ||
    typeof provenance !== "object" ||
    Array.isArray(provenance)
  ) {
    return null;
  }
  return provenance as Record<string, unknown>;
}

function recordFromValue(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function extractExecutionEvent(event: ToolEvent) {
  if (event.executionEvent && typeof event.executionEvent === "object") {
    return event.executionEvent;
  }
  const result = recordFromValue(event.result);
  if (!result) {
    return null;
  }
  const direct = recordFromValue(result.execution_event);
  if (direct) {
    return direct;
  }
  const preview = recordFromValue(result.preview);
  const compact = preview ? recordFromValue(preview.compact_result) : null;
  return compact ? recordFromValue(compact.execution_event) : null;
}

function nestedRecord(
  record: Record<string, unknown>,
  key: string,
): Record<string, unknown> | null {
  return recordFromValue(record[key]);
}

export function extractEvidenceContract(result: ToolEvent["result"]) {
  const record = recordFromValue(result);
  if (!record) {
    return null;
  }
  const candidates = [
    nestedRecord(record, "evidence_contract"),
    nestedRecord(nestedRecord(record, "compact_result") ?? {}, "evidence_contract"),
    nestedRecord(
      nestedRecord(nestedRecord(record, "preview") ?? {}, "compact_result") ?? {},
      "evidence_contract",
    ),
    nestedRecord(nestedRecord(record, "result") ?? {}, "evidence_contract"),
  ];
  return candidates.find(Boolean) ?? null;
}

export function formatEvidenceContractBadge(
  contract: Record<string, unknown> | null,
) {
  if (!contract) {
    return null;
  }
  const status = String(contract.status || "").trim().toLowerCase();
  const state = String(contract.evidence_state || "").trim();
  if (status === "passed") {
    return state === "compact_evidence" ? "evidence: compact" : "evidence: ok";
  }
  return "evidence: incomplete";
}

export function formatProvenanceBadges(provenance: Record<string, unknown>) {
  const badges: string[] = [];
  const searchBackend = String(provenance.search_backend || "").trim();
  const structureBackend = String(provenance.structure_backend || "").trim();
  if (searchBackend) {
    badges.push(`search: ${searchBackend}`);
  }
  if (structureBackend) {
    badges.push(`structure: ${structureBackend}`);
  }
  const definitionBackends = Array.isArray(provenance.definition_backends)
    ? (provenance.definition_backends as unknown[])
        .map((value) => String(value))
        .filter(Boolean)
    : [];
  if (definitionBackends.length) {
    badges.push(`definitions: ${definitionBackends.join(", ")}`);
  }
  const referenceBackends = Array.isArray(provenance.reference_backends)
    ? (provenance.reference_backends as unknown[])
        .map((value) => String(value))
        .filter(Boolean)
    : [];
  if (referenceBackends.length) {
    badges.push(`references: ${referenceBackends.join(", ")}`);
  }
  const callerBackends = Array.isArray(provenance.caller_backends)
    ? (provenance.caller_backends as unknown[])
        .map((value) => String(value))
        .filter(Boolean)
    : [];
  if (callerBackends.length) {
    badges.push(`callers: ${callerBackends.join(", ")}`);
  }
  const outlineBackends = Array.isArray(provenance.outline_backends)
    ? (provenance.outline_backends as unknown[])
        .map((value) => String(value))
        .filter(Boolean)
    : [];
  if (outlineBackends.length) {
    badges.push(`outline: ${outlineBackends.join(", ")}`);
  }
  return badges;
}
