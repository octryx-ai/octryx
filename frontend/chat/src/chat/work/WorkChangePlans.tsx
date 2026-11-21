import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { answerWorkPlanClarifications, decideWorkChangePlan, generateWorkItemLlmWorkPlan, loadWorkItemChangePlans } from "./workChangePlanApi";
import type { WorkChangePlan } from "./workChangePlanTypes";
import type { WorkItem } from "./workItemTypes";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
import { errorMessage } from "./workPlanListModel";
import { FINAL_PLAN_STATUSES } from "./planStatus";
import { formatDateTime } from "./workUtils";
import type { ClarificationAnswerResult } from "./WorkPlanClarificationAnswers";
import type { ClarificationAnswer } from "./workPlanClarificationModel";
import { WorkChangePlanView } from "./WorkChangePlanView";

type ChangePlansProps = {
  item: WorkItem;
  workflows: WorkWorkflowDefinition[];
  focusPlanId?: string | null;
  // Selects another version of this item (updates the address); without it versions are listed only.
  onSelectPlan?: (planId: string) => void;
  // Called after a decision or a new version succeeded, so plan lists and counts reload.
  onPlansChanged?: () => void;
};

function useChangePlanState(itemId: string, focusPlanId: string | null) {
  const [plans, setPlans] = useState<WorkChangePlan[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [decisionText, setDecisionText] = useState("");
  // Only the newest load may write: a slower earlier response never replaces newer plan data.
  const loadSequence = useRef(0);
  // One mutation at a time (generate or a decision), also against double clicks before a re-render.
  const mutating = useRef(false);
  // The item and requested plan on screen now, and whether this view is still mounted: a reply to an
  // answers request sent for another item or selection must not reload or reselect this one.
  const currentItemId = useRef(itemId);
  const currentFocus = useRef(focusPlanId);
  const mounted = useRef(true);
  useEffect(() => {
    currentItemId.current = itemId;
    currentFocus.current = focusPlanId;
  }, [itemId, focusPlanId]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  return {
    plans, setPlans, loaded, setLoaded, error, setError, busyAction, setBusyAction, decisionText, setDecisionText,
    loadSequence, mutating, currentItemId, currentFocus, mounted,
  };
}

type PlanState = ReturnType<typeof useChangePlanState>;

function useChangePlanLoading(state: PlanState, itemId: string, workflows: WorkWorkflowDefinition[]) {
  const { loadSequence, setError, setPlans, setLoaded, setDecisionText } = state;
  const workflow = useMemo(
    () => workflows.find((entry) => entry.is_default && entry.is_active) || workflows.find((entry) => entry.is_active) || workflows[0],
    [workflows],
  );
  const refresh = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setError(null);
    try {
      const next = await loadWorkItemChangePlans(itemId);
      if (sequence === loadSequence.current) setPlans(next);
    } catch (err) {
      if (sequence === loadSequence.current) setError(errorMessage(err, "Failed to load Change Plans"));
    } finally {
      if (sequence === loadSequence.current) setLoaded(true);
    }
  }, [itemId, loadSequence, setError, setPlans, setLoaded]);

  useEffect(() => {
    setLoaded(false);
    setPlans([]);
    setDecisionText("");
    void refresh();
  }, [refresh, setLoaded, setPlans, setDecisionText]);
  return { workflow, refresh };
}

type PlanContext = {
  state: PlanState;
  item: WorkItem;
  workflow: WorkWorkflowDefinition | undefined;
  selected: WorkChangePlan | null;
  refresh: () => Promise<void>;
  onSelectPlan?: (planId: string) => void;
  onPlansChanged?: () => void;
};

