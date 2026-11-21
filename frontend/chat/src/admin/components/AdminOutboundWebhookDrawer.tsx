import { FormSection } from "../../layout/FormSection";
import { SidePanel } from "../../layout/SidePanel";
import type { ProjectOptionRow, AdminOutboundWebhookRow } from "./webhookTypes";

type Props = {
  show: boolean;
  isEditing: boolean;
  entry: AdminOutboundWebhookRow | null;
  projects: ProjectOptionRow[];
  name: string;
  setName: (v: string) => void;
  url: string;
  setUrl: (v: string) => void;
  projectId: string;
  setProjectId: (v: string) => void;
  eventOptions: readonly string[];
  selectedEvents: string[];
  setSelectedEvents: (v: string[]) => void;
  error: string | null;
  loading: boolean;
  signingSecret: string | null;
  onSave: () => Promise<void> | void;
  onClose: () => void;
};

type TargetProps = Pick<Props, "projects" | "name" | "setName" | "url" | "setUrl" | "projectId" | "setProjectId">;

function OutboundWebhookTargetSection({ projects, name, setName, url, setUrl, projectId, setProjectId }: TargetProps) {
  return (
    <FormSection title="Target">
      <label className="admin-panel__field" htmlFor="obw-name">
        <span>Name *</span>
        <input
          id="obw-name"
          className="admin-panel__input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </label>
      <label className="admin-panel__field" htmlFor="obw-url">
        <span>Target URL *</span>
        <input
          id="obw-url"
          className="admin-panel__input"
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
        />
      </label>
      <label className="admin-panel__field" htmlFor="obw-project">
        <span>Workspace</span>
        <select
          id="obw-project"
          className="admin-panel__input"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
        >
          <option value="">All Workspaces</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
    </FormSection>
  );
}

type EventsProps = Pick<Props, "eventOptions" | "selectedEvents" | "setSelectedEvents">;

function OutboundWebhookEventsSection({ eventOptions, selectedEvents, setSelectedEvents }: EventsProps) {
  const toggleEvent = (eventType: string, checked: boolean) => {
    if (checked) {
      setSelectedEvents([...new Set([...selectedEvents, eventType])]);
    } else {
      setSelectedEvents(selectedEvents.filter((e) => e !== eventType));
    }
  };

  return (
    <FormSection title="Events">
      {eventOptions.map((eventType) => (
        <label key={eventType} className="admin-panel__checkbox">
          <input
            type="checkbox"
            checked={selectedEvents.includes(eventType)}
            onChange={(e) => toggleEvent(eventType, e.target.checked)}
          />
          <code>{eventType}</code>
        </label>
      ))}
    </FormSection>
  );
}

function OutboundWebhookFooter({ isEditing, loading, onClose }: Pick<Props, "isEditing" | "loading" | "onClose">) {
  return (
    <>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onClose}
      >
        Cancel
      </button>
      <button
        type="submit"
        form="outbound-webhook-form"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={loading}
      >
        {loading
          ? "Saving…"
          : isEditing
            ? "Save changes"
            : "Create outbound webhook"}
      </button>
    </>
  );
}

// New and edit of an outbound webhook in the one side panel: labelled fields in sections, Cancel
// and the primary action at the bottom right.
export function AdminOutboundWebhookDrawer(props: Props) {
  const { show, isEditing, entry, error, loading, signingSecret, onSave, onClose } = props;
  if (!show) return null;

  return (
    <SidePanel
      title={isEditing ? `Edit ${entry?.name || "outbound webhook"}` : "New outbound webhook"}
      subtitle="Outbound webhook"
      onClose={onClose}
      testId="outbound-webhook-panel"
      footer={<OutboundWebhookFooter isEditing={isEditing} loading={loading} onClose={onClose} />}
    >
      <form
        id="outbound-webhook-form"
        className="admin-panel__form"
        onSubmit={(e) => {
          e.preventDefault();
          void onSave();
        }}
      >
        <OutboundWebhookTargetSection {...props} />

        <OutboundWebhookEventsSection {...props} />

        {error ? (
          <p className="admin-panel__form-error" role="alert">
            {error}
          </p>
        ) : null}

        {signingSecret ? (
          <FormSection title="Signing secret">
            <p className="admin-panel__hint">Shown once. Save it in the receiving system now.</p>
            <code className="admin-outbound-webhook__secret">{signingSecret}</code>
          </FormSection>
        ) : null}
      </form>
    </SidePanel>
  );
}
