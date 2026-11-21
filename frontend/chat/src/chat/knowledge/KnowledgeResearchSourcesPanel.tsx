import { useEffect, useState } from "react";
import { webSearchApi } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeApi";
import type { SourceRequest, TrustedSource, WebSearchOverview } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { AdminHeaderActions } from "../../admin/components/AdminHeaderSlot";
import { DataTable } from "../../layout/DataTable";
import { StatusLabel } from "../../layout/StatusLabel";
import { KnowledgeResearchSourceDrawer } from "./KnowledgeResearchSourceDrawer";
import { KnowledgeResearchSourceDetail } from "./KnowledgeResearchSourceDetail";
import { KnowledgeResearchPolicy } from "./KnowledgeResearchPolicy";
import { researchSourceRow, STATE_TONES } from "./researchSourceRows";
import type { ResearchActionKey, ResearchSourceRow } from "./researchSourceRows";
import "./knowledge-contribution.css";
import "./knowledge-research.css";

type Filter = "all" | TrustedSource["state"];

// The one owner page of the workspace's research websites (the web-search source registry): which websites
// research and chat web search may read, which are blocked, and what the research agent proposed. The list is a
// table; a row opens the website in a side panel, where Approve, Block and Remove live (no buttons in rows).
// "Add website" is the page's primary action in the header; what the modes mean is in the page help.
export function KnowledgeResearchSourcesPanel({ workspaceId, mayAuthor }: { workspaceId: string; mayAuthor: boolean }) {
  const [overview, setOverview] = useState<WebSearchOverview | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [adding, setAdding] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void webSearchApi.overview(workspaceId).then(
      (result) => { if (active) setOverview(result); },
      (failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : String(failure)); },
    );
    return () => { active = false; };
  }, [workspaceId]);
  const run = async (action: () => Promise<WebSearchOverview>, done?: () => void) => {
    setBusy(true); setError(null); setNotice(null);
    try { setOverview(await action()); done?.(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  };
  const save = (request: SourceRequest) => void run(() => webSearchApi.put(workspaceId, request), () => setAdding(false));
  const canary = async () => {
    setBusy(true); setError(null);
    try {
      const result = await webSearchApi.canary(workspaceId);
      setOverview(await webSearchApi.overview(workspaceId));
      setNotice(result.healthy ? `Provider check passed (${result.provider}).` : `Provider check failed: ${result.reason.replaceAll("_", " ")}.`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  };
  const all = overview?.sources ?? [];
  const sources = all.filter((source) => filter === "all" || source.state === filter);
  const proposals = all.filter((source) => source.state === "proposed").length;
  const context = { mayAuthor, mayEditPlatform: overview?.may_edit_platform === true, origin: window.location.origin };
  const rows = sources.map((source) => researchSourceRow(source, context));
  const openRow = openId ? all.filter((source) => source.id === openId).map((source) => researchSourceRow(source, context))[0] ?? null : null;
  // The same calls: Approve/Block re-decide the entry, Remove deletes it; no extra prompt. Remove closes
  // the panel, a decision keeps it open on the re-decided entry.
  const decide = (sourceId: string, key: ResearchActionKey) => void run(() => key === "remove"
    ? webSearchApi.remove(workspaceId, sourceId)
    : webSearchApi.decide(workspaceId, sourceId, key), key === "remove" ? () => setOpenId(null) : undefined);
  return <section className="knowledge-contribution" aria-label="Research websites">
    {mayAuthor && overview ? <AdminHeaderActions>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="research-add-website"
        onClick={() => setAdding(true)}>Add website</button>
    </AdminHeaderActions> : null}
    {overview ? <KnowledgeResearchPolicy overview={overview} mayAuthor={mayAuthor} busy={busy}
      onMode={(mode) => void run(() => webSearchApi.setMode(workspaceId, mode))} onCanary={() => void canary()} /> : null}
    {notice ? <p className="admin-panel__note" role="status">{notice}</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {!overview && !error ? <p role="status">Loading research websites…</p> : null}
    {overview && all.length ? <div className="knowledge-contribution__inline">
      <label>Show<select className="admin-panel__input" value={filter} onChange={(event) => setFilter(event.target.value as Filter)}>
        <option value="all">All decisions ({all.length})</option>
        <option value="proposed">Awaiting review ({proposals})</option>
        <option value="trusted">Approved</option><option value="blocked">Blocked</option>
      </select></label>
    </div> : null}
    {overview ? <DataTable<ResearchSourceRow> label="Research websites" testId="research-websites-table" rows={rows}
      rowKey={(row) => row.id} onOpen={(row) => setOpenId(row.id)} selectedKey={openId}
      empty={all.length ? { text: "No websites with this decision.", action: { label: "Show all", onClick: () => setFilter("all") } }
        : { text: "No research websites yet.", action: mayAuthor ? { label: "Add website", onClick: () => setAdding(true) } : undefined }}
      columns={[
        { key: "website", header: "Website", grow: true, render: (row) => <div className="knowledge-research__site">
          <strong className="knowledge-research__domain">{row.pattern}</strong>
          <span className="knowledge-research__reason" title={row.reasonTitle}>{row.reason}</span>
        </div> },
        { key: "decision", header: "Decision", width: "9.5rem", nowrap: true,
          render: (row) => <StatusLabel label={row.stateLabel} tone={STATE_TONES[row.state]} /> },
        { key: "scope", header: "Applies to", width: "9rem", nowrap: true, render: (row) => row.meta[0].value },
        { key: "origin", header: "Proposed by", width: "9rem", nowrap: true, render: (row) => row.meta[2].value },
      ]} /> : null}
    {openRow ? <KnowledgeResearchSourceDetail row={openRow} busy={busy} onDecide={(key) => decide(openRow.id, key)}
      onClose={() => setOpenId(null)} /> : null}
    {adding && overview ? <KnowledgeResearchSourceDrawer sources={all} mayEditPlatform={overview.may_edit_platform}
      busy={busy} onSave={save} onClose={() => setAdding(false)} /> : null}
  </section>;
}
