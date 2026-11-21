import { FormSection } from "../../../layout/FormSection";
import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { ToggleSwitch } from "../settingsKit/SettingsKit";
import { COMMAND_LAYERING_TEXT, TRUSTED_BADGE } from "./workRolesModel";
import { slugify, trustedConfirmText } from "./workRoleDraft";
import { CheckRow } from "./WorkRolesParts";
import type { WorkFunction, WorkRole } from "./workRolesTypes";
import type { RoleEditor } from "./useRoleEditor";

type Workspace = { id: string; name: string };
type Part = { editor: RoleEditor; readOnly: boolean };

export function RoleEditorFooter({ editor, readOnly, onClose }: Part & { onClose: () => void }) {
  const { role, busy, problems, creating } = editor;
  if (readOnly) return <button type="button" className="ds-btn" onClick={onClose}>Close</button>;
  return (
    <div className="wr-footer">
      {role && !role.built_in ? (
        <button type="button" className="ds-btn ds-btn--danger" data-testid="role-delete" disabled={busy}
          onClick={() => { editor.setDeleteError(null); editor.setConfirmDelete(true); }}>Delete role</button>
      ) : null}
      <span className="wr-footer__spacer" />
      <button type="button" className="ds-btn" onClick={onClose}>Cancel</button>
      <button type="button" className="ds-btn ds-btn--primary" data-testid="role-save" disabled={busy || problems.length > 0}
        title={problems[0]} onClick={() => void editor.save()}>
        {busy ? "Saving…" : creating ? "Create role" : "Save"}
      </button>
    </div>
  );
}

export function RoleBasicsSection({ editor, readOnly, workspaces }: Part & { workspaces: Workspace[] }) {
  const { draft, set, creating, keyTouched } = editor;
  return (
    <FormSection title="Role">
      <label className="wr-field">
        <span>Name</span>
        <input value={draft.name} disabled={readOnly} data-testid="role-name"
          onChange={(event) => set({ name: event.target.value, ...(creating && !keyTouched ? { key: slugify(event.target.value) } : {}) })} />
      </label>
      {creating ? (
        <div className="wr-grid-2">
          <label className="wr-field">
            <span>Key</span>
            <input className="wr-mono" value={draft.key} data-testid="role-key"
              onChange={(event) => { editor.setKeyTouched(true); set({ key: event.target.value.trim() }); }} />
          </label>
          <label className="wr-field">
            <span>Available in</span>
            <select value={draft.workspace_id ?? ""} onChange={(event) => set({ workspace_id: event.target.value || null })}>
              <option value="">All Workspaces</option>
              {workspaces.map((ws) => <option key={ws.id} value={ws.id}>Only {ws.name}</option>)}
            </select>
          </label>
        </div>
      ) : (
        <div className="wr-field"><span>Key</span><span className="wr-field__key">{editor.role!.key}</span></div>
      )}
      <label className="wr-field">
        <span>Description</span>
        <textarea value={draft.description} disabled={readOnly} rows={2} onChange={(event) => set({ description: event.target.value })} />
      </label>
    </FormSection>
  );
}

export function RoleFunctionsSection({ editor, readOnly, functions }: Part & { functions: WorkFunction[] }) {
  return (
    <FormSection title="Functions">
      <p className="wr-hint">A person gets every function of every role assigned to them in a Workspace.</p>
      <div className="wr-checks">
        {functions.map((fn) => {
          const locked = editor.kept.includes(fn.key);
          return (
            <CheckRow key={fn.id} checked={editor.draft.function_keys.includes(fn.key)} disabled={readOnly || locked}
              testId={`role-function-${fn.key}`} onChange={(on) => editor.toggleFunction(fn.key, on)}
              title={fn.name} sub={locked ? `${fn.description} Kept by this built-in role.` : fn.description} />
          );
        })}
      </div>
    </FormSection>
  );
}

function ConnectionChoices({ editor, readOnly }: Part) {
  const { connections, draft } = editor;
  if (connections === null) return <p className="wr-hint" role="status">Loading connections…</p>;
  if (connections.length === 0) return <p className="wr-hint">No named connection exists yet.</p>;
  return (
    <div className="wr-checks">
      {connections.map((c) => (
        <CheckRow key={c.id} checked={draft.connection_ids.includes(c.id)} disabled={readOnly} title={c.name}
          onChange={(on) => editor.toggleConnection(c.id, on)} />
      ))}
    </div>
  );
}

