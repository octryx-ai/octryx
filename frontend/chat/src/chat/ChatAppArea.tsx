// The Chat area of the app shell: the session sidebar and the chat workspace with its composer.

import { SidebarShell } from "./SidebarShell";
import { WORKSPACE_MAIN_PROP_KEYS } from "./chatAppAreaProps";
import { WorkspaceMainArea } from "./WorkspaceMainArea";

export function ChatAppArea(props: any) {
  const {
    chatState, sidebarOpen, setSidebarOpen, chatSidebarCollapsed, setChatSidebarCollapsed, filteredThreadGroups,
    handleThreadSelect, handleNewThread, threadSearchQuery, setThreadSearchQuery, threadBulk, handlePinThread,
    handleRenameThread, handleArchiveThread, handleExportThread, handleExportAnalysisThread, handleDeleteThread,
    handleLoadThreadGroupPage, canDeleteThreads,
  } = props;
  const workspaceProps = Object.fromEntries(WORKSPACE_MAIN_PROP_KEYS.map((key) => [key, props[key]]));
  return (
    <div
      className={[
        "chat-app",
        sidebarOpen ? "chat-app--sidebar-open" : "",
        chatSidebarCollapsed ? "chat-app--sessions-collapsed" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
    <div className="chat-app__atmosphere" aria-hidden="true" />
    <div className="mobile-overlay" onClick={() => setSidebarOpen(false)} />

    <div className="chat-app__sidebar-shell">
      <SidebarShell
        chatState={chatState}
        filteredThreadGroups={filteredThreadGroups}
        handleThreadSelect={handleThreadSelect}
        handleNewThread={handleNewThread}
        threadSearchQuery={threadSearchQuery}
        setThreadSearchQuery={setThreadSearchQuery}
        threadBulk={threadBulk}
        onPinThread={handlePinThread}
        onRenameThread={handleRenameThread}
        onArchiveThread={handleArchiveThread}
        onExportThread={handleExportThread}
        onExportAnalysisThread={handleExportAnalysisThread}
        onDeleteThread={handleDeleteThread}
        onLoadThreadGroupPage={handleLoadThreadGroupPage}
        canDeleteThreads={canDeleteThreads}
        collapsed={chatSidebarCollapsed}
        onToggleCollapsed={() =>
          setChatSidebarCollapsed((current: boolean) => !current)
        }
      />
    </div>

    <div className="chat-app__workspace-shell">
      <WorkspaceMainArea {...(workspaceProps as any)} />
    </div>
    </div>
  );
}
