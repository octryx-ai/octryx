// Answers to an exact Work Plan version's open questions. Pure helpers: which version can be
// answered, the exact request body, per-question validation without silent truncation, the answers
// a revised version retains in its evidence, and readable refusal text.
//
// Backend contract (`POST /api/v1/secure-work/change-plans/{id}/clarification-answers`):
// - only the newest version, while open, can be answered, and only with `expected_latest_version`
//   equal to that version;
// - each answer repeats its question's index and exact text; partial answers are allowed, at least
//   one is required. No content limits (no artificial limits): the server only
//   guards transport, at most 1000 answers per request and 100000 characters per answer;
// - refusals are `"<code>: <message>"` strings in `detail`.
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
  // Request-wide problems (answer count); each is actionable, nothing is cut.
  totalError: string | null;
  // The request body, or null when nothing is answered or any field is invalid.
  payload: { expected_latest_version: number; answers: ClarificationAnswer[] } | null;
};

export type RetainedClarification = {
  sourcePlanId: string;
  sourceVersion: number;
  answeredAt: string | null;
  // The actor's name as recorded when answering, else null; the id is the recorded detail.
  answeredByLabel: string | null;
  answeredBy: string | null;
  answers: ClarificationAnswer[];
  unanswered: number[];
};

// Answerable: the newest version of the item, still open, with questions. Older or decided versions
// keep their questions read-only.
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

// The answers a revised version was generated from, or null when the plan carries none (or a
// malformed record, which is not shown as if it were complete).
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

// Readable text for a refusal; unknown messages are shown as they are, without the code prefix.
export function clarificationErrorText(message: string): string {
  const match = /^([a-z_]+): (.*)$/s.exec(message.trim());
  if (!match) return `${message.trim().replace(/[.!?]+$/, "") || "The revised plan was not created"}. Your answers are kept.`;
  return REFUSALS[match[1]] || `${match[2]} Your answers are kept.`;
}
