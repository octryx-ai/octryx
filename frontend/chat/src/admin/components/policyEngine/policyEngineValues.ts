// Cedar policy engine model: defensive readers of the backend answers (record, string, number, strings).

export type Json = Record<string, unknown>;

export const isRecord = (value: unknown): value is Json => typeof value === "object" && value !== null && !Array.isArray(value);
export const str = (value: unknown): string => (typeof value === "string" ? value : "");
export const num = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);
export const strs = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
export const optNum = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
