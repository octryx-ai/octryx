import type { SeatMode } from "./dataClassificationTypes";

// The state people see for a seat switch (allow by default). The seat-mode answer reports the stored
// switch (`seat_mode` / `codex_seat_mode`, "forbidden" when never set), whether it was ever set (`seat_mode_set` /
// `codex_seat_mode_set`, backend) and whether a seat session can run (`in_effect` / `codex_in_effect`). An unset
// switch follows the default: open at public and internal data (backend seat_policy.default_seat_mode). An answer
// without the `_set` flags: "forbidden" with in_effect true is read as unset. Pure: no React.

export const SEAT_DEFAULT_HINT = "Default: allowed for public and internal data; from confidential up, an admin must allow it.";
export const ALLOWED_BY_DEFAULT_TEXT = "Allowed by default (public/internal data)";

export type SeatStateView = {
  /** The mode the switch shows and the bounds act on: "allowed" also when only the default allows it. */
  mode: SeatMode | null;
  /** The word next to the switch. */
  value: string;
  byDefault: boolean;
};

/** `set`: the server's `_set` flag; null when it did not send one. */
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

/** A `_set` flag of the seat-mode answer (`seat_mode_set` / `codex_seat_mode_set`); null when the server did not say. */
export function readSeatSet(payload: unknown, key: "seat_mode_set" | "codex_seat_mode_set"): boolean | null {
  const value = typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>)[key] : null;
  return typeof value === "boolean" ? value : null;
}

/** `in_effect` of the Claude seat in the seat-mode answer; null when the server did not say. */
export function readSeatInEffect(payload: unknown): boolean | null {
  const value = typeof payload === "object" && payload !== null ? (payload as Record<string, unknown>).in_effect : null;
  return typeof value === "boolean" ? value : null;
}
