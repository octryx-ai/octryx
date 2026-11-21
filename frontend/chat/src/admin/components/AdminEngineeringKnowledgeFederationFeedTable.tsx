import { formatDateTime } from "../utils/dateTime";
export type FederationFeed = {
  id: string;
  name: string;
  publisher_instance_id: string;
  endpoint_url?: string | null;
  sync_mode: string;
  status: string;
  signing_key_ref?: string | null;
  verification_key_ref?: string | null;
  last_sync_at?: string | null;
  last_sync_status?: string | null;
  last_error?: string | null;
};

function statusBadgeClass(status: string) {
  const normalized = status.toLowerCase();
  if (["active", "success", "published", "ready"].includes(normalized)) {
    return "admin-panel__badge admin-panel__badge--active";
  }
  if (["failed", "blocked", "retracted", "disabled"].includes(normalized)) {
    return "admin-panel__badge admin-panel__badge--danger";
  }
  if (["pending_review", "paused", "retraction_received"].includes(normalized)) {
    return "admin-panel__badge admin-panel__badge--warning";
  }
  return "admin-panel__badge";
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  return formatDateTime(value);
}

export function AdminEngineeringKnowledgeFederationFeedTable({
  feeds,
  saving,
  onDisableFeed,
}: {
  feeds: FederationFeed[];
  saving: boolean;
  onDisableFeed: (feedId: string) => void;
}) {
  return (
    <div className="admin-panel__table-wrap">
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Publisher</th>
            <th>Mode</th>
            <th>Status</th>
            <th>Keys</th>
            <th>Last sync</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {feeds.map((feed) => (
            <tr key={feed.id}>
              <td>
                <strong>{feed.name}</strong>
                <div className="admin-panel__hint">{feed.endpoint_url || "manual feed"}</div>
              </td>
              <td>{feed.publisher_instance_id}</td>
              <td>{feed.sync_mode}</td>
              <td>
                <span className={statusBadgeClass(feed.last_sync_status || feed.status)}>
                  {feed.last_sync_status || feed.status}
                </span>
                {feed.last_error ? <div className="admin-panel__hint">{feed.last_error}</div> : null}
              </td>
              <td>
                <div className="admin-panel__hint">sign: {feed.signing_key_ref || "-"}</div>
                <div className="admin-panel__hint">verify: {feed.verification_key_ref || "-"}</div>
              </td>
              <td>{formatDate(feed.last_sync_at)}</td>
              <td>
                {feed.status === "disabled" ? (
                  <span className="admin-panel__hint">disabled</span>
                ) : (
                  <button
                    type="button"
                    className="admin-panel__action-btn admin-panel__action-btn--danger"
                    onClick={() => onDisableFeed(feed.id)}
                    disabled={saving}
                  >
                    Disable feed
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {feeds.length === 0 ? <div className="admin-panel__empty-state">No federation feeds registered.</div> : null}
    </div>
  );
}
