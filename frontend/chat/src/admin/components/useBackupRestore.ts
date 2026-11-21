// The backup and restore page's state: the chosen Workspaces, the backup file and its preview, the sections to
// restore, the export and import jobs and the history; with the backup, file and restore actions.
import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";

import type { ReadJsonFn } from "../hooks/useAdminTabLoader.types";
import {
  RESTORE_SECTION_OPTIONS, backupRestoreFormDefaults, parseBackupFile, readHistory, summarizeBackupFile,
  type HistoryEntry, type RestoreSectionId,
} from "./backupRestoreModel";
import { DATA, type DataTransferJob, type ProjectOption } from "./backupRestoreJobTypes";

type Setter<T> = Dispatch<SetStateAction<T>>;
type JobSteps = {
  readJson: ReadJsonFn; setBusy: Setter<boolean>; setError: Setter<string | null>; loadHistory: () => Promise<void>;
};

async function startBackup(steps: JobSteps, backupProjectId: string, setExportJob: Setter<DataTransferJob | null>) {
  const { readJson, setBusy, setError, loadHistory } = steps;
  if (!backupProjectId) {
    setError("Select a workspace to back up.");
    return;
  }
  setBusy(true);
  setError(null);
  try {
    const job = await readJson<DataTransferJob>(`${DATA}/exports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        export_type: "admin_config_backup",
        scope_type: "project",
        scope_id: backupProjectId,
        format: "json",
        include_sensitive: false,
      }),
    });
    setExportJob(job);
    void loadHistory();
  } catch (err) {
    setError(err instanceof Error ? err.message : "Backup failed");
  } finally {
    setBusy(false);
  }
}

type RestoreRequest = {
  restoreProjectId: string; restorePayload: Record<string, unknown> | null; overwriteExisting: boolean;
  overwriteSkills: boolean; restoringSkills: boolean; restoreSections: RestoreSectionId[];
};

async function startRestore(steps: JobSteps, request: RestoreRequest, setImportJob: Setter<DataTransferJob | null>) {
  const { readJson, setBusy, setError, loadHistory } = steps;
  const { restoreProjectId, restorePayload, overwriteExisting, overwriteSkills, restoringSkills, restoreSections } = request;
  if (!restoreProjectId) {
    setError("Select a target workspace.");
    return;
  }
  if (!restorePayload) {
    setError("Select an admin configuration backup file.");
    return;
  }
  setBusy(true);
  setError(null);
  try {
    const job = await readJson<DataTransferJob>(`${DATA}/imports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        import_type: "admin_config_backup",
        source_format: "json",
        payload_json: restorePayload,
        target_project_id: restoreProjectId,
        overwrite_existing: overwriteExisting,
        overwrite_skills: restoringSkills && overwriteSkills,
        restore_sections: restoreSections,
      }),
    });
    setImportJob(job);
    void loadHistory();
  } catch (err) {
    setError(err instanceof Error ? err.message : "Restore failed");
  } finally {
    setBusy(false);
  }
}

export function useBackupRestore(projects: ProjectOption[], readJson: ReadJsonFn) {
  const defaults = backupRestoreFormDefaults();
  const [backupProjectId, setBackupProjectId] = useState(defaults.backupProjectId);
  const [restoreProjectId, setRestoreProjectId] = useState(defaults.restoreProjectId);
  const [restorePayload, setRestorePayload] = useState<Record<string, unknown> | null>(null);
  const [restoreFileName, setRestoreFileName] = useState("");
  const [overwriteExisting, setOverwriteExisting] = useState(defaults.overwriteExisting);
  const [overwriteSkills, setOverwriteSkills] = useState(defaults.overwriteSkills);
  const [history, setHistory] = useState<HistoryEntry[] | null>(null);
  const [restoreSections, setRestoreSections] = useState<RestoreSectionId[]>(defaults.restoreSections);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportJob, setExportJob] = useState<DataTransferJob | null>(null);
  const [importJob, setImportJob] = useState<DataTransferJob | null>(null);

  const selectedBackupProjectName = useMemo(
    () => projects.find((project) => project.id === backupProjectId)?.name ?? "selected workspace",
    [backupProjectId, projects],
  );
  const preview = useMemo(
    () => (restorePayload ? summarizeBackupFile(restorePayload) : null),
    [restorePayload],
  );
  const loadHistory = useCallback(async () => {
    try {
      setHistory(readHistory(await readJson<unknown>(`${DATA}/backups/history`)));
    } catch {
      setHistory([]);
    }
  }, [readJson]);
  useEffect(() => { void loadHistory(); }, [loadHistory]);
  const workspaceSections = RESTORE_SECTION_OPTIONS.filter((section) => section.id !== "skills");
  const restoringSkills = restoreSections.includes("skills");
  const steps = { readJson, setBusy, setError, loadHistory };

  const createBackup = () => startBackup(steps, backupProjectId, setExportJob);
  const restoreBackup = () => startRestore(steps, {
    restoreProjectId, restorePayload, overwriteExisting, overwriteSkills, restoringSkills, restoreSections,
  }, setImportJob);
  return {
    backupProjectId, setBackupProjectId, restoreProjectId, setRestoreProjectId, restorePayload, setRestorePayload,
    restoreFileName, setRestoreFileName, overwriteExisting, setOverwriteExisting, overwriteSkills, setOverwriteSkills,
    history, restoreSections, setRestoreSections, busy, error, setError, exportJob, importJob, setImportJob,
    selectedBackupProjectName, preview, workspaceSections, restoringSkills, createBackup, restoreBackup,
  };
}
