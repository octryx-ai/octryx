import type { SeatMode, WorkspaceClassification } from "./dataClassificationTypes";

const SEAT_REASON_TEXT: Record<string, string> = {
  seat_mode_forbidden: "this Workspace does not allow them",
  codex_seat_mode_forbidden: "this Workspace does not allow Codex with a ChatGPT subscription",
  seat_requires_governed_routing: "this Workspace's policy requires governed routing",
  seat_classification_too_sensitive: "the data classification is too sensitive for them",
  seat_classification_unresolved: "no data classification is set",
  seat_classification_requires_governed_routing: "the classification policy requires governed routing for this level",
  policy_invalid: "the agent gateway policy of this Workspace is invalid",
};

export function seatReasonText(reason: string | null): string {
  if (!reason) return "they are not allowed here";
  return SEAT_REASON_TEXT[reason] || `refused (${reason})`;
}

const CLASSIFICATION_REASONS = new Set(["seat_classification_too_sensitive", "seat_classification_unresolved",
  "seat_classification_requires_governed_routing"]);
const SWITCH_INDEPENDENT_REASONS = new Set(["seat_requires_governed_routing", ...Array.from(CLASSIFICATION_REASONS)]);

function seatBlockReason(model: WorkspaceClassification): string | null {
  const effects = model.effects;
  if (!effects) return model.effective ? null : "seat_classification_unresolved";
  if (effects.seatModeAllowed !== false || !effects.seatModeReason) return null;
  return SWITCH_INDEPENDENT_REASONS.has(effects.seatModeReason) ? effects.seatModeReason : null;
}

export function seatToggleBlock(model: WorkspaceClassification): string | null {
  const reason = seatBlockReason(model);
  return reason ? `Not available: ${seatReasonText(reason)}.` : null;
}

/** A stored "allowed" switch can always be turned off, so only turning it on is disabled while seat is blocked. */
export function seatSwitchDisabled(model: WorkspaceClassification, seatMode: SeatMode | null): boolean {
  if (!model.canEdit || seatMode === null) return true;
  return seatMode !== "allowed" && seatBlockReason(model) !== null;
}

export function seatSwitchNote(model: WorkspaceClassification, seatMode: SeatMode | null): string | null {
  const reason = seatBlockReason(model);
  if (!reason) return null;
  if (seatMode === "allowed") {
    return `Stored as allowed, but blocked: ${seatReasonText(reason)}. Turning it off is still possible.`;
  }
  return `Not available: ${seatReasonText(reason)}.`;
}

export function seatClassificationRefusal(model: WorkspaceClassification | null): string | null {
  if (!model) return null;
  // An unclassified Workspace has no effects of its own: seat mode fails closed there (seat_policy).
  if (!model.effective) return "seat_classification_unresolved";
  const effects = model.effects;
  if (!effects || effects.seatModeAllowed !== false || !effects.seatModeReason) return null;
  return CLASSIFICATION_REASONS.has(effects.seatModeReason) ? effects.seatModeReason : null;
}
