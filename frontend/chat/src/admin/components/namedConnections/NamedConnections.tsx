import { ConnectionPolicies } from "../policyEngine/ConnectionPolicies";
import { NamedConnectionDetails } from "./NamedConnectionDetails";
import { NamedConnectionEditor } from "./NamedConnectionEditor";
import { WorkspaceConnectionsOverview } from "./WorkspaceConnectionsOverview";
import { authModeLabel, connectionTarget, deleteConsequence, storedSecretsText } from "./namedConnectionsText";
import { scopeLabel } from "./namedConnectionsForm";
import type { NamedConnection, NamedConnectionList } from "./namedConnectionsTypes";
import { ConnectorScopeCheck } from "../connectorTest/ConnectorScopeCheck";
import { namedConnectionActions, namedFormView, useNamedConnections, type Message, type NamedConnectionActions, type ReadJson } from "./useNamedConnections";
import "../projectsTab/workspaceConnection.css";
import "./namedConnections.css";

type Props = {
  // A Workspace's named connections, or the global ones (null: Automation → Connectors).
  projectId: string | null;
  // The connector's name; what its form holds comes with the list (the server's descriptor).
  connector: string;
  label: string;
  readJson: ReadJson;
  // A Workspace whose own named connection serves the connector needs no global one (its card says so).
  onReadyChange?: (ready: boolean) => void;
};

// The default connection: the connector settings (global) or the Workspace connection, with its facts.
function DefaultConnectionRow({ list, connector, global }: { list: NamedConnectionList; connector: string; global: boolean }) {
  const descriptor = list.descriptor;
  const scope = scopeLabel(descriptor);
  const defaultTarget = connectionTarget(descriptor, list.defaultFields);
  return (
    <li className="named-connections__row" data-testid="named-connection-default">
      <div className="named-connections__head">
        <strong>Default</strong> · {global ? "the connector settings above" : "the Workspace connection above"}
        {list.defaultActive ? "" : global ? " (not configured)" : " (not enabled for this Workspace)"}
        <span className="named-connections__id ds-sr-only">ID <code>default</code></span>
      </div>
      <ConnectionPolicies connector={connector} />
      {list.defaultConfigured ? (
        <div className="named-connections__facts">
          {[
            defaultTarget ?? "No URL set",
            authModeLabel(descriptor, list.defaultFields),
            `every other ${scope.one} its allowlist allows`,
            storedSecretsText({ secretStatus: list.defaultSecretStatus }),
          ].join(" · ")}
        </div>
      ) : null}
    </li>
  );
}

// One named connection with Edit, Test and Delete (confirmed in place).
function ConnectionRow({ connection, list, connector, busy, confirmDelete, setConfirmDelete, actions }: {
  connection: NamedConnection; list: NamedConnectionList; connector: string; busy: string | null; confirmDelete: string | null;
  setConfirmDelete: (id: string | null) => void; actions: NamedConnectionActions;
}) {
  const descriptor = list.descriptor;
  return (
    <li className="named-connections__row" data-testid="named-connection-row">
      <NamedConnectionDetails connection={connection} connector={descriptor}>
        <ConnectionPolicies connector={connector} connectionId={connection.id} />
        <span className="connector-card__actions">
          <button type="button" className="admin-panel__action-btn" disabled={busy !== null}
            onClick={() => actions.open(connection)}>Edit</button>
          {descriptor.testable ? (
            <button type="button" className="admin-panel__action-btn" disabled={busy !== null}
              onClick={() => actions.test(connection)}>
              {busy === `test:${connection.id}` ? "Testing…" : "Test"}
            </button>
          ) : null}
          <button type="button" className="admin-panel__action-btn" disabled={busy !== null}
            onClick={() => setConfirmDelete(connection.id)}>Delete</button>
        </span>
        {confirmDelete === connection.id ? (
          <span className="workspace-connection__confirm" role="note" data-testid="named-connection-confirm-delete">
            {deleteConsequence(connection, descriptor)}
            <span className="connector-card__actions">
              <button type="button" className="admin-panel__action-btn" disabled={busy !== null}
                onClick={() => actions.remove(connection)}>Delete connection</button>
              <button type="button" className="admin-panel__action-btn" onClick={() => setConfirmDelete(null)}>
                Keep
              </button>
            </span>
          </span>
        ) : null}
      </NamedConnectionDetails>
    </li>
  );
}

