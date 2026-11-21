import { useState } from "react";

import { SidePanel } from "../../layout/SidePanel";
import { AdminChannelTargetField } from "./AdminChannelTargetField";
import type {
  AdminChannelDeliveryTargetRow,
  AdminChannelRow,
  ProjectOptionRow,
} from "./channelTypes";
import { EmptyLine } from "../../layout/EmptyLine";
import { DataTable } from "../../layout/DataTable";
import { StatusLabel } from "../../layout/StatusLabel";
import { ActionMenu } from "./workflowSurfaces/ActionMenu";
import { PROBLEM_EVENT, PROBLEM_EVENT_LABEL } from "../../chat/notifications/problemAlertsModel";
import "./adminChannels.css";

// Only events that this pipeline actually delivers to a Workspace target (the backend's
// SUPPORTED_DELIVERY_EVENTS); the worker, scheduler and action events never reached it.
const DELIVERY_EVENT_OPTIONS = [
  { value: "approval.requested", label: "An approval is waiting" },
  { value: "trace.alert.triggered", label: "A trace alert fired" },
];

type AdminChannelDeliveryTargetsPanelProps = {
  channels: AdminChannelRow[];
  projects: ProjectOptionRow[];
  targets: AdminChannelDeliveryTargetRow[];
  projectId: string;
  setProjectId: (value: string) => void;
  eventType: string;
  setEventType: (value: string) => void;
  channelId: string;
  setChannelId: (value: string) => void;
  target: string;
  setTarget: (value: string) => void;
  loading: boolean;
  error: string | null;
  // Resolves true once the target is saved; the side panel then closes.
  onCreate: () => Promise<boolean>;
  onDelete: (target: AdminChannelDeliveryTargetRow) => void;
  onSetUpChannel: () => void;
};

function projectName(projects: ProjectOptionRow[], projectId: string | null) {
  return projects.find((project) => project.id === projectId)?.name || "No project";
}

function channelName(channels: AdminChannelRow[], channelId: number | null) {
  if (channelId == null) return "Any active Teams channel";
  return channels.find((channel) => channel.id === channelId)?.name || `Channel ${channelId}`;
}

// Teams alerts for run and device problems (Problem alerts) are Teams subscriptions too, so they are listed here.
const LISTED_EVENT_LABELS = [...DELIVERY_EVENT_OPTIONS, { value: PROBLEM_EVENT, label: PROBLEM_EVENT_LABEL }];

function eventLabel(value: string) {
  return LISTED_EVENT_LABELS.find((option) => option.value === value)?.label || value;
}

/** One row per target; Remove sits in the row's menu. */
function DeliveryTargetsTable({ targets, projects, channels, onDelete }: Pick<
  AdminChannelDeliveryTargetsPanelProps, "targets" | "projects" | "channels" | "onDelete"
>) {
  return (
    <DataTable<AdminChannelDeliveryTargetRow>
      label="Teams delivery targets"
      testId="delivery-targets-table"
      rows={targets}
      rowKey={(row) => row.id}
      columns={[
        { key: "project", header: "Workspace", nowrap: true, render: (row) => projectName(projects, row.project_id) },
        { key: "event", header: "Event", nowrap: true, render: (row) => eventLabel(row.event_type) },
        { key: "channel", header: "Channel", nowrap: true, render: (row) => channelName(channels, row.channel_config_id) },
        {
          key: "target",
          header: "Target",
          grow: true,
          render: (row) => <span className="admin-channels__target-cell" title={row.target}>{row.target}</span>,
        },
        {
          key: "status",
          header: "State",
          nowrap: true,
          render: (row) => <StatusLabel label={row.is_active ? "Active" : "Inactive"} />,
        },
      ]}
      rowMenu={(row) => (
        <ActionMenu
          row={{ objectName: eventLabel(row.event_type) }}
          items={[{ label: "Remove", danger: true, onSelect: () => onDelete(row) }]}
        />
      )}
    />
  );
}

