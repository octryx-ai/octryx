import type { ReadJsonFn } from "../hooks/useAdminTabLoader.types";
import { parseBackupFile, type RestoreSectionId } from "./backupRestoreModel";
import { BackupHistoryTable } from "./BackupHistoryTable";
import { DATA, type ProjectOption } from "./backupRestoreJobTypes";
import { WorkspaceSelect } from "./BackupWorkspaceSelect";
import { RestoreBackupCard } from "./RestoreBackupCard";
import { useBackupRestore } from "./useBackupRestore";
import "./settingsKit/settingsKit.css";

import "./backupRestore.css";

type AdminBackupRestoreTabProps = {
  projects: ProjectOption[];
  readJson: ReadJsonFn;
};

type Page = ReturnType<typeof useBackupRestore>;

function formatBytes(value?: number | null) {
  if (!value) return "0 KB";
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

// Settings → Organization → Backup & restore: back up and restore one Workspace, the history of
// backups and restores with who and when, and the platform-wide skills restored only on request.
export function AdminBackupRestoreTab({
  projects,
  readJson,
}: AdminBackupRestoreTabProps) {
  const page = useBackupRestore(projects, readJson);
  const { error } = page;

  return (
    <div className="backup-restore">
      <div className="admin-panel__section-header">
        <span>Backup &amp; restore</span>
      </div>

      {error ? <div className="admin-panel__error">{error}</div> : null}

      <div className="backup-restore__grid">
        <CreateBackupCard page={page} projects={projects} />
        <RestoreCard page={page} projects={projects} />
      </div>

      <BackupHistoryTable history={page.history} />
    </div>
  );
}

function CreateBackupCard({ page, projects }: { page: Page; projects: ProjectOption[] }) {
  const { backupProjectId, setBackupProjectId, createBackup, busy, exportJob, selectedBackupProjectName } = page;
  return (
    <section className="backup-restore__card" aria-label="Create backup">
      <h3>Create backup</h3>
      <WorkspaceSelect
        label="Workspace"
        value={backupProjectId}
        projects={projects}
        onChange={setBackupProjectId}
      />
      <div className="backup-restore__actions">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void createBackup()}
          disabled={busy || !backupProjectId}
        >
          Create backup
        </button>
      </div>
      {exportJob ? (
        <div className="admin-panel__note">
          <strong>{selectedBackupProjectName}</strong> backup is {exportJob.status}.
          {exportJob.file_size_bytes ? ` Size: ${formatBytes(exportJob.file_size_bytes)}.` : ""}
          {exportJob.status === "completed" ? (
            <>
              {" "}
              <a href={`${DATA}/exports/${encodeURIComponent(exportJob.id)}/download`}>
                Download JSON
              </a>
            </>
          ) : null}
        </div>
      ) : null}
    </section>

  );
}

function RestoreCard({ page, projects }: { page: Page; projects: ProjectOption[] }) {
  const {
    preview, restoreFileName, restoreProjectId, setRestoreProjectId, workspaceSections, restoreSections, setRestoreSections,
    overwriteExisting, setOverwriteExisting, restoringSkills, overwriteSkills, setOverwriteSkills, busy, restorePayload,
    restoreBackup, importJob, setImportJob, setRestorePayload, setRestoreFileName, setError,
  } = page;

  const handleRestoreFile = async (file: File | null) => {
    setImportJob(null);
    setRestorePayload(null);
    setRestoreFileName("");
    if (!file) return;
    try {
      setRestorePayload(parseBackupFile(await file.text()));
      setRestoreFileName(file.name);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read backup file");
    }
  };

  const toggleRestoreSection = (sectionId: RestoreSectionId, checked: boolean) => {
    setRestoreSections((current) =>
      checked ? Array.from(new Set([...current, sectionId])) : current.filter((item) => item !== sectionId),
    );
  };

  return (
    <RestoreBackupCard
      projects={projects}
      preview={preview}
      restoreFileName={restoreFileName}
      handleRestoreFile={handleRestoreFile}
      restoreProjectId={restoreProjectId}
      setRestoreProjectId={setRestoreProjectId}
      workspaceSections={workspaceSections}
      restoreSections={restoreSections}
      toggleRestoreSection={toggleRestoreSection}
      overwriteExisting={overwriteExisting}
      setOverwriteExisting={setOverwriteExisting}
      restoringSkills={restoringSkills}
      overwriteSkills={overwriteSkills}
      setOverwriteSkills={setOverwriteSkills}
      busy={busy}
      restorePayload={restorePayload}
      restoreBackup={restoreBackup}
      importJob={importJob}
    />
  );
}
