import { readableCitation } from "../../../admin/components/workspaceKnowledge/KnowledgeCitation";
import { SidePanel } from "../../../layout/SidePanel";
import { presentFact } from "../relationshipPresenter";
import { concernsEntity, sourceText, type ExploreFact } from "./exploreModel";

type Props = {
  entity: string;
  facts: ExploreFact[];
  canShowGraph: boolean;
  // "Open as page" (design system); absent when the entity already is the page.
  pageHref?: string;
  mode?: "panel" | "page";
  onSearchFor: (name: string) => void;
  onShowInGraph: () => void;
  onSelectEntity: (name: string) => void;
  onClose: () => void;
};

// Explore → List: the selected entity in the side panel over the dimmed list (design system), or as a page. Its
// relationships among the loaded ones, each with the source it was read from, and the ways on: Search for it, or
// see its neighbourhood in the graph.
export function ExploreEntityPanel({
  entity, facts, canShowGraph, pageHref, mode = "panel", onSearchFor, onShowInGraph, onSelectEntity, onClose,
}: Props) {
  const own = facts.filter((fact) => concernsEntity(fact, entity));
  const sources = new Set(own.map((fact) => fact.source_title).filter(Boolean)).size;
  const subtitle = own.length
    ? `${own.length} ${own.length === 1 ? "relationship" : "relationships"} · ${sources} ${sources === 1 ? "source" : "sources"}`
    : "No relationship of this entity is loaded.";
  const footer = <>
    {canShowGraph ? <button type="button" className="admin-panel__action-btn" onClick={onShowInGraph}>Show in graph</button> : null}
    <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
      onClick={() => onSearchFor(entity)}>Search for this</button>
  </>;
  return (
    <SidePanel title={entity} subtitle={subtitle} onClose={onClose} pageHref={pageHref} mode={mode} footer={footer}
      headerActions={mode === "page" ? <button type="button" className="admin-panel__action-btn" onClick={onClose}>Back to the list</button> : undefined}
      testId="explore-entity">
      {own.length ? <table className="ds-table knowledge-explore__entity-table" aria-label={`Relationships of ${entity}`}>
        <thead><tr>
          <th className="ds-table__th" scope="col">Relationship</th>
          <th className="ds-table__th knowledge-explore__with" scope="col">With</th>
          <th className="ds-table__th is-grow" scope="col">Source</th>
        </tr></thead>
        <tbody>{own.map((fact, index) => {
          const view = presentFact(fact);
          const other = view.object && view.object.toLowerCase() !== entity.toLowerCase() ? view.object
            : view.subject.toLowerCase() !== entity.toLowerCase() ? view.subject : "";
          const source = sourceText(fact, readableCitation);
          return <tr key={`${fact.citation}-${index}`} className="ds-table__row">
            <td className="ds-table__td is-nowrap" title={view.headline}>{view.relation}</td>
            <td className="ds-table__td knowledge-explore__with">{other ? <button type="button" className="knowledge-explore__link"
              onClick={() => onSelectEntity(other)}>{other}</button> : null}</td>
            <td className="ds-table__td is-grow">{!source ? <span className="knowledge-explore__muted">No source</span>
              : fact.source_url ? <a href={fact.source_url} target="_blank" rel="noopener noreferrer"
                title={fact.citation || fact.source_title}>{source}</a>
                : <span title={fact.citation || fact.source_title}>{source}</span>}</td>
          </tr>;
        })}</tbody>
      </table> : <p className="ds-empty" role="status">Change the filter or search for it.</p>}
    </SidePanel>
  );
}
