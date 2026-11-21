// The start card's choices (Run on, repository, model, cost budget) and the send of its Start / Don't start answer.
import { useEffect, useId, useState } from "react";

import { startBudget, startBudgetError, startModelError, type StartBudgetBody } from "./startCardChoices";
import type { WorkflowStartView } from "./workflowStartModel";

type StartHandler = (runOn: string, repository: string, model: string, budget: StartBudgetBody | null) => Promise<void>;
type Setter = (value: string | null) => void;

type SendInput = {
  kind: "start" | "skip";
  onStart: StartHandler;
  onSkip: () => Promise<void>;
  choices: { runOn: string; repository: string; model: string; cost: string };
  setProblem: Setter;
  setModelError: Setter;
  setCostError: Setter;
};

// Sends the answer; a refusal lands at the model, at the budget or as the card's problem.
async function sendStartAnswer({ kind, onStart, onSkip, choices, setProblem, setModelError, setCostError }: SendInput) {
  try {
    if (kind === "skip") await onSkip();
    else {
      const planned = startBudget(choices.cost);
      if ("error" in planned) setCostError(planned.error);
      else await onStart(choices.runOn, choices.repository, choices.model, planned.budget);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "The answer could not be sent.";
    const atModel = startModelError(message);
    const atBudget = startBudgetError(message);
    if (atModel) setModelError(atModel);
    else if (atBudget) setCostError(atBudget);
    else setProblem(message);
  }
}

export function useWorkflowStartCard(view: WorkflowStartView) {
  const [runOn, setRunOn] = useState(view.runOn.selected);
  const [repository, setRepository] = useState("");
  const [busy, setBusy] = useState<"start" | "skip" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [modelError, setModelError] = useState<string | null>(null);
  const [cost, setCost] = useState("");
  const [costError, setCostError] = useState<string | null>(null);
  const runOnId = useId();
  // "Other workflow…" brings a new draft with its own options: follow the server's choice again.
  useEffect(() => setRunOn(view.runOn.selected), [view.workflowKey, view.runOn.selected]);
  useEffect(() => {
    setRepository("");
    setProblem(null);
  }, [view.workflowKey]);
  return {
    runOn, setRunOn, repository, setRepository, busy, setBusy, problem, setProblem, model, setModel,
    modelError, setModelError, cost, setCost, costError, setCostError, runOnId,
  };
}

export type WorkflowStartCardState = ReturnType<typeof useWorkflowStartCard>;

export async function runStartDecision(
  kind: "start" | "skip",
  state: WorkflowStartCardState,
  { disabled, blocked, onStart, onSkip }: { disabled: boolean; blocked: string | null; onStart: StartHandler; onSkip: () => Promise<void> },
) {
  if (disabled || state.busy) return;
  if (kind === "start" && blocked) return;
  state.setBusy(kind);
  state.setProblem(null);
  state.setModelError(null);
  state.setCostError(null);
  try {
    const { runOn, repository, model, cost } = state;
    await sendStartAnswer({ kind, onStart, onSkip, choices: { runOn, repository, model, cost }, ...state });
  } finally {
    state.setBusy(null);
  }
}
