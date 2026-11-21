// The side panel's state, its lists, the file actions and the navigator's props, composed in hook order.
import type { ComponentProps } from "react";

import type { SelectedWorkspace, WorkspaceFileEntry } from "../chatWorkspaceTypes";
import type { ToolArtifact } from "../chatThreadTypes";
import { useWorkspaceFileSearch } from "./useWorkspaceFileSearch";
import { useWorkspacePreviewLayout } from "./useWorkspacePreviewLayout";
import { useWorkspacePreviewTabs } from "./useWorkspacePreviewTabs";
import { useWorkspaceSidePanelLists, useWorkspaceSidePanelState } from "./useWorkspaceSidePanelLists";
import { createWorkspaceFileActions } from "./workspaceSidePanelFileActions";
import type { WorkspaceFilesPanel } from "./WorkspaceSidePanelFilesPanel";

export type WorkspaceSidePanelProps = {
  workspace: SelectedWorkspace | null | undefined;
  onOpenArtifact: (artifact: ToolArtifact) => void;
  onRefresh?: () => void | Promise<void>;
  onLoadDirectory?: (path: string) => void | Promise<void>;
  onSearchFiles?: (query: string) => Promise<WorkspaceFileEntry[]>;
  onCreateFolder?: (path: string) => void | Promise<void>;
  onRenamePath?: (path: string, newName: string) => void | Promise<void>;
  onMovePaths?: (
    paths: string[],
    targetDirectory: string,
  ) => void | Promise<void>;
  onDeletePaths?: (paths: string[]) => void | Promise<void>;
  onClean?: () => void | Promise<void>;
};

export function useWorkspaceSidePanel({
  workspace,
  onOpenArtifact,
  onLoadDirectory,
  onSearchFiles,
  onCreateFolder,
  onRenamePath,
  onMovePaths,
  onDeletePaths,
  onClean,
}: WorkspaceSidePanelProps) {
  const state = useWorkspaceSidePanelState(workspace?.rootPath);
  const { activeTab, bulkMode, selectedPaths, expandedPaths, loadingDirectories, loweredQuery } = state;
  const previewTabs = useWorkspacePreviewTabs({
    workspaceRootPath: workspace?.rootPath,
    files: workspace?.files ?? [],
  });
  const previewLayout = useWorkspacePreviewLayout({
    enabled: Boolean(previewTabs.activePreviewEntry),
  });
  const { setSearchResults, setSearchLoading, setSearchError } = state;
  useWorkspaceFileSearch({ activeTab, loweredQuery, onSearchFiles, setSearchResults, setSearchLoading, setSearchError });
  const { displayedFiles, filteredChanges, childrenByParent, loadedDirectories, selectedEntries } =
    useWorkspaceSidePanelLists(workspace, loweredQuery, state.searchResults, selectedPaths);

  const actions = createWorkspaceFileActions({
    workspace, expandedPaths, loadingDirectories, loadedDirectories, selectedEntries,
    setSelectedPaths: state.setSelectedPaths, setExpandedPaths: state.setExpandedPaths,
    setLoadingDirectories: state.setLoadingDirectories, setBulkMode: state.setBulkMode,
    onLoadDirectory, onCreateFolder, onRenamePath, onMovePaths, onDeletePaths, onClean,
  });
  const filesPanel: ComponentProps<typeof WorkspaceFilesPanel> = {
    displayedFiles, searchLoading: state.searchLoading, searchError: state.searchError, loweredQuery, bulkMode,
    selectedEntries, selectedPaths, selectedPreviewPath: previewTabs.activePreviewPath, childrenByParent,
    expandedPaths, loadingDirectories, onToggleSelection: actions.toggleSelection, onToggleExpanded: actions.toggleExpanded,
    onSelectPreviewFile: previewTabs.openPreviewFile, onOpenArtifact, onRename: actions.handleRename,
    onMove: actions.handleMove, onDelete: actions.handleDelete,
  };

  return { state, previewTabs, previewLayout, displayedFiles, filteredChanges, actions, filesPanel };
}
