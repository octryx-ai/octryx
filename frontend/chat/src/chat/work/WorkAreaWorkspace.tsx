import { AreaTitle } from "../workspace/AreaTitle";
import { SegmentedTabs } from "../../layout/SegmentedTabs";
import { WorkAccessContext } from "./workAccess";

import type { ProjectOption } from "../../chatOptionTypes";
import type { WorkNavKey } from "./workTypes";
import { WorkBoard, WorkTable } from "./WorkAreaViews";
import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import { WorkItemDetailPanel } from "./WorkItemDetailPanel";
import { workItemPageHref } from "./workDetailLink";
import { WorkItemDetailPending } from "./WorkItemDetailPending";
import { WorkJiraWriteback } from "./WorkJiraWriteback";
import { WorkPlansPage } from "./WorkPlansPage";
import { workNavItem } from "./WorkNav";
import { WorkAreaNav } from "./WorkAreaNav";
import { entryViewParam, workAreaGroup, workAreaLabel } from "./workAreaMenu";
import type { WorkItemsMode } from "./workNavRedirects";
import { WorkFiltersBar } from "./WorkFilters";
import { WorkIntakePage } from "./intake/WorkIntakePage";
import { useActiveWorkspace } from "../useActiveWorkspace";
import { ChooseWorkspaceLine } from "../workspace/ChooseWorkspaceLine";
import { PageHeader } from "../../layout/PageHeader";
import { WorkProblemsLine } from "./WorkProblemsLine";
import { LoadingState } from "../../layout/LoadingState";
import { WorkMyWorkPanel, WorkScopeSwitch } from "./myWork/WorkMyWork";
import { WorkRunsPage } from "./WorkRunsPage";
import { WorkEpicsPage } from "./WorkEpicsPage";
import type { PluginViewer } from "../../admin/components/plugins/usePluginFrame";
import { WorkPluginPage } from "./WorkPluginPage";
import { useWorkAreaItems, useWorkAreaNavigation } from "./useWorkAreaState";

type WorkAreaWorkspaceProps = {
  projects: ProjectOption[];
  // The chat's selected Workspace; applies while the user has made no Workspace choice of their own.
  initialWorkspaceId?: string | null;
  // Opens an admin-shell page such as Automation → Connectors.
  onOpenAdminTab?: (tab: AdminTab) => void;
  // Opens a Coding page of the one Work menu (workAreaMenu.ts) with its address field.
  onOpenArea?: (area: "coding", params: Record<string, string>) => void;
  // Who looks (a plugin page's context.user).
  viewer?: PluginViewer;
  // False for a Workspace member without the Work role: reads Work, never sees what configures or starts it.
  canManageWork?: boolean;
};

type WorkAreaNavigation = ReturnType<typeof useWorkAreaNavigation>;
type WorkAreaItems = ReturnType<typeof useWorkAreaItems>;
type WorkAreaPartProps = {
  nav: WorkAreaNavigation;
  view: WorkAreaItems;
  projects: ProjectOption[];
  workspaceId: string;
  workspaceName: string;
  onOpenAdminTab?: (tab: AdminTab) => void;
};

export function WorkAreaWorkspace({ projects, initialWorkspaceId, onOpenAdminTab, onOpenArea, viewer, canManageWork = true }:
  WorkAreaWorkspaceProps) {
  const [workspaceId] = useActiveWorkspace(projects, initialWorkspaceId);
  const workspaceName = projects.find((project) => project.id === workspaceId)?.name ?? "";
  const nav = useWorkAreaNavigation(workspaceId, canManageWork, onOpenAdminTab);
  const view = useWorkAreaItems(workspaceId, nav.data, nav);
  const { sidebarCollapsed, plugin } = nav;
  const { pluginEntry } = plugin;

  return (
    <WorkAccessContext.Provider value={canManageWork}>
    <main className={`work-area ${sidebarCollapsed ? "work-area--sidebar-collapsed" : ""}`}>
      <WorkAreaSidebar nav={nav} canManageWork={canManageWork} onOpenArea={onOpenArea} />

      {pluginEntry ? (
        <WorkPluginPage entry={pluginEntry} workspaceId={workspaceId ?? null} viewer={viewer} />
      ) : (
      <WorkAreaMainSection nav={nav} view={view} projects={projects} workspaceId={workspaceId}
        workspaceName={workspaceName} onOpenAdminTab={onOpenAdminTab} />
      )}
    </main>
    </WorkAccessContext.Provider>
  );
}

