import type { SkillRow, Surface } from "./skillCatalogTypes";

// The catalog list filters (mock `renderTree`/`renderRows`): explicit fields only — category (the key or any
// child key), tag, free text over name/description/tags, status, surface and source. Pure functions, client-side over
// `list.items` (unit-tested in tests/unit/skillListModel.test.mjs).

export type StatusFilter = "" | "published" | "draft" | "in_review" | "update" | "retired";
export type SourceFilter = "" | "official" | "marketplace" | "git" | "upload" | "custom";
export type SurfaceFilter = "" | Surface;
export type ListFilters = {
  category: string;
  tag: string;
  query: string;
  status: StatusFilter;
  surface: SurfaceFilter;
  source: SourceFilter;
};

export const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "", label: "Any status" },
  { value: "published", label: "Published" },
  { value: "draft", label: "Draft" },
  { value: "in_review", label: "In review" },
  { value: "update", label: "Update available" },
  { value: "retired", label: "Retired" },
];
export const SOURCE_OPTIONS: { value: SourceFilter; label: string }[] = [
  { value: "", label: "Any source" },
  { value: "official", label: "Official sources only" },
  { value: "marketplace", label: "Marketplace entry" },
  { value: "git", label: "Upstream (Git)" },
  { value: "upload", label: "Uploaded" },
  { value: "custom", label: "Written here" },
];

export const EMPTY_FILTERS: ListFilters = { category: "", tag: "", query: "", status: "", surface: "", source: "" };

/** A row is in a category when its key is the category or one of its children (`parent.child`). */
export function inCategory(row: Pick<SkillRow, "category">, key: string): boolean {
  if (!key) return true;
  const own = row.category?.key ?? "";
  return own === key || own.startsWith(`${key}.`);
}

export function countInCategory(rows: Pick<SkillRow, "category">[], key: string): number {
  return rows.filter((row) => inCategory(row, key)).length;
}

/** A row with neither a published nor an open version is retired. */
export function isRetired(row: Pick<SkillRow, "published" | "open">): boolean {
  return !row.published && !row.open;
}

function matchesStatus(row: SkillRow, status: StatusFilter): boolean {
  switch (status) {
    case "published": return Boolean(row.published);
    case "draft": return row.open?.state === "draft";
    case "in_review": return row.open?.state === "in_review";
    case "update": return row.update_available;
    case "retired": return isRetired(row);
    default: return true;
  }
}

function matchesSource(row: SkillRow, source: SourceFilter): boolean {
  if (!source) return true;
  if (source === "custom") return row.source === null;
  if (source === "official") return row.source?.trust === "official";
  return row.source?.kind === source;
}

function matchesQuery(row: SkillRow, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [row.name, row.description, ...row.tags].some((text) => text.toLowerCase().includes(needle));
}

export function filterRows(rows: SkillRow[], filters: ListFilters): SkillRow[] {
  return rows.filter((row) => inCategory(row, filters.category)
    && (!filters.tag || row.tags.includes(filters.tag))
    && matchesQuery(row, filters.query)
    && matchesStatus(row, filters.status)
    && (!filters.surface || row.available[filters.surface])
    && matchesSource(row, filters.source));
}

/** Every tag of the rows, sorted, once. */
export function rowTags(rows: Pick<SkillRow, "tags">[]): string[] {
  return [...new Set(rows.flatMap((row) => row.tags))].sort();
}

export function cutText(text: string, max = 92): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}
