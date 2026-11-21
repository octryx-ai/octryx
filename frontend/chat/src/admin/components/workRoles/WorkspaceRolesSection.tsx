import type { ReactNode } from "react";

import { AssignPanel } from "./AssignPanel";
import { EffectivePanel } from "./EffectivePanel";
import { assignmentRows } from "./workRolesModel";
import { Card, ErrorLine } from "./WorkRolesParts";
import { useWorkspaceRoles } from "./useWorkspaceRoles";
import { AssignmentsCard, RevokeDialog, RoleBasedToolsCard, SwitchDialog } from "./WorkspaceRolesCards";
import "./workRoles.css";

// A Workspace's roles (board 8 "Assignments in …", contract §3.3): the "Role-based tools" switch with the members it
// would leave without tools, who holds which role, assigning and revoking, and the effective-permission preview for
// one member. Used on Workspace › Roles and on Admin › Roles & functions (with a Workspace switch in the title).
export function WorkspaceRolesSection({ workspaceId, workspaceName, workspaceSelect, primaryAssign = true }: {
  workspaceId: string;
  workspaceName: string;
  // The global page's Workspace picker, shown in the title ("Assignments in [Workspace ▾]").
  workspaceSelect?: ReactNode;
  // One primary action per view: the global page already has "New role".
  primaryAssign?: boolean;
}) {
  const m = useWorkspaceRoles(workspaceId);
  const { data, assign, preview, revoking } = m;

  if (m.loadError) return <Card title={`Roles in ${workspaceName}`}><ErrorLine error={m.loadError} /></Card>;
  if (!data) return <Card title={`Roles in ${workspaceName}`}><p className="wr-hint" role="status">Loading roles…</p></Card>;

  const part = { m, data, workspaceId, workspaceName };
  return (
    <div className="wr-page" data-testid="workspace-roles">
      <ErrorLine error={m.error} />
      <RoleBasedToolsCard {...part} />

      <AssignmentsCard {...part} rows={assignmentRows(data.assignments)} workspaceSelect={workspaceSelect} primaryAssign={primaryAssign} />

      {assign ? (
        <AssignPanel mode={assign} workspaceId={workspaceId} workspaceName={workspaceName} roles={data.roles.filter((r) => r.is_active)}
          people={m.allUsers} groups={m.groups} providers={m.providers} onClose={() => m.setAssign(null)}
          onDone={() => { m.setAssign(null); void m.load(); }} />
      ) : null}

      {preview ? <EffectivePanel workspaceId={workspaceId} workspaceName={workspaceName} member={preview} onClose={() => m.setPreview(null)} /> : null}

      {m.switchStep !== null ? <SwitchDialog {...part} /> : null}

      {revoking ? <RevokeDialog m={m} workspaceId={workspaceId} workspaceName={workspaceName} revoking={revoking} /> : null}
    </div>
  );
}
