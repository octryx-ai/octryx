import { useEffect } from "react";

import { CodingSessionDetail } from "./CodingSessionDetail";
import type { ProjectOption } from "../../chatOptionTypes";
import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import { useActiveWorkspace } from "../useActiveWorkspace";
import { requestWorkspaceSettings } from "../../admin/components/projectsTab/workspaceSettingsLink";
import { CodingSessionStartDialog } from "./CodingSessionStartDialog";
import { CODING_NAV_ITEMS, codingViewParam, type CodingNavKey } from "./CodingAreaNav";
import { usePluginSlots } from "../../admin/components/plugins/usePluginSlots";
import { desktopFetch } from "../../admin/components/plugins/pluginUiApi";
import { workAreaGroup, workAreaLabel } from "../work/workAreaMenu";
import { CodingSessionList, CodingSummary } from "./CodingSessionQueue";
import { CodingMissingSessionNotice } from "./CodingQueueEmptyState";
import { CodingExecutionNotice } from "./CodingExecutionNotice";
import { PageHeader } from "../../layout/PageHeader";
import { LoadingState } from "../../layout/LoadingState";
import { replaceCodingWorkItemUrl, storeSidebarCollapsedPreference } from "./codingAreaBrowser";
import { useCodingAreaState } from "./useCodingAreaState";
import { useCodingAreaSessions, type CodingAreaState } from "./useCodingAreaSessions";
import { RESTART_REASON, startCodingAgent } from "./codingAgentStart";
import { CodingAreaSidebar } from "./CodingAreaSidebar";
import { CodingConfigurePages } from "./CodingConfigurePages";
import { CodingAreaEmptyQueue, CodingAreaStartAction, CodingSessionFilters } from "./CodingAreaQueueParts";

type CodingAreaWorkspaceProps = {
  projects?: ProjectOption[];
  // Opens a Work page of the one Work menu (work/workAreaMenu.ts) with its address field.
  onOpenArea?: (area: "work", params: Record<string, string>) => void;
  initialWorkspaceId?: string | null;
  onOpenAdminTab?: (tab: AdminTab) => void;
};

type SessionsPaneProps = {
  state: CodingAreaState;
  lists: ReturnType<typeof useCodingAreaSessions>;
  onStartAgent: (restart: boolean) => void;
};

// The session list beside the selected session's detail (or the notice for an item without a session).
function CodingSessionsPane({ state, lists, onStartAgent }: SessionsPaneProps) {
  const { selectedId, setSelectedId, setActiveTab, refreshReview, setStartDialogOpen } = state;
  const { filteredSessions, selectedSession, selectedWorkItem } = lists;
  return (
    <div className={`coding-area__layout ${selectedSession ? "has-detail" : ""}`}>
      <CodingSessionList
        sessions={filteredSessions}
        selectedId={selectedId}
        onSelect={(id) => {
          setSelectedId(id);
          replaceCodingWorkItemUrl(id);
          setActiveTab("overview");
        }}
      />
      {selectedSession ? (
        <CodingSessionDetail
          session={selectedSession}
          detail={lists.shownDetail}
          loading={state.detailLoading}
          activeTab={state.activeTab}
          startingAgent={state.agentStartBusy}
          onTabChange={setActiveTab}
          onStartAgent={() => onStartAgent(false)}
          onRestartAgent={() => onStartAgent(true)}
          onReviewRecorded={() => void refreshReview(selectedSession.id)}
          onRetryReview={() => void refreshReview(selectedSession.id)}
          onRetryDetail={() => state.setDetailReload((count) => count + 1)}
        />
      ) : selectedWorkItem ? (
        <CodingMissingSessionNotice workItem={selectedWorkItem} onStart={() => setStartDialogOpen(true)} />
      ) : null}
    </div>
  );
}

// The chosen page stays in the address, as Work's pages do: a reload reopens it and its page help is its own.
function useCodingViewAddress(activeNav: CodingNavKey) {
  useEffect(() => {
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get("coding_view") === codingViewParam(activeNav)) return;
      url.searchParams.set("coding_view", codingViewParam(activeNav));
      window.history.replaceState(window.history.state, "", url.toString());
    } catch {
      // An address that cannot be written leaves the page as it is.
    }
  }, [activeNav]);
}

function CodingAreaBody({ state, lists, activeQueue, workspaceId, workspaceName, activeNavItem,
  onOpenAdminTab, openWorkspaceSettings, onStartAgent }: SessionsPaneProps & {
  activeQueue: ReturnType<typeof useCodingAreaState>["sessionQueue"] | null;
  workspaceId: string;
  workspaceName: string;
  activeNavItem: (typeof CODING_NAV_ITEMS)[number];
  onOpenAdminTab?: (tab: AdminTab) => void;
  openWorkspaceSettings: (section: "connectors" | "repositories" | "access" | "coding") => void;
}) {
  const { sessions, loading, error, executionNotice, search, setSearch, setSessionQueue, setActiveNav, refresh } = state;
  const { queueSessions, filteredSessions, keepDetail } = lists;
  return (
    <div className="work-area__body">
      {activeQueue ? (
        <CodingSessionFilters sessions={sessions} sessionQueue={state.sessionQueue} setSessionQueue={setSessionQueue}
          showSearch={queueSessions.length > 0} search={search} setSearch={setSearch} />
      ) : null}
      {activeQueue && !loading ? <CodingSummary sessions={sessions} /> : null}
      {error ? <div className="work-area__error">{error}</div> : null}
      {executionNotice ? <CodingExecutionNotice notice={executionNotice} /> : null}
      {/* Only on the Sessions pages that list them (on Work › Repositories these skeleton rows
          stood next to the repository list's own loading and empty state). */}
      {loading && activeQueue ? <LoadingState label="coding sessions" onRetry={() => void refresh()} /> : null}
      <CodingConfigurePages activeQueue={activeQueue} workspaceId={workspaceId} workspaceName={workspaceName}
        activeNav={state.activeNav} activeNavItem={activeNavItem} onOpenAdminTab={onOpenAdminTab}
        openWorkspaceSettings={openWorkspaceSettings} setActiveNav={setActiveNav} addingRule={state.addingRule}
        setAddingRule={state.setAddingRule} setRulesEditable={state.setRulesEditable} />
      {!loading && activeQueue && filteredSessions.length === 0 ? (
        <CodingAreaEmptyQueue queue={activeQueue} queueCount={queueSessions.length} workItemCount={state.workItemCount}
          search={search} sessions={sessions} onStart={() => state.setStartDialogOpen(true)}
          onClearSearch={() => setSearch("")} onOpenQueue={setSessionQueue} />
      ) : null}
      {!loading && activeQueue && (filteredSessions.length > 0 || keepDetail) ? (
        <CodingSessionsPane state={state} lists={lists} onStartAgent={onStartAgent} />
      ) : null}
    </div>
  );
}

