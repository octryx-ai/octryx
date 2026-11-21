import type { Dispatch, SetStateAction } from "react";
import { SidePanel } from "../../layout/SidePanel";
import { AdminChannelConfigFields } from "./AdminChannelConfigFields";
import type { AdminChannelRow, ProjectOptionRow } from "./channelTypes";

type AdminChannelConfigModalProps = {
  channel: AdminChannelRow | null;
  onClose: () => void;
  projects: ProjectOptionRow[];
  channelFormName: string;
  setChannelFormName: (value: string) => void;
  channelFormProjectId: string;
  setChannelFormProjectId: (value: string) => void;
  channelFormEnabled: boolean;
  setChannelFormEnabled: Dispatch<SetStateAction<boolean>>;
  channelShowRawJson: boolean;
  setChannelShowRawJson: Dispatch<SetStateAction<boolean>>;
  channelConfigJson: string;
  setChannelConfigJson: (value: string) => void;
  channelFormValues: Record<string, unknown>;
  setChannelFormValues: Dispatch<SetStateAction<Record<string, unknown>>>;
  channelFormError: string | null;
  channelFormLoading: boolean;
  onSave: () => Promise<void> | void;
};

type PartProps = { props: AdminChannelConfigModalProps; channel: AdminChannelRow };

export function AdminChannelConfigModal(props: AdminChannelConfigModalProps) {
  const { channel, onClose, channelFormError, channelFormLoading, onSave } = props;
  if (!channel) {
    return null;
  }

  // Adding or configuring a channel happens in the one side panel over the list: labelled
  // fields, Cancel and the primary action at the bottom right.
  return (
    <SidePanel
      title={channel.id == null ? `Add ${channel.name}` : `Configure ${channel.name}`}
      subtitle="Channel"
      onClose={onClose}
      testId="channel-config-panel"
      footer={(
        <>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={channelFormLoading}
            onClick={onSave}
          >
            {channelFormLoading ? "Saving…" : "Save and apply"}
          </button>
        </>
      )}
    >
          <div className="admin-modal__stack">
            <ChannelBasics props={props} channel={channel} />

            <ChannelConfiguration props={props} channel={channel} />

            {channelFormError ? (
              <div className="admin-panel__error">{channelFormError}</div>
            ) : null}
          </div>
    </SidePanel>
  );
}

function ChannelBasics({ props, channel }: PartProps) {
  const {
    projects, channelFormName, setChannelFormName, channelFormProjectId, setChannelFormProjectId, channelFormEnabled,
    setChannelFormEnabled,
  } = props;
  return (
    <>
    <div className="admin-form-field">
      <label className="admin-form-field__label">Channel name</label>
      <input
        type="text"
        className="admin-panel__form-input"
        value={channelFormName}
        onChange={(event) => setChannelFormName(event.target.value)}
      />
    </div>

    <div className="admin-form-field">
      <label className="admin-form-field__label">Workspace</label>
      <select
        className="admin-panel__form-input"
        value={channelFormProjectId}
        onChange={(event) =>
          setChannelFormProjectId(event.target.value)
        }
      >
        <option value="">No Workspace binding</option>
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </div>

    {channel.webhook_url ? (
      <div className="admin-form-field">
        <label className="admin-form-field__label">Webhook URL</label>
        <input
          type="text"
          className="admin-panel__form-input"
          value={channel.webhook_url}
          readOnly
        />
      </div>
    ) : null}

    <ChannelEnableSwitch enabled={channelFormEnabled} setEnabled={setChannelFormEnabled} />
    </>
  );
}

// The raw JSON view writes the form values back when it closes (invalid JSON keeps them); the form view writes them out.
function toggleRawJson(props: AdminChannelConfigModalProps) {
  const { channelShowRawJson, setChannelConfigJson, channelFormValues, setChannelFormValues, channelConfigJson, setChannelShowRawJson } = props;
  if (!channelShowRawJson) {
    setChannelConfigJson(
      JSON.stringify(channelFormValues, null, 2),
    );
  } else {
    try {
      setChannelFormValues(
        JSON.parse(channelConfigJson) as Record<
          string,
          unknown
        >,
      );
    } catch {
      // Keep current form values when raw JSON is invalid.
    }
  }
  setChannelShowRawJson((value) => !value);
}

function ChannelConfiguration({ props, channel }: PartProps) {
  const { channelShowRawJson, channelConfigJson, setChannelConfigJson, channelFormValues, setChannelFormValues } = props;
  return (
    <>
    <div
      className="admin-panel__section-header"
      style={{ marginBottom: "0.1rem" }}
    >
      <span className="admin-panel__form-label" style={{ margin: 0 }}>
        Configuration
      </span>
      <button
        type="button"
        className="admin-panel__action-btn"
        style={{ fontSize: "var(--ds-text-xs)", padding: "0.2rem 0.6rem" }}
        onClick={() => toggleRawJson(props)}
      >
        {channelShowRawJson ? "Show form" : "Show raw JSON"}
      </button>
    </div>

    {channelShowRawJson ? (
      <textarea
        className="admin-panel__form-input"
        rows={14}
        value={channelConfigJson}
        onChange={(event) => setChannelConfigJson(event.target.value)}
        style={{ fontFamily: "monospace", fontSize: "var(--ds-text-sm)" }}
      />
    ) : (
      <AdminChannelConfigFields
        configFields={channel.config_fields}
        channelConfigJson={channelConfigJson}
        setChannelConfigJson={setChannelConfigJson}
        channelFormValues={channelFormValues}
        setChannelFormValues={setChannelFormValues}
        secretFields={channel.secret_fields}
      />
    )}
    </>
  );
}

function ChannelEnableSwitch({ enabled, setEnabled }: { enabled: boolean; setEnabled: Dispatch<SetStateAction<boolean>> }) {
  return (
  <label className="admin-form-toggle-row">
    <div className="admin-form-toggle-copy">
      <strong>Enable channel</strong>
      <div className="admin-form-help">
        Activate the channel after saving this configuration.
      </div>
    </div>
    <span
      className={`toggle-switch ${enabled ? "toggle-switch--on" : ""}`}
      onClick={() => setEnabled((value) => !value)}
      role="switch"
      aria-checked={enabled}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === " " || event.key === "Enter") {
          setEnabled((value) => !value);
        }
      }}
    />
  </label>
  );
}
