import { formatDateTime } from "../utils/dateTime";
type FederationUsageEvent = {
  id: string;
  run_id?: string | null;
  session_id?: string | null;
  package_id?: string | null;
  package_record_id?: string | null;
  fact_ids: string[];
  created_at?: string | null;
};

export type FederationOperations = {
  failed_import_count: number;
  signature_failure_count: number;
  policy_blocked_count: number;
  usage_events: FederationUsageEvent[];
};

function formatDate(value?: string | null) {
  if (!value) return "-";
  return formatDateTime(value);
}

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="admin-panel__empty-state">
      <span className="admin-panel__eyebrow">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function AdminEngineeringKnowledgeFederationOperationsPanel({
  operations,
}: {
  operations?: FederationOperations;
}) {
  if (!operations) return null;
  return (
    <section className="admin-panel__form" style={{ marginTop: "0.9rem" }}>
      <div className="admin-panel__section-header">
        <div>
          <span className="admin-panel__section-title">Operations and usage</span>
          <div className="admin-panel__hint">Failed imports, policy blocks, signature failures, and run impact.</div>
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: "0.65rem",
        }}
      >
        <StatTile label="Failed imports" value={operations.failed_import_count} />
        <StatTile label="Signature failures" value={operations.signature_failure_count} />
        <StatTile label="Policy blocked" value={operations.policy_blocked_count} />
        <StatTile label="Usage events" value={operations.usage_events.length} />
      </div>
      <div className="admin-panel__table-wrap" style={{ marginTop: "0.75rem" }}>
        <table className="admin-panel__table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Package</th>
              <th>Facts</th>
              <th>Observed</th>
            </tr>
          </thead>
          <tbody>
            {operations.usage_events.map((event) => (
              <tr key={event.id}>
                <td>
                  <strong>{event.run_id || "-"}</strong>
                  <div className="admin-panel__hint">{event.session_id || "no session"}</div>
                </td>
                <td>
                  {event.package_id || "-"}
                  <div className="admin-panel__hint">{event.package_record_id || "-"}</div>
                </td>
                <td>{event.fact_ids.length}</td>
                <td>{formatDate(event.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {operations.usage_events.length === 0 ? (
          <div className="admin-panel__empty-state">No federated knowledge usage recorded yet.</div>
        ) : null}
      </div>
    </section>
  );
}
