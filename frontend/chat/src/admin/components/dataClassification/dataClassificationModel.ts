import { rerankerHoldText } from "../workspaceKnowledge/knowledgeSearchPresenter";
import { seatReasonText } from "./dataClassificationSeat";
import type {
  ClassificationEffects,
  ClassificationLevel,
  InstanceDefault,
  RerankerState,
  SeatMode,
  WorkspaceClassification,
} from "./dataClassificationTypes";

const RERANKER_STATES: readonly RerankerState[] = ["ok", "needs_configuration", "denied"];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const flag = (value: unknown) => (typeof value === "boolean" ? value : null);
const count = (value: unknown) => (typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null);

const EFFECT_KEYS = ["reranker_allowed", "remote_embeddings_allowed", "seat_mode_allowed"];

/** The plain facts of one level, or null when the value carries none of them. */
export function readEffects(value: unknown): ClassificationEffects | null {
  if (!isRecord(value) || !EFFECT_KEYS.some((key) => typeof value[key] === "boolean")) return null;
  const reasons = isRecord(value.reasons) ? value.reasons : {};
  return {
    rerankerAllowed: flag(value.reranker_allowed),
    rerankerState: RERANKER_STATES.find((state) => state === text(value.reranker_state)) ?? null,
    rerankerReason: text(reasons.reranker_allowed) || null,
    remoteEmbeddingsAllowed: flag(value.remote_embeddings_allowed),
    remoteEmbeddingsReason: text(reasons.remote_embeddings_allowed) || null,
    seatModeAllowed: flag(value.seat_mode_allowed),
    seatModeReason: text(reasons.seat_mode_allowed) || null,
    governedModels: Array.isArray(value.governed_models) ? value.governed_models.map(text).filter(Boolean) : null,
  };
}

/** The ordered levels exactly as the server lists them (objects or plain values). */
export function readLevels(value: unknown): ClassificationLevel[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const levels: ClassificationLevel[] = [];
  for (const entry of value) {
    const record: Record<string, unknown> = isRecord(entry) ? entry : { value: entry };
    const level = text(record.value);
    if (!level || seen.has(level)) continue;
    seen.add(level);
    levels.push({ value: level, label: text(record.label) || level, description: text(record.description), effects: readEffects(record.effects) });
  }
  return levels;
}

/** The Workspace read model; null when the answer carries no levels (nothing can be chosen then). */
export function readWorkspaceClassification(payload: unknown): WorkspaceClassification | null {
  if (!isRecord(payload)) return null;
  const levels = readLevels(payload.levels);
  if (!levels.length) return null;
  const effective = text(payload.effective) || null;
  const source = text(payload.source);
  const instanceDefault = isRecord(payload.instance_default) ? payload.instance_default.classification : payload.instance_default;
  return {
    effective,
    source: source === "workspace" || source === "instance_default" ? source : "unset",
    cleared: payload.cleared === true,
    instanceDefault: text(instanceDefault) || null,
    levels,
    effects: readEffects(payload.effects) ?? levels.find((level) => level.value === effective)?.effects ?? null,
    canEdit: payload.can_edit === true,
  };
}

export function readSeatMode(payload: unknown): SeatMode | null {
  const value = isRecord(payload) ? text(payload.seat_mode) : "";
  return value === "allowed" || value === "forbidden" ? value : null;
}

/** The Instance default read model; null when the answer carries no levels. */
export function readInstanceDefault(payload: unknown): InstanceDefault | null {
  if (!isRecord(payload)) return null;
  const levels = readLevels(payload.levels);
  if (!levels.length) return null;
  return {
    classification: text(payload.classification) || null,
    environmentInEffect: payload.env_in_effect === true,
    environmentValue: text(payload.env_value) || null,
    levels,
    unclassifiedWorkspaces: count(payload.unclassified_count),
  };
}

export function levelLabel(levels: ClassificationLevel[], value: string | null): string {
  if (!value) return "Not set";
  return levels.find((level) => level.value === value)?.label || value;
}

/** "Set for this Workspace", "Instance default (x)" or "Not set". */
export function sourceText(model: WorkspaceClassification): string {
  if (model.source === "workspace") return "Set for this Workspace";
  if (model.source === "instance_default") {
    return `Instance default (${levelLabel(model.levels, model.instanceDefault ?? model.effective)})`;
  }
  return model.cleared ? "Not set (cleared on purpose)" : "Not set";
}

