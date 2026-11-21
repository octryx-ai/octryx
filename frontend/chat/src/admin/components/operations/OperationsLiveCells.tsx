// Cells of the Operations live runs table: run and item names, where they work, cost, plus the state counts.
import { hasSeat, seatSentence, seatShort } from "../../../chat/cost/seatEquivalent";
import { costText, countTiles, itemMeta, runMeta } from "./operationsWords";
import { itemWhereText, whereText } from "./operationsWhere";
import { type OperationsLive, type OpsDevice, type OpsItem, type OpsRun } from "./operationsTypes";

export type Row = { kind: "run"; run: OpsRun } | { kind: "item"; run: OpsRun; item: OpsItem };

export function Muted({ text }: { text: string }) {
  return <span className="ops-muted">{text}</span>;
}

export function CountBar({ live }: { live: OperationsLive }) {
  return (
    <ul className="ops-counts" aria-label="Runs by state" data-testid="ops-counts">
      {countTiles(live.counts).map((tile) => (
        <li key={tile.key} className={`ds-card ops-count ops-count--${tile.tone}`} data-tone={tile.tone}>
          <span className="ops-count__label">{tile.label}</span>
          <span className="ops-count__value">{tile.value}</span>
        </li>
      ))}
    </ul>
  );
}

export function RunCell({ run, open, onToggle }: { run: OpsRun; open: boolean; onToggle: () => void }) {
  return (
    <div className="ops-run">
      {run.items.length ? (
        <button type="button" className="ops-toggle" aria-expanded={open} onClick={onToggle}
          aria-label={`${open ? "Hide" : "Show"} the ${run.items.length} items of ${run.title}`}
          title={`${open ? "Hide" : "Show"} ${run.items.length} items`} data-testid="ops-toggle">
          <svg viewBox="0 0 24 24" aria-hidden="true" className={open ? "is-open" : undefined}><path d="m9 6 6 6-6 6" /></svg>
        </button>
      ) : <span className="ops-toggle ops-toggle--none" aria-hidden="true" />}
      <span className="ops-two-lines">
        <span className="ops-strong">{run.title}</span>
        <span className="ops-muted">{runMeta(run) || "No Workspace"}</span>
      </span>
    </div>
  );
}

export function ItemCell({ item }: { item: OpsItem }) {
  return (
    <div className="ops-run ops-run--item">
      <span className="ops-two-lines">
        <span>{item.title}</span>
        <span className="ops-muted">{itemMeta(item)}</span>
      </span>
    </div>
  );
}

export function WhereCell({ row, devices }: { row: Row; devices: OpsDevice[] }) {
  if (row.kind === "item") {
    const detail = itemWhereText(row.item);
    return detail ? <span title={detail}>{detail}</span> : null;
  }
  const where = whereText(row.run.where, devices);
  // No stored target (where: null): the cell stays empty, it is not an error.
  if (!where.place) return null;
  return (
    <span className="ops-two-lines" title={[where.place, where.detail].filter(Boolean).join(" · ")}>
      <span>{where.place}</span>
      {where.detail ? <span className="ops-muted">{where.detail}</span> : null}
    </span>
  );
}

export function CostCell({ run }: { run: OpsRun }) {
  const api = costText(run.costUsd);
  return (
    <span className="ops-cost">
      {api ? <span title="API cost">{api}</span> : <Muted text="Not known" />}
      {hasSeat(run.seat) ? <span className="ops-muted" title={seatSentence(run.seat)} data-testid="ops-seat">{seatShort(run.seat)}</span> : null}
    </span>
  );
}
