// Value readers shared by the phased workflow start modules: records and trimmed text from server payloads.
export const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
export const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");
export const textOrNull = (value: unknown): string | null => text(value) || null;
