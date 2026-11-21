import { useRef, useState } from "react";

import type { ChatState } from "../types";
import type { ThreadGroup, ThreadSummary } from "../chatThreadTypes";
import { ThreadGroupSection } from "./ThreadGroupSection";
import { ThreadBulkActionBar, ThreadBulkHeader, ThreadBulkOverlays } from "./ThreadBulkControls";
import { partitionThreadGroups } from "./threadGroupPartition";
import { threadGroupBulk } from "./threadGroupBulk";
import { ThreadArchivedView } from "./ThreadArchivedView";
import { ThreadSearchBox } from "./ThreadSearchBox";
import { ThreadScopeToggle } from "./ThreadScopeToggle";
import { useThreadScope } from "./useThreadScope";
import { ThreadHoverCard } from "./ThreadHoverCard";
import { useThreadHoverCard } from "./useThreadHoverCard";
import { ThreadMarkerLegend } from "./ThreadMarkerLegend";
import type { ThreadRef } from "./threadSelection";
import { sectionThreads } from "./threadTime";
import type { ThreadBulkController } from "./useThreadBulk";
import { SidebarHeader, SidebarSectionRow, SidebarThreadList } from "./SidebarShellParts";
import { handleThreadsKeyDown } from "./sidebarThreadKeys";

type SidebarShellProps = {
  chatState: ChatState | null;
  filteredThreadGroups: ThreadGroup[];
  handleThreadSelect: (thread: ThreadSummary) => Promise<void>;
  handleNewThread: () => Promise<void>;
  threadSearchQuery: string;
  setThreadSearchQuery: (value: string) => void;
  threadBulk: ThreadBulkController;
  onPinThread: (thread: ThreadSummary) => void | Promise<void>;
  onRenameThread: (thread: ThreadSummary, title: string) => void | Promise<void>;
  onArchiveThread: (thread: ThreadSummary) => void | Promise<void>;
  onExportThread: (thread: ThreadSummary) => void | Promise<void>;
  onExportAnalysisThread: (thread: ThreadSummary) => void | Promise<void>;
  onDeleteThread: (thread: ThreadSummary) => void | Promise<void>;
  onLoadThreadGroupPage: (group: ThreadGroup) => void | Promise<void>;
  canDeleteThreads?: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
};

function countLabels(filteredThreadGroups: ThreadGroup[], searchActive: boolean) {
  const visibleThreadCount = filteredThreadGroups.reduce(
    (total, group) => total + (group.totalThreadCount ?? group.sessions.length), 0);
  const groupCount = filteredThreadGroups.length;
  const threadCountLabel = `${visibleThreadCount} ${
    searchActive ? (visibleThreadCount === 1 ? "match" : "matches") : visibleThreadCount === 1 ? "chat" : "chats"
  }`;
  const groupCountLabel = `${groupCount} ${groupCount === 1 ? "Workspace" : "Workspaces"}`;
  return { threadCountLabel, groupCountLabel };
}

function useSidebarModel(chatState: ChatState | null, searchedThreadGroups: ThreadGroup[], threadSearchQuery: string,
  bulkMode: boolean) {
  const scope = useThreadScope(chatState, searchedThreadGroups);
  const filteredThreadGroups = scope.groups;
  const searchQuery = threadSearchQuery.trim();
  const searchActive = searchQuery.length > 0;
  // Threads of workspaces that cannot be selected now stay reachable in one
  // collapsed section.
  const selectableProjectIds = new Set(
    (chatState?.projects ?? []).map((project) => project.id),
  );
  const partition = partitionThreadGroups(filteredThreadGroups, selectableProjectIds);
  const sidebarRef = useRef<HTMLElement>(null);
  const legendButtonRef = useRef<HTMLButtonElement>(null);
  const [legendOpen, setLegendOpen] = useState(false);
  const [archivedOpen, setArchivedOpen] = useState(false);
  const { hover, onRowHover } = useThreadHoverCard(sidebarRef, bulkMode);
  // An unsent new chat shows as one draft row in its Workspace (nothing is stored before the first message).
  const draftProjectId =
    chatState && !chatState.selectedSession ? (chatState.selectedProjectId ?? "") : null;
  const draftHasGroup =
    draftProjectId !== null &&
    filteredThreadGroups.some((group) => (group.projectId ?? "") === draftProjectId);
  // Visible top-level rows in render order: the range for shift-click and ⌘/Ctrl+A.
  const orderedRefs: ThreadRef[] = [...partition.active, ...partition.other].flatMap((group) =>
    sectionThreads(group.sessions).flatMap((section) =>
      section.threads.map((thread) => ({ id: thread.id, projectId: group.projectId ?? "" })),
    ),
  );
  return {
    scope, filteredThreadGroups, searchQuery, searchActive, ...countLabels(filteredThreadGroups, searchActive),
    ...partition, sidebarRef, legendButtonRef, legendOpen, setLegendOpen, archivedOpen, setArchivedOpen,
    hover, onRowHover, draftProjectId, showStandaloneDraft: draftProjectId !== null && !draftHasGroup && !bulkMode,
    orderedRefs,
  };
}

