// The cards of Workspace → Coding tools & devices that edit the draft: model calls, session permissions by role and
// the command & file rules. Saving always sends the whole draft.
import type { Dispatch, SetStateAction } from "react";

import type { AdminNavigation } from "../../adminNavigation";
import { ChipListEditor, ToggleRow } from "../settingsKit/SettingsKit";
import type { Coding, RoleCeiling } from "./workspaceSettingsModel";
import { CEILING_OPTIONS, ROLE_ROWS, ruleKindLabel, ruleTarget } from "./workspaceSettingsModel";

type DraftProps = {
  draft: Coding;
  saved: Coding;
  setDraft: Dispatch<SetStateAction<Coding | null>>;
  changed: boolean;
  busy: boolean;
  save: () => Promise<void>;
};

// Discard (when changed) and Save, as at the end of each card.
function SaveRow({ saved, setDraft, changed, busy, save, testId }: Omit<DraftProps, "draft"> & { testId?: string }) {
  return (
    <div className="sk-row sk-row--end">
      {changed ? <button type="button" className="admin-panel__action-btn" onClick={() => setDraft(saved)}>Discard</button> : null}
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid={testId}
        disabled={busy || !changed} onClick={() => void save()}>
        {busy ? "Saving…" : "Save"}
      </button>
    </div>
  );
}

export function CodingModelCallsCard({ draft, setDraft, onOpenModels }: Pick<DraftProps, "draft" | "setDraft"> & {
  onOpenModels: () => void;
}) {
  return (
    <section className="admin-panel__card">
      <div className="admin-panel__section-header"><span>Model calls</span></div>
      <ToggleRow title="Require the company gateway for every model call" on={draft.requiresGovernedRouting}
        testId="coding-governed-routing" onChange={(next) => setDraft({ ...draft, requiresGovernedRouting: next })}
        sub={<>Coding tools then only reach models through the gateway. Seats: see{" "}
          <button type="button" className="sk-link" onClick={onOpenModels}>Models</button>.</>} />
    </section>
  );
}

export function CodingRoleModesCard(props: DraftProps & { isPlatformAdmin: boolean }) {
  const { draft, setDraft, isPlatformAdmin } = props;
  return (
    <section className="admin-panel__card" data-testid="coding-role-modes">
      <div className="admin-panel__section-header"><span>Session permissions by role</span></div>
      <p className="sk-hint">
        What a person's Claude Code sessions may do in this Workspace, by their role: in the terminal, in VS Code and
        from the phone. The command &amp; file rules below apply in every role.
        {isPlatformAdmin ? null : " Workspace admins can lower a role; raising it is a platform admin's decision."}
      </p>
      <table className="admin-panel__table sk-cards">
        <thead><tr><th>Role</th><th>Sessions may</th></tr></thead>
        <tbody>
          {ROLE_ROWS.map((row) => (
            <tr key={row.role}>
              <td data-label="Role"><b>{row.label}</b><div className="admin-panel__cell--muted">{row.desc}</div></td>
              <td data-label="Sessions may">
                <select className="admin-panel__input" aria-label={`${row.label} sessions may`} value={draft.roleModes[row.role]}
                  data-testid={`coding-role-${row.role}`}
                  onChange={(event) => setDraft({ ...draft, roleModes: { ...draft.roleModes,
                    [row.role]: event.target.value as RoleCeiling } })}>
                  {CEILING_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <SaveRow {...props} />
    </section>
  );
}

export function CodingRulesCard(props: DraftProps & {
  message: { ok: boolean; text: string } | null;
  onAdd: () => void;
  openAdminTab: AdminNavigation["openAdminTab"];
}) {
  const { draft, setDraft, message, onAdd, openAdminTab } = props;
  return (
    <section className="admin-panel__card">
      <div className="admin-panel__section-header">
        <span>Command &amp; file rules</span>
        <button type="button" className="admin-panel__action-btn" data-testid="coding-add-rule" onClick={onAdd}>Add rule</button>
      </div>
      <p className="sk-hint">
        Apply to coding tools and device runs. Each rule is also published as a policy (
        <button type="button" className="sk-link" onClick={() => openAdminTab("cedarPolicies")}>Policies</button>, generated).
      </p>
      <table className="admin-panel__table sk-cards" data-testid="coding-rules">
        <thead><tr><th>Rule</th><th>Kind</th><th>Target</th><th /></tr></thead>
        <tbody>
          {draft.toolRules.length === 0 ? <tr><td colSpan={4} className="admin-panel__cell--muted">No rule.</td></tr> : null}
          {draft.toolRules.map((rule) => (
            <tr key={rule.id}>
              <td data-label="Rule">{rule.id}</td>
              <td data-label="Kind">{ruleKindLabel(rule.kind)}</td>
              <td data-label="Target"><span className="admin-policy-inline-code">{ruleTarget(rule)}</span></td>
              <td>
                <button type="button" className="admin-panel__action-btn" aria-label={`Remove ${rule.id}`}
                  onClick={() => setDraft({ ...draft, toolRules: draft.toolRules.filter((item) => item.id !== rule.id) })}>
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="admin-panel__field">
        <span>Blocked in the coding tool's own permissions</span>
        <ChipListEditor label="blocked coding-tool permissions" values={draft.clientDeny} tone="danger" testId="coding-client-deny"
          onChange={(clientDeny) => setDraft({ ...draft, clientDeny })} />
      </div>
      {message ? <p className={message.ok ? "admin-panel__success" : "sk-err"} role={message.ok ? "status" : "alert"}>{message.text}</p> : null}
      <SaveRow {...props} testId="coding-save" />
    </section>
  );
}
