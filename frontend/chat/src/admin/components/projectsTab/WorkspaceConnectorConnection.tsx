import { atlassianAuthSaveFields } from "../connectorsTab/atlassianAuthModel";
import { atlassianAuthView } from "../connectorsTab/atlassianAuthView";
import type { AtlassianProduct } from "../connectorsTab/atlassianAuthModes";
import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import "../connectorsTab/jiraConnectorSetup.css";
import "./workspaceConnection.css";
import { connectionAsConnector, sourceOf } from "./workspaceConnectionModel";
import { workspaceConnectionActions } from "./workspaceConnectionActions";
import { WorkspaceConnectionChoice } from "./WorkspaceConnectionChoice";
import { WorkspaceOwnConnectionForm } from "./WorkspaceOwnConnectionForm";
import { useWorkspaceConnectionState, useWorkspaceConnectionSync, type ConnectionState } from "./useWorkspaceConnection";

type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;

type Props = {
  projectId: string;
  connectorName: string;
  product: AtlassianProduct;
  label: string;
  readJson: ReadJson;
  /** Tells the card whether this Workspace's own connection can serve runtime access. */
  onReadyChange?: (ready: boolean) => void;
};

function LoadErrorLine({ loadError, onRetry }: { loadError: string | null; onRetry: () => void }) {
  return (
    <div
      className="workspace-connection__message"
      role="alert"
      data-testid="workspace-connection-load-error"
    >
      {loadError} Nothing was changed.{" "}
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onRetry}
      >
        Retry
      </button>
    </div>
  );
}

function ConnectionMessage({ message }: { message: { ok: boolean; text: string } }) {
  return (
    <div
      className={
        message.ok
          ? "admin-panel__success"
          : "workspace-connection__message"
      }
      role="status"
      data-testid="workspace-connection-message"
    >
      {message.text}
    </div>
  );
}

// The own connection's sign-in view of the draft, the draft setter, and Save, Test and Use global.
function ownConnectionEditing(s: ConnectionState, { projectId, connectorName, product, label, readJson }: Omit<Props, "onReadyChange">) {
  const { connection, draft, setDraft, setAttempted, setBusy, setMessage, setFocusField, setConfirmingGlobal, setConnection, apply } = s;
  // The shared model reads only tool_name, public_fields and secret_status of a connector.
  const asConnector = connectionAsConnector(
    connectorName,
    connection,
  ) as unknown as AdminConnector;
  const view = atlassianAuthView(product, asConnector, draft);
  const hasErrors = Object.keys(view.errors).length > 0;
  const set = (field: string, value: string) => {
    setDraft((previous) => ({ ...previous, [field]: value }));
    setMessage(null);
  };
  const ownBody = () => ({
    source: sourceOf("own"),
    ...atlassianAuthSaveFields(product, asConnector, draft),
  });
  const { save, test, useGlobal } = workspaceConnectionActions({ projectId, connectorName, product, label, readJson, view,
    hasErrors, ownBody, apply, setBusy, setMessage, setFocusField, setAttempted, setConnection, setConfirmingGlobal });

  return { asConnector, view, hasErrors, set, save, test, useGlobal };
}

// The ready connection: global or own, the own sign-in form with Test and Save, and the last message.
function WorkspaceConnectionReady({ s, projectId, connectorName, product, label, readJson }: Omit<Props, "onReadyChange"> & {
  s: ConnectionState;
}) {
  const { connection, choice, setChoice, draft, attempted, busy, message, setMessage, confirmingGlobal, setConfirmingGlobal } = s;
  const { asConnector, view, hasErrors, set, save, test, useGlobal } = ownConnectionEditing(s, {
    projectId, connectorName, product, label, readJson,
  });
  const storedOwn = connection?.mode === "own";
  return (
    <div
      className="admin-panel__stack admin-panel__stack--compact"
      data-testid="workspace-connection"
    >
      <WorkspaceConnectionChoice
        connectorName={connectorName}
        label={label}
        choice={choice}
        connection={connection}
        storedOwn={storedOwn}
        confirmingGlobal={confirmingGlobal}
        busy={busy}
        onChooseGlobal={() => {
          setMessage(null);
          // A stored own connection is removed only after the confirmation below.
          if (storedOwn) setConfirmingGlobal(true);
          else setChoice("global");
        }}
        onChooseOwn={() => {
          setChoice("own");
          setConfirmingGlobal(false);
          setMessage(null);
        }}
        onUseGlobal={useGlobal}
        onKeepOwn={() => setConfirmingGlobal(false)}
      />

      {choice === "own" ? (
        <WorkspaceOwnConnectionForm
          product={product}
          connection={connection}
          storedOwn={storedOwn}
          asConnector={asConnector}
          draft={draft}
          view={view}
          set={set}
          attempted={attempted}
          hasErrors={hasErrors}
          busy={busy}
          onTest={test}
          onSave={save}
        />
      ) : null}

      {message ? <ConnectionMessage message={message} /> : null}
    </div>
  );
}

// The Workspace's connection for Confluence or Jira: use the global connection, or an own
// connection for this Workspace with the sign-in form, its own Test connection (a typed secret is
// used for the test only) and Save. Switching back to global removes the Workspace's credentials and is
// confirmed first. The access save below (enable + allowlists) never touches any of this.
export function WorkspaceConnectorConnection({
  projectId,
  connectorName,
  product,
  label,
  readJson,
  onReadyChange,
}: Props) {
  const s = useWorkspaceConnectionState();
  useWorkspaceConnectionSync(s, { projectId, connectorName, product, readJson, onReadyChange });
  const { state, loadError, setReload } = s;

  if (state === "loading")
    return <div className="admin-panel__hint">Loading the connection…</div>;
  if (state === "error") {
    return <LoadErrorLine loadError={loadError} onRetry={() => setReload((value) => value + 1)} />;
  }

  return <WorkspaceConnectionReady s={s} projectId={projectId} connectorName={connectorName} product={product} label={label}
    readJson={readJson} />;
}
