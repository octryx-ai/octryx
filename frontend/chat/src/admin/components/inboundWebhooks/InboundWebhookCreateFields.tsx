// Parts of the inbound webhook create form: footer buttons, target fields and the timestamp choice.
import { InboundSourceChoice } from "./InboundSourceChoice";
import {
  cannotSignTimestamp,
  timestampFixedReason,
  NEW_ACTION,
  pollQueryLabel,
  type InboundSource,
} from "./inboundWebhookModel";
import type { InboundWebhookCreateState } from "./useInboundWebhookCreate";

type FormProps = { form: InboundWebhookCreateState };

export function InboundCreateFooter({
  form,
  onClose,
  onOpen,
}: FormProps & { onClose: () => void; onOpen: (webhookId: string) => void }) {
  const { created, busy, name, projectId, create } = form;
  return created ? (
    <>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onClose}
      >
        Done
      </button>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={() => onOpen(created.id)}
      >
        Send a test alert
      </button>
    </>
  ) : (
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
        disabled={busy || !name.trim() || !projectId}
        onClick={() => void create()}
      >
        {busy ? "Creating…" : "Create webhook"}
      </button>
    </>
  );
}

export function InboundCreateForm({
  form,
  sources,
  projects,
  onClose,
}: FormProps & { sources: InboundSource[]; projects: { id: string; name: string }[]; onClose: () => void }) {
  const { source, setSource, setUntimestamped, polled, pollQuery, setPollQuery } = form;
  return (
    <div className="admin-panel__form">
      <InboundSourceChoice
        sources={sources}
        source={source}
        onPick={(key) => {
          setSource(key);
          setUntimestamped(cannotSignTimestamp(key));
        }}
      />
      {polled ? (
        <label className="admin-panel__field">
          <span>{pollQueryLabel(source)}</span>
          <input
            className="admin-panel__input"
            value={pollQuery}
            onChange={(event) => setPollQuery(event.target.value)}
          />
          <small className="automation-muted">
            Only items that changed since the last check are read.
          </small>
        </label>
      ) : null}
      <InboundNameAndWorkspace form={form} projects={projects} />
      <InboundStartField form={form} onClose={onClose} />
      <InboundResultField form={form} />
      <InboundTimestampAndNotes form={form} />
    </div>
  );
}

function InboundNameAndWorkspace({ form, projects }: FormProps & { projects: { id: string; name: string }[] }) {
  const { name, setName, projectId, setProjectId, setTaskId } = form;
  return (
    <>
      <label className="admin-panel__field">
        <span>Name</span>
        <input
          className="admin-panel__input"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="admin-panel__field">
        <span>Workspace</span>
        <select
          className="admin-panel__input"
          value={projectId}
          onChange={(event) => {
            setProjectId(event.target.value);
            setTaskId("");
          }}
        >
          <option value="">Choose a Workspace</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}

function InboundStartField({ form, onClose }: FormProps & { onClose: () => void }) {
  const { taskId, setTaskId, projectId, openAdminTab, workspaceActions } = form;
  return (
    <label className="admin-panel__field">
      <span>Start</span>
      <select
        className="admin-panel__input"
        value={taskId}
        disabled={!projectId}
        onChange={(event) => {
          if (event.target.value === NEW_ACTION) {
            onClose();
            openAdminTab("tasks");
            return;
          }
          setTaskId(event.target.value);
        }}
      >
        <option value="">
          {projectId ? "Choose an action" : "Choose a Workspace first"}
        </option>
        {workspaceActions.map((action) => (
          <option key={action.id} value={action.id}>
            {action.name}
          </option>
        ))}
        <option value={NEW_ACTION}>New action…</option>
      </select>
      <small className="automation-muted">
        An action is a workflow plus instructions. "New action…" opens
        Actions; come back to pick it.
      </small>
    </label>
  );
}

function InboundResultField({ form }: FormProps) {
  const { resultTo, setResultTo, taskId, workspaceChannels } = form;
  return (
    <label className="admin-panel__field">
      <span>Send the result to</span>
      <select
        className="admin-panel__input"
        value={resultTo}
        disabled={!taskId}
        onChange={(event) => setResultTo(event.target.value)}
      >
        <option value="keep">Where the action already sends it</option>
        <option value="">Run history only</option>
        {workspaceChannels.map((channel) => (
          <option key={channel.id} value={String(channel.id)}>
            {channel.name}
          </option>
        ))}
      </select>
      <small className="automation-muted">
        This is the action's own destination, so it applies wherever the
        action runs.
      </small>
    </label>
  );
}

function InboundTimestampAndNotes({ form }: FormProps) {
  const { polled, untimestamped, setUntimestamped, source, error } = form;
  return (
    <>
      {!polled ? (
        <label className="admin-panel__checkbox">
          <input
            type="checkbox"
            checked={untimestamped || Boolean(timestampFixedReason(source))}
            disabled={Boolean(timestampFixedReason(source))}
            title={timestampFixedReason(source) || undefined}
            onChange={(event) => setUntimestamped(event.target.checked)}
          />
          <span>
            The sending tool can't sign a timestamp (accept the secret
            alone; repeats of the same call within 5 minutes are still
            refused)
          </span>
        </label>
      ) : null}
      {!polled && timestampFixedReason(source) ? (
        <small className="automation-muted" data-testid="webhook-timestamp-fixed">
          {timestampFixedReason(source)}
        </small>
      ) : null}
      <p className="automation-muted">
        Safe defaults: critical and warning alerts only, repeats grouped
        within 30 min, at most 20 analyses per hour. Change them after
        creating.
      </p>
      {error ? (
        <p className="automation-tone--error" role="alert">
          {error}
        </p>
      ) : null}
    </>
  );
}
