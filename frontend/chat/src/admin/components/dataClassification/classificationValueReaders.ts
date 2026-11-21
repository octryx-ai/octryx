// Small readers for untyped classification payload values (record, string, list).
export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export const text = (value: unknown) => (typeof value === "string" ? value : "");
export const list = (value: unknown) => (Array.isArray(value) ? value : []);
