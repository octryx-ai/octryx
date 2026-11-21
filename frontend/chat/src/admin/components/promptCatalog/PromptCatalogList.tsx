import { useMemo } from "react";
import { groupPromptItems, searchPromptItems } from "./promptCatalogSearch";
import { isOverridden, subGroupsOf } from "./promptCatalogModel";
import type { PromptListItem } from "./promptCatalogTypes";

type Props = { items: PromptListItem[]; query: string; onOpen: (key: string) => void };

// Every key is reviewed; the risk only says how much a change can break.
export function RiskBadge({ risk }: { risk: string }) {
  return (
    <span className={`admin-panel__badge admin-panel__badge--${risk === "high" ? "warning" : "inactive"}`}>
      {risk === "high" ? "high risk" : "standard"}
    </span>
  );
}

function publishedLabel(item: PromptListItem): string {
  if (!item.published) return "Shipped";
  return isOverridden(item) ? `Override v${item.published.version}` : `Shipped v${item.published.version}`;
}

// An area whose keys carry a sub-group (run texts: continuation, pipeline, ...) shows one titled block per
// sub-group, in the server's order; the group names come from the key spec, never from this file.
function sectionsOf(items: PromptListItem[]): Array<{ label: string | null; items: PromptListItem[] }> {
  if (!items.some((item) => item.group)) return [{ label: null, items }];
  return subGroupsOf(items);
}

// The registered keys matching the search, grouped by area (prompts) or by tool (tool and MCP
// descriptions). Groups are collapsed until opened; a search opens every matching group.
export function PromptCatalogList({ items, query, onOpen }: Props) {
  const groups = useMemo(() => groupPromptItems(searchPromptItems(items, query)), [items, query]);
  const searching = Boolean(query.trim());
  if (!items.length) return <div className="admin-panel__empty-state">No prompt keys are registered.</div>;
  if (!groups.length) return <div className="admin-panel__empty-state">No key matches this search.</div>;
  return (
    <div className="pc-list">
      <span className="ws-muted">
        {groups.reduce((sum, group) => sum + group.items.length, 0)} keys in {groups.length} groups.
        “Shipped” is the text the platform ships with; an override replaces it after a second person's review.
      </span>
      {groups.map((group) => (
        <details className="pc-group" key={`${group.id}:${searching}`} open={searching || groups.length === 1 || undefined}>
          <summary className="pc-group__summary">
            <span className="pc-group__label">{group.label}</span>
            <span className="ws-muted">
              {group.items.length} {group.items.length === 1 ? "key" : "keys"}
              {group.openVersions ? ` · ${group.openVersions} open` : ""}
            </span>
          </summary>
          <table className="admin-panel__table pc-table" data-testid={`pc-area-${group.id}`}>
            <thead>
              <tr>
                <th>Key</th>
                <th>Title</th>
                <th>Risk</th>
                <th>Published</th>
                <th>Open</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            {sectionsOf(group.items).map((section) => (
              <tbody key={section.label ?? "all"}>
                {section.label ? (
                  <tr className="pc-subgroup">
                    <th colSpan={6} scope="rowgroup">{section.label}</th>
                  </tr>
                ) : null}
                {section.items.map((item) => (
                  <tr key={item.key}>
                    <td>
                      <code className="ws-mono pc-key">{item.key}</code>
                    </td>
                    <td>{item.title}</td>
                    <td>
                      <RiskBadge risk={item.risk} />
                    </td>
                    <td className="admin-panel__cell--muted">{publishedLabel(item)}</td>
                    <td>{item.open_versions || "—"}</td>
                    <td>
                      <button type="button" className="admin-panel__action-btn pc-open" onClick={() => onOpen(item.key)}>
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </details>
      ))}
    </div>
  );
}
