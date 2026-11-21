import { useEffect, useId, useRef, useState } from "react";
import { workspaceKnowledgeApi } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeApi";
import type { KnowledgeSource, SourceDetail } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { KnowledgeSourceUploadPanel } from "./KnowledgeSourceUploadPanel";
import { KnowledgeDocumentPanel } from "./document/KnowledgeDocumentPanel";
import { documentHref, requestedDocument } from "./document/documentViewModel";
import { DataTable } from "../../layout/DataTable";
import { ActionMenu } from "../../admin/components/workflowSurfaces/ActionMenu";
import { takeDocumentUploadRequest } from "./knowledgeEntryIntent";
import { INITIAL_SOURCE_LIMIT, removedNotice, sourceListingSummary, sourceRow } from "./sourceInventoryModel";
import { useSourcePages } from "./useSourcePages";
import { documentOriginLine, syncedOriginOf } from "./syncedSourceModel";
import "./knowledge-contribution.css";

// The source page of a synced document opens in a new tab, only from the explicit "Open in …".
function openExternal(url: string) {
  if (!/^https?:\/\//i.test(url) || typeof window === "undefined") return;
  window.open(url, "_blank", "noopener,noreferrer");
}

const currentSearch = () => (typeof window === "undefined" ? "" : window.location.search);

// The open document lives in the address (?document=<id>, &document_view=page), so a link opens it again.
function writeDocumentParam(sourceId: string | null) {
  if (typeof window === "undefined" || !window.history?.replaceState) return;
  try {
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${documentHref(window.location.search, sourceId)}`);
  } catch {
    // An address that cannot be rewritten only loses the deep link.
  }
}

function message(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure);
}

function useInventoryState(workspaceId: string) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<KnowledgeSource | null>(null);
  const [requested] = useState(() => requestedDocument(currentSearch()));
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  // "Upload document" on the Search entry opens this page with its upload drawer (authors only).
  const [adding, setAdding] = useState(() => takeDocumentUploadRequest(workspaceId));
  const [refresh, setRefresh] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [enabling, setEnabling] = useState(false);
  const [enableError, setEnableError] = useState<string | null>(null);
  const pages = useSourcePages(workspaceId, query, refresh, workspaceKnowledgeApi.sourcePage, INITIAL_SOURCE_LIMIT);
  return { query, setQuery, selected, setSelected, requested, detail, setDetail, detailError, setDetailError, filter, setFilter,
    adding, setAdding, setRefresh, notice, setNotice, enabling, setEnabling, enableError, setEnableError, ...pages };
}

type InventoryState = ReturnType<typeof useInventoryState>;

function useDocumentDrawer(workspaceId: string, inventory: InventoryState) {
  const { requested, loaded, setSelected, setDetail, setDetailError, setNotice, setRefresh, setEnabling, setEnableError } = inventory;
  const request = useRef(0);
  const selectedId = useRef<string | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, [workspaceId]);
  const reload = () => { setNotice(null); setRefresh((value) => value + 1); };
  const inspect = async (source: KnowledgeSource, keepAddress = false) => {
    const generation = ++request.current;
    selectedId.current = source.source_id;
    setSelected(source); setDetail(null); setDetailError(null); setNotice(null);
    if (!keepAddress) writeDocumentParam(source.source_id);
    try {
      const result = await workspaceKnowledgeApi.sourceDetail(workspaceId, source.source_id);
      if (alive.current && request.current === generation) setDetail(result);
    } catch (failure) {
      if (alive.current && request.current === generation) setDetailError(message(failure));
    }
  };
  const close = () => {
    request.current++; selectedId.current = null;
    setSelected(null); setDetail(null); setDetailError(null);
    writeDocumentParam(null);
  };
  // A link to one document (?document=<id>) opens it once; the listing carries its title, else the id stands in.
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current || !requested.sourceId) return;
    opened.current = true;
    const known = loaded.find((source) => source.source_id === requested.sourceId);
    void inspect(known ?? ({ source_id: requested.sourceId, display_title: requested.sourceId } as KnowledgeSource), true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requested.sourceId]);
  // The removed document's drawer closes (only if it is still the open one) and the list reloads.
  const removed = (source: KnowledgeSource) => {
    if (selectedId.current === source.source_id) close();
    setRefresh((value) => value + 1);
    setNotice(removedNotice(sourceRow(source).title));
  };
  // The server decides who may enable it.
  const enable = async () => {
    setEnabling(true); setEnableError(null);
    try {
      await workspaceKnowledgeApi.enable(workspaceId);
      if (alive.current) reload();
    } catch (failure) {
      if (alive.current) setEnableError(message(failure));
    } finally {
      if (alive.current) setEnabling(false);
    }
  };
  return { reload, inspect, close, removed, enable };
}

function SourcesToolbar({ id, inventory, mayAuthor, reload }: { id: string; inventory: InventoryState; mayAuthor: boolean; reload: () => void }) {
  const { filter, setFilter, setQuery, setNotice, listing, loaded, hasMore, query, adding, setAdding } = inventory;
  return (
    <div className="knowledge-sources__toolbar">
      <form className="knowledge-sources__filter" role="search"
        onSubmit={(event) => { event.preventDefault(); setNotice(null); setQuery(filter.trim()); }}>
        <label htmlFor={`${id}-filter`} className="knowledge-sources__sr-only">Find by title or key</label>
        <input id={`${id}-filter`} type="search" className="admin-panel__input" value={filter} maxLength={200}
          placeholder="Find by title or key"
          onChange={(event) => { setFilter(event.target.value); if (!event.target.value) setQuery(""); }} />
        <button type="submit" className="admin-panel__action-btn">Find</button>
      </form>
      {listing ? <p className="admin-panel__note knowledge-sources__summary" role="status">
        {sourceListingSummary(loaded.length, hasMore, query)}</p> : null}
      <div className="knowledge-sources__actions">
        <button type="button" className="admin-panel__action-btn" onClick={reload}>Refresh</button>
        {mayAuthor ? <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          aria-haspopup="dialog" aria-expanded={adding} onClick={() => setAdding(true)}>Add document</button> : null}
      </div>
    </div>
  );
}

function SourcesProblem({ inventory, enable }: { inventory: InventoryState; enable: () => Promise<void> }) {
  const { error, listing, enabling, enableError } = inventory;
  return <div className="knowledge-sources__problem">
    <p role="alert">{error}</p>
    {!listing ? <button type="button" className="admin-panel__action-btn" disabled={enabling}
      onClick={() => void enable()}>{enabling ? "Enabling…" : "Enable Knowledge for this workspace"}</button> : null}
    {enableError ? <p role="alert">{enableError}</p> : null}
  </div>;
}

type SourceRows = { source: KnowledgeSource; row: ReturnType<typeof sourceRow>; synced: ReturnType<typeof syncedOriginOf> }[];

function SourcesTable({ rows, inventory, mayAuthor, inspect }: {
  rows: SourceRows; inventory: InventoryState; mayAuthor: boolean; inspect: (source: KnowledgeSource) => Promise<void>;
}) {
  const { selected, query, setAdding } = inventory;
  return <div className="knowledge-sources__list"><DataTable<SourceRows[number]> label="Documents" testId="knowledge-documents"
    rows={rows} rowKey={({ row }) => row.id} selectedKey={selected?.source_id ?? null}
    onOpen={({ source }) => void inspect(source)}
    empty={{ text: query ? "No document matches this filter." : "No documents yet.",
      action: mayAuthor && !query ? { label: "Add document", onClick: () => setAdding(true) } : undefined }}
    columns={[
      { key: "title", header: "Title", grow: true, render: ({ source, row, synced }) => <span className="knowledge-sources__title-cell">
        {/* A synced item links to its page at the source and says when it was removed there. */}
        {/* The title opens the document here; the source page only through "Open in …". */}
        <strong className="knowledge-sources__title">{row.title}</strong>
        {synced?.removedAtSource ? <span className="admin-panel__badge admin-panel__badge--inactive"
          data-testid="source-removed-at-source">Removed at source</span> : null}
        {/* Where it comes from, not its internal key; the key stays as tooltip and in the filter. */}
        <span className="knowledge-sources__key" title={row.key || undefined}>{documentOriginLine(source)}</span>
      </span> },
      { key: "revisions", header: "Revisions", nowrap: true,
        render: ({ row }) => <span data-label="Revisions">{row.revisions}</span> },
    ]}
    rowMenu={rows.some(({ synced }) => synced?.url) ? ({ row, synced }) => synced?.url ? <ActionMenu row={{ objectName: row.title }} items={[
      { label: `Open in ${synced.sourceName}`, onSelect: () => openExternal(synced.url as string) },
    ]} /> : null : undefined} /></div>;
}

export function KnowledgeSourceInventory({ workspaceId, mayAuthor }: { workspaceId: string; mayAuthor: boolean }) {
  const id = useId();
  const inventory = useInventoryState(workspaceId);
  const { reload, inspect, close, removed, enable } = useDocumentDrawer(workspaceId, inventory);
  const { selected, requested, detail, detailError, adding, setAdding, setRefresh, notice, listing, loaded, error } = inventory;
  const { loadingMore, loadMore, hasMore } = inventory;
  const rows = loaded.map((source) => ({ source, row: sourceRow(source), synced: syncedOriginOf(source) }));
  const panel = selected ? <KnowledgeDocumentPanel workspaceId={workspaceId} sourceId={selected.source_id}
    title={sourceRow(selected).title} detail={detail} error={detailError} mayAuthor={mayAuthor}
    mode={requested.page && requested.sourceId === selected.source_id ? "page" : "panel"}
    pageHref={documentHref(currentSearch(), selected.source_id, true)} backHref={documentHref(currentSearch(), null)}
    onRemoved={() => removed(selected)} onClose={close} /> : null;
  // "Open as page": the same document full width, without the list.
  if (selected && requested.page && requested.sourceId === selected.source_id) {
    return <section className="knowledge-contribution" aria-label="Document">{panel}</section>;
  }
  return <section className="knowledge-contribution" aria-label="Available knowledge sources">
    {/* One title only: the page header says "Documents" and its purpose. One filter row: find on the
        left, the page's actions at its end, as on the other list pages (UI set). */}
    <SourcesToolbar id={id} inventory={inventory} mayAuthor={mayAuthor} reload={reload} />
    {adding && mayAuthor ? <KnowledgeSourceUploadPanel workspaceId={workspaceId} onClose={() => setAdding(false)} onUploaded={() => setRefresh((value) => value + 1)} /> : null}
    {notice ? <p className="admin-panel__note" role="status">{notice}</p> : null}
    {error ? <SourcesProblem inventory={inventory} enable={enable} /> : null}
    {!listing && !error ? <p role="status">Loading documents…</p> : null}
    {listing ? <SourcesTable rows={rows} inventory={inventory} mayAuthor={mayAuthor} inspect={inspect} /> : null}
    {hasMore ? <button type="button" className="admin-panel__action-btn knowledge-sources__more" disabled={loadingMore}
      onClick={() => void loadMore()}>{loadingMore ? "Loading…" : "Load more documents"}</button> : null}
    {panel}
  </section>;
}
