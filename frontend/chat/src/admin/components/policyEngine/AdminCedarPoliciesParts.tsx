// Parts of the Policies page: the empty state, the tabbed sections, the guided builder panel and the drawers.
import type { Dispatch, ReactNode, SetStateAction } from "react";

import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import type { AdminTab } from "../../types/adminPanelTypes.governance";
import { ApprovalRuleBadge } from "../approvalRule/ApprovalRuleBadge";
import type { ApprovalRule } from "../approvalRule/approvalRule";
import { AdminDetectors } from "./AdminDetectors";
import { AdminPolicyTestBench } from "./AdminPolicyTestBench";
import { BuilderCheckPane } from "./BuilderCheckPane";
import { DraftTraffic } from "./DraftTraffic";
import { PolicyBuilder } from "./PolicyBuilder";
import type { BuilderSession } from "./usePolicyBuilder";
import { PolicyDraftBar } from "./PolicyDraftBar";
import { PolicyDrawer } from "./PolicyDrawer";
import { PolicyEngineStatusCard, PolicyEngineStatusDrawer } from "./PolicyEngineStatusCard";
import { PolicyList } from "./PolicyList";
import { PolicyTemplates, TemplateCard } from "./PolicyTemplates";
import { PolicyImpact } from "./PolicyImpact";
import { PolicyLifecycleDrawer } from "./PolicyLifecycleDrawer";
import type { EngineStatus } from "./policyEngineStatus";
import type { ListFilters, PolicyItem } from "./policyCatalogModel";
import { TABS } from "./policyPageActions";
import type { Drawer, Message, Mode, PoliciesData, PoliciesTab, PolicyPageActions } from "./policyPageActions";

const SOURCE_TABS: Record<string, AdminTab> = { classification: "classificationPolicy", workspace: "projects" };

export type PolicyPageCtx = {
  data: PoliciesData;
  policies: NonNullable<PoliciesData["policies"]>;
  status: EngineStatus;
  actions: PolicyPageActions;
  approvalRule: ApprovalRule;
  previewDelay?: number;
  openAdminTab: (tab: AdminTab) => void;
  setDrawer: Dispatch<SetStateAction<Drawer>>;
  setMode: Dispatch<SetStateAction<Mode>>;
  setMessage: Dispatch<SetStateAction<Message | null>>;
  labelOf: (action: string) => string;
};

