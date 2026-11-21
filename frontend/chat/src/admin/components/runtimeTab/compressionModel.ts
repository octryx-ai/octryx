// Pure model of the tool output compression page.
// Reduction source: backend/app/services/tool_result_compression/service.py —
// ratio = round((1 - compressed_tokens / original_tokens) * 100), clamped to 0..100.

export type ToolResultCompressor = {
  id: string;
  tool_name: string;
  strategy: string;
  config?: Record<string, unknown> | null;
  is_active: boolean;
};

export type ToolResultCompressorDraft = {
  strategy: string;
  config: Record<string, unknown>;
  is_active: boolean;
};

export type ToolResultCompressionLog = {
  id: string;
  tool_name: string;
  strategy: string;
  original_tokens: number;
  compressed_tokens: number;
  compression_ratio: number;
  created_at: string | null;
};

export type CompressorStatusFilter = "all" | "on" | "off";

export const REDUCTION_MEANING =
  "Reduction is the share of tokens removed before a tool result reached the model. 0 % means nothing was removed: the result was passed through at full size.";

const STRATEGY_LABELS: Record<string, string> = {
  bitbucket_pull_request_summary: "Pull request summary",
  bitbucket_recent_commit_summary: "Recent commit summary",
  confluence_page_summary: "Page summary",
  confluence_page_update_summary: "Page update summary",
  confluence_search_summary: "Search result summary",
  document_ingest_summary: "Document ingest summary",
  grafana_firing_only: "Firing alerts only",
  jira_extract_fields: "Ticket field summary",
  k8s_pod_failures: "Pod failure summary",
  knowledge_entry_summary: "Knowledge entry summary",
  knowledge_key_summary: "Knowledge key summary",
  loki_tail_errors: "Tail errors",
  office_document_view_summary: "Document view summary",
  office_element_summary: "Office element summary",
  office_html_summary: "HTML summary",
  office_query_summary: "Office query summary",
  subthread_context_summary: "Subthread context summary",
  workspace_git_commit_summary: "Workspace commit summary",
};

function titleize(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function strategyLabel(strategy: string): string {
  return STRATEGY_LABELS[strategy] || titleize(strategy);
}

export function configLabel(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

export function coerceConfigValue(currentValue: unknown, nextValue: string): unknown {
  if (typeof currentValue === "number") {
    return Number.isFinite(Number(nextValue)) ? Number(nextValue) : currentValue;
  }
  return nextValue;
}

export function averageReduction(logs: ReadonlyArray<ToolResultCompressionLog>): number | null {
  if (logs.length === 0) return null;
  const sum = logs.reduce((total, item) => total + Number(item.compression_ratio || 0), 0);
  return Math.round(sum / logs.length);
}

/** The draft shown for a compressor: the unsaved edit, else the stored row. */
export function compressorDraft(
  item: ToolResultCompressor,
  drafts: Record<string, ToolResultCompressorDraft | undefined>,
): ToolResultCompressorDraft {
  return (
    drafts[item.tool_name] || {
      strategy: item.strategy,
      config: item.config || {},
      is_active: item.is_active,
    }
  );
}

function matchesQuery(query: string, ...values: string[]): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return values.some((value) => value.toLowerCase().includes(needle));
}

/** Compressors matching the search (tool, profile key or label) and the on/off filter. */
export function filterCompressors(
  items: ReadonlyArray<ToolResultCompressor>,
  drafts: Record<string, ToolResultCompressorDraft | undefined>,
  query: string,
  status: CompressorStatusFilter,
): ToolResultCompressor[] {
  return items.filter((item) => {
    const draft = compressorDraft(item, drafts);
    if (status === "on" && !draft.is_active) return false;
    if (status === "off" && draft.is_active) return false;
    return matchesQuery(query, item.tool_name, draft.strategy, strategyLabel(draft.strategy));
  });
}

/** Log entries matching the same search. */
export function filterCompressionLogs(
  logs: ReadonlyArray<ToolResultCompressionLog>,
  query: string,
): ToolResultCompressionLog[] {
  return logs.filter((log) =>
    matchesQuery(query, log.tool_name, log.strategy, strategyLabel(log.strategy)),
  );
}
