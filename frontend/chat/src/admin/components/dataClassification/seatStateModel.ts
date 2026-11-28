import type { SeatMode } from "./dataClassificationTypes";

// An answer without the _set flags: "forbidden" with in_effect true reads as unset.

export const SEAT_DEFAULT_HINT = "Default: allowed for public and internal data; from confidential up, an admin must allow it.";
export const ALLOWED_BY_DEFAULT_TEXT = "Allowed by default (public/internal data)";

export type SeatStateView = {
  mode: SeatMode | null;
  value: string;
  byDefault: boolean;
};

export function seatStateView(stored: SeatMode | null, inEffect: boolean | null, set: boolean | null = null): SeatStateView {
  if (stored === null) return { mode: null, value: "Unknown", byDefault: false };
  const unset = set === false || (set === null && stored === "forbidden" && inEffect === true);
  if (unset) {
    return inEffect === true
      ? { mode: "allowed", value: ALLOWED_BY_DEFAULT_TEXT, byDefault: true }
      : { mode: "forbidden", value: "Not allowed by default", byDefault: true };
  }
  return stored === "allowed"
    ? { mode: "allowed", value: "Allowed", byDefault: false }
    : { mode: "forbidden", value: "Not allowed", byDefault: false };
}

export function readSeatSet(payload: unknown, key: "seat_mode_set" | "codex_seat_mode_set"): boolean | null {
  const value = typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>)[key] : null;
  return typeof value === "boolean" ? value : null;
}

export function readSeatInEffect(payload: unknown): boolean | null {
  const value = typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>).in_effect : null;
  return typeof value === "boolean" ? value : null;
}
