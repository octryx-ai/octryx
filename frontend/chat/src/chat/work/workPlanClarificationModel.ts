import type { WorkChangePlan } from "./workChangePlanTypes";

// Transport guards mirrored from the server, not content limits.
export const MAX_ANSWERS = 1000;
export const MAX_ANSWER_CHARS = 100000;
const OPEN_STATUSES = new Set(["draft", "needs_clarification", "ready_for_review"]);

export type ClarificationAnswer = { question_index: number; question: string; answer: string };

export type ClarificationDraftCheck = {
  answers: ClarificationAnswer[];
  unanswered: number[];
  errors: Record<number, string>;
  totalError: string | null;
  payload: { expected_latest_version: number; answers: ClarificationAnswer[] } | null;
};

export type RetainedClarification = {
  sourcePlanId: string;
  sourceVersion: number;
  answeredAt: string | null;
  answeredByLabel: string | null;
  answeredBy: string | null;
  answers: ClarificationAnswer[];
  unanswered: number[];
};

export function isAnswerable(plan: WorkChangePlan, newest: WorkChangePlan | null): boolean {
  return Boolean(newest && newest.id === plan.id && OPEN_STATUSES.has(plan.status) && plan.open_questions.length > 0);
}

export function checkClarificationDraft(plan: WorkChangePlan, drafts: string[]): ClarificationDraftCheck {
  const answers: ClarificationAnswer[] = [];
  const unanswered: number[] = [];
  const errors: Record<number, string> = {};
  plan.open_questions.forEach((question, index) => {
    const answer = (drafts[index] || "").trim();
    if (!answer) {
      unanswered.push(index);
      return;
    }
    if (answer.length > MAX_ANSWER_CHARS) {
      errors[index] = `Shorten this answer to ${MAX_ANSWER_CHARS} characters (now ${answer.length}).`;
    }
    answers.push({ question_index: index, question, answer });
  });
  const totalError = answers.length > MAX_ANSWERS
    ? `At most ${MAX_ANSWERS} answers can be sent at once (now ${answers.length}). Clear ${answers.length - MAX_ANSWERS} `
      + "of them here; the revised version keeps those questions open."
    : null;
  const valid = answers.length > 0 && !totalError && Object.keys(errors).length === 0;
  return {
    answers,
    unanswered,
    errors,
    totalError,
    payload: valid ? { expected_latest_version: plan.version, answers } : null,
  };
}

function isAnswer(value: unknown): value is ClarificationAnswer {
  if (!value || typeof value !== "object") return false;
  const entry = value as Record<string, unknown>;
  return Number.isInteger(entry.question_index) && typeof entry.question === "string" && typeof entry.answer === "string";
}

// A malformed record reads as none, never as if it were complete.
export function retainedClarification(plan: WorkChangePlan): RetainedClarification | null {
  const raw = plan.evidence?.clarification;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const answers = record.answers;
  if (typeof record.source_plan_id !== "string" || !Number.isInteger(record.source_version)) return null;
  if (!Array.isArray(answers) || answers.length === 0 || !answers.every(isAnswer)) return null;
  const unanswered = Array.isArray(record.unanswered_question_indexes)
    ? record.unanswered_question_indexes.filter((index): index is number => Number.isInteger(index))
    : [];
  return {
    sourcePlanId: record.source_plan_id,
    sourceVersion: record.source_version as number,
    answeredAt: typeof record.answered_at === "string" ? record.answered_at : null,
    answeredByLabel: typeof record.answered_by_label === "string" && record.answered_by_label.trim()
      ? record.answered_by_label.trim()
      : null,
    answeredBy: typeof record.answered_by === "string" && record.answered_by ? record.answered_by : null,
    answers,
    unanswered,
  };
}

const REFUSALS: Record<string, string> = {
  stale_plan_version: "This version is no longer the newest one. Your answers are kept; reload and answer the newest version.",
  plan_not_open: "This version was decided or replaced. Your answers are kept; answer the newest open version.",
  plan_changed_during_generation:
    "This version changed while the revised plan was generated. Nothing was saved and your answers are kept.",
  plan_version_conflict: "Another version was saved at the same time. Nothing was saved and your answers are kept.",
  plan_generation_unavailable: "No model produced a revised plan. Nothing was saved and your answers are kept.",
};

export function clarificationErrorText(message: string): string {
  const match = /^([a-z_]+): (.*)$/s.exec(message.trim());
  if (!match) return `${message.trim().replace(/[.!?]+$/, "") || "The revised plan was not created"}. Your answers are kept.`;
  return REFUSALS[match[1]] || `${match[2]} Your answers are kept.`;
}
