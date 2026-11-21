// Coercion of untyped payload values into strings and numbers for the mobile readers.

export const num = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
export const str = (value: unknown): string | null =>
  typeof value === "string" && value ? value : null;

export const liveText = (value: unknown) => (typeof value === "string" ? value : "");
