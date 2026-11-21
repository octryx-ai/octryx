import { useEffect, useId, useRef, useState } from "react";
import { useActiveWorkspace } from "../useActiveWorkspace";
import { GLOBAL_WORKSPACE_LABEL, workspaceInitials, workspaceSwitchLabel } from "./globalWorkspaceModel";
import { publishActiveWorkspaceName } from "./activeWorkspaceName";

type WorkspaceOption = { id: string; name: string; isDefault?: boolean; is_default?: boolean };

// The one Workspace switch of the app: at the head of the rail (and in the compact menu on
// narrow screens). Every area reads the same active Workspace (useActiveWorkspace); pages do not carry their own
// switch. `workspace_id` in the address stays the deep-link carrier and moves this switch along.
// `allowGlobal` (administrators): "Global · no workspace" is a choice here too, since the composer
// carries no Workspace select of its own.
export function GlobalWorkspaceSwitch({ projects, fallbackWorkspaceId, variant = "rail", allowGlobal = false }: {
  projects: WorkspaceOption[];
  fallbackWorkspaceId?: string | null;
  variant?: "rail" | "compact";
  allowGlobal?: boolean;
}) {
  const [workspaceId, setWorkspaceId] = useActiveWorkspace(projects, fallbackWorkspaceId);
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const current = projects.find((project) => project.id === workspaceId) ?? null;
  const label = workspaceSwitchLabel(current?.name ?? null);
  // Every area's sidebar head writes the name out ("Work · Test").
  useEffect(() => { publishActiveWorkspaceName(current?.name ?? ""); }, [current?.name]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    const onPointer = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onPointer);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onPointer);
    };
  }, [open]);

  if (!projects.length) return null;
  return (
    <div ref={rootRef} className={`global-workspace global-workspace--${variant}`} data-testid="global-workspace-switch">
      <button type="button" className="global-workspace__button" aria-haspopup="menu" aria-expanded={open}
        aria-controls={menuId} aria-label={label} title={label} data-tooltip={label} onClick={() => setOpen((value) => !value)}>
        <span className="global-workspace__initials" aria-hidden="true">{workspaceInitials(current?.name ?? null)}</span>
        {variant === "compact" ? <span className="global-workspace__name">{current?.name ?? "No workspace"}</span>
          : <span className="global-workspace__caption" aria-hidden="true">Workspace</span>}
      </button>
      {open ? (
        <div id={menuId} role="menu" aria-label="Choose a workspace" className="global-workspace__menu">
          <div className="global-workspace__heading">Workspace</div>
          {projects.map((project) => (
            <button key={project.id} type="button" role="menuitemradio" aria-checked={project.id === workspaceId}
              className={`global-workspace__item${project.id === workspaceId ? " is-current" : ""}`}
              data-testid={`global-workspace-item-${project.id}`}
              onClick={() => { setWorkspaceId(project.id); setOpen(false); }}>
              <span className="global-workspace__item-initials" aria-hidden="true">{workspaceInitials(project.name)}</span>
              <span>{project.name}</span>
            </button>
          ))}
          {allowGlobal ? (
            <button type="button" role="menuitemradio" aria-checked={!workspaceId}
              className={`global-workspace__item global-workspace__item--global${!workspaceId ? " is-current" : ""}`}
              data-testid="global-workspace-item-global"
              onClick={() => { setWorkspaceId(""); setOpen(false); }}>
              <span className="global-workspace__item-initials" aria-hidden="true">–</span>
              <span>{GLOBAL_WORKSPACE_LABEL}</span>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
