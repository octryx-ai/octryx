import type { MCPCatalogEntry } from "./mcpTypes";
import { mcpCatalogRequirements } from "./mcpCatalogSummary";
import { SidePanel } from "../../layout/SidePanel";
import "./adminMcpCatalog.css";

type AdminMcpCatalogModalProps = {
  open: boolean;
  close: () => void;
  search: string;
  setSearch: (value: string) => void;
  filteredCatalog: MCPCatalogEntry[];
  onSelectPreset: (preset: MCPCatalogEntry) => void;
};

function CatalogRow({
  preset,
  onSelect,
}: {
  preset: MCPCatalogEntry;
  onSelect: () => void;
}) {
  const requirements = mcpCatalogRequirements(preset);
  return (
    <li className="admin-mcp-catalog__row">
      <div className="admin-mcp-catalog__main">
        <div className="admin-mcp-catalog__title">
          <strong>{preset.name}</strong>
          <span className="admin-panel__cell--muted">
            {preset.vendor || "MCP"} · {preset.transport}
          </span>
        </div>
        <p className="admin-mcp-catalog__description">{preset.description}</p>
        <dl className="admin-mcp-catalog__facts">
          <div>
            <dt>Needs</dt>
            <dd>{requirements}</dd>
          </div>
          <div>
            <dt>Installed</dt>
            <dd>
              {preset.installed_count > 0
                ? preset.installed_names.join(", ")
                : "Not installed yet"}
            </dd>
          </div>
        </dl>
        {preset.source_url ? (
          <a
            className="admin-mcp-catalog__source"
            href={preset.source_url}
            target="_blank"
            rel="noreferrer noopener"
          >
            Source ↗
          </a>
        ) : null}
      </div>
      <button
        type="button"
        className="admin-panel__action-btn admin-mcp-catalog__install"
        onClick={onSelect}
      >
        {preset.installed_count > 0 ? "Install another" : "Install"}
      </button>
    </li>
  );
}

export function AdminMcpCatalogModal({
  open,
  close,
  search,
  setSearch,
  filteredCatalog,
  onSelectPreset,
}: AdminMcpCatalogModalProps) {
  if (!open) {
    return null;
  }

  // Choosing a preset happens in the one side panel over the list.
  return (
    <SidePanel title="Install MCP from catalog" subtitle="Catalog" onClose={close} testId="mcp-catalog-panel"
      footer={(
        <button type="button" className="admin-panel__action-btn" onClick={close}>
          Cancel
        </button>
      )}
    >
          <label className="thread-search thread-search--inline">
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <circle cx="9" cy="9" r="5.5" />
              <path d="M13.2 13.2 17 17" />
            </svg>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search MCP catalog"
              aria-label="Search MCP catalog"
            />
          </label>
          {filteredCatalog.length === 0 ? (
            <div className="admin-panel__empty-state">
              No MCP presets match your search.
            </div>
          ) : (
            <ul className="admin-mcp-catalog">
              {filteredCatalog.map((preset) => (
                <CatalogRow
                  key={preset.slug}
                  preset={preset}
                  onSelect={() => onSelectPreset(preset)}
                />
              ))}
            </ul>
          )}
    </SidePanel>
  );
}
