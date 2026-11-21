import { MATCH_BASIS_ORDER, matchBasisLabel, type MatchBasis } from "./entityGraphMatches";
import { linkLabel, type RankedEntity } from "./entityGraphReading";

type Props = {
  ranked: RankedEntity[];
  bases: Map<string, MatchBasis>;
  query: string;
  selectedId: string;
  neighborIds: Set<string>;
  searching: boolean;
  onSelect: (id: string) => void;
};

type ItemProps = Pick<Props, "selectedId" | "neighborIds" | "onSelect"> & { entity: RankedEntity; basis: string };

function EntityItem({ entity, basis, selectedId, neighborIds, onSelect }: ItemProps) {
  const selected = entity.id === selectedId;
  const state = selected ? "selected" : neighborIds.has(entity.id) ? "linked" : selectedId ? "dimmed" : "idle";
  return <li>
    <button type="button" className="entity-graph__entity" data-state={state} data-matched={entity.matched || undefined}
      data-entity-id={entity.id} aria-pressed={selected} onClick={() => onSelect(entity.id)}>
      <span className="entity-graph__entity-name">{entity.name}</span>
      {basis ? <span className="entity-graph__entity-basis">{basis}</span> : null}
      <span className="entity-graph__entity-meta">
        {state === "linked" ? "Linked to selection · " : ""}{linkLabel(entity)}
      </span>
    </button>
  </li>;
}

// The primary reading path of the graph: every shown entity with its full name, ranked by its visible
// relationships. With a search, the matches come first, grouped by why they matched; the rest are
// their neighbours, shown for context.
export function EntityGraphEntityList({ ranked, bases, query, selectedId, neighborIds, searching, onSelect }: Props) {
  const order = (id: string) => MATCH_BASIS_ORDER.indexOf(bases.get(id) ?? "server");
  const matches = searching ? ranked.filter((entity) => entity.matched).sort((a, b) => order(a.id) - order(b.id)) : [];
  const rest = searching ? ranked.filter((entity) => !entity.matched) : ranked;
  const item = (entity: RankedEntity) => <EntityItem key={entity.id} entity={entity} selectedId={selectedId}
    basis={entity.matched && searching ? matchBasisLabel(bases.get(entity.id) ?? "server", query) : ""}
    neighborIds={neighborIds} onSelect={onSelect} />;
  return <section className="entity-graph__entities" aria-label="Entities in this view">
    {matches.length ? <>
      <h4 className="entity-graph__entities-head">Matches ({matches.length})</h4>
      <ol className="entity-graph__entity-list">{matches.map(item)}</ol>
    </> : null}
    {rest.length ? <>
      <h4 className="entity-graph__entities-head">
        {matches.length ? `Connected entities (${rest.length})` : `Entities by relationships (${rest.length})`}
      </h4>
      <ol className="entity-graph__entity-list">{rest.map(item)}</ol>
    </> : null}
  </section>;
}
