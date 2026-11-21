import type { ReactNode } from "react";

import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { ToggleSwitch } from "../settingsKit/SettingsKit";
import { membersText, membersWithoutRoleText, subjectKindLabel, subjectLabel, type AssignmentRow } from "./workRolesModel";
import { Card, CheckRow, RoleChip } from "./WorkRolesParts";
import type { WorkRole, WorkspaceRoles } from "./workRolesTypes";
import { applyRevoke, applySwitch, type WorkspaceRolesModel } from "./useWorkspaceRoles";

type Part = { m: WorkspaceRolesModel; data: WorkspaceRoles; workspaceId: string; workspaceName: string };

export function RoleBasedToolsCard({ m, data }: Part) {
  const on = data.settings.role_based_tools;
  const without = data.members_without_role;
  return (
    <Card title="Role-based tools" testId="role-based-tools"
      meta={on
        ? "On: each member gets only the tools of their roles. A member without a role has no tools; platform admins are never limited."
        : "Off: roles are shown but do not limit tools yet. Turn it on once everyone who needs tools has a role."}
      actions={<ToggleSwitch on={on} label="Role-based tools" disabled={!data.can_edit || m.busy} testId="role-based-tools-switch"
        onChange={(next) => { m.setSwitchError(null); m.setSwitchStep(next); }} />}>
      <p className={without.length ? "wr-notice" : "wr-notice wr-notice--neutral"} data-testid="members-without-role">
        {membersWithoutRoleText(without, on)}
      </p>
      {data.can_edit ? null : <p className="wr-hint">Only a Workspace admin or someone with the function “Assign roles” can change this.</p>}
    </Card>
  );
}

function assignmentColumns({ m, data, workspaceName }: Part): DataTableColumn<AssignmentRow>[] {
  const roleById = new Map<string, WorkRole>(data.roles.map((role) => [role.id, role]));
  const providerName = (id: string | null) => (id ? m.providers.find((p) => p.id === id)?.name ?? null : null);
  const openRevoke = (row: AssignmentRow) => {
    m.setRevokeError(null);
    m.setRevokeIds(row.assignments.map((a) => a.id));
    m.setRevoking(row);
  };
  return [
    { key: "who", header: "Who", minWidth: "14rem", render: (row) => (
      <span className="wr-name">
        <span className="wr-name__title">{subjectLabel(row.subject)}</span>
        <span className="wr-name__sub">{subjectKindLabel(row.subject, "provider_id" in row.subject ? providerName(row.subject.provider_id) : null)}</span>
      </span>
    ) },
    { key: "roles", header: `Roles in ${workspaceName}`, grow: true, render: (row) => (
      <span className="wr-chips">
        {row.assignments.map((a) => <RoleChip key={a.id} name={a.role_name} trusted={roleById.get(a.role_id)?.trusted ?? false} />)}
      </span>
    ) },
    { key: "members", header: "Members", nowrap: true, render: (row) => <span className="wr-muted">{membersText(row.subject, row.members)}</span> },
    { key: "actions", header: "", nowrap: true, align: "end", render: (row) => (
      <span className="wr-row-actions">
        {row.subject.kind === "user" ? (
          <button type="button" className="ds-btn ds-btn--sm" onClick={() => m.setPreview({ id: (row.subject as { user_id: string }).user_id, label: subjectLabel(row.subject) })}>
            Preview
          </button>
        ) : null}
        {data.can_edit ? <button type="button" className="ds-btn ds-btn--sm" data-testid={`revoke-${row.key}`} onClick={() => openRevoke(row)}>Revoke</button> : null}
      </span>
    ) },
  ];
}

export function AssignmentsCard(props: Part & { rows: AssignmentRow[]; workspaceSelect?: ReactNode; primaryAssign: boolean }) {
  const { m, data, workspaceName, rows, workspaceSelect, primaryAssign } = props;
  return (
    <Card title="Assignments" testId="role-assignments"
      meta={<span className="wr-assign-title">{workspaceSelect ?? <>in {workspaceName}</>}</span>}
      actions={data.can_edit ? (
        <>
          <button type="button" className="ds-btn" data-testid="assign-sso" onClick={() => m.setAssign("sso")}>Assign SSO group or role</button>
          <button type="button" className={`ds-btn${primaryAssign ? " ds-btn--primary" : ""}`} data-testid="assign-person"
            onClick={() => m.setAssign("person")}>Assign person</button>
        </>
      ) : null}>
      <DataTable<AssignmentRow>
        label="Role assignments" testId="role-assignments-table" rows={rows} rowKey={(row) => row.key}
        empty={{ text: "Nobody holds a role in this Workspace yet." }}
        columns={assignmentColumns(props)}
      />
      <div className="wr-preview-row">
        <label className="wr-field wr-preview-row">
          <span>What a member gets</span>
          <select value={m.previewPick} data-testid="preview-member" onChange={(event) => m.setPreviewPick(event.target.value)}>
            <option value="">Choose a member</option>
            {m.people.map((person) => <option key={person.id} value={person.id}>{person.label}</option>)}
          </select>
        </label>
        <button type="button" className="ds-btn" disabled={!m.previewPick} data-testid="preview-open"
          onClick={() => m.setPreview(m.people.find((p) => p.id === m.previewPick) ?? null)}>Show effective permission</button>
      </div>
      <p className="wr-hint">A person gets every role from all lines that apply. SSO membership is read at each sign-in; leave the group in the identity provider and the role is gone at the next sign-in.</p>
    </Card>
  );
}

export function SwitchDialog({ m, data, workspaceId, workspaceName }: Part) {
  const switchStep = m.switchStep;
  const without = data.members_without_role;
  return (
    <ConfirmDialog title={switchStep ? `Turn on Role-based tools in ${workspaceName}?` : `Turn off Role-based tools in ${workspaceName}?`}
      tone="neutral" confirmLabel={switchStep ? "Turn on" : "Turn off"} busy={m.busy} error={m.switchError}
      onCancel={() => m.setSwitchStep(null)} onConfirm={() => void applySwitch(m, workspaceId, data)}>
      {switchStep ? (
        <>
          <p>Each member then gets only the tools of their roles, in the chat and in the client.</p>
          <p className={without.length ? "wr-notice" : "wr-notice wr-notice--neutral"}>{membersWithoutRoleText(without)}</p>
        </>
      ) : <p>Roles stop limiting tools; every member gets the Workspace's tools again.</p>}
    </ConfirmDialog>
  );
}

export function RevokeDialog({ m, workspaceId, workspaceName, revoking }: Omit<Part, "data"> & { revoking: AssignmentRow }) {
  const { revokeIds, setRevokeIds } = m;
  return (
    <ConfirmDialog title={`Revoke roles of ${subjectLabel(revoking.subject)}?`} confirmLabel="Revoke" busy={m.busy} error={m.revokeError}
      confirmDisabled={!revokeIds.length} onCancel={() => m.setRevoking(null)} onConfirm={() => void applyRevoke(m, workspaceId)}>
      {revoking.assignments.length > 1 ? (
        <div className="wr-checks">
          {revoking.assignments.map((a) => (
            <CheckRow key={a.id} checked={revokeIds.includes(a.id)} title={a.role_name}
              onChange={(next) => setRevokeIds(next ? [...revokeIds, a.id] : revokeIds.filter((id) => id !== a.id))} />
          ))}
        </div>
      ) : <p>{revoking.assignments[0]?.role_name} no longer applies to {subjectLabel(revoking.subject)} in {workspaceName}.</p>}
    </ConfirmDialog>
  );
}
