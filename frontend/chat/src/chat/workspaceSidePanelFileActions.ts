// File navigator actions of the workspace side panel: selection, folder expansion, create/rename/move/delete, clean, copy path.
import type { Dispatch, SetStateAction } from "react";

import type { SelectedWorkspace, WorkspaceFileEntry } from "../chatWorkspaceTypes";

type WorkspaceFileActionsArgs = {
  workspace: SelectedWorkspace | null | undefined;
  expandedPaths: Record<string, boolean>;
  loadingDirectories: Record<string, boolean>;
  loadedDirectories: Set<string>;
  selectedEntries: WorkspaceFileEntry[];
  setSelectedPaths: Dispatch<SetStateAction<string[]>>;
  setExpandedPaths: Dispatch<SetStateAction<Record<string, boolean>>>;
  setLoadingDirectories: Dispatch<SetStateAction<Record<string, boolean>>>;
  setBulkMode: Dispatch<SetStateAction<boolean>>;
  onLoadDirectory?: (path: string) => void | Promise<void>;
  onCreateFolder?: (path: string) => void | Promise<void>;
  onRenamePath?: (path: string, newName: string) => void | Promise<void>;
  onMovePaths?: (paths: string[], targetDirectory: string) => void | Promise<void>;
  onDeletePaths?: (paths: string[]) => void | Promise<void>;
  onClean?: () => void | Promise<void>;
};

export function createWorkspaceFileActions(args: WorkspaceFileActionsArgs) {
  return { ...navigationActions(args), ...editActions(args) };
}

// Selection, folder expansion (loading a folder's children on first open), copy path and bulk mode.
function navigationActions({
  workspace, expandedPaths, loadingDirectories, loadedDirectories, setSelectedPaths, setExpandedPaths, setLoadingDirectories,
  setBulkMode, onLoadDirectory,
}: WorkspaceFileActionsArgs) {

  const toggleSelection = (relativePath: string) => {
    setSelectedPaths((current) =>
      current.includes(relativePath)
        ? current.filter((item) => item !== relativePath)
        : [...current, relativePath],
    );
  };

  const toggleExpanded = (relativePath: string) => toggleFolder(relativePath, {
    workspace, expandedPaths, loadingDirectories, loadedDirectories, setExpandedPaths, setLoadingDirectories, onLoadDirectory,
  });

  const handleCopyRootPath = async () => {
    const value = String(workspace?.rootPath || "").trim();
    if (!value) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      window.prompt("Copy workspace path", value);
    }
  };

  const handleBulkModeToggle = () => {
    setBulkMode((current) => {
      const next = !current;
      if (!next) {
        setSelectedPaths([]);
      }
      return next;
    });
  };

  return { toggleSelection, toggleExpanded, handleCopyRootPath, handleBulkModeToggle };
}

// Create, rename, move, delete and clean, each asked for in a browser prompt or confirmation.
function editActions({
  selectedEntries, setSelectedPaths, onCreateFolder, onRenamePath, onMovePaths, onDeletePaths, onClean,
}: WorkspaceFileActionsArgs) {
  const handleCreateFolder = async () => {
    const nextPath = window.prompt("Folder name or relative path", "new-folder");
    if (!nextPath) {
      return;
    }
    await onCreateFolder?.(nextPath.trim());
  };

  const handleRename = async () => {
    if (selectedEntries.length !== 1) {
      return;
    }
    const entry = selectedEntries[0];
    const nextName = window.prompt("New name", entry.name);
    if (!nextName || nextName === entry.name) {
      return;
    }
    await onRenamePath?.(entry.relativePath, nextName.trim());
    setSelectedPaths([]);
  };

  const handleMove = async () => {
    if (!selectedEntries.length) {
      return;
    }
    const defaultTarget = selectedEntries[0]?.parentPath || "";
    const targetDirectory = window.prompt("Target directory relative to the workspace", defaultTarget);
    if (targetDirectory === null) {
      return;
    }
    await onMovePaths?.(selectedEntries.map((entry) => entry.relativePath), targetDirectory.trim());
    setSelectedPaths([]);
  };

  const handleDelete = async () => {
    if (!selectedEntries.length) {
      return;
    }
    if (!window.confirm(`Delete ${selectedEntries.length} selected item(s)?`)) {
      return;
    }
    await onDeletePaths?.(selectedEntries.map((entry) => entry.relativePath));
    setSelectedPaths([]);
  };

  const handleClean = async () => {
    if (!window.confirm("Remove all working files?")) {
      return;
    }
    await onClean?.();
    setSelectedPaths([]);
  };

  return { handleCreateFolder, handleRename, handleMove, handleDelete, handleClean };
}

// Opens or closes a folder; a folder with children not loaded yet loads them on its first open.
async function toggleFolder(relativePath: string, {
  workspace, expandedPaths, loadingDirectories, loadedDirectories, setExpandedPaths, setLoadingDirectories, onLoadDirectory,
}: Pick<WorkspaceFileActionsArgs, "workspace" | "expandedPaths" | "loadingDirectories" | "loadedDirectories" | "setExpandedPaths"
  | "setLoadingDirectories" | "onLoadDirectory">) {
  const entry = (workspace?.files ?? []).find(
    (file) => file.relativePath === relativePath,
  );
  const hasKnownChildren = Number(entry?.childCount || 0) > 0;
  const willOpen = !(expandedPaths[relativePath] ?? true);
  setExpandedPaths((current) => ({
    ...current,
    [relativePath]: willOpen,
  }));
  if (
    willOpen &&
    hasKnownChildren &&
    !loadedDirectories.has(relativePath) &&
    !loadingDirectories[relativePath]
  ) {
    setLoadingDirectories((current) => ({
      ...current,
      [relativePath]: true,
    }));
    try {
      await onLoadDirectory?.(relativePath);
    } finally {
      setLoadingDirectories((current) => {
        const next = { ...current };
        delete next[relativePath];
        return next;
      });
    }
  }
}
