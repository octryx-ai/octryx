import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "../../admin/components/confirm/ConfirmDialog";
import { ActionMenu } from "../../admin/components/workflowSurfaces/ActionMenu";
import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { PageHeader } from "../../layout/PageHeader";
import { StatusLabel } from "../../layout/StatusLabel";
import { loadSubscriptions, removeSubscription, saveSubscription, sendTest } from "./problemAlertsApi";
import {
  ALERT_CHANNELS,
  PROBLEM_EVENT_LABEL,
  TEST_SENT,
  personalChannelOn,
  personalProblemSubscription,
  problemSubscriptionRequest,
  withActive,
  type AlertChannel,
  type AlertChannelInfo,
  type NotificationSubscription,
} from "./problemAlertsModel";
import { ProblemAlertForm } from "./ProblemAlertForm";
import "./problemAlerts.css";

// My settings › Notifications: how the signed-in person hears about run and device problems. In-app (the bell, the
// companion and the phone) is always on; email, Slack and Teams are the person's own notification subscriptions to
// problem.raised. Each is its own switch: the global channel preferences gate only "*" subscriptions and
// are never touched here.

type Row = { key: "in_app" } | { key: AlertChannel; info: AlertChannelInfo; subscription: NotificationSubscription | null };

const errorText = (error: unknown) => (error instanceof Error && error.message) || "That did not work. Try again.";

export function MyNotificationsPage() {
  const state = useMyNotifications();
  const { subscriptions, error, notice, busy, editing, setEditing, removing, setRemoving, removeError, setRemoveError, subscriptionOf } = state;
  const { toggle, save, test, confirmRemove } = notificationActions(state);
  const rows: Row[] = [
    { key: "in_app" },
    ...ALERT_CHANNELS.map((info) => ({ key: info.key, info, subscription: subscriptionOf(info.key) })),
  ];
  const editingInfo = editing ? ALERT_CHANNELS.find((info) => info.key === editing) ?? null : null;

  return (
    <>
      <div className="admin-panel__header">
        <PageHeader eyebrow="My settings" title="Notifications"
          purpose="How you hear about runs and device jobs that are stuck or failed." />
      </div>
      <div className="admin-panel__body">
        <div className="admin-panel__stack">
          {error ? <p className="work-area__error" role="alert">{error}</p> : null}
          {notice ? <p className="alerts__notice" role="status" data-testid="alerts-notice">{notice}</p> : null}
          <section className="admin-panel__card" data-testid="my-problem-alerts">
            <div className="admin-panel__section-header"><span>{PROBLEM_EVENT_LABEL}</span></div>
            <DataTable<Row>
              label={PROBLEM_EVENT_LABEL}
              testId="my-problem-alerts-table"
              rows={rows}
              rowKey={(row) => row.key}
              loading={subscriptions === null && !error}
              loadingLabel="alert settings"
              columns={channelColumns(busy, toggle)}
              rowMenu={(row) => (row.key === "in_app" ? null : channelMenu(row, { setEditing, test, setRemoveError, setRemoving }))}
            />
          </section>
        </div>
      </div>
      {editingInfo ? (
        <ProblemAlertForm
          title={`${editingInfo.label} alerts`}
          fixedChannel={editingInfo.key}
          initial={subscriptionOf(editingInfo.key)}
          primaryLabel={subscriptionOf(editingInfo.key) ? "Save" : `Turn on ${editingInfo.label} alerts`}
          onClose={() => setEditing(null)}
          onSave={(draft) => save(editingInfo.key, draft.target, draft.channelConfigId)}
        />
      ) : null}
      {removing ? (
        <ConfirmDialog
          title={`Remove ${ALERT_CHANNELS.find((info) => info.key === removing.channel_type)?.label ?? "these"} alerts?`}
          confirmLabel="Remove"
          error={removeError}
          onCancel={() => setRemoving(null)}
          onConfirm={() => void confirmRemove()}
        >
          <span>Problems are no longer sent to <code>{removing.target}</code>.</span>
        </ConfirmDialog>
      ) : null}
    </>
  );
}

// The person's own subscriptions, loaded once, and the page's switches, form and confirmation state.
function useMyNotifications() {
  const [subscriptions, setSubscriptions] = useState<NotificationSubscription[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<AlertChannel | null>(null);
  const [editing, setEditing] = useState<AlertChannel | null>(null);
  const [removing, setRemoving] = useState<NotificationSubscription | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setSubscriptions(await loadSubscriptions("personal"));
  }, []);

  useEffect(() => {
    reload().catch((reason) => setError(errorText(reason)));
  }, [reload]);

  const subscriptionOf = (channel: AlertChannel) => personalProblemSubscription(subscriptions ?? [], channel);
  return { subscriptions, error, setError, notice, setNotice, busy, setBusy, editing, setEditing, removing, setRemoving,
    removeError, setRemoveError, reload, subscriptionOf };
}

