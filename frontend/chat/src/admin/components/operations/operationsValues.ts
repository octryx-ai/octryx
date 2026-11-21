// Defensive readers for untyped operations payload values.
export const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
export const text = (value: unknown): string => (typeof value === "string" ? value : "");
export const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
export const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
