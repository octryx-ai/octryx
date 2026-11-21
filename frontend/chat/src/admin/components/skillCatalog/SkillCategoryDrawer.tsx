import { useState } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { createCategory, saveCategory } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { CategoryNode } from "./skillCatalogTypes";
import { resultingKey } from "./skillTabsModel";

// Add or rename a skill category (WP 2.6). Two levels only: a new category sits at the top level or under a
// top-level one, and a short key under a parent is prefixed by the server. The key and the parent never change after
// creation (Workspace assignments store the key), so the rename form shows them read-only.
export function SkillCategoryDrawer({ editing, roots, onClose, onSaved }: {
  /** The category to rename; null adds a new one. */
  editing: CategoryNode | null;
  roots: CategoryNode[];
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [label, setLabel] = useState(editing?.label ?? "");
  const [key, setKey] = useState("");
  const [parentId, setParentId] = useState("");
  const [order, setOrder] = useState(String(editing?.sort_order ?? 0));
  const [description, setDescription] = useState(editing?.description ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const parent = roots.find((node) => node.id === (editing ? editing.parent_id : parentId)) ?? null;
  const parents = roots.filter((node) => !node.archived);
  const finalKey = editing ? editing.key : resultingKey(parent?.key ?? null, key);
  const sortOrder = Number.parseInt(order, 10);

  const save = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const common = { label: label.trim(), description: description.trim(), sort_order: Number.isFinite(sortOrder) ? sortOrder : 0 };
      if (editing) await saveCategory(editing.id, common);
      else await createCategory({ ...common, key: key.trim().toLowerCase(), parent_id: parentId || null });
      await onSaved();
    } catch (error) {
      setProblem(refusalText(error));
      setBusy(false);
    }
  };

  const footer = (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="category-save"
        disabled={busy || !label.trim() || (!editing && !key.trim())} onClick={() => void save()}>{editing ? "Save" : "Add"}</button>
    </>
  );

  return (
    <SettingsDrawer eyebrow="Skills · Categories" title={editing ? "Rename category" : "Add category"} size="detail" onClose={onClose} footer={footer}>
      <div className="admin-panel__stack" data-testid="category-drawer">
        <div className="admin-panel__form-grid">
          <label className="admin-panel__field"><span>Label</span>
            <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Name shown in pickers" data-testid="category-label" autoFocus /></label>
          <label className="admin-panel__field"><span>Key</span>
            {editing ? <input className="skills__mono" value={editing.key} readOnly disabled />
              : <input className="skills__mono" value={key} onChange={(event) => setKey(event.target.value)} placeholder="Lower-case letters, digits, hyphens" data-testid="category-key" />}</label>
          <label className="admin-panel__field"><span>Parent</span>
            {editing ? <input value={parent ? parent.label : "(top level)"} readOnly disabled />
              : (
                <select value={parentId} onChange={(event) => setParentId(event.target.value)} data-testid="category-parent">
                  <option value="">(top level)</option>
                  {parents.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}
                </select>
              )}</label>
          <label className="admin-panel__field"><span>Order</span>
            <input type="number" value={order} onChange={(event) => setOrder(event.target.value)} /></label>
        </div>
        <label className="admin-panel__field"><span>Description (shown in pickers)</span>
          <textarea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What belongs in this category" /></label>
        {!editing && finalKey ? <p className="skills__hint" data-testid="category-final-key">Resulting key: <span className="admin-policy-inline-code">{finalKey}</span></p> : null}
        <p className="skills__hint">The key is stable (it is what Workspace assignments store); the label can be renamed. Two levels only.</p>
        {problem ? <p className="workspace-classification__message" role="alert" data-testid="category-problem">{problem}</p> : null}
      </div>
    </SettingsDrawer>
  );
}
