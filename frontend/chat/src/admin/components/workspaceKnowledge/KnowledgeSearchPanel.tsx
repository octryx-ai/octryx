import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { KnowledgeSearchResults } from "./KnowledgeSearchResults";
import {
  activeOptionCount, DEFAULT_SEARCH_MODE, optionsLabel, relevanceStatus, SEARCH_MODES, searchHint, searchModeHint,
} from "./knowledgeSearchPresenter";
import { splitProducts } from "./workspaceKnowledgeRequest";
import { workspaceKnowledgeApi } from "./workspaceKnowledgeApi";
import { useKnowledgeSearch } from "./useKnowledgeSearch";
import { KnowledgeEntryOverview } from "../../../chat/knowledge/KnowledgeEntryOverview";
import { hasNoDocuments } from "../../../chat/knowledge/knowledgeEntryModel";
import { useKnowledgeEntryOverview, type EntryOverview } from "../../../chat/knowledge/useKnowledgeEntryOverview";
import { KnowledgeSearchStart } from "./search/KnowledgeSearchStart";
import "./knowledge-search.css";

// Knowledge → Search starts with the workspace status line (sources and their state, and actions); embedded uses
// show the search alone (`showOverview={false}`).
export function KnowledgeSearchPanel({ workspaceId, showOverview = true, isAdmin = false }: {
  workspaceId: string; showOverview?: boolean; isAdmin?: boolean;
}) {
  return showOverview ? <KnowledgeSearchEntry workspaceId={workspaceId} isAdmin={isAdmin} />
    : <KnowledgeSearchBody workspaceId={workspaceId} isAdmin={isAdmin} />;
}

function KnowledgeSearchEntry({ workspaceId, isAdmin }: { workspaceId: string; isAdmin: boolean }) {
  const overview = useKnowledgeEntryOverview(workspaceId);
  return <>
    <KnowledgeEntryOverview overview={overview} isAdmin={isAdmin} />
    <KnowledgeSearchBody workspaceId={workspaceId} emptyWorkspace={hasNoDocuments(overview.listing)} overview={overview}
      isAdmin={isAdmin} />
  </>;
}

// "Search for this" (Knowledge → Explore) hands a query over in the address (`q`); Search runs it once and removes it.
function takeHandedOverQuery(): string {
  if (typeof window === "undefined" || typeof window.location?.search !== "string") return "";
  const url = new URL(window.location.href);
  const query = (url.searchParams.get("q") ?? "").trim().slice(0, 2000);
  if (query) {
    url.searchParams.delete("q");
    window.history.replaceState(window.history.state, "", url.toString());
  }
  return query;
}

// The reranker's state before any search; null until (or unless) the settings read answers.
function useRerankerSettings(workspaceId: string): unknown {
  const [settings, setSettings] = useState<unknown>(null);
  useEffect(() => {
    let current = true;
    setSettings(null);
    Promise.resolve()
      .then(() => workspaceKnowledgeApi.settings(workspaceId))
      .then((value) => { if (current) setSettings(value); })
      .catch(() => undefined);
    return () => { current = false; };
  }, [workspaceId]);
  return settings;
}