export function RoleConnectionsSection({ editor, readOnly }: Part) {
  const { draft, set } = editor;
  return (
    <FormSection title="Write connections">
      <div className="wr-radios" role="radiogroup" aria-label="Write connections">
        <label><input type="radio" name="wr-delivery" checked={draft.delivery_connections === "all"} disabled={readOnly}
          onChange={() => set({ delivery_connections: "all" })} />All connections</label>
        <label><input type="radio" name="wr-delivery" checked={draft.delivery_connections === "selected"} disabled={readOnly}
          onChange={() => set({ delivery_connections: "selected" })} />Only these connections</label>
      </div>
      {draft.delivery_connections === "selected" ? <ConnectionChoices editor={editor} readOnly={readOnly} />
        : <p className="wr-hint">The role may write through every connection its tools reach.</p>}
    </FormSection>
  );
}

export function RoleCommandRulesSection({ editor, readOnly }: Part) {
  const { draft, set } = editor;
  return (
    <FormSection title="Command rules">
      <p className="wr-hint">{COMMAND_LAYERING_TEXT}</p>
      <div className="wr-grid-2">
        <label className="wr-field">
          <span>Allow (one pattern per line)</span>
          <textarea className="wr-mono-input" value={draft.allow} disabled={readOnly} rows={3} placeholder="npm run *"
            onChange={(event) => set({ allow: event.target.value })} />
        </label>
        <label className="wr-field">
          <span>Deny (one pattern per line)</span>
          <textarea className="wr-mono-input" value={draft.deny} disabled={readOnly} rows={3} placeholder="terraform *"
            onChange={(event) => set({ deny: event.target.value })} />
        </label>
      </div>
    </FormSection>
  );
}

export function RoleTrustSection({ editor, readOnly, role }: Part & { role: WorkRole }) {
  return (
    <FormSection title="Trust and status">
      <div className="wr-switch-row">
        <div className="wr-switch-row__text">
          <span className="wr-switch-row__title">Trusted</span>
          <span className="wr-hint">{role.trusted ? TRUSTED_BADGE : "Off: chat writes wait until a write plan is confirmed."}</span>
        </div>
        <ToggleSwitch on={role.trusted} label="Trusted" disabled={readOnly || editor.busy} testId="role-trusted"
          onChange={(on) => { editor.setTrustedError(null); editor.setTrustedStep({ on, reason: "" }); }} />
      </div>
      <div className="wr-switch-row">
        <div className="wr-switch-row__text">
          <span className="wr-switch-row__title">Active</span>
          <span className="wr-hint">An inactive role stays assigned but grants nothing.</span>
        </div>
        <ToggleSwitch on={editor.draft.is_active} label="Active" disabled={readOnly} testId="role-active"
          onChange={(on) => editor.set({ is_active: on })} />
      </div>
    </FormSection>
  );
}

export function RoleTrustedDialog({ editor, role }: { editor: RoleEditor; role: WorkRole }) {
  const step = editor.trustedStep!;
  return (
    <ConfirmDialog title={step.on ? `Turn Trusted on for ${role.name}?` : `Turn Trusted off for ${role.name}?`}
      tone={step.on ? "danger" : "neutral"} confirmLabel={step.on ? "Turn Trusted on" : "Turn Trusted off"}
      busy={editor.busy} error={editor.trustedError} confirmDisabled={step.on && !step.reason.trim()}
      onCancel={() => editor.setTrustedStep(null)} onConfirm={() => void editor.applyTrusted()}>
      <p>{trustedConfirmText(step.on)}</p>
      <label className="wr-field">
        <span>{step.on ? "Reason (required)" : "Reason (optional)"}</span>
        <textarea value={step.reason} rows={2} data-testid="role-trusted-reason"
          onChange={(event) => editor.setTrustedStep({ ...step, reason: event.target.value })} />
      </label>
    </ConfirmDialog>
  );
}
