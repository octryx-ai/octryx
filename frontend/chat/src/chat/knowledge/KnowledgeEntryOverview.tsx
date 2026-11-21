import { useAdminNavigation } from "../../admin/adminNavigation";
import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import { requestDocumentUpload } from "./knowledgeEntryIntent";
import { keepWorkspaceInUrl } from "./knowledgeNavigation";
import { approveActionLabel, hasNoDocuments, researchCounts } from "./knowledgeEntryModel";
import { statusItems } from "./knowledgeEntryStatus";
import type { EntryOverview } from "./useKnowledgeEntryOverview";
import { useKnowledgePermissions } from "./useKnowledgePermissions";
import "./knowledge-entry.css";

// The top of Knowledge → Search: one short status line ("6 sources · up to date", the count opening Sources) with
// the actions that open the owning pages. Nothing is changed here. `isAdmin`: the Sources page is admin-only.
export function KnowledgeEntryOverview({ overview, isAdmin = false }: { overview: EntryOverview; isAdmin?: boolean }) {
  const navigation = useAdminNavigation();
  // Every action keeps the selected workspace in the URL so the next page opens the same workspace.
  const openAdminTab = (tab: AdminTab) => { keepWorkspaceInUrl(overview.workspaceId); navigation.openAdminTab(tab); };
  const mayAuthor = useKnowledgePermissions(overview.workspaceId);
  // A workspace with a source that has not synced anything yet is not offered "connect a source" again.
  const noConnectors = overview.connectorsFailed || overview.connectors?.connectors.length === 0;
  const empty = hasNoDocuments(overview.listing) && noConnectors;
  const proposals = overview.research ? researchCounts(overview.research).proposed : 0;
  const upload = () => { requestDocumentUpload(overview.workspaceId); openAdminTab("knowledgeSources"); };
  const linkSources = isAdmin && Boolean(overview.connectors);
  return <section className={`knowledge-entry${empty ? " knowledge-entry--empty" : ""}`} aria-label="What this workspace knows">
    <div className="knowledge-entry__bar">
      <dl className="knowledge-entry__status">
        {statusItems(overview).map((item) => <div key={item.key}
          className={`knowledge-entry__item knowledge-entry__item--${item.tone}`}>
          <dt className="knowledge-entry__sr-only">{item.label}</dt>
          <dd>{item.key === "sources" && linkSources
            ? <button type="button" className="knowledge-entry__link"
              onClick={() => openAdminTab("workspaceKnowledge")}>{item.text}</button>
            : item.text}</dd>
        </div>)}
      </dl>
      <div className="knowledge-entry__actions">
        {mayAuthor
          ? <button type="button" className="admin-panel__action-btn"
            onClick={upload}>Upload document</button>
          : <button type="button" className="admin-panel__action-btn" onClick={() => openAdminTab("knowledgeSources")}>
            Open documents</button>}
        {/* Research proposals waiting for a decision are the one reason to act here; otherwise the sidebar suffices. */}
        {mayAuthor && proposals > 0 ? <button type="button" className="admin-panel__action-btn"
          onClick={() => openAdminTab("knowledgeResearch")}>{approveActionLabel(overview.research)}</button> : null}
      </div>
    </div>
    {/* A company's first source is a system such as Confluence or Jira; an upload comes second. */}
    {empty ? <div className="knowledge-entry__first-step" data-testid="knowledge-first-step">
      <strong>First step: connect Confluence or Jira</strong>
      {mayAuthor ? <>
        <p>Knowledge syncs their pages and tickets, so search can cite them. You can also upload single documents.</p>
        <div className="knowledge-entry__actions">
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
            onClick={() => openAdminTab("workspaceKnowledge")}>Connect a source</button>
        </div>
      </> : <p>This workspace has no sources yet. Ask a workspace admin to connect Confluence or Jira.</p>}
    </div> : null}
  </section>;
}
