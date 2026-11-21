import { seatAmountText, SEAT_LABELS, unpricedText, type SeatFigures, type SeatLabels } from "./seatEquivalent";
import "./seat-cost.css";

// A cell under a "Seat: would cost via API (list price)" heading: the amount, and under it the calls whose model has
// no list price with their count. Never an estimate for those, and never the API cost added in.
export function SeatCell({ figures, labels = SEAT_LABELS, strong = false, empty = "—" }: {
  figures: SeatFigures;
  labels?: SeatLabels;
  strong?: boolean;
  // What a row without seat use shows.
  empty?: string;
}) {
  const amount = seatAmountText(figures);
  const unpriced = unpricedText(figures.unpricedCalls, labels);
  if (!amount && !unpriced) return <span className="seat-cost__none">{empty}</span>;
  return (
    <span className="seat-cost" data-testid="seat-cost">
      {amount ? <span className={strong ? "seat-cost__amount seat-cost__amount--strong" : "seat-cost__amount"}>{amount}</span> : null}
      {unpriced ? <span className="seat-cost__unpriced" data-testid="seat-unpriced">{unpriced}</span> : null}
    </span>
  );
}
