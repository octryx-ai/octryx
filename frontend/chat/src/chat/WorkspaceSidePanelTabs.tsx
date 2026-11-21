// The side panel's two tab bodies: the file navigator (with the preview beside it) and the change list.
import type { ComponentProps } from "react";

import type { ToolArtifact } from "../chatThreadTypes";
import type { WorkspaceChangeEntry } from "../chatWorkspaceTypes";
import type { useWorkspacePreviewLayout } from "./useWorkspacePreviewLayout";
import type { useWorkspacePreviewTabs } from "./useWorkspacePreviewTabs";
import { WorkspaceSidePanelPreviewPanel } from "./WorkspaceSidePanelPreviewPanel";
import { WorkspaceChangesPanel } from "./workspaceSidePanelPanels";
import { WorkspaceFilesPanel } from "./WorkspaceSidePanelFilesPanel";

type FilesTabProps = {
  previewTabs: ReturnType<typeof useWorkspacePreviewTabs>;
  previewLayout: ReturnType<typeof useWorkspacePreviewLayout>;
  filesPanel: ComponentProps<typeof WorkspaceFilesPanel>;
  onOpenArtifact: (artifact: ToolArtifact) => void;
};

function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="workspace-sidepanel__section-header">
      <span className="workspace-sidepanel__section-title">
        {title}
      </span>
      <span className="workspace-sidepanel__section-meta">
        {count} item
        {count === 1 ? "" : "s"}
      </span>
    </div>
  );
}

export function WorkspaceFilesTab({ previewTabs, previewLayout, filesPanel, onOpenArtifact }: FilesTabProps) {
  const { activePreviewEntry } = previewTabs;
  return (
    <div
      ref={previewLayout.containerRef}
      className={`workspace-sidepanel__content-layout ${activePreviewEntry ? "workspace-sidepanel__content-layout--preview" : ""}`}
      style={previewLayout.layoutStyle}
    >
      {activePreviewEntry ? (
        <>
          <WorkspaceSidePanelPreviewPanel
            activePreviewPath={previewTabs.activePreviewPath}
            openPreviewEntries={previewTabs.openPreviewEntries}
            selectedEntry={activePreviewEntry}
            onClosePreviewPath={previewTabs.closePreviewPath}
            onOpenArtifact={onOpenArtifact}
            onSelectPreviewPath={previewTabs.selectPreviewPath}
          />
          <div
            className="workspace-sidepanel__content-resize-handle"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize preview and navigator"
            onMouseDown={previewLayout.handleResizeStart}
          />
        </>
      ) : null}
      <section className="workspace-sidepanel__navigator-panel">
        <SectionHeader title="Navigator" count={filesPanel.displayedFiles.length} />
        <section className="workspace-sidepanel__navigator">
          <WorkspaceFilesPanel {...filesPanel} />
        </section>
      </section>
    </div>
  );
}

export function WorkspaceChangesTab({ filteredChanges }: { filteredChanges: WorkspaceChangeEntry[] }) {
  return (
    <section className="workspace-sidepanel__changes-panel">
      <SectionHeader title="Changes" count={filteredChanges.length} />
      <WorkspaceChangesPanel filteredChanges={filteredChanges} />
    </section>
  );
}
