import { useState } from "react";

import { saveSeatSetting } from "./dataClassificationApi";
import { SeatModelListEditor } from "./SeatModelListEditor";
import type { WorkspaceClassification } from "./dataClassificationTypes";
import {
  ALLOWS_GOVERNED_EXPLANATION, ALLOWS_GOVERNED_LABEL, REQUIRES_GOVERNED_EXPLANATION, REQUIRES_GOVERNED_LABEL,
  SEAT_MODELS_EXPLANATION, SEAT_MODELS_LABEL, allowsGovernedBody, requiresGovernedBody,
  seatFlagValueText, seatModelsBody, seatModelsValueText, seatSettingErrorText, seatSettingSavedText,
  invalidSettingWarnings, seatFieldOfError, seatSettingsDisabled,
} from "./seatPolicyModel";
import type { SeatField, SeatPolicySettings as Settings, SeatSettingBody } from "./seatPolicyModel";

type Field = SeatField;
type Message = { field: Field; ok: boolean; text: string };

const WHAT: Record<Field, string> = {
  requiresGoverned: "the company-models-only setting",
  models: "the seat model list",
  allowsGoverned: "the company models setting for seat sessions",
};

// Three more seat keys under the two seat switches (Data classification card): "Only company models through the
// gateway", the Claude seat's model list, and company models in seat sessions, in this order. Each change saves one key at once
// (one PUT, one audit row); a refusal shows in words at its field. `busy` is the card's own save in progress.
// Loosening needs the server's `can_loosen` (seatBoundLocks); a Workspace admin or owner only tightens.
export function SeatPolicySettings({ projectId, model, settings, busy, onSaved }: {
  projectId: string;
  model: WorkspaceClassification;
  settings: Settings;
  busy: boolean;
  onSaved: () => Promise<void>;
}) {
  const [saving, setSaving] = useState<Field | null>(null);
  const [message, setMessage] = useState<Message | null>(null);
  const disabled = seatSettingsDisabled(model, settings);
  const locked = busy || saving !== null;
  const models = settings.models ?? [];

  const save = async (field: Field, body: SeatSettingBody) => {
    setSaving(field);
    setMessage(null);
    try {
      await saveSeatSetting(projectId, body);
      await onSaved();
      setMessage({ field, ok: true, text: seatSettingSavedText(body) });
      return true;
    } catch (error) {
      const at = seatFieldOfError(error, field);
      setMessage({ field: at, ok: false, text: seatSettingErrorText(error, WHAT[at], settings.limits) });
      return false;
    } finally {
      setSaving(null);
    }
  };

  const feedback = (field: Field) => (message?.field === field ? (
    <p className={message.ok ? "admin-panel__success" : "workspace-classification__message"} role={message.ok ? "status" : "alert"}
      data-testid={`seat-setting-message-${field}`}>{message.text}</p>
  ) : null);

  return (
    <>
      {invalidSettingWarnings(settings.invalid).map((line) => (
        <p key={line} className="security-field-hint--attention" role="note" data-testid="seat-invalid-setting">{line}</p>
      ))}
      <div className="workspace-classification__seat" data-testid="seat-requires-governed">
        <label className="admin-panel__checkbox">
          <input type="checkbox" data-testid="seat-requires-governed-toggle" checked={settings.requiresGoverned === true}
            disabled={locked || disabled.requiresGoverned}
            onChange={(event) => void save("requiresGoverned", requiresGovernedBody(event.target.checked))} />
          {REQUIRES_GOVERNED_LABEL}
          <span className="work-badge work-badge--neutral" data-testid="seat-requires-governed-value">{seatFlagValueText(settings.requiresGoverned)}</span>
        </label>
        <p className="admin-panel__hint">{REQUIRES_GOVERNED_EXPLANATION}</p>
        {feedback("requiresGoverned")}
      </div>
      <div className="workspace-classification__seat" data-testid="seat-models">
        <div className="seat-models__head">
          <span className="seat-models__label">{SEAT_MODELS_LABEL}</span>
          <span className="work-badge work-badge--neutral" data-testid="seat-models-value">{seatModelsValueText(settings)}</span>
        </div>
        <p className="admin-panel__hint">{SEAT_MODELS_EXPLANATION}</p>
        {settings.models === null ? <p className="admin-panel__hint" data-testid="seat-models-unknown">The model list could not be loaded.</p> : (
          <SeatModelListEditor testId="seat-models" models={models} limits={settings.limits} canRemove={!disabled.models}
            canAdd={!disabled.addModels} locked={locked} saving={saving === "models"}
            placeholder="Model id, e.g. claude-haiku-5" onSave={(next) => save("models", seatModelsBody(next))} />
        )}
        {feedback("models")}
      </div>
      <div className="workspace-classification__seat" data-testid="seat-allows-governed">
        <label className="admin-panel__checkbox">
          <input type="checkbox" data-testid="seat-allows-governed-toggle" checked={settings.allowsGoverned === true}
            disabled={locked || disabled.allowsGoverned}
            onChange={(event) => void save("allowsGoverned", allowsGovernedBody(event.target.checked))} />
          {ALLOWS_GOVERNED_LABEL}
          <span className="work-badge work-badge--neutral" data-testid="seat-allows-governed-value">{seatFlagValueText(settings.allowsGoverned)}</span>
        </label>
        <p className="admin-panel__hint">{ALLOWS_GOVERNED_EXPLANATION}</p>
        {feedback("allowsGoverned")}
      </div>
    </>
  );
}
