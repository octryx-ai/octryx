import type { SeatMode } from "./dataClassificationTypes";

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

// Only the Codex key: the server merges it and keeps every other policy key.
export function codexSeatBody(allowed: boolean): { codex_seat_mode: SeatMode } {
  return { codex_seat_mode: allowed ? "allowed" : "forbidden" };
}

// The switch still saves; the gateway refuses Codex seat sessions until the engine is allowed.
export function codexEngineHint(allowedEngines: string[] | null): string | null {
  if (!allowedEngines || allowedEngines.includes("codex")) return null;
  return "Codex is not an allowed coding engine in this Workspace, so Codex seat sessions are refused until a Workspace admin allows it under Coding tools & devices › Coding engine.";
}

export function codexSeatSavedText(allowed: boolean): string {
  return allowed ? "Codex with a ChatGPT subscription is allowed here." : "Codex with a ChatGPT subscription is no longer allowed here.";
}
