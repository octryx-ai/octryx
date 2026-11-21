// Engineering knowledge packs: evidence lists, the source evidence table and the review of a retrievable item.
import type { EngineeringKnowledgeItem, EngineeringKnowledgeSource } from "../types/engineeringKnowledgeTypes";

function EvidenceList({ value }: { value: unknown }) {
  if (!Array.isArray(value) || value.length === 0) {
    return <span style={{ color: "var(--status-error)" }}>missing</span>;
  }
  return (
    <div style={{ display: "grid", gap: "0.35rem" }}>
      {value.map((item, index) => {
        const evidence = item as {
          source_key?: string;
          title?: string;
          source_uri?: string;
          source_type?: string;
          trust_tier?: string;
          checksum?: string;
          raw_archive_path?: string;
          parsed_archive_path?: string;
          evidence_archive_path?: string;
          fetch_status?: string;
          freshness_status?: string;
        };
        return (
          <div
            key={index}
            style={{
              borderLeft: "2px solid var(--border-soft)",
              paddingLeft: "0.5rem",
            }}
          >
            <div>
              <span style={{ fontFamily: "monospace" }}>
                {evidence.source_key ?? "source"}
              </span>
              {" · "}
              {evidence.trust_tier ?? "unknown"}
              {evidence.source_type ? ` · ${evidence.source_type}` : ""}
              {evidence.fetch_status ? ` · ${evidence.fetch_status}` : ""}
              {evidence.freshness_status
                ? ` · ${evidence.freshness_status}`
                : ""}
            </div>
            {evidence.title && <div>{evidence.title}</div>}
            {evidence.source_uri && (
              <div
                style={{ wordBreak: "break-all", color: "var(--text-muted)" }}
              >
                URI: {evidence.source_uri}
              </div>
            )}
            {(evidence.evidence_archive_path ||
              evidence.raw_archive_path ||
              evidence.parsed_archive_path) && (
              <div
                style={{ wordBreak: "break-all", color: "var(--text-muted)" }}
              >
                Archive:{" "}
                {evidence.evidence_archive_path ??
                  evidence.parsed_archive_path ??
                  evidence.raw_archive_path}
              </div>
            )}
            {evidence.checksum && (
              <div
                style={{ wordBreak: "break-all", color: "var(--text-muted)" }}
              >
                Checksum: {evidence.checksum}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function SourceEvidenceTable({
  sources,
}: {
  sources: EngineeringKnowledgeSource[];
}) {
  if (sources.length === 0) {
    return (
      <div style={{ fontSize: "var(--ds-text-xs)", color: "var(--status-error)" }}>
        No pack-level source evidence is attached to this version.
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: "0.45rem" }}>
      {sources.map((source) => (
        <details
          key={source.id}
          style={{ fontSize: "var(--ds-text-xs)", color: "var(--text-secondary)" }}
        >
          <summary>
            <span style={{ fontFamily: "monospace" }}>{source.source_key}</span>
            {" · "}
            {source.trust_tier} · {source.fetch_status} ·{" "}
            {source.freshness_status}
          </summary>
          <div
            style={{
              marginTop: "0.35rem",
              display: "grid",
              gap: "0.2rem",
              color: "var(--text-muted)",
            }}
          >
            <div>{source.title}</div>
            <div style={{ wordBreak: "break-all" }}>
              URI: {source.source_uri}
            </div>
            <div style={{ wordBreak: "break-all" }}>
              Evidence archive: {source.evidence_archive_path ?? "—"}
            </div>
            <div style={{ wordBreak: "break-all" }}>
              Raw archive: {source.raw_archive_path ?? "—"}
            </div>
            <div style={{ wordBreak: "break-all" }}>
              Parsed archive: {source.parsed_archive_path ?? "—"}
            </div>
            <div style={{ wordBreak: "break-all" }}>
              Checksum: {source.checksum ?? "—"}
            </div>
          </div>
        </details>
      ))}
    </div>
  );
}

export function RetrievableItemReview({ item }: { item: EngineeringKnowledgeItem }) {
  return (
    <details
      style={{
        border: "1px solid var(--border-soft)",
        borderRadius: "var(--ds-radius-md)",
        padding: "0.5rem 0.6rem",
        fontSize: "var(--ds-text-xs)",
        color: "var(--text-secondary)",
      }}
    >
      <summary>
        <strong>{item.title}</strong>
        <span style={{ color: "var(--text-muted)" }}>
          {" "}
          · rank {item.retrieval_rank} ·{" "}
          {item.evidence_status ?? "unknown evidence"}
        </span>
      </summary>
      {item.summary && (
        <div style={{ marginTop: "0.45rem", color: "var(--text-muted)" }}>
          {item.summary}
        </div>
      )}
      <div style={{ marginTop: "0.45rem" }}>
        <p className="user-edit-panel__section-label">Evidence</p>
        <EvidenceList value={item.evidence ?? item.metadata?.evidence} />
      </div>
      <div style={{ marginTop: "0.45rem" }}>
        <p className="user-edit-panel__section-label">Content Preview</p>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            margin: 0,
            color: "var(--text-muted)",
            fontFamily: "inherit",
          }}
        >
          {item.content || item.content_preview || "—"}
        </pre>
      </div>
      {Object.keys(item.metadata || {}).length > 0 && (
        <details style={{ marginTop: "0.45rem" }}>
          <summary>Metadata JSON</summary>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              fontSize: "var(--ds-text-2xs)",
              color: "var(--text-muted)",
            }}
          >
            {JSON.stringify(item.metadata, null, 2)}
          </pre>
        </details>
      )}
    </details>
  );
}
