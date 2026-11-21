import { useAdminNavigation } from "../../adminNavigation";

type ConnectorOverviewSectionProps = {
  ctx: Record<string, unknown>;
};

// Connector settings, reached from Connections: a way back, the page's name and its one action.
// No count line: the table says what is there. "Set up connector" adds a built-in connector's setup; new systems are
// added with Add connection on Connections. Since the "Set up connector" is a quiet link inside the
// page, beside its name, not a page-header button competing with Add connection.
export function ConnectorOverviewSection({
  ctx,
}: ConnectorOverviewSectionProps) {
  const {
    availableConnectors,
    setConnectorCatalogSearch,
    setShowAddConnector,
  } = ctx as Record<string, any>;
  const { openAdminTab } = useAdminNavigation();

  return (
    <div className="connector-settings__head">
      <button type="button" className="admin-panel__action-btn" onClick={() => openAdminTab("adminConnections")}
        data-testid="connector-settings-back">
        ← Connections
      </button>
      <h3 className="connector-settings__title">Connector settings</h3>
      <button
        type="button"
        className="ds-link-button connector-settings__setup"
        onClick={() => {
          setConnectorCatalogSearch("");
          setShowAddConnector(true);
        }}
        disabled={availableConnectors.length === 0}
        title={availableConnectors.length === 0 ? "Every built-in connector is set up." : "Set up a built-in connector from the catalog"}
        data-testid="connector-add"
      >
        Set up a built-in connector
      </button>
    </div>
  );
}
