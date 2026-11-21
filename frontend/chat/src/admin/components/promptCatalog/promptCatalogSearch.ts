// Client-side search and grouping of the prompt catalog list (audits 59, 59a, 59b).
// Prompt keys group by their area; tool and MCP description keys
// (`tool.<name>.description`, `tool.<name>.param.<path>`, `mcp.<name>.description`)
// group by the tool they describe, so one tool's description and parameters stay together.
import type { PromptListItem } from "./promptCatalogTypes";

export type PromptGroup = {
  id: string;
  label: string;
  items: PromptListItem[];
  overrides: number;
  openVersions: number;
};

// Areas whose keys are named per tool and are grouped by that tool.
export const TOOL_KEYED_AREAS = new Set(["tool", "mcp"]);

export function toolNameOf(key: string): string {
  const [, name] = key.split(".");
  return name || key;
}

// Every whitespace-separated term must occur in the key, title or description.
export function searchPromptItems(items: PromptListItem[], query: string): PromptListItem[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return items;
  return items.filter((item) => {
    const haystack = `${item.key} ${item.title} ${item.description}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });
}

function keyOrder(left: PromptListItem, right: PromptListItem): number {
  // The tool description first, its parameters after it in key order.
  const leftDescription = left.key.endsWith(".description") ? 0 : 1;
  const rightDescription = right.key.endsWith(".description") ? 0 : 1;
  return leftDescription - rightDescription || left.key.localeCompare(right.key);
}

export function groupPromptItems(items: PromptListItem[]): PromptGroup[] {
  const groups = new Map<string, PromptListItem[]>();
  for (const item of items) {
    const id = TOOL_KEYED_AREAS.has(item.area) ? `${item.area}.${toolNameOf(item.key)}` : item.area;
    groups.set(id, [...(groups.get(id) ?? []), item]);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([id, rows]) => {
      const sorted = [...rows].sort(keyOrder);
      const toolKeyed = TOOL_KEYED_AREAS.has(sorted[0].area);
      return {
        id,
        label: toolKeyed ? toolNameOf(sorted[0].key) : sorted[0].area,
        items: sorted,
        overrides: sorted.reduce((sum, row) => sum + (row.override_count || 0), 0),
        openVersions: sorted.reduce((sum, row) => sum + (row.open_versions || 0), 0),
      };
    });
}
