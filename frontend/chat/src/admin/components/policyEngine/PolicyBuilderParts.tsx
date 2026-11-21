import type { ReactNode } from "react";

import { ContentPane } from "./BuilderContentPane";
import { ContentChecks, OutcomePane } from "./BuilderOutcomePane";
import { BasicsPane, ExceptionsPane, WherePane, WhoPane } from "./BuilderPanes";
import { WhatPane } from "./BuilderWhatPane";
import { CedarCode } from "./CedarCode";
import { PolicySentence } from "./PolicySentence";
import { EMPTY_DETECTORS } from "./builderContentModel";
import type { DetectorCatalog } from "./builderContentModel";
import { stepDone } from "./policyBuilderModel";
import type { BuilderModel, StepId } from "./policyBuilderModel";
import type { Catalog, PickerEntities } from "./policyCatalogModel";
import type { Preview, builderStatus } from "./usePolicyBuilder";

type Status = ReturnType<typeof builderStatus>;
type Pane = { model: BuilderModel; onChange: (next: BuilderModel) => void; catalog: Catalog; entities: PickerEntities; required: string[] };

// The stepper: one button per step, done steps marked, the hint under the current one.
export function BuilderSteps({ status, model, setStep }: { status: Status; model: BuilderModel; setStep: (step: StepId) => void }) {
  const { steps, current, index } = status;
  return (
    <nav className="policies__steps" aria-label="Builder steps">
      {steps.map((item, position) => (
        <div key={item.id}>
          <button type="button" data-testid={`builder-step-${item.id}`} aria-current={item.id === current ? "step" : undefined}
            className={`policies__step${item.id === current ? " policies__step--active" : ""}${position < index || (position > 0 && position < steps.length - 1 && stepDone(model, item.id)) ? " policies__step--done" : ""}`}
            onClick={() => setStep(item.id)}>
            <span className="policies__step-n">{position + 1}</span>{item.label}
          </button>
          {item.id === current ? <p className="policies__step-hint" data-testid="builder-step-hint">{item.hint}</p> : null}
        </div>
      ))}
    </nav>
  );
}

// The current step's pane; the check step also lists the content checks when the policy checks content.
export function BuilderStepPane({ current, pane, idLocked, onIdEdited, detectors, previewDelay, checkStep, preview, content }: {
  current: StepId;
  pane: Pane;
  idLocked: boolean;
  onIdEdited: () => void;
  detectors: DetectorCatalog | null;
  previewDelay: number;
  checkStep: (model: BuilderModel, preview: { valid: boolean; text: string }) => ReactNode;
  preview: Preview;
  content: string | null;
}) {
  const { model, entities } = pane;
  return (
    <div>
      {current === "basics" ? <BasicsPane {...pane} idLocked={idLocked} onIdEdited={onIdEdited} /> : null}
      {current === "who" ? <WhoPane {...pane} /> : null}
      {current === "what" ? <WhatPane {...pane} /> : null}
      {current === "content" ? <ContentPane {...pane} detectors={detectors ?? EMPTY_DETECTORS} previewDelay={previewDelay} /> : null}
      {current === "where" ? <WherePane {...pane} /> : null}
      {current === "outcome" ? <OutcomePane {...pane} detectors={detectors ?? EMPTY_DETECTORS} /> : null}
      {current === "exceptions" ? <ExceptionsPane {...pane} /> : null}
      {current === "check" ? checkStep(model, { valid: preview.valid, text: preview.text }) : null}
      {current === "check" && content ? <ContentChecks model={model} valid={preview.valid} aliases={entities.modelAliases} detectors={detectors ?? EMPTY_DETECTORS} /> : null}
    </div>
  );
}

// The read-only Cedar under "Advanced", with the confirmed conversion to a hand-written policy.
function BuilderCedar({ preview, confirmCedar, setConfirmCedar, onEditAsCedar, schemaVersion }: {
  preview: Preview;
  confirmCedar: boolean;
  setConfirmCedar: (value: boolean) => void;
  onEditAsCedar: (text: string) => void;
  schemaVersion: Catalog["schemaVersion"];
}) {
  return (
    <details className="policies__advanced" data-testid="builder-cedar-details">
      <summary>Advanced · Cedar (generated, read-only)</summary>
      {preview.text ? <CedarCode text={preview.text} testId="builder-cedar" /> : <pre className="policies__code"><span className="policies__code-comment">// nothing to generate yet</span></pre>}
      <div className="policies__row">
        {confirmCedar ? (
          <>
            <span className="policies__src">It becomes hand-written and is edited in the Cedar editor from then on.</span>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="builder-cedar-confirm"
              onClick={() => onEditAsCedar(preview.text.replace('@builder("1")\n', ""))}>Convert</button>
            <button type="button" className="admin-panel__action-btn" onClick={() => setConfirmCedar(false)}>Cancel</button>
          </>
        ) : (
          <button type="button" className="admin-panel__action-btn" data-testid="builder-edit-as-cedar" disabled={!preview.text}
            title="Converts it to a hand-written policy" onClick={() => setConfirmCedar(true)}>Edit as Cedar…</button>
        )}
        <span className="policies__src">Validated against schema {schemaVersion}</span>
      </div>
    </details>
  );
}

// "This policy": the effect, the live sentence, the warnings, the server issues and the generated Cedar.
export function BuilderSide({ status, preview, content, confirmCedar, setConfirmCedar, onEditAsCedar, schemaVersion }: {
  status: Status;
  preview: Preview;
  content: string | null;
  confirmCedar: boolean;
  setConfirmCedar: (value: boolean) => void;
  onEditAsCedar: (text: string) => void;
  schemaVersion: Catalog["schemaVersion"];
}) {
  const { badge, routeWarning, requiredShown, issues } = status;
  return (
    <aside className="policies__side">
      <section className="admin-panel__card policies__pane">
        <div className="admin-panel__section-header"><span>This policy</span><span className={`work-badge work-badge--${badge.tone}`} data-testid="builder-effect">{badge.label}</span></div>
        {preview.sentence.length ? <PolicySentence segments={preview.sentence} testId="builder-sentence" />
          : <span className="policies__sub" data-testid="builder-sentence-empty">{content ? "Pick what the content must contain — the sentence appears here." : "Pick who, what and where — the sentence appears here."}</span>}
        {routeWarning ? <div className="policies__warn" data-testid="builder-route-warning">{routeWarning}</div> : null}
        {requiredShown.map((item) => <div key={item.field} className="policies__warn" data-testid="builder-placeholder">Required: <b>{item.label}</b> — {item.hint}</div>)}
        {preview.warnings.map((warning) => <div key={warning.code + warning.message} className="policies__warn" data-testid="builder-warning">{warning.message}</div>)}
        {issues.length ? (
          <ul className="workspace-classification__message" role="alert" data-testid="builder-issues">
            {issues.map((issue) => <li key={issue.path + issue.message}>{issue.message}</li>)}
          </ul>
        ) : null}
        <BuilderCedar preview={preview} confirmCedar={confirmCedar} setConfirmCedar={setConfirmCedar} onEditAsCedar={onEditAsCedar} schemaVersion={schemaVersion} />
      </section>
    </aside>
  );
}
