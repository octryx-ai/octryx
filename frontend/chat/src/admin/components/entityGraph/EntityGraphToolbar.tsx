// The graph's top bar: the count line ("128 of 150 entities · 212 relationships"), a bounded-view note with the
// ways to narrow down, the entity list switch and "Advanced" (window size, graph layers, structure nodes, how to
// read). The search field only shows where no page filter bar searches (outside Knowledge › Explore).

import type { ReactNode } from "react";

export const MAX_NODE_OPTIONS = [50, 100, 150];

type Props = {
  query: string;
  onQueryChange: (value: string) => void;
  onSearch: () => void;
  canReset: boolean;
  onReset: () => void;
  maxNodes: number;
  onMaxNodes: (value: number) => void;
  // Structure nodes and literal values (entityGraphNoise.ts), hidden by default.
  showNoise?: boolean;
  onShowNoise?: (value: boolean) => void;
  count: string | null;
  // A passing message about the last Expand ("12 new around score-api", "Nothing new around …").
  note?: string;
  truncated: boolean;
  listOpen?: boolean;
  onListOpen?: (open: boolean) => void;
  layers?: ReactNode;
  // Advanced › Relationship kinds (EntityGraphKindFilter), when the view has more than one.
  kinds?: ReactNode;
  trail?: ReactNode;
  // False when the page's own filter bar searches (Knowledge → Explore).
  showSearch?: boolean;
};

function Advanced(props: Props) {
  return <details className="kg-advanced">
    <summary className="admin-panel__action-btn kg-bar__btn">Advanced</summary>
    <div className="kg-advanced__panel">
      <label className="kg-advanced__field">
        <span>Entities per view</span>
        <select className="admin-panel__input" value={props.maxNodes}
          onChange={(event) => props.onMaxNodes(Number(event.target.value))}>
          {MAX_NODE_OPTIONS.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      {props.layers ? <div className="kg-advanced__field"><span>Graph layers</span>{props.layers}</div> : null}
      {props.kinds ? <div className="kg-advanced__field"><span>Relationship kinds</span>{props.kinds}</div> : null}
      {props.onShowNoise ? <label className="admin-panel__checkbox kg-advanced__check">
        <input type="checkbox" checked={Boolean(props.showNoise)}
          onChange={(event) => props.onShowNoise?.(event.target.checked)} />
        Show documents, chapters and literal values
      </label> : null}
      <ul className="kg-advanced__help">
        <li>Click an entity to see its relationships; double-click or Expand loads its neighbourhood.</li>
        <li>The legend filters by type: click hides a type, double-click shows it alone.</li>
        <li>Scroll or + / − to zoom, drag or arrow keys to pan, 0 to fit.</li>
        <li>Search matches names and relationship statements; connected entities are shown for context.</li>
      </ul>
    </div>
  </details>;
}

export function EntityGraphToolbar(props: Props) {
  return <div className="kg-bar">
    {props.showSearch === false ? null : <form className="kg-bar__search" role="search"
      onSubmit={(event) => { event.preventDefault(); props.onSearch(); }}>
      <input type="search" className="admin-panel__input" aria-label="Search graph entities"
        placeholder="Search entity names or relationship statements" value={props.query}
        onChange={(event) => props.onQueryChange(event.target.value)} />
      <button type="submit" className="admin-panel__action-btn admin-panel__action-btn--primary">Search</button>
      {props.canReset ? <button type="button" className="admin-panel__action-btn" onClick={props.onReset}>Reset</button> : null}
    </form>}
    <div className="kg-bar__row">
      <div className="kg-bar__status">
        {props.count ? <p className="kg-bar__count" role="status">{props.count}</p> : null}
        {props.count && props.truncated ? <span className="kg-bar__bounded"
          title="This Workspace holds more than one view shows. Narrow down by search, by type in the legend, or expand one entity.">
          Bounded view · narrow by search, type or Expand</span> : null}
        {props.note ? <span className="kg-bar__note" role="status">{props.note}</span> : null}
        {props.trail}
      </div>
      <div className="kg-bar__actions">
        {props.onListOpen ? <button type="button" className="admin-panel__action-btn kg-bar__btn kg-bar__list-toggle" aria-pressed={Boolean(props.listOpen)}
          onClick={() => props.onListOpen?.(!props.listOpen)}>Entity list</button> : null}
        <Advanced {...props} />
      </div>
    </div>
  </div>;
}