function WorkAreaSidebar({ nav, canManageWork, onOpenArea }: {
  nav: WorkAreaNavigation;
  canManageWork: boolean;
  onOpenArea?: WorkAreaWorkspaceProps["onOpenArea"];
}) {
  const { sidebarCollapsed, toggleSidebarCollapsed, activeNav, setActiveNav } = nav;
  const { pluginGroups, pluginEntry, pluginPage, setPluginPage } = nav.plugin;
  return (
    <aside className="work-area__sidebar">
      <div className="work-area__brand">
        <div>
          <div className="work-area__eyebrow">Area</div>
          <AreaTitle area="Work" className="work-area__title" />
        </div>
        <button type="button" className="work-area__collapse" onClick={toggleSidebarCollapsed}
          aria-label={sidebarCollapsed ? "Expand Work navigation" : "Collapse Work navigation"}
          title={sidebarCollapsed ? "Expand navigation" : "Collapse navigation"}>
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d={sidebarCollapsed ? "M7 5l5 5-5 5" : "M13 5l-5 5 5 5"} />
          </svg>
        </button>
      </div>
      <WorkAreaNav host="work" activeKey={activeNav} onSelectLocal={(key) => { setPluginPage(null); setActiveNav(key as WorkNavKey); }}
        onOpenOther={(entry) => { const view = entryViewParam(entry); onOpenArea?.("coding", { [view.name]: view.value }); }}
        plugins={pluginGroups} activePlugin={pluginEntry ? pluginPage : null} onOpenPlugin={setPluginPage}
        canManage={canManageWork} />
    </aside>
  );
}

function WorkAreaMainSection({ nav, view, projects, workspaceId, workspaceName, onOpenAdminTab }: WorkAreaPartProps) {
  const { activeNav, itemsMode, setItemsMode, filters, setFilters, reloadToken, setReloadToken } = nav;
  const { items, workflows, loading, error, refresh } = nav.data;
  const { myWork, options, assigneeLabels, detail, setDetailRevision, selectedItem, selfLoading, asPage } = view;
  const activeNavItem = workNavItem(activeNav);
  // A page outside the Work menu (Jira write-back, opened from Admin › Connections since E6) has no menu group.
  const menuGroup = workAreaGroup("work", activeNav);
  return (
    <section className="work-area__main">
      <PageHeader eyebrow={menuGroup ? `Work · ${menuGroup}` : "Work"} title={menuGroup ? workAreaLabel("work", activeNav) : activeNavItem.label}
        purpose={activeNavItem.purpose}
        secondary={
          <button type="button" className="work-area__button"
            onClick={() => { setReloadToken((token) => token + 1); void refresh(); }}>
            Refresh
          </button>
        } />
      {workspaceId ? <WorkProblemsLine workspaceId={workspaceId} reloadKey={reloadToken} /> : null}

      <div className="work-area__body">
        {activeNav === "board" ? (
          <div className="work-items__toolbar">
            <SegmentedTabs label="Work items view" idPrefix="work-items-view" value={itemsMode}
              onChange={(key) => setItemsMode(key as WorkItemsMode)}
              tabs={[{ key: "board", label: "Board" }, { key: "table", label: "Table" }]} />
            {items.length > 0 ? <WorkScopeSwitch myWork={myWork} /> : null}
            {items.length > 0 ? (
              <WorkFiltersBar filters={filters} setFilters={setFilters} options={options} projects={projects}
                assigneeLabels={assigneeLabels} workflows={workflows} />
            ) : null}
          </div>
        ) : null}
        {error && !selfLoading ? <div className="work-area__error">{error}</div> : null}
        {loading && !selfLoading ? <LoadingState label="work items" variant="cards" rows={6} onRetry={() => void refresh()} /> : null}
        {asPage && selectedItem ? (
          <WorkItemDetailPanel item={selectedItem} workflows={workflows} onClose={detail.close} mode="page"
            projects={projects} onItemChanged={() => { setDetailRevision((value) => value + 1); void refresh(); }}
            focusPlanId={detail.selectedPlanId} onSelectPlan={detail.selectPlanVersion} onPlansChanged={detail.markPlansChanged} />
        ) : null}
          <WorkAreaContentGrid
            nav={nav}
            view={view}
            projects={projects}
            workspaceId={workspaceId}
            workspaceName={workspaceName}
            onOpenAdminTab={onOpenAdminTab}
          />
      </div>
    </section>
  );
}

