import { useEffect, useId, useState } from "react";
import {
  availabilityRows, availabilitySummary, lessRelevantStart, NO_MATCH_TEXT, resultCountLabel, searchRefusal,
} from "./knowledgeSearchPresenter";
import type { EvidenceHit, SearchResult } from "./workspaceKnowledgeTypes";
import { answerEvidenceKeys } from "./search/answerApi";
import { KnowledgeAnswer } from "./search/KnowledgeAnswer";
import { KnowledgeHitGroups } from "./search/KnowledgeHitGroups";
import { KnowledgeHitPreview } from "./search/KnowledgeHitPreview";
import { KnowledgeSearchFilters } from "./search/KnowledgeSearchFilters";
import { KnowledgeSearchProgress } from "./search/KnowledgeSearchProgress";
import { prepareAskInChat } from "./search/askInChat";
import { activeFacetCount, applyFacets, NO_FACETS, type SearchFacets } from "./search/searchFacets";
import { hitNumbers, presentedEvidence, presentHits } from "./search/searchFamilies";
import { searchTimingSummary, searchTimingText } from "./search/searchProgress";
import { queryTerms } from "./search/snippet";

type PresentedHits = ReturnType<typeof presentHits>;

export type SearchOutcome = {
  busy: boolean; error: string | null; errorState?: string | null; query: string; result: SearchResult | null;
};

