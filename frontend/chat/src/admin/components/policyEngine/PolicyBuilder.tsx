import type { ReactNode } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { normalizeContent } from "./builderContentModel";
import { savePolicy } from "./policyEngineApi";
import { refusalText } from "./policyEngineVersions";
import { saveBody } from "./policyBuilderModel";
import type { BuilderModel } from "./policyBuilderModel";
import type { Catalog, PickerEntities, PolicyView } from "./policyCatalogModel";
import { BuilderSide, BuilderStepPane, BuilderSteps } from "./PolicyBuilderParts";
import { builderStatus, usePolicyBuilder } from "./usePolicyBuilder";
import type { BuilderSession } from "./usePolicyBuilder";
import "./policyBuilder.css";

// "New policy" / "Edit": the guided builder — a stepper with a hint per step on the left, the
// step beside it, and below the live sentence, the warnings and the generated Cedar (read-only, from the server:
// the browser never writes Cedar). "Save to draft" stores the policy through the policy-level save with the draft's
// digest (If-Match); "Edit as Cedar…" turns it into a hand-written policy after a confirmation.
// it is a side panel over the dimmed list like every other create flow; Cancel, Back, Next and Save to draft sit in
// its footer, Save to draft last.
export function PolicyBuilder({ session, catalog, entities, view, onCancel, onSaved, onEditAsCedar, checkStep, previewDelay = 250 }: {
  session: BuilderSession;
  catalog: Catalog;
  entities: PickerEntities;
  view: PolicyView;
  onCancel: () => void;
  onSaved: (message: string) => Promise<void>;
  onEditAsCedar: (text: string) => void;
  checkStep: (model: BuilderModel, preview: { valid: boolean; text: string }) => ReactNode;
  previewDelay?: number;
}) {
  const state = usePolicyBuilder(session, catalog, previewDelay);
  const { model, setModel, setStep, idLocked, setIdLocked, preview, busy, setBusy, problem, setProblem, confirmCedar, setConfirmCedar, detectors, content } = state;
  const status = builderStatus(model, state.step, preview, catalog, view);
  const { required, target, steps, current, index, blocked, draftLabel } = status;

  const save = async () => {
    if (!target || blocked) return;
    setBusy(true);
    setProblem(null);
    try {
      await savePolicy(target.version, session.originalId ?? model.id, saveBody(model, session.isNew, ""), target.digest);
      await onSaved(`Saved "${model.name || model.id}" to the draft: validated, and the saved test cases ran against it.`);
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
    }
  };

  const pane = { model, onChange: (next: BuilderModel) => { setModel(normalizeContent(next)); setProblem(null); }, catalog, entities, required };
  return (
    <SidePanel
      title={session.title}
      onClose={onCancel}
      testId="policy-builder-panel"
      headerActions={<span className="work-badge work-badge--attention" data-testid="builder-target">{draftLabel}</span>}
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" data-testid="builder-back" onClick={onCancel}>Cancel</button>
          <button type="button" className="admin-panel__action-btn" data-testid="builder-prev" disabled={index === 0} onClick={() => setStep(steps[index - 1].id)}>Back</button>
          <button type="button" className="admin-panel__action-btn" data-testid="builder-next" disabled={index === steps.length - 1} onClick={() => setStep(steps[index + 1].id)}>Next</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="builder-save"
            disabled={busy || Boolean(blocked)} title={blocked ?? undefined} onClick={() => void save()}>Save to draft</button>
        </>
      )}
    >
    <div className="policies__pane" data-testid="policy-builder">
      {problem ? <p className="workspace-classification__message" role="alert" data-testid="builder-problem">{problem}</p> : null}
      <div className="policies__builder policies__builder--panel">
        <BuilderSteps status={status} model={model} setStep={setStep} />
        <BuilderStepPane current={current} pane={pane} idLocked={idLocked} onIdEdited={() => setIdLocked(true)} detectors={detectors}
          previewDelay={previewDelay} checkStep={checkStep} preview={preview} content={content} />
        <BuilderSide status={status} preview={preview} content={content} confirmCedar={confirmCedar} setConfirmCedar={setConfirmCedar}
          onEditAsCedar={onEditAsCedar} schemaVersion={catalog.schemaVersion} />
      </div>
    </div>
    </SidePanel>
  );
}
