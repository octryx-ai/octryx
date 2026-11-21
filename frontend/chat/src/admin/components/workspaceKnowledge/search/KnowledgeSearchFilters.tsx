import { useId } from "react";

import { activeFacetCount, facetOptions, NO_FACETS, TIME_WINDOWS, type SearchFacets, type TimeWindow } from "./searchFacets";
import type { EvidenceHit } from "../workspaceKnowledgeTypes";

// The filters left of the results: source, space or project, time. They narrow the returned hits in the browser;
// only choices that match a hit are offered, each with its count.
export function KnowledgeSearchFilters({ id: panelId, hits, facets, onChange }: {
  id?: string;
  hits: EvidenceHit[];
  facets: SearchFacets;
  onChange: (next: SearchFacets) => void;
}) {
  const id = useId();
  const options = facetOptions(hits);
  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value]);
  return (
    <aside id={panelId} className="knowledge-search__filters" aria-label="Filter results" data-testid="search-filters">
      {options.kinds.length > 1 ? (
        <fieldset className="knowledge-search__filter">
          <legend>Source</legend>
          {options.kinds.map((option) => (
            <label key={option.value} className="admin-panel__checkbox">
              <input type="checkbox" checked={facets.kinds.includes(option.value)}
                onChange={() => onChange({ ...facets, kinds: toggle(facets.kinds, option.value) })} />
              {option.label} <span className="knowledge-search__count">{option.count}</span>
            </label>
          ))}
        </fieldset>
      ) : null}
      {options.containers.length ? (
        <fieldset className="knowledge-search__filter">
          <legend>Space or project</legend>
          {options.containers.map((option) => (
            <label key={option.value} className="admin-panel__checkbox">
              <input type="checkbox" checked={facets.containers.includes(option.value)}
                onChange={() => onChange({ ...facets, containers: toggle(facets.containers, option.value) })} />
              {option.label} <span className="knowledge-search__count">{option.count}</span>
            </label>
          ))}
        </fieldset>
      ) : null}
      <label className="admin-panel__field knowledge-search__filter" htmlFor={`${id}-time`}>
        <span>Time</span>
        <select id={`${id}-time`} value={facets.within}
          onChange={(event) => onChange({ ...facets, within: event.target.value as TimeWindow })}>
          {TIME_WINDOWS.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
        </select>
      </label>
      {activeFacetCount(facets) ? (
        <button type="button" className="knowledge-search__toggle" onClick={() => onChange(NO_FACETS)}>Clear filters</button>
      ) : null}
    </aside>
  );
}
