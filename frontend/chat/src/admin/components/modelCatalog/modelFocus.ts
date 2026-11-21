// A link from Problems ("model has no price") names a model as `?model=<id>`; the catalog opens that one once.

export function focusedModelId(search: string | undefined): string {
  try {
    return new URLSearchParams(search ?? "").get("model")?.trim() ?? "";
  } catch {
    return "";
  }
}

/** The catalog row the link names (by row id first, else catalog key or model id), if it is in the catalog. */
export function modelToFocus<T extends { id: string; catalogKey?: string; modelId?: string }>(
  models: T[],
  search: string | undefined,
): T | null {
  const id = focusedModelId(search);
  if (!id) return null;
  return models.find((row) => row.id === id) ?? models.find((row) => row.catalogKey === id || row.modelId === id) ?? null;
}
