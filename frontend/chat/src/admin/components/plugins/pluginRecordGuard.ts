// Plugin UI model guard: whether a value is a plain JSON object.
export const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
