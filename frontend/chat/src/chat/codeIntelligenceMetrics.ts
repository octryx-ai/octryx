import type { ChatMessage, ToolEvent } from "../chatThreadTypes";

const FALLBACK_BACKENDS = new Set(["regex", "ripgrep", "snapshot", "manual"]);

export type CodeIntelligenceAggregate = {
  rows: Array<{ label: string; value: string }>;
  repositoryBackends: Record<string, string> | null;
  totalToolCalls: number;
  codeToolCalls: number;
  fallbackToolCalls: number;
  fallbackRate: number;
  hasData: boolean;
};

function normalizeBackendEntries(value: unknown) {
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry || "").trim()).filter(Boolean);
  }
  return [];
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

function collectBackendCounts(value: unknown, counts: Map<string, number>) {
  for (const entry of normalizeBackendEntries(value)) {
    counts.set(entry, (counts.get(entry) || 0) + 1);
  }
}

function summarizeBackendCounts(counts: Map<string, number>) {
  return Array.from(counts.entries())
    .sort(
      (left, right) => right[1] - left[1] || left[0].localeCompare(right[0]),
    )
    .map(([name, count]) => `${name} (${count})`)
    .join(", ");
}

function hasFallbackBackend(provenance: Record<string, unknown>) {
  const values = [
    provenance.search_backend,
    provenance.structure_backend,
    provenance.definition_backends,
    provenance.reference_backends,
    provenance.caller_backends,
    provenance.outline_backends,
  ];
  return values.some((value) =>
    normalizeBackendEntries(value).some((entry) =>
      FALLBACK_BACKENDS.has(entry),
    ),
  );
}

export function extractCodeIntelligenceSummary(
  toolEvents: ToolEvent[],
): CodeIntelligenceAggregate {
  const searchBackends = new Map<string, number>();
  const definitionBackends = new Map<string, number>();
  const referenceBackends = new Map<string, number>();
  const callerBackends = new Map<string, number>();
  const outlineBackends = new Map<string, number>();
  let repositoryBackends: Record<string, string> | null = null;
  let codeToolCalls = 0;
  let fallbackToolCalls = 0;

  for (const event of toolEvents) {
    const provenance = extractToolProvenance(event.result);
    if (!provenance) {
      continue;
    }
    codeToolCalls += 1;
    collectBackendCounts(provenance.search_backend, searchBackends);
    collectBackendCounts(provenance.definition_backends, definitionBackends);
    collectBackendCounts(provenance.reference_backends, referenceBackends);
    collectBackendCounts(provenance.caller_backends, callerBackends);
    collectBackendCounts(provenance.outline_backends, outlineBackends);
    if (hasFallbackBackend(provenance)) {
      fallbackToolCalls += 1;
    }
    if (
      !repositoryBackends &&
      provenance.repository_effective_backends &&
      typeof provenance.repository_effective_backends === "object" &&
      !Array.isArray(provenance.repository_effective_backends)
    ) {
      repositoryBackends = Object.fromEntries(
        Object.entries(
          provenance.repository_effective_backends as Record<string, unknown>,
        )
          .map(([key, value]) => [key, String(value || "").trim()])
          .filter((entry) => entry[0] && entry[1]),
      );
    }
  }

  const rows = [
    { label: "Search", value: summarizeBackendCounts(searchBackends) },
    { label: "Definitions", value: summarizeBackendCounts(definitionBackends) },
    { label: "References", value: summarizeBackendCounts(referenceBackends) },
    { label: "Callers", value: summarizeBackendCounts(callerBackends) },
    { label: "Outline", value: summarizeBackendCounts(outlineBackends) },
  ].filter((item) => item.value);

  return {
    rows,
    repositoryBackends,
    totalToolCalls: toolEvents.length,
    codeToolCalls,
    fallbackToolCalls,
    fallbackRate: codeToolCalls > 0 ? fallbackToolCalls / codeToolCalls : 0,
    hasData:
      rows.length > 0 ||
      Boolean(repositoryBackends && Object.keys(repositoryBackends).length),
  };
}

export function aggregateThreadCodeIntelligence(messages: ChatMessage[]) {
  const toolEvents = messages.flatMap((message) => message.toolEvents ?? []);
  return extractCodeIntelligenceSummary(toolEvents);
}
