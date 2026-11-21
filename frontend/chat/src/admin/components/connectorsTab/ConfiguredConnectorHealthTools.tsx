import { DataTable } from "../../../layout/DataTable";
import { FormSection } from "../../../layout/FormSection";
import { StatusLabel } from "../../../layout/StatusLabel";
import { formatExactTime } from "../../utils/dateTime";

type ConfiguredConnectorHealthToolsProps = {
  connector: any;
  healthHistory: any[];
  ctx: Record<string, unknown>;
};

type HealthEntry = { id: string; status: string; checked_at: string; response_time_ms?: number | null; error?: string | null; details?: string | null };

// The last health checks of a configured connector: one compact table (result, response time,
// what the check said, when) instead of a stack of cards; the exact time is the tooltip.
export function ConfiguredConnectorHealthTools({
  connector,
  healthHistory,
  ctx,
}: ConfiguredConnectorHealthToolsProps) {
  const {
    connectorHealthLoading,
    formatConnectorHealthStatus,
    formatRelativeTime,
  } = ctx as Record<string, any>;

  if (!connector.configured) return null;
  return (
    <FormSection title="Health checks" testId="connector-health-checks">
      <DataTable<HealthEntry>
        label="Health checks"
        testId="connector-health-table"
        loading={connectorHealthLoading === connector.tool_name}
        loadingLabel="Loading health checks…"
        rows={healthHistory.slice(0, 5)}
        rowKey={(entry) => String(entry.id)}
        empty={{ text: "No health checks recorded yet." }}
        columns={[
          { key: "result", header: "Result", nowrap: true, render: (entry) => {
            const label = formatConnectorHealthStatus(entry.status);
            return <StatusLabel label={label} tone={String(entry.status).toLowerCase() === "error" ? "problem" : "neutral"} />;
          } },
          { key: "time", header: "Response", nowrap: true, align: "end", render: (entry) => (entry.response_time_ms != null ? `${entry.response_time_ms} ms` : "—") },
          { key: "said", header: "Message", grow: true, clip: "28rem", render: (entry) => {
            const said = [entry.error, entry.details].filter(Boolean).join(" · ");
            return <span title={said || undefined}>{said || "—"}</span>;
          } },
          { key: "when", header: "Checked", nowrap: true, render: (entry) => (
            <span title={formatExactTime(entry.checked_at)}>{formatRelativeTime(entry.checked_at)}</span>
          ) },
        ]}
      />
    </FormSection>
  );
}
