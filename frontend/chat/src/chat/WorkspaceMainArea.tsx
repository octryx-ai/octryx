import type { CSSProperties } from "react";

import { WorkspaceSidePanel } from "./WorkspaceSidePanel";
import { WorkspacePrimarySection } from "./WorkspacePrimarySection";
import { useWorkspacePanelLayout } from "./useWorkspacePanelLayout";
import { pickWorkspacePrimarySectionProps } from "./workspacePrimarySectionProps";

type WorkspaceMainAreaProps = any;

export function WorkspaceMainArea(props: WorkspaceMainAreaProps) {
  const {
    workspacePanelOpen,
    setPreviewArtifact,
    effectiveWorkspace,
    handleRefreshWorkspace,
    handleLoadWorkspaceDirectory,
    handleSearchWorkspace,
    handleCreateWorkspaceFolder,
    handleRenameWorkspacePath,
    handleMoveWorkspacePaths,
    handleDeleteWorkspacePaths,
    handleCleanWorkspace,
  } = props;
  const { layoutStyle, handleResizeStart } = useWorkspacePanelLayout({
    open: workspacePanelOpen,
  });

  return (
    <main className="workspace">
      <div
        className={`workspace__layout ${workspacePanelOpen ? "workspace__layout--workspace-open" : ""}`}
        style={layoutStyle as CSSProperties | undefined}
      >
        <WorkspacePrimarySection {...pickWorkspacePrimarySectionProps(props)} />

        {workspacePanelOpen ? (
          <>
            <div
              className="workspace__resize-handle"
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize workspace panel"
              onMouseDown={handleResizeStart}
            />
            <WorkspaceSidePanel
              workspace={effectiveWorkspace}
              onOpenArtifact={setPreviewArtifact}
              onRefresh={handleRefreshWorkspace}
              onLoadDirectory={handleLoadWorkspaceDirectory}
              onSearchFiles={handleSearchWorkspace}
              onCreateFolder={handleCreateWorkspaceFolder}
              onRenamePath={handleRenameWorkspacePath}
              onMovePaths={handleMoveWorkspacePaths}
              onDeletePaths={handleDeleteWorkspacePaths}
              onClean={handleCleanWorkspace}
            />
          </>
        ) : null}
      </div>
    </main>
  );
}
