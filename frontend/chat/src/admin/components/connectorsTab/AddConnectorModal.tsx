import type { ReactNode } from "react";
import { SidePanel } from "../../../layout/SidePanel";
import {
  connectorCredentialSummary,
  connectorToolCount,
  sortConnectorCatalog,
} from "./connectorCatalog";

type AddConnectorModalProps = {
  ctx: Record<string, unknown>;
};

type ConnectorTemplate = {
  tool_name: string;
  label: string;
  description: string;
  secret_fields?: string[];
  tools: unknown[];
};

/** The catalog cards, sorted; choosing one closes the panel and opens the connector's setup. */
function ConnectorCatalogOptions({ connectors, colors, icons, onChoose }: {
  connectors: ConnectorTemplate[];
  colors: Record<string, string>;
  icons: Record<string, ReactNode>;
  onChoose: (connector: ConnectorTemplate) => void;
}) {
  return (
    <div className="admin-option-list">
      {sortConnectorCatalog(
        connectors,
      ).map((connector) => {
          const iconColor =
            colors[connector.tool_name] || "#6B7280";
          return (
            <button
              key={connector.tool_name}
              type="button"
              className="admin-option-card"
              onClick={() => onChoose(connector)}
            >
              <div
                className="admin-option-card__icon"
                style={{ color: iconColor }}
              >
                {icons[connector.tool_name] ?? (
                  <span className="connector-card__icon-fallback">
                    {connector.label[0]}
                  </span>
                )}
              </div>
              <div className="admin-option-card__body">
                <div className="admin-option-card__title">
                  {connector.label}
                </div>
                <div className="admin-option-card__desc">
                  {connector.description}
                </div>
                <div className="admin-option-card__desc">
                  {connectorCredentialSummary(connector)} ·{" "}
                  {connectorToolCount(connector)}
                </div>
              </div>
            </button>
          );
        })}
    </div>
  );
}

/** The search over the connectors not yet configured. */
function ConnectorCatalogSearch({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="thread-search thread-search--inline">
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <circle cx="9" cy="9" r="5.5" />
        <path d="M13.2 13.2 17 17" />
      </svg>
      <input
        type="search"
        value={value}
        onChange={(e) =>
          onChange(e.target.value)
        }
        placeholder="Search connectors"
        aria-label="Search connectors"
      />
    </label>
  );
}

/** Everything configured already, or the search with the matching catalog cards. */
function AddConnectorBody({ available, search, setSearch, filtered, colors, icons, onChoose }: {
  available: number;
  search: string;
  setSearch: (value: string) => void;
  filtered: ConnectorTemplate[];
  colors: Record<string, string>;
  icons: Record<string, ReactNode>;
  onChoose: (connector: ConnectorTemplate) => void;
}) {
  return available === 0 ? (
    <div className="admin-panel__empty-state">
      All available connectors are already configured.
    </div>
  ) : (
    <>
      <ConnectorCatalogSearch
        value={search}
        onChange={setSearch}
      />
      {filtered.length === 0 ? (
        <div className="admin-panel__empty-state">
          No connectors match your search.
        </div>
      ) : (
        <ConnectorCatalogOptions
          connectors={filtered}
          colors={colors}
          icons={icons}
          onChoose={onChoose}
        />
      )}
    </>
  );
}

export function AddConnectorModal({ ctx }: AddConnectorModalProps) {
  const {
    CONNECTOR_COLORS,
    CONNECTOR_ICONS,
    availableConnectors,
    connectorCatalogSearch,
    filteredAvailableConnectors,
    handleExpandConnector,
    setConnectorCatalogSearch,
    setShowAddConnector,
    showAddConnector,
  } = ctx as Record<string, any>;

  return (
    <>
      {showAddConnector && (
        <SidePanel
          title="Add connector"
          onClose={() => setShowAddConnector(false)}
          testId="connector-add-panel"
          footer={(
            <button
              type="button"
              className="admin-panel__action-btn"
              onClick={() => setShowAddConnector(false)}
            >
              Cancel
            </button>
          )}
        >
          <AddConnectorBody available={availableConnectors.length} search={connectorCatalogSearch} setSearch={setConnectorCatalogSearch}
            filtered={filteredAvailableConnectors as ConnectorTemplate[]} colors={CONNECTOR_COLORS} icons={CONNECTOR_ICONS}
            onChoose={(connector) => {
              setShowAddConnector(false);
              setConnectorCatalogSearch("");
              handleExpandConnector(
                connector.tool_name,
                connector,
              );
            }} />
        </SidePanel>
      )}
    </>
  );
}