type SidebarModel = ReturnType<typeof useSidebarModel>;

function groupRenderer(props: SidebarShellProps, model: SidebarModel) {
  const { threadBulk, canDeleteThreads = false, handleNewThread, onLoadThreadGroupPage } = props;
  const { draftProjectId, searchActive, orderedRefs, onRowHover } = model;
  const bulkMode = threadBulk.bulkMode;
  const refOf = (group: ThreadGroup, thread: ThreadSummary): ThreadRef => ({
    id: thread.id,
    projectId: group.projectId ?? "",
  });
  return (group: ThreadGroup) => (
    <ThreadGroupSection
      key={group.projectId ?? `name:${group.projectName}`}
      group={group}
      onSelect={props.handleThreadSelect}
      onPinToggle={props.onPinThread}
      onRename={props.onRenameThread}
      onArchive={(thread) =>
        thread.parentSessionId
          ? props.onArchiveThread(thread)
          : threadBulk.archiveOne(refOf(group, thread))
      }
      onExport={props.onExportThread}
      onExportAnalysis={props.onExportAnalysisThread}
      onDelete={(thread) =>
        thread.parentSessionId
          ? props.onDeleteThread(thread)
          : threadBulk.deleteOne(refOf(group, thread))
      }
      canDeleteThreads={canDeleteThreads}
      searching={searchActive}
      bulk={bulkMode ? threadGroupBulk(threadBulk, group, orderedRefs) : undefined}
      onEnterBulk={(thread) => threadBulk.enter(refOf(group, thread))}
      onLoadMore={() => onLoadThreadGroupPage(group)}
      onRowHover={onRowHover(group.projectName)}
      onDraftSelect={
        draftProjectId !== null && (group.projectId ?? "") === draftProjectId
          ? () => void handleNewThread()
          : undefined
      }
    />
  );
}

export function SidebarShell(props: SidebarShellProps) {
  const { chatState, handleNewThread, threadSearchQuery, setThreadSearchQuery, threadBulk, collapsed, onToggleCollapsed } = props;
  const bulkMode = threadBulk.bulkMode;
  const model = useSidebarModel(chatState, props.filteredThreadGroups, threadSearchQuery, bulkMode);
  const { scope, filteredThreadGroups, searchActive, orderedRefs, legendButtonRef, legendOpen, setLegendOpen, archivedOpen,
    setArchivedOpen } = model;
  const archivedCount = chatState?.archivedThreadCount ?? 0;
  const renderGroup = groupRenderer(props, model);
  return (
    <aside className="sidebar" ref={model.sidebarRef}>
      <div className="sidebar__pane">
        <SidebarHeader dashboardUrl={chatState?.dashboardUrl} collapsed={collapsed} onToggleCollapsed={onToggleCollapsed} />
        <div className="sidebar__section">
          {bulkMode ? (
            <ThreadBulkHeader threadBulk={threadBulk} visibleIds={orderedRefs.map((ref) => ref.id)} />
          ) : (
            <SidebarSectionRow threadCountLabel={model.threadCountLabel} groupCountLabel={model.groupCountLabel}
              legendButtonRef={legendButtonRef} legendOpen={legendOpen} onToggleLegend={() => setLegendOpen((value) => !value)}
              onSelectChats={() => threadBulk.enter()} onNewChat={() => void handleNewThread()} />
          )}
          <ThreadSearchBox value={threadSearchQuery} onChange={setThreadSearchQuery} />
          {scope.activeProjectId ? <ThreadScopeToggle {...scope.toggle} /> : null}
        </div>
        <div className="sidebar__threads" onKeyDown={(event) => handleThreadsKeyDown(event, bulkMode, threadBulk, orderedRefs)}>
          {archivedOpen && !bulkMode ? (
            <ThreadArchivedView onBack={() => setArchivedOpen(false)} onRestore={threadBulk.restore} />
          ) : (
            <SidebarThreadList showStandaloneDraft={model.showStandaloneDraft} onNewChat={() => void handleNewThread()}
              activeGroups={model.active} otherGroups={model.other} otherThreadCount={model.otherThreadCount}
              hasGroups={filteredThreadGroups.length > 0} renderGroup={renderGroup} searchActive={searchActive}
              searchQuery={model.searchQuery} showArchivedLink={!searchActive && !bulkMode && archivedCount > 0}
              archivedCount={archivedCount} onOpenArchived={() => setArchivedOpen(true)} />
          )}
        </div>
        {bulkMode ? <ThreadBulkActionBar threadBulk={threadBulk} groups={filteredThreadGroups} /> : null}
      </div>
      <ThreadBulkOverlays threadBulk={threadBulk} />
      <ThreadHoverCard hover={model.hover} />
      {legendOpen && !bulkMode ? (
        <ThreadMarkerLegend anchorRef={legendButtonRef} onClose={() => setLegendOpen(false)} />
      ) : null}
    </aside>
  );
}
