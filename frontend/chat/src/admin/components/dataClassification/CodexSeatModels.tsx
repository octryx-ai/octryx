import { useState } from "react";

import {
  CODEX_ALL_MODELS_TEXT, CODEX_SEAT_MODELS_EXPLANATION, CODEX_SEAT_MODELS_LABEL, codexModelsActions,
  codexModelsValueText, codexSeatModelsBody, codexSeatModelsSavedText,
} from "./codexSeatModelsModel";
import type { CodexModelsView } from "./codexSeatModelsModel";
import { saveSeatSetting } from "./dataClassificationApi";
import { SeatModelListEditor } from "./SeatModelListEditor";
import { seatSettingErrorText } from "./seatPolicyModel";
import type { SeatModelLimits } from "./seatPolicyModel";

type Message = { ok: boolean; text: string };

// The Codex seat's model list under the Codex seat switch. No list = every Codex model ("All Codex models
// (default)"); "Restrict to a list" opens the same editor as the Claude list, the first id saves the list. Restricting
// and removing tighten (Workspace admins); adding an id and "Allow all Codex models" loosen (`can_loosen` only).
export function CodexSeatModels({ projectId, view, limits, canEdit, canLoosen, busy, onSaved }: {
  projectId: string;
  view: CodexModelsView;
  limits: SeatModelLimits;
  canEdit: boolean;
  canLoosen: boolean;
  busy: boolean;
  onSaved: () => Promise<void>;
}) {
  const [saving, setSaving] = useState(false);
  const [restricting, setRestricting] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);
  const actions = codexModelsActions(view, canEdit, canLoosen);
  const locked = busy || saving;

  const save = async (models: string[] | null) => {
    const body = codexSeatModelsBody(models);
    setSaving(true);
    setMessage(null);
    try {
      await saveSeatSetting(projectId, body);
      await onSaved();
      setRestricting(false);
      setMessage({ ok: true, text: codexSeatModelsSavedText(body) });
      return true;
    } catch (error) {
      setMessage({ ok: false, text: seatSettingErrorText(error, "the Codex model list", limits) });
      return false;
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="seat-models seat-models--nested" data-testid="codex-seat-models">
      <div className="seat-models__head">
        <span className="seat-models__label">{CODEX_SEAT_MODELS_LABEL}</span>
        <span className="work-badge work-badge--neutral" data-testid="codex-seat-models-value">{codexModelsValueText(view)}</span>
      </div>
      <p className="admin-panel__hint">{CODEX_SEAT_MODELS_EXPLANATION}</p>
      {view.kind === "unknown" ? <p className="admin-panel__hint" data-testid="codex-seat-models-unknown">The Codex model list could not be loaded.</p> : null}
      {view.kind === "all" && !restricting ? (
        <div className="seat-models__all">
          <span data-testid="codex-seat-models-all">{CODEX_ALL_MODELS_TEXT}</span>
          {actions.restrict ? (
            <button type="button" className="admin-panel__action-btn" data-testid="codex-seat-models-restrict"
              disabled={locked} onClick={() => { setRestricting(true); setMessage(null); }}>Restrict to a list</button>
          ) : null}
        </div>
      ) : null}
      {view.kind === "all" && restricting ? (
        <>
          <SeatModelListEditor testId="codex-seat-models" models={[]} limits={limits} canRemove={false} canAdd
            locked={locked} saving={saving} placeholder="Codex model id, e.g. gpt-5.5" onSave={save} />
          <button type="button" className="admin-panel__action-btn" data-testid="codex-seat-models-cancel"
            disabled={locked} onClick={() => setRestricting(false)}>Cancel</button>
        </>
      ) : null}
      {view.kind === "list" ? (
        <>
          <SeatModelListEditor testId="codex-seat-models" models={view.models} limits={limits} canRemove={actions.remove}
            canAdd={actions.add} locked={locked} saving={saving} placeholder="Codex model id, e.g. gpt-5.5" onSave={save} />
          {actions.allowAll ? (
            <button type="button" className="admin-panel__action-btn" data-testid="codex-seat-models-allow-all"
              disabled={locked} onClick={() => void save(null)}>Allow all Codex models</button>
          ) : null}
        </>
      ) : null}
      {message ? (
        <p className={message.ok ? "admin-panel__success" : "workspace-classification__message"} role={message.ok ? "status" : "alert"}
          data-testid="codex-seat-models-message">{message.text}</p>
      ) : null}
    </div>
  );
}
