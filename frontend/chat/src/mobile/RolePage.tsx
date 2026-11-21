// More › My role (roles contract §3.3), read-only: the person's roles in the chosen Workspace (with the
// trusted badge), what they can do in words, where they may write, and the empty state when role-based tools are on
// and no role applies. A Workspace admin also sees the Workspace's assignments and the switch; changes stay on the
// desktop. The routes check who may read what; a refused admin read simply leaves that part out.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { StatusLabel } from "../layout/StatusLabel";
import {
  EMPTY_REASON_EN,
  TRUSTED_BADGE,
  WHO_ASSIGNS_ROLES,
  functionName,
  membersWithoutRoleText,
  readEffectivePermission,
  readWorkspaceRoles,
  subjectKindText,
  switchText,
  viaSummary,
  writeConnectionsText,
  type EffectivePermission,
  type WorkspaceRoles,
} from "../chat/roles/myRoleModel";
import { loadMyRole, loadWorkspaceRoles } from "./mobileApi";
import { DetailHeader } from "./PageHeader";
import { useRefreshEvent } from "./pullToRefresh";

export function RolePage({
  workspaceId,
  workspaceName,
  switcher,
  onBack,
}: {
  workspaceId: string;
  workspaceName: string;
  switcher?: ReactNode;
  onBack: () => void;
}) {
  const [mine, setMine] = useState<EffectivePermission | null>(null);
  const [admin, setAdmin] = useState<WorkspaceRoles | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const load = useCallback(async () => {
    if (!workspaceId) {
      setState("ready");
      return;
    }
    const [own, all] = await Promise.allSettled([loadMyRole(workspaceId), loadWorkspaceRoles(workspaceId)]);
    const permission = own.status === "fulfilled" ? readEffectivePermission(own.value) : null;
    setMine(permission);
    setAdmin(all.status === "fulfilled" ? readWorkspaceRoles(all.value) : null);
    setState(permission ? "ready" : "error");
  }, [workspaceId]);
  useRefreshEvent(load);
  useEffect(() => {
    setState("loading");
    setMine(null);
    setAdmin(null);
    void load();
  }, [load]);

  return (
    <div className="m-screen">
      <DetailHeader title="My role" subtitle={workspaceName || undefined} onBack={onBack} />
      <main className="m-body">
        {switcher}
        {state === "loading" && <p className="m-empty">Loading…</p>}
        {state === "error" && (
          <p className="m-banner m-banner-problem" role="alert">
            Your roles could not be loaded.
          </p>
        )}
        {!workspaceId && <p className="m-empty">Choose a Workspace to see your role there.</p>}
        {mine && <MyRole permission={mine} workspaceName={workspaceName} />}
        {admin && <WorkspaceAssignments roles={admin} />}
      </main>
    </div>
  );
}

function MyRole({ permission, workspaceName }: { permission: EffectivePermission; workspaceName: string }) {
  const empty = permission.enforced && !permission.platformAdmin && !permission.roles.length;
  return (
    <>
      {empty && (
        <div className="m-banner m-banner-attention" role="status" data-testid="m-role-empty">
          <p>{permission.emptyReason || EMPTY_REASON_EN}</p>
          <p className="m-banner-hint">
            Who can assign roles: a {WHO_ASSIGNS_ROLES} of {workspaceName || "this Workspace"}. The chat still answers,
            without tools.
          </p>
        </div>
      )}
      {permission.platformAdmin && (
        <p className="m-banner m-banner-info">You are a platform admin: your tools are never filtered by roles.</p>
      )}
      {!permission.enforced && !permission.platformAdmin && (
        <p className="m-note">
          Role-based tools are off in this Workspace, so you have its usual tools. Your roles apply once a{" "}
          {WHO_ASSIGNS_ROLES} turns them on.
        </p>
      )}
      {permission.roles.length > 0 && (
        <section aria-label="Your roles">
          <h2 className="m-section">{permission.roles.length === 1 ? "Your role" : "Your roles"}</h2>
          <ul className="m-rows m-group">
            {permission.roles.map((role) => (
              <li key={role.id || role.name}>
                <div className="m-row m-row-plain m-row-wrap">
                  <span className="m-row-text">
                    <b>{role.name}</b>
                    {viaSummary(role) && <span>{viaSummary(role)}</span>}
                    {role.trusted && (
                      <span className="m-row-status">
                        <StatusLabel label={TRUSTED_BADGE} tone="attention" />
                      </span>
                    )}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      {permission.functions.length > 0 && (
        <section aria-label="What you can do">
          <h2 className="m-section">What you can do</h2>
          <ul className="m-rows m-group">
            {permission.functions.map((key) => (
              <li key={key}>
                <div className="m-row m-row-plain m-row-single">
                  <span className="m-row-text">
                    <b>{functionName(key)}</b>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      {permission.roles.length > 0 && (
        <section className="m-panel" aria-label="Writes">
          <h2 className="m-section">Writes through</h2>
          <p className="m-note">{writeConnectionsText(permission)}</p>
          {permission.trusted && (
            <p className="m-facts-line">Your chat writes run without a plan confirmation.</p>
          )}
        </section>
      )}
    </>
  );
}

function WorkspaceAssignments({ roles }: { roles: WorkspaceRoles }) {
  const toggle = switchText(roles);
  const without = membersWithoutRoleText(roles.membersWithoutRole, roles.roleBasedTools);
  const active = roles.assignments.filter((assignment) => assignment.active);
  return (
    <section className="m-role-stack" aria-label="Workspace roles" data-testid="m-role-admin">
      <div>
        <h2 className="m-section">Workspace roles</h2>
        <p className="m-section-hint">Read-only here. Change roles on the desktop (Workspace › Roles).</p>
      </div>
      <div className="m-panel">
        <dl className="m-facts m-facts-first">
          <div>
            <dt>Role-based tools</dt>
            <dd>
              <b>{toggle.label}</b> · {toggle.detail}
            </dd>
          </div>
          {without && (
            <div>
              <dt>Without role</dt>
              <dd>{without}</dd>
            </div>
          )}
        </dl>
      </div>
      {active.length ? (
        <ul className="m-rows m-group">
          {active.map((assignment) => {
            const kind = subjectKindText(assignment.subject.kind);
            const reach =
              assignment.members !== null && assignment.subject.kind !== "user"
                ? `${assignment.members} ${assignment.members === 1 ? "person" : "people"}`
                : "";
            return (
              <li key={assignment.id}>
                <div className="m-row m-row-plain m-row-wrap">
                  <span className="m-row-text">
                    <b>{assignment.subject.label}</b>
                    <span>{[assignment.roleName, kind, reach].filter(Boolean).join(" · ")}</span>
                    {roles.trustedRoleIds.has(assignment.roleId) && (
                      <span className="m-row-status">
                        <StatusLabel label={TRUSTED_BADGE} tone="attention" />
                      </span>
                    )}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="m-empty">No roles are assigned in this Workspace yet.</p>
      )}
    </section>
  );
}
