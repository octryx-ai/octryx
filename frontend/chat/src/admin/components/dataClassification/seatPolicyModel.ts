import { classificationSaveErrorText } from "./dataClassificationModel";
import { seatSwitchDisabled } from "./dataClassificationSeat";
import type { SeatMode, WorkspaceClassification } from "./dataClassificationTypes";

// One key per PUT so the server merges only that key and keeps every other policy key.

export type SeatModelLimits = { maxModels: number; maxModelIdChars: number };

export type SeatPolicySettings = {
  requiresGoverned: boolean | null;
  models: string[] | null;
  defaultModels: string[];
  limits: SeatModelLimits;
  allowsGoverned: boolean | null;
  canLoosen: boolean;
  invalid: string[];
};

const FALLBACK_LIMITS: SeatModelLimits = { maxModels: 20, maxModelIdChars: 100 };

export const REQUIRES_GOVERNED_LABEL = "Only company models through the gateway";
export const REQUIRES_GOVERNED_EXPLANATION =
  "When on, no subscription session runs here, Claude or Codex, whatever the two switches above say. Agents use only the Workspace's company models through the gateway.";
export const SEAT_MODELS_LABEL = "Models a Claude seat session may use";
export const SEAT_MODELS_EXPLANATION =
  "A Claude seat session may call only these model ids; the gateway refuses any other. The Codex seat has its own list.";
export const ALLOWS_GOVERNED_LABEL = "Seat sessions may also call company models";
export const ALLOWS_GOVERNED_EXPLANATION =
  "A Claude seat session may also call the Workspace's company models, billed to the Workspace budget and under the governed checks.";

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;
const flag = (value: unknown) => (typeof value === "boolean" ? value : null);
const ids = (value: unknown) =>
  Array.isArray(value) && value.every((item) => typeof item === "string") ? (value as string[]) : null;
const positive = (value: unknown, fallback: number) =>
  typeof value === "number" && Number.isInteger(value) && value > 0 ? value : fallback;

export function readSeatPolicySettings(payload: unknown): SeatPolicySettings {
  const record = isRecord(payload) ? payload : {};
  const limits = isRecord(record.seat_models_limits) ? record.seat_models_limits : {};
  return {
    requiresGoverned: flag(record.requires_governed_routing),
    models: ids(record.seat_models),
    defaultModels: ids(record.seat_models_default) ?? [],
    limits: {
      maxModels: positive(limits.max_models, FALLBACK_LIMITS.maxModels),
      maxModelIdChars: positive(limits.max_model_id_chars, FALLBACK_LIMITS.maxModelIdChars),
    },
    allowsGoverned: flag(record.seat_allows_governed_models),
    canLoosen: record.can_loosen === true,
    invalid: ids(record.invalid_settings) ?? [],
  };
}

const SETTING_NAMES: Record<string, string> = {
  seat_mode: "the Claude seat",
  codex_seat_mode: "the Codex seat",
  requires_governed_routing: `"${REQUIRES_GOVERNED_LABEL}"`,
  seat_models: "the seat model list",
  seat_allows_governed_models: `"${ALLOWS_GOVERNED_LABEL}"`,
  codex_seat_models: "the Codex model list",
};

export function invalidSettingWarnings(invalid: string[]): string[] {
  return invalid.map((key) => `The stored value for ${SETTING_NAMES[key] ?? key} is not valid; a platform admin should set it again.`);
}

export type SeatField = "requiresGoverned" | "models" | "allowsGoverned";
const FIELD_OF_PATH: Record<string, SeatField> = {
  requires_governed_routing: "requiresGoverned", seat_models: "models", seat_allows_governed_models: "allowsGoverned",
};

export function seatFieldOfError(error: unknown, fallback: SeatField): SeatField {
  const detail = isRecord(error) && isRecord(error.detail) ? error.detail : {};
  return typeof detail.path === "string" ? FIELD_OF_PATH[detail.path] ?? fallback : fallback;
}

export const requiresGovernedBody = (on: boolean) => ({ requires_governed_routing: on });
export const allowsGovernedBody = (on: boolean) => ({ seat_allows_governed_models: on });
export const seatModelsBody = (models: string[]) => ({ seat_models: models });
export type SeatSettingBody =
  | ReturnType<typeof requiresGovernedBody>
  | ReturnType<typeof allowsGovernedBody>
  | ReturnType<typeof seatModelsBody>;

