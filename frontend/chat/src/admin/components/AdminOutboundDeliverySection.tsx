import { DataTable } from "../../layout/DataTable";
import { EmptyLine } from "../../layout/EmptyLine";
import { StatusLabel } from "../../layout/StatusLabel";
import { statusWords } from "./AdminOutboundWebhookTable";
import type { AdminOutboundWebhookDeliveryRow } from "./webhookTypes";

type AdminOutboundDeliverySectionProps = {
  totalCount: number;
  visible: boolean;
  setVisible: (value: boolean) => void;
  search: string;
  setSearch: (value: string) => void;
  deliveries: AdminOutboundWebhookDeliveryRow[];
  filteredDeliveries: AdminOutboundWebhookDeliveryRow[];
  formatDateTime: (value: string | null | undefined) => string;
};

// The delivery log as a compact table under its own header (Show/Hide and search stay).
export function AdminOutboundDeliverySection({
  totalCount,
  visible,
  setVisible,
  search,
  setSearch,
  deliveries,
  filteredDeliveries,
  formatDateTime,
}: AdminOutboundDeliverySectionProps) {
  return (
    <>
      <div className="admin-panel__section-header" style={{ marginTop: "1.5rem" }}>
        <span>Outbound deliveries ({totalCount})</span>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => setVisible(!visible)}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
      {!visible ? null : deliveries.length === 0 ? (
        <EmptyLine text="No outbound deliveries yet." testId="outbound-deliveries-empty" />
      ) : (
        <div>
          <div className="admin-panel__toolbar" style={{ marginBottom: "0.75rem" }}>
            <input
              className="admin-panel__search"
              type="search"
              aria-label="Search deliveries"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search deliveries…"
            />
          </div>
          <DataTable<AdminOutboundWebhookDeliveryRow>
            label="Outbound deliveries"
            testId="outbound-deliveries-table"
            rows={filteredDeliveries}
            rowKey={(delivery) => delivery.id}
            empty={{ text: "No deliveries match this search." }}
            columns={[
              { key: "event", header: "Event", nowrap: true, render: (delivery) => delivery.event_type },
              {
                key: "webhook",
                header: "Webhook",
                nowrap: true,
                render: (delivery) => delivery.webhook_name || "Removed webhook",
              },
              {
                key: "status",
                header: "Status",
                nowrap: true,
                render: (delivery) => (
                  <StatusLabel label={statusWords(delivery.status) || "Unknown"} title={delivery.error || undefined} />
                ),
              },
              { key: "http", header: "HTTP", nowrap: true, align: "end", render: (delivery) => delivery.http_status ?? "—" },
              {
                key: "error",
                header: "Error",
                grow: true,
                render: (delivery) =>
                  delivery.error ? (
                    <span className="admin-channels__target-cell" title={delivery.error}>{delivery.error}</span>
                  ) : (
                    ""
                  ),
              },
              { key: "request", header: "Request", nowrap: true, render: (delivery) => delivery.request_id || "—" },
              {
                key: "created",
                header: "Created",
                nowrap: true,
                render: (delivery) => (delivery.created_at ? formatDateTime(delivery.created_at) : "—"),
              },
            ]}
          />
        </div>
      )}
    </>
  );
}
