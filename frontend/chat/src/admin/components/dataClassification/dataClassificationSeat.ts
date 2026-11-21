// Data classification and seat sessions: refusal reasons in words and when the seat switch is blocked.
import type { SeatMode, WorkspaceClassification } from "./dataClassificationTypes";

const SEAT_REASON_TEXT: Record<string, string> = {
  seat_mode_forbidden: "this Workspace does not allow them",
  codex_seat_mode_forbidden: "this Workspace does not allow Codex with a ChatGPT subscription",
  seat_requires_governed_routing: "this Workspace's policy requires governed routing",
  seat_classification_too_sensitive: "the data classification is too sensitive for them",
  seat_classification_unresolved: "no data classification is set",
  // The classification policy requires governed routing for this level.
  seat_classification_requires_governed_routing: "the classification policy requires governed routing for this level",
  policy_invalid: "the agent gateway policy of this Workspace is invalid",
};

export function seatReasonText(reason: string | null): string {
  if (!reason) return "they are not allowed here";
  return SEAT_REASON_TEXT[reason] || `refused (${reason})`;
}

// Reasons that block seat sessions whatever the Workspace's own switch says.
const CLASSIFICATION_REASONS = new Set(["seat_classification_too_sensitive", "seat_classification_unresolved",
  "seat_classification_requires_governed_routing"]);
const SWITCH_INDEPENDENT_REASONS = new Set(["seat_requires_governed_routing", ...Array.from(CLASSIFICATION_REASONS)]);

/** The code that blocks seat sessions whatever the stored switch says (from the saved classification), or null. */
function seatBlockReason(model: WorkspaceClassification): string | null {
  const effects = model.effects;
  if (!effects) return model.effective ? null : "seat_classification_unresolved";
  if (effects.seatModeAllowed !== false || !effects.seatModeReason) return null;
  return SWITCH_INDEPENDENT_REASONS.has(effects.seatModeReason) ? effects.seatModeReason : null;
}

/** Why the "Allow seat sessions" switch cannot be turned on (from the saved classification), or null when it can. */
export function seatToggleBlock(model: WorkspaceClassification): string | null {
  const reason = seatBlockReason(model);
  return reason ? `Not available: ${seatReasonText(reason)}.` : null;
}

/**
 * F5 (judge-1191-1192): while seat is blocked, only turning the switch on is disabled. A stored "allowed" switch can
 * always be turned off (to forbidden), so the switch is usable then and the card says it is allowed but blocked.
 */
export function seatSwitchDisabled(model: WorkspaceClassification, seatMode: SeatMode | null): boolean {
  if (!model.canEdit || seatMode === null) return true;
  return seatMode !== "allowed" && seatBlockReason(model) !== null;
}

/** The line under the switch while seat is blocked: the reason, and for a stored "allowed" switch that it is blocked. */
export function seatSwitchNote(model: WorkspaceClassification, seatMode: SeatMode | null): string | null {
  const reason = seatBlockReason(model);
  if (!reason) return null;
  if (seatMode === "allowed") {
    return `Stored as allowed, but blocked: ${seatReasonText(reason)}. Turning it off is still possible.`;
  }
  return `Not available: ${seatReasonText(reason)}.`;
}

/** The seat refusal code when the classification refuses seat sessions (the Agents area then links to the card). */
export function seatClassificationRefusal(model: WorkspaceClassification | null): string | null {
  if (!model) return null;
  // An unclassified Workspace has no effects of its own: seat mode fails closed there (seat_policy).
  if (!model.effective) return "seat_classification_unresolved";
  const effects = model.effects;
  if (!effects || effects.seatModeAllowed !== false || !effects.seatModeReason) return null;
  return CLASSIFICATION_REASONS.has(effects.seatModeReason) ? effects.seatModeReason : null;
}
