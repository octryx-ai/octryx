import { useEffect, useMemo, useRef, useState } from "react";
import { workspaceKnowledgeApi } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeApi";
import { readableCitation } from "../../admin/components/workspaceKnowledge/KnowledgeCitation";
import type { ChangesResult, GraphStatus } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { EmptyLine } from "../../layout/EmptyLine";
import { LoadingState } from "../../layout/LoadingState";
import { RELATIONSHIP_PAGE, nextRelationshipLimit, presentFact, relationshipCountText } from "./relationshipPresenter";
import {
  concernsEntity, factRowKey, filterFacts, sourceText, unsourcedCount, type ExploreFact, type ExploreFilter,
} from "./explore/exploreModel";
import "./knowledge-contribution.css";

type Shown = { product: string; version: string; query: string; changesOnly: boolean; limit: number };

type Props = {
  workspaceId: string;
  filter: ExploreFilter;
  entity: string;
  onSelectEntity: (name: string) => void;
  // The loaded relationships, so the page offers the kinds and origins they carry and the entity panel lists them.
  onFacts: (facts: ExploreFact[]) => void;
  onBusy: (busy: boolean) => void;
  onOpen: (tab: AdminTab) => void;
};

// Explore → List (page id knowledgeRelationships): the relationships of a product up to a version, loaded at once
// for the first product and its newest version (concept: no form before the first result). The shared filter bar's
// term asks the server; kind and origin narrow in the browser. Design system: one compact table row per relationship
// (Subject · Relationship · Object · Version · Source); a row or a name opens the entity in the side panel.
export function KnowledgeRelationshipsPanel({ workspaceId, filter, entity, onSelectEntity, onFacts, onBusy, onOpen }: Props) {
  const [products, setProducts] = useState<Record<string, string[]>>({});
  const [product, setProduct] = useState("");
  const [version, setVersion] = useState("");
  const [changesOnly, setChangesOnly] = useState(true);
  const [showUnsourced, setShowUnsourced] = useState(false);
  const [status, setStatus] = useState<GraphStatus | null>(null);
  const [result, setResult] = useState<ChangesResult | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    let active = true;
    alive.current = true;
    void workspaceKnowledgeApi.products(workspaceId).then(
      (value) => {
        if (!active) return;
        setProducts(value.products);
        const first = Object.keys(value.products).sort()[0];
        if (first) { setProduct(first); setVersion(value.products[first].at(-1) ?? ""); }
      },
      (failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : String(failure)); },
    );
    void workspaceKnowledgeApi.graphStatus(workspaceId).then(
      (value) => { if (active) setStatus(value); }, () => {},
    );
    return () => { active = false; alive.current = false; };
  }, [workspaceId]);
  const load = async (next: Shown) => {
    const request = ++generation.current;
    setBusy(true); setError(null);
    try {
      const value = await workspaceKnowledgeApi.changes(workspaceId, {
        product: next.product, to_version: next.version, changes_only: next.changesOnly, limit: next.limit,
        ...(next.query ? { query: next.query } : {}),
      });
      if (alive.current && generation.current === request) { setResult(value); setShown(next); }
    } catch (failure) {
      if (alive.current && generation.current === request) setError(failure instanceof Error ? failure.message : String(failure));
    } finally { if (alive.current && generation.current === request) setBusy(false); }
  };
  const nothingExtracted = status !== null && status.episodes === 0;
  useEffect(() => {
    if (!product || !version || nothingExtracted) return;
    void load({ product, version, query: filter.text, changesOnly, limit: RELATIONSHIP_PAGE });
    // `load` reads only the values listed here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, product, version, changesOnly, filter.text, nothingExtracted]);
  useEffect(() => { onBusy(busy); }, [busy, onBusy]);
  const facts = useMemo<ExploreFact[]>(() => (result?.state === "ok" ? result.facts : []), [result]);
  useEffect(() => { onFacts(facts); }, [facts, onFacts]);
  const visible = filterFacts(facts, filter, showUnsourced);
  const rows: RelationshipRow[] = visible.map((fact, index) => ({ fact, key: factRowKey(fact, index) }));
  const selectedKey = entity ? rows.find((row) => concernsEntity(row.fact, entity))?.key ?? null : null;
  const hidden = showUnsourced ? 0 : unsourcedCount(facts);
  const more = result?.state === "ok" && shown ? nextRelationshipLimit(shown.limit, result.facts.length) : null;
  if (nothingExtracted) {
    return <RelationshipsEmptyState status={status} hasProducts={Object.keys(products).length > 0} onOpen={onOpen} />;
  }
  return <section className="knowledge-contribution knowledge-relationships" aria-label="Relationships">
    <div className="knowledge-explore__options" role="group" aria-label="Relationship options">
      <label className="admin-panel__field">
        <span>Product</span>
        <select className="admin-panel__input" value={product}
          onChange={(event) => { setProduct(event.target.value); setVersion(products[event.target.value]?.at(-1) ?? ""); }}>
          <option value="">Choose a product</option>
          {Object.keys(products).sort().map((name) => <option key={name}>{name}</option>)}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Up to version</span>
        <select className="admin-panel__input" value={version} disabled={!product}
          onChange={(event) => setVersion(event.target.value)}>
          <option value="">Choose a version</option>
          {(products[product] ?? []).map((value) => <option key={value}>{value}</option>)}
        </select>
      </label>
      <label className="admin-panel__checkbox">
        <input type="checkbox" checked={changesOnly} onChange={(event) => setChangesOnly(event.target.checked)} />
        Only changes
      </label>
    </div>
    {!product && Object.keys(products).length === 0 && status ? <EmptyLine
      text="Relationships are read from documents that carry a product and version."
      action={{ label: "Open Sources", onClick: () => onOpen("workspaceKnowledge") }} /> : null}
    {busy && !result ? <LoadingState label="relationships" rows={4} /> : null}
    {error ? <p role="alert">{error}</p> : null}
    {result && result.state !== "ok" ? <EmptyLine text={stateText(result.state)} /> : null}
    {result?.state === "ok" && shown && visible.length ? <p className="knowledge-explore__count" role="status"
      title={statusLine(status, result.facts_workspace)}>
      {relationshipCountText(result, Boolean(shown.query), shown.version)}</p> : null}
    {result?.state === "ok" ? <DataTable<RelationshipRow> label="Relationships" columns={relationshipColumns(onSelectEntity)}
      rows={rows} rowKey={(row) => row.key} selectedKey={selectedKey}
      onOpen={(row) => onSelectEntity(presentFact(row.fact).subject)}
      empty={{ text: "No matching relationships found." }} testId="explore-relationships" /> : null}
    {hidden ? <button type="button" className="admin-panel__action-btn" onClick={() => setShowUnsourced(true)}>
      Show {hidden} without a source</button> : null}
    {more && shown ? <button type="button" className="admin-panel__action-btn" disabled={busy}
      onClick={() => void load({ ...shown, limit: more })}>Show more</button> : null}
  </section>;
}

type RelationshipRow = { fact: ExploreFact; key: string };

function EntityName({ name, onSelect }: { name: string; onSelect: (name: string) => void }) {
  // Opens this entity, not the row's subject: the click stays with the name.
  return <button type="button" className="knowledge-explore__link knowledge-relationships__entity"
    onClick={(event) => { event.stopPropagation(); onSelect(name); }}
    onKeyDown={(event) => event.stopPropagation()}>{name}</button>;
}

function SourceCell({ fact }: { fact: ExploreFact }) {
  const text = sourceText(fact, readableCitation);
  if (!text) return <span className="knowledge-explore__muted">No source</span>;
  const full = fact.citation || fact.source_title;
  return fact.source_url
    ? <a href={fact.source_url} target="_blank" rel="noopener noreferrer" title={full}
      onClick={(event) => event.stopPropagation()}>{text}</a>
    : <span title={full}>{text}</span>;
}

function relationshipColumns(onSelect: (name: string) => void): DataTableColumn<RelationshipRow>[] {
  return [
    { key: "subject", header: "Subject", width: "22%", render: ({ fact }) => <EntityName name={presentFact(fact).subject} onSelect={onSelect} /> },
    { key: "relation", header: "Relationship", width: "16%", nowrap: true,
      render: ({ fact }) => { const view = presentFact(fact); return <span title={view.headline}>{view.relation}</span>; } },
    { key: "object", header: "Object", width: "22%",
      render: ({ fact }) => { const object = presentFact(fact).object; return object ? <EntityName name={object} onSelect={onSelect} /> : null; } },
    { key: "version", header: "Version", width: "8rem", nowrap: true, render: ({ fact }) => fact.version ?? "" },
    { key: "source", header: "Source", grow: true, render: ({ fact }) => <SourceCell fact={fact} /> },
  ];
}

// The extraction counts and the evidence Workspace, kept for the tooltip of the count line.
function statusLine(status: GraphStatus | null, factsWorkspace: string | undefined): string | undefined {
  const parts = [
    status ? `${status.episodes} extracted sections` : "",
    status?.pending_revisions ? `${status.pending_revisions} documents waiting for extraction` : "",
    factsWorkspace ? `Evidence workspace: ${factsWorkspace}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : undefined;
}

function stateText(state: string): string {
  if (state === "not_extracted") return "No relationships have been extracted for this version yet.";
  if (state === "no_sources") return "There are no documents for this product up to this version.";
  return "Relationships cannot be shown right now. Try again later.";
}

// What the page shows instead of an empty list when nothing has been extracted in this workspace: one line, one action.
function RelationshipsEmptyState({ status, hasProducts, onOpen }: {
  status: GraphStatus; hasProducts: boolean; onOpen: (tab: AdminTab) => void;
}) {
  if (!status.readable) {
    return <EmptyLine text="Relationships are not available on this installation yet; Search works without them."
      action={{ label: "Search documents", onClick: () => onOpen("knowledgeLibrary") }} />;
  }
  const waiting = status.pending_revisions ? ` ${status.pending_revisions} documents are waiting for extraction.` : "";
  if (hasProducts && status.extractable) {
    return <EmptyLine text={`No relationships extracted in this workspace yet.${waiting}`}
      action={{ label: "Open Changes", onClick: () => onOpen("knowledgeChanges") }} />;
  }
  return <EmptyLine text={`No relationships extracted in this workspace yet.${waiting}`}
    action={{ label: "Open Sources", onClick: () => onOpen("workspaceKnowledge") }} />;
}