// One search toolbar (§9.3): a single-line field, the primary "Search" and an "Options" disclosure for
// method, products and version. Enter submits; Escape clears the field, a second Escape leaves it.
function KnowledgeSearchBody({ workspaceId, emptyWorkspace = false, overview = null, isAdmin = false }: {
  workspaceId: string; emptyWorkspace?: boolean; overview?: EntryOverview | null; isAdmin?: boolean;
}) {
  const id = useId();
  const handedOver = useRef<string | null>(null);
  if (handedOver.current === null) handedOver.current = takeHandedOverQuery();
  const [query, setQuery] = useState(handedOver.current);
  const [mode, setMode] = useState(DEFAULT_SEARCH_MODE);
  const [products, setProducts] = useState("");
  const [version, setVersion] = useState("");
  const [optionsOpen, setOptionsOpen] = useState(false);
  const search = useKnowledgeSearch(workspaceId);
  const settings = useRerankerSettings(workspaceId);
  useEffect(() => {
    const first = handedOver.current;
    if (!first) return;
    handedOver.current = "";
    void search.submit({ query_text: first, mode: DEFAULT_SEARCH_MODE, limit: 10, products: null, version: null });
    // Runs once for the hand-off; later searches come from the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const relevance = relevanceStatus(settings, search.result?.mode_states?.rerank);

  const run = (text: string) => {
    const scope = splitProducts(products);
    void search.submit({
      query_text: text, mode, limit: 10,
      products: scope.length ? scope : null,
      version: scope.length && version.trim() ? version.trim() : null,
    });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(query);
  };
  // An example question goes into the field (so it can be changed) and runs at once.
  const ask = (question: string) => {
    setQuery(question);
    run(question);
  };
  const before = !search.busy && !search.result && !search.error;
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    if (query) setQuery("");
    else event.currentTarget.blur();
  };

  return (
    <KnowledgeSearchView id={id} workspaceId={workspaceId} search={search} relevance={relevance} emptyWorkspace={emptyWorkspace}
      isAdmin={isAdmin} overview={overview} before={before} onSubmit={submit} onAsk={ask} onKeyDown={onKeyDown}
      fields={{ query, mode, products, version, optionsOpen }}
      setters={{ setQuery, setMode, setProducts, setVersion, setOptionsOpen }} />
  );
}

type SearchFields = { query: string; mode: string; products: string; version: string; optionsOpen: boolean };
type SearchSetters = {
  setQuery: (value: string) => void;
  setMode: (value: string) => void;
  setProducts: (value: string) => void;
  setVersion: (value: string) => void;
  setOptionsOpen: (open: boolean) => void;
};
type SearchViewProps = {
  id: string; workspaceId: string; search: ReturnType<typeof useKnowledgeSearch>; relevance: ReturnType<typeof relevanceStatus>;
  emptyWorkspace: boolean; isAdmin: boolean; overview: EntryOverview | null; before: boolean; fields: SearchFields; setters: SearchSetters;
  onSubmit: (event: FormEvent) => void; onAsk: (question: string) => void; onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
};

// The search section; its controls take the section's skin (`.knowledge-search input, select`).
function KnowledgeSearchView({ id, workspaceId, search, relevance, emptyWorkspace, isAdmin, overview, before, fields, setters,
  onSubmit, onAsk, onKeyDown }: SearchViewProps) {
  const { query, mode, products, version, optionsOpen } = fields;
  const { setQuery, setMode, setProducts, setVersion, setOptionsOpen } = setters;
  return (
    <section className="knowledge-search" aria-label="Knowledge search">
      <form className="knowledge-search__toolbar" role="search" onSubmit={onSubmit}>
        <div className="knowledge-search__bar">
          <label htmlFor={`${id}-query`} className="knowledge-search__sr-only">Search this workspace's sources</label>
          <div className="knowledge-search__field">
            <SearchIcon />
            <input id={`${id}-query`} type="text" enterKeyHint="search" autoComplete="off" maxLength={2000} required
              aria-describedby={emptyWorkspace ? `${id}-hint` : undefined} value={query}
              placeholder="Ask a question, for example: Which PostgreSQL version does the server need?"
              onChange={(event) => setQuery(event.target.value)} onKeyDown={onKeyDown} />
            {query ? <button type="button" className="knowledge-search__clear" aria-label="Clear search"
              onClick={() => setQuery("")}>
              <ClearIcon />
            </button> : null}
          </div>
          <button type="submit" className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={search.busy || !query.trim()}>{search.busy ? "Searching…" : "Search"}</button>
          <button type="button" className="admin-panel__action-btn" aria-expanded={optionsOpen}
            aria-controls={`${id}-options`} onClick={() => setOptionsOpen(!optionsOpen)}>
            {optionsLabel(activeOptionCount({ mode, products, version }))}</button>
        </div>
        <div id={`${id}-options`} className="knowledge-search__fields" hidden={!optionsOpen}>
          <label>Search method
            <select value={mode} onChange={(event) => setMode(event.target.value)} aria-describedby={`${id}-mode-hint`}>
              {SEARCH_MODES.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
            </select>
            <ModeHint id={id} mode={mode} relevance={relevance} />
          </label>
          <label>Products (optional)
            <input value={products} placeholder="Comma-separated product names"
              onChange={(event) => setProducts(event.target.value)} />
          </label>
          <RelevanceDetail relevance={relevance} />
          <label>Version (requires a product)
            <input value={version} disabled={!products.trim()} placeholder="For example: 4.0"
              onChange={(event) => setVersion(event.target.value)} />
          </label>
        </div>
        <SearchHints id={id} emptyWorkspace={emptyWorkspace} isAdmin={isAdmin} relevance={relevance} />
      </form>
      {overview && before ? <KnowledgeSearchStart overview={overview} onAsk={onAsk} /> : null}
      <KnowledgeSearchResults workspaceId={workspaceId} search={search} isAdmin={isAdmin} />
    </section>
  );
}

function ModeHint({ id, mode, relevance }: { id: string; mode: string; relevance: ReturnType<typeof relevanceStatus> }) {
  return (
    <span id={`${id}-mode-hint`} className="knowledge-search__hint" data-testid="search-mode-hint">
      {searchModeHint(mode, relevance ? relevance.active : null)}
    </span>
  );
}

function RelevanceDetail({ relevance }: { relevance: ReturnType<typeof relevanceStatus> }) {
  return relevance ? <p className="knowledge-search__hint" data-testid="relevance-detail">
    {relevance.text}{relevance.classification ? ` ${relevance.classification}` : ""}</p> : null;
}

function SearchIcon() {
  return (
    <svg className="knowledge-search__icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function ClearIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M4.5 4.5 11.5 11.5M11.5 4.5 4.5 11.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function SearchHints({ id, emptyWorkspace, isAdmin, relevance }: {
  id: string; emptyWorkspace: boolean; isAdmin: boolean; relevance: ReturnType<typeof relevanceStatus>;
}) {
  return (
    <>
      {/* No explanatory line under the field; only an empty Workspace says what search still covers. */}
      {emptyWorkspace ? <p id={`${id}-hint`} className="knowledge-search__hint">{searchHint(true)}</p> : null}
      {/* Only a degraded ranking is worth a line, and only for an admin, who can change it; it is a quiet note, not a
          warning (outsider walkthrough). The active state and the classification live in Options. */}
      {isAdmin && relevance && !relevance.active ? (
        <p className="knowledge-search__hint" data-testid="relevance-status" data-active={relevance.active}>
          {relevance.text}</p>
      ) : null}
    </>
  );
}
