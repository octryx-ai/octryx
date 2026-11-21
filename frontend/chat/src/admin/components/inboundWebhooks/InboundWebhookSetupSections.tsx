// The test alert and setup sections of the inbound webhook side panel.
import {
  FILTER_LABELS,
  groupLabel,
  limitLabel,
  type ActionOption,
  type InboundSource,
  type InboundWebhook,
} from "./inboundWebhookModel";

const GROUP_CHOICES = [30, 120, 0];
const LIMIT_CHOICES = [20, 5, 60];

type TestProps = {
  source: InboundSource | undefined;
  sample: string;
  onSample: (sample: string) => void;
  busy: boolean;
  onSend: () => void;
  testResult: { tone: "ok" | "warn"; text: string } | null;
};

/** Sends one of the source's sample alerts and shows the outcome. */
export function InboundWebhookTestSection({ source, sample, onSample, busy, onSend, testResult }: TestProps) {
  return (
    <section className="automation-drawer-section">
      <h3>Send a test alert</h3>
      <div className="automation-toolbar">
        <label className="admin-panel__field">
          <span>Sample</span>
          <select
            className="admin-panel__input"
            value={sample}
            onChange={(event) => onSample(event.target.value)}
          >
            {(source?.samples ?? []).map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy || !sample}
          onClick={onSend}
        >
          Send test
        </button>
      </div>
      {testResult ? (
        <div
          className={
            testResult.tone === "ok"
              ? "automation-okbox"
              : "automation-warnbox"
          }
          role="status"
        >
          {testResult.text}
        </div>
      ) : null}
    </section>
  );
}

type SetupProps = {
  webhook: InboundWebhook;
  workspaceActions: ActionOption[];
  busy: boolean;
  error: string | null;
  save: (patch: Record<string, unknown>) => Promise<void>;
};

/** How many runs an hour at most; extra alerts are listed as skipped. */
function InboundWebhookLimitField({ webhook, busy, save }: Pick<SetupProps, "webhook" | "busy" | "save">) {
  return (
    <label className="admin-panel__field">
      <span>At most</span>
      <select
        className="admin-panel__input"
        value={webhook.rate_limit_per_hour}
        disabled={busy}
        onChange={(event) =>
          void save({ rate_limit_per_hour: Number(event.target.value) })
        }
      >
        {[
          ...new Set([webhook.rate_limit_per_hour, ...LIMIT_CHOICES]),
        ].map((limit) => (
          <option key={limit} value={limit}>
            {limitLabel(limit)}
          </option>
        ))}
      </select>
      <small className="automation-muted">
        Extra alerts are listed as skipped, never dropped silently.
      </small>
    </label>
  );
}

/** Advanced: which alerts start a run, how repeats are grouped and how many runs an hour at most. */
function InboundWebhookAdvanced({ webhook, busy, save }: Pick<SetupProps, "webhook" | "busy" | "save">) {
  return (
    <details className="automation-details">
      <summary>Advanced: filters, repeats, limits</summary>
      <div className="admin-panel__form">
        <label className="admin-panel__field">
          <span>Only start for</span>
          <select
            className="admin-panel__input"
            value={webhook.alert_filter}
            disabled={busy}
            onChange={(event) =>
              void save({ alert_filter: event.target.value })
            }
          >
            {Object.entries(FILTER_LABELS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="admin-panel__field">
          <span>Repeats</span>
          <select
            className="admin-panel__input"
            value={webhook.group_window_minutes}
            disabled={busy}
            onChange={(event) =>
              void save({
                group_window_minutes: Number(event.target.value),
              })
            }
          >
            {[
              ...new Set([webhook.group_window_minutes, ...GROUP_CHOICES]),
            ].map((minutes) => (
              <option key={minutes} value={minutes}>
                {groupLabel(minutes)}
              </option>
            ))}
          </select>
        </label>
        <InboundWebhookLimitField webhook={webhook} busy={busy} save={save} />
      </div>
    </details>
  );
}

/** The action to start, filters, repeats and limits. */
export function InboundWebhookSetup({ webhook, workspaceActions, busy, error, save }: SetupProps) {
  return (
    <section className="automation-drawer-section">
      <h3>Setup</h3>
      <label className="admin-panel__field">
        <span>Start</span>
        <select
          className="admin-panel__input"
          value={webhook.task_id ?? ""}
          disabled={busy}
          onChange={(event) =>
            void save({ task_id: event.target.value || null })
          }
        >
          <option value="">Choose an action</option>
          {workspaceActions.map((action) => (
            <option key={action.id} value={action.id}>
              {action.name}
            </option>
          ))}
        </select>
        <small className="automation-muted">
          The result goes where the action sends it: {webhook.result_to.label}
          .
        </small>
      </label>
      <InboundWebhookAdvanced webhook={webhook} busy={busy} save={save} />
      <p className="automation-muted">
        Runs as the {webhook.workspace_name} automation identity. What it may
        do comes from the action's workflow; the alert is attached to the run
        as data, not pasted into the instructions.
      </p>
      {error ? (
        <p className="automation-tone--error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