function MessageLine({ message }: { message: Message }) {
  if (!message) return null;
  return (
    <div className={message.ok ? "admin-panel__success" : "workspace-connection__message"} role="status"
      data-testid="named-connections-message">
      {message.text}
      {message.scopeCheck ? <ConnectorScopeCheck check={message.scopeCheck} /> : null}
    </div>
  );
}

// A Workspace also sees the global connections, read-only.
function InheritedConnections({ list }: { list: NamedConnectionList }) {
  return (
    <div className="admin-panel__stack admin-panel__stack--compact" data-testid="named-connections-inherited">
      <span className="ds-form-section__title">Global connections (read-only)</span>
      <div className="ds-sr-only">
        Managed in Connector settings. A {scopeLabel(list.descriptor).one} this Workspace binds above overrides them.
      </div>
      <ul className="named-connections__list">
        {list.inherited.map((connection) => (
          <li key={connection.id} className="named-connections__row" data-testid="named-connection-inherited-row">
            <NamedConnectionDetails connection={connection} connector={list.descriptor} inherited />
          </li>
        ))}
      </ul>
    </div>
  );
}

// Named connections of one connector: several accounts, each bound to its keys (spaces, projects, tables,
// clusters, accounts, ...), in a Workspace or globally. One component for every connector type: the binding, the
// fields and the form kind come from the connector's descriptor. A bound key is always read with its connection. Each connection has a server-generated id that never changes. Secrets are write-only: a stored one is
// shown as "stored", never filled in. A Workspace also sees the global connections, read-only.
export function NamedConnections({ projectId, connector, label, readJson, onReadyChange }: Props) {
  const s = useNamedConnections(projectId, connector, readJson, onReadyChange);
  const { list, state, editing, busy } = s;
  const global = projectId === null;

  if (state === "loading") return <div className="admin-panel__hint">Loading named connections…</div>;
  if (state === "error" || !list) {
    return (
      <div className="workspace-connection__message" role="alert" data-testid="named-connections-error">
        Named connections could not be loaded. Nothing was changed.
      </div>
    );
  }

  const v = namedFormView(connector, list, editing);
  const actions = namedConnectionActions({ s, v, projectId, connector, label, readJson });
  const scope = scopeLabel(v.descriptor);
  return (
    <div className="admin-panel__stack admin-panel__stack--compact named-connections" data-testid="named-connections">
      <span className="ds-form-section__title">Named connections</span>
      {/* The rule is read by assistive technology; on screen it is in the page's help. It names the
          bound keys in the plural, so it reads right for every connector ("every other account", never "a account"). */}
      <div className="ds-sr-only">
        A connection serves the {scope.plural.toLowerCase()} bound to it; every other {scope.one} uses the default connection.
        {global ? ` Global connections apply in every Workspace whose ${label} connector is on, unless the Workspace binds the ${scope.one} itself.` : ""}
      </div>
      <ul className="named-connections__list">
        <DefaultConnectionRow list={list} connector={connector} global={global} />
        {list.connections.map((connection) => (
          <ConnectionRow key={connection.id} connection={connection} list={list} connector={connector} busy={busy}
            confirmDelete={s.confirmDelete} setConfirmDelete={s.setConfirmDelete} actions={actions} />
        ))}
      </ul>
      {editing ? (
        <NamedConnectionEditor descriptor={v.descriptor} editing={editing} asConnector={v.asConnector} authView={v.authView}
          snView={v.snView} genericView={v.genericView} problems={v.problems} attempted={s.attempted} busy={busy} setEditing={s.setEditing} set={actions.set}
          onTest={actions.test} onSave={actions.save} onCancel={() => s.setEditing(null)} />
      ) : (
        <div className="connector-card__actions">
          <button type="button" className="admin-panel__action-btn" disabled={busy !== null} onClick={() => actions.open(null)}>
            Add connection
          </button>
        </div>
      )}
      <MessageLine message={s.message} />
      {global ? (
        <WorkspaceConnectionsOverview descriptor={v.descriptor} label={label} connections={list.workspaceConnections} />
      ) : null}
      {!global && list.inherited.length ? <InheritedConnections list={list} /> : null}
    </div>
  );
}
