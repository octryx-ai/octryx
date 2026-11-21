// A run's Codex seat events (backend codex_seat_tickets.py) as history lines, in attention tone:
// - `seat_report_mismatch` (detail: fields, model, session_id): the device's report differed from the admitted call;
//   only the field names are shown, never values;
// - `seat_call_without_report` (detail: model, admitted_at, codex_session_id): the run sweep found an admitted call
//   with no report.
// Without a run the backend writes the same as audit actions `model_gateway.codex_seat.<kind>`. Pure: no React.

export const SEAT_EVENTS = ["seat_report_mismatch", "seat_call_without_report"] as const;
export const SEAT_EVENT_AUDIT_LABELS: Record<string, string> = {
  "model_gateway.codex_seat.seat_report_mismatch": "Seat call report did not match",
  "model_gateway.codex_seat.seat_call_without_report": "Seat call without report",
};

// Shown like the platform's own steps: a quiet attention label "Needs a look" and the sentence beside it.
export type SeatEventLine = { title: string; auto: "Needs a look"; text: string; tone: "attention" };

// The backend's field names in words (an unknown name reads with spaces).
const FIELD_WORDS: Record<string, string> = { response_id: "response id", usage: "tokens" };

export function seatMismatchFields(fields: unknown): string[] {
  if (!Array.isArray(fields)) return [];
  return fields.filter((field): field is string => typeof field === "string" && /^[a-z0-9_]+$/.test(field))
    .map((field) => FIELD_WORDS[field] ?? field.replace(/_/g, " "));
}

/** The line for a seat event, or null for any other event. */
export function seatEventLine(kind: string, detail: Record<string, unknown>): SeatEventLine | null {
  if (kind === "seat_report_mismatch") {
    const fields = seatMismatchFields(detail.fields);
    const text = "The device's report did not match the admitted call";
    return { title: "Seat call", auto: "Needs a look", text: fields.length ? `${text}: ${fields.join(", ")}` : text, tone: "attention" };
  }
  if (kind === "seat_call_without_report") {
    return { title: "Seat call", auto: "Needs a look", text: "A seat call was admitted but the device sent no report", tone: "attention" };
  }
  return null;
}
