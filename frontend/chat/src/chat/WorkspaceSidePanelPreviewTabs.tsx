import type { WorkspaceFileEntry } from "../chatWorkspaceTypes";
import { workspaceFileTypeLabel } from "./workspaceSidePanelHelpers";

function ClosePreviewTabIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M6 6 14 14" />
      <path d="M14 6 6 14" />
    </svg>
  );
}

export function WorkspaceSidePanelPreviewTabs({
  activePreviewPath,
  openPreviewEntries,
  onCloseTab,
  onSelectTab,
}: {
  activePreviewPath: string;
  openPreviewEntries: WorkspaceFileEntry[];
  onCloseTab: (relativePath: string) => void;
  onSelectTab: (relativePath: string) => void;
}) {
  if (!openPreviewEntries.length) {
    return null;
  }

  return (
    <div
      className="workspace-sidepanel__preview-tabs"
      role="tablist"
      aria-label="Open preview files"
    >
      {openPreviewEntries.map((entry) => {
        const isActive = activePreviewPath === entry.relativePath;
        return (
          <div
            key={entry.relativePath}
            className={`workspace-sidepanel__preview-tab ${isActive ? "workspace-sidepanel__preview-tab--active" : ""}`}
          >
            <button
              type="button"
              role="tab"
              aria-selected={isActive}
              className="workspace-sidepanel__preview-tab-button"
              title={entry.relativePath}
              onClick={() => onSelectTab(entry.relativePath)}
            >
              <span className="workspace-sidepanel__preview-tab-type">
                {workspaceFileTypeLabel(entry.name)}
              </span>
              <span className="workspace-sidepanel__preview-tab-name">
                {entry.name}
              </span>
            </button>
            <button
              type="button"
              className="workspace-sidepanel__preview-tab-close"
              aria-label={`Close ${entry.name}`}
              title={`Close ${entry.name}`}
              onClick={() => onCloseTab(entry.relativePath)}
            >
              <ClosePreviewTabIcon />
            </button>
          </div>
        );
      })}
    </div>
  );
}
