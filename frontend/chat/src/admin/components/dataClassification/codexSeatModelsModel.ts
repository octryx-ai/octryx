// The Codex seat's model list (backend): `agent_gateway_policy.codex_seat_models`, under the Codex seat switch.
// Saved through the same `PUT /api/v1/workspaces/{id}/agent-gateway/seat-mode`, one key per call:
//   {codex_seat_models: [model id]}  restrict to these ids (1..max_models, the same id rule as seat_models)
//   {codex_seat_models: null}        no list again: every Codex model (the default)
// GET/PUT answer `codex_seat_models`: the list, or null for every Codex model; a stored invalid value is null too and
// is named in `invalid_settings`. An answer without the key reads as unknown.

export const CODEX_SEAT_MODELS_LABEL = "Models a Codex seat session may use";
export const CODEX_SEAT_MODELS_EXPLANATION =
  "By default Codex picks any of its models. Restrict it to a list and the gateway refuses every other Codex model.";
export const CODEX_ALL_MODELS_TEXT = "All Codex models (default)";

export type CodexModelsView =
  | { kind: "unknown" }
  | { kind: "all" }
  | { kind: "list"; models: string[] };

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;

export function readCodexSeatModels(payload: unknown): CodexModelsView {
  if (!isRecord(payload) || !("codex_seat_models" in payload)) return { kind: "unknown" };
  const invalid = Array.isArray(payload.invalid_settings) && payload.invalid_settings.includes("codex_seat_models");
  const value = payload.codex_seat_models;
  if (invalid) return { kind: "unknown" };
  if (value === null) return { kind: "all" };
  if (Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === "string")) {
    return { kind: "list", models: value as string[] };
  }
  return { kind: "unknown" };
}

/** The badge: Default for every Codex model, Custom for a list. */
export function codexModelsValueText(view: CodexModelsView): string {
  if (view.kind === "all") return "Default";
  if (view.kind === "list") return "Custom";
  return "Unknown";
}

/** The save body: only the Codex list key; null goes back to every Codex model. */
export const codexSeatModelsBody = (models: string[] | null) => ({ codex_seat_models: models });
export type CodexSeatModelsBody = ReturnType<typeof codexSeatModelsBody>;

/** Whether going from `before` to `after` loosens the rule (null = every Codex model). Mirrors backend
 * workspace_settings/bounds.py check_seat_setting: back to every model, or an added id, loosens; restricting from
 * every model to a list, or removing ids, tightens. */
export function codexModelsChangeLoosens(before: string[] | null, after: string[] | null): boolean {
  if (before === null) return false;
  if (after === null) return true;
  return after.some((model) => !before.includes(model));
}

/** Which steps this user may take. Tightening needs `can_edit`; loosening also `can_loosen` (platform admin). */
export function codexModelsActions(view: CodexModelsView, canEdit: boolean, canLoosen: boolean) {
  const edit = canEdit && view.kind !== "unknown";
  return {
    restrict: edit && view.kind === "all",
    add: edit && view.kind === "list" && canLoosen,
    remove: edit && view.kind === "list",
    allowAll: edit && view.kind === "list" && canLoosen,
  };
}

/** The confirmation after a save. */
export function codexSeatModelsSavedText(body: CodexSeatModelsBody): string {
  return body.codex_seat_models === null
    ? "Codex seat sessions may use every Codex model again."
    : "The Codex model list is saved.";
}
