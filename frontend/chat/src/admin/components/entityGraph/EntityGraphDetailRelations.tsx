// The selected entity's available relationships as scan-friendly rows: direction and the other entity,
// the relation in words (raw code in the tooltip), the statement it was read from and its source. A
// relationship whose two ends are the same stored entity is labelled as such, never hidden.

import type { RelationRow } from "./entityGraphDetailModel";
import { EntityGraphCitation } from "./EntityGraphCitation";

type Props = {
  rows: RelationRow[];
  workspaceId: string;
  onSelect: (id: string) => void;
  onFocusNode: (id: string) => void;
};

function Peer({ row, onSelect, onFocusNode }: Pick<Props, "onSelect" | "onFocusNode"> & { row: RelationRow }) {
  return <button type="button" className="entity-graph__link"
    title={row.peerInView ? `Show the details of ${row.peerName}` : `Show the neighbourhood of ${row.peerName} (not in this view)`}
    onClick={() => (row.peerInView ? onSelect(row.peerId) : onFocusNode(row.peerId))}>
    {row.peerName}
  </button>;
}

function Relation({ row }: { row: RelationRow }) {
  return <span className="entity-graph__relation-type" title={row.code}>{row.relation}</span>;
}

function Heading({ row, onSelect, onFocusNode }: Pick<Props, "onSelect" | "onFocusNode"> & { row: RelationRow }) {
  if (row.kind === "self") {
    return <>
      <span className="entity-graph__relation-dir" aria-hidden="true">↻</span>
      <Relation row={row} />{" "}
      <span className="entity-graph__self">refers to itself (same entity on both ends)</span>
    </>;
  }
  if (row.kind === "out") {
    return <>
      <span className="entity-graph__relation-dir" aria-hidden="true">→</span>
      <span className="entity-graph__sr-only">This entity </span>
      <Relation row={row} />{" "}
      <Peer row={row} onSelect={onSelect} onFocusNode={onFocusNode} />
    </>;
  }
  return <>
    <span className="entity-graph__relation-dir" aria-hidden="true">←</span>
    <Peer row={row} onSelect={onSelect} onFocusNode={onFocusNode} />{" "}
    <Relation row={row} />{" "}
    <span className="entity-graph__relation-this">this entity</span>
  </>;
}

export function EntityGraphDetailRelations({ rows, workspaceId, onSelect, onFocusNode }: Props) {
  if (!rows.length) return <p className="admin-panel__note">No readable relationships are available for this entity.</p>;
  return <ol className="entity-graph__relations">
    {rows.map((row) => <li key={row.key}
      className={`entity-graph__relation${row.inView ? "" : " entity-graph__relation--outside"}`}>
      <div className="entity-graph__relation-head">
        <Heading row={row} onSelect={onSelect} onFocusNode={onFocusNode} />
        {row.inView ? null : <span className="entity-graph__relation-scope">not in this view</span>}
      </div>
      {row.source.description ? <p className="entity-graph__relation-statement">{row.source.description}</p> : null}
      <EntityGraphCitation evidence={row.source} workspaceId={workspaceId} />
    </li>)}
  </ol>;
}
