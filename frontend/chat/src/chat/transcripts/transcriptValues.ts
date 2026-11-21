// Type guards for transcript payloads: record, string and finite number readers.

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
export const text = (value: unknown) => (typeof value === "string" ? value : "");
export const count = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
