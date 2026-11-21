// The seat's API equivalent beside the real API cost (backend). A seat call (Claude or ChatGPT
// subscription) costs the platform nothing; the platform shows what the same call WOULD cost through the API at list
// price. The two figures are always shown apart and never added together: no function here takes both. A model
// without a list price gets no estimate; its calls are counted and shown as "no list price (seat only)".

export type SeatFigures = { equivalentUsd: number; unpricedCalls: number };
export type SeatLabels = { equivalent: string; unpriced: string };

// The backend's own wording (`labels` of the seat-usage report); used where a response carries no labels.
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

/** The labels a response sends (`{api_equivalent_usd, unpriced_calls}`), else the backend's default wording. */
export function readSeatLabels(value: unknown): SeatLabels {
  const labels = record(value);
  return {
    equivalent: label(labels?.api_equivalent_usd, SEAT_LABELS.equivalent),
    unpriced: label(labels?.unpriced_calls, SEAT_LABELS.unpriced),
  };
}

/** The seat figures of one object under its own keys (`seat_api_equivalent` on Work runs, `…_usd` in Operations). */
export function readSeat(item: unknown, equivalentKey: string, unpricedKey: string): SeatFigures {
  const body = record(item);
  return { equivalentUsd: money(body?.[equivalentKey]), unpricedCalls: calls(body?.[unpricedKey]) };
}

/** Sums seat figures with seat figures only (a story's runs, an epic's stories). */
export function sumSeat(rows: SeatFigures[]): SeatFigures {
  return rows.reduce<SeatFigures>((sum, row) => ({
    equivalentUsd: sum.equivalentUsd + money(row.equivalentUsd),
    unpricedCalls: sum.unpricedCalls + calls(row.unpricedCalls),
  }), { ...NO_SEAT });
}

export function hasSeat(figures: SeatFigures): boolean {
  return figures.equivalentUsd > 0 || figures.unpricedCalls > 0;
}

/** "$0.41", "<$0.01" for a fraction of a cent, "$0.00" for nothing. */
export function usdText(usd: number): string {
  const value = money(usd);
  if (value > 0 && value < 0.005) return "<$0.01";
  return `$${value.toFixed(2)}`;
}

/** "1 call", "3 calls". */
export function callsText(count: number): string {
  return `${count} call${count === 1 ? "" : "s"}`;
}

/** "Seat: would cost via API (list price)": the heading of the figure (column header, label of a count). */
export function seatHeading(labels: SeatLabels = SEAT_LABELS): string {
  return `Seat: ${labels.equivalent}`;
}

/** "No list price (seat only)": the label as a heading. */
export function unpricedHeading(labels: SeatLabels = SEAT_LABELS): string {
  return labels.unpriced.charAt(0).toUpperCase() + labels.unpriced.slice(1);
}

/** "no list price (seat only) · 3 calls"; "" without such calls. Never an amount. */
export function unpricedText(count: number, labels: SeatLabels = SEAT_LABELS): string {
  const value = calls(count);
  return value ? `${labels.unpriced} · ${callsText(value)}` : "";
}

/**
 * The amount for a cell under a seat heading: "$10.40"; "" when only unpriced calls exist (the cell shows
 * `unpricedText` alone then, never "$0.00", which would read as an estimate) or nothing was used on a seat.
 */
export function seatAmountText(figures: SeatFigures): string {
  return figures.equivalentUsd > 0 ? usdText(figures.equivalentUsd) : "";
}

/**
 * The whole figure in one sentence part, for a line without a column heading:
 * "Seat: would cost via API (list price) $10.40", plus "· no list price (seat only) · 3 calls"; "" without seat use.
 */
export function seatSentence(figures: SeatFigures, labels: SeatLabels = SEAT_LABELS): string {
  if (!hasSeat(figures)) return "";
  const amount = seatAmountText(figures);
  const parts = [amount ? `${seatHeading(labels)} ${amount}` : `Seat: ${unpricedText(figures.unpricedCalls, labels)}`];
  if (amount && figures.unpricedCalls) parts.push(unpricedText(figures.unpricedCalls, labels));
  return parts.join(" · ");
}

/** The short form for a narrow place (phone card, story row): "Seat $10.40 (list price)"; the title holds the long one. */
export function seatShort(figures: SeatFigures): string {
  if (!hasSeat(figures)) return "";
  const amount = seatAmountText(figures);
  return amount ? `Seat ${amount} (list price)` : `Seat: ${callsText(figures.unpricedCalls)}, no list price`;
}
