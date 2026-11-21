import { readJson } from "../../utils/adminPanelHelpers";

// The Model catalog routes (backend api/routes/model_catalog.py); answers are parsed by modelCatalogContract.

const BASE = "/api/v1/admin/model-catalog";
const modelPath = (id: string) => `${BASE}/models/${encodeURIComponent(id)}`;

export const loadCatalog = (): Promise<unknown> => readJson<unknown>(BASE);

export const saveCatalogModel = (id: string, patch: Record<string, unknown>): Promise<unknown> =>
  readJson<unknown>(modelPath(id), { method: "PATCH", body: JSON.stringify(patch) });

export const syncCatalog = (): Promise<unknown> => readJson<unknown>(`${BASE}/sync`, { method: "POST" });

export const addSelectedModels = (selected: { provider_id: string; model_id: string }[]): Promise<unknown> =>
  readJson<unknown>(`${BASE}/sync/add`, { method: "POST", body: JSON.stringify({ selected }) });

export const addGatewayAlias = (id: string): Promise<unknown> =>
  readJson<unknown>(`${modelPath(id)}/alias`, { method: "POST" });
