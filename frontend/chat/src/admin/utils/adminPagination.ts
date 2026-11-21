export const DEFAULT_PAGINATION_LIMIT = 20;
export const DEFAULT_PAGINATION_OFFSET = 0;

const MIN_PAGINATION_PAGE_SIZE = 1;

function toFiniteNumber(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

export function resolvePaginationLimit(
  value: unknown,
  fallback = DEFAULT_PAGINATION_LIMIT,
  min = MIN_PAGINATION_PAGE_SIZE,
): number {
  const parsed = toFiniteNumber(value);
  if (Number.isNaN(parsed) || parsed < min) {
    return fallback;
  }
  return Math.floor(parsed);
}

export function resolvePaginationOffset(
  value: unknown,
  fallback = DEFAULT_PAGINATION_OFFSET,
  min = DEFAULT_PAGINATION_OFFSET,
): number {
  const parsed = toFiniteNumber(value);
  if (Number.isNaN(parsed) || parsed < min) {
    return fallback;
  }
  return Math.floor(parsed);
}
