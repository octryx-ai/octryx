// Answers to a workflow proposal: the request body, the refusal wording and the "Other workflow…" choices.
import type { WorkflowOption } from "../../chatOptionTypes";
import { answerModel, type StartBudgetBody } from "./startCardChoices";
import { text } from "./workflowStartValues";

export type ProposalDecision = "apply" | "skip" | "other";

export type ProposalAnswerBody = {
  proposal_id: string;
  decision: ProposalDecision;
  workflow_key?: string;
  run_on?: string;
  repository?: string;
  // A device location's model; never without `run_on`.
  model?: string;
  // The run budget for the Work item; only with Start.
  budget?: StartBudgetBody;
};

/**
 * The body of `POST /chat/api/sessions/{id}/workflow-proposal`: `run_on` only with Start (apply), and
 * `model` only with a device `run_on` (the server refuses it otherwise); `workflow_key` only with "other" (which
 * needs one). Null when the answer cannot be sent.
 */
export function proposalAnswerBody({
  proposalId,
  decision,
  workflowKey,
  runOn,
  repository,
  model,
  budget,
}: {
  proposalId: string | null | undefined;
  decision: string;
  workflowKey?: string | null;
  runOn?: string | null;
  repository?: string | null;
  model?: string | null;
  budget?: StartBudgetBody | null;
}): ProposalAnswerBody | null {
  const id = text(proposalId);
  if (!id) return null;
  if (decision === "skip") return { proposal_id: id, decision };
  if (decision === "apply") {
    const target = text(runOn);
    const repo = text(repository);
    const chosenModel = target ? answerModel(target, text(model)) : undefined;
    return { proposal_id: id, decision, ...(target ? { run_on: target } : {}), ...(repo ? { repository: repo } : {}),
      ...(chosenModel ? { model: chosenModel } : {}), ...(budget ? { budget } : {}) };
  }
  if (decision === "other") {
    const key = text(workflowKey);
    return key ? { proposal_id: id, decision, workflow_key: key } : null;
  }
  return null;
}

/**
 * A refused answer in words. The server's sentence wins (409: "Choose the repository the run works in (…)." or "no
 * longer pending"; 422: "Choose one of the repositories the card offers."); without one, 422 and 409 have their own.
 */
/** The refusal's own sentence: a plain detail, or the `message` of a typed one (`needs_configuration` /
 * `workspace_required`: a chat without a Workspace). */
export function answerDetailText(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string")
    return (detail as { message: string }).message;
  return null;
}

export function proposalAnswerProblem(status: number, detail?: string | null): string {
  const said = text(detail);
  if (said) return said;
  if (status === 422) return "This choice is not offered here. Pick another one from the list.";
  if (status === 409) return "This suggestion is no longer waiting for an answer. The chat shows its current state.";
  return "The answer could not be sent. Try again.";
}

export type OtherWorkflowChoice = { key: string; title: string; description: string };

/** "Other workflow…": the composer's catalog without the current workflow and the "No workflow" entry, filtered. */
export function otherWorkflowChoices(
  options: readonly Pick<WorkflowOption, "key" | "title" | "description" | "selection">[] | null | undefined,
  currentKey: string | null | undefined,
  query = "",
): OtherWorkflowChoice[] {
  const needle = query.trim().toLowerCase();
  const seen = new Set<string>();
  return (options ?? []).flatMap((option) => {
    const key = text(option.key);
    if (!key || option.selection === "no_workflow" || key === currentKey || seen.has(key)) return [];
    seen.add(key);
    const choice = { key, title: text(option.title) || key, description: text(option.description) };
    const haystack = `${choice.title} ${choice.key} ${choice.description}`.toLowerCase();
    return !needle || haystack.includes(needle) ? [choice] : [];
  });
}
