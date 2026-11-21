import { DataTable } from "../../layout/DataTable";
import { StatusLabel } from "../../layout/StatusLabel";
import type { AdminOutboundWebhookRow, ProjectOptionRow } from "./webhookTypes";
import { ActionMenu } from "./workflowSurfaces/ActionMenu";

type AdminOutboundWebhookTableProps = {
  outboundWebhooks: AdminOutboundWebhookRow[];
  projects: ProjectOptionRow[];
  onEdit: (webhook: AdminOutboundWebhookRow) => void;
  onToggleActive: (webhook: AdminOutboundWebhookRow) => Promise<void>;
  // Asks for the in-app confirmation (AdminOutboundWebhooksSection); the row only offers it in its ⋯ menu.
  onDelete: (webhook: AdminOutboundWebhookRow) => void;
  // The webhook whose side panel (edit drawer) is open.
  selectedKey?: string | null;
};

/** A status code in words ("dead_letter" → "Dead letter"); an empty one reads as nothing. */
export function statusWords(status: string | null | undefined): string {
  const words = String(status ?? "").replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "";
}

// The outbound webhooks as one compact table; a row opens its side panel (edit), the ⋯ menu holds
// Enable/Disable and Delete.
export function AdminOutboundWebhookTable({
  outboundWebhooks,
  projects,
  onEdit,
  onToggleActive,
  onDelete,
  selectedKey = null,
}: AdminOutboundWebhookTableProps) {
  return (
    <DataTable<AdminOutboundWebhookRow>
      label="Outbound webhooks"
      testId="outbound-webhooks-table"
      rows={outboundWebhooks}
      rowKey={(hook) => hook.id}
      onOpen={onEdit}
      selectedKey={selectedKey}
      empty={{ text: "No outbound webhooks configured yet." }}
      columns={[
        { key: "name", header: "Name", nowrap: true, render: (hook) => hook.name },
        {
          key: "url",
          header: "Target",
          grow: true,
          render: (hook) => <span className="admin-channels__target-cell" title={hook.url_masked}>{hook.url_masked}</span>,
        },
        {
          key: "scope",
          header: "Workspace",
          nowrap: true,
          render: (hook) => projects.find((project) => project.id === hook.project_id)?.name || "Global",
        },
        {
          key: "events",
          header: "Events",
          render: (hook) => {
            const events = hook.event_types.join(", ");
            return <span className="admin-channels__target-cell" title={events}>{events}</span>;
          },
        },
        {
          key: "state",
          header: "State",
          nowrap: true,
          render: (hook) => <StatusLabel label={hook.is_active ? "Active" : "Inactive"} tone="neutral" />,
        },
        {
          key: "last",
          header: "Last delivery",
          nowrap: true,
          render: (hook) =>
            hook.last_delivery_status ? (
              <StatusLabel label={statusWords(hook.last_delivery_status)} title={hook.last_error || undefined} />
            ) : (
              "None yet"
            ),
        },
      ]}
      rowMenu={(hook) => (
        <ActionMenu
          row={{ objectName: hook.name }}
          items={[
            { label: "Edit", onSelect: () => onEdit(hook) },
            { label: hook.is_active ? "Disable" : "Enable", onSelect: () => void onToggleActive(hook) },
            { label: "Delete…", danger: true, onSelect: () => onDelete(hook) },
          ]}
        />
      )}
    />
  );
}