export function PolicyEmptyState({ ctx }: { ctx: PolicyPageCtx }) {
  const { data: { catalog }, actions, labelOf } = ctx;
  return (
    <div className="policies__pane" data-testid="policy-empty">
      <div className="admin-panel__empty-state">
        <div className="policies__empty">
          <p>No custom policies yet. The generated baseline keeps applying; add a policy to block more.</p>
          <div className="policies__empty-actions">
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="policy-empty-new"
              disabled={actions.frozen || !catalog} title={actions.frozen ? "The draft is in review and frozen." : undefined} onClick={actions.newPolicy}>+ New policy</button>
            <button type="button" className="admin-panel__action-btn" data-testid="policy-empty-templates" onClick={() => actions.switchTab("templates")}>Browse all templates</button>
          </div>
        </div>
      </div>
      {catalog ? (
        <div className="policies__templates">
          {catalog.templates.slice(0, 3).map((template) => (
            <TemplateCard key={template.id} template={template} onUse={() => actions.startFromTemplate(template)}
              actionLabels={(Array.isArray(template.model.actions) ? template.model.actions as string[] : []).map(labelOf)} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PolicyListSection({ ctx, filters, setFilters }: { ctx: PolicyPageCtx; filters: ListFilters; setFilters: (next: ListFilters) => void }) {
  const { data, policies, actions, setDrawer } = ctx;
  const groups = data.catalog?.actionGroups ?? ["Connectors & tools", "Models", "Coding agent", "Knowledge", "Seats"];
  return (
    <>
      <PolicyList view={policies} filters={filters} onFilters={setFilters} entities={data.entities} groups={groups}
        loadingGenerated={data.loadingGenerated} onOpen={(item) => setDrawer({ kind: "policy", item, confirmRemove: false })} menuFor={actions.menuFor}
        onNew={actions.newPolicy} onTemplates={() => actions.switchTab("templates")} empty={<PolicyEmptyState ctx={ctx} />}
        newDisabled={actions.frozen || !data.catalog} />
      <div className="policies__row">
        <span className="policies__spacer" />
        <button type="button" className="admin-panel__action-btn" data-testid="policy-history" onClick={() => setDrawer({ kind: "lifecycle" })}>Version history</button>
        <button type="button" className="admin-panel__action-btn" data-testid="policy-advanced-cedar" onClick={() => void actions.openSet(false)}>Advanced · Edit the whole set as Cedar</button>
      </div>
    </>
  );
}

export function PolicyTabsView({ ctx, tab, filters, setFilters, message }: {
  ctx: PolicyPageCtx;
  tab: PoliciesTab;
  filters: ListFilters;
  setFilters: (next: ListFilters) => void;
  message: Message | null;
}) {
  const { data, policies, status, actions, approvalRule, setDrawer, setMessage } = ctx;
  const { working, catalog } = data;
  const changeCount = policies.changes.new + policies.changes.changed + policies.changes.removed;
  return (
    <>
      {/* The engine's state sits beside the sections, not in the page header: the header keeps one height and
          holds only actions (UI set, page header). */}
      <div className="policies__row policies__head">
        <SegmentedTabs size="small" label="Policies sections" idPrefix="policies" value={tab}
          onChange={(key) => actions.switchTab(key as PoliciesTab)}
          tabs={TABS.map((item) => ({ key: item.id, label: item.label, testId: `policies-tab-${item.id}` }))} />
        <span className="policies__spacer" />
        <PolicyEngineStatusCard status={status} onOpen={() => setDrawer({ kind: "engine" })} />
        <ApprovalRuleBadge rule={approvalRule} />
      </div>
      {working ? (
        <PolicyDraftBar working={working} publishedVersion={policies.publishedVersion} changeCount={changeCount}
          authorName={policies.authorName} selfApproval={approvalRule.selfApprovalAllowed}
          onLifecycle={() => setDrawer({ kind: "lifecycle" })} />
      ) : null}
      {message ? <p className={message.ok ? "admin-panel__success" : "workspace-classification__message"} role={message.ok ? "status" : "alert"} data-testid="cedar-message">{message.text}</p> : null}
      {data.generatedProblem && filters.showGenerated ? <p className="workspace-classification__message" role="alert">{data.generatedProblem}</p> : null}
      {tab === "list" ? <PolicyListSection ctx={ctx} filters={filters} setFilters={setFilters} /> : null}
      {tab === "templates" && catalog ? <PolicyTemplates templates={catalog.templates} labelOf={ctx.labelOf} onUse={actions.startFromTemplate} /> : null}
      {tab === "detectors" ? <AdminDetectors target={actions.target} workspaces={data.entities.workspaces} previewDelay={ctx.previewDelay}
        onEditElsewhere={() => ctx.openAdminTab("contentSecurity")}
        onSaved={async (text) => { await data.load(); setMessage({ ok: true, text }); }} /> : null}
      {tab === "bench" ? <AdminPolicyTestBench /> : null}
    </>
  );
}

export function PolicyBuilderPanel({ ctx, session }: { ctx: PolicyPageCtx; session: BuilderSession }) {
  const { data, policies, actions } = ctx;
  const { catalog, working, published } = data;
  if (!catalog) return null;
  return (
    <PolicyBuilder session={session} catalog={catalog} entities={data.entities} view={policies} previewDelay={ctx.previewDelay}
      onCancel={() => ctx.setMode({ kind: "tabs" })} onSaved={actions.saved}
      onEditAsCedar={(text) => void actions.openCedar({ text, originalId: session.originalId, isNew: session.isNew, title: `${session.title} · Cedar` })}
      checkStep={(model, preview) => (
        <BuilderCheckPane valid={preview.valid} schemaVersion={catalog.schemaVersion} report={working?.testReport ?? published?.testReport ?? null}
          examples={preview.valid ? <PolicyImpact model={model} originalId={session.originalId} policyName={model.name || model.id} onOpenBench={() => actions.switchTab("bench")} /> : null}
          traffic={<DraftTraffic impact={data.draftImpact} policyId={session.originalId ?? model.id}
            inDraft={Boolean(working && session.originalId && policies.items.some((item) => item.id === session.originalId && item.change !== "removed"))} />} />
      )} />
  );
}

function PolicyItemDrawer({ ctx, item, confirmRemove }: { ctx: PolicyPageCtx; item: PolicyItem; confirmRemove: boolean }) {
  const { data, policies, status, actions, setDrawer, openAdminTab } = ctx;
  const { working, published, entities } = data;
  const connectionLabel = (id: string) => {
    const found = entities.namedConnections.find((entry) => entry.id === id);
    return id === "default" ? "default" : found ? `${found.name} · ${found.connector}` : `unknown connection ${id}`;
  };
  const draftTraffic: ReactNode = working && (item.change === "new" || item.change === "changed")
    ? <DraftTraffic impact={data.draftImpact} policyId={item.id} inDraft /> : null;
  return (
    <PolicyDrawer item={item} onClose={() => setDrawer(null)} actions={actions.drawerActions(item, confirmRemove)}
      confirmRemove={confirmRemove}
      context={{ versionNumber: policies.version?.version ?? null, versionState: policies.version?.state ?? null, publishedVersion: policies.publishedVersion, testReport: working?.testReport ?? published?.testReport ?? null, engineMode: status.mode }}
      onShowDecisions={() => actions.showDecisions(item.id)}
      connectionLabel={connectionLabel}
      onOpenConnectors={() => { setDrawer(null); openAdminTab("connectors"); }}
      draftTraffic={draftTraffic}
      impact={item.model && item.change !== "removed" ? <PolicyImpact model={item.model} originalId={item.id} policyName={item.name} auto={false} /> : null}
      onEditSource={SOURCE_TABS[item.source] ? () => { setDrawer(null); openAdminTab(SOURCE_TABS[item.source]); } : null} />
  );
}

export function PolicyDrawers({ ctx, drawer }: { ctx: PolicyPageCtx; drawer: Drawer }) {
  const { data, policies, status, approvalRule, setDrawer, setMessage } = ctx;
  if (drawer?.kind === "lifecycle") {
    return (
      <PolicyLifecycleDrawer working={data.working} published={data.published} items={policies.items} history={data.history}
        schemaVersion={data.catalog?.schemaVersion ?? status.schemaVersion} selfApproval={approvalRule.selfApprovalAllowed}
        onClose={() => setDrawer(null)}
        onChanged={async (text) => { await data.load(); setDrawer(null); setMessage({ ok: true, text }); }} />
    );
  }
  if (drawer?.kind === "engine") return <PolicyEngineStatusDrawer status={status} onChanged={data.setStatus} onClose={() => setDrawer(null)} />;
  if (drawer?.kind === "policy") return <PolicyItemDrawer ctx={ctx} item={drawer.item} confirmRemove={drawer.confirmRemove} />;
  return null;
}
