import { useRef, useState } from "react";

import { flattenCategories, formatSize } from "./skillCatalogModel";
import type { CategoryCatalog } from "./skillCatalogTypes";

// The Upload step of the import drawer (mock `renderImport` upload): one SKILL.md or a .zip with one skill
// folder, the archive limits, and the category and tags the new draft gets.
export function SkillImportUpload({ file, categoryId, tags, categories, onFile, onCategory, onTags }: {
  file: File | null;
  categoryId: string;
  tags: string;
  categories: CategoryCatalog;
  onFile: (file: File | null) => void;
  onCategory: (categoryId: string) => void;
  onTags: (tags: string) => void;
}) {
  const input = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  return (
    <>
      <div className={`admin-panel__empty-state skills__drop${dragging ? " is-active" : ""}`} data-testid="skill-import-drop"
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); onFile(event.dataTransfer.files[0] ?? null); }}>
        {file ? (
          <>Selected <b className="skills__mono">{file.name}</b> ({formatSize(file.size)}) · <button type="button" className="skills__plain"
            onClick={() => input.current?.click()}>choose another file</button></>
        ) : (
          <>Drop a <b>SKILL.md</b> or a <b>.zip</b> with one skill folder here, or <button type="button" className="skills__plain"
            data-testid="skill-import-choose" onClick={() => input.current?.click()}>choose a file</button>.</>
        )}
        <br />
        <span className="skills__hint">Max 5 MB · 200 files · text files only (binaries refused)</span>
        <input ref={input} type="file" accept=".md,.zip" hidden data-testid="skill-import-file"
          onChange={(event) => onFile(event.target.files?.[0] ?? null)} />
      </div>
      <p className="skills__hint">Symbolic links, absolute paths, <span className="skills__mono">..</span> segments and archives with a
        compression ratio above 100 are refused. The upload becomes a draft. The name comes from the frontmatter (or the
        folder); a skill with a known name becomes a new draft version of that skill instead.</p>
      <div className="admin-panel__form-grid">
        <CategorySelect value={categoryId} categories={categories} onChange={onCategory} label="Category" />
        <label className="admin-panel__field">
          <span>Tags</span>
          <input value={tags} placeholder="Comma-separated" data-testid="skill-import-tags" onChange={(event) => onTags(event.target.value)} />
        </label>
      </div>
    </>
  );
}

export function CategorySelect({ value, categories, label, onChange }: {
  value: string;
  categories: CategoryCatalog;
  label: string;
  onChange: (categoryId: string) => void;
}) {
  const options = flattenCategories(categories.categories).filter((node) => !node.archived);
  return (
    <label className="admin-panel__field">
      <span>{label}</span>
      <select value={value} required data-testid="skill-import-category" onChange={(event) => onChange(event.target.value)}>
        <option value="">Choose a category…</option>
        {options.map((node) => <option key={node.id} value={node.id}>{node.fullLabel}</option>)}
      </select>
    </label>
  );
}
