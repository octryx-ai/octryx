import { useState } from "react";

import { SkillCategoryDrawer } from "./SkillCategoryDrawer";
import { archiveCategory, restoreCategory } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { CategoryCatalog, CategoryNode } from "./skillCatalogTypes";
import { workspacesLabel } from "./skillTabsModel";

type Editing = { node: CategoryNode | null } | null;

// Skills → Categories (WP 2.6, mock `#tab-categories`): the admin-managed two-level tree with each category's
// published skill count, where it is assigned as a whole, rename (label, description, order), archive and restore.
export function SkillCategoriesTab({ categories, onChanged, onOpenCategory }: {
  categories: CategoryCatalog;
  onChanged: () => void | Promise<void>;
  onOpenCategory: (key: string) => void;
}) {
  const [editing, setEditing] = useState<Editing>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const assignedIn = categories.assigned_in ?? {};

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setProblem(null);
    try {
      await action();
      await onChanged();
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
    }
  };

  const row = (node: CategoryNode, child: boolean) => (
    <tr key={node.id} data-testid={`category-row-${node.key}`}>
      <td style={child ? { paddingLeft: "1.8rem" } : undefined}>
        {child ? node.label : <b>{node.label}</b>}
        {node.archived ? <> <span className="work-badge work-badge--neutral">Archived</span></> : null}
        {node.description ? <div className="policies__sub">{node.description}</div> : null}
      </td>
      <td className="skills__mono">{node.key}</td>
      <td>{child ? node.skills : node.total}</td>
      <td className="admin-panel__cell--muted">{workspacesLabel(assignedIn[node.key])}</td>
      <td>
        <div className="policies__row">
          <button type="button" className="admin-panel__action-btn" onClick={() => onOpenCategory(node.key)}>Show skills</button>
          <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setEditing({ node })}>Rename</button>
          {node.archived ? (
            <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid={`category-restore-${node.key}`}
              onClick={() => void act(() => restoreCategory(node.id))}>Restore</button>
          ) : (
            <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid={`category-archive-${node.key}`}
              onClick={() => void act(() => archiveCategory(node.id))}>Archive</button>
          )}
        </div>
      </td>
    </tr>
  );

  return (
    <div data-testid="skills-categories">
      <div className="policies__flex-between" style={{ marginBottom: ".7rem" }}>
        <p className="admin-panel__hint">Categories are an admin-managed tree (two levels). Every skill has exactly one category; free
          tags add cross-cutting labels. Workspaces can assign a whole category: its published skills, including skills published later.</p>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="category-add"
          onClick={() => setEditing({ node: null })}>Add category</button>
      </div>
      {problem ? <p className="workspace-classification__message" role="alert" data-testid="categories-problem">{problem}</p> : null}
      <div className="skills__scroll">
        <table className="admin-panel__table">
          <thead><tr><th>Category</th><th>Key</th><th>Skills</th><th>Assigned as a whole in</th><th /></tr></thead>
          <tbody>
            {categories.categories.length ? categories.categories.flatMap((node) => [row(node, false), ...node.children.map((child) => row(child, true))]) : (
              <tr><td colSpan={5}><div className="admin-panel__empty-state">No categories yet. Add the first one.</div></td></tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="skills__hint" style={{ marginTop: ".6rem" }}>A category with skills cannot be archived; move its skills first.
        Renaming keeps the key, so Workspace assignments stay intact.</p>

      {editing ? (
        <SkillCategoryDrawer editing={editing.node} roots={categories.categories} onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await onChanged(); }} />
      ) : null}
    </div>
  );
}
