import { ACCESS_MODE_LABEL } from "./connectorTypes";
import { accessModeOf } from "./connectorConfig";
import { notGrantedView } from "./connectorReasons";
import type { SourceConnector } from "./connectorTypes";
import { CONNECTOR_FORM_ID, KnowledgeConnectorForm } from "./KnowledgeConnectorForm";
import { KnowledgeJiraReleasesDrawer } from "./KnowledgeJiraReleasesDrawer";
import { KnowledgeSourceList } from "./sources/KnowledgeSourceList";
import { sourceName } from "./sources/sourceState";
import { SourceDetailPanel } from "./sources/SourceDetailPanel";
import { instanceSchedulerState } from "./connectorFreshness";
import { KnowledgeEnablementNotice } from "./KnowledgeEnablementNotice";
import { KnowledgeFirstSource } from "./KnowledgeFirstSource";
import { UnlinkedRepositoriesNotice } from "./UnlinkedRepositoriesNotice";
import { LoadingState } from "../../../layout/LoadingState";
import { SidePanel } from "../../../layout/SidePanel";
import { AdminHeaderActions } from "../AdminHeaderSlot";
import { SourceAclSection } from "./sourceAcl/SourceAclSection";
import { knowledgeSourcesAccess } from "./sourceAcl/knowledgeSourcesAccess";
import { knowledgeConnectorActions, type KnowledgeConnectorActions } from "./knowledgeConnectorActions";
import { useKnowledgeConnectorsState, type KnowledgeConnectorsState } from "./useKnowledgeConnectorsState";

type View = { s: KnowledgeConnectorsState; a: KnowledgeConnectorActions; workspaceId: string; isPlatformAdmin: boolean };

// The opened source, in the panel or as a page.
function sourceDetail({ s, a, workspaceId, isPlatformAdmin }: View, selected: SourceConnector) {
  const instance = instanceSchedulerState(s.listing);
  return (
    <SourceDetailPanel connector={selected} workspaceId={workspaceId} lastRun={s.lastRun} running={s.runningKey === selected.connector_key}
      busy={s.busy} mayAuthor={s.mayAuthor} schedulingOn={instance !== "off"} instance={instanceSchedulerState(s.listing, selected)}
      mode={s.pageView ? "page" : "panel"} isPlatformAdmin={isPlatformAdmin} onClose={a.closeDetail} onRun={() => a.runNow(selected)}
      onAccessModeChanged={(described) => {
        const mode = accessModeOf(described);
        const tokenChanged = (described.git_token?.set_at ?? null) !== (selected.git_token?.set_at ?? null)
          || Boolean(described.git_token?.configured) !== Boolean(selected.git_token?.configured);
        s.setMessage(tokenChanged
          ? `Git token of ${sourceName(selected)}: ${described.git_token?.configured ? "configured" : "removed"}.`
          : `Access of ${sourceName(selected)}: ${mode ? ACCESS_MODE_LABEL[mode] : "changed"}.`);
        void s.refresh().catch(() => undefined);
      }}
      onEdit={() => { s.setSelectedKey(null); s.setAdding(false); s.setEditing(selected); }} />
  );
}

// The add or edit form of a source, in a side panel.
function sourceFormPanel({ s, a, workspaceId, isPlatformAdmin }: View, connectors: SourceConnector[]) {
  const { editing, busy } = s;
  return (
    <SidePanel title={editing ? `Edit ${sourceName(editing)}` : "Add source"} onClose={a.closeForm} testId="source-form-panel"
      // The actions at the bottom right like Add connection, primary last.
      footer={s.formOwnActions ? undefined : <>
        <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={a.closeForm}>Cancel</button>
        <button type="submit" form={CONNECTOR_FORM_ID} className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy} data-testid="source-form-submit">{editing ? "Save" : "Add source"}</button>
      </>}>
      {!editing && !connectors.length ? <KnowledgeFirstSource /> : null}
      <KnowledgeConnectorForm key={editing ? `${editing.connector_key}:${JSON.stringify(editing.scope.releases ?? null)}` : "new"}
        editing={editing} busy={busy} instance={instanceSchedulerState(s.listing, editing)}
        onSave={a.save} onCancel={a.closeForm} scopeRefusal={s.scopeRefusal}
        workspaceId={workspaceId} onConnectionSaved={() => void s.refresh().catch(() => undefined)}
        onOwnActions={s.setFormOwnActions} isPlatformAdmin={isPlatformAdmin} saveRefusal={s.saveRefusal} />
    </SidePanel>
  );
}

