// Runtime → Models → Default & fallback. Pure: no requests, no React.
//
// Contract (backend api/routes/model_selection.py):
//   GET /api/v1/admin/model-selection -> {order: [model], fallback: "next" | "stop",
//       tasks: [{key, label, model_key, workspace_overrides}], models: [model]}
//   PUT /api/v1/admin/model-selection/order {models: [catalog_key], fallback} -> page; 422 {detail: {code}}
//   PUT /api/v1/admin/model-selection/tasks {tasks: {task: catalog_key | null}} -> page
// model = {catalog_key, display_name, provider, enabled, provider_active, cleared_up_to, capabilities}

import { CAPABILITY_KEYS, CAPABILITY_LABELS, levelLabel } from "../modelCatalog/modelCatalogContract";
import type { CapabilityKey } from "../modelCatalog/modelCatalogContract";

export type FallbackChoice = "next" | "stop";
export type SelectionModel = {
  key: string; displayName: string; provider: string; enabled: boolean; providerActive: boolean;
  clearedUpTo: string | null; capabilities: Record<CapabilityKey, boolean>;
};
export type TaskRow = { key: string; label: string; modelKey: string | null; workspaceOverrides: number };
export type SelectionPage = { order: SelectionModel[]; fallback: FallbackChoice; tasks: TaskRow[]; models: SelectionModel[] };

export const FALLBACK_CHOICES: readonly { value: FallbackChoice; title: string; help: string }[] = [
  {
    value: "next",
    title: "Try the next allowed model",
    help: "Next model in this order that the Workspace allows and has cleared. The answer says it fell back and why.",
  },
  {
    value: "stop",
    title: "Stop with an error",
    help: "The turn ends with a visible error naming the model and the reason. Nothing else answers.",
  },
];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown) => (typeof value === "string" ? value : "");
const list = (value: unknown) => (Array.isArray(value) ? value.filter(isRecord) : []);

function readModel(raw: Record<string, unknown>): SelectionModel | null {
  const key = str(raw.catalog_key);
  if (!key) return null;
  const caps = isRecord(raw.capabilities) ? raw.capabilities : {};
  return {
    key, displayName: str(raw.display_name) || key, provider: str(raw.provider), enabled: raw.enabled === true,
    providerActive: raw.provider_active !== false, clearedUpTo: str(raw.cleared_up_to) || null,
    capabilities: Object.fromEntries(CAPABILITY_KEYS.map((cap) => [cap, caps[cap] === true])) as Record<CapabilityKey, boolean>,
  };
}

const models = (value: unknown) => list(value).map(readModel).filter((item): item is SelectionModel => item !== null);

export function readSelectionPage(payload: unknown): SelectionPage {
  const body = isRecord(payload) ? payload : {};
  return {
    order: models(body.order),
    fallback: body.fallback === "stop" ? "stop" : "next",
    tasks: list(body.tasks).map((task) => ({
      key: str(task.key), label: str(task.label), modelKey: str(task.model_key) || null,
      workspaceOverrides: typeof task.workspace_overrides === "number" ? task.workspace_overrides : 0,
    })).filter((task) => task.key),
    models: models(body.models),
  };
}

export const capabilityLabels = (model: SelectionModel): string[] =>
  CAPABILITY_KEYS.filter((cap) => model.capabilities[cap]).map((cap) => CAPABILITY_LABELS[cap]);

export const orderSubline = (model: SelectionModel): string =>
  `${model.provider} · ${model.clearedUpTo ? `cleared up to ${levelLabel(model.clearedUpTo)}` : "not cleared for data"}`;

/** Move the entry at ``index`` by ``step`` (−1 up, +1 down); out-of-range moves return the same order. */
export function moveEntry(order: string[], index: number, step: -1 | 1): string[] {
  const target = index + step;
  if (index < 0 || index >= order.length || target < 0 || target >= order.length) return order;
  const next = [...order];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** Enabled models that are not in the order yet (the "Add to the order" list). */
export const addableModels = (page: SelectionPage, order: string[]): SelectionModel[] =>
  page.models.filter((model) => model.enabled && !order.includes(model.key));

export const sameList = (a: string[], b: string[]) => a.length === b.length && a.every((item, index) => item === b[index]);

export function taskPayload(tasks: Record<string, string>): Record<string, string | null> {
  return Object.fromEntries(Object.entries(tasks).map(([task, key]) => [task, key || null]));
}

const SAVE_CODES: Record<string, string> = {
  model_order_empty: "the order needs at least one model",
  model_order_invalid: "the order lists a model twice",
  model_order_unknown_model: "a model in the order no longer exists",
  model_order_model_not_enabled: "a model in the order is not enabled in the Model catalog",
  model_fallback_invalid: "choose what happens when a model fails",
  task_models_invalid: "a task is not known",
  task_models_unknown_model: "a task model no longer exists",
  task_models_model_not_enabled: "a task model is not enabled in the Model catalog",
  task_models_model_not_in_order: "a task model must be in the platform order",
};

export function selectionErrorText(error: unknown): string {
  const record = isRecord(error) ? error : {};
  const code = str(record.code) || (isRecord(record.detail) ? str(record.detail.code) : "");
  if (record.status === 403) return "Not saved: only platform admins can change the platform order.";
  return `Not saved: ${SAVE_CODES[code] ?? "the change was refused"}.`;
}

// ---- Explain a turn ----------------------------------------------------------------------------
// GET  /api/v1/admin/model-selection/explain/options -> {workspaces: [{id, name, data_class}], models: [{key, name}]}
// POST /api/v1/admin/model-selection/explain {workspace_id, person_choice, agent_pin, first_fails}
//      -> {state, title, note, trace: [{icon: "ok" | "no" | "mid", label, text}]}

export type ExplainOptions = { workspaces: { id: string; name: string; dataClass: string }[]; models: { key: string; name: string }[] };
export type ExplainTurn = { workspaceId: string; personChoice: string; agentPin: string; firstFails: boolean };
export type ExplainStep = { icon: "ok" | "no" | "mid"; label: string; text: string };
export type ExplainResult = { state: string; title: string; note: string; trace: ExplainStep[] };

export function readExplainOptions(payload: unknown): ExplainOptions {
  const body = isRecord(payload) ? payload : {};
  return {
    workspaces: list(body.workspaces).map((item) => ({ id: str(item.id), name: str(item.name), dataClass: str(item.data_class) }))
      .filter((item) => item.id),
    models: list(body.models).map((item) => ({ key: str(item.key), name: str(item.name) || str(item.key) })).filter((item) => item.key),
  };
}

export function explainBody(turn: ExplainTurn): Record<string, unknown> {
  return {
    workspace_id: turn.workspaceId, person_choice: turn.personChoice, agent_pin: turn.agentPin, first_fails: turn.firstFails,
  };
}

export function readExplainResult(payload: unknown): ExplainResult {
  const body = isRecord(payload) ? payload : {};
  return {
    state: str(body.state), title: str(body.title), note: str(body.note),
    trace: list(body.trace).map((step) => ({
      icon: step.icon === "ok" || step.icon === "no" ? step.icon : "mid",
      label: str(step.label), text: str(step.text),
    })),
  };
}

export const explainFailed = (state: string) => state !== "answered";
export const TRACE_MARK: Record<ExplainStep["icon"], string> = { ok: "✓", no: "✕", mid: "!" };