// "needs_configuration" is neither ✓ nor ✗: the instance must be configured before the level matters.
export type EffectStatus = "allowed" | "denied" | "needs_configuration";
// ``words`` replaces the status words when they would contradict the line (local embeddings are not "remote").
export type EffectLine = { key: string; label: string; allowed: boolean; status: EffectStatus; detail: string; words?: string };

const fact = (key: string, label: string, allowed: boolean, detail: string): EffectLine =>
  ({ key, label, allowed, status: allowed ? "allowed" : "denied", detail });

/** The reranker's status: the server's `reranker_state` wins; ✓ only when it is `ok` and the fact says allowed. */
export function rerankerStatus(effects: ClassificationEffects): EffectStatus {
  if (effects.rerankerState === "needs_configuration") return "needs_configuration";
  if (effects.rerankerState === "denied") return "denied";
  return effects.rerankerAllowed ? "allowed" : "denied";
}

/** "What this means here": one ✓/✗ line per fact the server stated; nothing is guessed for an unstated fact. */
export function effectLines(effects: ClassificationEffects | null): EffectLine[] {
  if (!effects) return [];
  const lines: EffectLine[] = [];
  if (effects.rerankerAllowed !== null || effects.rerankerState !== null) {
    const status = rerankerStatus(effects);
    lines.push({
      key: "reranker", label: "Reranker for Knowledge search", allowed: status === "allowed", status,
      detail: status === "allowed" ? ""
        : status === "needs_configuration"
          ? rerankerHoldText(effects.rerankerReason) ?? factReasonText(effects.rerankerReason) ?? "the reranker needs configuration on this instance"
          : factReasonText(effects.rerankerReason) ?? "",
    });
  }
  if (effects.remoteEmbeddingsReason === "embedding_space_local") {
    // A local embedding space: nothing remote happens, so the line says that instead of "remote … allowed".
    lines.push({ key: "embeddings", label: "Embeddings for Knowledge", allowed: true, status: "allowed",
      words: "computed locally", detail: "nothing is sent out" });
  } else if (effects.remoteEmbeddingsAllowed !== null) {
    lines.push(fact("embeddings", "Remote embeddings for Knowledge", effects.remoteEmbeddingsAllowed,
      factReasonText(effects.remoteEmbeddingsReason) ?? ""));
  }
  if (effects.seatModeAllowed !== null) {
    lines.push(fact("seat", "Claude subscription (seat) sessions", effects.seatModeAllowed,
      effects.seatModeAllowed ? "" : seatReasonText(effects.seatModeReason)));
  }
  if (effects.governedModels !== null) {
    lines.push(fact("models", "Governed models through the gateway", effects.governedModels.length > 0,
      effects.governedModels.length ? effects.governedModels.join(", ") : "no gateway model is approved for this level"));
  }
  return lines;
}

const FACT_REASON_TEXT: Record<string, string> = {
  reranker_not_configured: "no reranker is configured on this instance",
  embedding_space_not_configured: "no embedding space is configured on this instance",
  embedding_space_local: "embeddings are computed locally, nothing is sent out",
  // The classification policy matrix forbids it for this level.
  classification_policy_reranker_forbidden: "the classification policy forbids it for this level",
  classification_policy_remote_embeddings_forbidden: "the classification policy forbids it for this level",
};

/** A reranker or embedding reason in words; another fixed code (a data-policy denial) is shown as the level's refusal. */
function factReasonText(reason: string | null): string | null {
  if (!reason) return null;
  return FACT_REASON_TEXT[reason] || `the data policy does not admit this level (${reason})`;
}

export const NOT_SET_WARNING =
  "Not set: Knowledge search runs without the reranker and remote embeddings, and Claude subscription (seat) sessions are refused, until a classification is set.";

export const CLEAR_HINT = "Not set keeps this Workspace unclassified on purpose: the Instance default will not fill it in.";

const errorRecord = (error: unknown) => (isRecord(error) ? error : null);
const errorMessage = (record: Record<string, unknown> | null) =>
  typeof record?.message === "string" && record.message ? record.message : "";

