// The side panel's local state and the lists it shows: files (or search hits) by folder, filtered changes, selection.
import { useEffect, useMemo, useState } from "react";

import type { SelectedWorkspace, WorkspaceFileEntry } from "../chatWorkspaceTypes";
import { relativeParent } from "./workspaceSidePanelHelpers";

export type WorkspaceTab = "files" | "changes";

export function useWorkspaceSidePanelState(rootPath: string | undefined) {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("files");
  const [query, setQuery] = useState("");
  const [bulkMode, setBulkMode] = useState(false);
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>(
    {},
  );
  const [loadingDirectories, setLoadingDirectories] = useState<
    Record<string, boolean>
  >({});
  const [searchResults, setSearchResults] = useState<WorkspaceFileEntry[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const loweredQuery = query.trim().toLowerCase();

  useEffect(() => {
    setSelectedPaths([]);
    setLoadingDirectories({});
    setBulkMode(false);
  }, [rootPath]);

  return {
    activeTab, setActiveTab, query, setQuery, bulkMode, setBulkMode, selectedPaths, setSelectedPaths,
    expandedPaths, setExpandedPaths, loadingDirectories, setLoadingDirectories, searchResults, setSearchResults,
    searchLoading, setSearchLoading, searchError, setSearchError, loweredQuery,
  };
}

// Directories first, then by path, per parent folder.
function groupByParent(displayedFiles: WorkspaceFileEntry[]) {
  const mapping = new Map<string, WorkspaceFileEntry[]>();
  for (const file of displayedFiles) {
    const parentPath = file.parentPath || relativeParent(file.relativePath);
    const bucket = mapping.get(parentPath) ?? [];
    bucket.push(file);
    mapping.set(parentPath, bucket);
  }
  for (const entries of mapping.values()) {
    entries.sort((left, right) => {
      const leftOrder = left.kind === "directory" ? 0 : 1;
      const rightOrder = right.kind === "directory" ? 0 : 1;
      if (leftOrder !== rightOrder) {
        return leftOrder - rightOrder;
      }
      return left.relativePath.localeCompare(right.relativePath);
    });
  }
  return mapping;
}

export function useWorkspaceSidePanelLists(
  workspace: SelectedWorkspace | null | undefined,
  loweredQuery: string,
  searchResults: WorkspaceFileEntry[],
  selectedPaths: string[],
) {
  const displayedFiles = useMemo(() => {
    if (loweredQuery) {
      return searchResults;
    }
    return workspace?.files ?? [];
  }, [loweredQuery, searchResults, workspace?.files]);

  const filteredChanges = useMemo(() => {
    const changes = workspace?.changes ?? [];
    if (!loweredQuery) {
      return changes;
    }
    return changes.filter((change) =>
      [change.summary, change.toolName || "", change.requestFingerprint || ""]
        .join(" ")
        .toLowerCase()
        .includes(loweredQuery),
    );
  }, [workspace?.changes, loweredQuery]);

  const childrenByParent = useMemo(() => groupByParent(displayedFiles), [displayedFiles]);

  const loadedDirectories = useMemo(
    () => new Set(workspace?.loadedDirectories ?? [""]),
    [workspace?.loadedDirectories],
  );

  const selectedEntries = useMemo(() => {
    const byRelativePath = new Map(
      (workspace?.files ?? []).map((file) => [file.relativePath, file]),
    );
    return selectedPaths
      .map((path) => byRelativePath.get(path))
      .filter((entry): entry is WorkspaceFileEntry => Boolean(entry));
  }, [selectedPaths, workspace?.files]);

  return { displayedFiles, filteredChanges, childrenByParent, loadedDirectories, selectedEntries };
}
