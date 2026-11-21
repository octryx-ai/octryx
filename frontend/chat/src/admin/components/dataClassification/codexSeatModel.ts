import type { SeatMode } from "./dataClassificationTypes";

// The Codex seat switch (backend): `agent_gateway_policy.codex_seat_mode`, saved through the same
// `PUT /api/v1/workspaces/{id}/agent-gateway/seat-mode` as the Claude seat, with `{codex_seat_mode}` as the body.
// The server merges that one key into the stored policy, so the other policy keys stay as they are.
//   GET/PUT answer: {seat_mode, in_effect, reason, codex_seat_mode, codex_in_effect, codex_reason, can_edit}

export const CODEX_SEAT_LABEL = "Codex with your own ChatGPT subscription";
export const CODEX_SEAT_EXPLANATION = "People use their own ChatGPT subscription. Traffic goes through the Octryx gateway, logged and counted.";
export const CODEX_SEAT_CONDITIONS = "The same classification rules apply as for the Claude seat. No company models.";

export type CodexSeat = { mode: SeatMode | null; inEffect: boolean | null; reason: string | null };

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;

export function readCodexSeat(payload: unknown): CodexSeat {
  if (!isRecord(payload)) return { mode: null, inEffect: null, reason: null };
  const mode = payload.codex_seat_mode;
  return {
    mode: mode === "allowed" || mode === "forbidden" ? mode : null,
    inEffect: typeof payload.codex_in_effect === "boolean" ? payload.codex_in_effect : null,
    reason: typeof payload.codex_reason === "string" && payload.codex_reason ? payload.codex_reason : null,
  };
}

/** The save body: only the Codex key, so the server keeps every other policy key. */
export function codexSeatBody(allowed: boolean): { codex_seat_mode: SeatMode } {
  return { codex_seat_mode: allowed ? "allowed" : "forbidden" };
}

/**
 * The hint when the Workspace does not allow the Codex engine (the switch still saves; the gateway refuses Codex
 * seat sessions with `engine_not_allowed_in_workspace` until it is allowed). Null when allowed or unknown.
 */
export function codexEngineHint(allowedEngines: string[] | null): string | null {
  if (!allowedEngines || allowedEngines.includes("codex")) return null;
  return "Codex is not an allowed coding engine in this Workspace, so Codex seat sessions are refused until a Workspace admin allows it under Coding tools & devices › Coding engine.";
}

/** The confirmation after a save. */
export function codexSeatSavedText(allowed: boolean): string {
  return allowed ? "Codex with a ChatGPT subscription is allowed here." : "Codex with a ChatGPT subscription is no longer allowed here.";
}