function browserStore(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

// The answer of one search: narrow filters left that fold away, the hits
// grouped by source over the rest of the width; a chosen hit's preview opens as a side panel over them, on demand
// only. The per-mode availability is collapsed after the list. Above the hits a short answer cites the top
// hits by their numbers on the page. A reranked answer's low-relevance tail stays
// apart under "Less relevant", by order only, never with a score.
export function KnowledgeSearchResults({ workspaceId, search, isAdmin = false }: {
  workspaceId: string; search: SearchOutcome; isAdmin?: boolean;
}) {
  const id = useId();
  const [facets, setFacets] = useState<SearchFacets>(NO_FACETS);
  const [selected, setSelected] = useState<EvidenceHit | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(true);
  const choose = (hit: EvidenceHit | null) => setSelected(hit);
  const evidence = search.result?.evidence ?? [];
  // A new query starts unfiltered and without a chosen preview; a new result of the same query keeps the chosen hit
  // when it is still there.
  useEffect(() => { setFacets(NO_FACETS); setSelected(null); }, [search.query]);
  useEffect(() => {
    setSelected((current) => (current && evidence.some((hit) => hit.evidence_key === current.evidence_key) ? current : null));
    // Only a new result can drop the chosen hit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.result]);
  const tail = lessRelevantStart(evidence, search.result?.mode_states?.rerank);
  const leading = presentHits(applyFacets(tail === null ? evidence : evidence.slice(0, tail), facets));
  const trailing = presentHits(applyFacets(tail === null ? [] : evidence.slice(tail), facets), leading.length + 1);
  const activeFilters = activeFacetCount(facets);
  const timing = searchTimingSummary(search.result?.timings_ms);
  const timingDetail = searchTimingText(search.result?.timings_ms);
  // Only the status, the error and the results header are announced; the list itself is read on demand.
  return (
    <div className="knowledge-search__outcome">
      <div aria-live="polite" aria-busy={search.busy}>
        {search.busy ? <KnowledgeSearchProgress /> : null}
        {search.error ? <SearchError search={search} isAdmin={isAdmin} /> : null}
        {search.result ? <div className="knowledge-search__results-head">
          <h2 id={`${id}-title`}>{resultCountLabel(evidence.length, search.query)}</h2>
          {evidence.length ? (
            <button type="button" className="admin-panel__action-btn" aria-expanded={filtersOpen} aria-controls={`${id}-filters`}
              data-testid="search-filters-toggle" onClick={() => setFiltersOpen(!filtersOpen)}>
              {filtersOpen ? "Hide filters" : `Filters${activeFilters ? ` (${activeFilters})` : ""}`}
            </button>
          ) : null}
          {timing ? <p className="knowledge-search__hint" data-testid="search-timing" title={timingDetail || undefined}>{timing}</p> : null}
        </div> : null}
      </div>
      {search.result ? <>
        {evidence.length === 0 ? (
          <p className="knowledge-search__empty">{NO_MATCH_TEXT}</p>
        ) : (
          <ResultsLayout id={id} workspaceId={workspaceId} query={search.query} evidence={evidence} facets={facets}
            setFacets={setFacets} filtersOpen={filtersOpen} leading={leading} trailing={trailing} selected={selected} choose={choose} />
        )}
        <SearchAvailability states={search.result.mode_states} />
      </> : null}
    </div>
  );
}

// The filters, the answer and the hit lists (the low-relevance tail apart), and the chosen hit's preview.
function ResultsLayout({ id, workspaceId, query, evidence, facets, setFacets, filtersOpen, leading, trailing, selected, choose }: {
  id: string; workspaceId: string; query: string; evidence: EvidenceHit[]; facets: SearchFacets;
  setFacets: (next: SearchFacets) => void; filtersOpen: boolean; leading: PresentedHits; trailing: PresentedHits;
  selected: EvidenceHit | null; choose: (hit: EvidenceHit | null) => void;
}) {
  const shown = leading.length + trailing.length;
  // The answer rests on the top hits of the whole answer, not on what the filters currently show, one per page
  // (and page family) first; it is asked as soon as the search result is in. KnowledgeAnswer compares the keys by value.
  const answerKeys = answerEvidenceKeys(presentedEvidence(presentHits(evidence)));
  const numberOf = hitNumbers([...leading, ...trailing]);
  const titleOf = new Map(evidence.map((hit) => [hit.evidence_key, hit.source_title] as const));
  const terms = queryTerms(query);
  const openCited = (key: string) => {
    const hit = evidence.find((entry) => entry.evidence_key === key);
    if (hit) choose(hit);
  };
  const askInChat = () => {
    const visible = [...leading, ...trailing].map((entry) => entry.hit);
    const href = prepareAskInChat(workspaceId, query, visible, browserStore());
    if (typeof window !== "undefined") window.location.assign(href);
  };
  return (
    <div className={`knowledge-search__layout${filtersOpen ? "" : " knowledge-search__layout--wide"}`}>
      {filtersOpen ? <KnowledgeSearchFilters id={`${id}-filters`} hits={evidence} facets={facets} onChange={setFacets} /> : null}
      <div className="knowledge-search__results" aria-labelledby={`${id}-title`}>
        <KnowledgeAnswer workspaceId={workspaceId} query={query} evidenceKeys={answerKeys}
          numberOf={numberOf} titleOf={titleOf} onOpen={openCited} onAskInChat={askInChat} />
        {shown === 0 ? <p className="knowledge-search__empty">No passage matches these filters.</p> : null}
        {leading.length ? (
          <KnowledgeHitGroups shown={leading} workspaceId={workspaceId} selectedKey={selected?.evidence_key ?? null}
            onSelect={choose} labelledBy={`${id}-title`} terms={terms} />
        ) : null}
        {trailing.length ? (
          <section aria-labelledby={`${id}-tail`} data-testid="search-less-relevant">
            <h3 id={`${id}-tail`} className="knowledge-search__tail-head">Less relevant</h3>
            <KnowledgeHitGroups shown={trailing} workspaceId={workspaceId} terms={terms}
              selectedKey={selected?.evidence_key ?? null} onSelect={choose} labelledBy={`${id}-tail`} />
          </section>
        ) : null}
      </div>
      {selected ? (
        <KnowledgeHitPreview workspaceId={workspaceId} hit={selected} terms={terms} onClose={() => choose(null)} />
      ) : null}
    </div>
  );
}

function SearchAvailability({ states }: { states?: Record<string, string> }) {
  const rows = availabilityRows(states);
  if (!rows.length) return null;
  return (
    <details className="knowledge-search__availability">
      <summary>Search availability: {availabilitySummary(rows)}</summary>
      <dl>{rows.map((row) => <div key={row.key}><dt>{row.label}</dt><dd>{row.state}</dd></div>)}</dl>
    </details>
  );
}

// An instance state (storage not set up, not reachable) reads as that state with its next step; any other refusal
// keeps the server's sentence.
function SearchError({ search, isAdmin }: { search: SearchOutcome; isAdmin: boolean }) {
  const refusal = searchRefusal(search.errorState, isAdmin);
  if (!refusal) return <p className="knowledge-search__error" role="alert">{search.error}</p>;
  return (
    <div className="knowledge-search__notice" role="status" data-testid="search-refusal">
      <p className="knowledge-search__notice-title">{refusal.title}</p>
      <p>{refusal.text}</p>
      {refusal.link ? <p><a href={refusal.link.href} target="_blank" rel="noopener noreferrer">{refusal.link.label}</a></p> : null}
    </div>
  );
}
