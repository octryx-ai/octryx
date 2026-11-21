import { useEffect, useMemo, useState } from "react";

import type { WorkspaceFileEntry } from "../chatWorkspaceTypes";

type UseWorkspacePreviewTabsArgs = {
  workspaceRootPath?: string;
  files: WorkspaceFileEntry[];
};

type UseWorkspacePreviewTabsResult = {
  activePreviewEntry: WorkspaceFileEntry | null;
  activePreviewPath: string;
  openPreviewEntries: WorkspaceFileEntry[];
  openPreviewFile: (entry: WorkspaceFileEntry) => void;
  selectPreviewPath: (relativePath: string) => void;
  closePreviewPath: (relativePath: string) => void;
  closeActivePreview: () => void;
};

function isPreviewableFile(
  entry: WorkspaceFileEntry | undefined,
): entry is WorkspaceFileEntry {
  return Boolean(entry && entry.kind !== "directory" && entry.url);
}

export function useWorkspacePreviewTabs({
  workspaceRootPath,
  files,
}: UseWorkspacePreviewTabsArgs): UseWorkspacePreviewTabsResult {
  const [openPreviewPaths, setOpenPreviewPaths] = useState<string[]>([]);
  const [activePreviewPath, setActivePreviewPath] = useState("");

  const filesByRelativePath = useMemo(
    () => new Map(files.map((entry) => [entry.relativePath, entry])),
    [files],
  );

  useEffect(() => {
    setOpenPreviewPaths([]);
    setActivePreviewPath("");
  }, [workspaceRootPath]);

  useEffect(() => {
    setOpenPreviewPaths((current) =>
      current.filter((relativePath) =>
        isPreviewableFile(filesByRelativePath.get(relativePath)),
      ),
    );
    setActivePreviewPath((current) =>
      isPreviewableFile(filesByRelativePath.get(current)) ? current : "",
    );
  }, [filesByRelativePath]);

  useEffect(() => {
    if (activePreviewPath) {
      return;
    }
    setOpenPreviewPaths((current) => {
      if (!current.length) {
        return current;
      }
      const nextActivePath = current[current.length - 1] ?? "";
      if (nextActivePath) {
        setActivePreviewPath(nextActivePath);
      }
      return current;
    });
  }, [activePreviewPath]);

  const openPreviewEntries = useMemo(
    () =>
      openPreviewPaths
        .map((relativePath) => filesByRelativePath.get(relativePath))
        .filter(isPreviewableFile),
    [filesByRelativePath, openPreviewPaths],
  );

  const activePreviewEntry = useMemo(
    () => filesByRelativePath.get(activePreviewPath) ?? null,
    [activePreviewPath, filesByRelativePath],
  );

  const openPreviewFile = (entry: WorkspaceFileEntry) => {
    if (!isPreviewableFile(entry)) {
      return;
    }
    setOpenPreviewPaths((current) =>
      current.includes(entry.relativePath)
        ? current
        : [...current, entry.relativePath],
    );
    setActivePreviewPath(entry.relativePath);
  };

  const selectPreviewPath = (relativePath: string) => {
    if (!isPreviewableFile(filesByRelativePath.get(relativePath))) {
      return;
    }
    setActivePreviewPath(relativePath);
  };

  const closePreviewPath = (relativePath: string) => {
    setOpenPreviewPaths((current) => {
      const next = current.filter((path) => path !== relativePath);
      setActivePreviewPath((currentActivePath) => {
        if (currentActivePath !== relativePath) {
          return currentActivePath;
        }
        const closingIndex = current.indexOf(relativePath);
        return (
          next[Math.min(closingIndex, next.length - 1)] ??
          next[next.length - 1] ??
          ""
        );
      });
      return next;
    });
  };

  const closeActivePreview = () => {
    if (!activePreviewPath) {
      return;
    }
    closePreviewPath(activePreviewPath);
  };

  return {
    activePreviewEntry,
    activePreviewPath,
    openPreviewEntries,
    openPreviewFile,
    selectPreviewPath,
    closePreviewPath,
    closeActivePreview,
  };
}
