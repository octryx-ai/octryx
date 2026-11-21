// The columns of the runs table in Operations › Live: run (with the item toggle), state, step, where, last sign of
// life, cost and the main action.
import type { DataTableColumn } from "../../../layout/DataTable";
import { StatusLabel } from "../../../layout/StatusLabel";
import { agoText, itemStateLabel, jobText, liveAge, runStateLabel } from "./operationsWords";
import { itemLastSeen, openHref, runMainAction } from "./operationsActions";
import { type OperationsLive, type OpsRun } from "./operationsTypes";
import { CostCell, ItemCell, Muted, RunCell, WhereCell, type Row } from "./OperationsLiveCells";

export function liveColumns({ live, elapsed, expanded, onToggle }: {
  live: OperationsLive | null;
  elapsed: number;
  expanded: (run: OpsRun) => boolean;
  onToggle: (run: OpsRun) => void;
}): DataTableColumn<Row>[] {
  return [
    { key: "run", header: "Run", grow: true, minWidth: "13rem", render: (row) => row.kind === "run"
      ? <RunCell run={row.run} open={expanded(row.run)} onToggle={() => onToggle(row.run)} />
      : <ItemCell item={row.item} /> },
    { key: "state", header: "State", nowrap: true, render: (row) => {
      const state = row.kind === "run"
        ? runStateLabel({ ...row.run, idleSeconds: row.run.idleSeconds === null ? null : row.run.idleSeconds + Math.round(elapsed) })
        : itemStateLabel(row.item);
      return <StatusLabel label={state.label} tone={state.tone} title={state.title} />;
    } },
    { key: "step", header: "Step", clip: "11rem", render: (row) => {
      const value = row.kind === "run" ? row.run.currentNode : jobText(row.item.job);
      return value ? <span title={value}>{value}</span> : <Muted text="Not started" />;
    } },
    { key: "where", header: "Where", clip: "11rem", render: (row) => <WhereCell row={row} devices={live?.devices ?? []} /> },
    { key: "seen", header: "Last sign of life", nowrap: true, render: (row) => {
      const at = row.kind === "run" ? row.run.lastEventAt : itemLastSeen(row.item);
      const text = agoText(liveAge(at, live?.generatedAt ?? null, elapsed));
      return text || <Muted text="No event yet" />;
    } },
    // The run's API cost and under it, on its own line, what its seat calls would cost via the API at list price
    // (never one sum). An item row shows neither: its device job reports one figure that mixes both.
    { key: "cost", header: "API cost · seat", nowrap: true, align: "end", render: (row) =>
      row.kind === "run" ? <CostCell run={row.run} /> : null },
    { key: "open", header: "Action", nowrap: true, render: (row) => {
      if (row.kind === "item") return null;
      const main = runMainAction(row.run);
      return main ? (
        <a className={`ds-btn ds-btn--sm${main.label === "Answer" ? " ds-btn--primary" : ""}`} data-testid="ops-open"
          href={openHref(row.run.sessionId, row.run.workspace?.id)}>{main.label}</a>
      ) : null;
    } },
  ];
}
