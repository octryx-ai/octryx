import { useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { Checks } from "../settingsKit/SettingsKit";
import type { CatalogLevel } from "./classificationLevelCatalog";
import type { EffectRule, EffectType } from "./classificationEffectsModel";
import { effectPolicyText, effectRuleId, effectRuleSentence } from "./classificationEffectsModel";

type Step = 1 | 2 | 3;
const STEPS: [Step, string][] = [[1, "Effect"], [2, "Where"], [3, "Preview"]];

type RuleStepTabsProps = { step: Step; effect: EffectType | null; setStep: (step: Step) => void };

function RuleStepTabs({ step, effect, setStep }: RuleStepTabsProps) {
  return (
    <div className="sk-steps">
      {STEPS.map(([value, label]) => (
        <button key={value} type="button" className="sk-step" aria-current={step === value ? "step" : undefined}
          disabled={value > 1 && !effect} onClick={() => setStep(value)}>
          <span className="sk-step__n">{value}</span>{label}
        </button>
      ))}
    </div>
  );
}

type RuleFooterProps = { step: Step; effect: EffectType | null; duplicate: boolean; setStep: (step: Step) => void; next: () => void; onClose: () => void };

function RuleFooter({ step, effect, duplicate, setStep, next, onClose }: RuleFooterProps) {
  return (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
      <button type="button" className="admin-panel__action-btn" disabled={step === 1} onClick={() => setStep((step - 1) as Step)}>Back</button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="rule-next"
        disabled={!effect || (step === 3 && duplicate)} onClick={next}>
        {step === 3 ? "Add to draft" : "Next"}
      </button>
    </>
  );
}

type EffectStepProps = { catalog: EffectType[]; effect: EffectType | null; pick: (item: EffectType) => void; onWritePolicy: () => void };

function EffectStep({ catalog, effect, pick, onWritePolicy }: EffectStepProps) {
  return (
    <>
      <p className="sk-hint">Pick what the rule controls. Only effects the platform can enforce are offered.</p>
      <div className="sk-option-grid" role="radiogroup" aria-label="Effect">
        {catalog.map((item) => (
          <label key={item.key} className="admin-option-card">
            <input type="radio" name="classification-effect" checked={effect?.key === item.key} disabled={!item.enforced}
              data-testid={`rule-effect-${item.key}`} onChange={() => pick(item)} />
            <span className="admin-option-card__body">
              <span className="admin-option-card__title">{item.label}</span>
              <span className="admin-option-card__desc">{item.description}</span>
              {!item.enforced ? <span className="sk-muted">Not available yet</span> : null}
            </span>
          </label>
        ))}
      </div>
      <p className="sk-hint">
        Something else? <button type="button" className="sk-link" onClick={onWritePolicy}>Write a policy</button>.
      </p>
    </>
  );
}

type WhereStepProps = {
  effect: EffectType;
  levels: CatalogLevel[];
  servers: string[];
  param: string;
  setParam: (param: string) => void;
  fromLevel: string;
  setFromLevel: (level: string) => void;
};

function WhereStep({ effect, levels, servers, param, setParam, fromLevel, setFromLevel }: WhereStepProps) {
  return (
    <>
      <label className="admin-panel__field"><span>Setting</span>
        <select value={param} data-testid="rule-param" onChange={(event) => setParam(event.target.value)}>
          {effect.param === "server" ? (
            <>
              <option value="*">Every MCP server: off</option>
              {servers.map((server) => <option key={server} value={server}>{server}: off</option>)}
            </>
          ) : <option value="off">Off</option>}
        </select>
      </label>
      <label className="admin-panel__field"><span>Applies at and above</span>
        <select value={fromLevel} data-testid="rule-from" onChange={(event) => setFromLevel(event.target.value)}>
          {levels.map((level) => <option key={level.key} value={level.key}>{level.label}</option>)}
        </select>
      </label>
      <p className="sk-note">Below that level the rule does not restrict anything. Workspaces may still make it stricter.</p>
    </>
  );
}

type PreviewStepProps = {
  rule: EffectRule;
  effect: EffectType | null;
  levels: CatalogLevel[];
  sentence: string;
  duplicate: boolean;
  affected: number | null;
};

function PreviewStep({ rule, effect, levels, sentence, duplicate, affected }: PreviewStepProps) {
  return (
    <>
      <p className="sk-sentence" data-testid="rule-sentence">{sentence}</p>
      <div className="work-detail__section">
        <h3>Generated policy</h3>
        <pre className="sk-code">{effectPolicyText(rule, levels, sentence)}</pre>
      </div>
      <div className="work-detail__section">
        <h3>Impact</h3>
        <Checks items={[
          ...(duplicate ? [{ state: "bad" as const, text: "This rule is already in the draft" }] : []),
          { state: "info", text: affected === null ? "Workspaces affected: loading…" : `${affected} ${affected === 1 ? "Workspace" : "Workspaces"} affected` },
          { state: "info", text: `Enforced at: ${effect?.enforcedAt}` },
          { state: "info", text: "Saved policy test cases run on submit; published only after review under the Approval rule" },
        ]} />
      </div>
    </>
  );
}

// Add rule, three steps: the effect from the closed catalog (only effects
// the platform can enforce can be picked), where it applies (a setting and the level it applies from), and a preview
// (the rule as a sentence, its generated policy, the Workspaces it touches).
export function ClassificationAddRuleDrawer({ catalog, levels, servers, existing, workspaceLevels, levelLabel, onClose, onSave }: {
  catalog: EffectType[];
  levels: CatalogLevel[];
  servers: string[];
  existing: EffectRule[];
  workspaceLevels: (string | null)[] | null;
  levelLabel: (key: string) => string;
  onClose: () => void;
  onSave: (rule: EffectRule) => void;
}) {
  const { openAdminTab } = useAdminNavigation();
  const [step, setStep] = useState<Step>(1);
  const [effect, setEffect] = useState<EffectType | null>(null);
  const [param, setParam] = useState("off");
  const middle = levels[Math.floor(levels.length / 2)]?.key ?? levels[0]?.key ?? "";
  const [fromLevel, setFromLevel] = useState(middle);

  const rule: EffectRule | null = effect ? { effect: effect.key, param, from_level: fromLevel } : null;
  const duplicate = rule ? existing.some((item) => effectRuleId(item) === effectRuleId(rule)) : false;
  const sentence = rule ? effectRuleSentence(rule, catalog, levelLabel) : "";
  const fromRank = levels.find((level) => level.key === fromLevel)?.rank ?? 0;
  const affected = workspaceLevels?.filter((key) => (levels.find((level) => level.key === key)?.rank ?? -1) >= fromRank).length ?? null;
  const pick = (item: EffectType) => {
    setEffect(item);
    setParam(item.param === "server" ? (servers[0] ?? "*") : "off");
  };
  const next = () => {
    if (step < 3) setStep((step + 1) as Step);
    else if (rule) onSave(rule);
  };

  return (
    <SettingsDrawer eyebrow="Classification · Draft" title="Add rule" size="detail" onClose={onClose}
      footer={(
        <RuleFooter step={step} effect={effect} duplicate={duplicate} setStep={setStep} next={next} onClose={onClose} />
      )}>
      <div className="sk-page" data-testid="classification-add-rule">
        <RuleStepTabs step={step} effect={effect} setStep={setStep} />
        {step === 1 ? (
          <EffectStep catalog={catalog} effect={effect} pick={pick} onWritePolicy={() => openAdminTab("cedarPolicies")} />
        ) : null}
        {step === 2 && effect ? (
          <WhereStep effect={effect} levels={levels} servers={servers} param={param} setParam={setParam} fromLevel={fromLevel}
            setFromLevel={setFromLevel} />
        ) : null}
        {step === 3 && rule ? (
          <PreviewStep rule={rule} effect={effect} levels={levels} sentence={sentence} duplicate={duplicate} affected={affected} />
        ) : null}
      </div>
    </SettingsDrawer>
  );
}

// An added rule's own drawer: the sentence, its generated policy, and remove (into the draft).
export function ClassificationRuleDetailDrawer({ rule, sentence, policy, editable, onClose, onRemove }: {
  rule: EffectRule;
  sentence: string;
  policy: string;
  editable: boolean;
  onClose: () => void;
  onRemove: () => void;
}) {
  return (
    <SettingsDrawer eyebrow="Classification · Added rule" title={sentence.split(",")[1]?.trim() ?? rule.effect} size="edit" onClose={onClose}
      footer={(
        <>
          {editable ? <button type="button" className="admin-panel__action-btn admin-panel__danger-btn" data-testid="rule-remove" onClick={onRemove}>Remove rule</button> : null}
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
        </>
      )}>
      <div className="sk-page">
        <p className="sk-sentence">{sentence}</p>
        <div className="work-detail__section"><h3>Generated policy</h3><pre className="sk-code">{policy}</pre></div>
      </div>
    </SettingsDrawer>
  );
}
