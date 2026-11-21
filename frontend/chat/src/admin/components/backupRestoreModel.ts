// Backup & restore form defaults, client-side backup file preview and the history.
// Nothing destructive is preselected: no target workspace, no overwrite, and nothing platform-wide — skills belong to
// every Workspace, so restoring them is opted into separately and existing skills are only replaced on request
// (the backend defaults for overwrite_existing and overwrite_skills are false as well).
export const RESTORE_SECTION_OPTIONS = [
  { id: "project_config", label: "Workspace configuration", payloadKey: "project" },
  { id: "tasks", label: "Actions", payloadKey: "tasks" },
  { id: "agents", label: "Agents", payloadKey: "agents" },
  { id: "skills", label: "Skills (platform-wide)", payloadKey: "skills" },
] as const;

export type RestoreSectionId = (typeof RESTORE_SECTION_OPTIONS)[number]["id"];

export type BackupRestoreFormDefaults = {
  backupProjectId: string;
  restoreProjectId: string;
  overwriteExisting: boolean;
  overwriteSkills: boolean;
  restoreSections: RestoreSectionId[];
};

export function backupRestoreFormDefaults(): BackupRestoreFormDefaults {
  return {
    backupProjectId: "",
    restoreProjectId: "",
    overwriteExisting: false,
    overwriteSkills: false,
    restoreSections: RESTORE_SECTION_OPTIONS.filter((section) => section.id !== "skills").map((section) => section.id),
  };
}

export type BackupFilePreview = {
  workspaceName: string;
  formatVersion: string;
  sections: Array<{
    id: RestoreSectionId;
    label: string;
    included: boolean;
    count: number | null;
  }>;
  excludedSections: string[];
  secretPolicy: string;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

export class BackupFileError extends Error {}

export function parseBackupFile(text: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new BackupFileError("The selected file is not valid JSON.");
  }
  const record = asRecord(parsed);
  if (record.export_type !== "admin_config_backup") {
    throw new BackupFileError("The selected file is not an admin configuration backup.");
  }
  return record;
}

export function summarizeBackupFile(payload: Record<string, unknown>): BackupFilePreview {
  const manifest = asRecord(payload.manifest);
  const included = stringList(manifest.included_sections);
  const project = asRecord(payload.project);
  return {
    workspaceName: String(project.name || "").trim() || "Unnamed workspace",
    formatVersion: manifest.format_version != null ? String(manifest.format_version) : "unknown",
    sections: RESTORE_SECTION_OPTIONS.map((section) => {
      const value = payload[section.payloadKey];
      // Lists show their entry count; the workspace configuration is a single object.
      const count = Array.isArray(value) ? value.length : null;
      return {
        id: section.id,
        label: section.label,
        included: included.length ? included.includes(section.id) : value != null,
        count,
      };
    }),
    excludedSections: stringList(manifest.excluded_sections),
    secretPolicy: String(manifest.secret_policy || ""),
  };
}

export function humanizeSectionKey(key: string): string {
  return key.replace(/_/g, " ");
}

export type HistoryEntry = {
  kind: "backup" | "restore";
  id: string;
  at: string | null;
  by: string;
  workspace: string;
  status: string;
  downloadable: boolean;
  result: string;
};

const names = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);

// One line per backup or restore: what it held or what it changed, with the platform-wide skills named.
export function historyResult(kind: string, status: string, summary: Record<string, unknown>, error: string | null): string {
  if (status === "failed") return error ? `Failed: ${error}` : "Failed";
  const count = (key: string) => Number(summary[key] ?? 0);
  if (kind === "backup") {
    return `${count("task_count")} actions, ${count("agent_count")} agents, ${count("skill_count")} skills`;
  }
  const parts = [summary.project_config_updated ? "configuration restored" : "configuration unchanged"];
  parts.push(`${count("task_count")} actions`, `${count("agent_count")} agents`);
  const created = names(summary.skills_created);
  const kept = names(summary.skills_kept);
  const overwritten = names(summary.skills_overwritten);
  if (created.length) parts.push(`skills added: ${created.join(", ")}`);
  if (kept.length) parts.push(`existing skills kept: ${kept.join(", ")}`);
  if (overwritten.length) parts.push(`skills overwritten: ${overwritten.join(", ")}`);
  return parts.join(" · ") + (status === "completed_with_warnings" ? " (with warnings)" : "");
}

export function readHistory(payload: unknown): HistoryEntry[] {
  if (!Array.isArray(payload)) return [];
  return payload.map(asRecord).filter((row) => typeof row.id === "string").map((row) => ({
    kind: row.kind === "restore" ? "restore" : "backup",
    id: String(row.id),
    at: typeof row.at === "string" ? row.at : null,
    by: String(row.by ?? ""),
    workspace: String(row.workspace ?? ""),
    status: String(row.status ?? ""),
    downloadable: row.downloadable === true,
    result: historyResult(String(row.kind), String(row.status ?? ""), asRecord(row.summary), typeof row.error === "string" ? row.error : null),
  }));
}
