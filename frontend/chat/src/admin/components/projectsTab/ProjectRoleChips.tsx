import {
  PROJECT_ROLE_HINTS,
  PROJECT_ROLE_OPTIONS,
  toggleProjectRole,
} from "./projectAccessDrafts";

// Workspace roles as checkbox chips instead of a native multi-select.
type ProjectRoleChipsProps = {
  label: string;
  value: string[];
  disabled?: boolean;
  onChange: (roles: string[]) => void;
};

export function ProjectRoleChips({ label, value, disabled, onChange }: ProjectRoleChipsProps) {
  return (
    <fieldset className="project-role-chips" disabled={disabled} aria-label={label}>
      {PROJECT_ROLE_OPTIONS.map((role) => (
        <label key={role} className="admin-users__role-chip" title={PROJECT_ROLE_HINTS[role]}>
          <input
            type="checkbox"
            checked={value.includes(role)}
            onChange={(event) => onChange(toggleProjectRole(value, role, event.target.checked))}
          />
          <span>{role}</span>
        </label>
      ))}
    </fieldset>
  );
}
