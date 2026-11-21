// The workspace file search: runs the server search for the Files tab query and tracks results, loading and error.
import { useEffect, type Dispatch, type SetStateAction } from "react";

import type { WorkspaceFileEntry } from "../chatWorkspaceTypes";

export function useWorkspaceFileSearch({
  activeTab,
  loweredQuery,
  onSearchFiles,
  setSearchResults,
  setSearchLoading,
  setSearchError,
}: {
  activeTab: "files" | "changes";
  loweredQuery: string;
  onSearchFiles?: (query: string) => Promise<WorkspaceFileEntry[]>;
  setSearchResults: Dispatch<SetStateAction<WorkspaceFileEntry[]>>;
  setSearchLoading: Dispatch<SetStateAction<boolean>>;
  setSearchError: Dispatch<SetStateAction<string | null>>;
}) {
  useEffect(() => {
    if (activeTab !== "files" || !loweredQuery) {
      setSearchResults([]);
      setSearchLoading(false);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    setSearchLoading(true);
    setSearchError(null);
    void onSearchFiles?.(loweredQuery)
      .then((results) => {
        if (!cancelled) {
          setSearchResults(results);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSearchError(
            error instanceof Error ? error.message : "Search failed",
          );
          setSearchResults([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setSearchLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, loweredQuery, onSearchFiles, setSearchError, setSearchLoading, setSearchResults]);
}
