import { useEffect, useState } from "react";
import type { ExploreFilter, FilterOption } from "./exploreModel";

type Props = {
  filter: ExploreFilter;
  // What the type choice means in the current view: "Kind of relationship" (List) or "Entity type" (Graph).
  typeLabel: string;
  typeOptions: FilterOption[];
  originOptions: FilterOption[];
  busy: boolean;
  // False in the Graph view: its legend is the type filter there.
  showType?: boolean;
  onChange: (filter: ExploreFilter) => void;
};

// One filter bar for both Explore views: the name or term applies on submit (it asks the server), the type and
// the origin narrow at once. An origin choice is offered only when the shown items carry their origin.
export function ExploreFilterBar({ filter, typeLabel, typeOptions, originOptions, busy, showType = true, onChange }: Props) {
  const [text, setText] = useState(filter.text);
  useEffect(() => { setText(filter.text); }, [filter.text]);
  return (
    <form className="knowledge-explore__filters" role="search" aria-label="Filter Explore"
      onSubmit={(event) => { event.preventDefault(); onChange({ ...filter, text: text.trim() }); }}>
      <label className="knowledge-explore__field knowledge-explore__field--text">
        <span>Entity or term</span>
        <input type="search" className="admin-panel__input" value={text} maxLength={500}
          placeholder="e.g. PostgreSQL, Issuing IAM, timeouts" onChange={(event) => setText(event.target.value)} />
      </label>
      {showType ? <label className="knowledge-explore__field">
        <span>{typeLabel}</span>
        <select className="admin-panel__input" value={filter.type} disabled={!typeOptions.length}
          onChange={(event) => onChange({ ...filter, type: event.target.value })}>
          <option value="">All</option>
          {typeOptions.map((option) => <option key={option.value} value={option.value}>
            {option.label} ({option.count})</option>)}
        </select>
      </label> : null}
      {originOptions.length ? <label className="knowledge-explore__field">
        <span>Origin</span>
        <select className="admin-panel__input" value={filter.origin}
          onChange={(event) => onChange({ ...filter, origin: event.target.value })}>
          <option value="">All</option>
          {originOptions.map((option) => <option key={option.value} value={option.value}>
            {option.label} ({option.count})</option>)}
        </select>
      </label> : null}
      <div className="knowledge-explore__filter-actions">
        <button type="submit" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}>
          {busy ? "Loading…" : "Show"}</button>
        {filter.text || filter.type || filter.origin ? <button type="button" className="admin-panel__action-btn"
          onClick={() => { setText(""); onChange({ text: "", type: "", origin: "" }); }}>Clear</button> : null}
      </div>
    </form>
  );
}
