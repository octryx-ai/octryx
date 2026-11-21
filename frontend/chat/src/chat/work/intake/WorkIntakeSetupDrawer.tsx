import { useEffect, useMemo, useState } from "react";

import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { SettingsDrawer } from "../../../admin/components/projectsTab/SettingsDrawer";
import type { IntakeSource } from "./workIntakeTypes";
import { STEPS, editableDraft, newDraft, stepProblem, withDiscovery } from "./workIntakeDraft";
import type { IntakeDiscovery, IntakeDraft } from "./workIntakeDraft";
import {
  countIntakeMatches,
  enableIntake,
  loadIntakeDraft,
  loadIntakeFields,
  previewIntake,
  saveIntakeDraft,
} from "./workIntakeSetupApi";
import { HowStep, PreviewStep, SourceStep, WhatStep, WhenStep } from "./WorkIntakeSetupSteps";
import type { PreviewResult } from "./WorkIntakeSetupSteps";
import { RestHowStep, RestWhatStep } from "./WorkIntakeRestSteps";
import type { FieldErrors } from "./WorkIntakeRestSteps";
import { REST_SOURCE, emptyRestForm } from "./restIntakeForm";
import { refusalOf, stepOfField } from "./restIntakeRefusals";
import { restStepRefusal } from "./restIntakeModel";

export type IntakeSetupTarget = { sourceKind: string } | { intakeId: string };

const message = (error: unknown) => (error instanceof Error ? error.message : "The request failed.");
const SOURCE_NAMES: Record<string, string> = { jira: "Jira", servicenow: "ServiceNow", [REST_SOURCE]: "Custom REST" };

function readPreview(result: Record<string, unknown>): PreviewResult {
  const run = (result.sync_run ?? {}) as { summary?: Record<string, unknown> };
  const summary = (result.summary as Record<string, unknown> | undefined) ?? run.summary ?? {};
  return { summary, items: Array.isArray(result.items) ? (result.items as Array<Record<string, unknown>>) : [] };
}

type SetupProps = {
  workspaceId: string;
  workspaceName: string;
  sources: IntakeSource[];
  target: IntakeSetupTarget;
  onClose: () => void;
  onDone: (message: string) => void;
  onOpenConnectors: () => void;
  /** The Workspace workflow's Sync as the overview reports it (`workflowModeOf`); undefined: read the workflows. */
  workflowMode?: string | null;
};

// The drawer's state: the connections that can feed work, the draft (null while an existing intake loads) and the
// current step with what it found, counted and previewed.
function useIntakeSetupState(sources: IntakeSource[], target: IntakeSetupTarget) {
  const connections = useMemo(() => sources.filter((source) => source.work_capable).flatMap((source) =>
    source.connections.map((connection) => ({
      ...connection, kind: source.kind, label: source.label,
      hint: [source.knowledge ? "used by Knowledge" : "", source.work_state === "set_up" ? "has an intake" : ""]
        .filter(Boolean).join(" · ") || source.label,
    }))), [sources]);
  const [draft, setDraft] = useState<IntakeDraft | null>(() => {
    if ("intakeId" in target) return null;
    const first = connections.find((entry) => !target.sourceKind || entry.kind === target.sourceKind);
    return newDraft(first?.kind ?? target.sourceKind ?? "jira", first?.id ?? "");
  });
  const [step, setStep] = useState(0);
  const [found, setFound] = useState<IntakeDiscovery | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  return { connections, draft, setDraft, step, setStep, found, setFound, count, setCount, preview, setPreview, busy, setBusy,
    error, setError, fieldErrors, setFieldErrors };
}

type SetupState = ReturnType<typeof useIntakeSetupState>;

