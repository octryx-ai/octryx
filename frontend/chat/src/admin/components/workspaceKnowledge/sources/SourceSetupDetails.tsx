import { cursorText } from "../connectorDisplay";
import type { SourceConnector } from "../connectorTypes";
import { ScheduleCell, ScopeCell } from "../KnowledgeConnectorCells";
import { isLocalSnapshot } from "../gitRepositoryScope";

// The setup of one source in its Details: everything the card leaves out — the full scope, products and version, the per-sync limit, the schedule and the listing
// cursor. Read-only; Edit in the ⋯ menu changes it. The panel title names the source, so the tab has no heading of its
// own and no extra indent.
export function SourceSetupDetails({ connector, name }: { connector: SourceConnector; name: string }) {
  return (
    <div data-testid="source-setup" data-source-name={name}>
      <dl className="admin-panel__stack admin-panel__stack--compact" style={{ margin: 0 }}>
        <div>
          <dt className="admin-panel__muted">Reads</dt>
          <dd style={{ margin: 0 }}><ScopeCell connector={connector} /></dd>
        </div>
        {isLocalSnapshot(connector) ? (
          <div>
            <dt className="admin-panel__muted">Fed by</dt>
            <dd style={{ margin: 0 }}>Local snapshot, uploaded by the launcher</dd>
          </div>
        ) : null}
        <div>
          <dt className="admin-panel__muted">Products</dt>
          <dd style={{ margin: 0 }}>
            {connector.products.join(", ") || "All"}
            {connector.version ? <span className="admin-panel__muted"> · version {connector.version}</span> : null}
          </dd>
        </div>
        <div>
          <dt className="admin-panel__muted">Per sync</dt>
          <dd style={{ margin: 0 }}>at most {connector.max_items_per_run} items</dd>
        </div>
        <div>
          <dt className="admin-panel__muted">Schedule</dt>
          <dd style={{ margin: 0 }}><ScheduleCell connector={connector} /></dd>
        </div>
        <div>
          <dt className="admin-panel__muted">Listing</dt>
          <dd style={{ margin: 0 }}>{cursorText(connector.cursor)}</dd>
        </div>
      </dl>
    </div>
  );
}