export function AdminChannelDeliveryTargetsPanel(props: AdminChannelDeliveryTargetsPanelProps) {
  const { channels, projects, targets, onDelete, onSetUpChannel } = props;
  const [adding, setAdding] = useState(false);
  const teamsChannels = channels.filter(
    (channel) => channel.plugin_id === "msteams" && channel.id != null,
  );

  return (
    <div className="admin-channels__targets">
      <div className="admin-panel__section-header">
        <span>Teams delivery targets ({targets.length})</span>
        {teamsChannels.length > 0 ? (
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => setAdding(true)}
            data-testid="delivery-target-add"
          >
            Add delivery target
          </button>
        ) : null}
      </div>

      {/* A compact table; Remove sits in the row's ⋯ menu. */}
      {targets.length > 0 ? (
        <DeliveryTargetsTable targets={targets} projects={projects} channels={channels} onDelete={onDelete} />
      ) : null}

      {teamsChannels.length === 0 ? (
        <EmptyLine
          text="Delivery targets need a Microsoft Teams channel."
          action={{ label: "Set up a channel", onClick: onSetUpChannel }}
          testId="delivery-targets-need-teams"
        />
      ) : targets.length === 0 ? (
        <EmptyLine
          text="No delivery targets yet."
          action={{ label: "Add delivery target", onClick: () => setAdding(true) }}
          testId="delivery-targets-empty"
        />
      ) : null}
      {adding && teamsChannels.length > 0 ? (
        <DeliveryTargetForm {...props} teamsChannels={teamsChannels} onClose={() => setAdding(false)} />
      ) : null}
    </div>
  );
}

// "Add delivery target" in the one side panel over the list: labelled fields, Cancel and the
// primary action at the bottom right.
function DeliveryTargetForm({
  projects,
  projectId,
  setProjectId,
  eventType,
  setEventType,
  channelId,
  setChannelId,
  target,
  setTarget,
  loading,
  error,
  onCreate,
  teamsChannels,
  onClose,
}: AdminChannelDeliveryTargetsPanelProps & { teamsChannels: AdminChannelRow[]; onClose: () => void }) {
  const create = async () => {
    if (await onCreate()) onClose();
  };
  return (
    <SidePanel
      title="Add delivery target"
      subtitle="Microsoft Teams"
      onClose={onClose}
      testId="delivery-target-panel"
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            onClick={() => void create()}
            disabled={loading}
          >
            {loading ? "Saving…" : "Add delivery target"}
          </button>
        </>
      )}
    >
      <DeliveryTargetFields projects={projects} projectId={projectId} setProjectId={setProjectId} eventType={eventType}
        setEventType={setEventType} channelId={channelId} setChannelId={setChannelId} target={target} setTarget={setTarget}
        teamsChannels={teamsChannels} />
      {error ? <div className="admin-panel__form-error">{error}</div> : null}
    </SidePanel>
  );
}

type DeliveryTargetFieldsProps = Pick<
  AdminChannelDeliveryTargetsPanelProps,
  "projects" | "projectId" | "setProjectId" | "eventType" | "setEventType" | "channelId" | "setChannelId" | "target" | "setTarget"
> & { teamsChannels: AdminChannelRow[] };

/** Workspace, event, Teams channel configuration and the target. */
function DeliveryTargetFields({
  projects, projectId, setProjectId, eventType, setEventType, channelId, setChannelId, target, setTarget, teamsChannels,
}: DeliveryTargetFieldsProps) {
  return (
    <div className="admin-form-grid">
      <div className="admin-form-field admin-form-grid__full">
        <label className="admin-form-field__label" htmlFor="delivery-target-project">
          Workspace
        </label>
        <select id="delivery-target-project" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
          <option value="">Select a Workspace</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </div>
      <div className="admin-form-field admin-form-grid__full">
        <label className="admin-form-field__label" htmlFor="delivery-target-event">
          Event
        </label>
        <select id="delivery-target-event" value={eventType} onChange={(event) => setEventType(event.target.value)}>
          {DELIVERY_EVENT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div className="admin-form-field admin-form-grid__full">
        <label className="admin-form-field__label" htmlFor="delivery-target-channel">
          Teams channel configuration
        </label>
        <select id="delivery-target-channel" value={channelId} onChange={(event) => setChannelId(event.target.value)}>
          <option value="">Any active Teams channel</option>
          {teamsChannels.map((channel) => (
            <option key={channel.id ?? channel.name} value={channel.id ?? ""}>
              {channel.name}
            </option>
          ))}
        </select>
        <span className="admin-form-help">The bot connection used to post the message.</span>
      </div>
      <AdminChannelTargetField target={target} setTarget={setTarget} />
    </div>
  );
}
