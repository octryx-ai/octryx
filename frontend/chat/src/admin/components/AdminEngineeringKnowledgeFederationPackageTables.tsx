// The packages and sync runs tables of the engineering knowledge federation panel.
import type { ReactNode } from "react";
import {
  formatDate,
  shortChecksum,
  statusBadgeClass,
  type FederationPackage,
  type FederationSyncRun,
} from "./engineeringKnowledgeFederationModel";

type PackagesProps = {
  packages: FederationPackage[];
  renderReviewActions: (item: FederationPackage) => ReactNode;
};

export function AdminEngineeringKnowledgeFederationPackagesTable({ packages, renderReviewActions }: PackagesProps) {
  return (
    <div className="admin-panel__table-wrap">
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>Package</th>
            <th>Direction</th>
            <th>Trust</th>
            <th>Status</th>
            <th>Conflicts</th>
            <th>Actions</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {packages.map((item) => (
            <tr key={item.id}>
              <td>
                <strong>{item.package_id}</strong>
                <div className="admin-panel__hint">
                  {item.publisher_instance_id} · v{item.version} · {shortChecksum(item.package_checksum)}
                </div>
              </td>
              <td>{item.direction}</td>
              <td>
                {item.trust_level} · {item.classification}
              </td>
              <td>
                <span className={statusBadgeClass(item.status)}>{item.status}</span>
                <div className="admin-panel__hint">review: {item.review_status}</div>
              </td>
              <td>
                {item.conflicts.length}
                {item.retraction_refs.length ? (
                  <div className="admin-panel__hint">retractions: {item.retraction_refs.length}</div>
                ) : null}
              </td>
              <td>{renderReviewActions(item)}</td>
              <td>{formatDate(item.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {packages.length === 0 ? (
        <div className="admin-panel__empty-state">No published or imported packages yet.</div>
      ) : null}
    </div>
  );
}

export function AdminEngineeringKnowledgeFederationSyncRunsTable({ syncRuns }: { syncRuns: FederationSyncRun[] }) {
  return (
    <div className="admin-panel__table-wrap">
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>Feed</th>
            <th>Operation</th>
            <th>Status</th>
            <th>Package</th>
            <th>Errors</th>
            <th>Completed</th>
          </tr>
        </thead>
        <tbody>
          {syncRuns.map((run) => (
            <tr key={run.id}>
              <td>{run.feed_name || "-"}</td>
              <td>{run.operation}</td>
              <td>
                <span className={statusBadgeClass(run.status)}>{run.status}</span>
              </td>
              <td>{run.package_id || "-"}</td>
              <td>{run.errors.map((err) => err.message || err.code).filter(Boolean).join("; ") || "-"}</td>
              <td>{formatDate(run.completed_at || run.started_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {syncRuns.length === 0 ? <div className="admin-panel__empty-state">No sync runs recorded.</div> : null}
    </div>
  );
}
