import type { CategoryNode, SkillRow } from "./skillCatalogTypes";
import { countInCategory, rowTags } from "./skillListModel";

// The catalog's left column (mock `renderTree`): All entries, the two-level category tree with the number of entries
// in each subtree, and the tags of the listed entries as a tag filter.
export function SkillCatalogTree({ rows, categories, category, tag, onCategory, onTag }: {
  rows: SkillRow[];
  categories: CategoryNode[];
  category: string;
  tag: string;
  onCategory: (key: string) => void;
  onTag: (tag: string) => void;
}) {
  const tags = rowTags(rows);
  const item = (key: string, label: string, count: number, child = false) => (
    <button key={key || "all"} type="button" data-testid={`skills-tree-${key || "all"}`}
      className={`skills__tree-item${child ? " skills__tree-item--child" : ""}${category === key ? " is-active" : ""}`}
      onClick={() => onCategory(key)}>
      {label}<span className="skills__tree-count">{count}</span>
    </button>
  );
  return (
    <nav className="skills__tree" aria-label="Categories" data-testid="skills-tree">
      <div className="skills__tree-label">Categories</div>
      {item("", "All entries", rows.length)}
      {categories.filter((node) => !node.archived).map((node) => [
        item(node.key, node.label, countInCategory(rows, node.key)),
        ...node.children.filter((child) => !child.archived).map((child) => item(child.key, child.label, countInCategory(rows, child.key), true)),
      ])}
      <div className="skills__tree-label" style={{ marginTop: ".5rem" }}>Tags</div>
      {tags.length ? (
        <div className="policies__row" style={{ flexWrap: "wrap", padding: "0 .4rem" }}>
          {tags.map((value) => (
            <button key={value} type="button" className={`skills__tag${tag === value ? " is-active" : ""}`} style={{ cursor: "pointer" }}
              aria-pressed={tag === value} data-testid={`skills-tag-${value}`} onClick={() => onTag(tag === value ? "" : value)}>#{value}</button>
          ))}
        </div>
      ) : <div className="skills__hint" style={{ padding: "0 .5rem" }}>No tags yet.</div>}
    </nav>
  );
}
