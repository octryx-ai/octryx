import { useState } from "react";
import type { ReactNode } from "react";

import { AdminHeaderActions } from "../AdminHeaderSlot";
import { PolicySentence } from "./PolicySentence";
import { formatExactTime, formatRecent } from "../../utils/dateTime";
import { SOURCE_LABELS, effectOf, filterPolicies, policyStatus } from "./policyCatalogModel";
import type { ListFilters, PickerEntities, PolicyItem, PolicyView } from "./policyCatalogModel";

export type MenuEntry = { label: string; onSelect: () => void; disabled?: boolean };

const STATUS_OPTIONS = [["published", "Published"], ["draft", "Draft"], ["in_review", "In review"]];

function RowMenu({ entries }: { entries: MenuEntry[] }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="policies__menu-shell" onClick={(event) => event.stopPropagation()}>
      <button type="button" className="admin-users__row-btn" title="More" aria-haspopup="menu" aria-expanded={open}
        data-testid="policy-row-menu" onClick={() => setOpen(!open)}>⋯</button>
      {open ? (
        <span className="policies__menu" role="menu" onMouseLeave={() => setOpen(false)}>
          {entries.map((entry) => (
            <button key={entry.label} type="button" role="menuitem" disabled={entry.disabled}
              onClick={() => { setOpen(false); entry.onSelect(); }}>{entry.label}</button>
          ))}
        </span>
      ) : null}
    </span>
  );
}

type PolicyListProps = {
  view: PolicyView;
  filters: ListFilters;
  onFilters: (next: ListFilters) => void;
  entities: PickerEntities;
  groups: string[];
  loadingGenerated: boolean;
  onOpen: (item: PolicyItem) => void;
  menuFor: (item: PolicyItem) => MenuEntry[];
  onNew: () => void;
  onTemplates: (() => void) | null;
  empty: ReactNode;
  newDisabled?: boolean;
};

