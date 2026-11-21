// Token, cache and working-set tiles of the execution trace, and the raw trace sections.
import type { TurnTrace } from "../chatThreadTypes";
import { extractWithinTurnWorkingSetStats } from "./traceTurnDiff";
import { formatTokenCount } from "./traceToolEventValues";
import { TraceValue } from "./traceUiComponents";
import { callTotals, traceCalls } from "./traceCallsModel";

/** Token counts of the turn: with several calls the tiles show the whole turn, not only the call that wrote the answer. */
function traceUsageCounts(trace: TurnTrace) {
  const usage = trace.usage ?? {};
  const calls = traceCalls(trace);
  const turnTotals = calls.length > 1 ? callTotals(calls) : null;
  const promptTokens = turnTotals ? turnTotals.input : Number(usage.prompt_tokens ?? usage.input_tokens ?? 0);
  const completionTokens = turnTotals ? turnTotals.output : Number(
    usage.completion_tokens ?? usage.output_tokens ?? 0,
  );
  const totalTokens = turnTotals ? turnTotals.input + turnTotals.output : Number(
    usage.total_tokens ?? promptTokens + completionTokens,
  );
  const cacheReadTokens = Number(
    usage.bedrock_cache_read_input_tokens ?? usage.cacheReadInputTokens ?? 0,
  );
  const cacheWriteTokens = Number(
    usage.bedrock_cache_write_input_tokens ?? usage.cacheWriteInputTokens ?? 0,
  );
  const nonCachedInputTokens = Number(
    usage.bedrock_input_tokens_non_cached ?? usage.inputTokens ?? 0,
  );
  const cachePricingStatus =
    typeof usage.bedrock_cache_cost_pricing_status === "string"
      ? usage.bedrock_cache_cost_pricing_status
      : "";
  const hasCacheUsage =
    usage.bedrock_prompt_cache_enabled === true ||
    cacheReadTokens > 0 ||
    cacheWriteTokens > 0 ||
    Boolean(cachePricingStatus);
  return {
    promptTokens, completionTokens, totalTokens, cacheReadTokens, cacheWriteTokens, nonCachedInputTokens,
    cachePricingStatus, hasCacheUsage,
  };
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="turn-trace-usage__item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function TraceUsageTiles({ trace }: { trace: TurnTrace }) {
  const counts = traceUsageCounts(trace);
  return (
    <>
      <div className="turn-trace-usage">
        <Tile label="Input" value={formatTokenCount(counts.promptTokens)} />
        <Tile label="Output" value={formatTokenCount(counts.completionTokens)} />
        <Tile label="Total" value={formatTokenCount(counts.totalTokens)} />
      </div>
      {counts.hasCacheUsage ? (
        <div className="turn-trace-usage turn-trace-usage--working-set">
          <Tile label="Non-cached" value={formatTokenCount(counts.nonCachedInputTokens)} />
          <Tile label="Cache read" value={formatTokenCount(counts.cacheReadTokens)} />
          <Tile label="Cache write" value={formatTokenCount(counts.cacheWriteTokens)} />
          {counts.cachePricingStatus ? <Tile label="Cache pricing" value={counts.cachePricingStatus} /> : null}
        </div>
      ) : null}
    </>
  );
}

const WORKING_SET_TILES = [
  ["Tool msgs", "tool_messages_total"],
  ["Detailed", "detailed_tool_messages"],
  ["Snapshots", "snapshot_tool_messages"],
  ["Collapsed", "collapsed_tool_messages"],
  ["Collapsed calls", "collapsed_assistant_tool_messages"],
  ["Est. prompt", "estimated_prompt_tokens"],
] as const;

export function TraceWorkingSetTiles({ trace }: { trace: TurnTrace }) {
  const workingSetStats = extractWithinTurnWorkingSetStats(trace);
  if (!workingSetStats) return null;
  return (
    <div className="turn-trace-usage turn-trace-usage--working-set">
      {WORKING_SET_TILES.map(([label, key]) => (
        <Tile key={label} label={label} value={formatTokenCount(Number(workingSetStats[key] ?? 0))} />
      ))}
    </div>
  );
}

export function TraceRawSections({ trace }: { trace: TurnTrace }) {
  const sections: [string, unknown][] = [
    ["Input", trace.inputMessages],
    ["Context", trace.contextSnapshot],
    ["Tools", trace.toolTrace],
    ["Output", trace.rawOutput],
    ["Usage", trace.usage],
  ];
  return (
    <div className="turn-trace-sections">
      {sections.map(([title, value]) => (
        <section key={title} className="turn-trace-section">
          <h4>{title}</h4>
          <TraceValue value={value} />
        </section>
      ))}
    </div>
  );
}
