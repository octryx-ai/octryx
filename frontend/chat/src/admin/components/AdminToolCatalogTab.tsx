import { useState } from "react";
import type { AdminToolCatalogEntry } from "../types/adminPanelTypes.usersProviders";
import { AdminDefaultToolSetsSection } from "./AdminDefaultToolSetsSection";
import {
  filterTools,
  POLICY_FILTER_OPTIONS,
  SOURCE_FILTER_OPTIONS,
  toolAvailability,
  toolSourceLabel,
  type ToolPolicyFilter,
  type ToolSourceFilter,
} from "./toolCatalog/toolCatalogModel";
import { AreaPurpose } from "./workflowSurfaces/AreaPurpose";
import "./toolCatalog/toolCatalog.css";

type AdminToolCatalogTabProps = {
  ctx: Record<string, unknown>;
};

const AVAILABILITY_BADGE = {
  core: "admin-panel__badge",
  change: "admin-panel__badge admin-panel__badge--warning",
  plan: "admin-panel__badge admin-panel__badge--secondary",
  discoverable: "admin-panel__badge admin-panel__badge--inactive",
} as const;

/** The search (shared with the connector catalog) and the source and availability filters. */
function ToolCatalogToolbar({ search, onSearch, sourceFilter, setSourceFilter, policyFilter, setPolicyFilter }: {
  search: string;
  onSearch: (value: string) => void;
  sourceFilter: ToolSourceFilter;
  setSourceFilter: (value: ToolSourceFilter) => void;
  policyFilter: ToolPolicyFilter;
  setPolicyFilter: (value: ToolPolicyFilter) => void;
}) {
  return (
    <section className="admin-users__toolbar tool-catalog__toolbar">
      <input
        type="search"
        className="admin-users__toolbar-input"
        value={search}
        onChange={(event) => onSearch(event.target.value)}
        placeholder="Search tools by name, description or connector…"
        aria-label="Search tools"
      />
      <select
        className="admin-users__toolbar-select"
        value={sourceFilter}
        onChange={(event) => setSourceFilter(event.target.value as ToolSourceFilter)}
        aria-label="Filter tool source"
      >
        {SOURCE_FILTER_OPTIONS.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
      <select
        className="admin-users__toolbar-select"
        value={policyFilter}
        onChange={(event) => setPolicyFilter(event.target.value as ToolPolicyFilter)}
        aria-label="Filter tool availability"
      >
        {POLICY_FILTER_OPTIONS.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
    </section>
  );
}

/** One row per tool: name and description, availability badge and source. */
function ToolCatalogTable({ tools }: { tools: AdminToolCatalogEntry[] }) {
  return (
    <div className="admin-panel__table-wrap">
      <table className="admin-panel__table tool-catalog__table">
        <thead>
          <tr>
            <th>Tool</th>
            <th>Availability</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {tools.map((tool) => {
            const availability = toolAvailability(tool);
            return (
              <tr key={tool.name}>
                <td>
                  <code className="tool-catalog__name">{tool.name}</code>
                  <span className="tool-catalog__desc" title={tool.description || undefined}>
                    {tool.description || "No description"}
                  </span>
                </td>
                <td>
                  <span className={AVAILABILITY_BADGE[availability.tone]}>{availability.label}</span>
                </td>
                <td className="admin-panel__cell--muted">{toolSourceLabel(tool)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Tools page: the searchable catalog first; the governed default tool sets below, collapsed.
export function AdminToolCatalogTab({ ctx }: AdminToolCatalogTabProps) {
  const { connectorCatalogSearch, filteredToolCatalog, setConnectorCatalogSearch, toolCatalog } = ctx as Record<
    string,
    any
  >;
  const [sourceFilter, setSourceFilter] = useState<ToolSourceFilter>("all");
  const [policyFilter, setPolicyFilter] = useState<ToolPolicyFilter>("all");
  const allTools = (Array.isArray(toolCatalog) ? toolCatalog : []) as AdminToolCatalogEntry[];
  // The shared search (useAdminCatalogFilters) narrows by name, description and connector.
  const searched = (Array.isArray(filteredToolCatalog) ? filteredToolCatalog : allTools) as AdminToolCatalogEntry[];
  const filtered = filterTools(searched, sourceFilter, policyFilter);
  const coreCount = allTools.filter((tool) => tool.is_core).length;

  return (
    <div className="tool-catalog">
      <AreaPurpose
        links={[
          { tab: "workflowList", label: "Workflows" },
          { tab: "skills", label: "Skills" },
          { tab: "promptCatalog", label: "Tool descriptions (System prompt texts)" },
        ]}
      />
      <div className="admin-panel__section-header">
        <span>
          Tools ({filtered.length}/{allTools.length}) · {coreCount} core · {allTools.length - coreCount} discoverable
        </span>
      </div>
      <ToolCatalogToolbar search={connectorCatalogSearch ?? ""} onSearch={setConnectorCatalogSearch}
        sourceFilter={sourceFilter} setSourceFilter={setSourceFilter} policyFilter={policyFilter} setPolicyFilter={setPolicyFilter} />

      {filtered.length === 0 ? (
        <div className="admin-panel__empty-state">No tools match the current search and filters.</div>
      ) : (
        <ToolCatalogTable tools={filtered} />
      )}

      <AdminDefaultToolSetsSection />
    </div>
  );
}
