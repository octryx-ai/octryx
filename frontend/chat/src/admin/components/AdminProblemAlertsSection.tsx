import { useCallback, useEffect, useState } from "react";

import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { EmptyLine } from "../../layout/EmptyLine";
import { StatusLabel } from "../../layout/StatusLabel";
import { useAdminNavigation } from "../adminNavigation";
import { ProblemAlertForm, type ProblemAlertDraft } from "../../chat/notifications/ProblemAlertForm";
import { loadSubscriptions, removeSubscription, saveSubscription, sendTest } from "../../chat/notifications/problemAlertsApi";
import {
  TEST_SENT,
  channelLabel,
  problemSubscriptionRequest,
  withActive,
  workspaceAlertState,
  workspaceProblemSubscriptions,
  type NotificationSubscription,
} from "../../chat/notifications/problemAlertsModel";
import "../../chat/notifications/problemAlerts.css";
import { ConfirmDialog } from "./confirm/ConfirmDialog";
import type { AdminChannelRow, ProjectOptionRow } from "./channelTypes";
import { ActionMenu } from "./workflowSurfaces/ActionMenu";
import "./adminChannels.css";

// Connections › Channels › Problem alerts: where a Workspace's run and device problems (problem.raised) are
// sent by email, Slack or Microsoft Teams. Each row is a Workspace notification subscription
// (/admin/notification-subscriptions with no person). Outbound webhooks for problem.raised and
// problem.cleared stay on the Webhooks page; this page links there.

type Props = {
  channels: AdminChannelRow[];
  projects: ProjectOptionRow[];
};

const errorText = (error: unknown) => (error instanceof Error && error.message) || "That did not work. Try again.";

// The page's state and actions: the Workspace subscriptions, the open form and the remove confirmation.
function useProblemAlerts() {
  const [all, setAll] = useState<NotificationSubscription[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // null: closed; "new": the add form; else the subscription being edited.
  const [editing, setEditing] = useState<NotificationSubscription | "new" | null>(null);
  const [removing, setRemoving] = useState<NotificationSubscription | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setAll(await loadSubscriptions("workspace"));
  }, []);

  useEffect(() => {
    reload().catch((reason) => setError(errorText(reason)));
  }, [reload]);

  const run = async (work: () => Promise<void>, done: string | null = null) => {
    setError(null);
    setNotice(null);
    try {
      await work();
      setNotice(done);
      await reload();
    } catch (reason) {
      setError(errorText(reason));
    }
  };

  const save = async (draft: ProblemAlertDraft): Promise<string | null> => {
    const base = editing && editing !== "new" ? editing : null;
    try {
      await saveSubscription("workspace", problemSubscriptionRequest(draft, base), base?.id);
      await reload();
      return null;
    } catch (reason) {
      return errorText(reason);
    }
  };

  const confirmRemove = async () => {
    if (!removing) return;
    setRemoveError(null);
    try {
      await removeSubscription("workspace", removing.id);
      setRemoving(null);
      await reload();
    } catch (reason) {
      setRemoveError(errorText(reason));
    }
  };

  return { all, error, notice, editing, setEditing, removing, setRemoving, removeError, setRemoveError, run, save, confirmRemove };
}

type ProblemAlertsState = ReturnType<typeof useProblemAlerts>;

function problemAlertColumns(
  channels: AdminChannelRow[],
  workspaceName: (id: string | null) => string,
  connectionName: (row: NotificationSubscription) => string,
): DataTableColumn<NotificationSubscription>[] {
  return [
    { key: "workspace", header: "Workspace", nowrap: true, render: (row) => workspaceName(row.project_id) },
    { key: "channel", header: "Channel", nowrap: true, render: (row) => channelLabel(row.channel_type) },
    { key: "target", header: "Sends to", grow: true, clip: "18rem",
      render: (row) => <span className="alerts__target" title={row.target}>{row.target}</span> },
    { key: "via", header: "Through", clip: "14rem", render: connectionName },
    { key: "state", header: "State", nowrap: true, render: (row) => {
      const state = workspaceAlertState(row, channels);
      return <StatusLabel label={state} tone={state === "Needs configuration" ? "attention" : "neutral"}
        title={state === "Needs configuration" ? `No enabled ${channelLabel(row.channel_type)} channel can send this.` : undefined} />;
    } },
  ];
}

