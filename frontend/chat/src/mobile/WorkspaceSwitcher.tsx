// The phone's Workspace switch: a chip under each tab's title opens a sheet with every Workspace the person can
// access and "All workspaces". The choice filters chats, runs, Work items and what needs the person.

import { useState } from "react";
import { workspaceInitials } from "../chat/workspace/globalWorkspaceModel";
import { Icon } from "./icons";
import { BottomSheet } from "./BottomSheet";
import { ALL_WORKSPACES, ALL_WORKSPACES_LABEL, workspaceName, type WorkspaceRef } from "./mobileWorkspace";

export function WorkspaceSwitcher({
  workspace,
  workspaces,
  onChange,
}: {
  workspace: string;
  workspaces: WorkspaceRef[];
  onChange: (workspaceId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!workspaces.length) return null;
  const name = workspaceName(workspace, workspaces);
  const choose = (id: string) => {
    onChange(id);
    setOpen(false);
  };
  return (
    <>
      <button
        type="button"
        className="m-ws-chip"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Workspace: ${name}. Change`}
        data-testid="m-workspace-chip"
        onClick={() => setOpen(true)}
      >
        <span className={`m-ws-initials${workspace ? "" : " m-ws-initials-all"}`} aria-hidden="true">
          {workspace ? workspaceInitials(name) : <Icon name="stack" size={14} />}
        </span>
        <span className="m-ws-name">{name}</span>
        <Icon name="chevronDown" size={16} />
      </button>
      {open && (
        <BottomSheet title="Workspace" onClose={() => setOpen(false)}>
          <p className="m-sheet-hint">Shows the chats, runs and Work items of one Workspace, or of all of yours.</p>
          <ul className="m-choice-list" role="listbox" aria-label="Workspaces">
            <WorkspaceOption
              label={ALL_WORKSPACES_LABEL}
              detail={`${workspaces.length} ${workspaces.length === 1 ? "workspace" : "workspaces"}`}
              selected={workspace === ALL_WORKSPACES}
              onChoose={() => choose(ALL_WORKSPACES)}
            />
            {workspaces.map((item) => (
              <WorkspaceOption
                key={item.id}
                label={item.name}
                initials={workspaceInitials(item.name)}
                detail={item.private ? "Private · only you" : item.isDefault ? "Default" : ""}
                selected={workspace === item.id}
                onChoose={() => choose(item.id)}
              />
            ))}
          </ul>
        </BottomSheet>
      )}
    </>
  );
}

function WorkspaceOption({
  label,
  initials,
  detail,
  selected,
  onChoose,
}: {
  label: string;
  initials?: string;
  detail: string;
  selected: boolean;
  onChoose: () => void;
}) {
  return (
    <li>
      <button type="button" role="option" aria-selected={selected} className="m-choice" onClick={onChoose}>
        <span className={`m-ws-initials m-ws-initials-lg${initials ? "" : " m-ws-initials-all"}`} aria-hidden="true">
          {initials ?? <Icon name="stack" size={18} />}
        </span>
        <span className="m-choice-text">
          <b>{label}</b>
          {detail && <span>{detail}</span>}
        </span>
        {selected && <Icon name="check" size={20} className="m-choice-check" />}
      </button>
    </li>
  );
}
