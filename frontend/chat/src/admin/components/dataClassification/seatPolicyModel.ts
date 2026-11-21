import { classificationSaveErrorText } from "./dataClassificationModel";
import { seatSwitchDisabled } from "./dataClassificationSeat";
import type { SeatMode, WorkspaceClassification } from "./dataClassificationTypes";

// Three more seat keys of `agent_gateway_policy`, under the two seat switches in the Data classification card. They
// save through the same `PUT /api/v1/workspaces/{id}/agent-gateway/seat-mode`, one key per call, so the server merges
// only that key and keeps every other policy key (backend `set_workspace_seat_setting`).
//   GET/PUT answer adds: requires_governed_routing, seat_models, seat_models_default,
//                        seat_models_limits: {max_models, max_model_id_chars}, seat_allows_governed_models
// The server answers each key's value in effect (its default when the key is not stored).

export type SeatModelLimits = { maxModels: number; maxModelIdChars: number };

export type SeatPolicySettings = {
  /** `requires_governed_routing`; null when the server did not say. */
  requiresGoverned: boolean | null;
  /** `seat_models`; null when the server did not say. */
  models: string[] | null;
  defaultModels: string[];
  limits: SeatModelLimits;
  /** `seat_allows_governed_models`; null when the server did not say. */
  allowsGoverned: boolean | null;
  /** `can_loosen`: true only for platform admins; a Workspace admin or owner may only tighten. */
  canLoosen: boolean;
  /** `invalid_settings`: keys whose stored value is present but invalid (their value reads as null). */
  invalid: string[];
};

// The backend's limits (seat_policy_keys.py), used only when the answer does not carry them.
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

/** One warning per stored value the server reports as invalid (`invalid_settings`). */
export function invalidSettingWarnings(invalid: string[]): string[] {
  return invalid.map((key) => `The stored value for ${SETTING_NAMES[key] ?? key} is not valid; a platform admin should set it again.`);
}

export type SeatField = "requiresGoverned" | "models" | "allowsGoverned";
const FIELD_OF_PATH: Record<string, SeatField> = {
  requires_governed_routing: "requiresGoverned", seat_models: "models", seat_allows_governed_models: "allowsGoverned",
};

/** The field a refusal names (`detail.path` of a 403 platform_admin_required), else `fallback`. */
export function seatFieldOfError(error: unknown, fallback: SeatField): SeatField {
  const detail = isRecord(error) && isRecord(error.detail) ? error.detail : {};
  return typeof detail.path === "string" ? FIELD_OF_PATH[detail.path] ?? fallback : fallback;
}

// The save bodies: each names only its own key, so the server keeps every other policy key.
export const requiresGovernedBody = (on: boolean) => ({ requires_governed_routing: on });
export const allowsGovernedBody = (on: boolean) => ({ seat_allows_governed_models: on });
export const seatModelsBody = (models: string[]) => ({ seat_models: models });
export type SeatSettingBody =
  | ReturnType<typeof requiresGovernedBody>
  | ReturnType<typeof allowsGovernedBody>
  | ReturnType<typeof seatModelsBody>;

/** The value word next to a flag; `false` is the default of both flags. */
export function seatFlagValueText(value: boolean | null): string {
  if (value === true) return "On";
  if (value === false) return "Off (default)";
  return "Unknown";
}

/** "Default" when the list is the baseline (same ids, same order), else "Custom". */
export function seatModelsValueText(settings: SeatPolicySettings): string {
  if (!settings.models) return "Unknown";
  const same = settings.defaultModels.length === settings.models.length
    && settings.defaultModels.every((model, index) => settings.models?.[index] === model);
  return same ? "Default" : "Custom";
}

// The backend's model id rule (seat_policy_keys._model_id): letters, digits and . _ : - [ ].
const MODEL_ID = /^[\p{L}\p{N}._:\-[\]]+$/u;

/** Why `candidate` cannot be added to `models`, in words; null when it can. */
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
/** The list must keep at least one model (an empty list is refused). */
export const canRemoveSeatModel = (models: string[]) => models.length > 1;

/** One hint at the top of the seat block for someone without `can_loosen` (instead of one per locked control). */
export const PLATFORM_ADMIN_HINT = "You can tighten these seat settings. Only a platform admin can loosen them: allow seat "
  + "sessions, add seat models, allow company models in seat sessions, or turn off \"Only company models\".";
/** Whether the seat block shows PLATFORM_ADMIN_HINT: an editor who may only tighten. */
export const showsPlatformAdminHint = (canEdit: boolean, canLoosen: boolean) => canEdit && !canLoosen;

export type SeatBoundState = {
  seatMode: SeatMode | null;
  codexMode: SeatMode | null;
  requiresGoverned: boolean | null;
  allowsGoverned: boolean | null;
};

/** Which next step this user may not take: loosening a seat bound needs the server's `can_loosen` (platform admins,
 * backend workspace_settings/bounds.py check_seat_setting, 403 `platform_admin_required`). Allowing a seat mode, switching "Only company
 * models" off, allowing company models in seat sessions and adding a seat model loosen; the opposite steps tighten and
 * stay open. The seat block shows PLATFORM_ADMIN_HINT once. Nothing is locked when the server says `can_loosen`. */
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

/** Which controls are read-only. Same rules as the seat switches: the server's `can_edit`, and a value it did not
 * report. Company models in seat sessions loosen a rule, so turning them on is also blocked while the classification
 * blocks seat sessions (seatSwitchDisabled); turning them off always works. On top, the platform-admin bounds
 * (seatBoundLocks): "Only company models" can be switched on by a Workspace admin, but only off by a platform admin. */
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

/** A refused save at the field, in words: 403 platform_admin_required → the bound, other 403 → the missing right, the 422 codes of these keys, else as the card. */
export function seatSettingErrorText(error: unknown, what: string, limits: SeatModelLimits): string {
  const record = isRecord(error) ? error : {};
  const code = typeof record.code === "string" ? SEAT_SETTING_CODES[record.code] : undefined;
  if (code && (record.status !== 403 || record.code === "platform_admin_required")) return `Not saved: ${code(limits)}.`;
  return classificationSaveErrorText(error, what);
}

/** The confirmation after a save. */
export function seatSettingSavedText(body: SeatSettingBody): string {
  if ("requires_governed_routing" in body) {
    return body.requires_governed_routing ? "Only company models run here now." : "Subscription sessions follow the two seat switches again.";
  }
  if ("seat_allows_governed_models" in body) {
    return body.seat_allows_governed_models ? "Seat sessions may also call company models." : "Seat sessions use only their subscription models.";
  }
  return "The model list is saved.";
}
