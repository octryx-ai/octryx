import { useId, useState } from "react";

import { FormSection } from "../../../layout/FormSection";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { createAssignment } from "./workRolesApi";
import { errorView, TRUSTED_BADGE, type ErrorView } from "./workRolesModel";
import { CheckRow, ErrorLine } from "./WorkRolesParts";
import type { AssignmentSubject, SsoProvider, WorkRole } from "./workRolesTypes";

export type AssignMode = "person" | "sso";
export type PickOption = { id: string; label: string };

type AssignPanelProps = {
  mode: AssignMode;
  workspaceId: string;
  workspaceName: string;
  roles: WorkRole[];
  people: PickOption[];
  groups: PickOption[];
  providers: SsoProvider[];
  onClose: () => void;
  onDone: () => void;
};

/** The assignment subject for the picked kind and value, or null while no value is given. */
function assignmentSubject(kind: AssignmentSubject["kind"], value: string, providerId: string): AssignmentSubject | null {
  if (!value) return null;
  if (kind === "user") return { kind, user_id: value };
  if (kind === "group") return { kind, group_id: value };
  return { kind, value, provider_id: providerId || null };
}

/** Assigns each role in turn; a role that is already assigned is skipped. */
async function assignRoles(workspaceId: string, roleIds: string[], who: AssignmentSubject) {
  for (const roleId of roleIds) {
    try {
      await createAssignment(workspaceId, roleId, who);
    } catch (failure) {
      // Already assigned: nothing to do for that role.
      if ((failure as { code?: string }).code !== "assignment_exists") throw failure;
    }
  }
}

// Assign one or more roles in a Workspace: to a person or Workspace group ("Assign person"), or to an SSO group or
// SSO role claim ("Assign SSO group or role"; values from sign-ins are offered, any other value may be typed).
export function AssignPanel({ mode, workspaceId, workspaceName, roles, people, groups, providers, onClose, onDone }: AssignPanelProps) {
  const listId = useId();
  const [kind, setKind] = useState<AssignmentSubject["kind"]>(mode === "person" ? "user" : "sso_group");
  const [target, setTarget] = useState("");
  const [providerId, setProviderId] = useState<string>(providers.length === 1 ? providers[0].id : "");
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [error, setError] = useState<ErrorView | null>(null);
  const [busy, setBusy] = useState(false);

  const scoped = providerId ? providers.filter((p) => p.id === providerId) : providers;
  const suggestions = Array.from(new Set(scoped.flatMap((p) => (kind === "sso_role" ? p.known_roles : p.known_groups)))).sort();
  const value = target.trim();

  const submit = async () => {
    const who = assignmentSubject(kind, value, providerId);
    if (!who) return;
    setBusy(true);
    setError(null);
    try {
      await assignRoles(workspaceId, roleIds, who);
      onDone();
    } catch (failure) {
      setError(errorView(failure));
    } finally {
      setBusy(false);
    }
  };

  const title = mode === "person" ? "Assign person" : "Assign SSO group or role";
  const footer = (
    <>
      <button type="button" className="ds-btn" onClick={onClose}>Cancel</button>
      <button type="button" className="ds-btn ds-btn--primary" data-testid="assign-save" disabled={busy || !value || !roleIds.length}
        onClick={() => void submit()}>{busy ? "Assigning…" : roleIds.length > 1 ? `Assign ${roleIds.length} roles` : "Assign"}</button>
    </>
  );

  return (
    <SidePanel title={title} subtitle={workspaceName} onClose={onClose} footer={footer} testId="assign-panel">
      <div className="wr-form">
        <ErrorLine error={error} />
        <FormSection title="Who">
          <KindTabs mode={mode} kind={kind} hasGroups={groups.length > 0} onKind={(next) => { setKind(next); setTarget(""); }} />
          {kind === "user" || kind === "group" ? (
            <TargetPicker kind={kind} target={target} options={kind === "user" ? people : groups} onTarget={setTarget} />
          ) : (
            <SsoValueFields kind={kind} listId={listId} target={target} providerId={providerId} providers={providers}
              suggestions={suggestions} onTarget={setTarget} onProvider={setProviderId} />
          )}
        </FormSection>
        <FormSection title="Roles">
          <RoleChecks roles={roles} roleIds={roleIds} onRoleIds={setRoleIds} />
        </FormSection>
      </div>
    </SidePanel>
  );
}

