// The workspace side panel: header, Files/Changes tabs, the file navigator with preview, and the change list.
import { useWorkspaceSidePanel, type WorkspaceSidePanelProps } from "./useWorkspaceSidePanel";
import { WorkspaceSidePanelControls, WorkspaceSidePanelHeader } from "./workspaceSidePanelPanels";
import { WorkspaceChangesTab, WorkspaceFilesTab } from "./WorkspaceSidePanelTabs";

export function WorkspaceSidePanel(props: WorkspaceSidePanelProps) {
  const { workspace, onOpenArtifact, onRefresh } = props;
  const { state, previewTabs, previewLayout, displayedFiles, filteredChanges, actions, filesPanel } =
    useWorkspaceSidePanel(props);
  const { activeTab, bulkMode } = state;

  return (
    <aside className="workspace-sidepanel">
      <WorkspaceSidePanelHeader
        rootPath={workspace?.rootPath}
        rootLabel={workspace?.rootLabel}
        onCopyRootPath={actions.handleCopyRootPath}
        onCreateFolder={actions.handleCreateFolder}
        onClean={actions.handleClean}
        onRefresh={() => onRefresh?.()}
      />

      <WorkspaceSidePanelControls
        activeTab={activeTab}
        onChangeTab={state.setActiveTab}
        bulkMode={bulkMode}
        onToggleBulkMode={actions.handleBulkModeToggle}
        query={state.query}
        onQueryChange={state.setQuery}
        fileCount={displayedFiles.length}
        changeCount={filteredChanges.length}
      />

      <div className="workspace-sidepanel__body">
        {activeTab === "files" ? (
          <WorkspaceFilesTab previewTabs={previewTabs} previewLayout={previewLayout} filesPanel={filesPanel}
            onOpenArtifact={onOpenArtifact} />
        ) : (
          <WorkspaceChangesTab filteredChanges={filteredChanges} />
        )}
      </div>
    </aside>
  );
}
