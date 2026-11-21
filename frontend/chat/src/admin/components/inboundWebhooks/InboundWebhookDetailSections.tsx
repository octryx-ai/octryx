// The flow and connect sections of the inbound webhook side panel.
import { formatRelativeTime } from "../../utils/formatters";
import { AutomationIcon } from "../automation/AutomationIcon";
import { InboundSecretFields } from "./InboundSecretFields";
import {
  FILTER_LABELS,
  WORKFLOW_LABELS,
  pollQueryLabel,
  stateLine,
  type InboundWebhook,
} from "./inboundWebhookModel";

type FlowProps = {
  webhook: InboundWebhook;
  state: ReturnType<typeof stateLine>;
};

/** Source → action → result, with the webhook's state line. */
export function InboundWebhookFlow({ webhook, state }: FlowProps) {
  return (
    <section className="automation-drawer-section">
      <div className="automation-flow">
        <div className="automation-flow__node">
          <AutomationIcon kind={webhook.source_type} small />
          <div>
            <b>{webhook.source_label}</b>
            <span className="automation-muted">
              {FILTER_LABELS[webhook.alert_filter]}
            </span>
          </div>
        </div>
        <span className="automation-flow__arrow">→</span>
        <div className="automation-flow__node">
          <AutomationIcon kind="action" small />
          <div>
            <b>{webhook.action?.name ?? "No action yet"}</b>
            <span className="automation-muted">
              {webhook.workspace_name}
              {webhook.action?.workflow
                ? ` · ${WORKFLOW_LABELS[webhook.action.workflow] ?? webhook.action.workflow}`
                : ""}
            </span>
          </div>
        </div>
        <span className="automation-flow__arrow">→</span>
        <div className="automation-flow__node">
          <AutomationIcon
            kind={
              webhook.result_to.plugin_id?.includes("slack")
                ? "slack"
                : webhook.result_to.kind === "channel"
                  ? "teams"
                  : "action"
            }
            small
          />
          <div>
            <b>{webhook.result_to.label}</b>
            <span className="automation-muted">Result</span>
          </div>
        </div>
      </div>
      <p
        className={`automation-tone--${state.tone === "ok" ? "ok" : state.tone === "warn" ? "warn" : "muted"}`}
      >
        {state.text}
      </p>
    </section>
  );
}

type ConnectProps = {
  webhook: InboundWebhook;
  rotated: InboundWebhook | null;
  busy: boolean;
  save: (patch: Record<string, unknown>) => Promise<void>;
  onRotate: () => void;
};

/** Where the alerts come from: the URL and secret, or the polled query. */
export function InboundWebhookConnect({ webhook, rotated, busy, save, onRotate }: ConnectProps) {
  return (
    <section className="automation-drawer-section">
      <h3>
        {webhook.polled
          ? "Where the changes come from"
          : "Connect your alerting tool"}
      </h3>
      <InboundSecretFields webhook={rotated ?? webhook} />
      {webhook.polled ? (
        <>
          <label className="admin-panel__field">
            <span>{pollQueryLabel(webhook.source_type)}</span>
            <input
              className="admin-panel__input"
              defaultValue={webhook.poll_query ?? ""}
              disabled={busy}
              onBlur={(event) => {
                if (event.target.value.trim() !== (webhook.poll_query ?? ""))
                  void save({ poll_query: event.target.value });
              }}
            />
          </label>
          <p className="automation-muted">
            Checked every 5 minutes through the Workspace's connection
            {webhook.last_polled_at
              ? ` · last checked ${formatRelativeTime(webhook.last_polled_at)}`
              : " · not checked yet"}
            .
          </p>
        </>
      ) : null}
      {!webhook.polled ? (
        <div>
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={busy}
            onClick={onRotate}
          >
            Rotate secret…
          </button>
          <label className="admin-panel__checkbox">
            <input
              type="checkbox"
              checked={Boolean(webhook.accept_untimestamped)}
              disabled={busy}
              onChange={(event) =>
                void save({ accept_untimestamped: event.target.checked })
              }
            />
            {/* The label only; when to use it is the tooltip and in the Webhooks help. */}
            <span title="For tools that can only send the secret or sign the body. Repeats of the same call within 5 minutes are still refused.">
              Accept calls without a signed timestamp
            </span>
          </label>
        </div>
      ) : null}
    </section>
  );
}
