import { useCallback, useEffect, useState, type ReactNode } from "react";

import { DataTable } from "../../../layout/DataTable";
import { useActiveWorkspace } from "../../../chat/useActiveWorkspace";
import { AdminHeaderActions } from "../AdminHeaderSlot";
import { RoleEditorPanel } from "./RoleEditorPanel";
import { SsoMappingCards } from "./SsoMappingCard";
import { WorkspaceRolesSection } from "./WorkspaceRolesSection";
import { listFunctions, listRoles } from "./workRolesApi";
import { errorView, matrixRows, scopeText, type ErrorView, type MatrixRow } from "./workRolesModel";
import { Card, ErrorLine, RoleBadges } from "./WorkRolesParts";
import type { WorkFunction, WorkRole } from "./workRolesTypes";
import "./workRoles.css";

type Workspace = { id: string; name: string };

// Admin › People & sign-in › Roles & functions › Roles (board 8 "Global › People & roles"): the role × function
// matrix with "New role", the SSO mapping per identity provider and the assignments of one Workspace.
export function WorkRolesPage({ projects, isAdmin }: { projects: Workspace[]; isAdmin: boolean }) {
  const [roles, setRoles] = useState<WorkRole[] | null>(null);
  const [functions, setFunctions] = useState<WorkFunction[]>([]);
  const [error, setError] = useState<ErrorView | null>(null);
  const [editing, setEditing] = useState<WorkRole | "new" | null>(null);
  const [workspaceId, setWorkspaceId] = useActiveWorkspace(projects);
  const [assignmentsKey, setAssignmentsKey] = useState(0);

  const load = useCallback(async () => {
    try {
      const [nextRoles, nextFunctions] = await Promise.all([listRoles(), listFunctions()]);
      setRoles(nextRoles);
      setFunctions(nextFunctions);
      setError(null);
    } catch (failure) {
      setRoles([]);
      setError(errorView(failure, "The roles could not be loaded."));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const workspace = projects.find((p) => p.id === workspaceId) ?? projects[0] ?? null;

  return (
    <div className="wr-page" data-testid="work-roles-page">
      {isAdmin ? (
        <AdminHeaderActions>
          <button type="button" className="ds-btn ds-btn--primary" data-testid="new-role" onClick={() => setEditing("new")}>New role</button>
        </AdminHeaderActions>
      ) : null}
      <ErrorLine error={error} />

      <RoleMatrixCard roles={roles} functions={functions} projects={projects} isAdmin={isAdmin} editing={editing}
        setEditing={setEditing} />

      <SsoMappingCards canEdit={isAdmin} />

      {workspace ? (
        <WorkspaceRolesSection key={`${workspace.id}:${assignmentsKey}`} workspaceId={workspace.id} workspaceName={workspace.name} primaryAssign={false}
          workspaceSelect={(
            <>
              <span>in</span>
              <select className="wr-input" aria-label="Workspace" value={workspace.id} data-testid="roles-workspace" onChange={(event) => setWorkspaceId(event.target.value)}>
                {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </>
          )} />
      ) : <Card title="Assignments"><p className="ds-empty">Create a Workspace to assign roles in it.</p></Card>}

      {editing ? (
        <RoleEditorPanel key={editing === "new" ? "new" : editing.id} role={editing === "new" ? null : editing} functions={functions} workspaces={projects} canEdit={isAdmin}
          onClose={() => setEditing(null)}
          onSaved={() => { void load(); setAssignmentsKey((k) => k + 1); }} />
      ) : null}
    </div>
  );
}

// The role × function matrix: a row per role (opens its editor), a column per function.
function RoleMatrixCard({ roles, functions, projects, isAdmin, editing, setEditing }: {
  roles: WorkRole[] | null;
  functions: WorkFunction[];
  projects: Workspace[];
  isAdmin: boolean;
  editing: WorkRole | "new" | null;
  setEditing: (next: WorkRole | "new" | null) => void;
}) {
  const rows = roles ? matrixRows(roles, functions) : [];
  const cell = (row: MatrixRow, content: ReactNode) => <span className={row.muted ? "wr-is-muted" : undefined}>{content}</span>;

  return (
    <Card title="Roles and their functions" testId="role-matrix"
      meta="A role is a name plus the functions it may use. Define roles once; assign them in each Workspace to people, SSO groups or SSO roles.">
      <div className="wr-matrix">
        <DataTable<MatrixRow>
          label="Roles and functions" rows={rows} rowKey={(row) => row.role.id} loading={roles === null} loadingLabel="roles"
          onOpen={(row) => setEditing(row.role)} selectedKey={editing && editing !== "new" ? editing.id : null}
          empty={{ text: "No role yet.", action: isAdmin ? { label: "New role", onClick: () => setEditing("new") } : undefined }}
          columns={[
            { key: "role", header: "Role", minWidth: "15rem", grow: true, render: (row) => cell(row, (
              <span className="wr-name">
                <span className="wr-name__line"><span className="wr-name__title">{row.role.name}</span><RoleBadges role={row.role} /></span>
                <span className="wr-name__sub">
                  {scopeText(row.role.workspace_id, projects)} · {row.role.assignment_count} {row.role.assignment_count === 1 ? "assignment" : "assignments"}
                </span>
              </span>
            )) },
            ...functions.map((fn, index) => ({
              key: fn.key, header: fn.name, width: "6.5rem",
              render: (row: MatrixRow) => cell(row, row.cells[index]
                ? <span className="wr-tick" aria-label="Yes">✓</span>
                : <span className="wr-tick wr-tick--no" aria-label="No">·</span>),
            })),
          ]}
        />
      </div>
      <p className="wr-hint">
        “Decide as product owner” is a function, not a role: every role with it may answer readiness and ship decisions.
        Built-in roles cannot lose the functions that keep a Workspace manageable.
      </p>
    </Card>
  );
}