// The policy table: name and @id, effect, the who · what · where sentence, scope, status against
// the published version, source, author and last change. Generated baseline rows are read-only and open where they
// are edited. Filters: search, action group, status, Workspace, and the connection/connector of a deep link.
export function PolicyList({ view, filters, onFilters, entities, groups, loadingGenerated, onOpen, menuFor, onNew, onTemplates, empty, newDisabled = false }: PolicyListProps) {
  const state = view.version?.state ?? null;
  const set = (patch: Partial<ListFilters>) => onFilters({ ...filters, ...patch });
  const rows = filterPolicies(view.items, filters, state, entities.namedConnections);
  const generated = filters.showGenerated ? filterPolicies(view.generated ?? [], { ...filters, status: "", workspace: "", connection: "", connector: "" }, null) : [];
  const connectionName = (id: string) => entities.namedConnections.find((item) => item.id === id)?.name ?? (id === "default" ? "default" : `unknown connection ${id}`);
  const chips: { label: string; clear: Partial<ListFilters> }[] = [];
  if (filters.workspace) chips.push({ label: `Workspace: ${entities.workspaces.find((item) => item.id === filters.workspace)?.name ?? filters.workspace}`, clear: { workspace: "" } });
  if (filters.connection) chips.push({ label: `Connection: ${connectionName(filters.connection)}`, clear: { connection: "" } });
  if (filters.connector) chips.push({ label: `Connector: ${entities.connectorFamilies.find((item) => item.id === filters.connector)?.label ?? filters.connector}`, clear: { connector: "" } });

  return (
    <div data-testid="policy-list">
      <PolicyToolbar filters={filters} groups={groups} workspaces={entities.workspaces} set={set} />
      {/* The page's actions sit in the page header like on every other page, so the open help panel
          never covers them; the header wraps when it is narrow. */}
      <AdminHeaderActions>
        {onTemplates ? <button type="button" className="admin-panel__action-btn" data-testid="policy-from-template" onClick={onTemplates}>From template</button> : null}
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="policy-new" disabled={newDisabled}
          title={newDisabled ? "The draft is in review and frozen." : undefined} onClick={onNew}>New policy</button>
      </AdminHeaderActions>
      {chips.length ? (
        <div className="policies__row policies__filters" data-testid="policy-active-filters">
          {chips.map((chip) => (
            <span key={chip.label} className="admin-policy-chip">{chip.label}
              <button type="button" className="policies__chip-clear" aria-label={`Clear ${chip.label}`} onClick={() => set(chip.clear)}>✕</button></span>
          ))}
        </div>
      ) : null}
      {/* Every column fits the page at 1280 and 1440 (fixed layout, long names cut with a tooltip,
          the source beside the @id, the author under the time). With the help open the frame narrows and the
          low-priority columns step back (container queries in policiesPage.css) instead of a sideways scroll. */}
      <div className="policies__table-wrap" data-testid="policy-table-frame">
      <table className="admin-panel__table policies__table" data-testid="policy-table">
        <thead><tr>
          <th scope="col" className="policies__col-name">Name</th>
          <th scope="col" className="policies__col-effect">Effect</th>
          <th scope="col" className="policies__col-sentence">Who · What · Where</th>
          <th scope="col" className="policies__col-scope">Scope</th>
          <th scope="col" className="policies__col-status">Status</th>
          <th scope="col" className="policies__col-updated">Updated</th>
          <th scope="col" className="policies__col-menu"><span className="classification-policy__sr">Actions</span></th>
        </tr></thead>
        <tbody>
          {rows.map((item) => <PolicyRow key={item.id} item={item} state={state} menu={menuFor(item)} onOpen={onOpen} />)}
          {generated.map((item) => <GeneratedRow key={`generated-${item.id}`} item={item} onOpen={onOpen} />)}
          {loadingGenerated ? <tr><td colSpan={7} className="admin-panel__cell--muted">Loading the generated baseline…</td></tr> : null}
          {!rows.length && !generated.length && !loadingGenerated ? (
            <tr><td colSpan={7}>{view.items.length ? <div className="admin-panel__empty-state" data-testid="policy-empty-filtered">No policies match. Clear the filters or start from a template.</div> : empty}</td></tr>
          ) : null}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function PolicyToolbar({ filters, groups, workspaces, set }: {
  filters: ListFilters;
  groups: string[];
  workspaces: PickerEntities["workspaces"];
  set: (patch: Partial<ListFilters>) => void;
}) {
  return (
    <div className="policies__toolbar">
      <input className="admin-users__toolbar-input" placeholder="Search name, description, @id, Workspace, connection, tool …"
        value={filters.query} data-testid="policy-search" onChange={(event) => set({ query: event.target.value })} />
      <select className="admin-users__toolbar-select" value={filters.group} data-testid="policy-filter-group" onChange={(event) => set({ group: event.target.value })}>
        <option value="">All actions</option>
        {groups.map((group) => <option key={group} value={group}>{group}</option>)}
      </select>
      <select className="admin-users__toolbar-select" value={filters.status} data-testid="policy-filter-status" onChange={(event) => set({ status: event.target.value })}>
        <option value="">Any status</option>
        {STATUS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <select className="admin-users__toolbar-select" value={filters.workspace} data-testid="policy-filter-workspace" onChange={(event) => set({ workspace: event.target.value })}>
        <option value="">All Workspaces</option>
        {workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
      <label className="policies__row policies__src">
        <input type="checkbox" checked={filters.showGenerated} data-testid="policy-show-generated" onChange={(event) => set({ showGenerated: event.target.checked })} />
        Show generated baseline
      </label>
    </div>
  );
}

function PolicyRow({ item, state, menu, onOpen }: { item: PolicyItem; state: string | null; menu: MenuEntry[]; onOpen: (item: PolicyItem) => void }) {
  const status = policyStatus(item, state);
  const source = SOURCE_LABELS[item.source] ?? item.source;
  return (
    <tr className={`policies__table-row${item.change === "removed" ? " admin-panel__row--inactive" : ""}`} data-testid="policy-row" onClick={() => onOpen(item)}>
      <td className="policies__col-name">
        <div className="policies__name" title={item.description ? `${item.name} — ${item.description}` : item.name}>{item.name}</div>
        <div className="policies__sub" title={`${source} · ${item.id}`}><span className="policies__src">{source}</span> · <span className="admin-policy-inline-code">{item.id}</span></div>
      </td>
      <td className="policies__col-effect"><span className={`work-badge work-badge--${effectOf(item).tone}`} data-testid="policy-row-effect">{effectOf(item).label}</span></td>
      <td className="policies__col-sentence policies__summary">
        <PolicySentence segments={item.sentence} className="policies__summary" />
        {item.warnings.length ? <> <span className="work-badge work-badge--attention" title={item.warnings.map((warning) => warning.message).join(" ")} data-testid="policy-row-warning">!</span></> : null}
      </td>
      <td className="policies__col-scope admin-panel__cell--muted" title={item.scope}>{item.scope}</td>
      <td className="policies__col-status"><span className={`work-badge work-badge--${status.tone}`} data-testid="policy-row-status">{status.label}</span></td>
      <td className="policies__col-updated admin-panel__cell--muted">
        <div title={item.lastChanged?.at ? formatExactTime(item.lastChanged.at) : undefined}>{formatRecent(item.lastChanged?.at)}</div>
        {item.lastChanged?.byName ? <div className="policies__sub" title={item.lastChanged.byName}>{item.lastChanged.byName}</div> : null}
      </td>
      <td className="policies__col-menu"><RowMenu entries={menu} /></td>
    </tr>
  );
}

function GeneratedRow({ item, onOpen }: { item: PolicyItem; onOpen: (item: PolicyItem) => void }) {
  return (
    <tr className="policies__table-row admin-panel__row--inactive" data-testid="policy-generated-row" onClick={() => onOpen(item)}>
      <td className="policies__col-name">
        <div className="policies__name policies__name--generated" title={item.id}>{item.id}</div>
        <div className="policies__sub"><span className="policies__src">{SOURCE_LABELS[item.source] ?? item.source} ↗</span> · read-only · generated</div>
      </td>
      <td className="policies__col-effect"><span className={`work-badge work-badge--${effectOf(item).tone}`}>{effectOf(item).label}</span></td>
      <td className="policies__col-sentence policies__summary"><PolicySentence segments={item.sentence} className="policies__summary" /></td>
      <td className="policies__col-scope admin-panel__cell--muted" title={item.scope}>{item.scope}</td>
      <td className="policies__col-status"><span className="work-badge work-badge--neutral">Generated</span></td>
      <td className="policies__col-updated admin-panel__cell--muted">live</td>
      <td className="policies__col-menu" />
    </tr>
  );
}
