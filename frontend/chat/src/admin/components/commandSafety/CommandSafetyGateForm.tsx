import { Fragment, type CSSProperties } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { ChipListEditor, ToggleRow } from "../settingsKit/SettingsKit";
import type { GateSettings, Lists, LlmRisk } from "./commandSafetyModel";
import { OUTCOME_TEXT } from "./commandSafetyModel";

const LIST_ROWS: [keyof Lists, string][] = [["commands", "Commands"], ["git", "git"], ["kubectl", "kubectl"]];

/** The platform's defaults not in the list now (removed by an admin, or just now): new defaults still arrive. */
const removedDefaults = (value: GateSettings, key: keyof Lists) =>
  (value.origins?.[key]?.defaults ?? []).filter((item) => !value.lists[key].includes(item));

// The gate itself: checks, AI risk review, command lists. The platform page and a Workspace's
// override use this same form.
export function CommandSafetyGateForm({ value, onChange, disabled = false }: {
  value: GateSettings;
  onChange: (next: GateSettings) => void;
  disabled?: boolean;
}) {
  const { openAdminTab } = useAdminNavigation();
  const setLlm = (patch: Partial<LlmRisk>) => onChange({ ...value, llm: { ...value.llm, ...patch } });
  const setList = (key: keyof Lists, next: string[]) => onChange({ ...value, lists: { ...value.lists, [key]: next } });
  const llmOn = value.checks.some((check) => check.key === "llm_risk" && check.enabled);
  const number = (field: "timeout_seconds" | "review_threshold" | "deny_threshold", label: string, min: number, max: number) => (
    <label className="admin-panel__field"><span>{label}</span>
      <input type="number" min={min} max={max} className="sk-num" value={String(value.llm[field])} disabled={disabled}
        data-testid={`command-${field}`}
        onChange={(event) => setLlm({ [field]: event.target.value === "" ? Number.NaN : Number(event.target.value) })} />
    </label>
  );
  const bar = { "--sk-ask": `${value.llm.review_threshold}%`, "--sk-block": `${value.llm.deny_threshold}%` } as CSSProperties;

  return (
    <>
      <section className="admin-panel__card" aria-label="Checks">
        <div className="admin-panel__section-header"><span>Checks</span><span className="sk-muted">order does not matter</span></div>
        {value.checks.map((check) => (
          <ToggleRow key={check.key} title={check.label} on={check.enabled} disabled={disabled} testId={`command-check-${check.key}`}
            sub={(
              <>
                {check.description}
                <span className="sk-chips sk-chips--spaced">
                  {check.outcomes.map((outcome) => (
                    <span key={outcome} className={`sk-out sk-out--${OUTCOME_TEXT[outcome]?.tone ?? "none"}`}>{OUTCOME_TEXT[outcome]?.text ?? outcome}</span>
                  ))}
                </span>
              </>
            )}
            onChange={(enabled) => onChange({ ...value, checks: value.checks.map((item) => (item.key === check.key ? { ...item, enabled } : item)) })} />
        ))}
      </section>
      <section className="admin-panel__card" aria-label="AI risk review">
        <div className="admin-panel__section-header">
          <span>AI risk review</span>
          {!llmOn ? <span className="work-badge work-badge--neutral">Off</span> : null}
        </div>
        <div className="admin-panel__form-grid">
          <div className="admin-panel__field"><span>Model</span>
            <span className="sk-hint">
              {value.llm.review_model || "Platform priority #1"} ·{" "}
              <button type="button" className="sk-link" onClick={() => openAdminTab("modelOrder")}>Security review model</button>
            </span>
          </div>
          {number("timeout_seconds", "Timeout (seconds, 1–60)", 1, 60)}
          {number("review_threshold", "Ask a person from score", 0, 100)}
          {number("deny_threshold", "Block from score", 0, 100)}
        </div>
        <div>
          <div className="sk-bar" style={bar} />
          <div className="sk-bar-legend">
            <span>0 allow</span><span>{value.llm.review_threshold} ask</span><span>{value.llm.deny_threshold} block</span><span>100</span>
          </div>
        </div>
        <p className="sk-hint">If the model is unavailable or not allowed for the Workspace, the command waits for a person.</p>
      </section>
      <section className="admin-panel__card" aria-label="Command lists">
        <div className="admin-panel__section-header"><span>Always blocked</span></div>
        <ChipListEditor label="Always blocked" values={value.lists.always_deny_patterns} tone="danger" disabled={disabled}
          testId="command-deny" onChange={(next) => setList("always_deny_patterns", next)} />
        <div className="admin-panel__section-header"><span>Allowed without asking in read-only runs</span></div>
        <dl className="work-detail__kv">
          {LIST_ROWS.map(([key, label]) => (
            <Fragment key={key}>
              <dt>{label}</dt>
              <dd>
                <ChipListEditor label={label} values={value.lists[key]} disabled={disabled} testId={`command-${key}`}
                  defaults={value.origins?.[key]?.defaults} onChange={(next) => setList(key, next)} />
                {removedDefaults(value, key).length ? (
                  <p className="sk-hint" data-testid={`command-${key}-removed`}>
                    Defaults removed here: {removedDefaults(value, key).join(", ")}. Add one again to allow it.
                  </p>
                ) : null}
              </dd>
            </Fragment>
          ))}
          <dt>Risky shell operators</dt>
          <dd><ChipListEditor label="Risky shell operators" values={value.lists.operators} disabled={disabled} testId="command-operators"
            onChange={(next) => setList("operators", next)} /></dd>
        </dl>
      </section>
    </>
  );
}