async function generatePlan({ state, item, workflow, refresh, onSelectPlan, onPlansChanged }: PlanContext) {
  const { mutating, setBusyAction, setError } = state;
  if (mutating.current) return;
  mutating.current = true;
  setBusyAction("generate");
  setError(null);
  try {
    const approvalBaseUrl = typeof window === "undefined" ? "/chat" : `${window.location.origin}/chat`;
    const created = await generateWorkItemLlmWorkPlan({
      workItemId: item.id,
      workflowId: workflow?.id,
      targetState: "ready_for_review",
      approvalBaseUrl,
    });
    state.setDecisionText("");
    onPlansChanged?.();
    await refresh();
    if (created?.id) onSelectPlan?.(created.id);
  } catch (err) {
    setError(errorMessage(err, "Failed to generate Change Plan"));
  } finally {
    mutating.current = false;
    setBusyAction(null);
  }
}

// Bound to the exact plan the answers were written for, never the selection at reply time.
async function answerPlan(
  { state, item, refresh, onSelectPlan, onPlansChanged }: PlanContext,
  plan: WorkChangePlan,
  payload: { expected_latest_version: number; answers: ClarificationAnswer[] },
): Promise<ClarificationAnswerResult> {
  const { mutating, mounted, currentItemId, currentFocus } = state;
  if (mutating.current) return { ok: false, message: "Another change is still in progress" };
  mutating.current = true;
  state.setBusyAction("answer");
  state.setError(null);
  const requestItemId = item.id;
  const requestFocus = currentFocus.current;
  // The server may still finish for the original item; only a still-current view applies the reply.
  const stillCurrent = () => mounted.current && currentItemId.current === requestItemId;
  try {
    const created = await answerWorkPlanClarifications({
      changePlanId: plan.id,
      expectedLatestVersion: payload.expected_latest_version,
      answers: payload.answers,
    });
    if (stillCurrent()) {
      state.setDecisionText("");
      onPlansChanged?.();
      await refresh();
      if (created?.id && stillCurrent() && currentFocus.current === requestFocus) onSelectPlan?.(created.id);
    }
    return { ok: true };
  } catch (err) {
    if (stillCurrent()) await refresh();
    return { ok: false, message: errorMessage(err, "The revised plan was not created") };
  } finally {
    mutating.current = false;
    if (mounted.current) state.setBusyAction(null);
  }
}

async function decide(
  { state, selected, workflow, refresh, onPlansChanged }: PlanContext,
  action: "approve" | "reject" | "request_clarification",
) {
  const { mutating, decisionText } = state;
  if (!selected || mutating.current) return;
  mutating.current = true;
  state.setBusyAction(action);
  state.setError(null);
  try {
    await decideWorkChangePlan({
      changePlanId: selected.id,
      action,
      reason: decisionText || defaultDecisionReason(action),
      requiredChanges: action === "request_clarification" ? [decisionText || "Clarification required."] : [],
      workflowId: selected.workflow_id || workflow?.id,
      targetState: action === "approve" ? "approved" : action === "reject" ? "rejected" : "needs_clarification",
    });
    state.setDecisionText("");
    onPlansChanged?.();
    await refresh();
  } catch (err) {
    state.setError(errorMessage(err, "Failed to update Change Plan"));
  } finally {
    mutating.current = false;
    state.setBusyAction(null);
  }
}

function PlanToolbar({ selected, newest, focusMissing, busyAction, hasPlans, onGenerate }: {
  selected: WorkChangePlan | null;
  newest: WorkChangePlan | null;
  focusMissing: boolean;
  busyAction: string | null;
  hasPlans: boolean;
  onGenerate: () => void;
}) {
  return (
    <div className="work-change-plan__toolbar">
      <div>
        <strong>
          {selected ? `Version ${selected.version}` : focusMissing ? "Requested plan not found" : "No Change Plan"}
        </strong>
        <span>
          {selected
            ? `${selected.status.replaceAll("_", " ")} · ${formatDateTime(selected.updated_at || selected.created_at)}`
              + (newest && newest.id !== selected.id ? ` · newest is v${newest.version}` : "")
            : focusMissing
              ? "Choose a version below."
              : "Generate a structured plan before code-changing execution."}
        </span>
      </div>
      <button
        type="button"
        className="work-area__button"
        onClick={onGenerate}
        disabled={Boolean(busyAction)}
      >
        {busyAction === "generate" ? "Generating..." : hasPlans ? "New version" : "Generate plan"}
      </button>
    </div>
  );
}

