// A held workflow proposal's answer, posted with its status kept for the refusal sentence.
import type { ChatState } from "../types";
import { answerDetailText } from "./run/workflowProposalAnswer";
import { proposalAnswerProblem } from "./run/workflowProposalAnswer";

// The proposal endpoint with its status kept: 422 and 409 have their own sentence (`proposalAnswerProblem`).
export async function postProposalAnswer(path: string, body: unknown): Promise<ChatState> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail: string | null = null;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      detail = answerDetailText(payload.detail);
    } catch {
      // Keep the status sentence.
    }
    throw new Error(proposalAnswerProblem(response.status, detail));
  }
  return (await response.json()) as ChatState;
}
