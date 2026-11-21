import { useState } from "react";
import { RuntimeCompressionToolRow } from "./RuntimeCompressionToolRow";
import {
  REDUCTION_MEANING,
  averageReduction,
  compressorDraft,
  filterCompressionLogs,
  filterCompressors,
  strategyLabel,
  type CompressorStatusFilter,
  type ToolResultCompressionLog,
  type ToolResultCompressor,
  type ToolResultCompressorDraft,
} from "./compressionModel";
import type { RuntimeTabCtx } from "./types";
import "./runtimeSections.css";

type RuntimeCompressionSectionProps = {
  ctx: RuntimeTabCtx;
};

const STATUS_FILTERS: Array<{ value: CompressorStatusFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
];


// Search and status filter over the tools and the log; Reset appears once a filter is set.
function CompressionFilterBar({ query, setQuery, status, setStatus }: {
  query: string;
  setQuery: (value: string) => void;
  status: CompressorStatusFilter;
  setStatus: (value: CompressorStatusFilter) => void;
}) {
  return (
    <div className="runtime-filter-bar">
      <label className="thread-search thread-search--inline runtime-filter-bar__search">
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="9" cy="9" r="5.5" />
          <path d="M13.2 13.2 17 17" />
        </svg>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search tools or profiles"
          aria-label="Search tools or profiles"
        />
      </label>
      {/* A filter in the toolbar, not a third tab row under Platform › Advanced (two levels). */}
      <select className="admin-users__toolbar-select" aria-label="Compression status" value={status}
        onChange={(event) => setStatus(event.target.value as CompressorStatusFilter)}>
        {STATUS_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>Status · {filter.label}</option>)}
      </select>
      {query || status !== "all" ? (
        <button
          type="button"
          className="admin-panel__action-btn runtime-filter-bar__reset"
          onClick={() => {
            setQuery("");
            setStatus("all");
          }}
        >
          Reset
        </button>
      ) : null}
    </div>
  );
}

// One row per tool with its profile, limits and switch.
function CompressorTable({ visible, drafts, saving, setDraft, onSave }: {
  visible: ToolResultCompressor[];
  drafts: Record<string, ToolResultCompressorDraft>;
  saving: unknown;
  setDraft: (toolName: string, draft: ToolResultCompressorDraft) => void;
  onSave: (toolName: string) => void;
}) {
  return (
    <div className="providers-table-wrapper">
      <table className="admin-panel__table runtime-compression__table">
        <thead>
          <tr>
            <th>Tool</th>
            <th>Profile</th>
            <th>Limits</th>
            <th>Compression</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 ? (
            <tr>
              <td colSpan={5} className="admin-panel__cell--muted">
                No tools match this filter.
              </td>
            </tr>
          ) : (
            visible.map((item) => (
              <RuntimeCompressionToolRow
                key={item.id}
                item={item}
                draft={compressorDraft(item, drafts)}
                saving={saving === item.tool_name}
                onDraftChange={(draft) => setDraft(item.tool_name, draft)}
                onSave={() => onSave(item.tool_name)}
              />
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

// The recent compression log, filtered by the same search.
function CompressionLogTable({ logs, visibleLogs, formatRelativeTime }: {
  logs: ToolResultCompressionLog[];
  visibleLogs: ToolResultCompressionLog[];
  formatRelativeTime: (value: string | null) => string;
}) {
  return (
    <div className="providers-table-wrapper">
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>Tool</th>
            <th>Profile</th>
            <th>Original tokens</th>
            <th>Sent tokens</th>
            <th>Reduction</th>
            <th>When</th>
          </tr>
        </thead>
        <tbody>
          {visibleLogs.length === 0 ? (
            <tr>
              <td colSpan={6} className="admin-panel__cell--muted">
                {logs.length === 0 ? "No compression log entries yet." : "No log entries match this search."}
              </td>
            </tr>
          ) : (
            visibleLogs.map((item) => (
              <tr key={item.id}>
                <td>{item.tool_name}</td>
                <td>{strategyLabel(item.strategy)}</td>
                <td>{item.original_tokens}</td>
                <td>{item.compressed_tokens}</td>
                <td>{item.compression_ratio} %</td>
                <td>{formatRelativeTime(item.created_at)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function RuntimeCompressionSection({ ctx }: RuntimeCompressionSectionProps) {
  const {
    formatRelativeTime,
    handleSaveToolResultCompressor,
    setToolResultCompressorDrafts,
    toolResultCompressionLogs,
    toolResultCompressionSaving,
    toolResultCompressorDrafts,
    toolResultCompressors,
  } = ctx;
  const compressors: ToolResultCompressor[] = toolResultCompressors || [];
  const logs: ToolResultCompressionLog[] = toolResultCompressionLogs || [];
  const drafts: Record<string, ToolResultCompressorDraft> = toolResultCompressorDrafts || {};
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<CompressorStatusFilter>("all");

  const activeCount = compressors.filter((item) => compressorDraft(item, drafts).is_active).length;
  const reduction = averageReduction(logs);
  const visible = filterCompressors(compressors, drafts, query, status);
  const visibleLogs = filterCompressionLogs(logs, query);
  const setDraft = (toolName: string, draft: ToolResultCompressorDraft) =>
    setToolResultCompressorDrafts((prev: Record<string, ToolResultCompressorDraft>) => ({
      ...prev,
      [toolName]: draft,
    }));

  return (
    <div className="admin-panel__subsection runtime-panel__card">
      <div className="admin-panel__section-header runtime-compression__header">
        <span>Tool output compression</span>
        <div className="runtime-compression__summary">
          <span>{activeCount} on</span>
          <span>{compressors.length} tools</span>
          <span title={REDUCTION_MEANING}>{reduction == null ? "No recent runs" : `${reduction} % average reduction`}</span>
        </div>
      </div>

      <CompressionFilterBar query={query} setQuery={setQuery} status={status} setStatus={setStatus} />

      <CompressorTable visible={visible} drafts={drafts} saving={toolResultCompressionSaving} setDraft={setDraft}
        onSave={(toolName) => void handleSaveToolResultCompressor(toolName)} />

      <div className="admin-panel__section-header runtime-compression__log-header">
        <span>Recent compression log</span>
      </div>
      <CompressionLogTable logs={logs} visibleLogs={visibleLogs} formatRelativeTime={formatRelativeTime} />
    </div>
  );
}
