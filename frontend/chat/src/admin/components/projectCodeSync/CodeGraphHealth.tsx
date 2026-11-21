// Code graph health of one code repository: backend, counts, languages, recent runs, stale files and parse errors.
import type { AdminCodeRepository } from "../../types/projectQualityTypes.code";
import { formatDateTime } from "../../utils/dateTime";

type CodeGraphStatus = NonNullable<AdminCodeRepository["code_graph_status"]>;

export function CodeGraphHealth({ graphStatus }: { graphStatus: CodeGraphStatus }) {
  const graphSummary = graphStatus.summary;
  const graphLanguages = graphSummary?.language_distribution
    ? Object.entries(graphSummary.language_distribution)
    : [];

  return (
    <div className="admin-panel__subsection" style={{ marginTop: 12 }}>
      <div className="admin-panel__section-header">
        <div>
          <h4>Code graph health</h4>
          <p>
            {graphStatus.backend || "no backend"} ·{" "}
            {graphStatus.indexing_mode || "no mode"} ·{" "}
            {graphStatus.latest_run?.started_at
              ? formatDateTime(graphStatus.latest_run.started_at)
              : "not indexed"}
          </p>
        </div>
      </div>
      <GraphBadges graphStatus={graphStatus} />
      {graphLanguages.length ? (
        <div className="admin-inline-actions" style={{ marginTop: 8 }}>
          {graphLanguages.slice(0, 4).map(([language, count]) => (
            <span
              key={language}
              className="task-item__badge task-item__badge--secondary"
            >
              {language}: {count}
            </span>
          ))}
        </div>
      ) : null}
      <GraphRecentLists graphStatus={graphStatus} />
    </div>
  );
}

// The status and the counts of the graph, one badge each.
function GraphBadges({ graphStatus }: { graphStatus: CodeGraphStatus }) {
  const graphSummary = graphStatus.summary;
  return (
    <div className="admin-inline-actions" style={{ flexWrap: "wrap" }}>
      <span className="task-item__badge">
        status: {graphStatus.status}
      </span>
      <span className="task-item__badge task-item__badge--secondary">
        files: {String(graphSummary?.file_count || 0)}
      </span>
      <span className="task-item__badge task-item__badge--secondary">
        nodes: {String(graphSummary?.node_count || 0)}
      </span>
      <span className="task-item__badge task-item__badge--secondary">
        edges: {String(graphSummary?.edge_count || 0)}
      </span>
      <span className="task-item__badge task-item__badge--secondary">
        routes: {String(graphSummary?.route_count || 0)}
      </span>
      <span className="task-item__badge task-item__badge--secondary">
        stale: {String(graphStatus.stale_files.length)}
      </span>
      <span className="task-item__badge task-item__badge--secondary">
        errors: {String(graphStatus.parse_errors.length)}
      </span>
    </div>
  );
}

// The latest runs, stale files and parse errors, three of each.
function GraphRecentLists({ graphStatus }: { graphStatus: CodeGraphStatus }) {
  return (
    <>
      {graphStatus.run_history.length ? (
        <div className="connector-card__meta" style={{ marginTop: 8 }}>
          runs:{" "}
          {graphStatus.run_history
            .slice(0, 3)
            .map(
              (run) =>
                `${run.status}${run.duration_ms !== null ? ` ${run.duration_ms}ms` : ""}`,
            )
            .join(" · ")}
        </div>
      ) : null}
      {graphStatus.stale_files.length ? (
        <div className="connector-card__meta" style={{ marginTop: 8 }}>
          stale files:{" "}
          {graphStatus.stale_files
            .slice(0, 3)
            .map((file) => `${file.file_path} (${file.status})`)
            .join(" · ")}
        </div>
      ) : null}
      {graphStatus.parse_errors.length ? (
        <div className="connector-card__meta" style={{ marginTop: 8 }}>
          parse errors:{" "}
          {graphStatus.parse_errors
            .slice(0, 3)
            .map((error) => `${error.file_path}: ${error.parse_error}`)
            .join(" · ")}
        </div>
      ) : null}
    </>
  );
}
