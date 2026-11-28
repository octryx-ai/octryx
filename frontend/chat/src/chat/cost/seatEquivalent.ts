// Seat and API figures are always shown apart and never added: no function here takes both.

export type SeatFigures = { equivalentUsd: number; unpricedCalls: number };
export type SeatLabels = { equivalent: string; unpriced: string };

// The backend's own wording, for a response that carries no labels.
export const SEAT_LABELS: SeatLabels = {
  equivalent: "would cost via API (list price)",
  unpriced: "no list price (seat only)",
};

export const NO_SEAT: SeatFigures = { equivalentUsd: 0, unpricedCalls: 0 };

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const money = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0);
const calls = (value: unknown): number =>
  (typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.round(value) : 0);
const label = (value: unknown, fallback: string): string => (typeof value === "string" && value.trim() ? value.trim() : fallback);

export function readSeatLabels(value: unknown): SeatLabels {
  const labels = record(value);
  return {
    equivalent: label(labels?.api_equivalent_usd, SEAT_LABELS.equivalent),
    unpriced: label(labels?.unpriced_calls, SEAT_LABELS.unpriced),
  };
}

export function readSeat(item: unknown, equivalentKey: string, unpricedKey: string): SeatFigures {
  const body = record(item);
  return { equivalentUsd: money(body?.[equivalentKey]), unpricedCalls: calls(body?.[unpricedKey]) };
}

export function sumSeat(rows: SeatFigures[]): SeatFigures {
  return rows.reduce<SeatFigures>((sum, row) => ({
    equivalentUsd: sum.equivalentUsd + money(row.equivalentUsd),
    unpricedCalls: sum.unpricedCalls + calls(row.unpricedCalls),
  }), { ...NO_SEAT });
}

export function hasSeat(figures: SeatFigures): boolean {
  return figures.equivalentUsd > 0 || figures.unpricedCalls > 0;
}

export function usdText(usd: number): string {
  const value = money(usd);
  if (value > 0 && value < 0.005) return "<$0.01";
  return `$${value.toFixed(2)}`;
}

export function callsText(count: number): string {
  return `${count} call${count === 1 ? "" : "s"}`;
}

export function seatHeading(labels: SeatLabels = SEAT_LABELS): string {
  return `Seat: ${labels.equivalent}`;
}

export function unpricedHeading(labels: SeatLabels = SEAT_LABELS): string {
  return labels.unpriced.charAt(0).toUpperCase() + labels.unpriced.slice(1);
}

export function unpricedText(count: number, labels: SeatLabels = SEAT_LABELS): string {
  const value = calls(count);
  return value ? `${labels.unpriced} · ${callsText(value)}` : "";
}

/** "" when only unpriced calls exist: "$0.00" would read as an estimate. */
export function seatAmountText(figures: SeatFigures): string {
  return figures.equivalentUsd > 0 ? usdText(figures.equivalentUsd) : "";
}

export function seatSentence(figures: SeatFigures, labels: SeatLabels = SEAT_LABELS): string {
  if (!hasSeat(figures)) return "";
  const amount = seatAmountText(figures);
  const parts = [amount ? `${seatHeading(labels)} ${amount}` : `Seat: ${unpricedText(figures.unpricedCalls, labels)}`];
  if (amount && figures.unpricedCalls) parts.push(unpricedText(figures.unpricedCalls, labels));
  return parts.join(" · ");
}

export function seatShort(figures: SeatFigures): string {
  if (!hasSeat(figures)) return "";
  const amount = seatAmountText(figures);
  return amount ? `Seat ${amount} (list price)` : `Seat: ${callsText(figures.unpricedCalls)}, no list price`;
}
