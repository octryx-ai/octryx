import { useCallback, useEffect, useState } from "react";
import {
  addRepositoryFromSource, loadRepositorySources, loadWorkspaceRepositories,
  type RepositorySource, type WorkspaceRepository,
} from "../../../admin/components/projectsTab/repositories/workspaceRepositoriesApi";

// The Workspace's repository records and (for authors) its Knowledge git sources, and setting a source up as a record.
export function useWorkspaceRepositoryList(workspace: string, mayAuthor: boolean) {
  const [records, setRecords] = useState<WorkspaceRepository[]>([]);
  // The first record read is in (or failed): before it, "no repository" would be a guess.
  const [recordsListed, setRecordsListed] = useState(false);
  const [sources, setSources] = useState<RepositorySource[]>([]);
  // The source read is in (or failed); with no record yet, every row is a source.
  const [sourcesListed, setSourcesListed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refreshRecords = useCallback(async (signal?: AbortSignal) => {
    const items = await loadWorkspaceRepositories(workspace);
    if (!signal?.aborted) setRecords(Array.isArray(items) ? items : []);
  }, [workspace]);
  useEffect(() => {
    const abort = new AbortController();
    void refreshRecords(abort.signal)
      .catch((failure: Error) => { if (!abort.signal.aborted) setError(failure.message); })
      .finally(() => { if (!abort.signal.aborted) setRecordsListed(true); });
    return () => abort.abort();
  }, [refreshRecords]);
  useEffect(() => {
    if (!mayAuthor) return;
    const abort = new AbortController();
    void loadRepositorySources(workspace)
      .then((items) => { if (!abort.signal.aborted) setSources(items); })
      .catch(() => { /* Source selection is optional; the records keep their own errors. */ })
      .finally(() => { if (!abort.signal.aborted) setSourcesListed(true); });
    return () => abort.abort();
  }, [workspace, mayAuthor]);

  const bind = useCallback(async (connectorId: string) => {
    setBusy(true); setError("");
    try {
      await addRepositoryFromSource(workspace, connectorId);
      await refreshRecords();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "The repository could not be set up."); }
    finally { setBusy(false); }
  }, [workspace, refreshRecords]);

  return { records, recordsListed, sources, sourcesListed, busy, error, bind, refreshRecords };
}