// The page's handlers: Workspace settings, the sidebar toggle and the coding agent's start or restart.
function codingAreaActions(
  state: CodingAreaState,
  selectedSession: ReturnType<typeof useCodingAreaSessions>["selectedSession"],
  workspaceId: string,
  onOpenAdminTab?: (tab: AdminTab) => void,
) {
  // Workspace settings → a section of the active Workspace (Connectors, Repositories, Access).
  function openWorkspaceSettings(section: "connectors" | "repositories" | "access" | "coding") {
    if (workspaceId) requestWorkspaceSettings(workspaceId, section);
    onOpenAdminTab?.("projects");
  }

  function toggleSidebarCollapsed() {
    state.setSidebarCollapsed((current) => {
      const next = !current;
      storeSidebarCollapsedPreference(next);
      return next;
    });
  }

  const onStartAgent = (restart: boolean) =>
    void startCodingAgent(state, selectedSession, restart
      ? { restartFromScratch: true, restartReason: RESTART_REASON }
      : { restartFromScratch: false });
  return { openWorkspaceSettings, toggleSidebarCollapsed, onStartAgent };
}

export function CodingAreaWorkspace({ projects = [], initialWorkspaceId = null, onOpenAdminTab,
  onOpenArea }: CodingAreaWorkspaceProps = {}) {
  const [workspaceId] = useActiveWorkspace(projects, initialWorkspaceId);
  const workspaceName = projects.find((project) => project.id === workspaceId)?.name ?? "";
  // Plugin pages of the Work menu open in the Work host (plugins contract §4).
  const pluginSlots = usePluginSlots(workspaceId, desktopFetch);
  const state = useCodingAreaState(workspaceId);
  const { sessionQueue, workItemCount, loading, activeNav, setActiveNav, sidebarCollapsed,
    rulesEditable, setStartDialogOpen, refresh } = state;

  const activeQueue = activeNav === "sessions" ? sessionQueue : null;
  useCodingViewAddress(activeNav);
  const lists = useCodingAreaSessions(state, activeQueue);
  const activeNavItem = CODING_NAV_ITEMS.find((item) => item.key === activeNav) || CODING_NAV_ITEMS[0];
  // Why a coding session cannot start yet, or null when it can.
  const startBlocked = !workspaceId ? "Select a Workspace first" : !loading && workItemCount === 0 ? "Import work items first" : null;

  const { openWorkspaceSettings, toggleSidebarCollapsed, onStartAgent } =
    codingAreaActions(state, lists.selectedSession, workspaceId, onOpenAdminTab);

  return (
    <main className={`work-area coding-area ${sidebarCollapsed ? "work-area--sidebar-collapsed" : ""}`}>
      <CodingAreaSidebar sidebarCollapsed={sidebarCollapsed} toggleSidebarCollapsed={toggleSidebarCollapsed}
        activeNav={activeNav} setActiveNav={setActiveNav} onOpenArea={onOpenArea} pluginEntries={pluginSlots.entries} />

      <section className="work-area__main">
        {/* A page outside the menu (the Delivery pipeline, opened from Coding rules) keeps its own name, not its key. */}
        <PageHeader eyebrow={`Work · ${workAreaGroup("coding", activeNav) || "Configure"}`}
          title={workAreaLabel("coding", activeNav) === activeNav ? activeNavItem.label : workAreaLabel("coding", activeNav)} purpose={activeNavItem.purpose}
          secondary={activeQueue ? <button type="button" className="work-area__button" onClick={() => void refresh()}>Refresh</button> : null}
          primary={<CodingAreaStartAction rulesPage={activeNav === "rules"} canAddRule={Boolean(rulesEditable && workspaceId)}
            activeQueue={activeQueue} startBlocked={startBlocked} onAddRule={() => state.setAddingRule(true)}
            onStart={() => setStartDialogOpen(true)} />} />

        <CodingAreaBody state={state} lists={lists} activeQueue={activeQueue} workspaceId={workspaceId}
          workspaceName={workspaceName} activeNavItem={activeNavItem}
          onOpenAdminTab={onOpenAdminTab} openWorkspaceSettings={openWorkspaceSettings} onStartAgent={onStartAgent} />
      </section>
      <CodingSessionStartDialog
        open={state.startDialogOpen}
        items={state.workItems}
        repositoryProfiles={state.repositoryProfiles}
        onClose={() => setStartDialogOpen(false)}
        onCreated={(workItemId) => {
          setStartDialogOpen(false);
          void refresh(workItemId);
        }}
      />
    </main>
  );
}
