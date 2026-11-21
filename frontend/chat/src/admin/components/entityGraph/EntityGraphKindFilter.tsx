// Advanced › Relationship kinds: hide relationships of a kind ("requires", "moved to", "removed" …) from the
// drawing. The entities stay; only the lines go. Offered when the view has more than one kind.
import { humanizeRelation } from "./entityGraphDetailModel";

type Props = { kinds: [string, number][]; hidden: Set<string>; onToggle: (kind: string) => void };

export function EntityGraphKindFilter({ kinds, hidden, onToggle }: Props) {
  if (kinds.length < 2) return null;
  return <div className="entity-graph__legend" role="group" aria-label="Relationship kinds: click to hide or show">
    {kinds.map(([kind, count]) => <button key={kind} type="button" data-testid="kg-kind-chip" title={kind}
      className={`entity-graph__legend-item${hidden.has(kind) ? " entity-graph__legend-item--off" : ""}`}
      aria-pressed={!hidden.has(kind)} onClick={() => onToggle(kind)}>
      {humanizeRelation(kind)} ({count})
    </button>)}
  </div>;
}
