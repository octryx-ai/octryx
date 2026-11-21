import { formatRelativeTime } from "../../utils/formatters";
import { AutomationIcon } from "../automation/AutomationIcon";
import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { StatusLabel, type StatusTone } from "../../../layout/StatusLabel";
import "../adminDetailFacts.css";
import {
  outcomeLabel,
  outcomeTone,
  type InboundEvent,
  type Tone,
} from "./inboundWebhookModel";

// The outcome's tone in the one state colour scale: a finished analysis is worth noticing, a started one is in
// progress, a refused call failed, a webhook that waits for setup needs a person; the rest is neutral.
const STATUS_TONES: Record<Tone, StatusTone> = { ok: "neutral", warn: "attention", error: "problem", muted: "neutral" };

export function outcomeStatusTone(outcome: string): StatusTone {
  if (outcome === "completed") return "success";
  if (outcome === "started") return "info";
  return STATUS_TONES[outcomeTone(outcome)];
}

// Recent alerts as a compact table with their outcome in words, never as its code
// ("rejected_replay" reads "Duplicate"); "Open run" goes to the run's conversation.
export function InboundEventRows({
  events,
  showWebhook = false,
}: {
  events: InboundEvent[];
  showWebhook?: boolean;
}) {
  const columns: DataTableColumn<InboundEvent>[] = [
    {
      key: "time",
      header: "Received",
      nowrap: true,
      render: (event) => formatRelativeTime(event.received_at),
    },
    ...(showWebhook
      ? [{
          key: "webhook",
          header: "Webhook",
          nowrap: true,
          render: (event: InboundEvent) => (
            <span className="admin-detail-name">
              <AutomationIcon kind={event.source_type || "generic"} small />
              <span>{event.webhook_name || "Removed webhook"}</span>
            </span>
          ),
        }]
      : []),
    {
      key: "alert",
      header: "Alert",
      nowrap: true,
      render: (event) => `${event.title || outcomeLabel(event.outcome)}${event.is_test ? " (test)" : ""}`,
    },
    {
      key: "message",
      header: "Details",
      grow: true,
      render: (event) => <span title={event.error || undefined}>{event.message}</span>,
    },
    {
      key: "outcome",
      header: "Outcome",
      nowrap: true,
      render: (event) => (
        <StatusLabel label={outcomeLabel(event.outcome)} tone={outcomeStatusTone(event.outcome)} />
      ),
    },
    {
      key: "run",
      header: "Run",
      nowrap: true,
      render: (event) =>
        event.session_id ? (
          <a className="ds-link-button" href={`/chat?session_id=${encodeURIComponent(event.session_id)}`}>
            Open run
          </a>
        ) : (
          ""
        ),
    },
  ];
  return (
    <DataTable<InboundEvent>
      label="Alerts"
      testId="inbound-events"
      rows={events}
      rowKey={(event) => event.id}
      empty={{ text: "No alerts yet." }}
      columns={columns}
    />
  );
}