// The existing intake's draft, the chosen connection's fields, and the match count while What is edited.
function useIntakeLoads(workspaceId: string, target: IntakeSetupTarget, state: SetupState) {
  const { draft, setDraft, step, setFound, setCount, setError } = state;
  useEffect(() => {
    if (!("intakeId" in target)) return;
    loadIntakeDraft(workspaceId, target.intakeId).then((loaded) => setDraft(editableDraft(loaded))).catch((failure) => setError(message(failure)));
  }, [workspaceId, target, setDraft, setError]);

  const sourceKey = draft ? `${draft.source_type}:${draft.connection_id}` : "";
  useEffect(() => {
    if (!draft?.connection_id) return;
    let active = true;
    setFound(null);
    loadIntakeFields(workspaceId, draft.source_type, draft.connection_id)
      .then((next) => { if (active) { setFound(next); setDraft((current) => (current ? withDiscovery(current, next) : current)); } })
      .catch((failure) => active && setError(message(failure)));
    return () => { active = false; };
    // Discovery follows the chosen connection only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, sourceKey]);

  const whatKey = draft ? JSON.stringify(draft.what) : "";
  useEffect(() => {
    // No count until What names a project: the count of "everything allowed" would read as this intake's count.
    const projects = draft?.what.project_keys;
    if (!draft || step !== 1 || draft.source_type !== "jira" || !Array.isArray(projects) || !projects.length) {
      setCount(null);
      return;
    }
    let active = true;
    const timer = setTimeout(() => {
      countIntakeMatches(workspaceId, draft).then((result) => active && setCount(result.count ?? null)).catch(() => active && setCount(null));
    }, 400);
    return () => { active = false; clearTimeout(timer); };
    // The count follows the selection only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, step, whatKey]);
}

// Set up or edit one intake (§3.2): Source → What → When → How → Preview, then Enable. The intake is saved when
// the preview runs; a new intake stays off until it is enabled after a successful preview.
export function WorkIntakeSetupDrawer({ workspaceId, workspaceName, sources, target, onClose, onDone, onOpenConnectors, workflowMode }: SetupProps) {
  const state = useIntakeSetupState(sources, target);
  useIntakeLoads(workspaceId, target, state);
  const { draft, step, setStep, busy, preview, error } = state;

  if (!draft) {
    return <SettingsDrawer eyebrow={`Work · Intake · ${workspaceName}`} title="Edit intake" size="detail" onClose={onClose}>
      {error ? <div className="work-area__error">{error}</div> : <p className="admin-panel__hint">Loading the intake…</p>}
    </SettingsDrawer>;
  }

  const { update, next } = intakeActions(draft, state, workspaceId, onDone);
  const kind = SOURCE_NAMES[draft.source_type] ?? draft.source_type;
  const nextLabel = step === 3 ? "Run preview" : step === 4 ? (draft.is_active ? "Done" : "Enable intake") : "Next";
  const footer = (
    <>
      <button type="button" className="admin-panel__action-btn" disabled={step === 0 || busy} onClick={() => setStep(step - 1)}>Back</button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={busy || (step === 4 && !preview)} onClick={next}>{busy ? "Working…" : nextLabel}</button>
    </>
  );
  return (
    <SettingsDrawer eyebrow={`Work · Intake · ${workspaceName}`} size="detail" onClose={onClose} footer={footer}
      title={draft.id ? "Edit intake" : `New ${kind} intake`}>
      <SegmentedTabs label="Setup steps" idPrefix="work-intake-step" size="small" value={String(step)} onChange={(key) => setStep(Number(key))}
        tabs={STEPS.map((label, index) => ({ key: String(index), label: `${index + 1} ${label}`, disabled: index > step }))} />
      <IntakeStepPane draft={draft} state={state} update={update} workspaceId={workspaceId} workflowMode={workflowMode}
        onOpenConnectors={onOpenConnectors} />
      {error ? <div className="work-area__error" role="alert">{error}</div> : null}
    </SettingsDrawer>
  );
}

// The drawer's steps: update a field, save and preview, enable, and move on when the step is complete.
function intakeActions(draft: IntakeDraft, state: SetupState, workspaceId: string, onDone: (message: string) => void) {
  const { step, setStep, found, setDraft, setBusy, setError, setFieldErrors, setPreview } = state;
  const update = (patch: Partial<IntakeDraft>) => { setDraft({ ...draft, ...patch }); setError(null); setFieldErrors({}); setPreview(null); };
  const problem = stepProblem(step, draft, found);
  const rest = draft.source_type === REST_SOURCE;

  // A refusal in words; a Custom REST refusal at a field is shown at that field, on the step that edits it.
  function refused(failure: unknown) {
    const refusal = refusalOf(failure);
    // The Sync is the one field every source shares; its refusal (422) is shown at the select.
    if (!rest && refusal.field !== "how.sync_mode") { setError(message(failure)); return; }
    const at = stepOfField(refusal.field);
    if (refusal.field) setFieldErrors({ [refusal.field]: refusal.text });
    if (at !== null && at !== 4) setStep(at);
    setError(refusal.field && at !== null ? null : refusal.text);
  }

  async function guarded(work: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (failure) {
      refused(failure);
    } finally {
      setBusy(false);
    }
  }

  const runPreview = () => guarded(async () => {
    const saved = editableDraft(await saveIntakeDraft(workspaceId, draft));
    setDraft(saved);
    setStep(4);
    setPreview(readPreview(await previewIntake(workspaceId, saved.id as string)));
  });

  async function finish() {
    if (!draft.id) return;
    if (draft.is_active) { onDone("Intake saved."); return; }
    const id = draft.id;
    await guarded(async () => {
      const result = await enableIntake(workspaceId, id);
      onDone(result.first_run_error ? "Intake enabled. The first run failed; see its run history." : "Intake enabled. The first run started.");
    });
  }

  function next() {
    if (problem) {
      // A Custom REST problem is shown at its field; the other sources show it below the step.
      const refusal = rest ? restStepRefusal(step, draft.rest ?? emptyRestForm(), found?.list_operations?.find((entry) => entry.op_key === draft.rest?.operation)) : null;
      if (refusal) setFieldErrors({ [refusal.field]: refusal.text }); else setError(problem);
      return;
    }
    if (step < 3) setStep(step + 1);
    else if (step === 3) void runPreview();
    else void finish();
  }
  return { update, next };
}

function IntakeStepPane({ draft, state, update, workspaceId, workflowMode, onOpenConnectors }: {
  draft: IntakeDraft; state: SetupState; update: (patch: Partial<IntakeDraft>) => void; workspaceId: string;
  workflowMode?: string | null; onOpenConnectors: () => void;
}) {
  const { step, found, count, preview, fieldErrors, connections } = state;
  const rest = draft.source_type === REST_SOURCE;
  return (
    <div className="work-intake__pane" data-testid={`intake-step-${step}`}>
      {step === 0 ? <SourceStep draft={draft} connections={connections} onOpenConnectors={onOpenConnectors}
        update={(patch) => {
          const kindChanged = patch.source_type !== undefined && patch.source_type !== draft.source_type;
          // A REST API's operations are its own: another API starts the Custom REST form over.
          const apiChanged = draft.source_type === REST_SOURCE && patch.connection_id !== draft.connection_id;
          const fresh = newDraft(patch.source_type ?? draft.source_type, patch.connection_id ?? draft.connection_id);
          update((kindChanged || apiChanged) && !draft.id
            ? { ...patch, what: fresh.what, how: fresh.how, schedule: fresh.schedule, rest: fresh.rest } : patch);
        }} /> : null}
      {step === 1 && rest ? <RestWhatStep draft={draft} found={found} update={update} errors={fieldErrors} /> : null}
      {step === 1 && !rest ? <WhatStep draft={draft} found={found} count={count} update={update} /> : null}
      {step === 2 ? <WhenStep draft={draft} update={update} /> : null}
      {step === 3 ? <HowStep draft={draft} found={found} workspaceId={workspaceId} update={update}
        workflowMode={workflowMode} syncError={fieldErrors["how.sync_mode"]} sourceParts={rest
        ? <RestHowStep draft={draft} found={found} workspaceId={workspaceId} update={update} errors={fieldErrors} /> : undefined} /> : null}
      {step === 4 ? <PreviewStep draft={draft} preview={preview} found={found} /> : null}
    </div>
  );
}
