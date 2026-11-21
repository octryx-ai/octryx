import { useState } from "react";

import { KindBadge, SurfaceBadges, TrustBadge } from "./SkillBadges";
import { SkillCatalogTree } from "./SkillCatalogTree";
import type { DetailTab } from "./useSkillDetail";
import { SURFACE_LABELS } from "./skillCatalogTypes";
import { categoryLabels, shortCommit, stateBadge, trustLabel, versionLine, STATE_LABELS } from "./skillCatalogModel";
import type { CategoryCatalog, SkillList, SkillRow, Surface } from "./skillCatalogTypes";
import { EMPTY_FILTERS, SOURCE_OPTIONS, STATUS_OPTIONS, cutText, filterRows, isRetired } from "./skillListModel";
import type { ListFilters, SourceFilter, StatusFilter, SurfaceFilter } from "./skillListModel";

// The Catalog tab (mock `#tab-catalog`, `renderTree`, `renderRows`): one update bar per entry with an upstream
// update, the category tree with tags, the toolbar filters with active-filter chips, and the entries table. Filtering
// is client-side over the loaded list; the category filter is owned by the page so other tabs can open a category.
export function SkillCatalogList({ list, categories, categoryFilter, onCategoryFilter, onOpen, onNew, onImport, onReviewUpdate }: {
  list: SkillList;
  categories: CategoryCatalog;
  categoryFilter: string;
  onCategoryFilter: (key: string) => void;
  onOpen: (skillId: string, sub?: DetailTab) => void;
  onNew: () => void;
  onImport: () => void;
  onReviewUpdate: (skillId: string) => void;
}) {
  const [filters, setFilters] = useState<Omit<ListFilters, "category">>(EMPTY_FILTERS);
  const set = (patch: Partial<ListFilters>) => setFilters((current) => ({ ...current, ...patch }));
  const labels = categoryLabels(categories.categories);
  const rows = filterRows(list.items, { ...filters, category: categoryFilter });
  const updates = list.items.filter((row) => row.update_available);
  const chips = [
    categoryFilter ? { label: `Category: ${labels[categoryFilter] ?? categoryFilter}`, clear: () => onCategoryFilter("") } : null,
    filters.tag ? { label: `#${filters.tag}`, clear: () => set({ tag: "" }) } : null,
  ].filter((chip): chip is { label: string; clear: () => void } => chip !== null);

  return (
    <div data-testid="skills-catalog">
      {updates.map((row) => <UpdateBar key={row.id} row={row} onOpen={onOpen} onReviewUpdate={onReviewUpdate} />)}
      <div className="skills__catalog">
        <SkillCatalogTree rows={list.items} categories={categories.categories} category={categoryFilter} tag={filters.tag}
          onCategory={onCategoryFilter} onTag={(tag) => set({ tag })} />
        <div style={{ minWidth: 0 }}>
          <div className="policies__toolbar">
            <input className="admin-users__toolbar-input" placeholder="Search name, description, tag…" aria-label="Search the catalog"
              value={filters.query} data-testid="skills-search" onChange={(event) => set({ query: event.target.value })} />
            <select className="admin-users__toolbar-select" aria-label="Status" value={filters.status} data-testid="skills-filter-status"
              onChange={(event) => set({ status: event.target.value as StatusFilter })}>
              {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <select className="admin-users__toolbar-select" aria-label="Available in" value={filters.surface} data-testid="skills-filter-surface"
              onChange={(event) => set({ surface: event.target.value as SurfaceFilter })}>
              <option value="">Available anywhere</option>
              {(Object.keys(SURFACE_LABELS) as Surface[]).map((surface) => <option key={surface} value={surface}>{SURFACE_LABELS[surface]}</option>)}
            </select>
            <select className="admin-users__toolbar-select" aria-label="Source" value={filters.source} data-testid="skills-filter-source"
              onChange={(event) => set({ source: event.target.value as SourceFilter })}>
              {SOURCE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
            <button type="button" className="admin-panel__action-btn" data-testid="skills-new" onClick={onNew}>New skill</button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skills-import" onClick={onImport}>Import skill</button>
          </div>
          {chips.length ? (
            <div className="policies__row" style={{ marginBottom: ".5rem" }} data-testid="skills-active-filters">
              {chips.map((chip) => (
                <span key={chip.label} className="admin-policy-chip">{chip.label}
                  <button type="button" className="policies__chip-clear" aria-label={`Clear ${chip.label}`} onClick={chip.clear}>✕</button></span>
              ))}
            </div>
          ) : null}
          <div className="skills__scroll">
            <table className="admin-panel__table" data-testid="skills-table">
              <thead><tr><th scope="col">Skill / entry</th><th scope="col">Category</th><th scope="col">Version</th><th scope="col">Available in</th><th scope="col">Source</th><th scope="col">Workspaces</th><th scope="col">Uses</th></tr></thead>
              <tbody>
                {rows.map((row) => <CatalogRow key={row.id} row={row} onOpen={onOpen} onReviewUpdate={onReviewUpdate} />)}
                {rows.length ? null : (
                  <tr><td colSpan={7}><div className="admin-panel__empty-state" data-testid="skills-empty">No entry matches. Clear the filters or import one.</div></td></tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="skills__hint" style={{ marginTop: ".6rem" }}>
            A skill is published instructions (and optional reference files) that an agent loads when a task matches. Entries
            marked <span className="skills__kind">MCP server</span> come from plugins that bring a server instead of a skill; whether
            one may run is decided by the Workspace MCP policy. Neither grants permissions: every tool a skill needs is still decided
            by the Workspace&apos;s tool policy and the platform policies.
          </p>
        </div>
      </div>
    </div>
  );
}

function CatalogRow({ row, onOpen, onReviewUpdate }: { row: SkillRow; onOpen: (skillId: string) => void; onReviewUpdate: (skillId: string) => void }) {
  const path = row.category?.path ?? [];
  const states = [row.published?.state, row.open?.state].filter((state): state is NonNullable<typeof state> => Boolean(state));
  return (
    <tr className={`policies__table-row${isRetired(row) ? " admin-panel__row--inactive" : ""}`} data-testid="skills-row" onClick={() => onOpen(row.id)}>
      <td>
        <div className="policies__name skills__mono">{row.name} <KindBadge kind={row.kind} /></div>
        <div className="policies__sub" title={row.description}>{cutText(row.description)}</div>
        {row.tags.length ? <div className="policies__row" style={{ marginTop: ".25rem", flexWrap: "wrap" }}>{row.tags.map((tag) => <span key={tag} className="skills__tag">#{tag}</span>)}</div> : null}
      </td>
      <td className="skills__cat">
        {path.length > 1 ? <>{path.slice(0, -1).join(" / ")} / <b>{path[path.length - 1]}</b></> : path.length ? <b>{path[0]}</b> : <span className="admin-panel__cell--muted">—</span>}
      </td>
      <td>
        <div className="policies__row" style={{ flexWrap: "wrap" }}>
          <span className="skills__mono">{versionLine(row)}</span>
          {states.length ? states.map((state) => <span key={state} className={stateBadge(state)}>{STATE_LABELS[state]}</span>)
            : <span className={stateBadge("retired")}>Retired</span>}
        </div>
      </td>
      <td>
        <SurfaceBadges available={row.available} />
        {row.kind === "mcp_server" ? <div className="policies__sub">only where the MCP policy allows it</div> : null}
      </td>
      <td>
        <div className="policies__src">{row.source?.label ?? "Written here"}</div>
        {row.source ? <div className="skills__trust"><TrustBadge source={row.source} /></div> : null}
        {row.update_available ? (
          <button type="button" className="work-badge work-badge--attention" style={{ marginTop: ".2rem", cursor: "pointer", border: 0 }}
            data-testid="skills-row-update" onClick={(event) => { event.stopPropagation(); onReviewUpdate(row.id); }}>Update available</button>
        ) : null}
      </td>
      <td>{row.workspaces || <span className="admin-panel__cell--muted">—</span>}</td>
      <td>{row.uses || <span className="admin-panel__cell--muted">—</span>}</td>
    </tr>
  );
}

function UpdateBar({ row, onOpen, onReviewUpdate }: {
  row: SkillRow;
  onOpen: (skillId: string, sub?: DetailTab) => void;
  onReviewUpdate: (skillId: string) => void;
}) {
  const status = row.upstream_status;
  const notes = [status?.checked_at ? `checked ${status.checked_at.slice(0, 10)}` : "", status?.path_moved ? "skill folder moved" : ""].filter(Boolean);
  return (
    <div className="skills__bar" data-testid={`skills-update-bar-${row.name}`}>
      <span>
        <strong>Update available:</strong> <span className="skills__mono">{row.name}</span>{" "}
        {row.source ? <span className={`work-badge ${row.source.trust === "official" ? "work-badge--running" : "work-badge--neutral"}`}>{trustLabel(row.source)} · {row.source.label}</span> : null}
        {" "}— upstream <span className="skills__mono">{shortCommit(status?.current_commit)} → {shortCommit(status?.latest_commit)}</span>
        {notes.length ? ` (${notes.join(", ")})` : ""}.
        {row.published ? ` Your published v${row.published.version} stays live until the update is reviewed.` : ""}
      </span>
      <span className="policies__row">
        <button type="button" className="admin-panel__action-btn" onClick={() => onOpen(row.id, "versions")}>Versions</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skills-update-review"
          onClick={() => onReviewUpdate(row.id)}>Review update ▸</button>
      </span>
    </div>
  );
}
