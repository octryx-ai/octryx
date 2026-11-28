// A hook assembled from smaller hooks still returns its keys in the documented order.
export function orderKeys<T extends object>(value: T, order: readonly (keyof T)[]): T {
  const ordered = {} as T;
  for (const key of order) ordered[key] = value[key];
  for (const key of Object.keys(value) as (keyof T)[]) {
    if (!order.includes(key)) ordered[key] = value[key];
  }
  return ordered;
}
