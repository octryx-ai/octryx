// Editable draft of one Workspace capability binding: reset whenever the binding changes, saved as one patch.
import { useEffect, useState } from "react";

import type {
  WorkspaceBindingUpdatePayload,
  WorkspaceCapabilityBinding,
} from "../../../types/workspaceCompositionTypes";
import {
  formatJsonRecord,
  formatStringList,
  parseJsonRecord,
  parseStringList,
} from "./formUtils";

type DraftValues = {
  displayName: string;
  bindingStatus: string;
  isEnabled: boolean;
  isDefault: boolean;
  intentScopesDraft: string;
  bindingConfigDraft: string;
  policyConfigDraft: string;
};

/** The update patch of a draft; throws when a JSON field does not parse. */
function bindingPatch(binding: WorkspaceCapabilityBinding, draft: DraftValues): WorkspaceBindingUpdatePayload {
  const { bindingStatus } = draft;
  return {
    display_name: draft.displayName.trim() || binding.binding_key,
    binding_status: bindingStatus === "hidden" ? "hidden" : "active",
    is_enabled: draft.isEnabled,
    is_default: draft.isDefault,
    intent_scopes: parseStringList(draft.intentScopesDraft),
    binding_config: parseJsonRecord(draft.bindingConfigDraft, "Assignment config"),
    policy_config: parseJsonRecord(draft.policyConfigDraft, "Assignment policy config"),
  };
}

export function useBindingDraft(
  binding: WorkspaceCapabilityBinding,
  onSave: (bindingId: string, patch: WorkspaceBindingUpdatePayload) => Promise<unknown>,
) {
  const [displayName, setDisplayName] = useState(
    binding.display_name || binding.binding_key,
  );
  const [bindingStatus, setBindingStatus] = useState(binding.binding_status);
  const [isEnabled, setIsEnabled] = useState(Boolean(binding.is_enabled));
  const [isDefault, setIsDefault] = useState(Boolean(binding.is_default));
  const [intentScopesDraft, setIntentScopesDraft] = useState(
    formatStringList(binding.intent_scopes),
  );
  const [bindingConfigDraft, setBindingConfigDraft] = useState(
    formatJsonRecord(binding.binding_config),
  );
  const [policyConfigDraft, setPolicyConfigDraft] = useState(
    formatJsonRecord(binding.policy_config),
  );
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    setDisplayName(binding.display_name || binding.binding_key);
    setBindingStatus(binding.binding_status);
    setIsEnabled(Boolean(binding.is_enabled));
    setIsDefault(Boolean(binding.is_default));
    setIntentScopesDraft(formatStringList(binding.intent_scopes));
    setBindingConfigDraft(formatJsonRecord(binding.binding_config));
    setPolicyConfigDraft(formatJsonRecord(binding.policy_config));
    setFormError(null);
  }, [binding]);

  const values = { displayName, bindingStatus, isEnabled, isDefault, intentScopesDraft, bindingConfigDraft, policyConfigDraft };
  const handleSave = async () => {
    try {
      const patch = bindingPatch(binding, values);
      setFormError(null);
      await onSave(binding.id, patch);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Failed to save project assignment.");
    }
  };

  return {
    ...values, setDisplayName, setBindingStatus, setIsEnabled, setIsDefault, setIntentScopesDraft,
    setBindingConfigDraft, setPolicyConfigDraft, formError, handleSave,
  };
}

export type BindingDraft = ReturnType<typeof useBindingDraft>;