// The notices above the list: header action, confirm, enablement, message and unlinked repositories.
function sourcesHead({ s, a, workspaceId }: View, connectors: SourceConnector[]) {
  const notGrantedLink = notGrantedView(s.saveRefusal)?.href ?? null;
  return (
    <>
      {s.mayAuthor ? (
        <AdminHeaderActions>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={a.openAdd}
            data-testid="sources-add">Add source</button>
        </AdminHeaderActions>
      ) : null}
      {s.confirmAction.notice}
      {s.confirmAction.dialog}
      <KnowledgeEnablementNotice workspaceId={workspaceId} listing={s.listing} hasConnectors={connectors.length > 0}
        mayAuthor={s.mayAuthor} onEnabled={() => void s.refresh().catch(() => undefined)} />
      {/* No page-wide "automatic sync is off" line: it is said at the source (its Freshness tab, and the reason
          of a source that is out of date because of it) and on Problems. */}
      {s.message ? <div className="admin-panel__hint" role="status">{s.message}</div> : null}
      {notGrantedLink ? (
        <a className="ds-link-button" href={notGrantedLink} data-testid="source-connection-release-link">Open the connection to release it ›</a>
      ) : null}
      {s.mayAuthor ? <UnlinkedRepositoriesNotice connectors={connectors} onEdit={a.edit} /> : null}
    </>
  );
}

// Source Sync connectors of one Workspace: Confluence spaces, Jira projects, ServiceNow knowledge bases and records,
// and public GitHub repositories synced into the evidence ledger, each item as a linked revision. Configure and run need the Workspace admin or owner
// role: the listing's may_author hides those controls for readers, and the server enforces it either way.
export function KnowledgeConnectorsPanel({ workspaceId, isPlatformAdmin = false }: { workspaceId: string; isPlatformAdmin?: boolean }) {
  const s = useKnowledgeConnectorsState(workspaceId);
  const a = knowledgeConnectorActions(s, workspaceId);
  const { connectors, mayAuthor } = s;
  if (!connectors) {
    return s.message ? <div className="admin-panel__hint">{s.message}</div> : <LoadingState label="sources" variant="table" rows={4} />;
  }
  const view: View = { s, a, workspaceId, isPlatformAdmin };
  const selected = connectors.find((connector) => connector.connector_key === s.selectedKey) ?? null;
  const instance = instanceSchedulerState(s.listing);
  const detail = selected ? sourceDetail(view, selected) : null;
  // "Open as page": the source alone, full width, with a way back to the list.
  if (s.pageView && detail) {
    return (
      <div className="admin-panel__stack">
        <a className="knowledge-sources__back" href={`/chat?area=knowledge&tab=workspaceKnowledge&workspace_id=${encodeURIComponent(workspaceId)}`}>← All sources</a>
        {detail}
        {s.confirmAction.notice}
        {s.confirmAction.dialog}
      </div>
    );
  }
  const { releasesKey } = s;
  return (
    <div className="admin-panel__stack">
      {sourcesHead(view, connectors)}
      <KnowledgeSourceList connectors={connectors} selectedKey={s.selectedKey} busy={s.busy} runningKey={s.runningKey}
        schedulingOn={instance !== "off"} mayAuthor={mayAuthor}
        empty={{ text: "No sources yet.", action: mayAuthor ? { label: "Add source", onClick: a.openAdd } : undefined, testId: "sources-empty" }}
        actions={{
          onRun: a.runNow, onShow: (connector) => void s.showRun(connector.connector_key),
          onEdit: a.edit, onToggle: a.toggle,
          onReleases: (connector) => s.setReleasesKey(connector.connector_key), onDelete: a.remove,
          onOpenUploads: () => s.openAdminTab("knowledgeSources"),
        }} />
      {!mayAuthor ? <div className="admin-panel__hint">Only a Workspace admin or owner can change sources.</div> : null}
      {knowledgeSourcesAccess(isPlatformAdmin).aclSwitch ? <SourceAclSection workspaceId={workspaceId} /> : null}

      {releasesKey ? (
        <KnowledgeJiraReleasesDrawer workspaceId={workspaceId} connectorKey={releasesKey}
          onClose={() => s.setReleasesKey(null)} onSaved={() => void a.releasesSaved(releasesKey)} />
      ) : null}

      {detail}

      {mayAuthor && (s.adding || s.editing) ? sourceFormPanel(view, connectors) : null}
    </div>
  );
}