function WorkAreaContentGrid({ nav, view, projects, workspaceId, workspaceName, onOpenAdminTab }: WorkAreaPartProps) {
  const { activeNav, setActiveNav, itemsMode, plansTab, setPlansTab, filters, reloadToken, openWorkspaceSettings } = nav;
  const { items, hasIntakes, workflows, refresh } = nav.data;
  const { handleEmptyAction } = nav;
  const { myWork, filteredItems, askMyWork, detail, setDetailRevision, selectedItem, location, asPage, ready, showItems } = view;
  return (
<div className="work-area__content-grid" hidden={asPage || undefined}>
  <div className="work-area__content-main">
    {ready && activeNav === "board" && askMyWork ? <WorkMyWorkPanel myWork={myWork} items={items} /> : null}
    {showItems && itemsMode === "board" ? (
      <WorkBoard items={filteredItems} hasIntakes={hasIntakes} onOpenItem={detail.openItem} workflows={workflows}
        nav={activeNav} hasItems={items.length > 0} onEmptyAction={handleEmptyAction} />
    ) : null}
    {showItems && itemsMode === "table" ? (
      // A new filter or scope starts on the first page; a state filter that names Done shows Done.
      <WorkTable key={`${JSON.stringify(filters)}:${myWork.scope}`} items={filteredItems} hasIntakes={hasIntakes}
        onOpenItem={detail.openItem} workflows={workflows} selectedId={detail.selectedItemId}
        showDoneDefault={Boolean(filters.workState)} nav={activeNav} hasItems={items.length > 0} onEmptyAction={handleEmptyAction} />
    ) : null}
    {activeNav === "changePlans" ? (
      <WorkPlansPage tab={plansTab} onTab={setPlansTab} projectId={workspaceId} onOpenWorkItems={() => setActiveNav("board")}
        reloadKey={`${reloadToken}:${detail.planRevision}`} selectedPlanId={detail.selectedPlanId}
        onOpenPlan={detail.openPlan} onOpenApprovalRule={() => onOpenAdminTab?.("approvalRule")} />
    ) : null}
    {activeNav === "runs" ? <WorkRunsPage projectId={workspaceId} reloadKey={reloadToken} /> : null}
    {ready && activeNav === "epics" ? (
      <WorkEpicsPage items={items} projectId={workspaceId} reloadKey={reloadToken} onOpenItem={detail.openItem} />
    ) : null}
    {activeNav === "intake" ? (
      workspaceId ? (
        <WorkIntakePage workspaceId={workspaceId} workspaceName={workspaceName} reloadKey={reloadToken}
          onOpenConnectors={() => openWorkspaceSettings("connectors")} />
      ) : <ChooseWorkspaceLine projects={projects} purpose="to see its intake" />
    ) : null}
    {ready && activeNav === "writeback" ? (
      workspaceId ? <WorkJiraWriteback workflows={workflows} workspaceId={workspaceId} projects={projects} onChanged={refresh} />
        : <ChooseWorkspaceLine projects={projects} purpose="to see its Jira write-back" />
    ) : null}
  </div>
  {selectedItem && !asPage ? (
    <WorkItemDetailPanel item={selectedItem} workflows={workflows} onClose={detail.close}
      pageHref={workItemPageHref(location.search, location.pathname)}
      projects={projects} onItemChanged={() => { setDetailRevision((value) => value + 1); void refresh(); }}
      focusPlanId={detail.selectedPlanId} onSelectPlan={detail.selectPlanVersion} onPlansChanged={detail.markPlansChanged} />
  ) : detail.selectedItemId ? (
    <WorkItemDetailPending selection={detail.selection} onClose={detail.close} />
  ) : null}
</div>
  );
}
