// Custom REST source: value readers shared by the form, the dry run and the status (plain object, plain string).

export const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
export const str = (value: unknown) => (typeof value === "string" ? value : value === null || value === undefined ? "" : String(value));
