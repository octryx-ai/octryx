import { useId } from "react";
import "./workspace-scope.css";

type WorkspaceOption = { id: string; name: string };

// Compact, labelled workspace selector for area pages that act on one
// workspace. It never preselects a workspace on its own; the shared active
// workspace (chat/useActiveWorkspace) supplies the value.
// variant "header": the one Workspace switch of a page, always at the same place in the page header,
// first of the header controls; "row" stays for forms that pick a Workspace as a field.
export function WorkspaceScopeSelect({ projects, value, onChange, hint, variant = "row" }: {
  projects: WorkspaceOption[];
  value: string;
  onChange: (workspaceId: string) => void;
  hint?: string;
  variant?: "row" | "header";
}) {
  const id = useId();
  return (
    <div className={`workspace-scope workspace-scope--${variant}`} data-testid={variant === "header" ? "workspace-switch" : undefined}>
      <label htmlFor={id} className="workspace-scope__label">Workspace</label>
      <select id={id} className="workspace-scope__select" value={value}
        onChange={(event) => onChange(event.target.value)}>
        <option value="">Select a workspace</option>
        {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select>
      {hint ? <span className="workspace-scope__hint">{hint}</span> : null}
    </div>
  );
}
