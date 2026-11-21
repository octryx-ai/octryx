import type { SourceConnector } from "./connectorTypes";
import { unlinkedWithCandidates } from "./gitConnectionModel";

// Git repository sources read anonymously although a connection of the Workspace could read them: a private
// repository then fails as "not found". Each one opens its edit form at "Read through connection".
export function UnlinkedRepositoriesNotice({ connectors, onEdit }: {
  connectors: SourceConnector[];
  onEdit: (connector: SourceConnector) => void;
}) {
  const unlinked = unlinkedWithCandidates(connectors);
  if (!unlinked.length) return null;
  return (
    <div className="admin-panel__hint" role="status" data-testid="unlinked-repositories-notice" style={{ margin: 0 }}>
      {unlinked.length === 1 ? "A repository source is" : `${unlinked.length} repository sources are`} read without a
      connection, although a connection of this Workspace can read {unlinked.length === 1 ? "it" : "them"}.
      {" "}A private repository needs a connection with access.
      {unlinked.map((connector) => (
        <span key={connector.connector_key}>
          {" "}
          <button type="button" className="ds-link-button" data-testid="unlinked-repository-edit"
            onClick={() => onEdit(connector)}>Choose a connection for {connector.connector_key} ›</button>
        </span>
      ))}
    </div>
  );
}