function notificationActions({ subscriptionOf, setEditing, setBusy, setError, setNotice, reload, removing, setRemoving,
  setRemoveError }: ReturnType<typeof useMyNotifications>) {
  const toggle = async (channel: AlertChannel) => {
    const subscription = subscriptionOf(channel);
    if (!subscription) { setEditing(channel); return; }
    setBusy(channel);
    setError(null);
    setNotice(null);
    try {
      await saveSubscription("personal", withActive(subscription, !subscription.is_active), subscription.id);
      await reload();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(null);
    }
  };

  // Resolves null when saved, else the server's message for the form.
  const save = async (channel: AlertChannel, target: string, channelConfigId: number | null): Promise<string | null> => {
    const subscription = subscriptionOf(channel);
    try {
      const body = problemSubscriptionRequest(
        { channel, target, projectId: subscription?.project_id ?? null, channelConfigId, active: true },
        subscription,
      );
      await saveSubscription("personal", body, subscription?.id);
      await reload();
      return null;
    } catch (reason) {
      return errorText(reason);
    }
  };

  const test = async (subscription: NotificationSubscription) => {
    setError(null);
    setNotice(null);
    try {
      await sendTest("personal", subscription.id);
      setNotice(TEST_SENT);
    } catch (reason) {
      setError(errorText(reason));
    }
  };

  const confirmRemove = async () => {
    if (!removing) return;
    setRemoveError(null);
    try {
      await removeSubscription("personal", removing.id);
      setRemoving(null);
      await reload();
    } catch (reason) {
      setRemoveError(errorText(reason));
    }
  };

  return { toggle, save, test, confirmRemove };
}

type ChannelRow = Exclude<Row, { key: "in_app" }>;

function channelColumns(busy: AlertChannel | null, toggle: (channel: AlertChannel) => Promise<void>): DataTableColumn<Row>[] {
  return [
    { key: "channel", header: "Channel", nowrap: true,
      render: (row) => (row.key === "in_app" ? "In app" : row.info.label) },
    { key: "covers", header: "What arrives", grow: true,
      render: (row) => (row.key === "in_app"
        ? "Problems with your runs and device jobs, in the bell and on your phone"
        : "Problems in your runs and in the Workspaces you administer") },
    { key: "target", header: "Sends to", clip: "18rem",
      render: (row) => (row.key === "in_app"
        ? "Octryx"
        : row.subscription
          ? <span className="alerts__target" title={row.subscription.target}>{row.subscription.target}</span>
          : <span className="alerts__muted">Not set up</span>) },
    { key: "state", header: "On", nowrap: true, align: "end",
      render: (row) => (row.key === "in_app"
        ? <StatusLabel label="Always on" tone="neutral" />
        : <ChannelSwitch label={row.info.label}
            on={personalChannelOn(row.subscription)}
            busy={busy === row.key} onToggle={() => void toggle(row.key)} />) },
  ];
}

function channelMenu(row: ChannelRow, { setEditing, test, setRemoveError, setRemoving }: {
  setEditing: (channel: AlertChannel) => void;
  test: (subscription: NotificationSubscription) => Promise<void>;
  setRemoveError: (error: string | null) => void;
  setRemoving: (subscription: NotificationSubscription | null) => void;
}) {
  return (
    <ActionMenu
      row={{ objectName: `${row.info.label} alerts` }}
      items={[
        { label: row.subscription ? "Change where it goes…" : "Set up…", onSelect: () => setEditing(row.key) },
        ...(row.subscription
          ? [{ label: "Send test", onSelect: () => void test(row.subscription as NotificationSubscription) }]
          : []),
        ...(row.subscription
          ? [{ label: "Remove…", danger: true, onSelect: () => { setRemoveError(null); setRemoving(row.subscription); } }]
          : []),
      ]}
    />
  );
}

function ChannelSwitch({ label, on, busy, onToggle }: { label: string; on: boolean; busy: boolean; onToggle: () => void }) {
  return (
    <span
      className={`toggle-switch ${on ? "toggle-switch--on" : ""}`}
      role="switch"
      aria-checked={on}
      aria-label={`${label} alerts`}
      aria-disabled={busy}
      tabIndex={0}
      onClick={() => { if (!busy) onToggle(); }}
      onKeyDown={(event) => {
        if (event.key === " " || event.key === "Enter") {
          event.preventDefault();
          if (!busy) onToggle();
        }
      }}
    />
  );
}
