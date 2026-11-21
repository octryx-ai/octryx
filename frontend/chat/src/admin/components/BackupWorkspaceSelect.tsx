// Required Workspace picker of the backup and restore cards.
import type { ProjectOption } from "./backupRestoreJobTypes";

export function WorkspaceSelect({
  label,
  value,
  projects,
  onChange,
}: {
  label: string;
  value: string;
  projects: ProjectOption[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="backup-restore__field">
      <span>
        {label} <span className="backup-restore__required" aria-hidden="true">*</span>
      </span>
      <select value={value} onChange={(event) => onChange(event.target.value)} required>
        <option value="">Select workspace</option>
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </label>
  );
}