type Kind = AssignmentSubject["kind"];

function KindTabs({ mode, kind, hasGroups, onKind }: { mode: AssignMode; kind: Kind; hasGroups: boolean; onKind: (kind: Kind) => void }) {
  return mode === "person" ? (
    <SegmentedTabs label="Assign to" size="small" idPrefix="assign-kind" value={kind}
      onChange={(next) => onKind(next as AssignmentSubject["kind"])}
      tabs={[{ key: "user", label: "Person" }, { key: "group", label: "Workspace group", disabled: !hasGroups }]} />
  ) : (
    <SegmentedTabs label="Assign to" size="small" idPrefix="assign-kind" value={kind}
      onChange={(next) => onKind(next as AssignmentSubject["kind"])}
      tabs={[{ key: "sso_group", label: "SSO group" }, { key: "sso_role", label: "SSO role" }]} />
  );
}

function TargetPicker({ kind, target, options, onTarget }: { kind: Kind; target: string; options: PickOption[]; onTarget: (value: string) => void }) {
  return (
    <label className="wr-field">
      <span>{kind === "user" ? "Person" : "Workspace group"}</span>
      <select value={target} data-testid="assign-target" onChange={(event) => onTarget(event.target.value)}>
        <option value="">{kind === "user" ? "Choose a person" : "Choose a group"}</option>
        {options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
      </select>
    </label>
  );
}

function SsoValueFields({ kind, listId, target, providerId, providers, suggestions, onTarget, onProvider }: {
  kind: Kind; listId: string; target: string; providerId: string; providers: SsoProvider[]; suggestions: string[];
  onTarget: (value: string) => void; onProvider: (value: string) => void;
}) {
  return (
    <>
      <label className="wr-field">
        <span>Identity provider</span>
        <select value={providerId} onChange={(event) => onProvider(event.target.value)}>
          <option value="">Any identity provider</option>
          {providers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <label className="wr-field">
        <span>{kind === "sso_role" ? "SSO role (as in the roles claim)" : "SSO group (as in the groups claim)"}</span>
        <input list={listId} value={target} data-testid="assign-sso-value" className="wr-mono" autoComplete="off"
          placeholder={kind === "sso_role" ? "Release-Manager" : "eng-developers"} onChange={(event) => onTarget(event.target.value)} />
        <datalist id={listId}>{suggestions.map((s) => <option key={s} value={s} />)}</datalist>
      </label>
      <p className="wr-hint">
        {suggestions.length
          ? `${suggestions.length} known from sign-ins. A name nobody has signed in with yet can be typed; it applies from their next sign-in.`
          : "No value seen in a sign-in yet. Type the name exactly as the identity provider sends it."}
      </p>
    </>
  );
}

function RoleChecks({ roles, roleIds, onRoleIds }: { roles: WorkRole[]; roleIds: string[]; onRoleIds: (ids: string[]) => void }) {
  return (
    <div className="wr-checks">
      {roles.map((role) => (
        <CheckRow key={role.id} checked={roleIds.includes(role.id)} testId={`assign-role-${role.key}`}
          onChange={(on) => onRoleIds(on ? [...roleIds, role.id] : roleIds.filter((id) => id !== role.id))}
          title={role.trusted ? <span className="wr-name__line">{role.name}<StatusLabel label={TRUSTED_BADGE} tone="attention" /></span> : role.name}
          sub={role.description} />
      ))}
    </div>
  );
}
