import { authModeLabel, connectionTarget } from "./namedConnectionsText";
import { scopeLabel } from "./namedConnectionsForm";
import type { NamedDescriptor, WorkspaceConnection } from "./namedConnectionsTypes";

type Props = {
  descriptor: NamedDescriptor;
  label: string;
  connections: WorkspaceConnection[];
};

// Automation → Connectors: every active Workspace's own connections of this connector, read-only, so no account
// is visible only inside its Workspace. Each is managed under Settings → Workspaces → <Workspace> → Connectors.
export function WorkspaceConnectionsOverview({ descriptor, label, connections }: Props) {
  if (!connections.length) return null;
  const scope = scopeLabel(descriptor);
  return (
    <div className="admin-panel__stack admin-panel__stack--compact" data-testid="named-connections-workspaces">
      <span className="ds-form-section__title">Workspace connections (read-only)</span>
      <div className="ds-sr-only">
        {label} accounts a Workspace holds itself. Managed in the Workspace's settings, Data › Connectors.
      </div>
      <ul className="named-connections__list">
        {connections.map((connection) => (
          <li key={`${connection.workspaceId}:${connection.id}`} className="named-connections__row"
            data-testid="named-connection-workspace-row">
            <div className="named-connections__head">
              <strong>{connection.workspaceName}</strong> ·{" "}
              {connection.id === "default" ? "Workspace default connection" : connection.name}
              {connection.active ? "" : " (not enabled for this Workspace)"}
              <span className="named-connections__id ds-sr-only">ID <code>{connection.id}</code></span>
            </div>
            <div className="named-connections__facts">
              {[
                connectionTarget(descriptor, connection.publicFields) ?? "No URL set",
                authModeLabel(descriptor, connection.publicFields),
                connection.boundScopes.length
                  ? `${scope.plural}: ${connection.boundScopes.join(", ")}`
                  : `No ${scope.plural.toLowerCase()} listed`,
              ].join(" · ")}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
