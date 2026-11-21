// Tolerant readers for the companion's payload values: unknown shapes read as empty, never thrown.

export const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
export const str = (value: unknown): string => (typeof value === "string" ? value : "");
export const optStr = (value: unknown): string | null => (typeof value === "string" && value ? value : null);
export const pick = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
  allowed.includes(value as T) ? (value as T) : fallback;
