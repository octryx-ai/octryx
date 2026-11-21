import { readJson } from "../../utils/adminPanelHelpers";
import type { FallbackChoice } from "./modelSelectionContract";

// The Default & fallback routes (backend api/routes/model_selection.py); parsed by modelSelectionContract.

const BASE = "/api/v1/admin/model-selection";

export const loadSelection = (): Promise<unknown> => readJson<unknown>(BASE);

export const saveOrder = (models: string[], fallback: FallbackChoice): Promise<unknown> =>
  readJson<unknown>(`${BASE}/order`, { method: "PUT", body: JSON.stringify({ models, fallback }) });

export const saveTasks = (tasks: Record<string, string | null>): Promise<unknown> =>
  readJson<unknown>(`${BASE}/tasks`, { method: "PUT", body: JSON.stringify({ tasks }) });

export const loadExplainOptions = (): Promise<unknown> => readJson<unknown>(`${BASE}/explain/options`);

export const explainTurn = (body: Record<string, unknown>): Promise<unknown> =>
  readJson<unknown>(`${BASE}/explain`, { method: "POST", body: JSON.stringify(body) });
