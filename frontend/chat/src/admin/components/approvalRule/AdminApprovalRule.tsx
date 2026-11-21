import { useCallback, useEffect, useState } from "react";

import { loadApprovalRule, saveApprovalRule, type ApprovalRule, type ApprovalRuleValue } from "./approvalRule";

type Message = { ok: boolean; text: string };

const errorText = (error: unknown, action: string) => {
  const record = error && typeof error === "object" ? (error as { status?: unknown; message?: unknown }) : null;
  if (record?.status === 401 || record?.status === 403) return "Only platform admins can change the approval rule.";
  return `The approval rule could not be ${action}: ${typeof record?.message === "string" && record.message ? record.message : "the request failed"}.`;
};

const OPTION_HINTS: Record<ApprovalRuleValue, string> = {
  four_eyes: "Every governed change (policies, skills, prompts, routing rules) is published only after another admin approved it.",
  single_admin: "For installations with one admin: you approve and publish your own changes in one step. Each self-approval is recorded in the audit log.",
};

// Settings → Governance → "Approval rule": whether a governed change needs a second admin. Platform admins only;
// every change is audited by the server (who, when, old → new).
export function AdminApprovalRule({ isAdmin }: { isAdmin: boolean }) {
  const [rule, setRule] = useState<ApprovalRule | null>(null);
  const [draft, setDraft] = useState<ApprovalRuleValue>("four_eyes");
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);

  const load = useCallback(async () => {
    try {
      const loaded = await loadApprovalRule();
      setRule(loaded);
      setDraft(loaded.rule);
      setProblem(null);
    } catch (error) {
      setProblem(errorText(error, "loaded"));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const saved = await saveApprovalRule(draft);
      setRule(saved);
      setDraft(saved.rule);
      setMessage({ ok: true, text: `Approval rule saved: ${saved.label}.` });
    } catch (error) {
      setMessage({ ok: false, text: errorText(error, "saved") });
    } finally {
      setSaving(false);
    }
  };

  if (problem) return <p className="admin-panel__error" role="alert" data-testid="approval-rule-error">{problem}</p>;
  if (!rule) return <p className="admin-panel__hint" role="status">Loading the approval rule…</p>;

  return (
    <section className="admin-panel__card" aria-label="Approval rule" data-testid="approval-rule">
      <div className="admin-panel__section-header">
        <span>Approval rule</span>
      </div>
      <fieldset className="admin-panel__field" disabled={!isAdmin || saving}>
        <legend className="admin-panel__hint">Rule</legend>
        {rule.options.map((option) => (
          <label key={option.value} className="admin-panel__checkbox">
            <input type="radio" name="approval-rule" value={option.value} checked={draft === option.value}
              data-testid={`approval-rule-${option.value}`}
              onChange={() => { setDraft(option.value); setMessage(null); }} />
            <span>
              <strong>{option.label}</strong>
              <span className="admin-panel__hint"> — {OPTION_HINTS[option.value]}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {rule.selfApprovalSource === "dev_flag" ? (
        <p className="security-field-hint--attention" data-testid="approval-rule-dev-flag">
          This instance allows self-approval whatever the rule says; a platform operator can switch that off.
        </p>
      ) : null}
      {!isAdmin ? <p className="admin-panel__hint">Only platform admins can change the approval rule.</p> : null}
      <div>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          data-testid="approval-rule-save" disabled={!isAdmin || saving || draft === rule.rule} onClick={() => void save()}>
          {saving ? "Saving…" : "Save approval rule"}
        </button>
      </div>
      {message ? (
        <p className={message.ok ? "admin-panel__success" : "admin-panel__error"}
          role={message.ok ? "status" : "alert"} data-testid="approval-rule-message">
          {message.text}
        </p>
      ) : null}
    </section>
  );
}
