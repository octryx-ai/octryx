import { useState } from "react";

import { AdminChannelTargetField } from "../../admin/components/AdminChannelTargetField";
import { FormSection } from "../../layout/FormSection";
import { SidePanel } from "../../layout/SidePanel";
import {
  ALERT_CHANNELS,
  PROBLEM_EVENT,
  PROBLEM_EVENT_LABEL,
  channelInfo,
  type AlertChannel,
  type NotificationSubscription,
} from "./problemAlertsModel";

// One alert subscription in the side panel: personal (the channel is given) or a Workspace's (Workspace, channel and
// the channel connection to send through). Shows the server's refusal verbatim at the bottom.

export type ProblemAlertDraft = {
  projectId: string | null;
  channel: AlertChannel;
  channelConfigId: number | null;
  target: string;
  active: boolean;
};

type Option = { id: string; name: string };
type Connection = { id: number | null; name: string; plugin_id: string };

type ProblemAlertFormProps = {
  title: string;
  primaryLabel: string;
  initial: NotificationSubscription | null;
  // Personal: the channel of the row; no Workspace and connection choice.
  fixedChannel?: AlertChannel;
  // A Workspace's alerts: the Workspaces and the configured channel connections to choose from.
  workspaces?: Option[];
  connections?: Connection[];
  onClose: () => void;
  // Resolves null when saved (the panel closes), else the message to show.
  onSave: (draft: ProblemAlertDraft) => Promise<string | null>;
};

const asChannel = (value: string | undefined): AlertChannel => channelInfo(value ?? "")?.key ?? "email";

export function ProblemAlertForm({
  title, primaryLabel, initial, fixedChannel, workspaces, connections, onClose, onSave,
}: ProblemAlertFormProps) {
  const [draft, setDraft] = useState<ProblemAlertDraft>(() => ({
    projectId: initial?.project_id ?? (workspaces?.length === 1 ? workspaces[0].id : null),
    channel: fixedChannel ?? asChannel(initial?.channel_type),
    channelConfigId: initial?.channel_config_id ?? null,
    target: initial?.target ?? "",
    active: initial?.is_active ?? true,
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const info = channelInfo(draft.channel) ?? ALERT_CHANNELS[0];
  const set = (patch: Partial<ProblemAlertDraft>) => setDraft((current) => ({ ...current, ...patch }));
  const connectionsHere = (connections ?? []).filter((item) => item.plugin_id === info.plugin && item.id != null);
  const ready = draft.target.trim() !== "" && (!workspaces || Boolean(draft.projectId));

  const submit = async () => {
    setSaving(true);
    setError(null);
    const message = await onSave(draft);
    setSaving(false);
    if (message === null) onClose();
    else setError(message);
  };

  return (
    <SidePanel
      title={title}
      subtitle={PROBLEM_EVENT_LABEL}
      onClose={onClose}
      testId="problem-alert-panel"
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
            onClick={() => void submit()} disabled={saving || !ready} data-testid="problem-alert-save">
            {saving ? "Saving…" : primaryLabel}
          </button>
        </>
      )}
    >
      <FormSection title="Where alerts go">
        <div className="admin-form-grid">
          {workspaces ? (
            <div className="admin-form-field admin-form-grid__full">
              <label className="admin-form-field__label" htmlFor="problem-alert-workspace">Workspace</label>
              <select id="problem-alert-workspace" value={draft.projectId ?? ""}
                onChange={(event) => set({ projectId: event.target.value || null })}>
                <option value="">Select a Workspace</option>
                {workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </div>
          ) : null}
          {fixedChannel ? null : (
            <div className="admin-form-field admin-form-grid__full">
              <label className="admin-form-field__label" htmlFor="problem-alert-channel">Channel</label>
              <select id="problem-alert-channel" value={draft.channel}
                onChange={(event) => set({ channel: asChannel(event.target.value), channelConfigId: null })}>
                {ALERT_CHANNELS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
              </select>
            </div>
          )}
          {connections ? (
            <div className="admin-form-field admin-form-grid__full">
              <label className="admin-form-field__label" htmlFor="problem-alert-connection">Send through</label>
              <select id="problem-alert-connection" value={draft.channelConfigId ?? ""}
                onChange={(event) => set({ channelConfigId: event.target.value ? Number(event.target.value) : null })}>
                <option value="">Any active {info.label} channel</option>
                {connectionsHere.map((item) => <option key={item.id} value={item.id ?? ""}>{item.name}</option>)}
              </select>
            </div>
          ) : null}
          {draft.channel === "teams" ? (
            <AdminChannelTargetField target={draft.target} setTarget={(target) => set({ target })} />
          ) : (
            <div className="admin-form-field admin-form-grid__full">
              <label className="admin-form-field__label" htmlFor="problem-alert-target">{info.targetLabel}</label>
              <input id="problem-alert-target" value={draft.target} placeholder={info.placeholder}
                type={draft.channel === "email" ? "email" : "text"} spellCheck={false} autoComplete="off"
                onChange={(event) => set({ target: event.target.value })} />
            </div>
          )}
          {workspaces ? (
            <label className="alerts__check admin-form-grid__full">
              <input type="checkbox" checked={draft.active} onChange={(event) => set({ active: event.target.checked })} />
              <span>Active</span>
            </label>
          ) : null}
          <div className="admin-form-field admin-form-grid__full">
            <span className="admin-form-field__label">Event</span>
            <span className="alerts__event">
              {PROBLEM_EVENT_LABEL} <code className="alerts__key">{PROBLEM_EVENT}</code>
            </span>
          </div>
        </div>
      </FormSection>
      {error ? <div className="admin-panel__form-error" role="alert">{error}</div> : null}
    </SidePanel>
  );
}
