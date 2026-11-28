// A stored invalid value is answered as null too; an answer without the key reads as unknown.

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

export function codexModelsValueText(view: CodexModelsView): string {
  if (view.kind === "all") return "Default";
  if (view.kind === "list") return "Custom";
  return "Unknown";
}

export const codexSeatModelsBody = (models: string[] | null) => ({ codex_seat_models: models });
export type CodexSeatModelsBody = ReturnType<typeof codexSeatModelsBody>;

/** Mirrors backend workspace_settings/bounds.py check_seat_setting (null = every Codex model). */
export function codexModelsChangeLoosens(before: string[] | null, after: string[] | null): boolean {
  if (before === null) return false;
  if (after === null) return true;
  return after.some((model) => !before.includes(model));
}

export function codexModelsActions(view: CodexModelsView, canEdit: boolean, canLoosen: boolean) {
  const edit = canEdit && view.kind !== "unknown";
  return {
    restrict: edit && view.kind === "all",
    add: edit && view.kind === "list" && canLoosen,
    remove: edit && view.kind === "list",
    allowAll: edit && view.kind === "list" && canLoosen,
  };
}

export function codexSeatModelsSavedText(body: CodexSeatModelsBody): string {
  return body.codex_seat_models === null
    ? "Codex seat sessions may use every Codex model again."
    : "The Codex model list is saved.";
}
