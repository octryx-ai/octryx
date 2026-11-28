import { useId } from "react";
import "./workspace-scope.css";

type WorkspaceOption = { id: string; name: string };

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
