import { useEffect, useState } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { listConnections } from "../connections/connectionsApi";
import { listFunctions, loadEffective } from "./workRolesApi";
import { errorView, functionNames, TRUSTED_BADGE, viaText, writeConnectionsText, type ErrorView } from "./workRolesModel";
import { ErrorLine, RoleChip } from "./WorkRolesParts";
import type { EffectivePermission, WorkFunction } from "./workRolesTypes";

// What one member gets in a Workspace (contract §2 EffectivePermission): their roles and how each reaches them,
// the functions in words, the connections they may write through, and whether chat writes skip confirmation.
export function EffectivePanel({ workspaceId, workspaceName, member, onClose }: {
  workspaceId: string;
  workspaceName: string;
  member: { id: string; label: string };
  onClose: () => void;
}) {
  const [effective, setEffective] = useState<EffectivePermission | null>(null);
  const [functions, setFunctions] = useState<WorkFunction[]>([]);
  const [connections, setConnections] = useState<Array<{ id: string; name: string }>>([]);
  const [error, setError] = useState<ErrorView | null>(null);

  useEffect(() => {
    let cancelled = false;
    setEffective(null);
    loadEffective(workspaceId, member.id)
      .then((answer) => { if (!cancelled) setEffective(answer); })
      .catch((failure) => { if (!cancelled) setError(errorView(failure, "The member's permission could not be loaded.")); });
    listFunctions(workspaceId).then((list) => { if (!cancelled) setFunctions(list); }).catch(() => undefined);
    void listConnections().then((result) => {
      if (!cancelled && result.kind === "ok") setConnections(result.connections.map((c) => ({ id: c.id, name: c.name })));
    });
    return () => { cancelled = true; };
  }, [workspaceId, member.id]);

  const policy = effective?.command_policy;
  return (
    <SidePanel title={member.label} subtitle={`What they get in ${workspaceName}`} onClose={onClose} testId="effective-panel"
      footer={<button type="button" className="ds-btn" onClick={onClose}>Close</button>}>
      <ErrorLine error={error} />
      {!effective && !error ? <p className="wr-hint" role="status">Loading…</p> : null}
      {effective ? (
        <div className="wr-form">
          {effective.platform_admin ? <p className="wr-notice wr-notice--neutral">Platform admin: never limited by roles.</p> : null}
          {!effective.enforced && !effective.platform_admin ? (
            <p className="wr-notice wr-notice--neutral">Role-based tools is off in this Workspace, so this applies once it is turned on.</p>
          ) : null}
          {effective.trusted ? <p className="wr-notice" data-testid="effective-trusted">{TRUSTED_BADGE}: their chat writes run without confirming a write plan first.</p> : null}
          {effective.empty_reason ? <p className="wr-notice">{effective.empty_reason}</p> : null}
          <dl className="wr-facts">
            <div>
              <dt>Roles</dt>
              <dd>
                {effective.roles.length ? effective.roles.map((role) => (
                  <div key={role.id} className="wr-role-line">
                    <span className="wr-chips"><RoleChip name={role.name} trusted={role.trusted} /></span>
                    <span className="wr-name__sub">{role.via.map(viaText).join(" · ")}</span>
                  </div>
                )) : <span className="wr-muted">No role</span>}
              </dd>
            </div>
            <div>
              <dt>Functions</dt>
              <dd>{effective.functions.length ? functionNames(effective.functions, functions).join(", ") : <span className="wr-muted">None</span>}</dd>
            </div>
            <div>
              <dt>May write through</dt>
              <dd>{writeConnectionsText(effective.write_connections, connections)}</dd>
            </div>
            <div>
              <dt>Tools</dt>
              <dd>{effective.tools.length} {effective.tools.length === 1 ? "tool" : "tools"}</dd>
            </div>
            {policy && (policy.allow.length || policy.deny.length) ? (
              <div>
                <dt>Command rules</dt>
                <dd>
                  {policy.allow.length ? <div>Allow: {policy.allow.map((p) => <code key={p} className="wr-code">{p}</code>)}</div> : null}
                  {policy.deny.length ? <div>Deny: {policy.deny.map((p) => <code key={p} className="wr-code">{p}</code>)}</div> : null}
                </dd>
              </div>
            ) : null}
            <div>
              <dt>Chat writes</dt>
              <dd>{effective.trusted ? <StatusLabel label="No plan confirmation" tone="attention" /> : "After the write plan is confirmed"}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </SidePanel>
  );
}
