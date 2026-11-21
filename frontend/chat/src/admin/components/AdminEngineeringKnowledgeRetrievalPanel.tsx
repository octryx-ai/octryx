import { useState } from "react";

import type {
  EngineeringKnowledgePackVersion,
  EngineeringKnowledgeRetrievalSearchPayload,
} from "../types/engineeringKnowledgeTypes";

type Props = {
  version: EngineeringKnowledgePackVersion;
  loading: boolean;
  result?: EngineeringKnowledgeRetrievalSearchPayload;
  onSearch: (
    versionId: string,
    query: string,
    recordKind: string,
  ) => Promise<EngineeringKnowledgeRetrievalSearchPayload>;
};

function retrievalIndexReport(version: EngineeringKnowledgePackVersion) {
  const report = version.quality_report || {};
  const index = report.retrieval_index;
  return index && typeof index === "object"
    ? (index as {
        active?: boolean;
        indexed_record_count?: number;
        record_kind_counts?: Record<string, number>;
        status?: string;
      })
    : null;
}

type IndexReport = ReturnType<typeof retrievalIndexReport>;

function RetrievalIndexFacts({ index }: { index: IndexReport }) {
  const kindCounts = index?.record_kind_counts || {};
  return (
    <div
      style={{
        display: "flex",
        gap: "0.45rem",
        flexWrap: "wrap",
        alignItems: "center",
        fontSize: "var(--ds-text-xs)",
        color: "var(--text-muted)",
      }}
    >
      <span>
        Status: {index?.active ? "active" : index?.status || "not indexed"}
      </span>
      <span>Records: {index?.indexed_record_count ?? 0}</span>
      {Object.entries(kindCounts).map(([kind, count]) => (
        <span key={kind} className="admin-panel__badge">
          {kind} {count}
        </span>
      ))}
    </div>
  );
}

type SearchBarProps = Pick<Props, "version" | "loading" | "onSearch"> & {
  index: IndexReport;
  query: string;
  setQuery: (query: string) => void;
  recordKind: string;
  setRecordKind: (recordKind: string) => void;
};

function RetrievalSearchBar({ version, loading, onSearch, index, query, setQuery, recordKind, setRecordKind }: SearchBarProps) {
  return (
    <div style={{ display: "flex", gap: "0.45rem", marginTop: "0.45rem" }}>
      <input
        className="connector-field__input"
        style={{ flex: 1, fontSize: "var(--ds-text-xs)" }}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            void onSearch(version.id, query, recordKind);
          }
        }}
      />
      <select
        className="connector-field__input"
        style={{ maxWidth: "120px", fontSize: "var(--ds-text-xs)" }}
        value={recordKind}
        onChange={(event) => setRecordKind(event.target.value)}
      >
        <option value="all">All</option>
        <option value="fact">Facts</option>
        <option value="item">Items</option>
        <option value="source">Sources</option>
        <option value="pack">Pack</option>
      </select>
      <button
        type="button"
        className="admin-panel__action-btn"
        style={{ fontSize: "var(--ds-text-xs)" }}
        disabled={loading || !index?.active}
        onClick={() => void onSearch(version.id, query, recordKind)}
      >
        {loading ? "Searching..." : "Search"}
      </button>
    </div>
  );
}

function RetrievalRecords({ result }: { result: EngineeringKnowledgeRetrievalSearchPayload }) {
  return (
    <div style={{ display: "grid", gap: "0.45rem", marginTop: "0.55rem" }}>
      {result.records.length === 0 ? (
        <div style={{ fontSize: "var(--ds-text-xs)", color: "var(--text-muted)" }}>
          No indexed records matched this query.
        </div>
      ) : (
        result.records.map((record) => (
          <details
            key={record.record_id}
            style={{
              border: "1px solid var(--border-soft)",
              borderRadius: "var(--ds-radius-md)",
              padding: "0.5rem 0.6rem",
              fontSize: "var(--ds-text-xs)",
              color: "var(--text-secondary)",
            }}
          >
            <summary>
              <strong>{record.title}</strong>
              <span style={{ color: "var(--text-muted)" }}>
                {" "}
                · {record.record_kind}
                {record.fact_id ? ` · ${record.fact_id}` : ""}
              </span>
            </summary>
            <div
              style={{ marginTop: "0.4rem", color: "var(--text-muted)" }}
            >
              {record.summary || record.content || "No preview available."}
            </div>
            <div
              style={{
                marginTop: "0.35rem",
                wordBreak: "break-all",
                color: "var(--text-muted)",
              }}
            >
              Source: {record.source_key || "none"} · URI:{" "}
              {record.canonical_uri || record.source_uri || "none"} ·
              Archive: {record.archive_path || "none"}
            </div>
          </details>
        ))
      )}
    </div>
  );
}

export function AdminEngineeringKnowledgeRetrievalPanel({
  version,
  loading,
  result,
  onSearch,
}: Props) {
  const [query, setQuery] = useState("migration");
  const [recordKind, setRecordKind] = useState("fact");
  const index = retrievalIndexReport(version);

  return (
    <div style={{ marginTop: "0.55rem" }}>
      <p className="user-edit-panel__section-label">Retrieval Index</p>
      <RetrievalIndexFacts index={index} />
      <RetrievalSearchBar version={version} loading={loading} onSearch={onSearch} index={index} query={query} setQuery={setQuery}
        recordKind={recordKind} setRecordKind={setRecordKind} />
      {result && <RetrievalRecords result={result} />}
    </div>
  );
}
