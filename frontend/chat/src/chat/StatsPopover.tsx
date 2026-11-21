import type { ThreadCodeIntelligenceStats, ThreadUsageStats } from "../chatUsageTypes";
import { formatCost, formatTokenCount } from "./statsFormat";
import { codeIntelligenceSection, workflowRoiSection } from "./statsPopoverSections";

export function StatsPopover({
  stats,
  codeIntelligence,
}: {
  stats: ThreadUsageStats | null;
  codeIntelligence: ThreadCodeIntelligenceStats | null;
}) {
  if (!stats) {
    return (
      <div className="stats-panel">
        <div className="stats-panel__empty">
          No usage data for this chat yet.
        </div>
      </div>
    );
  }
  const workflowRoi = stats.workflowRoi;

  return (
    <div className="stats-panel">
      <div className="stats-panel__eyebrow">Chat Statistics</div>
      <div className="stats-panel__hint">
        Aggregated across the selected chat and its subthreads.
      </div>
      {statsCards(stats)}
      {statsRows(stats)}
      {modelCostSection(stats)}
      {workflowRoi ? workflowRoiSection(workflowRoi) : null}
      {codeIntelligence?.hasData ? codeIntelligenceSection(codeIntelligence) : null}
    </div>
  );
}

type Stats = ThreadUsageStats;

function statsCounts(stats: Stats) {
  const llmRequestCount = stats.llmRequestCount ?? stats.requestCount;
  const toolCallCount = stats.toolCallCount ?? 0;
  const deterministicStepCount = stats.deterministicStepCount ?? 0;
  const cacheReadInputTokens = stats.cacheReadInputTokens ?? 0;
  const cacheWriteInputTokens = stats.cacheWriteInputTokens ?? 0;
  const nonCachedInputTokens = stats.nonCachedInputTokens ?? 0;
  const hasPromptCacheStats =
    cacheReadInputTokens > 0 ||
    cacheWriteInputTokens > 0 ||
    nonCachedInputTokens > 0;
  return { llmRequestCount, toolCallCount, deterministicStepCount, cacheReadInputTokens, cacheWriteInputTokens,
    nonCachedInputTokens, hasPromptCacheStats };
}

// Tokens, requests, tool calls, workflow steps and cost as cards.
function statsCards(stats: Stats) {
  const { llmRequestCount, toolCallCount, deterministicStepCount } = statsCounts(stats);
  return (
    <div className="stats-panel__grid">
      <div className="stats-panel__card">
        <span className="stats-panel__value">
          {formatTokenCount(stats.contextTokens)}
        </span>
        <span className="stats-panel__label">Context</span>
      </div>
      <div className="stats-panel__card">
        <span className="stats-panel__value">
          {formatTokenCount(stats.inputTokens)}
        </span>
        <span className="stats-panel__label">Input</span>
      </div>
      <div className="stats-panel__card">
        <span className="stats-panel__value">
          {formatTokenCount(stats.outputTokens)}
        </span>
        <span className="stats-panel__label">Output</span>
      </div>
      <div className="stats-panel__card">
        <span className="stats-panel__value">
          {formatTokenCount(llmRequestCount)}
        </span>
        <span className="stats-panel__label">LLM requests</span>
      </div>
      <div className="stats-panel__card">
        <span className="stats-panel__value">
          {formatTokenCount(toolCallCount)}
        </span>
        <span className="stats-panel__label">Tool calls</span>
      </div>
      <div className="stats-panel__card">
        <span className="stats-panel__value">
          {formatTokenCount(deterministicStepCount)}
        </span>
        <span className="stats-panel__label">Workflow steps</span>
      </div>
      <div className="stats-panel__card">
        <span className="stats-panel__value">
          {formatCost(stats.totalCost)}
        </span>
        <span className="stats-panel__label">Cost</span>
      </div>
    </div>
  );
}

// Message counts, the last model and provider, a usage note and the prompt cache.
function statsRows(stats: Stats) {
  const { cacheReadInputTokens, cacheWriteInputTokens, nonCachedInputTokens, hasPromptCacheStats } = statsCounts(stats);
  return (
    <div className="stats-panel__rows">
      <div className="stats-panel__row">
        <span>Messages</span>
        <strong>{formatTokenCount(stats.messageCount)}</strong>
      </div>
      <div className="stats-panel__row">
        <span>User</span>
        <strong>{formatTokenCount(stats.userMessageCount)}</strong>
      </div>
      <div className="stats-panel__row">
        <span>Assistant</span>
        <strong>{formatTokenCount(stats.assistantMessageCount)}</strong>
      </div>
      {stats.lastModel ? (
        <div className="stats-panel__row stats-panel__row--stacked">
          <span>Last model</span>
          <strong>{stats.lastModel}</strong>
        </div>
      ) : null}
      {stats.lastProvider ? (
        <div className="stats-panel__row">
          <span>Provider</span>
          <strong>{stats.lastProvider}</strong>
        </div>
      ) : null}
      {stats.zeroCostReason ? (
        <div className="stats-panel__row stats-panel__row--stacked">
          <span>Usage note</span>
          <strong>{stats.zeroCostReason}</strong>
        </div>
      ) : null}
      {hasPromptCacheStats ? (
        <div className="stats-panel__row stats-panel__row--stacked">
          <span>Prompt cache</span>
          <strong>
            {formatTokenCount(nonCachedInputTokens)} non-cached ·{" "}
            {formatTokenCount(cacheReadInputTokens)} read ·{" "}
            {formatTokenCount(cacheWriteInputTokens)} write
          </strong>
        </div>
      ) : null}
    </div>
  );
}

function modelCostSection(stats: Stats) {
  if (!stats.costByModel?.length) return null;
  return (
    <div className="stats-panel__section">
      <div className="stats-panel__section-title">Model cost</div>
      <div className="stats-panel__rows">
        {stats.costByModel.map((row, index) => (
          <div
            key={`${row.provider}:${row.model}:${index}`}
            className="stats-panel__row stats-panel__row--stacked"
          >
            <span>
              {row.provider || "Unknown provider"} /{" "}
              {row.model || "Unknown model"}
            </span>
            <strong>
              {formatCost(row.cost)} · {formatTokenCount(row.requestCount)}{" "}
              req · {formatTokenCount(row.inputTokens)} in ·{" "}
              {formatTokenCount(row.outputTokens)} out
            </strong>
          </div>
        ))}
      </div>
    </div>
  );
}
