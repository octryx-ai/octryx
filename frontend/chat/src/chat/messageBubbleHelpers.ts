import type { ToolEvent, TurnTrace } from "../chatThreadTypes";
import { formatChatTime, parseChatTimestamp } from "./chatTimestamp";
import { extractCodeIntelligenceSummary } from "./codeIntelligenceMetrics";

export function formatMessageTimestamp(value: string | null) {
  return formatChatTime(value);
}

export function extractThinkingFromTrace(trace: TurnTrace | null | undefined) {
  if (!trace) {
    return "";
  }
  const rawOutput = trace.rawOutput;
  if (!rawOutput || typeof rawOutput !== "object" || Array.isArray(rawOutput)) {
    return "";
  }
  const thinking = rawOutput.thinking;
  return typeof thinking === "string" ? thinking.trim() : "";
}

function formatDuration(value: number | null | undefined) {
  const duration = Number(value || 0);
  if (!Number.isFinite(duration) || duration <= 0) {
    return null;
  }
  if (duration >= 1000) {
    return `${(duration / 1000).toFixed(duration >= 10_000 ? 0 : 1)} s`;
  }
  return `${Math.round(duration)} ms`;
}

export function extractPerformanceSections(
  trace: TurnTrace | null | undefined,
  toolEvents: ToolEvent[],
) {
  const usage = trace?.usage ?? {};
  const rawOutput = trace?.rawOutput ?? {};
  const promptTokens = Number(usage.prompt_tokens ?? usage.input_tokens ?? 0);
  const completionTokens = Number(
    usage.completion_tokens ?? usage.output_tokens ?? 0,
  );
  const totalTokens = Number(
    usage.total_tokens ?? promptTokens + completionTokens,
  );
  const requestDurationMs = Number(usage.request_duration_ms ?? 0);
  const cacheReadTokens = Number(
    usage.bedrock_cache_read_input_tokens ?? usage.cacheReadInputTokens ?? 0,
  );
  const cacheWriteTokens = Number(
    usage.bedrock_cache_write_input_tokens ?? usage.cacheWriteInputTokens ?? 0,
  );
  const cachePricingStatus =
    typeof usage.bedrock_cache_cost_pricing_status === "string" &&
    usage.bedrock_cache_cost_pricing_status.trim()
      ? usage.bedrock_cache_cost_pricing_status.trim()
      : null;

  const modelSteps = [
    { label: "Model request", value: formatDuration(requestDurationMs) },
    {
      label: "Load model",
      value: formatDuration(Number(usage.load_duration_ms ?? 0)),
    },
    {
      label: "Prompt eval",
      value: formatDuration(Number(usage.prompt_eval_duration_ms ?? 0)),
    },
    {
      label: "Generate answer",
      value: formatDuration(Number(usage.eval_duration_ms ?? 0)),
    },
    {
      label: "Total runtime",
      value: formatDuration(Number(usage.total_duration_ms ?? 0)),
    },
  ].filter((item) => item.value);

  const visibleToolEvents = toolEvents.filter(
    (event) => Number(event.durationMs || 0) > 0,
  );
  const toolSteps = visibleToolEvents.map((event) => ({
    id: event.id,
    label: event.toolName,
    status: event.status,
    value: formatDuration(event.durationMs),
  }));
  const totalToolDurationMs = visibleToolEvents.reduce(
    (total, event) => total + Number(event.durationMs || 0),
    0,
  );
  const runtimeAttemptsRaw = Array.isArray(rawOutput.runtime_attempts)
    ? rawOutput.runtime_attempts
    : [];
  const runtimeAttempts = runtimeAttemptsRaw
    .filter(
      (attempt): attempt is Record<string, unknown> =>
        Boolean(attempt) &&
        typeof attempt === "object" &&
        !Array.isArray(attempt),
    )
    .map((attempt, index) => ({
      id: `${String(attempt.target_id || attempt.model || index)}`,
      label: `${String(attempt.provider || "runtime")} / ${String(attempt.model || "").trim() || "unknown"}`,
      status: String(attempt.status || "unknown"),
      error:
        typeof attempt.error === "string" && attempt.error.trim()
          ? attempt.error.trim()
          : null,
      value: formatDuration(Number(attempt.duration_ms || 0)),
    }));

  const summary = [
    {
      label: "Input tokens",
      value: promptTokens > 0 ? String(promptTokens) : null,
    },
    {
      label: "Output tokens",
      value: completionTokens > 0 ? String(completionTokens) : null,
    },
    {
      label: "Total tokens",
      value: totalTokens > 0 ? String(totalTokens) : null,
    },
    {
      label: "Cache read",
      value: cacheReadTokens > 0 ? String(cacheReadTokens) : null,
    },
    {
      label: "Cache write",
      value: cacheWriteTokens > 0 ? String(cacheWriteTokens) : null,
    },
    { label: "Cache pricing", value: cachePricingStatus },
    { label: "Request time", value: formatDuration(requestDurationMs) },
    { label: "Tool total", value: formatDuration(totalToolDurationMs) },
    {
      label: "Finished as",
      value:
        typeof usage.done_reason === "string" && usage.done_reason.trim()
          ? usage.done_reason
          : null,
    },
  ].filter((item) => item.value);

  const codeIntelligence = extractCodeIntelligenceSummary(toolEvents);

  return {
    summary,
    modelSteps,
    toolSteps,
    runtimeAttempts,
    codeIntelligence,
    hasPerformance:
      summary.length > 0 ||
      modelSteps.length > 0 ||
      toolSteps.length > 0 ||
      runtimeAttempts.length > 0 ||
      codeIntelligence.hasData,
  };
}

export function isObjectRecord(
  value: unknown,
): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function getToolRows(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(isObjectRecord);
}

export function getToolRowTitle(row: Record<string, unknown>) {
  const title = typeof row.title === "string" ? row.title.trim() : "";
  if (title) {
    return title;
  }
  const key = typeof row.key === "string" ? row.key.trim() : "";
  if (key) {
    return key;
  }
  const id = typeof row.id === "string" ? row.id.trim() : "";
  return id || "Untitled";
}