/** A refused read, in words. */
export function classificationLoadErrorText(error: unknown): string {
  const record = errorRecord(error);
  if (record?.status === 404) {
    return "No data classification is shown: this server does not offer it yet, or you are not a member of this Workspace.";
  }
  if (record?.status === 401 || record?.status === 403) return "Only members of this Workspace can see its data classification.";
  return `The data classification could not be loaded: ${errorMessage(record) || "the request failed"}.`;
}

const SAVE_CODE_TEXT: Record<string, string> = {
  data_classification_unknown: "the server does not know this level; reload the page",
  invalid_seat_mode: "the server does not know this seat setting",
  agent_gateway_policy_invalid: "the stored agent gateway policy of this Workspace is invalid; a platform admin must fix it first",
  platform_admin_required: "only a platform admin can change this",
};

/** A refused save, in words: the missing right for a 403, a known refusal code, else the server's message. */
export function classificationSaveErrorText(error: unknown, what = "the classification"): string {
  const record = errorRecord(error);
  if (record?.code === "platform_admin_required") return `Not saved: ${SAVE_CODE_TEXT.platform_admin_required}.`;
  if (record?.status === 403) return `Not saved: only Workspace admins and owners can change ${what}.`;
  const code = typeof record?.code === "string" ? SAVE_CODE_TEXT[record.code] : undefined;
  if (code) return `Not saved: ${code}.`;
  const message = errorMessage(record);
  if (record?.status === 422) return `Not saved: the server refused this value${message ? ` (${message})` : ""}.`;
  return `Not saved: ${message || "the change was refused"}.`;
}

/** The Instance default checkbox label, with the count when the server reported it. */
export function applyToUnclassifiedLabel(unclassified: number | null): string {
  return `Also apply to Workspaces that are not classified yet${unclassified === null ? "" : ` (${unclassified})`}`;
}

/** How many Workspaces a save classified (`applied_count`), or null when the answer does not say. */
export function readAppliedCount(payload: unknown): number | null {
  return isRecord(payload) ? count(payload.applied_count) : null;
}

/** The confirmation after saving the Instance default; the count is the server's, never assumed. */
export function defaultSavedText(levels: ClassificationLevel[], classification: string | null, applied: boolean, appliedCount: number | null): string {
  const head = classification ? `Saved: the Instance default is ${levelLabel(levels, classification)}.` : "Saved: no Instance default.";
  if (!applied) return head;
  const classified = appliedCount === null ? "The server did not report how many Workspaces were" : `${appliedCount} ${appliedCount === 1 ? "Workspace was" : "Workspaces were"}`;
  return `${head} ${classified} classified; Workspaces with their own value or cleared on purpose were left as they are.`;
}

/** Where the Instance default comes from. */
export function defaultSourceText(model: InstanceDefault): string {
  if (model.environmentInEffect) {
    return `The instance's preset value is in effect (${levelLabel(model.levels, model.environmentValue ?? model.classification)}). Saving here replaces it.`;
  }
  if (!model.classification) return "No Instance default is set: new Workspaces start unclassified.";
  return "Set here.";
}

/** Whether the chosen value ("" = Not set) would change anything when saved. */
export function canSaveDraft(model: WorkspaceClassification, draft: string): boolean {
  if (model.source === "workspace") return draft !== (model.effective ?? "");
  // Without an own value any level is a change (it becomes the Workspace's own); clearing changes something only
  // while the Instance default fills the Workspace in.
  return draft !== "" || model.source === "instance_default";
}

export type DraftPreview = { heading: string; lines: EffectLine[]; warning: string | null; unstated: boolean };

/** "What this means here" for the saved value, or what the chosen value would mean once saved. */
export function draftPreview(model: WorkspaceClassification, draft: string): DraftPreview {
  if (draft === (model.effective ?? "")) {
    const lines = effectLines(model.effects);
    return { heading: "What this means here", lines, warning: model.effective ? null : NOT_SET_WARNING, unstated: !lines.length && Boolean(model.effective) };
  }
  if (!draft) return { heading: "What this would mean after saving", lines: [], warning: NOT_SET_WARNING, unstated: false };
  const lines = effectLines(model.levels.find((level) => level.value === draft)?.effects ?? null);
  return { heading: "What this would mean after saving", lines, warning: null, unstated: !lines.length };
}
