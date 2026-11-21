import { Icon } from "@iconify/react";
import { codeRepoBackendBadgeClass } from "../../utils/formatters";
import type { AdminCodeRepository } from "../../types/projectQualityTypes.code";
import { formatDateTime } from "../../utils/dateTime";
import { CodeGraphHealth } from "./CodeGraphHealth";

type CodeRepositoryCardProps = {
  repo: AdminCodeRepository;
  projectCodeRepositoryRunningId: string | null;
  projectCodeRepositoryLoading: boolean;
  handleEditProjectCodeRepository: (repo: AdminCodeRepository) => void;
  handleRunProjectCodeIndex: (repoId: string) => Promise<void>;
  handleDeleteProjectCodeRepository: (repoId: string) => Promise<void>;
};

// Name, provider and index badges, the root and the configured and effective backends.
function RepositoryInfo({ repo }: { repo: AdminCodeRepository }) {
  const effectiveBackends = repo.effective_backends || {};
  const graphStatus = repo.code_graph_status;
  return (
    <div className="connector-card__info">
      <div className="connector-card__name-row">
        <div className="connector-card__name">{repo.name}</div>
        <span className="connector-card__meta-badge">{repo.provider}</span>
        <span className="connector-card__meta-badge">
          {repo.last_index_status || "not indexed"}
        </span>
        {graphStatus ? (
          <span
            className={`connector-card__meta-badge ${graphStatus.status === "ready" ? "connector-card__meta-badge--ok" : ""}`}
          >
            graph {graphStatus.status}
          </span>
        ) : null}
      </div>
      <div
        className={`connector-card__status ${repo.last_index_status === "ready" ? "connector-card__status--ok" : ""}`}
      >
        {repo.repo_root}
      </div>
      <div className="connector-card__meta">
        configured: search {repo.index_backend} · semantic{" "}
        {repo.semantic_backend} · structure {repo.structure_backend} · graph{" "}
        {repo.graph_backend}
      </div>
      <div className="connector-card__meta">
        effective: search {effectiveBackends.index || repo.index_backend} ·
        semantic {effectiveBackends.semantic || repo.semantic_backend} ·
        structure {effectiveBackends.structure || repo.structure_backend} ·
        graph {effectiveBackends.graph || repo.graph_backend}
      </div>
      <div className="connector-card__meta">
        last index:{" "}
        {repo.last_indexed_at
          ? formatDateTime(repo.last_indexed_at)
          : "never"}
        {repo.last_index_error ? ` · ${repo.last_index_error}` : ""}
      </div>
    </div>
  );
}

// Edit, rebuild the index and delete.
function RepositoryActions({
  repo,
  projectCodeRepositoryRunningId,
  projectCodeRepositoryLoading,
  handleEditProjectCodeRepository,
  handleRunProjectCodeIndex,
  handleDeleteProjectCodeRepository,
}: CodeRepositoryCardProps) {
  return (
    <div className="connector-card__header-right">
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={() => handleEditProjectCodeRepository(repo)}
      >
        Edit
      </button>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={() => void handleRunProjectCodeIndex(repo.id)}
        disabled={projectCodeRepositoryRunningId === repo.id}
      >
        {projectCodeRepositoryRunningId === repo.id
          ? "Indexing…"
          : "Rebuild Index"}
      </button>
      <button
        type="button"
        className="admin-panel__danger-btn"
        onClick={() => void handleDeleteProjectCodeRepository(repo.id)}
        disabled={projectCodeRepositoryLoading}
      >
        Delete
      </button>
    </div>
  );
}

type BackendStatus = NonNullable<AdminCodeRepository["backend_status"]>;

const BACKEND_LABELS = [
  ["index", "Search"],
  ["semantic", "Semantic"],
  ["structure", "Structure"],
  ["graph", "Graph"],
];

// One line with every backend's state, configured and effective value, artifact and detail.
function backendSummaryText(backendStatus: BackendStatus): string {
  return BACKEND_LABELS
    .map(([key, label]) => {
      const entry = backendStatus[key];
      if (!entry) return null;
      const state = entry.ready
        ? "ready"
        : entry.available
          ? "degraded"
          : "unavailable";
      const configured = entry.configured || "auto";
      const artifact = entry.artifact_status
        ? ` · artifact ${entry.artifact_status}`
        : "";
      return `${label}: ${state}, configured ${configured}, effective ${entry.effective}${artifact}${entry.detail ? ` · ${entry.detail}` : ""}`;
    })
    .filter(Boolean)
    .join(" | ");
}

// Files, symbols and the three largest languages of the latest index.
function IndexCounts({ latestSummary }: { latestSummary: NonNullable<AdminCodeRepository["latest_index_summary"]> }) {
  const languages =
    latestSummary.languages && typeof latestSummary.languages === "object"
      ? Object.entries(latestSummary.languages as Record<string, number>)
      : [];
  return (
    <div className="admin-inline-actions">
      <span className="task-item__badge">
        files: {String(latestSummary.file_count || 0)}
      </span>
      <span className="task-item__badge task-item__badge--secondary">
        symbols: {String(latestSummary.symbol_count || 0)}
      </span>
      {languages.slice(0, 3).map(([language, count]) => (
        <span
          key={language}
          className="task-item__badge task-item__badge--secondary"
        >
          {language}: {count}
        </span>
      ))}
    </div>
  );
}

// A locally indexed repository: counts, languages, per-backend badges and their states, and the graph health.
function LocalIndexDetails({ repo }: { repo: AdminCodeRepository }) {
  const latestSummary = repo.latest_index_summary || {};
  const backendStatus = repo.backend_status || {};
  const graphStatus = repo.code_graph_status;
  return (
    <div className="task-item__runs" style={{ paddingTop: 0 }}>
      <IndexCounts latestSummary={latestSummary} />
      <div
        className="admin-inline-actions"
        style={{ marginTop: 10, flexWrap: "wrap", alignItems: "stretch" }}
      >
        {BACKEND_LABELS.map(([key, label]) => {
          const entry = backendStatus[key];
          if (!entry) return null;
          return (
            <span
              key={key}
              className={`connector-card__meta-badge ${codeRepoBackendBadgeClass(Boolean(entry.ready), entry.mode)}`}
              title={entry.detail || ""}
            >
              {label}: {entry.effective}
              {entry.mode === "fallback" ? " (fallback)" : ""}
              {entry.mode === "disabled" ? " (off)" : ""}
            </span>
          );
        })}
      </div>
      <div className="connector-card__meta" style={{ marginTop: 8 }}>
        {backendSummaryText(backendStatus)}
      </div>
      {graphStatus ? <CodeGraphHealth graphStatus={graphStatus} /> : null}
    </div>
  );
}

export function CodeRepositoryCard(props: CodeRepositoryCardProps) {
  const { repo } = props;

  return (
    <div className="connector-card connector-card--configured">
      <div className="connector-card__header">
        <div className="connector-card__icon" style={{ background: "#1d4ed8" }}>
          <Icon icon="lucide:binary" width="18" height="18" />
        </div>
        <RepositoryInfo repo={repo} />
        <RepositoryActions {...props} />
      </div>
      <LocalIndexDetails repo={repo} />
    </div>
  );
}