function PlanVersions({ plans, selected, busyAction, onSelectPlan }: {
  plans: WorkChangePlan[];
  selected: WorkChangePlan | null;
  busyAction: string | null;
  onSelectPlan?: (planId: string) => void;
}) {
  return (
    <div className="work-change-plan__versions" aria-label="Change Plan versions">
      {plans.map((plan) => {
        const label = `v${plan.version} · ${plan.status.replaceAll("_", " ")}`;
        const current = plan.id === selected?.id;
        return onSelectPlan ? (
          <button key={plan.id} type="button" className={`work-area__button ${current ? "is-active" : ""}`}
            aria-pressed={current} disabled={Boolean(busyAction)} onClick={() => onSelectPlan(plan.id)}>
            {label}
          </button>
        ) : (
          <span key={plan.id}>{label}</span>
        );
      })}
    </div>
  );
}

// A plan opened from Change Plans or Plan reviews (or a `change_plan_id` link) is shown and decided
// by its exact id. Without a requested id the newest version is shown. A
// requested id that is not a plan of this Work Item is an explicit error: nothing is selected and
// no decision is offered, never a silent fallback to another version.
export function WorkChangePlans({ item, workflows, focusPlanId = null, onSelectPlan, onPlansChanged }: ChangePlansProps) {
  const state = useChangePlanState(item.id, focusPlanId);
  const { plans, loaded, error, busyAction, decisionText, setDecisionText } = state;
  const { workflow, refresh } = useChangePlanLoading(state, item.id, workflows);
  // Plans arrive newest version first.
  const newest = plans[0] || null;
  const selected = focusPlanId ? plans.find((plan) => plan.id === focusPlanId) || null : newest;
  const focusMissing = Boolean(focusPlanId) && loaded && !error && !selected;
  const previous = selected ? plans.find((plan) => plan.version < selected.version) || null : null;
  const ctx: PlanContext = { state, item, workflow, selected, refresh, onSelectPlan, onPlansChanged };
  const canDecide = Boolean(selected && !FINAL_PLAN_STATUSES.has(selected.status));

  if (!loaded) {
    return <div className="work-change-plan"><p className="work-detail__empty">Loading Change Plans…</p></div>;
  }

  return (
    <div className="work-change-plan">
      <PlanToolbar selected={selected} newest={newest} focusMissing={focusMissing} busyAction={busyAction}
        hasPlans={plans.length > 0} onGenerate={() => void generatePlan(ctx)} />
      {error ? <p className="work-detail__empty" role="alert">{error}</p> : null}
      {focusMissing ? (
        <p className="work-detail__empty" role="alert" data-testid="change-plan-focus-missing">
          The requested Change Plan is not a plan of this Work Item, or it no longer exists. No version is selected
          and no decision is offered.
        </p>
      ) : null}
      {selected ? (
        <WorkChangePlanView selected={selected} newest={newest} previous={previous} busyAction={busyAction}
          canDecide={canDecide} decisionText={decisionText} setDecisionText={setDecisionText}
          answerPlan={(plan, payload) => answerPlan(ctx, plan, payload)} decide={(action) => decide(ctx, action)} />
      ) : null}
      {plans.length > 1 || (focusMissing && plans.length > 0) ? (
        <PlanVersions plans={plans} selected={selected} busyAction={busyAction} onSelectPlan={onSelectPlan} />
      ) : null}
      {!selected && !focusMissing && !error ? (
        <p className="work-detail__empty">
          No Change Plan exists yet. Generate one after repository impact and reviewer setup are available.
        </p>
      ) : null}
    </div>
  );
}

function defaultDecisionReason(action: string): string {
  if (action === "approve") return "Approved from Work Item detail.";
  if (action === "reject") return "Rejected from Work Item detail.";
  return "Clarification requested from Work Item detail.";
}