function problemAlertMenu(row: NotificationSubscription, alerts: ProblemAlertsState, workspaceName: (id: string | null) => string) {
  const { setEditing, run, setRemoveError, setRemoving } = alerts;
  return (
    <ActionMenu
      row={{ objectName: `${channelLabel(row.channel_type)} alert for ${workspaceName(row.project_id)}` }}
      items={[
        { label: "Edit…", onSelect: () => setEditing(row) },
        { label: "Send test", onSelect: () => void run(() => sendTest("workspace", row.id), TEST_SENT) },
        { label: row.is_active ? "Turn off" : "Turn on",
          onSelect: () => void run(() => saveSubscription("workspace", withActive(row, !row.is_active), row.id)) },
        { label: "Remove…", danger: true, onSelect: () => { setRemoveError(null); setRemoving(row); } },
      ]}
    />
  );
}

type ProblemAlertDialogsProps = Props & { alerts: ProblemAlertsState; workspaceName: (id: string | null) => string };

function ProblemAlertDialogs({ channels, projects, alerts, workspaceName }: ProblemAlertDialogsProps) {
  const { editing, setEditing, removing, setRemoving, removeError, save, confirmRemove } = alerts;
  return (
    <>
      {editing ? (
        <ProblemAlertForm
          key={editing === "new" ? "new" : editing.id}
          title={editing === "new" ? "Add alert" : "Edit alert"}
          primaryLabel={editing === "new" ? "Add alert" : "Save"}
          initial={editing === "new" ? null : editing}
          workspaces={projects}
          connections={channels}
          onClose={() => setEditing(null)}
          onSave={save}
        />
      ) : null}
      {removing ? (
        <ConfirmDialog
          title={`Remove the ${channelLabel(removing.channel_type)} alert for ${workspaceName(removing.project_id)}?`}
          confirmLabel="Remove alert"
          error={removeError}
          onCancel={() => setRemoving(null)}
          onConfirm={() => void confirmRemove()}
        >
          <span>Problems in this Workspace are no longer sent to <code>{removing.target}</code>.</span>
        </ConfirmDialog>
      ) : null}
    </>
  );
}

export function AdminProblemAlertsSection({ channels, projects }: Props) {
  const { openAdminTab } = useAdminNavigation();
  const alerts = useProblemAlerts();
  const { all, error, notice, editing, setEditing } = alerts;

  const workspaceName = (id: string | null) => projects.find((project) => project.id === id)?.name ?? "Unknown Workspace";
  const connectionName = (row: NotificationSubscription) => (row.channel_config_id == null
    ? `Any active ${channelLabel(row.channel_type)} channel`
    : channels.find((channel) => channel.id === row.channel_config_id)?.name ?? `Channel ${row.channel_config_id}`);
  const rows = all ? workspaceProblemSubscriptions(all, (id) => workspaceName(id)) : [];

  const add = () => setEditing("new");

  return (
    <div className="admin-channels__targets" data-testid="problem-alerts">
      <div className="admin-panel__section-header">
        <span>Run and device problems ({rows.length})</span>
        <button type="button" className="admin-panel__action-btn" onClick={add} data-testid="problem-alert-add">
          Add alert
        </button>
      </div>
      {error ? <div className="admin-panel__form-error" role="alert">{error}</div> : null}
      {notice ? <p className="alerts__notice" role="status" data-testid="alerts-notice">{notice}</p> : null}
      <DataTable<NotificationSubscription>
        label="Run and device problem alerts"
        testId="problem-alerts-table"
        rows={rows}
        rowKey={(row) => row.id}
        loading={all === null && !error}
        loadingLabel="problem alerts"
        onOpen={(row) => setEditing(row)}
        selectedKey={editing && editing !== "new" ? editing.id : null}
        empty={{ text: "No Workspace sends its problems to a channel yet.", action: { label: "Add alert", onClick: add } }}
        columns={problemAlertColumns(channels, workspaceName, connectionName)}
        rowMenu={(row) => problemAlertMenu(row, alerts, workspaceName)}
      />
      <div className="alerts__footer">
        <EmptyLine
          text="Webhooks can report each problem too, when it appears and when it clears."
          action={{ label: "Open webhooks", onClick: () => openAdminTab("webhooks") }}
          testId="problem-alerts-webhooks"
        />
      </div>
      <ProblemAlertDialogs channels={channels} projects={projects} alerts={alerts} workspaceName={workspaceName} />
    </div>
  );
}
