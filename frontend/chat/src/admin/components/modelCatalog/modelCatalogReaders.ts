// Model catalog payload readers: tolerant record, string, number and string-list readers.

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
export const str = (value: unknown) => (typeof value === "string" ? value : "");
export const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : null);
export const strings = (value: unknown) => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
