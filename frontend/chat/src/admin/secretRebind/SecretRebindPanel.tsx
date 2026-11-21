import { fieldLabel, secretRebindConfirmText, secretRebindSummary, SECRET_REBIND_REQUIRED } from "./secretRebindModel";
import type { SecretRebindFlow } from "./secretRebindFlow";

type SecretRebindPanelProps = {
  flow: SecretRebindFlow<unknown>;
  busy: boolean;
  onReenter: () => void;
  onConfirmStep: () => void;
  onConfirm: () => void;
  onBack: () => void;
};

// The inline refusal with exactly two ways forward: re-enter the kept secret(s), or confirm in a second explicit
// click that the stored secret may go to the new target. Field names only; no value, URL or host is shown.
export function SecretRebindPanel({ flow, busy, onReenter, onConfirmStep, onConfirm, onBack }: SecretRebindPanelProps) {
  const { refusal, step } = flow;
  return (
    <div className="security-refusal security-refusal--attention" role="alert">
      <div className="security-refusal__head">
        <strong>Secret rebind required</strong>
        <code className="security-refusal__code">{SECRET_REBIND_REQUIRED}</code>
      </div>
      <p className="security-refusal__text">{secretRebindSummary(refusal)}</p>
      <dl className="security-refusal__fields">
        <dt>Changed target</dt>
        <dd>{refusal.changedTargetFields.map(fieldLabel).join(", ") || "—"}</dd>
        <dt>Kept secret</dt>
        <dd>{refusal.keptFields.map(fieldLabel).join(", ") || "—"}</dd>
      </dl>
      {step === "choose" ? (
        <div className="security-refusal__actions">
          <button type="button" className="admin-panel__action-btn" onClick={onConfirmStep}>
            Send the stored secret to the new host…
          </button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={onReenter}>
            Re-enter secret
          </button>
        </div>
      ) : null}
      {step === "reenter" ? (
        <>
          <p className="security-refusal__text">
            Enter a new value for {refusal.keptFields.map(fieldLabel).join(", ")} above, then save.
          </p>
          {flow.error ? <p className="security-refusal__error">{flow.error}</p> : null}
          <div className="security-refusal__actions">
            <button type="button" className="admin-panel__action-btn" onClick={onBack}>Back</button>
          </div>
        </>
      ) : null}
      {step === "confirm" ? (
        <>
          <p className="security-refusal__text security-refusal__text--strong">{secretRebindConfirmText(refusal)}</p>
          <div className="security-refusal__actions">
            <button type="button" className="admin-panel__action-btn" onClick={onBack} disabled={busy}>Cancel</button>
            <button type="button" className="admin-panel__danger-btn" onClick={onConfirm} disabled={busy}>
              {busy ? "Saving…" : "Confirm: send the stored secret"}
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
