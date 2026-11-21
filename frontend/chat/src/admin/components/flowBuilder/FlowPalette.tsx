import { useMemo, useRef, useState, type RefObject } from "react";
import type { FlowNodeCatalogItem, FlowNodeContract, FlowNodeType } from "./flowBuilderTypes";
import {
  buildPaletteGroups,
  defaultOpenGroups,
  filterPaletteGroups,
  isPaletteGroupOpen,
  paletteEntryAccessibleName,
  type FlowAgentOption,
  type PaletteEntry,
} from "./flowPaletteModel";
import { PaletteIcon } from "./FlowPaletteIcons";
import "./flowPalette.css";

type FlowPaletteProps = {
  onAddNode: (
    type: FlowNodeType,
    agentId?: string,
    labelOverride?: string,
    contract?: FlowNodeContract,
    defaultConfig?: Record<string, unknown>,
    catalogItem?: FlowNodeCatalogItem,
  ) => void;
  agents?: FlowAgentOption[];
  nodeContracts?: FlowNodeContract[];
  nodeCatalogItems?: FlowNodeCatalogItem[];
  isCollapsed?: boolean;
  loading?: boolean;
  // Told after the palette opens or closes; the palette takes real space, so the graph refits.
  onCollapsedChange?: (collapsed: boolean) => void;
};

function addEntry(entry: PaletteEntry, onAddNode: FlowPaletteProps["onAddNode"]) {
  if (entry.disabledReason) return;
  if (entry.agentId) {
    onAddNode("agent_step", entry.agentId, entry.label);
    return;
  }
  onAddNode(entry.type, undefined, entry.label, entry.contract, entry.catalogItem?.default_config, entry.catalogItem);
}

export function FlowPalette({
  onAddNode,
  agents = [],
  nodeContracts = [],
  nodeCatalogItems = [],
  isCollapsed = false,
  loading = false,
  onCollapsedChange,
}: FlowPaletteProps) {
  const groups = useMemo(
    () => buildPaletteGroups(nodeCatalogItems, nodeContracts, agents),
    [agents, nodeCatalogItems, nodeContracts],
  );
  const [collapsed, setCollapsedState] = useState(isCollapsed);
  const setCollapsed = (next: boolean) => {
    setCollapsedState(next);
    onCollapsedChange?.(next);
  };
  const [query, setQuery] = useState("");
  const { searchRef, openGroups, toggleGroup } = usePaletteGroupState(groups);
  const visibleGroups = useMemo(() => filterPaletteGroups(groups, query), [groups, query]);
  const matchCount = visibleGroups.reduce((total, group) => total + group.entries.length, 0);

  if (collapsed) {
    return (
      <div className="flow-palette flow-palette--collapsed">
        <button type="button" className="flow-palette__toggle" onClick={() => setCollapsed(false)} title="Add a step"
          aria-label="Open the step palette">
          <PaletteIcon hint="plus" size={16} />
        </button>
      </div>
    );
  }

  return (
    <div className="flow-palette" role="region" aria-label="Step palette">
      <PaletteHeader loading={loading} onClose={() => setCollapsed(true)} />
      <PaletteSearch query={query} setQuery={setQuery} searchRef={searchRef} matchCount={matchCount} />
      <div className="flow-palette__groups">
        {visibleGroups.map((group) => (
          <PaletteGroup key={group.label} group={group} open={isPaletteGroupOpen(group.label, openGroups, query)}
            onToggle={() => toggleGroup(group.label)} onAddNode={onAddNode} />
        ))}
      </div>
    </div>
  );
}

// The groups the user opened or closed (everything else follows the default open set) and the search field's ref.
function usePaletteGroupState(groups: ReturnType<typeof buildPaletteGroups>) {
  const [toggled, setToggled] = useState<Set<string>>(new Set());
  const searchRef = useRef<HTMLInputElement>(null);
  const openGroups = useMemo(() => {
    const open = defaultOpenGroups(groups);
    for (const label of toggled) {
      if (open.has(label)) open.delete(label);
      else open.add(label);
    }
    return open;
  }, [groups, toggled]);
  function toggleGroup(label: string) {
    setToggled((current) => {
      const next = new Set(current);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }
  return { searchRef, openGroups, toggleGroup };
}

function PaletteHeader({ loading, onClose }: { loading: boolean; onClose: () => void }) {
  return (
    <div className="flow-palette__header">
      <span>Add a step</span>
      <span className="flow-palette__header-actions">
        {loading ? (
          <span className="flow-palette__loading-dot" title="Loading agents…" role="status" aria-label="Loading agents" />
        ) : null}
        {/* Closing stays possible while agents load, so the palette never blocks the graph. */}
        <button
          type="button"
          className="flow-palette__collapse-btn"
          onClick={onClose}
          title="Close the step palette"
          aria-label="Close the step palette"
        >
          <PaletteIcon hint="close" size={12} />
        </button>
      </span>
    </div>
  );
}

function PaletteSearch({
  query,
  setQuery,
  searchRef,
  matchCount,
}: {
  query: string;
  setQuery: (query: string) => void;
  searchRef: RefObject<HTMLInputElement>;
  matchCount: number;
}) {
  return (
    <div className="flow-palette__search">
      <label className="flow-palette__search-field">
        <PaletteIcon hint="search" size={13} />
        <input
          ref={searchRef}
          type="search"
          value={query}
          placeholder="Search steps, tools, agents…"
          aria-label="Search steps, tools and agents"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setQuery("");
              searchRef.current?.blur();
            }
          }}
        />
      </label>
      {query.trim() ? (
        <span className="flow-palette__search-count" role="status">
          {matchCount === 0 ? "No step matches" : `${matchCount} match${matchCount === 1 ? "" : "es"}`}
        </span>
      ) : null}
    </div>
  );
}

type PaletteGroupRow = ReturnType<typeof filterPaletteGroups>[number];

function PaletteGroup({
  group,
  open,
  onToggle,
  onAddNode,
}: {
  group: PaletteGroupRow;
  open: boolean;
  onToggle: () => void;
  onAddNode: FlowPaletteProps["onAddNode"];
}) {
  const listId = `flow-palette-group-${group.label.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
  return (
    <div className="flow-palette__group">
      <button
        type="button"
        className="flow-palette__group-header"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={listId}
      >
        <span>{group.label}</span>
        <span className="flow-palette__group-toggle" aria-hidden="true">
          {open ? "▾" : `▸ ${group.entries.length}`}
        </span>
      </button>
      {open ? (
        <div className="flow-palette__items" id={listId}>
          {group.entries.map((entry) => (
            <PaletteItem key={entry.key} entry={entry} onAddNode={onAddNode} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PaletteItem({ entry, onAddNode }: { entry: PaletteEntry; onAddNode: FlowPaletteProps["onAddNode"] }) {
  return (
    <button
      type="button"
      className={entry.disabledReason ? "flow-palette__item flow-palette__item--disabled" : "flow-palette__item"}
      disabled={Boolean(entry.disabledReason)}
      onClick={() => addEntry(entry, onAddNode)}
      aria-label={paletteEntryAccessibleName(entry)}
      title={entry.disabledReason || entry.description || `Add ${entry.label}`}
    >
      <span className="flow-palette__item-icon">
        <PaletteIcon hint={entry.iconHint} fallback={entry.type} />
      </span>
      <span className="flow-palette__item-main">
        <span>{entry.label}</span>
        {entry.disabledReason ? <small>{entry.disabledReason}</small> : entry.meta ? <small>{entry.meta}</small> : null}
      </span>
    </button>
  );
}
