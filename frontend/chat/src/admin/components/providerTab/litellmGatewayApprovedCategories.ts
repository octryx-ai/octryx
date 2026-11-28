// A malformed list refuses the alias at admission, so the form refuses it first with the backend's code.

export const MAX_APPROVED_CATEGORIES = 30;
export const ALIAS_APPROVED_CATEGORIES_INVALID = "alias_approved_data_categories_invalid";
const CATEGORY_ID = /^[a-z][a-z0-9_]{1,39}$/;

export function readApprovedCategories(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return [...new Set(raw.map((item) => (typeof item === "string" ? item : String(item))))].sort();
}

export function approvedCategoriesCodes(categories: string[] = []): string[] {
  const valid = categories.length <= MAX_APPROVED_CATEGORIES && categories.every((item) => CATEGORY_ID.test(item));
  return valid ? [] : [ALIAS_APPROVED_CATEGORIES_INVALID];
}

export function approvedCategoriesEntry(categories: string[] = []): { approved_data_categories?: string[] } {
  return categories.length ? { approved_data_categories: [...new Set(categories)].sort() } : {};
}

export function toggleCategory(categories: string[], id: string): string[] {
  return categories.includes(id) ? categories.filter((item) => item !== id) : [...categories, id].sort();
}

export type ContentCategory = { id: string; label: string };

export function readContentCategories(raw: unknown): ContentCategory[] {
  const list = raw && typeof raw === "object" && Array.isArray((raw as { categories?: unknown }).categories)
    ? (raw as { categories: unknown[] }).categories : [];
  return list.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const id = typeof record.id === "string" ? record.id : "";
    return id ? [{ id, label: typeof record.label === "string" && record.label ? record.label : id }] : [];
  });
}
