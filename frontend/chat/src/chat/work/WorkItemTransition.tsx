import { useState } from "react";

import { applyWorkTransition, previewWorkTransition } from "./workTransitionApi";
import "./workTransition.css";
import {
  previewBinding,
  preselectedWorkflow,
  targetStates,
  transitionPlan,
  transitionRefusal,
  transitionResultText,
  workflowsForItem,
  workflowsHref,
} from "./workTransitionModel";
import type { WorkItem } from "./workItemTypes";
import type { WorkTransitionPreview, WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
type Busy = "preview" | "apply" | null;
type Refusal = { text: string; offers: string[] | null } | null;
type Plan = NonNullable<ReturnType<typeof transitionPlan>>;

type TransitionContext = {
  item: WorkItem;
  workflow: WorkWorkflowDefinition | null;
  reason: string;
  guard: string | null;
  setBusy: (busy: Busy) => void;
  setPreview: (preview: WorkTransitionPreview | null) => void;
  setRefusal: (refusal: Refusal) => void;
};

async function runTransitionPreview(ctx: TransitionContext, toState: string, reset: () => void) {
  const { item, workflow, reason, guard, setBusy, setPreview, setRefusal } = ctx;
  if (!workflow || !toState) return;
  setBusy("preview");
  reset();
  try {
    const response = await previewWorkTransition({
      workflowId: workflow.id, workItemId: item.id, toState, reason, sourceJiraUpdatedAt: guard,
    });
    if (response.preview.valid === false) setRefusal({ text: response.preview.error || "The transition is not valid.", offers: null });
    else setPreview(response.preview);
  } catch (error) {
    setRefusal(transitionRefusal(error));
  } finally {
    setBusy(null);
  }
}

async function applyTransition(
  ctx: TransitionContext & { setResult: (result: string) => void; setToState: (state: string) => void },
  preview: WorkTransitionPreview | null,
  label: (key: string) => string,
  onApplied?: () => void,
) {
  const { item, workflow, reason, guard, setBusy, setPreview, setRefusal, setResult, setToState } = ctx;
  if (!workflow || !preview) return;
  setBusy("apply");
  setRefusal(null);
  try {
    const applied = await applyWorkTransition({
      workflowId: workflow.id, workItemId: item.id, toState: preview.to_state, reason, sourceJiraUpdatedAt: guard,
      binding: previewBinding(preview),
    });
    setResult(transitionResultText(label(applied.work_state || preview.to_state), applied.preview));
    setPreview(null);
    setToState("");
    onApplied?.();
  } catch (error) {
    // A refused apply never leaves its preview to be applied again: the author previews anew.
    setPreview(null);
    setRefusal(transitionRefusal(error));
  } finally {
    setBusy(null);
  }
}

function TransitionConfirmation({ item, preview, plan, label, busy, apply, reset }: {
  item: WorkItem;
  preview: WorkTransitionPreview;
  plan: Plan;
  label: (key: string) => string;
  busy: Busy;
  apply: () => Promise<void>;
  reset: () => void;
}) {
  return (
    <div className="work-transition__block" role="group" aria-label="Confirm the transition" data-testid="transition-confirmation">
      <p className="work-transition__heading" data-testid="transition-heading">
        {label(preview.from_state)} → {label(preview.to_state)}
      </p>
      {plan.blocked ? (
        <div className="work-area__error work-transition__block" role="alert" data-testid="transition-blocked">
          <p>{plan.blocked}</p>
          {plan.offers.length ? (
            <>
              <p>Jira offers from the issue&apos;s current status:</p>
              <ul className="work-detail__object-list">{plan.offers.map((offer) => <li key={offer}>{offer}</li>)}</ul>
            </>
          ) : null}
        </div>
      ) : plan.writesToJira ? (
        <>
          <p>Written to Jira {item.source_key}:</p>
          <ul className="work-detail__object-list" data-testid="transition-effects">
            {plan.effects.map((effect, index) => <li key={`${effect.kind}-${index}`}>{effect.text}</li>)}
          </ul>
        </>
      ) : (
        <p className="work-detail__empty" data-testid="transition-local">{plan.localReason}</p>
      )}
      {plan.conflict ? <p className="work-area__error" role="alert">{plan.conflict}</p> : null}
      <div>
        <button type="button" className="work-area__button is-active" disabled={busy !== null || Boolean(plan.conflict) || Boolean(plan.blocked)}
          onClick={() => void apply()}>
          {busy === "apply" ? "Applying…" : plan.writesToJira ? "Apply and write to Jira" : "Apply in Octryx"}
        </button>{" "}
        <button type="button" className="work-area__button" disabled={busy !== null} onClick={reset}>Cancel</button>
      </div>
    </div>
  );
}

function TransitionRefusal({ refusal }: { refusal: NonNullable<Refusal> }) {
  return (
    <div className="work-area__error work-transition__block" role="alert" data-testid="transition-refusal">
      <p>Not applied: {refusal.text}</p>
      {refusal.offers ? (
        refusal.offers.length ? (
          <>
            <p>Jira offers from the issue&apos;s current status:</p>
            <ul className="work-detail__object-list">{refusal.offers.map((offer) => <li key={offer}>{offer}</li>)}</ul>
          </>
        ) : <p>Jira offers no transition from the issue&apos;s current status.</p>
      ) : null}
    </div>
  );
}

type TransitionViewProps = {
  item: WorkItem;
  candidates: WorkWorkflowDefinition[];
  workflowId: string;
  states: ReturnType<typeof targetStates>;
  toState: string;
  reason: string;
  busy: Busy;
  setWorkflowId: (workflowId: string) => void;
  setToState: (state: string) => void;
  setReason: (reason: string) => void;
  reset: () => void;
  runPreview: () => Promise<void>;
  preview: WorkTransitionPreview | null;
  plan: Plan | null;
  label: (key: string) => string;
  apply: () => Promise<void>;
  refusal: Refusal;
  result: string | null;
};

// The form (workflow, target state, reason, Preview), then the confirmation, the refusal and the result.
function TransitionView(props: TransitionViewProps) {
  const {
    item, candidates, workflowId, states, toState, reason, busy, setWorkflowId, setToState, setReason, reset, runPreview, preview,
    plan, label, apply, refusal, result,
  } = props;
  return (
    <div className="work-dry-run" data-testid="work-item-transition">
      {candidates.length > 1 ? (
        <label>
          Workflow
          <select value={workflowId} onChange={(event) => { setWorkflowId(event.target.value); setToState(""); reset(); }}>
            {candidates.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}
          </select>
        </label>
      ) : null}
      <label>
        Move to
        <select value={toState} aria-label="Target state" onChange={(event) => { setToState(event.target.value); reset(); }}>
          <option value="">Choose a state…</option>
          {states.map((state) => <option key={state.key} value={state.key}>{state.label || state.key}</option>)}
        </select>
      </label>
      <label>
        Reason (optional, recorded with the transition)
        <input value={reason} aria-label="Transition reason" onChange={(event) => { setReason(event.target.value); reset(); }} />
      </label>
      <div>
        <button type="button" className="work-area__button" disabled={!toState || busy !== null} onClick={() => void runPreview()}>
          {busy === "preview" ? "Previewing…" : "Preview"}
        </button>
      </div>

      {preview && plan ? (
        <TransitionConfirmation item={item} preview={preview} plan={plan} label={label} busy={busy} apply={apply} reset={reset} />
      ) : null}

      {refusal ? <TransitionRefusal refusal={refusal} /> : null}
      {result ? <p className="work-area__notice" role="status" data-testid="transition-result">{result}</p> : null}
    </div>
  );
}

export function WorkItemTransition({
  item,
  workflows,
  onApplied,
}: {
  item: WorkItem;
  workflows: WorkWorkflowDefinition[];
  onApplied?: () => void;
}) {
  const candidates = workflowsForItem(item, workflows);
  const [workflowId, setWorkflowId] = useState(() => preselectedWorkflow(item, candidates)?.id ?? "");
  const workflow = candidates.find((entry) => entry.id === workflowId) ?? null;
  const states = targetStates(item, workflow);
  const [toState, setToState] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<WorkTransitionPreview | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [refusal, setRefusal] = useState<Refusal>(null);
  const guard = item.last_source_updated_at ?? null;
  const [result, setResult] = useState<string | null>(null);

  if (!candidates.length) {
    return (
      <p className="work-detail__empty" data-testid="transition-no-workflow">
        No active workflow covers this item yet, so it cannot be moved here.{" "}
        <a href={workflowsHref(item.project_id)}>Publish a workflow for it in Agents › Workflows</a>, then move it here.
      </p>
    );
  }
  // Any change after a preview discards it: the apply is always the transition the author confirmed.
  const reset = () => {
    setPreview(null);
    setRefusal(null);
    setResult(null);
  };
  const label = (key: string) => workflow?.states.find((state) => state.key === key)?.label || key;
  const plan = preview ? transitionPlan(item, workflow, preview) : null;

  const ctx = { item, workflow, reason, guard, setBusy, setPreview, setRefusal };
  const runPreview = () => runTransitionPreview(ctx, toState, reset);
  const apply = () => applyTransition({ ...ctx, setResult, setToState }, preview, label, onApplied);

  return (
    <TransitionView item={item} candidates={candidates} workflowId={workflowId} states={states} toState={toState} reason={reason}
      busy={busy} setWorkflowId={setWorkflowId} setToState={setToState} setReason={setReason} reset={reset}
      runPreview={runPreview} preview={preview} plan={plan} label={label} apply={apply} refusal={refusal} result={result} />
  );
}