export function seatFlagValueText(value: boolean | null): string {
  if (value === true) return "On";
  if (value === false) return "Off (default)";
  return "Unknown";
}

export function seatModelsValueText(settings: SeatPolicySettings): string {
  if (!settings.models) return "Unknown";
  const same = settings.defaultModels.length === settings.models.length
    && settings.defaultModels.every((model, index) => settings.models?.[index] === model);
  return same ? "Default" : "Custom";
}

const MODEL_ID = /^[\p{L}\p{N}._:\-[\]]+$/u;

export function seatModelProblem(candidate: string, models: string[], limits: SeatModelLimits): string | null {
  const id = candidate.trim();
  if (!id) return "Enter a model id.";
  if (id.length > limits.maxModelIdChars) return `A model id has at most ${limits.maxModelIdChars} characters.`;
  if (!MODEL_ID.test(id)) return "A model id has only letters, digits and . _ : - [ ] (no spaces).";
  if (models.includes(id)) return "This model is already in the list.";
  if (models.length >= limits.maxModels) return `The list holds at most ${limits.maxModels} models; remove one first.`;
  return null;
}

export const withSeatModel = (models: string[], candidate: string) => [...models, candidate.trim()];
export const withoutSeatModel = (models: string[], model: string) => models.filter((item) => item !== model);
export const canRemoveSeatModel = (models: string[]) => models.length > 1;

export const PLATFORM_ADMIN_HINT = "You can tighten these seat settings. Only a platform admin can loosen them: allow seat "
  + "sessions, add seat models, allow company models in seat sessions, or turn off \"Only company models\".";
export const showsPlatformAdminHint = (canEdit: boolean, canLoosen: boolean) => canEdit && !canLoosen;

export type SeatBoundState = {
  seatMode: SeatMode | null;
  codexMode: SeatMode | null;
  requiresGoverned: boolean | null;
  allowsGoverned: boolean | null;
};

export function seatBoundLocks(canLoosen: boolean, state: SeatBoundState) {
  if (canLoosen) return { seatMode: false, codexMode: false, requiresGoverned: false, allowsGoverned: false, addModels: false };
  return {
    seatMode: state.seatMode !== "allowed",
    codexMode: state.codexMode !== "allowed",
    requiresGoverned: state.requiresGoverned === true,
    allowsGoverned: state.allowsGoverned !== true,
    addModels: true,
  };
}

export function seatSettingsDisabled(model: WorkspaceClassification, settings: SeatPolicySettings) {
  const locks = seatBoundLocks(settings.canLoosen, { seatMode: null, codexMode: null, ...settings });
  return {
    requiresGoverned: !model.canEdit || settings.requiresGoverned === null || locks.requiresGoverned,
    models: !model.canEdit || settings.models === null,
    addModels: !model.canEdit || settings.models === null || locks.addModels,
    allowsGoverned: settings.allowsGoverned === null || locks.allowsGoverned
      || seatSwitchDisabled(model, settings.allowsGoverned ? "allowed" : "forbidden"),
  };
}

const SEAT_SETTING_CODES: Record<string, (limits: SeatModelLimits) => string> = {
  invalid_list: (limits) => `the list needs 1 to ${limits.maxModels} model ids`,
  invalid_model_id: (limits) => `a model id has 1 to ${limits.maxModelIdChars} characters: letters, digits and . _ : - [ ]`,
  invalid_flag: () => "the value must be on or off",
  one_setting_per_call: () => "only one setting can be saved at a time",
  platform_admin_required: () => "only a platform admin can change this",
  unknown_setting: () => "the server does not know this setting",
};

export function seatSettingErrorText(error: unknown, what: string, limits: SeatModelLimits): string {
  const record = isRecord(error) ? error : {};
  const code = typeof record.code === "string" ? SEAT_SETTING_CODES[record.code] : undefined;
  if (code && (record.status !== 403 || record.code === "platform_admin_required")) return `Not saved: ${code(limits)}.`;
  return classificationSaveErrorText(error, what);
}

export function seatSettingSavedText(body: SeatSettingBody): string {
  if ("requires_governed_routing" in body) {
    return body.requires_governed_routing ? "Only company models run here now." : "Subscription sessions follow the two seat switches again.";
  }
  if ("seat_allows_governed_models" in body) {
    return body.seat_allows_governed_models ? "Seat sessions may also call company models." : "Seat sessions use only their subscription models.";
  }
  return "The model list is saved.";
}
