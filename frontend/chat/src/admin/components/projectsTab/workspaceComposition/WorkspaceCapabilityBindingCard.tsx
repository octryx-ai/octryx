// One Workspace capability binding as an editable card: header badges, the draft fields and the save action.
import type {
  WorkspaceBindingUpdatePayload,
  WorkspaceCapabilityBinding,
} from "../../../types/workspaceCompositionTypes";
import { useBindingDraft, type BindingDraft } from "./useBindingDraft";

type WorkspaceCapabilityBindingCardProps = {
  binding: WorkspaceCapabilityBinding;
  isSaving: boolean;
  onSave: (
    bindingId: string,
    patch: WorkspaceBindingUpdatePayload,
  ) => Promise<unknown>;
};

function BindingCardHeader({ binding }: { binding: WorkspaceCapabilityBinding }) {
  const capabilityName =
    binding.capability_type?.name ||
    binding.display_name ||
    binding.binding_key;
  const capabilityDescription =
    binding.capability_type?.description ||
    "No assignment description available.";
  return (
    <div className="connector-card__header">
      <div className="connector-card__info">
        <div className="connector-card__name-row">
          <div className="connector-card__name">{capabilityName}</div>
          <span className="connector-card__meta-badge">
            {binding.capability_kind}
          </span>
          <span className="connector-card__meta-badge">
            {binding.capability_type?.key || binding.binding_key}
          </span>
          <span className="connector-card__meta-badge">
            {binding.binding_status}
          </span>
          {binding.is_default ? (
            <span className="connector-card__meta-badge">default</span>
          ) : null}
        </div>
        <div
          className={`connector-card__status ${binding.is_enabled ? "connector-card__status--ok" : ""}`}
        >
          {binding.is_enabled ? "Enabled" : "Disabled"}
        </div>
        <div className="connector-card__meta">{capabilityDescription}</div>
      </div>
    </div>
  );
}

function BindingDraftFields({ binding, draft }: { binding: WorkspaceCapabilityBinding; draft: BindingDraft }) {
  const {
    displayName, setDisplayName, bindingStatus, setBindingStatus, isEnabled, setIsEnabled, isDefault, setIsDefault,
    intentScopesDraft, setIntentScopesDraft, bindingConfigDraft, setBindingConfigDraft, policyConfigDraft,
    setPolicyConfigDraft,
  } = draft;
  return (
    <div className="admin-form-grid admin-form-grid--dual">
      <label className="admin-form-field">
        <span>Display name</span>
        <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
      </label>
      <label className="admin-form-field">
        <span>Status</span>
        <select value={bindingStatus} onChange={(event) => setBindingStatus(event.target.value)}>
          <option value="active">Active</option>
          <option value="hidden">Hidden</option>
        </select>
      </label>
      <label className="admin-form-field">
        <span>Intent scopes</span>
        <textarea rows={3} value={intentScopesDraft} onChange={(event) => setIntentScopesDraft(event.target.value)}
          placeholder="documentation&#10;diagnosis" />
      </label>
      <div className="admin-form-field">
        <span>Binding state</span>
        <label className="admin-checkbox-row">
          <input type="checkbox" checked={isEnabled} onChange={(event) => {
            const nextEnabled = event.target.checked;
            setIsEnabled(nextEnabled);
            if (!nextEnabled) {
              setIsDefault(false);
            }
          }} />
          <span>Enabled</span>
        </label>
        <label className="admin-checkbox-row">
          <input type="checkbox" checked={isDefault} disabled={!isEnabled || bindingStatus === "hidden"}
            onChange={(event) => setIsDefault(event.target.checked)} />
          <span>Default for {binding.capability_kind}</span>
        </label>
      </div>
      <label className="admin-form-field" style={{ gridColumn: "1 / -1" }}>
        <span>Assignment config</span>
        <textarea rows={6} value={bindingConfigDraft} onChange={(event) => setBindingConfigDraft(event.target.value)} />
      </label>
      <label className="admin-form-field" style={{ gridColumn: "1 / -1" }}>
        <span>Assignment policy config</span>
        <textarea rows={6} value={policyConfigDraft} onChange={(event) => setPolicyConfigDraft(event.target.value)} />
      </label>
    </div>
  );
}

export function WorkspaceCapabilityBindingCard({
  binding,
  isSaving,
  onSave,
}: WorkspaceCapabilityBindingCardProps) {
  const draft = useBindingDraft(binding, onSave);
  const { formError, handleSave } = draft;

  return (
    <div className="connector-card connector-card--configured">
      <BindingCardHeader binding={binding} />
      <div className="task-item__runs" style={{ paddingTop: 0 }}>
        <BindingDraftFields binding={binding} draft={draft} />
        {formError ? (
          <div className="admin-panel__empty-state">{formError}</div>
        ) : null}
        <div className="admin-inline-actions" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => void handleSave()}
            disabled={isSaving}
          >
            {isSaving ? "Saving…" : "Save assignment"}
          </button>
          {binding.source_entity_type ? (
            <span className="task-item__badge">
              source: {binding.source_entity_type}
            </span>
          ) : null}
          {binding.capability_type?.lifecycle_status ? (
            <span className="task-item__badge task-item__badge--secondary">
              lifecycle: {binding.capability_type.lifecycle_status}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
