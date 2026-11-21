// Restore card of Backup & restore: backup file and its preview, target Workspace, sections and skills options.
import {
  humanizeSectionKey,
  type RESTORE_SECTION_OPTIONS,
  type RestoreSectionId,
  type summarizeBackupFile,
} from "./backupRestoreModel";
import type { DataTransferJob, ProjectOption } from "./backupRestoreJobTypes";
import { WorkspaceSelect } from "./BackupWorkspaceSelect";

type RestoreBackupCardProps = {
  projects: ProjectOption[];
  preview: ReturnType<typeof summarizeBackupFile> | null;
  restoreFileName: string;
  handleRestoreFile: (file: File | null) => Promise<void>;
  restoreProjectId: string;
  setRestoreProjectId: (value: string) => void;
  workspaceSections: (typeof RESTORE_SECTION_OPTIONS)[number][];
  restoreSections: RestoreSectionId[];
  toggleRestoreSection: (sectionId: RestoreSectionId, checked: boolean) => void;
  overwriteExisting: boolean;
  setOverwriteExisting: (value: boolean) => void;
  restoringSkills: boolean;
  overwriteSkills: boolean;
  setOverwriteSkills: (value: boolean) => void;
  busy: boolean;
  restorePayload: Record<string, unknown> | null;
  restoreBackup: () => Promise<void>;
  importJob: DataTransferJob | null;
};

export function RestoreBackupCard(props: RestoreBackupCardProps) {
  const { projects, preview, restoreFileName, handleRestoreFile, restoreProjectId, setRestoreProjectId } = props;
  const { overwriteExisting, setOverwriteExisting, busy, restorePayload, restoreSections, restoreBackup, importJob } = props;
  return (
    <section className="backup-restore__card" aria-label="Restore backup">
      <h3>Restore backup</h3>
      <label className="backup-restore__field">
        <span>
          Backup file <span className="backup-restore__required" aria-hidden="true">*</span>
        </span>
        <input
          type="file"
          accept="application/json,.json"
          onChange={(event) => void handleRestoreFile(event.target.files?.[0] ?? null)}
        />
      </label>
      {preview ? <BackupPreview preview={preview} restoreFileName={restoreFileName} /> : null}
      <WorkspaceSelect
        label="Target workspace"
        value={restoreProjectId}
        projects={projects}
        onChange={setRestoreProjectId}
      />
      <RestoreSectionChecks {...props} />
      <label className="backup-restore__check">
        <input
          type="checkbox"
          checked={overwriteExisting}
          onChange={(event) => setOverwriteExisting(event.target.checked)}
        />
        <span>Overwrite matching existing actions and agents</span>
      </label>
      <SkillChoices {...props} />
      <div className="backup-restore__actions">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void restoreBackup()}
          disabled={busy || !restoreProjectId || !restorePayload || restoreSections.length === 0}
        >
          Restore backup
        </button>
      </div>
      {importJob ? (
        <div className="admin-panel__note">
          Restore is {importJob.status}. Rows: {importJob.rows_success ?? 0}/{importJob.rows_total ?? 0}
          {importJob.rows_failed ? `, failed: ${importJob.rows_failed}` : ""}.
        </div>
      ) : null}
    </section>
  );
}

function BackupPreview({
  preview,
  restoreFileName,
}: {
  preview: NonNullable<RestoreBackupCardProps["preview"]>;
  restoreFileName: string;
}) {
  return (
    <div className="backup-restore__preview" aria-label="Backup file preview">
      <p>
        <strong>{restoreFileName}</strong> · workspace <strong>{preview.workspaceName}</strong> ·
        format {preview.formatVersion}
      </p>
      <ul>
        {preview.sections.map((section) => (
          <li key={section.id}>
            {section.label}:{" "}
            {section.included
              ? section.count == null
                ? "included"
                : `${section.count} item${section.count === 1 ? "" : "s"}`
              : "not in this backup"}
          </li>
        ))}
      </ul>
      {preview.excludedSections.length ? (
        <p className="admin-panel__hint">
          Never included: {preview.excludedSections.map(humanizeSectionKey).join(", ")}.
        </p>
      ) : null}
    </div>
  );
}

function RestoreSectionChecks({
  workspaceSections,
  restoreSections,
  toggleRestoreSection,
}: Pick<RestoreBackupCardProps, "workspaceSections" | "restoreSections" | "toggleRestoreSection">) {
  return (
    <fieldset className="backup-restore__checks">
      <legend>Restore into this Workspace</legend>
      {workspaceSections.map((section) => (
        <label key={section.id} className="backup-restore__check">
          <input
            type="checkbox"
            checked={restoreSections.includes(section.id)}
            onChange={(event) => toggleRestoreSection(section.id, event.target.checked)}
          />
          <span>{section.label}</span>
        </label>
      ))}
      <p className="admin-panel__hint">
        Workspace configuration replaces the target Workspace&apos;s
        configuration and description; whether it is active stays as it is.
      </p>
    </fieldset>
  );
}

function SkillChoices({
  restoringSkills,
  overwriteSkills,
  toggleRestoreSection,
  setOverwriteSkills,
}: Pick<RestoreBackupCardProps, "restoringSkills" | "overwriteSkills" | "toggleRestoreSection" | "setOverwriteSkills">) {
  return (
    <fieldset className="backup-restore__checks" data-testid="backup-skills">
      <legend>Platform-wide skills</legend>
      <p className="sk-warn">
        Skills belong to every Workspace. Restoring them adds the missing ones as catalog drafts; existing skills
        are kept unless you choose to replace them, and a published skill changes only through the skill catalog.
      </p>
      <label className="backup-restore__check">
        <input
          type="checkbox"
          checked={restoringSkills}
          data-testid="backup-restore-skills"
          onChange={(event) => toggleRestoreSection("skills", event.target.checked)}
        />
        <span>Restore skills from this backup</span>
      </label>
      <label className="backup-restore__check">
        <input
          type="checkbox"
          checked={restoringSkills && overwriteSkills}
          disabled={!restoringSkills}
          data-testid="backup-overwrite-skills"
          onChange={(event) => setOverwriteSkills(event.target.checked)}
        />
        <span>Replace existing draft skills with the backup&apos;s version (changes them for every Workspace)</span>
      </label>
    </fieldset>
  );
}
